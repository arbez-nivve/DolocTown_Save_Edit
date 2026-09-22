"""Inventory tree, reusable item samples and typed property editing."""
import copy
import json
import math
import re
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from inventory import (add_item, backpack, container_at, delete_item, discover_catalog,
                       item_at, replace_item, validate_item)
from save_codec import SaveFormatError

LABELS = {'itemName': '物品 ID', 'itemCount': '数量', 'currentDurability': '箱子耐久',
          'skinIndex': '箱子外观编号', 'isClonedSeed': '克隆种子',
          'incubationProgress': '种子培养进度', 'isSellable': '可出售',
          'canSell': '可出售', 'sellable': '可出售', 'isValid': '有效',
          'fishName': '鱼种 ID', 'growth': '成长进度', 'incubation': '孵化进度'}


class InventoryEditor(ctk.CTkFrame):
    def __init__(self, parent, get_data, on_change):
        super().__init__(parent, fg_color='transparent')
        self.get_data, self.on_change = get_data, on_change
        self.selected = None
        self.loading = False
        self.editors = {}
        self.draft = None
        self.templates, self.genes = [], []
        self.grid_columnconfigure(0, weight=1, minsize=300)
        self.grid_columnconfigure(1, weight=1, minsize=330)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text='展开箱子查看内部物品。新增使用空槽，删除保留槽位；编辑会在切换物品或保存时应用。',
                     anchor='w', wraplength=620).grid(row=0, column=0, columnspan=2, sticky='ew', pady=6)
        tools = ctk.CTkFrame(self, fg_color='transparent')
        tools.grid(row=1, column=0, columnspan=2, sticky='ew', pady=6)
        for text, command in [('添加物品', self.open_catalog), ('复制所选', self.duplicate),
                              ('删除所选', self.delete), ('应用属性', self.apply),
                              ('完整物品 JSON', self.edit_json)]:
            ctk.CTkButton(tools, text=text, width=108, command=lambda c=command: self.run(c)).pack(side='left', padx=3)
        tree_frame = ctk.CTkFrame(self)
        tree_frame.grid(row=2, column=0, sticky='nsew', padx=(0, 8))
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.configure('Inventory.Treeview', rowheight=28, font=('Microsoft YaHei UI', 10))
        self.tree = ttk.Treeview(tree_frame, columns=('count', 'detail'), style='Inventory.Treeview',
                                 selectmode='browse', show='tree headings')
        self.tree.heading('#0', text='槽位 / 物品 ID（展开箱子）')
        self.tree.heading('count', text='数量')
        self.tree.heading('detail', text='属性')
        self.tree.column('#0', width=220, minwidth=150)
        self.tree.column('count', width=55, minwidth=45, stretch=False)
        self.tree.column('detail', width=150, minwidth=80)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.details = ctk.CTkScrollableFrame(self, label_text='物品属性')
        self.details.grid(row=2, column=1, sticky='nsew')
        self.details.grid_columnconfigure(0, weight=1)
        self.info = ctk.StringVar(value='打开存档后显示物品栏')
        ctk.CTkLabel(self, textvariable=self.info, anchor='w', wraplength=620).grid(
            row=3, column=0, columnspan=2, sticky='ew', pady=6)

    def run(self, action):
        try:
            action()
        except (SaveFormatError, ValueError, TypeError) as exc:
            messagebox.showerror('物品编辑失败', str(exc), parent=self)

    def refresh(self, rebuild_catalog=True):
        data = self.get_data()
        if data is None:
            return
        try:
            container = backpack(data)
            for item in container['items']:
                if item is not None:
                    validate_item(item)
        except SaveFormatError as exc:
            self.tree.delete(*self.tree.get_children())
            self.selected = None
            self.show_item()
            self.info.set(str(exc) + ' 请在高级 JSON 中修正后重试。')
            return
        if rebuild_catalog:
            self.templates, self.genes = discover_catalog(data)
        open_nodes = set()
        def remember(parent=''):
            for node in self.tree.get_children(parent):
                if self.tree.item(node, 'open'):
                    open_nodes.add(node)
                remember(node)
        remember()
        self.loading = True
        self.tree.delete(*self.tree.get_children())
        def insert(inv, path=(), parent=''):
            locks = inv.get('slotLockStates', [])
            for index, item in enumerate(inv['items']):
                address = path + (index,)
                iid = '/'.join(map(str, address))
                locked = index < len(locks) and locks[index]
                name = item.get('itemName', '?') if isinstance(item, dict) else '（空槽）'
                detail = '锁定' if locked else ''
                if isinstance(item, dict):
                    if 'currentDurability' in item:
                        detail += f" 耐久 {item['currentDurability']}"
                    group = item.get('geneGroup')
                    if isinstance(group, dict):
                        detail += ' ' + ', '.join(group.get('geneIds', []))
                self.tree.insert(parent, 'end', iid=iid, text=f'{index + 1:02} · {name}',
                                 values=(item.get('itemCount', '') if isinstance(item, dict) else '', detail),
                                 open=iid in open_nodes)
                if isinstance(item, dict) and isinstance(item.get('inventory'), dict):
                    if isinstance(item['inventory'].get('items'), list):
                        insert(item['inventory'], address, iid)
        insert(container)
        iid = '/'.join(map(str, self.selected or ()))
        if iid and self.tree.exists(iid):
            self.tree.selection_set(iid)
        else:
            self.selected = None
        self.loading = False
        self.show_item()
        used = sum(x is not None for x in container['items'])
        self.info.set(f"背包 {used}/{len(container['items'])} 槽 · 全存档物品样本 {len(self.templates)} 个 · 基因 {len(self.genes)} 种")

    def select(self, _event=None):
        selection = self.tree.selection()
        if self.loading or not selection:
            return
        path = tuple(map(int, selection[0].split('/')))
        if path == self.selected:
            return
        try:
            self.commit()
        except SaveFormatError as exc:
            if self.selected is not None:
                self.tree.selection_set('/'.join(map(str, self.selected)))
            messagebox.showerror('请先修正当前物品', str(exc), parent=self)
            return
        self.selected = path
        self.show_item()

    def changed(self, *_):
        if not self.loading:
            self.on_change()

    def show_item(self):
        self.loading = True
        for widget in self.details.winfo_children():
            widget.destroy()
        self.editors, self.draft = {}, None
        self.gene_var = None
        if self.selected is None:
            ctk.CTkLabel(self.details, text='选择左侧物品或空槽').grid(sticky='w', padx=8, pady=12)
            self.loading = False
            return
        item = item_at(self.get_data(), self.selected)
        if item is None:
            ctk.CTkLabel(self.details, text='这是空槽，可点击“添加物品”。').grid(sticky='w', padx=8, pady=12)
            self.loading = False
            return
        self.draft = copy.deepcopy(item)
        ctk.CTkLabel(self.details, text=item.get('$type', '普通物品（未记录 $type）'),
                     wraplength=280, justify='left').grid(row=0, sticky='w', padx=8, pady=8)
        row = 1
        for key, value in item.items():
            if key == '$type' or not isinstance(value, (str, bool, int, float)):
                continue
            ctk.CTkLabel(self.details, text=f'{LABELS.get(key, key)}  ·  {key}', anchor='w').grid(
                row=row, column=0, sticky='ew', padx=8, pady=(6, 0))
            if type(value) is bool:
                var = ctk.BooleanVar(value=value)
                control = ctk.CTkCheckBox(self.details, text='是 / 启用', variable=var)
            else:
                var = ctk.StringVar(value=str(value))
                control = ctk.CTkEntry(self.details, textvariable=var)
            control.grid(row=row + 1, column=0, sticky='ew', padx=8, pady=3)
            var.trace_add('write', self.changed)
            self.editors[key] = (var, type(value))
            row += 2
        if isinstance(item.get('geneGroup'), dict):
            ctk.CTkLabel(self.details, text='基因 ID（逗号分隔，可手动输入）').grid(row=row, sticky='w', padx=8, pady=(12, 3))
            self.gene_var = ctk.StringVar(value=', '.join(item['geneGroup'].get('geneIds', [])))
            ctk.CTkEntry(self.details, textvariable=self.gene_var).grid(row=row + 1, sticky='ew', padx=8)
            self.gene_var.trace_add('write', self.changed)
            self.gene_choice = ctk.CTkComboBox(self.details, values=self.genes or [''], command=self.add_gene)
            self.gene_choice.set('选择基因加入…')
            self.gene_choice.grid(row=row + 2, sticky='ew', padx=8, pady=6)
            row += 3
        if isinstance(item.get('inventory'), dict):
            ctk.CTkButton(self.details, text='展开箱内物品', command=self.expand_selected).grid(
                row=row, sticky='ew', padx=8, pady=8)
            row += 1
        ctk.CTkLabel(self.details,
            text='可出售：案例未记录独立开关。若当前物品含该字段，会在上方显示。\n复杂属性可通过“完整物品 JSON”修改。',
            wraplength=280, justify='left', text_color=('#64748B', '#AFC0D1')).grid(
                row=row, sticky='ew', padx=8, pady=12)
        self.loading = False

    def add_gene(self, gene):
        current = self.parse_genes()
        if gene and gene not in current:
            current.append(gene)
        self.gene_var.set(', '.join(current))

    def parse_genes(self):
        return [x for x in re.split(r'[,，\s]+', self.gene_var.get().strip()) if x]

    def commit(self):
        if self.selected is None or self.draft is None:
            return
        candidate = copy.deepcopy(self.draft)
        for key, (var, kind) in self.editors.items():
            try:
                candidate[key] = kind(var.get())
            except (ValueError, TypeError) as exc:
                raise SaveFormatError(f'{key} 的值无效，需要 {kind.__name__}。') from exc
            if kind is float and not math.isfinite(candidate[key]):
                raise SaveFormatError(f'{key} 必须为有限数值。')
        if self.gene_var is not None:
            candidate['geneGroup']['geneIds'] = self.parse_genes()
        if candidate['itemName'] != self.draft['itemName']:
            known = [t for t in self.templates if t.item['itemName'] == candidate['itemName']]
            if known and not any(t.item.get('$type') == candidate.get('$type') for t in known):
                raise SaveFormatError('新 ID 的物品类型不同，请删除后从样本库添加，以保留正确属性。')
        validate_item(candidate)
        if candidate != item_at(self.get_data(), self.selected):
            replace_item(self.get_data(), self.selected, candidate)
            self.draft = copy.deepcopy(candidate)
            self.on_change()
            iid = '/'.join(map(str, self.selected))
            self.tree.item(iid, text=f"{self.selected[-1] + 1:02} · {candidate['itemName']}",
                           values=(candidate['itemCount'], '已编辑'))

    def apply(self):
        self.commit()
        self.refresh(rebuild_catalog=False)

    def expand_selected(self):
        if self.selected is not None:
            self.tree.item('/'.join(map(str, self.selected)), open=True)

    def destination(self):
        if self.selected is None:
            return (), None
        item = item_at(self.get_data(), self.selected)
        if item is None:
            return self.selected[:-1], self.selected[-1]
        if isinstance(item.get('inventory'), dict):
            return self.selected, None
        return self.selected[:-1], None

    def duplicate(self):
        self.commit()
        if self.selected is None or self.draft is None:
            raise SaveFormatError('请先选择要复制的物品。')
        self.selected = add_item(self.get_data(), self.selected[:-1], self.draft)
        self.on_change()
        self.refresh(False)

    def delete(self):
        if self.selected is None or item_at(self.get_data(), self.selected) is None:
            raise SaveFormatError('请先选择要删除的物品。')
        if not messagebox.askyesno('删除物品', '删除所选物品？若为箱子，其中物品也会删除。\n尚未保存到文件，可重新打开原存档恢复。', parent=self):
            return
        delete_item(self.get_data(), self.selected)
        self.draft = None
        self.on_change()
        self.refresh(False)

    def open_catalog(self):
        self.commit()
        if self.get_data() is None:
            raise SaveFormatError('请先打开存档。')
        container_path, slot = self.destination()
        container = container_at(self.get_data(), container_path)
        self.templates, self.genes = discover_catalog(self.get_data())
        window = ctk.CTkToplevel(self)
        window.title('从全存档样本添加物品')
        window.geometry('810x580')
        window.transient(self.winfo_toplevel())
        window.grab_set()
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(2, weight=1)
        location = '背包' if not container_path else '箱内 ' + '/'.join(str(i + 1) for i in container_path)
        ctk.CTkLabel(window, text=f'目标：{location} · {len(container["items"])} 槽；复制样本的完整属性，初始数量为 1。').grid(padx=16, pady=10, sticky='ew')
        query = ctk.StringVar()
        ctk.CTkEntry(window, textvariable=query, placeholder_text='筛选物品 ID / 类型 / 基因，例如 seed_ 或 plastic_box').grid(row=1, sticky='ew', padx=16, pady=6)
        listing = tk.Listbox(window, exportselection=False, font=('Microsoft YaHei UI', 11))
        listing.grid(row=2, sticky='nsew', padx=16, pady=6)
        bar = ttk.Scrollbar(window, orient='vertical', command=listing.yview)
        bar.grid(row=2, column=1, sticky='ns')
        listing.configure(yscrollcommand=bar.set)
        source = ctk.StringVar(value='选择样本可查看来源；箱子样本会连同内部物品一起复制。')
        ctk.CTkLabel(window, textvariable=source, wraplength=740, justify='left').grid(row=3, padx=16, pady=6, sticky='ew')
        filtered = []
        def filter_items(*_):
            filtered[:] = [t for t in self.templates if query.get().casefold() in t.label.casefold()]
            listing.delete(0, 'end')
            for item in filtered:
                listing.insert('end', item.label)
        def selected(_=None):
            indices = listing.curselection()
            if indices:
                source.set('来源：' + filtered[indices[0]].source)
        def add():
            indices = listing.curselection()
            if not indices:
                return
            try:
                self.selected = add_item(self.get_data(), container_path, filtered[indices[0]].item, slot)
            except SaveFormatError as exc:
                messagebox.showerror('无法添加', str(exc), parent=window)
                return
            self.on_change()
            window.destroy()
            self.refresh(False)
            iid = '/'.join(map(str, self.selected))
            self.tree.see(iid)
        query.trace_add('write', filter_items)
        listing.bind('<<ListboxSelect>>', selected)
        filter_items()
        ctk.CTkButton(window, text='添加到目标空槽', command=add).grid(row=4, padx=16, pady=12)

    def edit_json(self):
        self.commit()
        if self.draft is None:
            raise SaveFormatError('请先选择物品。')
        window = ctk.CTkToplevel(self)
        window.title('完整物品 JSON')
        window.geometry('760x620')
        window.transient(self.winfo_toplevel())
        window.grab_set()
        editor = ctk.CTkTextbox(window, font=('Consolas', 13), undo=True)
        editor.pack(fill='both', expand=True, padx=16, pady=12)
        editor.insert('1.0', json.dumps(self.draft, ensure_ascii=False, indent=2))
        def apply():
            try:
                candidate = json.loads(editor.get('1.0', 'end-1c'))
                replace_item(self.get_data(), self.selected, candidate)
            except (ValueError, TypeError) as exc:
                messagebox.showerror('物品格式错误', str(exc), parent=window)
                return
            self.on_change()
            window.destroy()
            self.refresh(False)
        ctk.CTkButton(window, text='验证并应用到物品', command=apply).pack(pady=(0, 12))
