"""The «Имена по тегам» utility: preview «сейчас → будет», rename, undo."""

from __future__ import annotations

import tkinter as tk
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .renaming import (
    FILE_TEMPLATES,
    FOLDER_TEMPLATES,
    RELEASE_FIELDS,
    TRACK_FIELDS,
    NamingScheme,
    RenameItem,
    RenameJournal,
    RenamePlan,
    RenameResult,
    RenameStopped,
    TemplateError,
    apply_renames,
    latest_journal,
    load_scheme,
    parse_template,
    plan_renames,
    read_tracks,
    save_scheme,
    undo_journal,
)
from .utility_panel import WINDOW_TITLE, BackgroundUtilityPanel

SOURCES = (
    "",
    "Qobuz",
    "Deezer",
    "Tidal",
    "Apple Music",
    "Bandcamp",
    "Beatport",
    "HDtracks",
)
KIND_NAMES = {"folder": "папка релиза", "disc": "папка диска", "file": "файл"}


def renames_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "переименование"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "переименования"
    return "переименований"


def plan_summary(plan: RenamePlan) -> str:
    chosen = Counter(item.kind for item in plan.chosen())
    parts = [
        f"файлов {chosen['file']}",
        f"папок дисков {chosen['disc']}",
        f"папок релизов {chosen['folder']}",
    ]
    text = "Будет переименовано: " + ", ".join(parts)
    text += f" · уже по шаблону: {plan.unchanged}"
    if plan.problems:
        text += f" · не переименовать: {plan.problems}"
    return text


class RenamePanel(BackgroundUtilityPanel):
    """Name release folders, disc folders and files after their tags."""

    title = "Имена по тегам"
    description = (
        "Переименовывает папки релизов, папки дисков и файлы по шаблону из "
        "тегов — по умолчанию как скрипты Tags-Discography-Normalizer: «1972 "
        "Irrlicht (Qobuz, Brain, 0004228331272)», «CD2», «01. Satz Ebene.flac». "
        "Сначала «сейчас → будет»; ничего не перезаписывается, каждый запуск "
        "можно откатить."
    )

    def build(self) -> None:
        scheme = load_scheme()
        self.plan: RenamePlan | None = None
        self.item_rows: dict[str, RenameItem] = {}
        self.journal: RenameJournal | None = None
        folder = self.context.selected_folder or self.context.root_folder
        self.root_var = tk.StringVar(value=str(folder) if folder else "")
        self.include_subfolders_var = tk.BooleanVar(
            value=self.context.include_subfolders
        )
        self.rename_folders_var = tk.BooleanVar(value=scheme.rename_folders)
        self.rename_files_var = tk.BooleanVar(value=scheme.rename_files)
        self.disc_folders_var = tk.BooleanVar(value=scheme.disc_folders)
        self.folder_template_var = tk.StringVar(value=scheme.folder_template)
        self.file_template_var = tk.StringVar(value=scheme.file_template)
        self.source_var = tk.StringVar(value=scheme.source)
        self.status_var = tk.StringVar(
            value="Нажмите «Показать изменения»" if folder else "Папка не выбрана"
        )
        self.summary_var = tk.StringVar()
        self.undo_var = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_verb = "Переименование"
        self._build_options()
        self._build_preview()
        self._build_bottom()
        for variable in (
            self.folder_template_var,
            self.file_template_var,
            self.source_var,
        ):
            variable.trace_add("write", lambda *_args: self._invalidate())
        self._refresh_undo()

    # -- layout ----------------------------------------------------------------
    def _build_options(self) -> None:
        options = ttk.LabelFrame(self.frame, text="Папка и шаблоны", padding=(9, 5))
        options.grid(row=0, column=0, sticky="ew")
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="Папка").grid(row=0, column=0, sticky="w")
        ttk.Entry(options, textvariable=self.root_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )
        ttk.Button(options, text="Выбрать...", command=self._choose_root).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Checkbutton(
            options,
            text="Включать подпапки",
            variable=self.include_subfolders_var,
            command=self._invalidate,
        ).grid(row=0, column=3, padx=(12, 0))
        for row, (label, enabled, template, presets) in enumerate(
            (
                (
                    "Папки релизов",
                    self.rename_folders_var,
                    self.folder_template_var,
                    FOLDER_TEMPLATES,
                ),
                (
                    "Файлы",
                    self.rename_files_var,
                    self.file_template_var,
                    FILE_TEMPLATES,
                ),
            ),
            start=1,
        ):
            ttk.Checkbutton(
                options, text=label, variable=enabled, command=self._invalidate
            ).grid(row=row, column=0, sticky="w", pady=(5, 0))
            ttk.Combobox(options, textvariable=template, values=presets).grid(
                row=row, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(5, 0)
            )
        line = ttk.Frame(options)
        line.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(5, 0))
        ttk.Checkbutton(
            line,
            text="Папки дисков → CD1, CD2…",
            variable=self.disc_folders_var,
            command=self._invalidate,
        ).pack(side="left")
        ttk.Label(line, text="Источник").pack(side="left", padx=(18, 6))
        ttk.Combobox(line, textvariable=self.source_var, values=SOURCES, width=14).pack(
            side="left"
        )
        ttk.Label(line, text="пусто — из тега URL или имени папки").pack(
            side="left", padx=(8, 0)
        )
        fields_text = (
            "Поля: "
            + " ".join(f"{{{name}}}" for name in RELEASE_FIELDS)
            + "; для файлов ещё "
            + " ".join(f"{{{name}}}" for name in TRACK_FIELDS)
            + ", {track:02}. Часть в <…> пропадает, если в ней пустое поле."
        )
        self.help_label = ttk.Label(
            options, text=fields_text, wraplength=760, justify="left"
        )
        self.help_label.grid(row=4, column=0, columnspan=4, sticky="w", pady=(5, 0))
        options.bind(
            "<Configure>",
            lambda event: self.help_label.configure(
                wraplength=max(320, event.width - 24)
            ),
        )

    def _build_preview(self) -> None:
        preview = ttk.LabelFrame(
            self.frame,
            text="Сейчас → будет · двойной щелчок или пробел — снять или поставить отметку",
            padding=(9, 5),
        )
        preview.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.frame.rowconfigure(1, weight=1)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            preview,
            columns=("mark", "current", "new", "problem"),
            show=("tree", "headings"),
            selectmode="browse",
            height=10,
        )
        self.tree.heading("#0", text="Релиз")
        self.tree.column("#0", width=180, minwidth=120, stretch=False)
        for column, heading, width, stretch in (
            ("mark", "✓", 30, False),
            ("current", "Сейчас", 210, True),
            ("new", "Будет", 250, True),
            ("problem", "Почему нельзя", 130, False),
        ):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, minwidth=34, stretch=stretch)
        scroll = ttk.Scrollbar(preview, orient="vertical", command=self.tree.yview)
        hscroll = ttk.Scrollbar(preview, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=hscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("Problem", foreground="#a9473e")
        self.tree.tag_configure("Release", font=("TkDefaultFont", 9, "bold"))
        self.tree.bind("<Double-1>", self._toggle)
        self.tree.bind("<space>", self._toggle)
        ttk.Label(preview, textvariable=self.summary_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

    def _build_bottom(self) -> None:
        bottom = ttk.Frame(self.frame)
        bottom.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Progressbar(
            bottom, mode="determinate", maximum=100, variable=self.progress_var
        ).grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(bottom, textvariable=self.status_var).grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )
        # On the status line, not next to the buttons: a long «last run» text
        # squeezed «Переименовать» down to «Переи».
        ttk.Label(bottom, textvariable=self.undo_var).grid(
            row=1, column=1, sticky="e", pady=(3, 0)
        )
        actions = ttk.Frame(bottom)
        actions.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.preview_button = ttk.Button(
            actions, text="Показать изменения", command=self.preview
        )
        self.preview_button.pack(side="left")
        self.apply_button = ttk.Button(
            actions,
            text="Переименовать",
            command=self.apply,
            style="Accent.TButton",
            state="disabled",
        )
        self.apply_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(
            actions, text="Остановить", command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="left")
        self.undo_button = ttk.Button(
            bottom, text="Откатить последнее...", command=self.undo, state="disabled"
        )
        self.undo_button.grid(row=2, column=1, sticky="e", pady=(6, 0))

    # -- options ---------------------------------------------------------------
    def _root(self) -> Path | None:
        value = self.root_var.get().strip()
        return Path(value) if value else None

    def _choose_root(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.frame,
            title="Папка для переименования",
            initialdir=self.root_var.get() or None,
        )
        if chosen:
            self.root_var.set(chosen)
            self._invalidate()

    def scheme(self) -> NamingScheme:
        return NamingScheme(
            folder_template=self.folder_template_var.get().strip(),
            file_template=self.file_template_var.get().strip(),
            rename_folders=self.rename_folders_var.get(),
            rename_files=self.rename_files_var.get(),
            disc_folders=self.disc_folders_var.get(),
            source=self.source_var.get().strip(),
        )

    def _template_problem(self, scheme: NamingScheme) -> str:
        """The first template error, as the user should read it."""
        if not (scheme.rename_folders or scheme.rename_files or scheme.disc_folders):
            return (
                "Отметьте, что переименовывать: папки релизов, файлы или папки дисков"
            )
        try:
            if scheme.rename_folders:
                parse_template(scheme.folder_template, RELEASE_FIELDS)
        except TemplateError as exc:
            return f"Шаблон папок: {exc}"
        try:
            if scheme.rename_files:
                parse_template(scheme.file_template, {*RELEASE_FIELDS, *TRACK_FIELDS})
        except TemplateError as exc:
            return f"Шаблон файлов: {exc}"
        return ""

    def _invalidate(self) -> None:
        if self.busy:
            return
        self.plan = None
        self.item_rows.clear()
        self.tree.delete(*self.tree.get_children())
        self.summary_var.set("")
        self.apply_button.configure(state="disabled")

    # -- preview ---------------------------------------------------------------
    def preview(self) -> None:
        if self.busy:
            return
        root = self._root()
        if root is None or not root.is_dir():
            messagebox.showwarning(
                WINDOW_TITLE, "Выберите существующую папку", parent=self.frame
            )
            return
        scheme = self.scheme()
        problem = self._template_problem(scheme)
        if problem:
            messagebox.showwarning(WINDOW_TITLE, problem, parent=self.frame)
            return
        save_scheme(scheme)
        self._invalidate()
        self.status_var.set("Чтение тегов...")
        include_subfolders = self.include_subfolders_var.get()
        excluded = self.context.excluded_folders
        extensions = self.context.extensions
        protected = self.context.root_folder

        def run() -> None:
            try:
                tracks = read_tracks(
                    root,
                    extensions=extensions,
                    include_subfolders=include_subfolders,
                    excluded_folders=excluded,
                    stop_event=self.stop_event,
                    progress=lambda index, total, label: self.post(
                        "read", index, total, label
                    ),
                )
                self.post(
                    "plan", plan_renames(root, tracks, scheme, protected=protected)
                )
            except RenameStopped:
                self.post("stopped")
            except Exception as exc:
                self.post("task_error", "Предпросмотр не построен", str(exc))

        self.run_in_background(run)

    def show_plan(self, plan: RenamePlan) -> None:
        self.plan = plan
        self.item_rows.clear()
        self.tree.delete(*self.tree.get_children())
        # By folder, not by title: two «Irrlicht (1972)» in two folders are
        # two releases.
        releases: dict[Path | None, str] = {}
        for index, item in enumerate(plan.items):
            parent = releases.get(item.folder)
            if parent is None:
                parent = self.tree.insert(
                    "",
                    "end",
                    text=item.release,
                    values=(
                        "",
                        self._relative(item.folder) if item.folder else "",
                        "",
                        "",
                    ),
                    open=True,
                    tags=("Release",),
                )
                releases[item.folder] = parent
            row = self.tree.insert(
                parent,
                "end",
                iid=f"item::{index}",
                text=KIND_NAMES[item.kind],
                values=(
                    "✓" if item.selected else "",
                    item.source.name,
                    item.target.name if item.changes else "—",
                    item.problem,
                ),
                tags=("Problem",) if item.problem else (),
            )
            self.item_rows[row] = item
        self._refresh_marks()
        if not plan.items:
            self.status_var.set(
                f"Переименовывать нечего: все имена уже по шаблону ({plan.unchanged})"
            )
        else:
            self.status_var.set(
                "Проверьте список и нажмите «Переименовать». Ничего ещё не изменено."
            )

    @staticmethod
    def _when(created: str) -> str:
        """«03.11.2026 20:41» from the journal's ISO time."""
        try:
            return datetime.fromisoformat(created).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return created

    def _relative(self, path: Path) -> str:
        root = self.plan.root if self.plan else None
        try:
            return str(path.relative_to(root)) if root and path != root else str(path)
        except ValueError:
            return str(path)

    def _refresh_marks(self) -> None:
        if self.plan is None:
            return
        for parent in self.tree.get_children(""):
            children = [self.item_rows[row] for row in self.tree.get_children(parent)]
            chosen = sum(item.selected for item in children)
            mark = "✓" if chosen == len(children) else ("–" if chosen else "")
            self.tree.set(parent, "mark", mark)
        for row, item in self.item_rows.items():
            self.tree.set(row, "mark", "✓" if item.selected else "")
        self.summary_var.set(plan_summary(self.plan))
        self.apply_button.configure(
            state="normal" if self.plan.chosen() and not self.busy else "disabled"
        )

    def _toggle(self, _event=None) -> str:
        row = self.tree.focus()
        items = (
            [self.item_rows[row]]
            if row in self.item_rows
            else [self.item_rows[child] for child in self.tree.get_children(row)]
        )
        allowed = [item for item in items if not item.problem]
        if allowed:
            select = not all(item.selected for item in allowed)
            for item in allowed:
                item.selected = select
            self._refresh_marks()
        return "break"

    # -- renaming and undo -------------------------------------------------------
    def apply(self) -> None:
        if self.busy or self.plan is None or not self.plan.chosen():
            return
        plan = self.plan
        chosen = Counter(item.kind for item in plan.chosen())
        total = sum(chosen.values())
        lines = [
            f"Выполнить {total} {renames_word(total)}?",
            f"Файлов: {chosen['file']} · папок дисков: {chosen['disc']} · "
            f"папок релизов: {chosen['folder']}.",
            "",
            "Файлы не перемещаются между папками и не перезаписываются. "
            "Журнал запуска позволит откатить переименование кнопкой "
            "«Откатить последнее».",
        ]
        if not messagebox.askyesno(WINDOW_TITLE, "\n".join(lines), parent=self.frame):
            return
        self.status_var.set("Переименование...")
        self.progress_verb = "Переименование"

        def run() -> None:
            try:
                result = apply_renames(
                    plan,
                    stop_event=self.stop_event,
                    progress=lambda index, total, label: self.post(
                        "progress", index, total, label
                    ),
                )
                self.post("renamed", result)
            except Exception as exc:
                self.post("task_error", "Переименование прервано", str(exc))

        self.run_in_background(run)

    def _refresh_undo(self) -> None:
        self.journal = latest_journal()
        if self.journal is None:
            self.undo_var.set("Откатывать нечего")
        else:
            count = len(self.journal.entries)
            self.undo_var.set(
                f"Последний запуск: {self._when(self.journal.created)}, "
                f"{count} {renames_word(count)}"
            )
        self.undo_button.configure(
            state="normal" if self.journal is not None and not self.busy else "disabled"
        )

    def undo(self) -> None:
        journal = latest_journal()
        if self.busy or journal is None:
            self._refresh_undo()
            return
        count = len(journal.entries)
        if not messagebox.askyesno(
            WINDOW_TITLE,
            f"Вернуть прежние имена: {count} {renames_word(count)} запуска "
            f"{self._when(journal.created)} в папке\n{journal.root}?",
            parent=self.frame,
        ):
            return
        self.status_var.set("Откат...")
        self.progress_verb = "Откат"

        def run() -> None:
            try:
                result = undo_journal(
                    journal,
                    stop_event=self.stop_event,
                    progress=lambda index, total, label: self.post(
                        "progress", index, total, label
                    ),
                )
                self.post("undone", result, journal)
            except Exception as exc:
                self.post("task_error", "Откат прерван", str(exc))

        self.run_in_background(run)

    def _report(self, result: RenameResult, done_text: str) -> None:
        lines = [done_text]
        if result.failures:
            lines.append(f"Не удалось: {len(result.failures)}.")
            lines.extend(
                f"• {path.name}: {reason}" for path, reason in result.failures[:8]
            )
        if result.stopped:
            lines.append("Остановлено до конца списка.")
        if result.journal is not None and result.journal.name.endswith(".undone.jsonl"):
            lines.append("Журнал запуска закрыт.")
        elif result.journal is not None:
            lines.append(f"Журнал: {result.journal}")
        messagebox.showinfo(WINDOW_TITLE, "\n".join(lines), parent=self.frame)

    def _renamed(self, result: RenameResult) -> None:
        self.finish_background()
        self.progress_var.set(0)
        count = result.renamed
        plan_root = self.plan.root if self.plan is not None else None
        root_renamed = result.root is not None and result.root != plan_root
        self._report(result, f"Переименовано: {count}.")
        if root_renamed:
            # The chosen folder itself got its new name.
            self.root_var.set(str(result.root))
        self._refresh_undo()
        if count and result.root is not None:
            self.context.on_completed(
                result.root.parent if root_renamed else result.root
            )
            self.status_var.set(
                f"Готово: {count} {renames_word(count)}. Список обновляется..."
            )
            self.preview()
        else:
            self.status_var.set("Изменений нет")

    def _undone(self, result: RenameResult, journal: RenameJournal) -> None:
        self.finish_background()
        self.progress_var.set(0)
        self._report(result, f"Возвращено прежних имён: {result.renamed}.")
        self._invalidate()
        renamed_root = any(old == journal.root for _kind, old, _new in journal.entries)
        if renamed_root:
            self.root_var.set(str(journal.root))
        if result.renamed:
            self.context.on_completed(
                journal.root.parent if renamed_root else journal.root
            )
        self.status_var.set(
            "Откат выполнен" if not result.failures else "Откат выполнен не полностью"
        )
        self._refresh_undo()

    # -- background ----------------------------------------------------------------
    def _stop(self) -> None:
        self.stop()
        self.stop_button.configure(state="disabled")
        self.status_var.set("Остановка...")

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.preview_button.configure(state=state)
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.apply_button.configure(
            state="normal"
            if not busy and self.plan and self.plan.chosen()
            else "disabled"
        )
        self.undo_button.configure(
            state="normal" if not busy and self.journal is not None else "disabled"
        )

    def handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind in ("read", "progress"):
            _kind, index, total, label = event
            self.progress_var.set(round(index / total * 100) if total else 0)
            what = "Чтение тегов" if kind == "read" else self.progress_verb
            self.status_var.set(f"{what}: {index} из {total} — …{label[-60:]}")
        elif kind == "plan":
            self.finish_background()
            self.progress_var.set(0)
            self.show_plan(event[1])
        elif kind == "renamed":
            self._renamed(event[1])
        elif kind == "undone":
            self._undone(event[1], event[2])
        elif kind == "stopped":
            self.finish_background()
            self.progress_var.set(0)
            self.status_var.set("Остановлено")
        elif kind == "task_error":
            self.finish_background()
            self.progress_var.set(0)
            self.status_var.set(event[1])
            messagebox.showerror(
                WINDOW_TITLE, f"{event[1]}.\n\nПричина: {event[2]}", parent=self.frame
            )
            self._refresh_undo()
