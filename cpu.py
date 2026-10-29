"""Модель процессора: трехадресный, гарвардская архитектура, 5 стадий исполнения.

Стадии каждой команды (выполняются последовательно, без конвейера):
    IF  (FETCH)     - выборка команды из памяти команд в регистр команд
    ID  (DECODE)    - дешифрация полей, чтение регистров, расчет исполнительного адреса
    EX  (EXECUTE)   - операция АЛУ / проверка условия перехода
    MEM (MEMORY)    - обращение к памяти данных (только MOV с ОЗУ)
    WB  (WRITEBACK) - запись результата в регистр, флагов и нового PC
"""
import isa

IF, ID, EX, MEM, WB = range(5)
STAGE_NAMES = ["IF (выборка)", "ID (дешифрация)", "EX (исполнение)",
               "MEM (память)", "WB (запись)"]


class CPUError(Exception):
    pass


class CPU:
    def __init__(self):
        self.prog_mem = [0] * isa.PROG_MEM_SIZE
        self.data_mem = [0] * isa.DATA_MEM_SIZE
        self.reset()

    # ------------------------------------------------------------- загрузка
    def load(self, program, data):
        self.prog_mem = [0] * isa.PROG_MEM_SIZE
        self.data_mem = [0] * isa.DATA_MEM_SIZE
        for addr, word in enumerate(program):
            self.prog_mem[addr] = word
        for addr, value in data.items():
            self.data_mem[addr] = value
        self.reset()

    def reset(self):
        """Сброс регистров (память не меняется)."""
        self.reg = [0] * isa.REG_COUNT    # регистры общего назначения R0..R15
        self.pc = 0                       # счетчик команд (8 бит)
        self.ir = 0                       # регистр команды (32 бита)
        self.zf = self.sf = self.cf = 0   # флаги нуля, знака, переноса
        self.stage = IF                   # следующая стадия
        self.halted = False
        self.cycles = 0                   # выполнено тактов (стадий)
        self.instr_count = 0              # выполнено команд
        # внутренние (скрытые от программиста) регистры тракта данных
        self.f_opc = self.f_mode = self.f_ra = self.f_rb = self.f_op3 = 0
        self.op_a = self.op_b = None      # входы АЛУ
        self.ea = None                    # исполнительный адрес в ОЗУ данных
        self.alu = None                   # выход АЛУ
        self.mdr = None                   # регистр данных памяти
        self.new_flags = None
        self.branch = False
        self.log = []                     # журнал изменений по командам
        self._snap = None

    # ------------------------------------------------------------ состояние
    def flags_str(self):
        return f"ZF={self.zf} SF={self.sf} CF={self.cf}"

    def snapshot(self):
        return {"PC": self.pc, "IR": self.ir, "FLAGS": (self.zf, self.sf, self.cf),
                "R": list(self.reg), "D": list(self.data_mem)}

    def _diff(self, before, after):
        ch = []
        if before["PC"] != after["PC"]:
            ch.append(f"PC: {before['PC']} -> {after['PC']}")
        for i, (a, b) in enumerate(zip(before["R"], after["R"])):
            if a != b:
                ch.append(f"R{i}: {a} -> {b}")
        if before["FLAGS"] != after["FLAGS"]:
            ch.append("ZF,SF,CF: {} -> {}".format(
                "".join(map(str, before["FLAGS"])), "".join(map(str, after["FLAGS"]))))
        for i, (a, b) in enumerate(zip(before["D"], after["D"])):
            if a != b:
                ch.append(f"DM[{i}]: {a} -> {b}")
        return ch

    # --------------------------------------------------------------- стадии
    def _fetch(self):
        if not 0 <= self.pc < isa.PROG_MEM_SIZE:
            raise CPUError(f"PC={self.pc} вне памяти команд")
        self._snap = self.snapshot()
        self._addr = self.pc
        self.ir = self.prog_mem[self.pc]             # IR <- PM[PC]
        self.pc = (self.pc + 1) % isa.PROG_MEM_SIZE  # PC <- PC + 1
        self.op_a = self.op_b = self.ea = self.alu = self.mdr = None
        self.new_flags = None
        self.branch = False

    def _decode(self):
        opc, mode, ra, rb, op3 = isa.decode(self.ir)
        self.f_opc, self.f_mode, self.f_ra, self.f_rb, self.f_op3 = opc, mode, ra, rb, op3
        if opc not in isa.OPC_NAMES:
            raise CPUError(f"неизвестный код операции 0x{opc:02X}")
        # первый операнд - регистр RB (для сохранения - данные из RA)
        if opc in isa.ALU_OPS:
            self.op_a = self.reg[rb]
        elif opc == isa.MOVS:
            self.op_a = self.reg[ra]
        # второй операнд / исполнительный адрес по типу адресации
        if mode == isa.M_REG:
            self.op_b = self.reg[op3 & 0xF]
        elif mode == isa.M_IMM:
            self.op_b = op3
        elif mode == isa.M_DIR:
            self.ea = op3
        else:
            self.ea = self.reg[op3 & 0xF]
        if (opc in isa.ALU_OPS or opc in isa.JUMP_OPS) and mode in isa.MEM_MODES:
            raise CPUError("АЛУ и переходы не работают с операндами в ОЗУ")
        if opc == isa.MOVS and mode not in isa.MEM_MODES:
            raise CPUError("MOV в память: нужен адрес в ОЗУ")
        if self.ea is not None and not 0 <= self.ea < isa.DATA_MEM_SIZE:
            raise CPUError(f"адрес {self.ea} вне памяти данных")

    def _execute(self):
        opc, a, b = self.f_opc, self.op_a, self.op_b
        if opc in (isa.ADD, isa.ADC):
            full = a + b + (self.cf if opc == isa.ADC else 0)
            self.alu = full & isa.WORD_MASK
            self.new_flags = (self.alu == 0, self.alu >> 15, int(full > isa.WORD_MASK))
        elif opc in (isa.SUB, isa.SBB, isa.CMP):
            full = a - b - (self.cf if opc == isa.SBB else 0)
            self.alu = full & isa.WORD_MASK
            self.new_flags = (self.alu == 0, self.alu >> 15, int(full < 0))  # CF = заем
        elif opc == isa.MUL:
            self.alu = (a * b) & isa.WORD_MASK
        elif opc == isa.MULH:
            self.alu = (a * b) >> isa.WORD_BITS
        elif opc == isa.MOVL and self.f_mode in (isa.M_REG, isa.M_IMM):
            self.alu = b                                 # пересылка через АЛУ
        elif opc in isa.JUMP_OPS:
            self.branch = {isa.JMP: True, isa.JZ: self.zf == 1, isa.JNZ: self.zf == 0,
                           isa.JC: self.cf == 1, isa.JNC: self.cf == 0}[opc]

    def _memory(self):
        if self.f_opc == isa.MOVL and self.f_mode in isa.MEM_MODES:
            self.mdr = self.data_mem[self.ea]            # MDR <- DM[EA]
        elif self.f_opc == isa.MOVS:
            self.data_mem[self.ea] = self.op_a           # DM[EA] <- RA

    def _writeback(self):
        opc = self.f_opc
        if opc == isa.MOVL:
            self.reg[self.f_ra] = self.mdr if self.f_mode in isa.MEM_MODES else self.alu
        elif opc in isa.ALU_OPS and opc != isa.CMP:
            self.reg[self.f_ra] = self.alu
        if self.new_flags is not None:
            self.zf, self.sf, self.cf = (int(x) for x in self.new_flags)
        if self.branch:
            self.pc = self.f_op3 & (isa.PROG_MEM_SIZE - 1)   # PC <- адрес перехода
        if opc == isa.HLT:
            self.halted = True
        self.instr_count += 1
        self.log.append((self._addr, self.ir, isa.disassemble(self.ir),
                         self._diff(self._snap, self.snapshot())))

    # ----------------------------------------------------------- управление
    def step_stage(self):
        """Выполнить одну стадию (такт). Возвращает номер выполненной стадии."""
        if self.halted:
            return None
        done = self.stage
        [self._fetch, self._decode, self._execute, self._memory, self._writeback][done]()
        self.cycles += 1
        self.stage = (done + 1) % 5
        return done

    def step(self):
        """Выполнить команду целиком (до конца стадии WB)."""
        if self.halted:
            return
        while True:
            if self.step_stage() == WB:
                return

    def run(self, max_instr=10000):
        while not self.halted:
            if self.instr_count >= max_instr:
                raise CPUError(f"превышен лимит {max_instr} команд (зацикливание?)")
            self.step()
