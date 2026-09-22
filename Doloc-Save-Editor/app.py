"""Windows GUI for safely editing Doloc Town save files."""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Literal

import customtkinter as ctk

from save_codec import SaveFormatError, format_json, load_save, parse_json_text, write_save
from inventory_ui import InventoryEditor
from inventory import backpack, validate_backpack_layout
from json_search import JsonSearch


APP_NAME = "多洛可小镇存档修改器"
FORM_TAB = "常用字段"
JSON_TAB = "高级 JSON"
INVENTORY_TAB = "物品栏"
INT32_MAX = 2_147_483_647


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    paths: tuple[str, ...]
    kind: Literal["text", "integer"]
    hint: str


FIELDS = (
    FieldSpec(
        "player_name",
        "玩家名称",
        ("baseData.customPlayerName", "farmData.agentData.customPlayerName"),
        "text",
        "同步修改两处名称字段",
    ),
    FieldSpec(
        "money",
        "持有金钱",
        ("baseData.money", "farmData.agentData.money"),
        "integer",
        "0 至 2,147,483,647",
    ),
    FieldSpec(
        "health",
        "当前生命",
        ("farmData.agentData.health",),
        "integer",
        "不能高于最大生命",
    ),
    FieldSpec(
        "max_health",
        "最大生命",
        ("farmData.agentData.maxHealth",),
        "integer",
        "角色生命上限",
    ),
    FieldSpec(
        "energy",
        "当前能量",
        ("farmData.agentData.energy",),
        "integer",
        "不能高于最大能量",
    ),
    FieldSpec(
        "max_energy",
        "最大能量",
        ("farmData.agentData.maxEnergy",),
        "integer",
        "角色能量上限",
    ),
    FieldSpec(
        "spirit",
        "当前精神",
        ("farmData.agentData.spirit",),
        "integer",
        "不能高于最大精神",
    ),
    FieldSpec(
        "max_spirit",
        "最大精神",
        ("farmData.agentData.maxSpirit",),
        "integer",
        "角色精神上限",
    ),
    FieldSpec(
        "backpack_level",
        "背包等级",
        ("farmData.agentData.backpackLevel",),
        "integer",
        "只读：保持原存档的背包容量",
    ),
    FieldSpec(
        "farm_level",
        "农场等级",
        ("farmData.agentData.farmLevel",),
        "integer",
        "请使用游戏中存在的等级",
    ),
)


def get_path(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise SaveFormatError(f"当前存档缺少字段：{dotted_path}")
        current = current[part]
    return current


def set_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise SaveFormatError(f"当前存档缺少字段：{dotted_path}")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise SaveFormatError(f"当前存档缺少字段：{dotted_path}")
    current[parts[-1]] = value


def format_game_date(date_data: Any) -> str:
    if not isinstance(date_data, dict):
        return "—"
    try:
        return (
            f"第 {date_data['Year']} 年 · {date_data['Month']} 月 {date_data['Day']} 日 "
            f"{int(date_data['Hour']):02d}:{int(date_data['Minute']):02d}"
        )
    except (KeyError, TypeError, ValueError):
        return "—"


class DolocSaveEditor(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1240x820")
        self.minsize(1040, 700)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.source_path: Path | None = None
        self.data: dict[str, Any] | None = None
        self.original_data: dict[str, Any] | None = None
        self.field_vars = {spec.key: ctk.StringVar() for spec in FIELDS}
        self.overview_vars = {
            "version": ctk.StringVar(value="—"),
            "game_date": ctk.StringVar(value="—"),
            "play_time": ctk.StringVar(value="—"),
            "scene": ctk.StringVar(value="—"),
        }
        self.status_var = ctk.StringVar(value="请选择一个 .data 存档开始")
        self.source_var = ctk.StringVar(value="尚未打开文件")
        self.previous_tab = FORM_TAB
        self.tab_syncing = False
        self.dirty = False
        self.programmatic_change = False

        self._build_layout()
        self._set_actions_enabled(False)
        for variable in self.field_vars.values():
            variable.trace_add('write', lambda *_: self._mark_dirty())
        self.bind('<Control-f>', self._focus_search)
        self.bind('<F3>', lambda e: self.search.move())
        self.bind('<Shift-F3>', lambda e: self.search.move(-1))

        if len(sys.argv) > 1:
            requested = Path(sys.argv[1])
            self.after(150, lambda: self.load_path(requested))

    def _build_layout(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        sidebar = ctk.CTkFrame(self, width=282, corner_radius=0, fg_color=("#0F2742", "#0B1728"))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(8, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="DOLOC  SAVE LAB",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#69D7CA",
        ).grid(row=0, column=0, sticky="w", padx=26, pady=(28, 4))
        ctk.CTkLabel(
            sidebar,
            text="存档修改器",
            font=ctk.CTkFont(size=27, weight="bold"),
            text_color="#F8FAFC",
        ).grid(row=1, column=0, sticky="w", padx=26, pady=(0, 22))

        self.open_button = ctk.CTkButton(
            sidebar,
            text="打开存档",
            height=44,
            fg_color="#12A594",
            hover_color="#0E887B",
            command=self.open_file,
        )
        self.open_button.grid(row=2, column=0, sticky="ew", padx=24, pady=6)

        self.save_as_button = ctk.CTkButton(
            sidebar,
            text="另存为修改版",
            height=42,
            command=self.save_as,
        )
        self.save_as_button.grid(row=3, column=0, sticky="ew", padx=24, pady=6)

        self.save_current_button = ctk.CTkButton(
            sidebar,
            text="覆盖当前存档",
            height=42,
            fg_color="transparent",
            border_width=1,
            border_color="#F59E0B",
            text_color=("#FCD34D", "#FBBF24"),
            hover_color=("#24415B", "#172A42"),
            command=self.save_current,
        )
        self.save_current_button.grid(row=4, column=0, sticky="ew", padx=24, pady=6)

        self.export_button = ctk.CTkButton(
            sidebar,
            text="导出格式化 JSON",
            height=40,
            fg_color="transparent",
            border_width=1,
            border_color="#5B7896",
            hover_color=("#24415B", "#172A42"),
            command=self.export_json,
        )
        self.export_button.grid(row=5, column=0, sticky="ew", padx=24, pady=(18, 6))

        source_card = ctk.CTkFrame(sidebar, fg_color=("#173553", "#10243A"), corner_radius=12)
        source_card.grid(row=6, column=0, sticky="ew", padx=24, pady=(22, 8))
        ctk.CTkLabel(
            source_card,
            text="当前文件",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#8AB4D8",
        ).pack(anchor="w", padx=14, pady=(12, 5))
        ctk.CTkLabel(
            source_card,
            textvariable=self.source_var,
            justify="left",
            anchor="w",
            wraplength=212,
            text_color="#E2E8F0",
        ).pack(fill="x", padx=14, pady=(0, 12))

        safety = ctk.CTkFrame(sidebar, fg_color=("#173553", "#10243A"), corner_radius=12)
        safety.grid(row=7, column=0, sticky="ew", padx=24, pady=8)
        ctk.CTkLabel(
            safety,
            text="安全策略",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#8AB4D8",
        ).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            safety,
            text="覆盖前自动备份\n写入后自动解密回读",
            justify="left",
            text_color="#C6D5E4",
        ).pack(anchor="w", padx=14, pady=(0, 12))

        ctk.CTkLabel(sidebar, text="界面主题", text_color="#8AB4D8").grid(
            row=9, column=0, sticky="w", padx=26, pady=(8, 4)
        )
        theme_picker = ctk.CTkSegmentedButton(
            sidebar,
            values=["跟随系统", "浅色", "深色"],
            command=self._set_theme,
        )
        theme_picker.grid(row=10, column=0, sticky="ew", padx=24, pady=(0, 24))
        theme_picker.set("跟随系统")

        main = ctk.CTkFrame(self, corner_radius=0, fg_color=("#F4F7FA", "#0F1724"))
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(24, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="安全编辑游戏进度",
            font=ctk.CTkFont(size=25, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="常用字段会同步到存档中的对应副本",
            text_color=("#64748B", "#9AAFC4"),
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.state_badge = ctk.CTkLabel(
            header,
            text="未加载",
            width=104,
            height=30,
            corner_radius=12,
            fg_color=("#E2E8F0", "#233247"),
            text_color=("#475569", "#B9C9D9"),
        )
        self.state_badge.grid(row=0, column=1, rowspan=2, sticky="e")

        self.tabs = ctk.CTkTabview(main, command=self._on_tab_changed)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=28, pady=(6, 12))
        fields_tab = self.tabs.add(FORM_TAB)
        inventory_tab = self.tabs.add(INVENTORY_TAB)
        json_tab = self.tabs.add(JSON_TAB)
        self.tabs.set(FORM_TAB)

        self._build_fields_tab(fields_tab)
        self._build_json_tab(json_tab)
        self.inventory_editor = InventoryEditor(inventory_tab, lambda: self.data, self._mark_dirty)
        self.inventory_editor.pack(fill='both', expand=True)

        footer = ctk.CTkFrame(main, height=42, corner_radius=0, fg_color=("#E8EEF4", "#101D2C"))
        footer.grid(row=2, column=0, sticky="ew")
        ctk.CTkLabel(
            footer,
            textvariable=self.status_var,
            anchor="w",
            text_color=("#475569", "#AFC0D1"),
        ).pack(fill="x", padx=30, pady=10)

    def _build_fields_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        overview = ctk.CTkFrame(parent, fg_color="transparent")
        overview.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 14))
        for index in range(4):
            overview.grid_columnconfigure(index, weight=1, uniform="overview")
        cards = (
            ("存档版本", "version"),
            ("游戏时间", "game_date"),
            ("累计游玩", "play_time"),
            ("当前场景", "scene"),
        )
        for column, (label, key) in enumerate(cards):
            card = ctk.CTkFrame(overview, corner_radius=12)
            card.grid(row=0, column=column, sticky="nsew", padx=5)
            ctk.CTkLabel(
                card,
                text=label,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("#64748B", "#90A5BA"),
            ).pack(anchor="w", padx=14, pady=(12, 3))
            ctk.CTkLabel(
                card,
                textvariable=self.overview_vars[key],
                anchor="w",
                justify="left",
                wraplength=180,
                font=ctk.CTkFont(size=14, weight="bold"),
            ).pack(fill="x", padx=14, pady=(0, 13))

        editor = ctk.CTkScrollableFrame(parent, label_text="可安全编辑的常用字段")
        editor.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        editor.grid_columnconfigure((0, 1), weight=1, uniform="fields")

        for index, spec in enumerate(FIELDS):
            row, column = divmod(index, 2)
            card = ctk.CTkFrame(editor, corner_radius=12)
            card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                card,
                text=spec.label,
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 3))
            entry = ctk.CTkEntry(
                card,
                textvariable=self.field_vars[spec.key],
                height=38,
                placeholder_text="打开存档后显示",
            )
            entry.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
            if spec.key == 'backpack_level':
                entry.configure(state='disabled')
            ctk.CTkLabel(
                card,
                text=spec.hint,
                text_color=("#718096", "#90A5BA"),
                font=ctk.CTkFont(size=11),
            ).grid(row=2, column=0, sticky="w", padx=14, pady=(2, 12))

        note = ctk.CTkLabel(
            editor,
            text="日期包含 TotalDays、TotalTUs 和星期等联动值，第一版仅展示，不在常用区直接修改。需要时可在高级 JSON 中编辑。",
            justify="left",
            anchor="w",
            wraplength=760,
            text_color=("#9A6700", "#F2C26B"),
        )
        note.grid(row=(len(FIELDS) + 1) // 2, column=0, columnspan=2, sticky="ew", padx=10, pady=(14, 8))

    def _build_json_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        toolbar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            toolbar,
            text="高级模式会暴露完整存档结构；不要删除 $type 字段或未知区段。",
            text_color=("#9A6700", "#F2C26B"),
            anchor="w",
            wraplength=620,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        self.validate_button = ctk.CTkButton(
            toolbar, text="验证", width=90, fg_color="transparent", border_width=1, command=self.validate_json
        )
        self.validate_button.grid(row=1, column=1, padx=4)
        self.format_button = ctk.CTkButton(toolbar, text="格式化", width=90, command=self.format_json_editor)
        self.format_button.grid(row=1, column=2, padx=4)
        self.restore_button = ctk.CTkButton(
            toolbar,
            text="撤销未应用编辑",
            width=126,
            fg_color="transparent",
            border_width=1,
            command=self.restore_json_editor,
        )
        self.restore_button.grid(row=1, column=3, padx=(4, 0))

        self.json_editor = ctk.CTkTextbox(
            parent,
            wrap="none",
            font=("Consolas", 13),
            undo=True,
            maxundo=50,
        )
        self.json_editor.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.search = JsonSearch(parent, self.json_editor)
        self.search.grid(row=1, column=0, sticky='ew', padx=8, pady=(2, 8))
        self.json_editor._textbox.bind('<<Modified>>', self._json_modified)

    def _focus_search(self, _event=None):
        self.tabs.set(JSON_TAB)
        self._on_tab_changed()
        if self.tabs.get() == JSON_TAB:
            return self.search.focus()
        return 'break'

    def _json_modified(self, _event=None):
        text = self.json_editor._textbox
        if text.edit_modified():
            self._mark_dirty()
            self.search.schedule()
            text.edit_modified(False)

    def _set_theme(self, choice: str) -> None:
        modes = {"跟随系统": "System", "浅色": "Light", "深色": "Dark"}
        ctk.set_appearance_mode(modes[choice])

    def _set_actions_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (
            self.save_as_button,
            self.save_current_button,
            self.export_button,
            self.validate_button,
            self.format_button,
            self.restore_button,
        ):
            button.configure(state=state)

    def _mark_dirty(self, _event: Any = None) -> None:
        if self.data is not None and not self.programmatic_change:
            self.dirty = True
            self.state_badge.configure(text="有未保存修改", fg_color=("#FEF3C7", "#4A3412"))

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def open_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="打开多洛可小镇存档",
            initialdir=str(self.source_path.parent if self.source_path else Path.home()),
            filetypes=(("Doloc 存档 / JSON", "*.data *.json"), ("所有文件", "*.*")),
        )
        if selected:
            self.load_path(Path(selected))

    def load_path(self, path: Path) -> None:
        if self.dirty and not messagebox.askyesno("放弃修改？", "当前修改尚未保存，仍要打开其他存档吗？"):
            return
        self._set_status("正在解密并验证存档…")
        self.update_idletasks()
        try:
            if path.suffix.lower() == '.json':
                data = parse_json_text(path.read_text(encoding='utf-8-sig'))
            else:
                data, _ = load_save(path)
            backpack(data)
            for spec in FIELDS:
                for field in spec.paths:
                    get_path(data, field)
        except (SaveFormatError, OSError, UnicodeError) as exc:
            self._set_status("打开失败")
            messagebox.showerror("无法打开存档", str(exc), parent=self)
            return

        self.source_path = path
        self.data = data
        self.original_data = copy.deepcopy(data)
        self.previous_tab = FORM_TAB
        self.tabs.set(FORM_TAB)
        self._populate_form()
        self._render_json()
        self._refresh_overview()
        self.inventory_editor.selected = None
        self.inventory_editor.refresh()
        self.source_var.set(f"{path.name}\n{path.parent}")
        self._set_actions_enabled(True)
        self.dirty = False
        self.state_badge.configure(text="已验证", fg_color=("#D1FAE5", "#123D35"))
        self._set_status(f"已载入：{path}")

    def _populate_form(self) -> None:
        if self.data is None:
            return
        self.programmatic_change = True
        try:
            for spec in FIELDS:
                self.field_vars[spec.key].set(str(get_path(self.data, spec.paths[0])))
        finally:
            self.programmatic_change = False

    def _parse_integer(self, spec: FieldSpec) -> int:
        raw = self.field_vars[spec.key].get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise SaveFormatError(f"{spec.label}必须是整数。") from exc
        if not 0 <= value <= INT32_MAX:
            raise SaveFormatError(f"{spec.label}必须在 0 至 {INT32_MAX:,} 之间。")
        return value

    def _apply_form(self) -> None:
        if self.data is None:
            raise SaveFormatError("尚未打开存档。")
        updated = copy.deepcopy(self.data)
        values: dict[str, Any] = {}
        for spec in FIELDS:
            if spec.key == 'backpack_level':
                value = get_path(self.data, spec.paths[0])
            elif spec.kind == "integer":
                value: Any = self._parse_integer(spec)
            else:
                value = self.field_vars[spec.key].get().strip()
                if not value:
                    raise SaveFormatError(f"{spec.label}不能为空。")
                if len(value) > 64:
                    raise SaveFormatError(f"{spec.label}不能超过 64 个字符。")
            values[spec.key] = value
            for path in spec.paths:
                set_path(updated, path, value)

        pairs = (
            ("当前生命", "health", "max_health"),
            ("当前能量", "energy", "max_energy"),
            ("当前精神", "spirit", "max_spirit"),
        )
        for label, current_key, maximum_key in pairs:
            if values[current_key] > values[maximum_key]:
                raise SaveFormatError(f"{label}不能高于对应上限。")
        self._validate_backpack_layout(updated)
        self.data = updated
        self._refresh_overview()

    def _render_json(self) -> None:
        if self.data is None:
            return
        text = format_json(self.data)
        self.programmatic_change = True
        try:
            self.json_editor.delete("1.0", "end")
            self.json_editor.insert("1.0", text)
            self.json_editor._textbox.edit_reset()
            self.json_editor._textbox.edit_modified(False)
            self.search.schedule()
        finally:
            self.programmatic_change = False

    def _apply_json(self) -> None:
        text = self.json_editor.get("1.0", "end-1c")
        candidate = parse_json_text(text)
        for spec in FIELDS:
            for field in spec.paths:
                get_path(candidate, field)
        self._validate_backpack_layout(candidate)
        self.data = candidate
        self._populate_form()
        self._refresh_overview()

    def _on_tab_changed(self) -> None:
        if self.tab_syncing or self.data is None:
            return
        selected = self.tabs.get()
        if selected == self.previous_tab:
            return
        try:
            if self.previous_tab == FORM_TAB:
                self._apply_form()
            elif self.previous_tab == JSON_TAB:
                self._apply_json()
            elif self.previous_tab == INVENTORY_TAB:
                self.inventory_editor.commit()
            if selected == JSON_TAB:
                self._render_json()
            elif selected == INVENTORY_TAB:
                self.inventory_editor.refresh()
            else:
                self._populate_form()
        except SaveFormatError as exc:
            self.tab_syncing = True
            try:
                self.tabs.set(self.previous_tab)
            finally:
                self.tab_syncing = False
            messagebox.showerror("无法切换编辑模式", str(exc), parent=self)
            return
        self.previous_tab = selected

    def _refresh_overview(self) -> None:
        if self.data is None:
            return
        base = self.data.get("baseData", {})
        seconds = base.get("totalGameSeconds")
        if isinstance(seconds, (int, float)):
            hours = float(seconds) / 3600
            play_time = f"{hours:.1f} 小时"
        else:
            play_time = "—"
        scene = str(base.get("currentScene", "—"))
        if len(scene) > 24:
            scene = scene[:21] + "…"
        self.overview_vars["version"].set(str(base.get("version", "—")))
        self.overview_vars["game_date"].set(format_game_date(base.get("dateNow")))
        self.overview_vars["play_time"].set(play_time)
        self.overview_vars["scene"].set(scene)

    def _validate_backpack_layout(self, data) -> None:
        if self.original_data is not None:
            validate_backpack_layout(data, self.original_data)

    def _collect_active_data(self) -> dict[str, Any]:
        if self.tabs.get() == JSON_TAB:
            self._apply_json()
        elif self.tabs.get() == FORM_TAB:
            self._apply_form()
        elif self.tabs.get() == INVENTORY_TAB:
            self.inventory_editor.commit()
        if self.data is None:
            raise SaveFormatError("尚未打开存档。")
        self._validate_backpack_layout(self.data)
        return self.data

    def validate_json(self) -> None:
        try:
            parsed = parse_json_text(self.json_editor.get("1.0", "end-1c"))
            self._validate_backpack_layout(parsed)
        except SaveFormatError as exc:
            messagebox.showerror("JSON 验证失败", str(exc), parent=self)
            return
        messagebox.showinfo("JSON 验证通过", f"顶层区段：{len(parsed)} 个", parent=self)
        self._set_status("高级 JSON 验证通过")

    def format_json_editor(self) -> None:
        try:
            self._apply_json()
            self._render_json()
            self._populate_form()
            self._refresh_overview()
            self._mark_dirty()
        except SaveFormatError as exc:
            messagebox.showerror("无法格式化 JSON", str(exc), parent=self)

    def restore_json_editor(self) -> None:
        if self.data is None:
            return
        if messagebox.askyesno("撤销 JSON 编辑？", "将丢弃文本框中尚未应用的改动。", parent=self):
            self._render_json()
            self._set_status("已恢复当前内存中的存档内容")

    def save_as(self) -> None:
        if self.source_path is None:
            return
        default_name = f"{self.source_path.stem}-modified.data"
        selected = filedialog.asksaveasfilename(
            title="另存为修改版存档",
            initialdir=str(self.source_path.parent),
            initialfile=default_name,
            defaultextension=".data",
            filetypes=(("Doloc Town 存档", "*.data"), ("所有文件", "*.*")),
        )
        if selected:
            self._save_to(Path(selected))

    def save_current(self) -> None:
        if self.source_path is None:
            return
        if self.source_path.suffix.lower() == '.json':
            self.save_as()
            return
        confirmed = messagebox.askyesno(
            "覆盖当前存档？",
            "修改器会先创建时间戳备份，再覆盖当前文件。\n\n建议先退出游戏，避免游戏稍后覆盖改动。",
            icon="warning",
            parent=self,
        )
        if confirmed:
            self._save_to(self.source_path)

    def _save_to(self, target: Path) -> None:
        self._set_status("正在验证、加密并回读存档…")
        self.update_idletasks()
        try:
            data = self._collect_active_data()
            result = write_save(target, data, backup_existing=True)
        except SaveFormatError as exc:
            self._set_status("保存失败；原文件未被替换")
            messagebox.showerror("保存失败", str(exc), parent=self)
            return

        self.source_path = result.output_path
        self.original_data = copy.deepcopy(data)
        self.source_var.set(f"{target.name}\n{target.parent}")
        self.dirty = False
        self.state_badge.configure(text="已保存并回读", fg_color=("#D1FAE5", "#123D35"))
        backup_line = f"\n备份：{result.backup_path}" if result.backup_path else ""
        self._set_status(f"保存成功：{target}")
        messagebox.showinfo(
            "保存成功",
            f"已生成加密存档，并完成回读验证。请另行确认游戏内加载结果。\n文件：{target}{backup_line}",
            parent=self,
        )

    def export_json(self) -> None:
        if self.source_path is None:
            return
        selected = filedialog.asksaveasfilename(
            title="导出格式化 JSON",
            initialdir=str(self.source_path.parent),
            initialfile=f"{self.source_path.stem}.json",
            defaultextension=".json",
            filetypes=(("JSON 文件", "*.json"),),
        )
        if not selected:
            return
        target = Path(selected)
        if target.exists() and not messagebox.askyesno("覆盖 JSON？", f"文件已存在：\n{target}\n\n是否覆盖？", parent=self):
            return
        try:
            data = self._collect_active_data()
            target.write_text(format_json(data), encoding="utf-8")
            parse_json_text(target.read_text(encoding="utf-8"))
        except (OSError, SaveFormatError) as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self._set_status(f"JSON 已导出：{target}")
        messagebox.showinfo("导出成功", f"已导出并重新验证：\n{target}", parent=self)

    def _on_close(self) -> None:
        if self.dirty and not messagebox.askyesno("退出修改器？", "尚有未保存的修改，确定退出吗？", parent=self):
            return
        self.destroy()


def main() -> None:
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = DolocSaveEditor()
    app.mainloop()


if __name__ == "__main__":
    main()
