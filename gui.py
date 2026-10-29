"""Графическая оболочка эмулятора (tkinter).

    python gui.py
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import isa
from assembler import AsmError, Assembler
from cpu import CPU, CPUError, STAGE_NAMES, WB

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = {"Задание 1: максимум": os.path.join(HERE, "programs", "max.asm"),
            "Задание 2: свертка": os.path.join(HERE, "programs", "conv.asm")}
DATA_ROWS = 64
MONO = ("Consolas", 10)
HL = "#fff2a8"      # подсветка изменившихся значений
CUR = "#cde8ff"     # подсветка текущей команды


class EmulatorGUI:
    def __init__(self, root):
        self.root = root
        self.cpu = CPU()
        self.labels = {}
        self.prev = None
        root.title("Эмулятор трехадресного процессора (гарвардская архитектура) - вариант 15")
        root.geometry("1500x900")
        self._build()
        self.load_example(next(iter(EXAMPLES)))

    # -------------------------------------------------------------- разметка
    def _build(self):
        bar = ttk.Frame(self.root, padding=4)
        bar.pack(fill="x")
        self.example = tk.StringVar(value=next(iter(EXAMPLES)))
        ttk.Label(bar, text="Пример:").pack(side="left")
        cb = ttk.Combobox(bar, textvariable=self.example, values=list(EXAMPLES),
                          state="readonly", width=22)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.load_example(self.example.get()))
        for text, cmd in (("Открыть .asm", self.open_file), ("Сохранить .asm", self.save_file),
                          ("Ассемблировать и загрузить", self.assemble),
                          ("Такт (стадия)", self.do_stage), ("Шаг (команда)", self.do_step),
                          ("Выполнить до HLT", self.do_run), ("Сброс", self.do_reset)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)

        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True)

        # ---- левая колонка: редактор ассемблера
        left = ttk.Labelframe(main, text="Программа на ассемблере", padding=4)
        self.editor = tk.Text(left, width=52, font=MONO, undo=True, wrap="none")
        self.editor.pack(fill="both", expand=True)
        self.status = ttk.Label(left, text="", foreground="#a00000", wraplength=380)
        self.status.pack(fill="x")
        main.add(left, weight=3)

        # ---- средняя колонка: регистры
        mid = ttk.Frame(main, padding=4)
        main.add(mid, weight=4)

        irf = ttk.Labelframe(mid, text="Регистр команд (IR, 32 бита)", padding=4)
        irf.pack(fill="x")
        self.ir_hex = ttk.Label(irf, font=MONO)
        self.ir_hex.pack(anchor="w")
        self.ir_bin = ttk.Label(irf, font=MONO)
        self.ir_bin.pack(anchor="w")
        self.ir_asm = ttk.Label(irf, font=(MONO[0], 12, "bold"))
        self.ir_asm.pack(anchor="w")
        self.fields = ttk.Treeview(irf, columns=("bits", "val", "mean"), height=5)
        for col, title, w in (("#0", "Поле", 60), ("bits", "Биты", 70),
                              ("val", "Значение", 150), ("mean", "Смысл", 260)):
            self.fields.heading(col, text=title)
            self.fields.column(col, width=w, stretch=col == "mean")
        self.fields.pack(fill="x", pady=2)

        sp = ttk.Labelframe(mid, text="Регистры специального назначения", padding=4)
        sp.pack(fill="x", pady=4)
        self.pc_lbl = ttk.Label(sp, font=MONO)
        self.pc_lbl.grid(row=0, column=0, sticky="w", columnspan=3)
        self.flag_lbls = {}
        for i, (f, title) in enumerate((("zf", "ZF (нуль)"), ("sf", "SF (знак)"),
                                        ("cf", "CF (перенос/заем)"))):
            lbl = tk.Label(sp, font=MONO, relief="groove", padx=6)
            lbl.grid(row=1, column=i, sticky="w", padx=2, pady=2)
            self.flag_lbls[f] = (lbl, title)
        self.counters = ttk.Label(sp, font=MONO)
        self.counters.grid(row=2, column=0, columnspan=3, sticky="w")

        st = ttk.Labelframe(mid, text="Стадии исполнения команды", padding=4)
        st.pack(fill="x")
        self.stage_lbls = []
        for i, name in enumerate(STAGE_NAMES):
            lbl = tk.Label(st, text=name, relief="ridge", padx=4, pady=2)
            lbl.grid(row=0, column=i, padx=1, sticky="ew")
            self.stage_lbls.append(lbl)
        self.latch = ttk.Label(st, font=MONO)
        self.latch.grid(row=1, column=0, columnspan=5, sticky="w", pady=2)

        rf = ttk.Labelframe(mid, text="Регистры общего назначения (16 x 16 бит)", padding=4)
        rf.pack(fill="x", pady=4)
        self.reg_lbls = []
        for i in range(isa.REG_COUNT):
            lbl = tk.Label(rf, font=MONO, anchor="w", width=24, relief="groove")
            lbl.grid(row=i % 8, column=i // 8, padx=2, pady=1)
            self.reg_lbls.append(lbl)

        lf = ttk.Labelframe(mid, text="Журнал: изменения после каждой команды", padding=4)
        lf.pack(fill="both", expand=True)
        self.log = tk.Text(lf, height=10, font=(MONO[0], 9), state="disabled")
        self.log.pack(fill="both", expand=True)

        # ---- правая колонка: память
        right = ttk.Frame(main, padding=4)
        main.add(right, weight=3)
        pf = ttk.Labelframe(right, text="Память команд (256 x 32 бита)", padding=4)
        pf.pack(fill="both", expand=True)
        self.pmem = ttk.Treeview(pf, columns=("code", "asm"), height=14)
        for col, title, w in (("#0", "Адрес", 55), ("code", "Код", 95), ("asm", "Ассемблер", 190)):
            self.pmem.heading(col, text=title)
            self.pmem.column(col, width=w)
        self.pmem.tag_configure("cur", background=CUR)
        self.pmem.pack(fill="both", expand=True)

        df = ttk.Labelframe(right, text=f"Память данных (1024 x 16 бит, ячейки 0..{DATA_ROWS - 1})",
                            padding=4)
        df.pack(fill="both", expand=True, pady=4)
        self.dmem = ttk.Treeview(df, columns=("dec", "hex", "lab"), height=14)
        for col, title, w in (("#0", "Адрес", 55), ("dec", "Значение", 80),
                              ("hex", "HEX", 70), ("lab", "Метка", 70)):
            self.dmem.heading(col, text=title)
            self.dmem.column(col, width=w)
        self.dmem.tag_configure("chg", background=HL)
        sb = ttk.Scrollbar(df, command=self.dmem.yview)
        self.dmem.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.dmem.pack(fill="both", expand=True)

    # ------------------------------------------------------------ программы
    def load_example(self, name):
        with open(EXAMPLES[name], encoding="utf-8") as f:
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", f.read())
        self.assemble()

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("Ассемблер", "*.asm"), ("Все", "*.*")])
        if path:
            with open(path, encoding="utf-8") as f:
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", f.read())
            self.assemble()

    def save_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".asm")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.get("1.0", "end-1c"))

    def assemble(self):
        asm = Assembler()
        try:
            program, data, _ = asm.assemble(self.editor.get("1.0", "end-1c"))
        except AsmError as e:
            self.status.config(text=f"Ошибка ассемблирования. {e}", foreground="#a00000")
            self.editor.tag_remove("err", "1.0", "end")
            self.editor.tag_add("err", f"{e.line_no}.0", f"{e.line_no}.end")
            self.editor.tag_config("err", background="#ffc8c8")
            return
        self.editor.tag_remove("err", "1.0", "end")
        self.labels = {asm.labels[k]: k for k in asm.data_labels}
        self.program_len = len(program)
        self.cpu.load(program, data)
        self.status.config(text=f"Загружено: {len(program)} команд, {len(data)} слов данных.",
                           foreground="#006000")
        self._clear_log()
        self.prev = self.cpu.snapshot()
        self.refresh()

    # ------------------------------------------------------------ управление
    def _guard(self, action):
        try:
            action()
        except CPUError as e:
            messagebox.showerror("Ошибка исполнения", str(e))
        self.refresh()

    def do_stage(self):
        def act():
            if self.cpu.stage == 0:
                self.prev = self.cpu.snapshot()
            done = self.cpu.step_stage()
            if done == WB:
                self._append_log()
        self._guard(act)

    def do_step(self):
        def act():
            if self.cpu.stage == 0:
                self.prev = self.cpu.snapshot()
            self.cpu.step()
            self._append_log()
        self._guard(act)

    def do_run(self):
        def act():
            while not self.cpu.halted:
                if self.cpu.instr_count > 10000:
                    raise CPUError("превышен лимит 10000 команд")
                self.prev = self.cpu.snapshot()
                self.cpu.step()
                self._append_log()
        self._guard(act)

    def do_reset(self):
        self.assemble()

    # ------------------------------------------------------------ отображение
    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _append_log(self):
        if not self.cpu.log:
            return
        addr, word, asm, ch = self.cpu.log[-1]
        self.log.config(state="normal")
        self.log.insert("end", f"#{len(self.cpu.log):<3} [{addr:3}] {word:08X} {asm:<18} "
                               f"{'; '.join(ch) if ch else '-'}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    @staticmethod
    def _ra_meaning(opc, ra):
        if opc == isa.MOVS:
            return f"R{ra}: источник данных для записи в ОЗУ"
        if opc == isa.MOVL or (opc in isa.ALU_OPS and opc != isa.CMP):
            return f"R{ra}: приемник результата"
        return "не используется"

    def refresh(self):
        cpu = self.cpu
        word = cpu.ir
        opc, mode, ra, rb, op3 = isa.decode(word)
        self.ir_hex.config(text=f"HEX: 0x{word:08X}")
        self.ir_bin.config(text=f"BIN: {isa.fields_bin(word)}  (OPC_MODE_RA_RB_OP3)")
        self.ir_asm.config(text=f"ASM: {isa.disassemble(word)}")
        self.fields.delete(*self.fields.get_children())
        rows = (("OPC", "31-26", f"0x{opc:02X} ({opc:06b})", isa.OPC_NAMES.get(opc, "?")),
                ("MODE", "25-24", f"{mode:02b}", f"адресация OP3: {isa.MODE_NAMES[mode]}"),
                ("RA", "23-20", f"{ra} ({ra:04b})", self._ra_meaning(opc, ra)),
                ("RB", "19-16", f"{rb} ({rb:04b})",
                 f"R{rb}: первый операнд АЛУ" if opc in isa.ALU_OPS else "не используется"),
                ("OP3", "15-0", f"{op3} (0x{op3:04X})",
                 f"адрес перехода {op3}" if opc in isa.JUMP_OPS
                 else "не используется" if opc in (isa.NOP, isa.HLT)
                 else isa.fmt_op3(mode, op3)))
        for r in rows:
            self.fields.insert("", "end", text=r[0], values=r[1:])

        self.pc_lbl.config(text=f"PC (счетчик команд, 8 бит) = {cpu.pc}    "
                                f"{'ОСТАНОВ (HLT)' if cpu.halted else ''}")
        for f, (lbl, title) in self.flag_lbls.items():
            v = getattr(cpu, f)
            lbl.config(text=f"{title} = {v}", bg="#b8f0b8" if v else "#eeeeee")
        self.counters.config(text=f"Выполнено команд: {cpu.instr_count}   тактов: {cpu.cycles}")
        last = (cpu.stage - 1) % 5 if cpu.cycles else None
        for i, lbl in enumerate(self.stage_lbls):
            lbl.config(bg="#ffd27f" if i == last else "#eeeeee")
        show = lambda v: "-" if v is None else str(v)
        self.latch.config(text=f"A={show(cpu.op_a)}  B={show(cpu.op_b)}  EA={show(cpu.ea)}  "
                               f"ALU={show(cpu.alu)}  MDR={show(cpu.mdr)}  "
                               f"переход={'да' if cpu.branch else 'нет'}")

        prev = self.prev or cpu.snapshot()
        for i, lbl in enumerate(self.reg_lbls):
            v = cpu.reg[i]
            lbl.config(text=f"R{i:<2} = {v:>5}  (0x{v:04X})",
                       bg=HL if v != prev["R"][i] else "#ffffff")

        self.pmem.delete(*self.pmem.get_children())
        cur = cpu._addr if cpu.stage != 0 and cpu.cycles else cpu.pc
        for a in range(max(self.program_len, 1)):
            w = cpu.prog_mem[a]
            self.pmem.insert("", "end", text=str(a), values=(f"{w:08X}", isa.disassemble(w)),
                             tags=("cur",) if a == cur else ())
        self.dmem.delete(*self.dmem.get_children())
        for a in range(DATA_ROWS):
            v = cpu.data_mem[a]
            self.dmem.insert("", "end", text=str(a),
                             values=(v, f"{v:04X}", self.labels.get(a, "")),
                             tags=("chg",) if v != prev["D"][a] else ())


def main():
    root = tk.Tk()
    EmulatorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
