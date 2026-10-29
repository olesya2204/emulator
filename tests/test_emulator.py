"""Автотесты эмулятора: python -m unittest discover -s tests"""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import isa  # noqa: E402
from assembler import AsmError, Assembler  # noqa: E402
from cpu import CPU  # noqa: E402


def run(text):
    asm = Assembler()
    program, data, _ = asm.assemble(text)
    cpu = CPU()
    cpu.load(program, data)
    cpu.run()
    return cpu, asm.labels


def read(name):
    with open(os.path.join(ROOT, "programs", name), encoding="utf-8") as f:
        return f.read()


def with_data(src, label, values):
    """Подменить строку .word у метки на свои данные."""
    lines = []
    for line in src.splitlines():
        if line.startswith(label + ":"):
            line = f"{label}: .word " + ", ".join(map(str, values))
        lines.append(line)
    return "\n".join(lines)


class TestEncoding(unittest.TestCase):
    def test_roundtrip(self):
        w = isa.encode(isa.ADD, isa.M_IMM, 5, 7, 1234)
        self.assertEqual(isa.decode(w), (isa.ADD, isa.M_IMM, 5, 7, 1234))
        self.assertEqual(isa.disassemble(w), "ADD R5, R7, 1234")

    def test_addressing_modes(self):
        asm = Assembler()
        prog, _, _ = asm.assemble("MOV R1, R2\nMOV R1, 5\nMOV R1, [5]\nMOV R1, [R2]\nMOV [R3], R4")
        modes = [isa.decode(w)[1] for w in prog]
        self.assertEqual(modes, [isa.M_REG, isa.M_IMM, isa.M_DIR, isa.M_IND, isa.M_IND])
        self.assertEqual(isa.decode(prog[4])[0], isa.MOVS)

    def test_risc_restriction(self):
        with self.assertRaises(AsmError):
            Assembler().assemble("ADD R1, R2, [R3]")

    def test_errors(self):
        for bad in ("FOO R1", "ADD R1, R2", "JMP NOWHERE", "MOV R16, 1", "MOV 5, R1"):
            with self.assertRaises(AsmError, msg=bad):
                Assembler().assemble(bad)


class TestFlags(unittest.TestCase):
    def test_add_carry_and_sub_borrow(self):
        cpu, _ = run("MOV R1, 65535\nADD R2, R1, 1\nHLT")
        self.assertEqual((cpu.reg[2], cpu.zf, cpu.cf), (0, 1, 1))
        cpu, _ = run("MOV R1, 3\nSUB R2, R1, 5\nHLT")
        self.assertEqual((cpu.reg[2], cpu.cf, cpu.sf), (65534, 1, 1))

    def test_mul(self):
        cpu, _ = run("MOV R1, 65535\nMUL R2, R1, R1\nMULH R3, R1, R1\nHLT")
        self.assertEqual(cpu.reg[3] << 16 | cpu.reg[2], 65535 * 65535)

    def test_five_stages(self):
        cpu, _ = run("NOP\nHLT")
        self.assertEqual(cpu.cycles, 10)


class TestPrograms(unittest.TestCase):
    def test_max_default(self):
        cpu, lab = run(read("max.asm"))
        self.assertEqual(cpu.data_mem[lab["MAX"]], 65000)

    def test_max_random(self):
        rnd = random.Random(1)
        src = read("max.asm")
        for n in (1, 2, 6, 15):
            arr = [rnd.randrange(65536) for _ in range(n)]
            cpu, lab = run(with_data(src, "ARR", [n] + arr))
            self.assertEqual(cpu.data_mem[lab["MAX"]], max(arr))

    def test_conv_default(self):
        cpu, lab = run(read("conv.asm"))
        s = lab["S"]
        res = cpu.data_mem[s] | cpu.data_mem[s + 1] << 16 | cpu.data_mem[s + 2] << 32
        a = [50000, 40000, 65535, 1234, 30000, 7]
        b = [60000, 3, 65535, 20000, 45000, 9]
        self.assertEqual(res, sum(x * y for x, y in zip(a, b)))

    def test_conv_max_values(self):
        src = with_data(with_data(read("conv.asm"), "A", [6] + [65535] * 6), "B", [6] + [65535] * 6)
        cpu, lab = run(src)
        s = lab["S"]
        res = cpu.data_mem[s] | cpu.data_mem[s + 1] << 16 | cpu.data_mem[s + 2] << 32
        self.assertEqual(res, 6 * 65535 * 65535)


if __name__ == "__main__":
    unittest.main()
