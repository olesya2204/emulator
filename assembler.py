"""Двухпроходный ассемблер: текст программы -> машинные коды памяти команд
и начальное содержимое памяти данных.

Синтаксис строки:   [МЕТКА:] [МНЕМОНИКА операнд, операнд, ...] [; комментарий]
Директивы:  .data [адрес] - секция данных (с указанного адреса ОЗУ данных)
            .code         - секция команд
            .word a, b, … - разместить 16-битные слова в памяти данных
Операнды:   R5     - регистровая адресация
            25, 0x1F, ARR, ARR+3 - непосредственная (число или адрес метки)
            [25], [ARR+1]        - прямая адресация
            [R1]                 - косвенно-регистровая адресация
"""
import re

import isa

REG_RE = re.compile(r"^R(\d{1,2})$", re.I)
LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class AsmError(Exception):
    def __init__(self, line_no, msg):
        super().__init__(f"Строка {line_no}: {msg}")
        self.line_no = line_no


ALU3 = {"ADD": isa.ADD, "ADC": isa.ADC, "SUB": isa.SUB, "SBB": isa.SBB,
        "MUL": isa.MUL, "MULH": isa.MULH}
JUMPS = {"JMP": isa.JMP, "JZ": isa.JZ, "JNZ": isa.JNZ, "JC": isa.JC, "JNC": isa.JNC}
MNEMONICS = set(ALU3) | set(JUMPS) | {"NOP", "HLT", "MOV", "CMP"}


def _split_operands(text):
    return [op.strip() for op in text.split(",")] if text.strip() else []


def _parse_reg(tok):
    m = REG_RE.match(tok)
    if not m:
        return None
    n = int(m.group(1))
    return n if n < isa.REG_COUNT else None


class Assembler:
    def __init__(self):
        self.labels = {}
        self.data_labels = set()     # метки памяти данных (остальные - метки команд)

    # ------------------------------------------------------------ выражения
    def _value(self, expr, line_no):
        """Число, метка или метка±число."""
        expr = expr.replace(" ", "")
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)?([+-]?)(0x[0-9A-Fa-f]+|\d+)?$", expr)
        if not m or expr == "" or (m.group(1) and m.group(2) == "" and m.group(3)):
            raise AsmError(line_no, f"неверное выражение '{expr}'")
        label, sign, num = m.groups()
        value = 0
        if label:
            if label.upper() not in self.labels:
                raise AsmError(line_no, f"неизвестная метка '{label}'")
            value = self.labels[label.upper()]
        if num:
            n = int(num, 0)
            value = value - n if sign == "-" else value + n
        elif sign:
            raise AsmError(line_no, f"неверное выражение '{expr}'")
        return value

    def _operand(self, tok, line_no):
        """Операнд -> (тип адресации, значение поля OP3)."""
        reg = _parse_reg(tok)
        if reg is not None:
            return isa.M_REG, reg
        if tok.startswith("[") and tok.endswith("]"):
            inner = tok[1:-1].strip()
            reg = _parse_reg(inner)
            if reg is not None:
                return isa.M_IND, reg
            addr = self._value(inner, line_no)
            if not 0 <= addr < isa.DATA_MEM_SIZE:
                raise AsmError(line_no, f"адрес {addr} вне памяти данных")
            return isa.M_DIR, addr
        value = self._value(tok, line_no)
        if not -32768 <= value <= 0xFFFF:
            raise AsmError(line_no, f"константа {value} не помещается в 16 бит")
        return isa.M_IMM, value & 0xFFFF

    def _need_reg(self, tok, line_no):
        reg = _parse_reg(tok)
        if reg is None:
            raise AsmError(line_no, f"ожидался регистр R0..R15, получено '{tok}'")
        return reg

    # ---------------------------------------------------------------- проходы
    def _lines(self, text):
        for no, raw in enumerate(text.splitlines(), 1):
            line = raw.split(";", 1)[0].strip()
            labels = []
            while True:
                m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:(.*)$", line)
                if not m:
                    break
                labels.append(m.group(1).upper())
                line = m.group(2).strip()
            yield no, labels, line

    def assemble(self, text):
        """Возвращает (program, data, listing).
        program - список 32-битных слов; data - словарь {адрес: слово};
        listing - список (адрес, машинный код, исходная строка)."""
        self.labels = {}
        self.data_labels = set()
        # ---- 1-й проход: адреса меток
        section, pc, dp = "code", 0, 0
        for no, labels, line in self._lines(text):
            for lab in labels:
                if lab in self.labels:
                    raise AsmError(no, f"метка '{lab}' объявлена повторно")
                if lab in MNEMONICS or _parse_reg(lab) is not None:
                    raise AsmError(no, f"недопустимое имя метки '{lab}'")
                self.labels[lab] = pc if section == "code" else dp
                if section == "data":
                    self.data_labels.add(lab)
            if not line:
                continue
            head, _, rest = line.partition(" ")
            head = head.lower()
            if head == ".data":
                section = "data"
                if rest.strip():
                    dp = int(rest.strip(), 0)
            elif head == ".code":
                section = "code"
            elif head == ".word":
                if section != "data":
                    raise AsmError(no, ".word допустима только в секции .data")
                dp += len(_split_operands(rest))
            elif section == "code":
                pc += 1
            else:
                raise AsmError(no, "команда в секции данных")

        # ---- 2-й проход: генерация кода
        program, data, listing = [], {}, []
        section, dp = "code", 0
        for no, labels, line in self._lines(text):
            if not line:
                continue
            head, _, rest = line.partition(" ")
            if head.lower() == ".data":
                section = "data"
                if rest.strip():
                    dp = int(rest.strip(), 0)
                continue
            if head.lower() == ".code":
                section = "code"
                continue
            if head.lower() == ".word":
                for tok in _split_operands(rest):
                    if not 0 <= dp < isa.DATA_MEM_SIZE:
                        raise AsmError(no, "данные вне памяти данных")
                    data[dp] = self._value(tok, no) & isa.WORD_MASK
                    dp += 1
                continue
            word = self._instruction(head.upper(), _split_operands(rest), no)
            if len(program) >= isa.PROG_MEM_SIZE:
                raise AsmError(no, "программа не помещается в память команд")
            listing.append((len(program), word, line))
            program.append(word)
        return program, data, listing

    def _instruction(self, mnem, ops, no):
        def count(n):
            if len(ops) != n:
                raise AsmError(no, f"{mnem}: ожидалось операндов {n}, получено {len(ops)}")

        if mnem in ("NOP", "HLT"):
            count(0)
            return isa.encode(isa.NOP if mnem == "NOP" else isa.HLT)
        if mnem == "MOV":
            count(2)
            dst, src = ops
            if _parse_reg(dst) is not None:                 # загрузка в регистр
                mode, op3 = self._operand(src, no)
                return isa.encode(isa.MOVL, mode, _parse_reg(dst), 0, op3)
            mode, op3 = self._operand(dst, no)              # сохранение в ОЗУ
            if mode not in isa.MEM_MODES:
                raise AsmError(no, "MOV: приемник должен быть регистром или ячейкой памяти")
            return isa.encode(isa.MOVS, mode, self._need_reg(src, no), 0, op3)
        if mnem in ALU3 or mnem == "CMP":
            if mnem == "CMP":
                count(2)
                ra, rb, src = 0, self._need_reg(ops[0], no), ops[1]
                opc = isa.CMP
            else:
                count(3)
                ra, rb, src = self._need_reg(ops[0], no), self._need_reg(ops[1], no), ops[2]
                opc = ALU3[mnem]
            mode, op3 = self._operand(src, no)
            if mode in isa.MEM_MODES:
                raise AsmError(no, f"{mnem}: по принципу RISC операнды АЛУ - только "
                                   "регистры или константы (к ОЗУ обращается только MOV)")
            return isa.encode(opc, mode, ra, rb, op3)
        if mnem in JUMPS:
            count(1)
            addr = self._value(ops[0], no)
            if not 0 <= addr < isa.PROG_MEM_SIZE:
                raise AsmError(no, f"адрес перехода {addr} вне памяти команд")
            return isa.encode(JUMPS[mnem], isa.M_IMM, 0, 0, addr)
        raise AsmError(no, f"неизвестная команда '{mnem}'")


def assemble(text):
    return Assembler().assemble(text)
