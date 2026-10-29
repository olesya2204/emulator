"""Консольный запуск эмулятора.

    python main.py                      - выполнить обе встроенные программы
    python main.py programs/max.asm     - выполнить программу из файла
    python main.py prog.asm --stages    - подробный вывод каждой стадии
"""
import argparse
import os
import sys

import isa
from assembler import AsmError, Assembler
from cpu import CPU, CPUError, STAGE_NAMES

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROGRAMS = [os.path.join(HERE, "programs", "max.asm"),
                    os.path.join(HERE, "programs", "conv.asm")]


def print_fields(word):
    opc, mode, ra, rb, op3 = isa.decode(word)
    print(f"    IR = 0x{word:08X} = {isa.fields_bin(word)}   ({isa.disassemble(word)})")
    print(f"    поля: OPC=0x{opc:02X} ({isa.OPC_NAMES.get(opc, '?')}), "
          f"MODE={mode:02b} ({isa.MODE_NAMES[mode]}), RA=R{ra}, RB=R{rb}, OP3={op3}")


def print_state(cpu):
    regs = "  ".join(f"R{i}={v}" for i, v in enumerate(cpu.reg))
    print(f"    PC={cpu.pc}  {cpu.flags_str()}")
    print(f"    {regs}")


def run_file(path, stages=False):
    print("=" * 78)
    print(f"Программа: {os.path.basename(path)}")
    print("=" * 78)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        assembler = Assembler()
        program, data, listing = assembler.assemble(text)
    except AsmError as e:
        print(f"Ошибка ассемблирования: {e}")
        return None, {}

    print("Память команд (адрес: машинный код | поля | ассемблер):")
    for addr, word, _ in listing:
        print(f"  {addr:3}: 0x{word:08X} | {isa.fields_bin(word)} | {isa.disassemble(word)}")
    used = sorted(data)
    print("Память данных (начальное состояние):")
    print("  " + ", ".join(f"[{a}]={data[a]}" for a in used))

    cpu = CPU()
    cpu.load(program, data)
    print("\nВыполнение (изменения после каждой команды):")
    try:
        while not cpu.halted:
            if stages:
                done = cpu.step_stage()
                show = lambda v: "-" if v is None else v
                print(f"  -- {STAGE_NAMES[done]}: PC={cpu.pc} A={show(cpu.op_a)} "
                      f"B={show(cpu.op_b)} EA={show(cpu.ea)} ALU={show(cpu.alu)} "
                      f"MDR={show(cpu.mdr)}")
                if done != 4:
                    continue
            else:
                cpu.step()
            addr, word, asm, changes = cpu.log[-1]
            print(f"#{cpu.instr_count:<3} [{addr:3}] 0x{word:08X}  {asm:<20} "
                  f"{'; '.join(changes) if changes else '-'}")
            if cpu.instr_count > 10000:
                raise CPUError("слишком много команд")
    except CPUError as e:
        print(f"Ошибка исполнения: {e}")
        return cpu, assembler.labels

    print("\nИтоговое состояние:")
    print_fields(cpu.ir)
    print_state(cpu)
    print(f"    выполнено команд: {cpu.instr_count}, тактов (стадий): {cpu.cycles}")
    print("    память данных: " + ", ".join(f"[{a}]={cpu.data_mem[a]}"
                                             for a in range(max(used) + 1)))
    return cpu, assembler.labels


def main():
    ap = argparse.ArgumentParser(description="Эмулятор трехадресного процессора "
                                             "гарвардской архитектуры (вариант 15)")
    ap.add_argument("files", nargs="*", help="файлы программ на ассемблере")
    ap.add_argument("--stages", action="store_true", help="выводить каждую стадию")
    args = ap.parse_args()
    for path in args.files or DEFAULT_PROGRAMS:
        cpu, labels = run_file(path, args.stages)
        if cpu and cpu.halted and "MAX" in labels:
            print(f"\n>>> Максимум массива: MAX = {cpu.data_mem[labels['MAX']]}")
        if cpu and cpu.halted and "S" in labels:
            s0, s1, s2 = cpu.data_mem[labels["S"]:labels["S"] + 3]
            print(f"\n>>> Свертка S = S2:S1:S0 = {s2}:{s1}:{s0} = {s0 | s1 << 16 | s2 << 32}")
        print()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
