from __future__ import annotations

import contextlib
import io
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .audit_dialog import AuditFixDialog
from .audit_models import AuditSeverity, MetadataAuditIssue
from .completeness import album_group_key, parse_position
from .constants import (
    APP_NAME,
    DEFAULT_REPORT_COLORS,
    DEFAULT_VARIATION_MARKERS,
    EXPORT_COLUMNS,
    REPORT_COLOR_CHOICES,
    STATUS_ROW_COLORS_DARK,
    STATUS_ROW_COLORS_LIGHT,
    SUPPORTED_FORMATS,
    TABLE_COLUMNS,
)
from .copy_dialog import UniqueCopyDialog
from .exporter import export_xlsx
from .metadata import MetadataDependencyError, read_embedded_cover
from .metadata_audit import find_folder_cover
from .models import (
    AlbumCompletenessIssue,
    AnalysisResult,
    Track,
    TrackStatus,
    album_completeness_text,
    folder_summary_text,
)
from .numbering_dialog import NumberingFixDialog
from .numbering_fix import NumberingPlan, plan_numbering_fix
from .parsing import files_word, folders_word, validate_markers
from .scanner import (
    AnalysisStopped,
    NoAudioFilesError,
    NoSelectedFormatsError,
    analyze_collection,
)
from .settings import AppSettings
from .utilities_dialog import UtilitiesDialog, UtilityContext

TABLE_FIELD_IDS = [item[0] for item in TABLE_COLUMNS]


def _files_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "файл"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "файла"
    return "файлов"


# The same physical key in the Russian (ЙЦУКЕН) layout. Tk matches shortcuts
# by keysym, so a <Control-o> binding never fires while that layout is active
# (the key reports "Cyrillic_shcha") nor under Caps Lock (it reports "O").
RUSSIAN_LAYOUT_KEYS = {
    "c": "es",
    "e": "u",
    "f": "a",
    "o": "shcha",
    "v": "em",
    "x": "che",
}


def _russian_control_sequences(letter: str) -> list[str]:
    name = RUSSIAN_LAYOUT_KEYS[letter]
    return [f"<Control-Cyrillic_{name}>", f"<Control-Cyrillic_{name.upper()}>"]


def _control_sequences(letter: str) -> list[str]:
    """Ctrl+<letter> in both cases (Caps Lock) and in the Russian layout."""
    return [
        f"<Control-{letter}>",
        f"<Control-{letter.upper()}>",
        *_russian_control_sequences(letter),
    ]


def _responsive_group_width(viewport_width: int) -> int:
    if viewport_width <= 1:
        return 335
    return min(620, max(335, round(viewport_width * 0.38)))


class DiscographyAnalyzerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = AppSettings.load()
        self.result: AnalysisResult | None = None
        self.track_by_id: dict[str, Track] = {}
        self.visible_tracks: list[Track] = []
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.sort_column: str | None = None
        self.sort_reverse = False
        self.cover_photo: ImageTk.PhotoImage | None = None
        self.group_labels: dict[str, str] = {}
        self.group_members: dict[str, list[str]] = {}
        self.variation_source_ids: set[str] = set()
        self._group_column_width: int | None = None
        self._folder_column_width: int | None = None
        self._column_widths: dict[str, int] = {}
        self._filter_job: str | None = None
        # Default view: the folder tree, where album numbering and the
        # completeness warnings are easiest to read.
        self.current_tab = tk.StringVar(value="folders")
        self.filter_var = tk.StringVar()
        self.issue_by_id: dict[str, AlbumCompletenessIssue] = {}
        self.audit_issue_by_id: dict[str, MetadataAuditIssue] = {}
        self.audit_item_track_ids: dict[str, str] = {}
        self._numbering_plan: NumberingPlan | None = None

        self.root.title(APP_NAME)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = min(1450, max(640, screen_width - 80))
        window_height = min(900, max(520, screen_height - 100))
        self.root.geometry(f"{window_width}x{window_height}")
        self.root.minsize(min(960, window_width), min(620, window_height))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")

        self._create_variables()
        self._build_ui()
        self._bind_actions()
        self.apply_theme()
        self._reset_progress()
        self._clear_info()
        self.root.after(100, self._poll_events)

    def _create_variables(self) -> None:
        last = self.settings.last_folder if self.settings.remember_folder else ""
        self.folder_var = tk.StringVar(value=last)
        self.include_subfolders_var = tk.BooleanVar(
            value=self.settings.include_subfolders
        )
        self.use_tags_var = tk.BooleanVar(value=self.settings.use_tags)
        self.detect_variations_var = tk.BooleanVar(
            value=self.settings.detect_variations
        )
        self.check_track_gaps_var = tk.BooleanVar(
            value=self.settings.check_track_gaps
        )
        self.folder_tree_mode_var = tk.BooleanVar(
            value=self.settings.folder_tree_mode
        )
        self.dark_theme_var = tk.BooleanVar(value=self.settings.dark_theme)
        self.format_vars = {
            name: tk.BooleanVar(value=self.settings.formats.get(name, True))
            for name in SUPPORTED_FORMATS
        }
        self.progress_percent_var = tk.StringVar(value="0%")
        self.progress_state_var = tk.StringVar(value="Анализ не запущен")
        self.files_count_var = tk.StringVar(value="Файлов: 0")
        self.folders_count_var = tk.StringVar(value="Папок: 0")
        self.variations_count_var = tk.StringVar(value="Вариаций: 0")
        self.shown_count_var = tk.StringVar(value="0 из 0")
        self.statistics_var = tk.StringVar(value="Статистика: —")

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(4, weight=1)

        header = ttk.Frame(self.root, padding=(14, 9), style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="♫", style="BrandIcon.TLabel").grid(
            row=0, column=0, rowspan=2, padx=(0, 10)
        )
        ttk.Label(header, text=APP_NAME, style="BrandTitle.TLabel").grid(
            row=0, column=1, sticky="sw"
        )
        ttk.Label(
            header,
            text="Анализ локальной музыкальной коллекции",
            style="BrandSub.TLabel",
        ).grid(
            row=1, column=1, sticky="nw"
        )
        ttk.Checkbutton(
            header,
            text="Тёмная тема",
            variable=self.dark_theme_var,
            command=self._theme_changed,
            style="Header.TCheckbutton",
        ).grid(row=0, column=2, rowspan=2)

        source = ttk.LabelFrame(self.root, text="Источник", padding=8)
        source.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 7))
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text="Папка").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(source, textvariable=self.folder_var, state="readonly").grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(source, text="Выбрать...", command=self.choose_folder).grid(
            row=0, column=2, padx=8
        )
        ttk.Checkbutton(
            source,
            text="Включать подпапки",
            variable=self.include_subfolders_var,
        ).grid(row=0, column=3)

        workspace = ttk.Frame(self.root)
        workspace.grid(row=2, column=0, sticky="ew", padx=12)
        workspace.columnconfigure(1, weight=1, minsize=500)

        settings_frame = ttk.LabelFrame(
            workspace, text="Настройки анализа", padding=9
        )
        settings_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(settings_frame, text="Форматы:").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        for index, (name, variable) in enumerate(self.format_vars.items()):
            ttk.Checkbutton(settings_frame, text=name, variable=variable).grid(
                row=1, column=index, sticky="w", padx=(0, 8)
            )
        ttk.Checkbutton(
            settings_frame,
            text="Учитывать теги (не только имена файлов)",
            variable=self.use_tags_var,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(5, 0))
        ttk.Checkbutton(
            settings_frame,
            text="Определять вариации (миксы, ремиксы, live)",
            variable=self.detect_variations_var,
        ).grid(row=3, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(
            settings_frame,
            text="Проверять пропуски номеров треков",
            variable=self.check_track_gaps_var,
        ).grid(row=4, column=0, columnspan=4, sticky="w")

        buttons = ttk.Frame(settings_frame)
        buttons.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(7, 4))
        self.start_button = ttk.Button(
            buttons,
            text="Начать анализ",
            command=self.start_analysis,
            style="Accent.TButton",
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            buttons,
            text="Остановить",
            command=self.stop_analysis,
            state="disabled",
            style="Stop.TButton",
        )
        self.stop_button.pack(side="left", padx=6)
        ttk.Button(
            buttons, text="Дополнительно...", command=self.open_advanced_settings
        ).pack(side="left")

        self.progress = ttk.Progressbar(
            settings_frame, maximum=100, mode="determinate", value=0
        )
        self.progress.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(2, 2))
        status_line = ttk.Frame(settings_frame)
        status_line.grid(row=7, column=0, columnspan=4, sticky="ew")
        status_line.columnconfigure(0, weight=1)
        ttk.Label(
            status_line,
            textvariable=self.progress_state_var,
            width=36,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Label(status_line, textvariable=self.progress_percent_var).grid(
            row=0, column=1, sticky="e"
        )
        counters = ttk.Frame(settings_frame)
        counters.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        ttk.Label(counters, textvariable=self.files_count_var).pack(side="left")
        ttk.Label(counters, textvariable=self.folders_count_var).pack(
            side="left", padx=14
        )
        ttk.Label(counters, textvariable=self.variations_count_var).pack(side="left")

        info_frame = ttk.LabelFrame(
            workspace, text="Информация о выбранном треке", padding=7
        )
        info_frame.grid(row=0, column=1, sticky="nsew")
        info_frame.columnconfigure(0, weight=1, minsize=250)
        info_frame.rowconfigure(0, weight=1)
        info_holder = ttk.Frame(info_frame)
        info_holder.grid(row=0, column=0, sticky="nsew")
        info_holder.columnconfigure(0, weight=1)
        info_holder.rowconfigure(0, weight=1)
        self.info_text = tk.Text(
            info_holder,
            width=36,
            height=13,
            wrap="word",
            state="disabled",
            relief="flat",
        )
        info_scroll = ttk.Scrollbar(
            info_holder, orient="vertical", command=self.info_text.yview
        )
        self.info_text.configure(yscrollcommand=info_scroll.set)
        self.info_text.grid(row=0, column=0, sticky="nsew")
        info_scroll.grid(row=0, column=1, sticky="ns")
        self.cover_holder = ttk.Frame(info_frame, width=205, height=205)
        self.cover_holder.grid(row=0, column=1, padx=(8, 0), sticky="ne")
        self.cover_holder.grid_propagate(False)
        self.cover_label = tk.Label(
            self.cover_holder,
            text="Обложка не выбрана",
            justify="center",
            anchor="center",
        )
        self.cover_label.grid(row=0, column=0, sticky="nsew")
        self.cover_holder.columnconfigure(0, weight=1)
        self.cover_holder.rowconfigure(0, weight=1)

        toolbar = ttk.Frame(self.root, padding=(12, 7), style="Toolbar.TFrame")
        toolbar.grid(row=3, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        tabs_frame = ttk.Frame(toolbar, style="Toolbar.TFrame")
        tabs_frame.grid(row=0, column=0, sticky="w")
        tabs = (
            ("all", "Все треки"),
            ("duplicates", "Дубликаты"),
            ("variations", "Вариации"),
            ("unique", "Уникальные"),
            ("folders", "По папкам"),
            ("audit", "Аудит"),
        )
        for value, text in tabs:
            ttk.Radiobutton(
                tabs_frame,
                text=text,
                value=value,
                variable=self.current_tab,
                command=self.refresh_table,
                style="Tab.TRadiobutton",
            ).pack(side="left", padx=(0, 4))

        controls = ttk.Frame(toolbar, style="Toolbar.TFrame")
        controls.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        controls.columnconfigure(6, weight=1)
        ttk.Label(controls, text="Показано:", style="Toolbar.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            controls,
            textvariable=self.shown_count_var,
            style="Toolbar.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=(4, 14))
        self.folder_tree_check = ttk.Checkbutton(
            controls,
            text="Древовидный вид",
            variable=self.folder_tree_mode_var,
            command=self._tree_mode_changed,
            state="disabled",
            style="Toolbar.TCheckbutton",
        )
        self.folder_tree_check.grid(row=0, column=2, sticky="w")
        self.expand_tree_button = ttk.Button(
            controls,
            text="Развернуть всё",
            command=lambda: self._set_folder_tree_open(True),
            state="disabled",
        )
        self.expand_tree_button.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.collapse_tree_button = ttk.Button(
            controls,
            text="Свернуть всё",
            command=lambda: self._set_folder_tree_open(False),
            state="disabled",
        )
        self.collapse_tree_button.grid(row=0, column=4, sticky="w", padx=(4, 0))
        ttk.Button(
            controls,
            text="Автоподгонка столбцов",
            command=self.autofit_columns,
        ).grid(row=0, column=5, sticky="w", padx=(4, 0))
        self.utilities_button = ttk.Button(
            controls,
            text="Утилиты",
            command=self._open_utilities,
            style="Accent.TButton",
        )
        self.utilities_button.grid(row=0, column=7, sticky="e", padx=(4, 0))
        ttk.Label(controls, text="Фильтр", style="Toolbar.TLabel").grid(
            row=0, column=8, padx=(12, 5)
        )
        self.filter_entry = ttk.Entry(
            controls, textvariable=self.filter_var, width=26
        )
        self.filter_entry.grid(row=0, column=9)
        ttk.Button(
            controls,
            text="×",
            width=3,
            command=lambda: self.filter_var.set(""),
        ).grid(row=0, column=10, padx=(4, 0))

        table_frame = ttk.Frame(self.root)
        table_frame.grid(row=4, column=0, sticky="nsew", padx=12)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame,
            columns=TABLE_FIELD_IDS,
            show="headings",
            selectmode="extended",
        )
        self.tree.heading(
            "#0",
            text="Структура папок",
            command=lambda: self.sort_by("#0"),
        )
        self.tree.column("#0", width=0, minwidth=0, stretch=False)
        for column_id, heading, width in TABLE_COLUMNS:
            self.tree.heading(
                column_id,
                text=heading,
                command=lambda name=column_id: self.sort_by(name),
            )
            self.tree.column(column_id, width=width, minwidth=55, stretch=False)
        vscroll = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.tree.yview
        )
        hscroll = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")

        bottom = ttk.Frame(self.root, padding=12)
        bottom.grid(row=5, column=0, sticky="ew")
        bottom.columnconfigure(6, weight=1)
        ttk.Button(
            bottom,
            text="Экспорт в XLSX",
            command=self.open_export,
            style="Accent.TButton",
        ).grid(row=0, column=0)
        self.unique_copy_button = ttk.Button(
            bottom,
            text="Копировать уникальные...",
            command=self.open_unique_copy,
            state="disabled",
        )
        self.unique_copy_button.grid(row=0, column=1, padx=(6, 0))
        self.audit_fix_button = ttk.Button(
            bottom,
            text="Исправить замечания...",
            command=self.open_audit_fixes,
            state="disabled",
        )
        self.audit_fix_button.grid(row=0, column=2, padx=(6, 0))
        # Shown only while the selection points at a group whose Track # totals
        # contradict the found numbering.
        self.numbering_fix_button = ttk.Button(
            bottom,
            text="Исправить нумерацию...",
            command=self.open_numbering_fix,
            style="Numbering.TButton",
        )
        self.numbering_fix_button.grid(row=0, column=3, padx=(6, 0))
        self.numbering_fix_button.grid_remove()
        ttk.Button(
            bottom,
            text="Копировать в буфер",
            command=self.copy_selected,
        ).grid(row=0, column=4, padx=6)
        ttk.Button(bottom, text="Открыть файл", command=self.open_selected_file).grid(
            row=0, column=5
        )
        # Its own row: with the numbering button the summary no longer fits
        # next to the actions and was clipped at the window edge.
        ttk.Label(bottom, textvariable=self.statistics_var, anchor="w").grid(
            row=1, column=0, columnspan=7, sticky="ew", pady=(7, 0)
        )

        self.context_menu = tk.Menu(self.root, tearoff=False)
        self.context_menu.add_command(
            label="Открыть файл", command=self.open_selected_file
        )
        self.context_menu.add_command(
            label="Открыть папку", command=self.open_selected_folder
        )
        self.context_menu.add_command(
            label="Полная информация", command=self.open_full_info
        )
        self.context_menu.add_command(
            label="Показать исходный трек", command=self.open_source_track
        )
        self.context_menu.add_command(
            label="Исправить нумерацию...",
            command=self.open_numbering_fix,
            state="disabled",
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Копировать путь", command=self.copy_path)
        self.context_menu.add_command(
            label="Копировать строку", command=self.copy_selected
        )

    def _bind_actions(self) -> None:
        self.filter_var.trace_add("write", lambda *_: self._schedule_filter())
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Button-1>", self._tree_group_click, add="+")
        self.tree.bind("<<TreeviewOpen>>", self._tree_group_opened)
        self.tree.bind("<<TreeviewClose>>", self._tree_group_closed)
        self.tree.bind("<Double-1>", self._tree_double_click)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind(
            "<ButtonRelease-1>",
            self._remember_column_widths,
            add="+",
        )
        self._bind_shortcut(self.root, "o", lambda _event: self.choose_folder())
        self._bind_shortcut(self.root, "e", lambda _event: self.open_export())
        self._bind_shortcut(self.root, "f", self._focus_filter)
        self._bind_shortcut(self.tree, "c", lambda _event: self.copy_selected())
        self.filter_entry.bind("<Escape>", lambda _event: self.filter_var.set(""))
        self.root.bind("<F5>", lambda _event: self.start_analysis())
        # Text fields: Tk's own Cut/Copy/Paste events know only Latin keysyms.
        for virtual, letter in (
            ("<<Cut>>", "x"),
            ("<<Copy>>", "c"),
            ("<<Paste>>", "v"),
        ):
            with contextlib.suppress(tk.TclError):
                self.root.event_add(virtual, *_russian_control_sequences(letter))

    @staticmethod
    def _bind_shortcut(widget, letter: str, callback) -> None:
        for sequence in _control_sequences(letter):
            # A Tk build without the Cyrillic keysym names must still start.
            with contextlib.suppress(tk.TclError):
                widget.bind(sequence, callback)

    def _focus_filter(self, _event=None) -> str:
        self.filter_entry.focus_set()
        self.filter_entry.select_range(0, "end")
        return "break"

    def _schedule_filter(self) -> None:
        if self._filter_job is not None:
            self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(250, self._run_scheduled_filter)

    def _run_scheduled_filter(self) -> None:
        self._filter_job = None
        self.refresh_table()

    def _remember_group_column_width(self, _event=None) -> None:
        if self.current_tab.get() == "folders":
            return
        if "tree" not in self.tree.cget("show"):
            return
        self.root.after_idle(self._capture_group_column_width)

    def _capture_group_column_width(self) -> None:
        if self.current_tab.get() == "folders":
            return
        if "tree" not in self.tree.cget("show"):
            return
        width = int(self.tree.column("#0", "width"))
        if width >= 260:
            self._group_column_width = width
            self.tree.column(
                "#0",
                width=width,
                minwidth=260,
                stretch=False,
            )

    def _remember_column_widths(self, _event=None) -> None:
        self.root.after_idle(self._capture_column_widths)

    def _capture_column_widths(self) -> None:
        for column_id in TABLE_FIELD_IDS:
            width = int(self.tree.column(column_id, "width"))
            if width >= 55:
                self._column_widths[column_id] = width
                self.tree.column(column_id, width=width, stretch=False)
        if "tree" not in self.tree.cget("show"):
            return
        width = int(self.tree.column("#0", "width"))
        if self.current_tab.get() == "folders":
            if width >= 180:
                self._folder_column_width = width
                self.tree.column("#0", width=width, stretch=False)
        elif width >= 260:
            self._group_column_width = width
            self.tree.column("#0", width=width, stretch=False)

    def _all_tree_items(self) -> list[str]:
        items: list[str] = []
        stack = list(reversed(self.tree.get_children("")))
        while stack:
            item_id = stack.pop()
            items.append(item_id)
            stack.extend(reversed(self.tree.get_children(item_id)))
        return items

    def autofit_columns(self) -> None:
        body_font_name = self.style.lookup("Treeview", "font") or "TkDefaultFont"
        heading_font_name = (
            self.style.lookup("Treeview.Heading", "font") or body_font_name
        )
        try:
            body_font = tkfont.nametofont(body_font_name)
        except tk.TclError:
            body_font = tkfont.nametofont("TkDefaultFont")
        try:
            heading_font = tkfont.nametofont(heading_font_name)
        except tk.TclError:
            heading_font = body_font

        show_tree = "tree" in self.tree.cget("show")
        columns = (["#0"] if show_tree else []) + TABLE_FIELD_IDS
        widths = {
            column_id: heading_font.measure(
                str(self.tree.heading(column_id, "text"))
            )
            + 34
            for column_id in columns
        }
        for item_id in self._all_tree_items():
            if show_tree:
                widths["#0"] = max(
                    widths["#0"],
                    body_font.measure(str(self.tree.item(item_id, "text"))) + 32,
                )
            values = self.tree.item(item_id, "values")
            for index, column_id in enumerate(TABLE_FIELD_IDS):
                if index >= len(values):
                    break
                widths[column_id] = max(
                    widths[column_id],
                    body_font.measure(str(values[index])) + 28,
                )

        for column_id in TABLE_FIELD_IDS:
            width = max(70, widths[column_id])
            self._column_widths[column_id] = width
            self.tree.column(column_id, width=width, stretch=False)
        if show_tree:
            minimum = 180 if self.current_tab.get() == "folders" else 260
            width = max(minimum, widths["#0"])
            if self.current_tab.get() == "folders":
                self._folder_column_width = width
            else:
                self._group_column_width = width
            self.tree.column("#0", width=width, stretch=False)

    def _open_utilities(self) -> None:
        root_folder: Path | None = None
        if self.folder_var.get().strip():
            root_folder = Path(self.folder_var.get())
        elif self.result is not None:
            root_folder = self.result.root
        context = UtilityContext(
            root_folder=root_folder,
            include_subfolders=self.include_subfolders_var.get(),
            excluded_folders=tuple(self.settings.excluded_folders),
            # Utilities cover the whole collection, so every format the app
            # understands is processed even if the analysis filter hides it.
            extensions=frozenset(SUPPORTED_FORMATS.values()),
            backup_enabled=self.settings.backup_before_tag_writes,
            on_backup_changed=self._set_backup_preference,
            on_completed=self._utility_completed,
        )
        dialog = UtilitiesDialog(self.root, context)
        self._style_toplevel(dialog.window)

    def _utility_completed(self, changed_root: Path) -> None:
        """Re-run the analysis so the table and the audit see the new covers."""
        if self.result is None:
            return
        analysed = self.result.root.resolve()
        changed = changed_root.resolve()
        # Either folder may contain the other: a run on the parent of the
        # analysed folder changed the analysed files too.
        if not (changed.is_relative_to(analysed) or analysed.is_relative_to(changed)):
            return
        if self.worker and self.worker.is_alive():
            return
        self.start_analysis()

    def apply_theme(self) -> None:
        dark = self.dark_theme_var.get()
        bg = "#1f2225" if dark else "#eeeae4"
        panel = "#2a2e32" if dark else "#fffdf9"
        field = "#24272a" if dark else "#ffffff"
        toolbar = "#30353a" if dark else "#f7f3ed"
        header = "#3b4147" if dark else "#4b5158"
        header_active = "#4a5158" if dark else "#5a6168"
        header_pressed = "#2f353a" if dark else "#3e444a"
        fg = "#f4efe8" if dark else "#2f3439"
        border = "#555b61" if dark else "#c9c5bf"
        orange = "#df7724" if dark else "#d96813"
        orange_active = "#f08a35" if dark else "#bf570d"
        orange_soft = "#56371f" if dark else "#fff0e3"
        selected = orange
        selected_fg = "#ffffff"
        disabled_fg = "#858b91" if dark else "#8a8f94"
        stop = "#b85549" if dark else "#bd5548"
        self.root.configure(bg=bg)
        self.root.option_add("*selectBackground", selected)
        self.root.option_add("*selectForeground", selected_fg)
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", fg)
        self.root.option_add("*TCombobox*Listbox.selectBackground", selected)
        self.root.option_add("*TCombobox*Listbox.selectForeground", selected_fg)
        self.style.configure(".", background=bg, foreground=fg)
        self.style.configure("TFrame", background=bg)
        self.style.configure("Header.TFrame", background=header)
        self.style.configure("Toolbar.TFrame", background=toolbar)
        self.style.configure("TLabelframe", background=bg, foreground=fg)
        self.style.configure(
            "TLabelframe.Label",
            background=bg,
            foreground=orange_active if dark else "#9f4608",
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure(
            "BrandIcon.TLabel",
            background=header,
            foreground="#ff9b4a",
            font=("TkDefaultFont", 24, "bold"),
        )
        self.style.configure(
            "BrandTitle.TLabel",
            background=header,
            foreground="#ffffff",
            font=("TkDefaultFont", 15, "bold"),
        )
        self.style.configure(
            "BrandSub.TLabel",
            background=header,
            foreground="#d9dde1",
            font=("TkDefaultFont", 9),
        )
        self.style.configure(
            "Toolbar.TLabel",
            background=toolbar,
            foreground=fg,
        )
        self.style.configure(
            "TButton",
            background=panel,
            foreground=fg,
            bordercolor=border,
            lightcolor=panel,
            darkcolor=border,
            padding=(9, 5),
        )
        self.style.map(
            "TButton",
            background=[
                ("pressed", orange_active),
                ("active", orange_soft),
                ("disabled", bg),
            ],
            foreground=[
                ("pressed", selected_fg),
                ("active", fg),
                ("disabled", disabled_fg),
            ],
            bordercolor=[
                ("focus", orange),
                ("active", orange),
                ("disabled", border),
            ],
        )
        self.style.configure(
            "Accent.TButton",
            background=orange,
            foreground=selected_fg,
            bordercolor=orange_active,
            lightcolor=orange,
            darkcolor=orange_active,
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.map(
            "Accent.TButton",
            background=[
                ("pressed", orange_active),
                ("active", "#ee8a38" if dark else "#eb7d28"),
                ("disabled", border),
            ],
            foreground=[
                ("active", selected_fg),
                ("pressed", selected_fg),
                ("disabled", disabled_fg),
            ],
        )
        # Same dark grey as the column headers, white text - used for the
        # «Исправить нумерацию» action so it reads as a companion of the table.
        self.style.configure(
            "Numbering.TButton",
            background=header,
            foreground="#ffffff",
            bordercolor=header,
            lightcolor=header,
            darkcolor=header_pressed,
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.map(
            "Numbering.TButton",
            background=[
                ("pressed", header_pressed),
                ("active", header_active),
            ],
            foreground=[
                ("pressed", "#ffffff"),
                ("active", "#ffffff"),
            ],
        )
        self.style.configure(
            "Stop.TButton",
            background=panel,
            foreground=stop,
            bordercolor=stop,
            lightcolor=panel,
            darkcolor=border,
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.map(
            "Stop.TButton",
            background=[("pressed", stop), ("active", stop), ("disabled", bg)],
            foreground=[
                ("pressed", "#ffffff"),
                ("active", "#ffffff"),
                ("disabled", disabled_fg),
            ],
        )
        self.style.configure("TCheckbutton", background=bg, foreground=fg)
        self.style.map(
            "TCheckbutton",
            background=[("active", bg)],
            foreground=[("disabled", disabled_fg), ("active", fg)],
        )
        self.style.configure(
            "Header.TCheckbutton",
            background=header,
            foreground="#f5f1ec",
        )
        self.style.map(
            "Header.TCheckbutton",
            background=[("active", header), ("selected", header)],
            foreground=[
                ("active", "#ffffff"),
                ("selected", "#ffffff"),
                ("disabled", "#aeb3b8"),
            ],
            indicatorcolor=[("selected", orange), ("!selected", "#f4efe8")],
        )
        self.style.configure(
            "Toolbar.TCheckbutton",
            background=toolbar,
            foreground=fg,
        )
        self.style.map(
            "Toolbar.TCheckbutton",
            background=[("active", toolbar), ("selected", toolbar)],
            foreground=[
                ("active", fg),
                ("selected", fg),
                ("disabled", disabled_fg),
            ],
            indicatorcolor=[("selected", orange), ("!selected", field)],
        )
        self.style.configure("TRadiobutton", background=bg, foreground=fg)
        self.style.configure(
            "Tab.TRadiobutton",
            padding=(11, 6),
            background=toolbar,
            foreground=fg,
            bordercolor=border,
            relief="flat",
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.map(
            "Tab.TRadiobutton",
            background=[
                ("selected", selected),
                ("active", orange_soft),
                ("pressed", orange_active),
            ],
            foreground=[
                ("selected", selected_fg),
                ("active", fg),
                ("pressed", selected_fg),
            ],
            indicatorcolor=[
                ("selected", selected),
                ("!selected", toolbar),
            ],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=field,
            foreground=fg,
            insertcolor=fg,
            selectbackground=selected,
            selectforeground=selected_fg,
            bordercolor=border,
        )
        self.style.map(
            "TEntry",
            fieldbackground=[("readonly", field), ("disabled", panel)],
            foreground=[("readonly", fg), ("disabled", disabled_fg)],
            selectbackground=[("focus", selected)],
            selectforeground=[("focus", selected_fg)],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=field,
            background=panel,
            foreground=fg,
            selectbackground=selected,
            selectforeground=selected_fg,
            bordercolor=border,
            arrowcolor=fg,
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", field)],
            background=[("readonly", panel), ("active", selected)],
            foreground=[("readonly", fg), ("active", selected_fg)],
            selectbackground=[("readonly", selected)],
            selectforeground=[("readonly", selected_fg)],
        )
        self.style.configure(
            "Treeview",
            background=field,
            fieldbackground=field,
            foreground=fg,
            rowheight=23,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
        )
        self.style.map(
            "Treeview",
            background=[("selected", selected)],
            foreground=[("selected", selected_fg)],
        )
        self.style.configure(
            "Treeview.Heading",
            background=header,
            foreground="#ffffff",
            font=("TkDefaultFont", 9, "bold"),
            padding=(7, 5),
            bordercolor=border,
            lightcolor=header,
            darkcolor=header,
        )
        self.style.map(
            "Treeview.Heading",
            background=[("active", orange), ("pressed", orange_active)],
            foreground=[
                ("active", selected_fg),
                ("pressed", selected_fg),
            ],
        )
        self.style.configure(
            "Horizontal.TProgressbar",
            background=orange,
            troughcolor=field,
            bordercolor=border,
            lightcolor=orange,
            darkcolor=orange_active,
        )
        self.info_text.configure(
            bg=field,
            fg=fg,
            insertbackground=fg,
            selectbackground=selected,
            selectforeground=selected_fg,
        )
        self.cover_label.configure(bg=field, fg=fg)
        self.context_menu.configure(
            bg=panel,
            fg=fg,
            activebackground=selected,
            activeforeground=selected_fg,
            disabledforeground=disabled_fg,
        )
        colors = STATUS_ROW_COLORS_DARK if dark else STATUS_ROW_COLORS_LIGHT
        for status, color in colors.items():
            self.tree.tag_configure(status, background=color, foreground=fg)
        group_colors = {
            "GroupDuplicate": ("#6a411f", "#fff5eb")
            if dark
            else ("#f7d7bd", "#71340b"),
            "GroupVariation": ("#29465d", "#eef7ff")
            if dark
            else ("#d7eafb", "#174e78"),
            "GroupConflict": ("#613733", "#fff1ef")
            if dark
            else ("#f4d2cd", "#7a2e27"),
            "GroupRelated": ("#41474d", "#f2f3f4")
            if dark
            else ("#e0e2e4", "#333a40"),
        }
        for tag, (background, foreground) in group_colors.items():
            self.tree.tag_configure(
                tag,
                background=background,
                foreground=foreground,
                font=("TkDefaultFont", 9, "bold"),
            )
        self.tree.tag_configure(
            "Folder",
            background=toolbar,
            foreground=fg,
            font=("TkDefaultFont", 9, "bold"),
        )
        self.tree.tag_configure(
            "FolderIssue",
            background="#613733" if dark else "#f8dfda",
            foreground="#fff1ef" if dark else "#7a2e27",
            font=("TkDefaultFont", 9, "bold"),
        )
        # A folder whose release is missing files according to the tags: dark
        # red, almost burgundy, so it is visible without opening the folder.
        # Such a row carries this tag alone: ttk gives tags created earlier
        # (Folder) priority whatever their order in the row's tag list.
        self.tree.tag_configure(
            "FolderGap",
            background="#5a1c1c" if dark else "#591a1a",
            foreground="#ffe9e7" if dark else "#fff2f0",
            font=("TkDefaultFont", 9, "bold"),
        )
        audit_colors = {
            "AuditGroup": (
                "#41474d" if dark else "#e5e7e9",
                "#f5f6f7" if dark else "#2f3439",
            ),
            "AuditError": (
                "#613733" if dark else "#f8dfda",
                "#fff1ef" if dark else "#7a2e27",
            ),
            "AuditWarning": (
                "#29465d" if dark else "#e2effb",
                "#eef7ff" if dark else "#174e78",
            ),
            "AuditInfo": (
                "#294b36" if dark else "#e5f3e8",
                "#effbf2" if dark else "#255f2c",
            ),
        }
        for tag, (background, foreground) in audit_colors.items():
            self.tree.tag_configure(
                tag,
                background=background,
                foreground=foreground,
                font=(
                    "TkDefaultFont",
                    9,
                    "bold" if tag == "AuditGroup" else "normal",
                ),
            )

    def _theme_changed(self) -> None:
        self.apply_theme()
        self.settings.dark_theme = self.dark_theme_var.get()
        self._autosave()

    def _tk_palette(self) -> tuple[str, str, str, str, str]:
        if self.dark_theme_var.get():
            return "#1f2225", "#24272a", "#f4efe8", "#df7724", "#ffffff"
        return "#eeeae4", "#ffffff", "#2f3439", "#d96813", "#ffffff"

    def _style_text_widget(self, widget: tk.Text) -> None:
        _bg, field, fg, selected, selected_fg = self._tk_palette()
        widget.configure(
            bg=field,
            fg=fg,
            insertbackground=fg,
            selectbackground=selected,
            selectforeground=selected_fg,
        )

    def _style_toplevel(self, window: tk.Toplevel) -> None:
        bg, _field, _fg, _selected, _selected_fg = self._tk_palette()
        window.configure(bg=bg)

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Выберите корневую директорию",
            initialdir=self.folder_var.get() or None,
        )
        if selected:
            self.folder_var.set(selected)

    def _reset_progress(self) -> None:
        self.progress["value"] = 0
        self.progress_percent_var.set("0%")
        self.progress_state_var.set("Анализ не запущен")
        self.files_count_var.set("Файлов: 0")
        self.folders_count_var.set("Папок: 0")
        self.variations_count_var.set("Вариаций: 0")

    def _clear_info(self) -> None:
        self._set_text(self.info_text, "Выберите трек в таблице")
        self.cover_photo = None
        self.cover_label.configure(image="", text="Обложка не выбрана")

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def start_analysis(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        folder = Path(self.folder_var.get())
        if not self.folder_var.get() or not folder.is_dir():
            messagebox.showwarning(
                APP_NAME,
                "Пожалуйста, выберите корневую директорию",
                parent=self.root,
            )
            return
        self._clear_results()
        self.filter_var.set("")
        self._reset_progress()
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        selected_formats = [
            name for name, variable in self.format_vars.items() if variable.get()
        ]
        include_subfolders = self.include_subfolders_var.get()
        use_tags = self.use_tags_var.get()
        detect_variations = self.detect_variations_var.get()
        check_track_gaps = self.check_track_gaps_var.get()
        excluded_folders = list(self.settings.excluded_folders)
        variation_markers = list(self.settings.variation_markers)

        def progress(percent: int, state: str, files: int, folders: int, variations: int):
            self.events.put(
                ("progress", percent, state, files, folders, variations)
            )

        def run() -> None:
            try:
                result = analyze_collection(
                    root=folder,
                    include_subfolders=include_subfolders,
                    selected_formats=selected_formats,
                    excluded_folders=excluded_folders,
                    use_tags=use_tags,
                    detect_variations=detect_variations,
                    check_track_gaps=check_track_gaps,
                    variation_markers=variation_markers,
                    stop_event=self.stop_event,
                    progress=progress,
                )
                self.events.put(("result", result))
            except AnalysisStopped:
                self.events.put(("stopped",))
            except (
                NoAudioFilesError,
                NoSelectedFormatsError,
                MetadataDependencyError,
            ) as exc:
                self.events.put(("known_error", str(exc)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def stop_analysis(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.stop_button.configure(state="disabled")
            self.progress_state_var.set("Остановка анализа...")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _, percent, state, files, folders, variations = event
                    self.progress["value"] = percent
                    self.progress_percent_var.set(f"{percent}%")
                    self.progress_state_var.set(state)
                    self.files_count_var.set(f"Файлов: {files}")
                    self.folders_count_var.set(f"Папок: {folders}")
                    self.variations_count_var.set(f"Вариаций: {variations}")
                elif kind == "result":
                    self._analysis_finished(event[1])
                elif kind == "stopped":
                    self._analysis_stopped()
                elif kind == "known_error":
                    self._analysis_failed(event[1], generic=False)
                elif kind == "error":
                    self._analysis_failed(event[1], generic=True)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _restore_buttons(self) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _analysis_finished(self, result: AnalysisResult) -> None:
        self.result = result
        self.track_by_id = {track.id: track for track in result.tracks}
        self.variation_source_ids = {
            track.source_track_id
            for track in result.tracks
            if track.source_track_id
        }
        self.issue_by_id = {issue.id: issue for issue in result.completeness_issues}
        self.audit_issue_by_id = {
            issue.id: issue for issue in result.audit_issues
        }
        self._restore_buttons()
        self.unique_copy_button.configure(state="normal")
        self._reset_sort_to_track_number()
        self.refresh_table()
        self._update_statistics()
        self._sync_settings_from_ui()
        self._autosave()

    def _reset_sort_to_track_number(self) -> None:
        """A fresh scan is shown in track order: 1, 2, 3 … regardless of titles."""
        self.sort_column = "track_number"
        self.sort_reverse = False

    def _clear_results(self) -> None:
        """Drop the previous analysis from memory and from every widget."""
        self.result = None
        self.track_by_id.clear()
        self.variation_source_ids.clear()
        self.issue_by_id.clear()
        self.audit_issue_by_id.clear()
        self.audit_item_track_ids.clear()
        self.visible_tracks.clear()
        self.tree.delete(*self.tree.get_children())
        self.statistics_var.set("Статистика: —")
        self.shown_count_var.set("0 из 0")
        self.unique_copy_button.configure(state="disabled")
        self.audit_fix_button.configure(state="disabled")
        self._numbering_plan = None
        self.numbering_fix_button.grid_remove()
        self.context_menu.entryconfigure("Исправить нумерацию...", state="disabled")
        self._clear_info()

    def _analysis_stopped(self) -> None:
        self._restore_buttons()
        self.progress_state_var.set("Анализ остановлен")
        self._clear_results()

    def _analysis_failed(self, reason: str, generic: bool) -> None:
        self._restore_buttons()
        self.progress_state_var.set("Ошибка анализа")
        self._clear_results()
        title = "Произошла ошибка при анализе" if generic else reason
        detail = f"\n\nПричина: {reason}" if generic and reason else ""
        messagebox.showerror(APP_NAME, title + detail, parent=self.root)

    def refresh_table(self) -> None:
        if not self.result:
            return
        active = self.current_tab.get()
        self.folder_tree_check.configure(
            state="normal" if active == "folders" else "disabled"
        )
        tree_controls_enabled = (
            active == "folders" and self.folder_tree_mode_var.get()
        )
        tree_control_state = "normal" if tree_controls_enabled else "disabled"
        self.expand_tree_button.configure(state=tree_control_state)
        self.collapse_tree_button.configure(state=tree_control_state)
        self.audit_fix_button.configure(
            state=(
                "normal"
                if any(issue.fixable for issue in self.result.audit_issues)
                else "disabled"
            )
        )
        query = self.filter_var.get().strip().casefold()
        tracks = list(self.result.tracks)
        if active == "duplicates":
            tracks = [
                track
                for track in tracks
                if track.status in (TrackStatus.DUPLICATE, TrackStatus.CONFLICT)
            ]
        elif active == "variations":
            tracks = [
                track for track in tracks if track.status == TrackStatus.VARIATION
            ]
        elif active == "unique":
            tracks = [
                track for track in tracks if track.status == TrackStatus.UNIQUE
            ]
        self.group_labels.clear()
        self.group_members.clear()
        self.audit_item_track_ids.clear()
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())

        if active == "audit":
            issues = [
                issue
                for issue in self.result.audit_issues
                if (
                    not query
                    or query in issue.search_text()
                    or (
                        issue.track_id in self.track_by_id
                        and query
                        in self.track_by_id[issue.track_id].search_text()
                    )
                )
            ]
            visible_ids = {issue.track_id for issue in issues}
            self.visible_tracks = [
                track for track in tracks if track.id in visible_ids
            ]
            self._insert_audit_groups(issues)
        elif active == "folders":
            if query:
                tracks = [track for track in tracks if query in track.search_text()]
            if self.sort_column:
                tracks.sort(
                    key=lambda track: self._sort_key(
                        track, self.sort_column or ""
                    ),
                    reverse=self.sort_reverse,
                )
                # Stable second pass keeps the tree hierarchy while preserving
                # the requested order inside each folder.
                tracks.sort(key=lambda track: track.relative_folder.casefold())
            else:
                tracks.sort(key=self._folder_sort_key)
            self.visible_tracks = tracks
            if self.folder_tree_mode_var.get():
                self._insert_folder_tree(tracks)
            else:
                self.tree.configure(show="headings")
                self.tree.column("#0", width=0, minwidth=0, stretch=False)
                for track in tracks:
                    self._insert_track_row("", track)
        else:
            entries, visible_tracks = self._build_relation_groups(tracks, query)
            self.visible_tracks = visible_tracks
            self._insert_relation_groups(entries)

        for item_id in selected:
            if self.tree.exists(item_id):
                self.tree.selection_add(item_id)
        self.shown_count_var.set(
            f"{len(self.visible_tracks)} из {len(self.result.tracks)}"
        )
        self._refresh_headings()
        self._refresh_numbering_button()

    def _tree_mode_changed(self) -> None:
        self.settings.folder_tree_mode = self.folder_tree_mode_var.get()
        self.refresh_table()
        self._autosave()

    def _set_folder_tree_open(self, opened: bool) -> None:
        if (
            self.current_tab.get() != "folders"
            or not self.folder_tree_mode_var.get()
        ):
            return
        top_level = set(self.tree.get_children(""))
        for item_id in self._all_tree_items():
            self.tree.item(
                item_id,
                open=opened or item_id in top_level,
            )

    def _related_component(self, start_id: str) -> set[str]:
        component: set[str] = set()
        stack = [start_id]
        while stack:
            current = stack.pop()
            if current in component or current not in self.track_by_id:
                continue
            component.add(current)
            stack.extend(self.track_by_id[current].related_track_ids)
        return component

    def _group_representative(
        self, members: list[Track], selected_ids: set[str]
    ) -> Track:
        source_ids = {
            track.source_track_id for track in members if track.source_track_id
        }
        for track in members:
            if track.id in source_ids:
                return track
        selected_members = [track for track in members if track.id in selected_ids]
        priority = {
            TrackStatus.DUPLICATE: 0,
            TrackStatus.CONFLICT: 1,
            TrackStatus.UNIQUE: 2,
            TrackStatus.VARIATION: 3,
        }
        return min(
            selected_members or members,
            key=lambda track: (
                priority[track.status],
                track.base_title.casefold(),
                track.filename.casefold(),
            ),
        )

    def _group_member_sort_key(self, track: Track):
        priority = {
            TrackStatus.UNIQUE: 0,
            TrackStatus.DUPLICATE: 1,
            TrackStatus.CONFLICT: 2,
            TrackStatus.VARIATION: 3,
        }
        return (
            0 if track.id in self.variation_source_ids else 1,
            priority[track.status],
            track.variation.casefold(),
            track.relative_folder.casefold(),
            track.filename.casefold(),
        )

    def _build_relation_groups(
        self, selected_tracks: list[Track], query: str
    ) -> tuple[list[tuple[Track, list[Track]]], list[Track]]:
        selected_ids = {track.id for track in selected_tracks}
        processed: set[str] = set()
        entries: list[tuple[Track, list[Track]]] = []
        visible_selected: list[Track] = []

        for track in selected_tracks:
            if track.id in processed:
                continue
            component_ids = self._related_component(track.id)
            selected_component_ids = component_ids & selected_ids
            processed.update(selected_component_ids)
            members = [
                self.track_by_id[item_id]
                for item_id in component_ids
                if item_id in self.track_by_id
            ]
            members.sort(key=self._group_member_sort_key)
            if query and not any(query in member.search_text() for member in members):
                continue
            selected_members = [
                member for member in members if member.id in selected_component_ids
            ]
            visible_selected.extend(selected_members)
            representative = self._group_representative(members, selected_ids)
            entries.append((representative, members))

        def entry_sort_key(entry: tuple[Track, list[Track]]):
            representative, members = entry
            if self.sort_column == "#0":
                # Same text the row shows: «Дубликаты: <название> · N файлов».
                group_kind, _tag = self._group_kind(members)
                base_title = (
                    representative.base_title or representative.filename_title
                )
                return f"{group_kind}: {base_title}".casefold()
            if self.sort_column:
                return self._sort_key(
                    representative, self.sort_column or ""
                )
            return (
                representative.base_title.casefold(),
                representative.relative_folder.casefold(),
                representative.filename.casefold(),
            )

        entries.sort(
            key=entry_sort_key,
            reverse=self.sort_reverse if self.sort_column else False,
        )
        return entries, visible_selected

    def _group_kind(self, members: list[Track]) -> tuple[str, str]:
        statuses = {member.status for member in members}
        if TrackStatus.VARIATION in statuses:
            return "Вариация", "GroupVariation"
        if statuses == {TrackStatus.DUPLICATE}:
            return "Дубликаты", "GroupDuplicate"
        if TrackStatus.CONFLICT in statuses:
            return "Конфликт", "GroupConflict"
        return "Связанные файлы", "GroupRelated"

    def _insert_relation_groups(
        self, entries: list[tuple[Track, list[Track]]]
    ) -> None:
        self.tree.configure(show=("tree", "headings"))
        self.tree.heading("#0", text="Группы и файлы")
        width = self._group_column_width
        if width is None:
            width = _responsive_group_width(self.tree.winfo_width())
        self.tree.column(
            "#0",
            width=width,
            minwidth=260,
            stretch=False,
        )
        for representative, members in entries:
            if len(members) == 1:
                self._insert_track_row("", representative)
                continue
            group_kind, group_tag = self._group_kind(members)
            group_id = "group::" + min(member.id for member in members)
            base_title = representative.base_title or representative.filename_title
            count = len(members)
            label = f"{group_kind}: {base_title} · {count} {files_word(count)}"
            folders = {member.relative_folder for member in members}
            variations = sorted(
                {member.variation for member in members if member.variation}
            )
            warnings = sorted(
                {
                    member.collection_warning
                    for member in members
                    if member.collection_warning
                }
            )
            self.tree.insert(
                "",
                "end",
                iid=group_id,
                text=f"[+] {label}",
                values=self._row_values(
                    status=f"{group_kind} · {len(members)}",
                    base_title=base_title,
                    variation=", ".join(variations) or "—",
                    relation="Нажмите [+], чтобы показать связанные файлы",
                    collection_warning="; ".join(warnings) or "—",
                    relative_folder=(
                        next(iter(folders))
                        if len(folders) == 1
                        else f"{len(folders)} {folders_word(len(folders))}"
                    ),
                ),
                tags=(group_tag,),
                open=False,
            )
            self.group_labels[group_id] = label
            self.group_members[group_id] = [member.id for member in members]
            for member in members:
                self._insert_track_row(group_id, member)

    def _insert_audit_groups(
        self,
        issues: list[MetadataAuditIssue],
    ) -> None:
        grouped: dict[str, list[MetadataAuditIssue]] = {}
        for issue in issues:
            grouped.setdefault(issue.track_id, []).append(issue)
        ordered_ids = sorted(
            grouped,
            key=lambda track_id: (
                self.track_by_id[track_id].relative_folder.casefold(),
                self.track_by_id[track_id].filename.casefold(),
            )
            if track_id in self.track_by_id
            else ("", ""),
        )
        if self.sort_column:
            def audit_sort_key(track_id: str):
                track = self.track_by_id.get(track_id)
                first = min(
                    grouped[track_id],
                    key=lambda issue: (
                        issue.severity.order,
                        issue.category.value,
                        issue.field,
                    ),
                )
                audit_values = {
                    "status": first.severity.order,
                    "base_title": first.category.value.casefold(),
                    "variation": first.field_label.casefold(),
                    "relation": first.current_value.casefold(),
                    "collection_warning": first.message.casefold(),
                    "artist": first.confidence.value.casefold(),
                }
                if self.sort_column in audit_values:
                    return audit_values[self.sort_column]
                if track is None:
                    return ""
                return self._sort_key(track, self.sort_column or "")

            ordered_ids.sort(
                key=audit_sort_key,
                reverse=self.sort_reverse,
            )
        self.tree.configure(show=("tree", "headings"))
        self.tree.heading("#0", text="Файлы и замечания")
        width = self._group_column_width
        if width is None:
            width = _responsive_group_width(self.tree.winfo_width())
        self.tree.column("#0", width=width, minwidth=260, stretch=False)
        for track_id in ordered_ids:
            track = self.track_by_id.get(track_id)
            if track is None:
                continue
            track_issues = sorted(
                grouped[track_id],
                key=lambda issue: (
                    issue.severity.order,
                    issue.category.value,
                    issue.field,
                ),
            )
            errors = sum(
                issue.severity == AuditSeverity.ERROR
                for issue in track_issues
            )
            warnings = sum(
                issue.severity == AuditSeverity.WARNING
                for issue in track_issues
            )
            safe_fixes = sum(issue.safe_fix for issue in track_issues)
            count = len(track_issues)
            label = f"{track.filename} · замечаний: {count}"
            group_id = f"audit-group::{track.id}"
            self.tree.insert(
                "",
                "end",
                iid=group_id,
                text=f"[+] {label}",
                values=self._row_values(
                    status=f"Ошибок {errors} · предупреждений {warnings}",
                    track_number=track.track_number,
                    base_title=track.album or track.base_title,
                    variation=f"Безопасных исправлений: {safe_fixes}",
                    relation="Нажмите [+], чтобы показать замечания",
                    relative_folder=track.relative_folder,
                    filename=track.filename,
                    artist=track.artist,
                ),
                tags=("AuditGroup",),
                open=False,
            )
            self.group_labels[group_id] = label
            self.group_members[group_id] = [track.id]
            self.audit_item_track_ids[group_id] = track.id
            for issue in track_issues:
                child_id = f"audit-issue::{issue.id}"
                relation = issue.current_value
                if issue.suggested_value:
                    relation = (
                        f"{issue.current_value or '—'} → "
                        f"{issue.suggested_value}"
                    )
                self.tree.insert(
                    group_id,
                    "end",
                    iid=child_id,
                    text=issue.message,
                    values=self._row_values(
                        status=issue.severity.decorated,
                        track_number=track.track_number,
                        base_title=issue.category.value,
                        variation=issue.field_label,
                        relation=relation or "—",
                        collection_warning=issue.message,
                        relative_folder=track.relative_folder,
                        filename=track.filename,
                        artist=issue.confidence.value,
                    ),
                    tags=(f"Audit{issue.severity.name.title()}",),
                )
                self.audit_item_track_ids[child_id] = track.id

    def _set_group_label(self, item_id: str, opened: bool) -> None:
        label = self.group_labels.get(item_id)
        if label and self.tree.exists(item_id):
            self.tree.item(item_id, text=f"{'[-]' if opened else '[+]'} {label}")

    def _tree_group_click(self, event):
        item_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if item_id not in self.group_labels or column != "#0":
            return None
        opened = not bool(self.tree.item(item_id, "open"))
        self.tree.item(item_id, open=opened)
        self._set_group_label(item_id, opened)
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        return "break"

    def _tree_group_opened(self, _event=None) -> None:
        item_id = self.tree.focus()
        if item_id in self.group_labels:
            self.root.after_idle(
                lambda: self._set_group_label(
                    item_id, bool(self.tree.item(item_id, "open"))
                )
            )

    def _tree_group_closed(self, _event=None) -> None:
        item_id = self.tree.focus()
        if item_id in self.group_labels:
            self.root.after_idle(lambda: self._set_group_label(item_id, False))

    def _tree_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id in self.group_labels:
            return "break"
        self.open_selected_file()
        return None

    def _folder_sort_key(self, track: Track):
        disc, _disc_total = parse_position(track.disc_number)
        number, _track_total = parse_position(track.track_number)
        return (
            track.relative_folder.casefold(),
            disc or 1,
            number is None,
            number or 0,
            track.base_title.casefold(),
            track.filename.casefold(),
        )

    def _insert_track_row(self, parent: str, track: Track) -> None:
        values = track.table_row(TABLE_FIELD_IDS)
        number, _total = parse_position(track.track_number)
        tree_text = f"{number:02d} · {track.filename}" if number else track.filename
        self.tree.insert(
            parent,
            "end",
            iid=track.id,
            text=tree_text,
            values=values,
            tags=(track.status.value,),
        )

    def _row_values(self, **values: str) -> list[str]:
        return [values.get(column[0], "") for column in TABLE_COLUMNS]

    def _folder_parts(self, relative_folder: str) -> tuple[str, ...]:
        if relative_folder == "(корень)":
            return ()
        return tuple(part for part in Path(relative_folder).parts if part not in (".", ""))

    def _folders_with_missing_numbers(self) -> set[tuple[str, ...]]:
        """Folders whose release is short of files according to the tags."""
        if not self.result:
            return set()
        return {
            self._folder_parts(issue.relative_folder)
            for issue in self.result.completeness_issues
            if issue.missing_numbers
        }

    def _insert_folder_tree(self, tracks: list[Track]) -> None:
        if not self.result:
            return
        self.tree.configure(show=("tree", "headings"))
        self.tree.column(
            "#0",
            width=self._folder_column_width or 285,
            minwidth=180,
            stretch=False,
        )
        root_id = "folder-root::node"
        root_name = self.result.root.name or str(self.result.root)
        folders_with_gaps = self._folders_with_missing_numbers()
        root_tags = ("FolderGap",) if () in folders_with_gaps else ("Folder",)
        self.tree.insert(
            "",
            "end",
            iid=root_id,
            text=f"📁 {root_name}",
            values=self._row_values(
                status=f"Папка · {len(tracks)} {files_word(len(tracks))}"
            ),
            tags=root_tags,
            open=True,
        )
        folder_ids: dict[tuple[str, ...], str] = {(): root_id}

        def ensure_folder(parts: tuple[str, ...]) -> str:
            if parts in folder_ids:
                return folder_ids[parts]
            parent_parts = parts[:-1]
            parent = ensure_folder(parent_parts)
            item_id = "folder-path::" + "/".join(parts)
            tags = ("FolderGap",) if parts in folders_with_gaps else ("Folder",)
            self.tree.insert(
                parent,
                "end",
                iid=item_id,
                text=f"📁 {parts[-1]}",
                values=self._row_values(status="Папка"),
                tags=tags,
                open=True,
            )
            folder_ids[parts] = item_id
            return item_id

        for track in tracks:
            ensure_folder(self._folder_parts(track.relative_folder))

        visible_ids = {track.id for track in tracks}
        visible_issue_ids = {
            track.collection_issue_id
            for track in tracks
            if track.collection_issue_id
        }
        for issue in self.result.completeness_issues:
            if issue.id not in visible_issue_ids:
                continue
            parent = ensure_folder(self._folder_parts(issue.relative_folder))
            label = issue.album or "Альбом без тега Album"
            if issue.disc > 1:
                label += f" · диск {issue.disc}"
            self.tree.insert(
                parent,
                "end",
                iid=f"issue::{issue.id}",
                text=f"⚠ {label}",
                values=self._row_values(
                    status=(
                        "⚠ Нумерация"
                        if issue.inconsistent_totals and not issue.missing_numbers
                        else "⚠ Пропуски"
                    ),
                    collection_warning=issue.short_text,
                    album=issue.album,
                    relative_folder=issue.relative_folder,
                ),
                tags=("FolderIssue",),
            )
        for track in tracks:
            if track.id not in visible_ids:
                continue
            parent = ensure_folder(self._folder_parts(track.relative_folder))
            self._insert_track_row(parent, track)

    def _sort_key(self, track: Track, column: str):
        if column in ("track_number", "#0"):
            number, _total = parse_position(track.track_number)
            if column == "#0":
                return (
                    number is None,
                    number or 0,
                    track.filename.casefold(),
                )
            return (number is None, number or 0)
        numeric = {
            "duration": track.duration_seconds,
            "bitrate": track.bitrate,
            "size_mb": track.size_mb,
            "year": int(track.year[:4]) if track.year[:4].isdigit() else None,
        }
        if column in numeric:
            value = numeric[column]
            return (value is None, value or 0)
        return str(track.table_value(column)).casefold()

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self.refresh_table()

    def _refresh_headings(self) -> None:
        if self.current_tab.get() == "audit":
            zero_title = "Файлы и замечания"
        elif self.current_tab.get() == "folders" and self.folder_tree_mode_var.get():
            zero_title = "Структура папок"
        else:
            zero_title = "Группы и файлы"
        zero_arrow = ""
        if self.sort_column == "#0":
            zero_arrow = " ▼" if self.sort_reverse else " ▲"
        self.tree.heading("#0", text=zero_title + zero_arrow)
        audit_headings = {
            "status": "Уровень",
            "base_title": "Категория",
            "variation": "Поле",
            "relation": "Было → Предложение",
            "collection_warning": "Описание",
            "relative_folder": "Папка",
            "filename": "Файл",
            "artist": "Уверенность",
        }
        for column_id, heading, _width in TABLE_COLUMNS:
            if self.current_tab.get() == "audit":
                heading = audit_headings.get(column_id, heading)
            arrow = ""
            if column_id == self.sort_column:
                arrow = " ▼" if self.sort_reverse else " ▲"
            self.tree.heading(column_id, text=heading + arrow)

    def _update_statistics(self) -> None:
        if not self.result:
            self.statistics_var.set("Статистика: —")
            return
        result = self.result
        self.statistics_var.set(
            "Статистика: "
            f"всего {len(result.tracks)} · "
            f"уникальных {result.count(TrackStatus.UNIQUE)} · "
            f"дубликатов {result.count(TrackStatus.DUPLICATE)} · "
            f"вариаций {result.count(TrackStatus.VARIATION)} · "
            f"конфликтов {result.count(TrackStatus.CONFLICT)} · "
            f"пропущено номеров {result.missing_track_count} "
            f"в {len(result.completeness_issues)} группах · "
            f"аудит: ошибок {result.audit_count(AuditSeverity.ERROR)}, "
            f"предупреждений {result.audit_count(AuditSeverity.WARNING)}, "
            f"рекомендаций {result.audit_count(AuditSeverity.INFO)} · "
            f"папок {result.folders_scanned} · "
            f"{result.total_size_mb:.2f} MB"
        )

    def _selected_track(self) -> Track | None:
        selection = self.tree.selection()
        if not selection:
            return None
        focused = self.tree.focus()
        for track_id in (focused, *selection):
            mapped_id = self.audit_item_track_ids.get(track_id, track_id)
            track = self.track_by_id.get(mapped_id)
            if track is not None:
                return track
        return None

    def _selection_changed(self, _event=None) -> None:
        self._refresh_numbering_button()
        focused = self.tree.focus()
        if focused.startswith("audit-issue::"):
            audit_issue = self.audit_issue_by_id.get(
                focused.removeprefix("audit-issue::")
            )
            if audit_issue:
                self._show_audit_issue_in_panel(audit_issue)
                return
        if focused.startswith("audit-group::"):
            self._show_audit_group_in_panel(focused)
            return
        if focused in self.group_members:
            self._show_group_in_panel(focused)
            return
        folder_parts = self._folder_parts_from_tree_id(focused)
        if folder_parts is not None:
            self._show_folder_in_panel(folder_parts)
            return
        track = self._selected_track()
        if track:
            self._show_track_in_panel(track)
            return
        if focused.startswith("issue::"):
            issue = self.issue_by_id.get(focused.removeprefix("issue::"))
            if issue:
                self._show_issue_in_panel(issue)

    def _show_audit_group_in_panel(self, group_id: str) -> None:
        track_id = group_id.removeprefix("audit-group::")
        track = self.track_by_id.get(track_id)
        if track is None or not self.result:
            return
        issues = [
            issue
            for issue in self.result.audit_issues
            if issue.track_id == track_id
        ]
        lines = [
            "АУДИТ МЕТАДАННЫХ",
            track.filename,
            f"Папка: {track.relative_folder}",
            "",
            "Нажмите [+], чтобы раскрыть замечания.",
            "",
        ]
        for issue in issues:
            lines.append(
                f"• {issue.severity.value}: {issue.field_label} — "
                f"{issue.message}"
            )
        self._set_text(self.info_text, "\n".join(lines))
        self._load_cover(track, self.cover_label, 190)

    def _show_audit_issue_in_panel(self, issue: MetadataAuditIssue) -> None:
        track = self.track_by_id.get(issue.track_id)
        if track is None:
            return
        lines = [
            "АУДИТ МЕТАДАННЫХ",
            f"Уровень: {issue.severity.value}",
            f"Категория: {issue.category.value}",
            f"Поле: {issue.field_label}",
            f"Файл: {track.filename}",
            f"Папка: {track.relative_folder}",
            "",
            issue.message,
        ]
        if issue.current_value:
            lines.extend(["", f"Сейчас: {issue.current_value}"])
        if issue.suggested_value:
            lines.extend(
                [
                    f"Предложение: {issue.suggested_value}",
                    f"Уверенность: {issue.confidence.value}",
                    (
                        "Можно выбрать в окне безопасного исправления."
                        if issue.safe_fix
                        else "Требуется ручная проверка."
                    ),
                ]
            )
        self._set_text(self.info_text, "\n".join(lines))
        self._load_cover(track, self.cover_label, 190)

    def _show_folder_in_panel(self, parts: tuple[str, ...]) -> None:
        """Summary of a folder row in the tree: its album or whole subtree."""
        if not self.result:
            return
        result = self.result
        inside = {
            folder
            for folder in {track.relative_folder for track in result.tracks}
            if self._folder_parts(folder)[: len(parts)] == parts
        }
        tracks = [track for track in result.tracks if track.relative_folder in inside]
        track_ids = {track.id for track in tracks}
        cover_file = find_folder_cover(result.root.joinpath(*parts))
        self._set_text(
            self.info_text,
            folder_summary_text(
                parts[-1] if parts else (result.root.name or str(result.root)),
                str(Path(*parts)) if parts else "(корень)",
                tracks,
                [
                    issue
                    for issue in result.completeness_issues
                    if issue.relative_folder in inside
                ],
                [issue for issue in result.audit_issues if issue.track_id in track_ids],
                cover_file.name if cover_file else "",
            ),
        )
        with_cover = next(
            (
                track
                for track in sorted(tracks, key=self._folder_sort_key)
                if track.cover_hash and not track.cover_error
            ),
            None,
        )
        if with_cover is not None:
            self._load_cover(with_cover, self.cover_label, 190)
        else:
            self.cover_photo = None
            self.cover_label.configure(image="", text="Встроенной обложки\nв папке нет")

    def _show_group_in_panel(self, group_id: str) -> None:
        members = [
            self.track_by_id[track_id]
            for track_id in self.group_members.get(group_id, [])
            if track_id in self.track_by_id
        ]
        if not members:
            return
        kind, _tag = self._group_kind(members)
        lines = [
            f"{kind.upper()}",
            self.group_labels.get(group_id, ""),
            "",
            "Нажмите [+] слева от группы, чтобы раскрыть файлы.",
            "",
        ]
        for index, track in enumerate(members, start=1):
            role = (
                "исходный трек"
                if track.id in self.variation_source_ids
                else track.status.value.casefold()
            )
            lines.extend(
                [
                    f"{index}. {track.filename}",
                    f"   Роль: {role}",
                    f"   Папка: {track.relative_folder}",
                    f"   Формат: {track.format}",
                ]
            )
        self._set_text(self.info_text, "\n".join(lines))
        self.cover_photo = None
        self.cover_label.configure(
            image="", text="Выберите файл\nвнутри раскрытой группы"
        )

    def _track_info_text(self, track: Track) -> str:
        source = self.track_by_id.get(track.source_track_id or "")

        def value(item) -> str:
            return str(item) if item not in ("", None) else "—"

        result_lines = [
            "РЕЗУЛЬТАТ АНАЛИЗА",
            f"Статус: {track.status.value}",
            f"Базовое название: {value(track.base_title)}",
            f"Вариация: {value(track.variation)}",
            f"Связь с файлами: {value(track.relation)}",
        ]
        if source:
            result_lines.append(f"Исходный трек: {source.filename}")
        completeness_lines = [
            "\nПРОВЕРКА КОМПЛЕКТА АЛЬБОМА",
            track.collection_warning or "Пропуски по тегам Track # не обнаружены",
        ]
        track_audit_issues = (
            [
                issue
                for issue in self.result.audit_issues
                if issue.track_id == track.id
            ]
            if self.result
            else []
        )
        audit_lines = ["\nАУДИТ МЕТАДАННЫХ"]
        audit_lines.extend(
            [
                (
                    f"{issue.severity.value}: {issue.field_label} — "
                    f"{issue.message}"
                )
                for issue in track_audit_issues
            ]
            or ["Замечаний не обнаружено"]
        )

        file_lines = [
            "\nФАЙЛ",
            f"Имя файла: {track.filename}",
            f"Полный путь: {track.path}",
            f"Относительный путь: {track.relative_path}",
            f"Относительная папка: {track.relative_folder}",
            f"Формат: {track.format}",
            f"Размер: {track.size_bytes} байт ({track.size_mb:.2f} MB)",
            f"Изменён: {value(track.modified_at)}",
            f"Создан: {value(track.created_at)}",
        ]
        tag_lines = [
            "\nОСНОВНЫЕ ТЕГИ И ПАРАМЕТРЫ",
            f"Title: {value(track.title)}",
            f"Artist: {value(track.artist)}",
            f"Album: {value(track.album)}",
            f"Album Artist: {value(track.album_artist)}",
            f"Track #: {value(track.track_number)}",
            f"Disc #: {value(track.disc_number)}",
            f"Year: {value(track.year)}",
            f"Genre: {value(track.genre)}",
            f"Comment: {value(track.comment)}",
            f"Длительность: {value(track.duration_display)}",
            f"Длительность в секундах: {value(track.duration_seconds)}",
            f"Битрейт: {value(track.bitrate_display)}",
            f"Частота дискретизации: {value(track.sample_rate)}",
            f"Разрядность: {value(track.bit_depth)}",
        ]
        technical_values = [
            ("Точная длительность", track.duration_exact),
            ("Битрейт", track.bitrate),
            ("Частота дискретизации", track.sample_rate),
            ("Разрядность", track.bit_depth),
            ("Каналы", track.channels),
            ("Режим каналов", track.channel_mode),
            ("Режим битрейта", track.bitrate_mode),
            ("Кодек", track.codec),
            ("Кодировщик", track.encoder),
            ("Настройки кодировщика", track.encoder_settings),
            ("Версия", track.version),
            ("Слой", track.layer),
            ("Защита", track.protection),
            ("Track Gain", track.track_gain),
            ("Track Peak", track.track_peak),
            ("Album Gain", track.album_gain),
            ("Album Peak", track.album_peak),
        ]
        technical_lines = ["\nТЕХНИЧЕСКАЯ ИНФОРМАЦИЯ"]
        present = [(label, item) for label, item in technical_values if item not in ("", None)]
        technical_lines.extend(
            [f"{label}: {item}" for label, item in present] or ["Нет данных"]
        )
        all_tag_lines = ["\nВСЕ ИМЕЮЩИЕСЯ ТЕГИ"]
        if track.all_tags:
            for key in sorted(track.all_tags, key=str.casefold):
                all_tag_lines.append(f"{key}: {'; '.join(track.all_tags[key])}")
        else:
            all_tag_lines.append("Нет данных")
        if track.cover_size:
            all_tag_lines.append(
                f"Встроенная обложка: {track.cover_mime or 'изображение'}, "
                f"{track.cover_size} байт"
                + (
                    f", {track.cover_width}×{track.cover_height}"
                    if track.cover_width and track.cover_height
                    else ""
                )
            )
        if track.cover_error:
            all_tag_lines.append(
                f"Ошибка встроенной обложки: {track.cover_error}"
            )
        error_lines: list[str] = []
        if track.metadata_errors:
            error_lines = ["\nОШИБКИ ЧТЕНИЯ", *track.metadata_errors]
        return "\n".join(
            result_lines
            + completeness_lines
            + audit_lines
            + file_lines
            + tag_lines
            + technical_lines
            + all_tag_lines
            + error_lines
        )

    def _show_track_in_panel(self, track: Track) -> None:
        self._set_text(self.info_text, self._track_info_text(track))
        self._load_cover(track, self.cover_label, 190)

    def _show_issue_in_panel(self, issue: AlbumCompletenessIssue) -> None:
        self._set_text(self.info_text, album_completeness_text(issue))
        self.cover_photo = None
        self.cover_label.configure(image="", text="Для проверки папки\nобложка не требуется")

    def _load_cover(self, track: Track, label: tk.Label, size: int) -> None:
        data, _mime, error = read_embedded_cover(track.path)
        if not data:
            label.configure(
                image="", text="Обложка не распознана" if error else "Обложка отсутствует"
            )
            if label is self.cover_label:
                self.cover_photo = None
            return
        try:
            image = Image.open(io.BytesIO(data))
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            label.configure(image=photo, text="")
            label.image = photo
            if label is self.cover_label:
                self.cover_photo = photo
        except Exception:
            # Pillow also raises DecompressionBombError and SyntaxError for
            # broken pictures; the panel must not keep the previous cover.
            label.configure(image="", text="Обложка не распознана")

    def _show_context_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        track_id = self.audit_item_track_ids.get(row, row)
        if not row or track_id not in self.track_by_id:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        track = self.track_by_id.get(track_id)
        state = "normal" if track and track.source_track_id else "disabled"
        self.context_menu.entryconfigure("Показать исходный трек", state=state)
        self._refresh_numbering_button()
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showwarning(APP_NAME, "Файл не найден", parent=self.root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror(
                APP_NAME, f"Не удалось открыть объект.\n\nПричина: {exc}", parent=self.root
            )

    def open_selected_file(self) -> None:
        track = self._selected_track()
        if track:
            self._open_path(track.path)

    def open_selected_folder(self) -> None:
        track = self._selected_track()
        if track:
            self._open_path(track.path.parent)

    def copy_path(self) -> None:
        track = self._selected_track()
        if track:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(track.path))

    def copy_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        lines = [
            "\t".join(str(value) for value in self.tree.item(item_id, "values"))
            for item_id in selection
        ]
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))

    def open_unique_copy(self) -> None:
        if not self.result or not self.result.tracks:
            messagebox.showinfo(
                APP_NAME,
                "Нет данных для копирования. Сначала выполните анализ",
                parent=self.root,
            )
            return
        dialog = UniqueCopyDialog(
            self.root,
            self.result.tracks,
            self.result.root,
        )
        self._style_toplevel(dialog.window)

    def open_audit_fixes(self) -> None:
        if not self.result:
            return
        fixable = [
            issue for issue in self.result.audit_issues if issue.fixable
        ]
        if not fixable:
            messagebox.showinfo(
                APP_NAME,
                (
                    "Нет замечаний, которые программа может исправить "
                    "механически. Остальные результаты требуют ручной проверки."
                ),
                parent=self.root,
            )
            return
        dialog = AuditFixDialog(
            self.root,
            self.result.tracks,
            self.result.audit_issues,
            self.result.root,
            self.start_analysis,
        )
        self._style_toplevel(dialog.window)

    def open_numbering_fix(self) -> None:
        if not self.result:
            return
        issues = self._numbering_issues_for_selection()
        if not issues:
            return
        plan = plan_numbering_fix(self.result.tracks, issues)
        if not plan.changes:
            messagebox.showinfo(
                APP_NAME,
                "Итоги Track # уже согласованы — исправлять нечего",
                parent=self.root,
            )
            return
        dialog = NumberingFixDialog(
            self.root,
            plan,
            self.result.root,
            backup_enabled=self.settings.backup_before_tag_writes,
            on_backup_changed=self._set_backup_preference,
            on_completed=self.start_analysis,
        )
        self._style_toplevel(dialog.window)

    def _folder_parts_from_tree_id(self, item_id: str) -> tuple[str, ...] | None:
        if item_id == "folder-root::node":
            return ()
        if item_id.startswith("folder-path::"):
            return tuple(
                part
                for part in item_id.removeprefix("folder-path::").split("/")
                if part
            )
        return None

    def _numbering_issues_for_selection(self) -> list[AlbumCompletenessIssue]:
        """Completeness issues with conflicting totals for the focused row."""
        if not self.result:
            return []
        focused = self.tree.focus()
        if not focused:
            return []
        issues = [
            issue
            for issue in self.result.completeness_issues
            if issue.inconsistent_totals
        ]
        if not issues:
            return []
        if focused.startswith("issue::"):
            issue = self.issue_by_id.get(focused.removeprefix("issue::"))
            return [issue] if issue in issues else []
        if focused.startswith("folder-"):
            parts = self._folder_parts_from_tree_id(focused)
            if parts is None:
                return []
            return [
                issue
                for issue in issues
                if self._folder_parts(issue.relative_folder) == parts
            ]
        track_id = self.audit_item_track_ids.get(focused, focused)
        if focused.startswith("audit-issue::"):
            audit_issue = self.audit_issue_by_id.get(
                focused.removeprefix("audit-issue::")
            )
            track_id = audit_issue.track_id if audit_issue else ""
        elif self.group_members.get(focused):
            track_id = self.group_members[focused][0]
        track = self.track_by_id.get(track_id)
        if track is None:
            return []
        key = album_group_key(track)
        return [
            issue
            for issue in issues
            if (
                issue.relative_folder,
                issue.album.strip().casefold(),
                issue.disc,
            )
            == key
        ]

    def _refresh_numbering_button(self) -> None:
        """Show the fix button only when the focused row has conflicting totals."""
        issues = self._numbering_issues_for_selection()
        plan = (
            plan_numbering_fix(self.result.tracks, issues)
            if self.result and issues
            else None
        )
        self._numbering_plan = plan if plan and plan.count else None
        if self._numbering_plan is not None:
            self.numbering_fix_button.configure(
                text=f"Исправить нумерацию ({self._numbering_plan.count})"
            )
            self.numbering_fix_button.grid()
        else:
            self.numbering_fix_button.grid_remove()
        self.context_menu.entryconfigure(
            "Исправить нумерацию...",
            state="normal" if self._numbering_plan is not None else "disabled",
        )

    def _set_backup_preference(self, enabled: bool) -> None:
        """Remember the «делать бэкап» choice for both tag writers."""
        self.settings.backup_before_tag_writes = enabled
        # Only the preference is written; the rest of settings.json stays as is.
        with contextlib.suppress(OSError):
            self.settings.save()

    def open_full_info(self) -> None:
        track = self._selected_track()
        if track:
            self._open_info_dialog(track, "Полная информация о треке")

    def open_source_track(self) -> None:
        track = self._selected_track()
        if not track or not track.source_track_id:
            return
        source = self.track_by_id.get(track.source_track_id)
        if source:
            self._open_info_dialog(
                source, f'Исходный трек для “{track.filename}”'
            )

    def _open_info_dialog(self, track: Track, title: str) -> None:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("950x650")
        window.minsize(720, 480)
        window.transient(self.root)
        self._style_toplevel(window)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        holder = ttk.Frame(window, padding=10)
        holder.grid(row=0, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        text = tk.Text(holder, wrap="word", relief="flat")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        text.insert("1.0", self._track_info_text(track))
        text.configure(state="disabled")
        cover = tk.Label(
            holder,
            text="Обложка не выбрана",
            width=35,
            height=18,
            anchor="center",
            justify="center",
        )
        cover.grid(row=0, column=2, sticky="n", padx=(10, 0))
        _bg, field, fg, _selected, _selected_fg = self._tk_palette()
        self._style_text_widget(text)
        cover.configure(bg=field, fg=fg)
        self._load_cover(track, cover, 300)

    def open_advanced_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Дополнительные настройки")
        window.geometry("690x720")
        window.minsize(580, 520)
        window.transient(self.root)
        self._style_toplevel(window)
        window.grab_set()
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        canvas = tk.Canvas(window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, padding=12)
        content_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        content.columnconfigure(0, weight=1)
        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_id, width=event.width),
        )

        ttk.Label(
            content,
            text="Обозначения вариаций (одно на строку)",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w")
        markers_text = tk.Text(content, height=12, wrap="none")
        markers_text.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        markers_text.insert("1.0", "\n".join(self.settings.variation_markers))
        marker_buttons = ttk.Frame(content)
        marker_buttons.grid(row=2, column=0, sticky="w")
        ttk.Button(
            marker_buttons,
            text="+ Добавить",
            command=lambda: markers_text.insert("end", "\nНовая вариация"),
        ).pack(side="left")
        ttk.Button(
            marker_buttons,
            text="Сбросить",
            command=lambda: (
                markers_text.delete("1.0", "end"),
                markers_text.insert("1.0", "\n".join(DEFAULT_VARIATION_MARKERS)),
            ),
        ).pack(side="left", padx=6)

        ttk.Label(
            content, text="Исключаемые папки (по одной на строку)"
        ).grid(row=3, column=0, sticky="w", pady=(14, 0))
        excluded_text = tk.Text(content, height=6, wrap="none")
        excluded_text.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        excluded_text.insert("1.0", "\n".join(self.settings.excluded_folders))
        bg, _field, _fg, _selected, _selected_fg = self._tk_palette()
        canvas.configure(bg=bg)
        self._style_text_widget(markers_text)
        self._style_text_widget(excluded_text)

        ttk.Label(content, text="Цветовая схема XLSX-отчёта").grid(
            row=5, column=0, sticky="w", pady=(14, 4)
        )
        color_frame = ttk.Frame(content)
        color_frame.grid(row=6, column=0, sticky="ew")
        color_names_by_hex = {value: name for name, value in REPORT_COLOR_CHOICES.items()}
        color_vars: dict[str, tk.StringVar] = {}
        for row, status in enumerate(
            ("Уникальный", "Дубликат", "Вариация", "Конфликт")
        ):
            ttk.Label(color_frame, text=status, width=18).grid(
                row=row, column=0, sticky="w", pady=2
            )
            current = self.settings.report_colors.get(
                status, DEFAULT_REPORT_COLORS[status]
            )
            variable = tk.StringVar(
                value=color_names_by_hex.get(current, next(iter(REPORT_COLOR_CHOICES)))
            )
            color_vars[status] = variable
            ttk.Combobox(
                color_frame,
                textvariable=variable,
                values=list(REPORT_COLOR_CHOICES),
                state="readonly",
                width=20,
            ).grid(row=row, column=1, sticky="w", pady=2)

        remember_var = tk.BooleanVar(value=self.settings.remember_folder)
        autosave_var = tk.BooleanVar(value=self.settings.autosave)
        ttk.Checkbutton(
            content, text="Запомнить последнюю папку", variable=remember_var
        ).grid(row=7, column=0, sticky="w", pady=(14, 0))
        ttk.Checkbutton(
            content, text="Автосохранение настроек", variable=autosave_var
        ).grid(row=8, column=0, sticky="w")
        actions = ttk.Frame(content)
        actions.grid(row=9, column=0, sticky="e", pady=(18, 0))

        def save() -> None:
            try:
                markers = validate_markers(
                    markers_text.get("1.0", "end").splitlines()
                )
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=window)
                return
            self.settings.variation_markers = markers
            self.settings.excluded_folders = [
                line.strip()
                for line in excluded_text.get("1.0", "end").splitlines()
                if line.strip()
            ]
            self.settings.report_colors = {
                status: REPORT_COLOR_CHOICES[color_vars[status].get()]
                for status in color_vars
            }
            self.settings.remember_folder = remember_var.get()
            self.settings.autosave = autosave_var.get()
            self._sync_settings_from_ui()
            self._save_settings_with_warning(window)
            window.destroy()

        ttk.Button(actions, text="Сохранить", command=save).pack(side="left")
        ttk.Button(actions, text="Отмена", command=window.destroy).pack(
            side="left", padx=(6, 0)
        )

    def open_export(self) -> None:
        result = self.result
        if result is None or not result.tracks:
            messagebox.showinfo(
                APP_NAME,
                "Нет данных для экспорта. Сначала выполните анализ",
                parent=self.root,
            )
            return
        window = tk.Toplevel(self.root)
        window.title("Экспорт в XLSX")
        window.geometry("720x680")
        window.minsize(620, 560)
        window.transient(self.root)
        self._style_toplevel(window)
        window.grab_set()
        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)
        sheet_frame = ttk.LabelFrame(window, text="Листы отчёта", padding=10)
        sheet_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        sheet_vars = {
            "all": tk.BooleanVar(value=True),
            "attention": tk.BooleanVar(value=True),
            "matrix": tk.BooleanVar(value=True),
            "folders": tk.BooleanVar(value=True),
            "audit": tk.BooleanVar(value=True),
        }
        for index, (key, label) in enumerate(
            (
                ("all", "Все треки"),
                ("attention", "Только дубликаты"),
                ("matrix", "Матрица дубликатов"),
                ("folders", "Сводка по папкам"),
                ("audit", "Аудит метаданных"),
            )
        ):
            ttk.Checkbutton(
                sheet_frame, text=label, variable=sheet_vars[key]
            ).grid(
                row=index // 3,
                column=index % 3,
                padx=(0, 12),
                pady=2,
                sticky="w",
            )

        column_frame = ttk.LabelFrame(window, text="Столбцы", padding=10)
        column_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        column_vars: dict[str, tk.BooleanVar] = {}
        for index, (key, (label, default)) in enumerate(EXPORT_COLUMNS.items()):
            variable = tk.BooleanVar(value=default)
            column_vars[key] = variable
            ttk.Checkbutton(column_frame, text=label, variable=variable).grid(
                row=index // 3, column=index % 3, sticky="w", padx=(0, 20), pady=2
            )
        controls = ttk.Frame(column_frame)
        controls.grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(
            controls,
            text="Выбрать все",
            command=lambda: [var.set(True) for var in column_vars.values()],
        ).pack(side="left")
        ttk.Button(
            controls,
            text="Сбросить",
            command=lambda: [var.set(False) for var in column_vars.values()],
        ).pack(side="left", padx=6)

        destination_frame = ttk.LabelFrame(window, text="Файл", padding=10)
        destination_frame.grid(
            row=2, column=0, sticky="new", padx=12, pady=(6, 12)
        )
        destination_frame.columnconfigure(1, weight=1)
        filename_var = tk.StringVar(
            value=f"discography_report_{date.today().isoformat()}.xlsx"
        )
        ttk.Label(destination_frame, text="Имя файла").grid(row=0, column=0)
        ttk.Entry(destination_frame, textvariable=filename_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )

        def save_as() -> None:
            filename = filename_var.get().strip() or "discography_report.xlsx"
            if not filename.casefold().endswith(".xlsx"):
                filename += ".xlsx"
            chosen = filedialog.asksaveasfilename(
                parent=window,
                title="Сохранить отчёт",
                initialfile=filename,
                defaultextension=".xlsx",
                filetypes=[("Excel Workbook", "*.xlsx")],
            )
            if not chosen:
                return
            try:
                path = export_xlsx(
                    result.tracks,
                    Path(chosen),
                    {key: variable.get() for key, variable in sheet_vars.items()},
                    [key for key, variable in column_vars.items() if variable.get()],
                    dict(self.settings.report_colors),
                    result.audit_issues,
                )
                messagebox.showinfo(
                    APP_NAME, f"Отчёт успешно сохранён:\n{path}", parent=window
                )
                window.destroy()
            except Exception as exc:
                messagebox.showerror(
                    APP_NAME,
                    f"Не удалось сохранить отчёт.\n\nПричина: {exc}",
                    parent=window,
                )

        actions = ttk.Frame(destination_frame)
        actions.grid(row=1, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(actions, text="Сохранить как...", command=save_as).pack(
            side="left"
        )
        ttk.Button(actions, text="Отмена", command=window.destroy).pack(
            side="left", padx=(6, 0)
        )

    def _sync_settings_from_ui(self) -> None:
        self.settings.last_folder = self.folder_var.get()
        self.settings.include_subfolders = self.include_subfolders_var.get()
        self.settings.use_tags = self.use_tags_var.get()
        self.settings.detect_variations = self.detect_variations_var.get()
        self.settings.check_track_gaps = self.check_track_gaps_var.get()
        self.settings.folder_tree_mode = self.folder_tree_mode_var.get()
        self.settings.dark_theme = self.dark_theme_var.get()
        self.settings.formats = {
            name: variable.get() for name, variable in self.format_vars.items()
        }

    def _save_settings_with_warning(self, parent) -> None:
        try:
            self.settings.save()
        except OSError as exc:
            messagebox.showwarning(
                APP_NAME,
                f"Не удалось сохранить настройки.\n\nПричина: {exc}",
                parent=parent,
            )

    def _autosave(self) -> None:
        if self.settings.autosave:
            self._sync_settings_from_ui()
            with contextlib.suppress(OSError):
                self.settings.save()

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
        self._sync_settings_from_ui()
        if self.settings.autosave:
            with contextlib.suppress(OSError):
                self.settings.save()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    DiscographyAnalyzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
