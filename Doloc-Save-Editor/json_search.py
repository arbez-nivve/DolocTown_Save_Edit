"""Literal search over the live Tk text buffer; indexes stay Unicode-correct."""
import customtkinter as ctk


class JsonSearch(ctk.CTkFrame):
    def __init__(self, parent, textbox):
        super().__init__(parent, fg_color='transparent')
        self.text = textbox._textbox
        self.matches = []
        self.match_length = 0
        self.current = -1
        self.pending = None
        self.query = ctk.StringVar()
        self.case_sensitive = ctk.BooleanVar(value=False)
        self.status = ctk.StringVar(value='输入关键字搜索')
        self.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(self, textvariable=self.query, placeholder_text='搜索文字 / 字段 / ID  ·  Ctrl+F')
        self.entry.grid(row=0, column=0, sticky='ew', padx=(0, 8))
        ctk.CTkCheckBox(self, text='区分大小写', variable=self.case_sensitive,
                       width=116, command=self.refresh).grid(row=0, column=1, padx=4)
        ctk.CTkButton(self, text='上一处', width=66, command=lambda: self.move(-1)).grid(row=0, column=2, padx=4)
        ctk.CTkButton(self, text='下一处', width=66, command=self.move).grid(row=0, column=3, padx=4)
        ctk.CTkLabel(self, textvariable=self.status, width=120).grid(row=0, column=4, padx=4)
        self.entry.bind('<Return>', lambda e: self.move())
        self.entry.bind('<Shift-Return>', lambda e: self.move(-1))
        self.query.trace_add('write', lambda *_: self.schedule())
        self.text.tag_configure('search_current', background='#F6C85F', foreground='#172033')

    def focus(self):
        self.entry.focus_set()
        self.entry.select_range(0, 'end')
        return 'break'

    def schedule(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
        self.matches = []
        self.current = -1
        self.text.tag_remove('search_current', '1.0', 'end')
        self.pending = self.after(250, self.refresh)

    def refresh(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        self.text.tag_remove('search_current', '1.0', 'end')
        self.matches, self.current = [], -1
        query = self.query.get()
        if not query:
            self.status.set('输入关键字搜索')
            return
        # Native Tcl returns exact text indices, including Chinese/astral characters.
        args = [self.text._w, 'search', '-all', '-exact']
        if not self.case_sensitive.get():
            args.append('-nocase')
        result = self.text.tk.call(*args, '--', query, '1.0', 'end-1c')
        self.matches = list(self.text.tk.splitlist(result))
        # Tk search counts UTF-16 units, but index +Nc counts Unicode characters.
        # Literal search has the same character length as the query, even for emoji.
        self.match_length = len(query)
        self.move()

    def move(self, direction=1):
        if self.pending is not None:
            self.refresh()
            return 'break'
        if not self.matches:
            self.status.set('无匹配' if self.query.get() else '输入关键字搜索')
            return 'break'
        self.current = (self.current + direction) % len(self.matches)
        index = str(self.matches[self.current])
        end = f'{index}+{self.match_length}c'
        self.text.tag_remove('search_current', '1.0', 'end')
        self.text.tag_add('search_current', index, end)
        self.text.see(index)
        self.status.set(f'{self.current + 1} / {len(self.matches)}')
        return 'break'
