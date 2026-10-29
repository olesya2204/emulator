"""Система команд трехадресного процессора гарвардской архитектуры (вариант 15).

Формат команды (32 бита, все команды одного формата):

    31      26 25  24 23    20 19    16 15                 0
   +----------+------+--------+--------+--------------------+
   |   OPC    | MODE |   RA   |   RB   |        OP3         |
   +----------+------+--------+--------+--------------------+
      6 бит    2 бит   4 бита   4 бита        16 бит

OPC  - код операции;
MODE - тип адресации третьего операнда (OP3);
RA   - номер регистра-приемника (для MOV-сохранения - регистр-источник);
RB   - номер регистра первого операнда-источника;
OP3  - второй операнд-источник: номер регистра, константа или адрес.
"""

# ---------------------------------------------------------------- размерности
WORD_BITS = 16                      # разрядность данных, регистров и ячеек ОЗУ данных
WORD_MASK = (1 << WORD_BITS) - 1
CMD_BITS = 32                       # разрядность команды и ячейки памяти команд
REG_COUNT = 16                      # R0..R15
PROG_MEM_SIZE = 256                 # ячеек памяти команд (адрес 8 бит)
DATA_MEM_SIZE = 1024                # ячеек памяти данных (адрес 10 бит)

# ------------------------------------------------------------ типы адресации
M_REG, M_IMM, M_DIR, M_IND = range(4)
MODE_NAMES = {
    M_REG: "регистровая",
    M_IMM: "непосредственная",
    M_DIR: "прямая",
    M_IND: "косвенно-регистровая",
}

# ------------------------------------------------------------- коды операций
NOP = 0x00
MOVL = 0x01     # MOV Ra, op3   - загрузка в регистр (все 4 типа адресации)
MOVS = 0x02     # MOV op3, Ra   - сохранение в ОЗУ (прямая, косвенно-регистровая)
ADD = 0x03
ADC = 0x04
SUB = 0x05
SBB = 0x06
MUL = 0x07      # младшие 16 бит произведения
MULH = 0x08     # старшие 16 бит произведения (без знака)
CMP = 0x09
JMP = 0x10
JZ = 0x11
JNZ = 0x12
JC = 0x13
JNC = 0x14
HLT = 0x3F

# мнемоника, используемая в дизассемблере
OPC_NAMES = {
    NOP: "NOP", MOVL: "MOV", MOVS: "MOV", ADD: "ADD", ADC: "ADC", SUB: "SUB",
    SBB: "SBB", MUL: "MUL", MULH: "MULH", CMP: "CMP", JMP: "JMP", JZ: "JZ",
    JNZ: "JNZ", JC: "JC", JNC: "JNC", HLT: "HLT",
}

ALU_OPS = {ADD, ADC, SUB, SBB, MUL, MULH, CMP}
JUMP_OPS = {JMP, JZ, JNZ, JC, JNC}
MEM_MODES = {M_DIR, M_IND}


def encode(opc, mode=0, ra=0, rb=0, op3=0):
    """Собрать машинное слово из полей."""
    return ((opc & 0x3F) << 26) | ((mode & 0x3) << 24) | ((ra & 0xF) << 20) \
        | ((rb & 0xF) << 16) | (op3 & 0xFFFF)


def decode(word):
    """Разобрать машинное слово на поля: (OPC, MODE, RA, RB, OP3)."""
    return ((word >> 26) & 0x3F, (word >> 24) & 0x3, (word >> 20) & 0xF,
            (word >> 16) & 0xF, word & 0xFFFF)


def fmt_op3(mode, op3):
    if mode == M_REG:
        return f"R{op3 & 0xF}"
    if mode == M_IMM:
        return str(op3)
    if mode == M_DIR:
        return f"[{op3}]"
    return f"[R{op3 & 0xF}]"


def disassemble(word):
    """Ассемблерное представление машинной команды."""
    opc, mode, ra, rb, op3 = decode(word)
    name = OPC_NAMES.get(opc, f"??{opc:02X}")
    if opc in (NOP, HLT):
        return name
    if opc == MOVL:
        return f"MOV R{ra}, {fmt_op3(mode, op3)}"
    if opc == MOVS:
        return f"MOV {fmt_op3(mode, op3)}, R{ra}"
    if opc == CMP:
        return f"CMP R{rb}, {fmt_op3(mode, op3)}"
    if opc in ALU_OPS:
        return f"{name} R{ra}, R{rb}, {fmt_op3(mode, op3)}"
    if opc in JUMP_OPS:
        return f"{name} {op3}"
    return name


def fields_bin(word):
    """Двоичная запись команды с разделением на поля."""
    b = f"{word:032b}"
    return f"{b[0:6]}_{b[6:8]}_{b[8:12]}_{b[12:16]}_{b[16:32]}"
