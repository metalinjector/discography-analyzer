"""The «Утилиты» window — collection-wide maintenance tools.

The window keeps a list of utilities on the left and builds the selected panel
on the right, so a new utility is a new panel class plus one entry in
``UTILITY_PANELS``; the base classes are in :mod:`utility_panel`, so the class
can live in its own module. Panels work on the filesystem, not on the analysis
result, so they can run before any scan.
"""

from __future__ import annotations

import contextlib
import io
import queue
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .constants import APP_NAME
from .cover_embedding import (
    CoverEmbedResult,
    CoverPlan,
    CoverTaskStopped,
    embed_covers,
    plan_cover_embedding,
)
from .cover_extraction import (
    CoverExtractionPlan,
    CoverExtractionResult,
    plan_cover_extraction,
    write_covers,
)
from .online.panel import OnlineTagsPanel
from .parsing import files_word, folders_word
from .utility_panel import WINDOW_TITLE, UtilityContext, UtilityPanel

COVER_FORMATS = "MP3, FLAC, M4A, APE"

__all__ = ["UTILITY_PANELS", "UtilitiesDialog", "UtilityContext", "UtilityPanel"]


class CoverEmbeddingPanel(UtilityPanel):
    """Write each folder's cover image into the tags of files that have none."""

    title = "Обложки из папки в теги"
    description = (
        "Находит папки с файлом обложки (cover.jpg, cover.jpeg, folder.png, …) "
        "и встраивает эту картинку в теги тех аудиофайлов папки, где обложки "
        f"нет. Форматы: {COVER_FORMATS}. Папки из списка исключений и скрытые "
        "папки пропускаются. Каждый файл сначала записывается во временную "
        "копию, проверяется и только потом заменяет оригинал."
    )

    def build(self) -> None:
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.plan: CoverPlan | None = None
        self.busy = False
        self._poll_job: str | None = None

        default_root = (
            str(self.context.root_folder) if self.context.root_folder else ""
        )
        self.root_var = tk.StringVar(value=default_root)
        self.include_subfolders_var = tk.BooleanVar(
            value=self.context.include_subfolders
        )
        self.replace_broken_var = tk.BooleanVar(value=False)
        self.backup_enabled_var = tk.BooleanVar(value=self.context.backup_enabled)
        self.backup_path_var = tk.StringVar(
            value=self._default_backup_path(self.context.root_folder)
        )
        self.status_var = tk.StringVar(
            value=(
                "Нажмите «Проверить папки», чтобы найти файлы без обложки"
                if default_root
                else "Папка коллекции не выбрана"
            )
        )
        self.summary_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)

        source = ttk.LabelFrame(self.frame, text="Папка коллекции", padding=9)
        source.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text="Папка").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(source, textvariable=self.root_var, state="readonly").grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(source, text="Выбрать...", command=self._choose_root).grid(
            row=0, column=2, padx=(8, 0)
        )
        options = ttk.Frame(source)
        options.grid(row=1, column=0, columnspan=3, sticky="w", pady=(7, 0))
        ttk.Checkbutton(
            options,
            text="Включать подпапки",
            variable=self.include_subfolders_var,
            command=self._invalidate_plan,
        ).pack(side="left")
        ttk.Checkbutton(
            options,
            text="Заменять повреждённые обложки",
            variable=self.replace_broken_var,
            command=self._invalidate_plan,
        ).pack(side="left", padx=(14, 0))

        preview = ttk.LabelFrame(
            self.frame,
            text="Предпросмотр: папки, где обложку можно встроить",
            padding=9,
        )
        preview.grid(row=1, column=0, sticky="nsew")
        self.frame.rowconfigure(1, weight=1)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        columns = ("folder", "cover", "targets", "present")
        self.tree = ttk.Treeview(
            preview,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=11,
        )
        headings = {
            "folder": "Папка",
            "cover": "Файл обложки",
            "targets": "Без обложки",
            "present": "Уже с обложкой",
        }
        widths = {"folder": 280, "cover": 230, "targets": 110, "present": 135}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                minwidth=70,
                stretch=column in {"folder", "cover"},
            )
        scroll = ttk.Scrollbar(preview, orient="vertical", command=self.tree.yview)
        hscroll = ttk.Scrollbar(preview, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=hscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        ttk.Label(preview, textvariable=self.summary_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        backup = ttk.LabelFrame(
            self.frame, text="Резервная копия исходных файлов", padding=9
        )
        backup.grid(row=2, column=0, sticky="ew", pady=7)
        backup.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            backup,
            text="Делать резервную копию перед записью",
            variable=self.backup_enabled_var,
            command=self._backup_state_changed,
        ).grid(row=0, column=0, padx=(0, 8))
        self.backup_entry = ttk.Entry(
            backup, textvariable=self.backup_path_var, state="readonly"
        )
        self.backup_entry.grid(row=0, column=1, sticky="ew")
        self.backup_button = ttk.Button(
            backup, text="Выбрать...", command=self._choose_backup
        )
        self.backup_button.grid(row=0, column=2, padx=(8, 0))
        backup_state = "normal" if self.backup_enabled_var.get() else "disabled"
        entry_state = "readonly" if self.backup_enabled_var.get() else "disabled"
        self.backup_button.configure(state=backup_state)
        self.backup_entry.configure(state=entry_state)

        progress_holder = ttk.Frame(self.frame)
        progress_holder.grid(row=3, column=0, sticky="ew")
        progress_holder.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            progress_holder,
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_holder, textvariable=self.status_var).grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )

        actions = ttk.Frame(self.frame)
        actions.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        self.preview_button = ttk.Button(
            actions, text="Проверить папки", command=self.preview
        )
        self.preview_button.pack(side="left")
        self.apply_button = ttk.Button(
            actions,
            text="Встроить обложки",
            command=self.apply,
            style="Accent.TButton",
            state="disabled",
        )
        self.apply_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(
            actions, text="Остановить", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left")

        self._schedule_poll()

    # -- root folder and backup -------------------------------------------
    def _root(self) -> Path | None:
        value = self.root_var.get().strip()
        return Path(value) if value else None

    @staticmethod
    def _default_backup_path(root: Path | None) -> str:
        if root is None:
            return ""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(root.parent / f"{root.name}_cover_backup_{stamp}")

    def _choose_root(self) -> None:
        current = self.root_var.get() or None
        chosen = filedialog.askdirectory(
            parent=self.frame,
            title="Папка коллекции",
            initialdir=current,
        )
        if not chosen:
            return
        self.root_var.set(chosen)
        self.backup_path_var.set(self._default_backup_path(Path(chosen)))
        self._invalidate_plan()
        self.preview()

    def _choose_backup(self) -> None:
        current = self.backup_path_var.get()
        chosen = filedialog.askdirectory(
            parent=self.frame,
            title="Папка для резервных копий",
            initialdir=str(Path(current).parent) if current else None,
        )
        if chosen:
            self.backup_path_var.set(chosen)

    def _backup_state_changed(self) -> None:
        enabled = self.backup_enabled_var.get()
        self.backup_button.configure(state="normal" if enabled else "disabled")
        self.backup_entry.configure(state="readonly" if enabled else "disabled")
        # The choice is a user preference: both tag writers remember it.
        self.context.on_backup_changed(enabled)

    def _invalidate_plan(self) -> None:
        self.plan = None
        self.tree.delete(*self.tree.get_children())
        self.summary_var.set("")
        self.apply_button.configure(state="disabled")

    # -- preview -----------------------------------------------------------
    def preview(self) -> None:
        if self.busy:
            return
        root = self._root()
        if root is None or not root.is_dir():
            messagebox.showwarning(
                WINDOW_TITLE,
                "Выберите существующую папку коллекции",
                parent=self.frame,
            )
            return
        self._invalidate_plan()
        self._start_busy("Проверка папок...")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        include_subfolders = self.include_subfolders_var.get()
        replace_broken = self.replace_broken_var.get()
        excluded = self.context.excluded_folders
        extensions = self.context.extensions

        def progress(files: int, folders: int, label: str) -> None:
            self.events.put(("plan_progress", files, folders, label))

        def run() -> None:
            try:
                plan = plan_cover_embedding(
                    root,
                    extensions=extensions,
                    include_subfolders=include_subfolders,
                    excluded_folders=excluded,
                    replace_broken=replace_broken,
                    stop_event=self.stop_event,
                    progress=progress,
                )
                self.events.put(("plan", plan))
            except CoverTaskStopped:
                self.events.put(("plan_stopped",))
            except Exception as exc:
                self.events.put(("plan_error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _plan_finished(self, plan: CoverPlan) -> None:
        self.plan = plan
        self._stop_busy()
        self.tree.delete(*self.tree.get_children())
        for folder in plan.folders:
            cover = folder.cover
            self.tree.insert(
                "",
                "end",
                values=(
                    folder.relative_folder,
                    f"{cover.path.name} ({cover.width}×{cover.height})",
                    len(folder.targets),
                    folder.files_with_cover,
                ),
            )
        details = [
            f"Папок к обработке: {plan.folder_count}",
            f"файлов без обложки: {plan.target_count}",
        ]
        if plan.files_with_cover:
            details.append(f"уже с обложкой: {plan.files_with_cover}")
        if plan.files_with_broken_cover:
            details.append(
                "повреждённых обложек: "
                f"{plan.files_with_broken_cover} (не заменяются: включите опцию)"
            )
        if plan.problems:
            details.append(f"проблемных файлов: {len(plan.problems)}")
        self.summary_var.set("; ".join(details))
        if plan.target_count:
            self.status_var.set(
                f"Найдено {plan.target_count} {files_word(plan.target_count)} "
                f"в {plan.folder_count} {folders_word(plan.folder_count)}. "
                "Проверьте список и нажмите «Встроить обложки»."
            )
            self.apply_button.configure(state="normal")
        else:
            self.status_var.set("Вставлять нечего: во всех папках обложки уже есть")
        if plan.problems:
            messagebox.showwarning(
                WINDOW_TITLE,
                "Часть файлов не удалось проверить:\n"
                + "\n".join(
                    f"• {problem.relative_path}: {problem.reason}"
                    for problem in plan.problems[:8]
                ),
                parent=self.frame,
            )

    # -- apply -------------------------------------------------------------
    def apply(self) -> None:
        if self.busy or self.plan is None or not self.plan.target_count:
            return
        root = self._root()
        if root is None or not root.is_dir():
            return
        backup_root: Path | None = None
        if self.backup_enabled_var.get():
            raw = self.backup_path_var.get().strip()
            if not raw:
                messagebox.showwarning(
                    WINDOW_TITLE,
                    "Укажите папку для резервной копии или отключите её",
                    parent=self.frame,
                )
                return
            backup_root = Path(raw)
            try:
                backup_root.resolve().relative_to(root.resolve())
            except ValueError:
                pass
            else:
                messagebox.showwarning(
                    WINDOW_TITLE,
                    "Папка резервной копии не должна находиться внутри "
                    "обрабатываемой коллекции.",
                    parent=self.frame,
                )
                return
        plan = self.plan
        backup_note = (
            "Резервные копии будут созданы."
            if backup_root is not None
            else "Резервные копии отключены."
        )
        confirmed = messagebox.askyesno(
            WINDOW_TITLE,
            f"Встроить обложку в {plan.target_count} "
            f"{files_word(plan.target_count)} в {plan.folder_count} "
            f"{folders_word(plan.folder_count)}?\n\n"
            "Теги файлов будут изменены. Само аудио не перекодируется.\n"
            f"{backup_note}",
            parent=self.frame,
        )
        if not confirmed:
            return
        self._start_busy("Встраивание обложек...")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress_var.set(0)

        def progress(current: int, total: int, label: str) -> None:
            self.events.put(("embed_progress", current, total, label))

        def run() -> None:
            try:
                result = embed_covers(
                    plan,
                    backup_root=backup_root,
                    stop_event=self.stop_event,
                    progress=progress,
                )
                self.events.put(("embed", result))
            except Exception as exc:
                self.events.put(("embed_error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _embed_finished(self, result: CoverEmbedResult) -> None:
        self._stop_busy()
        root = self._root()
        self.status_var.set(
            "Готово" if not result.stopped else "Остановлено пользователем"
        )
        details = [
            f"Обложка встроена в {result.updated_files} "
            f"{files_word(result.updated_files)} "
            f"в {result.folders_updated} {folders_word(result.folders_updated)}.",
            f"Создано резервных копий: {result.backup_files}.",
        ]
        if result.failures:
            details.append(f"Не удалось изменить: {len(result.failures)}.")
            details.extend(
                f"• {failure.path.name}: {failure.reason}"
                for failure in result.failures[:8]
            )
        if result.stopped:
            details.append("Обработка была остановлена до конца списка.")
        messagebox.showinfo(WINDOW_TITLE, "\n".join(details), parent=self.frame)
        if result.updated_files and root is not None:
            self.context.on_completed(root)
            self.preview()
        else:
            self.status_var.set("Изменений нет")

    # -- infrastructure ----------------------------------------------------
    def stop(self) -> None:
        if self.busy and self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.stop_button.configure(state="disabled")
            self.status_var.set("Остановка после текущего файла...")

    def _start_busy(self, status: str) -> None:
        self.busy = True
        self.stop_event.clear()
        self.status_var.set(status)
        self.preview_button.configure(state="disabled")
        self.apply_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def _stop_busy(self) -> None:
        self.busy = False
        self.worker = None
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress_var.set(0)
        self.preview_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _schedule_poll(self) -> None:
        self._poll_job = self.frame.after(100, self._poll_events)

    def _poll_events(self) -> None:
        if not self.frame.winfo_exists():
            return
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "plan_progress":
                    _, files, folders, label = event
                    self.status_var.set(
                        f"Проверка: {folders} {folders_word(folders)}, "
                        f"{files} {files_word(files)} — …{label[-70:]}"
                    )
                elif kind == "plan":
                    self._plan_finished(event[1])
                elif kind == "plan_stopped":
                    self._stop_busy()
                    self.status_var.set("Проверка остановлена")
                elif kind == "plan_error":
                    self._stop_busy()
                    self.status_var.set("Не удалось проверить папки")
                    messagebox.showerror(
                        WINDOW_TITLE,
                        f"Проверка не выполнена.\n\nПричина: {event[1]}",
                        parent=self.frame,
                    )
                elif kind == "embed_progress":
                    _, current, total, label = event
                    self.progress_var.set(
                        round(current / total * 100) if total else 0
                    )
                    self.status_var.set(f"{current} из {total}: …{label[-70:]}")
                elif kind == "embed":
                    self._embed_finished(event[1])
                elif kind == "embed_error":
                    self._stop_busy()
                    self.status_var.set("Не удалось встроить обложки")
                    messagebox.showerror(
                        WINDOW_TITLE,
                        f"Обложки не встроены.\n\nПричина: {event[1]}",
                        parent=self.frame,
                    )
        except queue.Empty:
            pass
        self._schedule_poll()

    def can_close(self) -> bool:
        if not self.busy:
            return True
        messagebox.showwarning(
            WINDOW_TITLE,
            "Сначала дождитесь завершения или нажмите «Остановить».",
            parent=self.frame,
        )
        return False

    def close(self) -> None:
        if self._poll_job is not None:
            with contextlib.suppress(tk.TclError):
                self.frame.after_cancel(self._poll_job)
            self._poll_job = None




class CoverExtractionPanel(UtilityPanel):
    """Save the cover embedded in the tags into the album folder."""

    title = "Обложка из тегов в файл папки"
    description = (
        "Находит папки без файла обложки, где у большинства треков встроена "
        "одна и та же картинка, и сохраняет её рядом с аудио как cover.jpg, "
        "cover.png или cover.webp — его читают foobar2000, Kodi, Plex и "
        "проводник. Аудиофайлы не изменяются, резервные копии не нужны. "
        "Папки с разными обложками у треков пропускаются."
    )

    def build(self) -> None:
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.plan: CoverExtractionPlan | None = None
        self.busy = False
        self._poll_job: str | None = None

        default_root = (
            str(self.context.root_folder) if self.context.root_folder else ""
        )
        self.root_var = tk.StringVar(value=default_root)
        self.include_subfolders_var = tk.BooleanVar(
            value=self.context.include_subfolders
        )
        self.status_var = tk.StringVar(
            value=(
                "Нажмите «Проверить папки», чтобы найти обложки только в тегах"
                if default_root
                else "Папка коллекции не выбрана"
            )
        )
        self.summary_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)

        source = ttk.LabelFrame(self.frame, text="Папка коллекции", padding=9)
        source.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text="Папка").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(source, textvariable=self.root_var, state="readonly").grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(source, text="Выбрать...", command=self._choose_root).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Checkbutton(
            source,
            text="Включать подпапки",
            variable=self.include_subfolders_var,
            command=self._invalidate_plan,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(7, 0))

        preview = ttk.LabelFrame(
            self.frame,
            text="Предпросмотр: папки, куда будет записана обложка",
            padding=9,
        )
        preview.grid(row=1, column=0, sticky="nsew")
        self.frame.rowconfigure(1, weight=1)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        columns = ("folder", "source", "size", "matching", "target")
        self.tree = ttk.Treeview(
            preview,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=11,
        )
        headings = {
            "folder": "Папка",
            "source": "Источник обложки",
            "size": "Размер",
            "matching": "Обложка у файлов",
            "target": "Будет создан",
        }
        widths = {
            "folder": 230,
            "source": 185,
            "size": 90,
            "matching": 120,
            "target": 105,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                minwidth=70,
                stretch=column in {"folder", "source"},
            )
        scroll = ttk.Scrollbar(preview, orient="vertical", command=self.tree.yview)
        hscroll = ttk.Scrollbar(preview, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=hscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        ttk.Label(preview, textvariable=self.summary_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        progress_holder = ttk.Frame(self.frame)
        progress_holder.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        progress_holder.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            progress_holder,
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_holder, textvariable=self.status_var).grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )

        actions = ttk.Frame(self.frame)
        actions.grid(row=3, column=0, sticky="ew", pady=(9, 0))
        self.preview_button = ttk.Button(
            actions, text="Проверить папки", command=self.preview
        )
        self.preview_button.pack(side="left")
        self.apply_button = ttk.Button(
            actions,
            text="Записать обложки",
            command=self.apply,
            style="Accent.TButton",
            state="disabled",
        )
        self.apply_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(
            actions, text="Остановить", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left")

        self._schedule_poll()

    # -- root folder -------------------------------------------------------
    def _root(self) -> Path | None:
        value = self.root_var.get().strip()
        return Path(value) if value else None

    def _choose_root(self) -> None:
        current = self.root_var.get() or None
        chosen = filedialog.askdirectory(
            parent=self.frame,
            title="Папка коллекции",
            initialdir=current,
        )
        if not chosen:
            return
        self.root_var.set(chosen)
        self._invalidate_plan()
        self.preview()

    def _invalidate_plan(self) -> None:
        self.plan = None
        self.tree.delete(*self.tree.get_children())
        self.summary_var.set("")
        self.apply_button.configure(state="disabled")

    # -- preview -----------------------------------------------------------
    def preview(self) -> None:
        if self.busy:
            return
        root = self._root()
        if root is None or not root.is_dir():
            messagebox.showwarning(
                WINDOW_TITLE,
                "Выберите существующую папку коллекции",
                parent=self.frame,
            )
            return
        self._invalidate_plan()
        self._start_busy("Проверка папок...")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        include_subfolders = self.include_subfolders_var.get()
        excluded = self.context.excluded_folders
        extensions = self.context.extensions

        def progress(files: int, folders: int, label: str) -> None:
            self.events.put(("plan_progress", files, folders, label))

        def run() -> None:
            try:
                plan = plan_cover_extraction(
                    root,
                    extensions=extensions,
                    include_subfolders=include_subfolders,
                    excluded_folders=excluded,
                    stop_event=self.stop_event,
                    progress=progress,
                )
                self.events.put(("plan", plan))
            except CoverTaskStopped:
                self.events.put(("plan_stopped",))
            except Exception as exc:
                self.events.put(("plan_error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _plan_finished(self, plan: CoverExtractionPlan) -> None:
        self.plan = plan
        self._stop_busy()
        self.tree.delete(*self.tree.get_children())
        for target in plan.targets:
            self.tree.insert(
                "",
                "end",
                values=(
                    target.relative_folder,
                    f"{target.source.name} ({target.width}×{target.height})",
                    f"{target.size_kb:.0f} KB",
                    f"{target.matching} из {target.total}",
                    target.destination.name,
                ),
            )
        details = [f"Папок к записи: {plan.writable}"]
        if plan.skipped:
            details.append(f"пропущено папок: {len(plan.skipped)}")
        if plan.problems:
            details.append(f"проблемных файлов: {len(plan.problems)}")
        self.summary_var.set("; ".join(details))
        if plan.writable:
            self.status_var.set(
                f"Найдено {plan.writable} {folders_word(plan.writable)}. "
                "Проверьте список и нажмите «Записать обложки»."
            )
            self.apply_button.configure(state="normal")
        else:
            self.status_var.set(
                "Записывать нечего: в папках уже есть файл обложки или "
                "нет общей встроенной картинки"
            )
        notes = [
            f"• {item.relative_folder}: {item.reason}" for item in plan.skipped[:8]
        ]
        notes.extend(
            f"• {item.relative_path}: {item.reason}" for item in plan.problems[:8]
        )
        if notes:
            messagebox.showinfo(
                WINDOW_TITLE,
                "Пропущенные папки и проблемы:\n" + "\n".join(notes),
                parent=self.frame,
            )

    # -- write -------------------------------------------------------------
    def apply(self) -> None:
        if self.busy or self.plan is None or not self.plan.targets:
            return
        root = self._root()
        if root is None or not root.is_dir():
            return
        plan = self.plan
        confirmed = messagebox.askyesno(
            WINDOW_TITLE,
            f"Записать обложки в {plan.writable} "
            f"{folders_word(plan.writable)}?\n\n"
            "Аудиофайлы не изменяются, существующие файлы обложек не "
            "перезаписываются.",
            parent=self.frame,
        )
        if not confirmed:
            return
        self._start_busy("Запись обложек...")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress_var.set(0)

        def progress(current: int, total: int, label: str) -> None:
            self.events.put(("write_progress", current, total, label))

        def run() -> None:
            try:
                result = write_covers(
                    plan, stop_event=self.stop_event, progress=progress
                )
                self.events.put(("write", result))
            except Exception as exc:
                self.events.put(("write_error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _write_finished(self, result: CoverExtractionResult) -> None:
        self._stop_busy()
        root = self._root()
        self.status_var.set(
            "Готово" if not result.stopped else "Остановлено пользователем"
        )
        details = [
            f"Записано обложек: {result.written} "
            f"в {result.written} {folders_word(result.written)}.",
        ]
        if result.failures:
            details.append(f"Не удалось записать: {len(result.failures)}.")
            details.extend(
                f"• {failure.destination.name}: {failure.reason}"
                for failure in result.failures[:8]
            )
        if result.stopped:
            details.append("Обработка была остановлена до конца списка.")
        messagebox.showinfo(WINDOW_TITLE, "\n".join(details), parent=self.frame)
        if result.written and root is not None:
            self.context.on_completed(root)
            self.preview()

    # -- infrastructure ----------------------------------------------------
    def stop(self) -> None:
        if self.busy and self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.stop_button.configure(state="disabled")
            self.status_var.set("Остановка после текущей папки...")

    def _start_busy(self, status: str) -> None:
        self.busy = True
        self.stop_event.clear()
        self.status_var.set(status)
        self.preview_button.configure(state="disabled")
        self.apply_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def _stop_busy(self) -> None:
        self.busy = False
        self.worker = None
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress_var.set(0)
        self.preview_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _schedule_poll(self) -> None:
        self._poll_job = self.frame.after(100, self._poll_events)

    def _poll_events(self) -> None:
        if not self.frame.winfo_exists():
            return
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "plan_progress":
                    _, files, folders, label = event
                    self.status_var.set(
                        f"Проверка: {folders} {folders_word(folders)}, "
                        f"{files} {files_word(files)} — …{label[-70:]}"
                    )
                elif kind == "plan":
                    self._plan_finished(event[1])
                elif kind == "plan_stopped":
                    self._stop_busy()
                    self.status_var.set("Проверка остановлена")
                elif kind == "plan_error":
                    self._stop_busy()
                    self.status_var.set("Не удалось проверить папки")
                    messagebox.showerror(
                        WINDOW_TITLE,
                        f"Проверка не выполнена.\n\nПричина: {event[1]}",
                        parent=self.frame,
                    )
                elif kind == "write_progress":
                    _, current, total, label = event
                    self.progress_var.set(
                        round(current / total * 100) if total else 0
                    )
                    self.status_var.set(f"{current} из {total}: …{label[-70:]}")
                elif kind == "write":
                    self._write_finished(event[1])
                elif kind == "write_error":
                    self._stop_busy()
                    self.status_var.set("Не удалось записать обложки")
                    messagebox.showerror(
                        WINDOW_TITLE,
                        f"Обложки не записаны.\n\nПричина: {event[1]}",
                        parent=self.frame,
                    )
        except queue.Empty:
            pass
        self._schedule_poll()

    def can_close(self) -> bool:
        if not self.busy:
            return True
        messagebox.showwarning(
            WINDOW_TITLE,
            "Сначала дождитесь завершения или нажмите «Остановить».",
            parent=self.frame,
        )
        return False

    def close(self) -> None:
        if self._poll_job is not None:
            with contextlib.suppress(tk.TclError):
                self.frame.after_cancel(self._poll_job)
            self._poll_job = None


# The cover square in the dialog's left column: as wide as the list above it.
COVER_BOX = 240


UTILITY_PANELS: tuple[type[UtilityPanel], ...] = (
    CoverEmbeddingPanel,
    CoverExtractionPanel,
    OnlineTagsPanel,
)


class UtilitiesDialog:
    """Left list of utilities, right panel with the selected one."""

    def __init__(self, parent: tk.Misc, context: UtilityContext) -> None:
        self.parent = parent
        self.context = context
        self.panels: dict[str, UtilityPanel] = {}
        self.current_key = ""

        self.window = tk.Toplevel(parent)
        self.window.title(f"{APP_NAME} — {WINDOW_TITLE}")
        self.window.geometry("1120x760")
        self.window.minsize(940, 620)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.columnconfigure(1, weight=1)
        self.window.rowconfigure(1, weight=1)

        intro = ttk.Label(
            self.window,
            text=(
                "Утилиты обслуживают коллекцию целиком и не требуют "
                "предварительного анализа. Список будет пополняться."
            ),
            wraplength=1040,
            justify="left",
        )
        intro.grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 6))

        left = ttk.LabelFrame(self.window, text="Утилиты", padding=6)
        left.grid(row=1, column=0, sticky="nsw", padx=(12, 6), pady=(0, 6))
        left.rowconfigure(1, weight=1)
        self.list = ttk.Treeview(
            left,
            show="tree",
            selectmode="browse",
            height=14,
        )
        self.list.column("#0", width=240, stretch=False)
        for index, panel_class in enumerate(UTILITY_PANELS):
            self.list.insert("", "end", iid=str(index), text=panel_class.title)
        self.list.grid(row=0, column=0, sticky="ns")
        self.list.bind("<<TreeviewSelect>>", self._selection_changed)

        # The empty room under the list is the cover of the album the panel is
        # working on: «Загрузка обложки… 42 %» while it downloads, the picture
        # after. A click asks the panel for the large view.
        self.cover_frame = ttk.Frame(left, width=COVER_BOX, height=COVER_BOX)
        self.cover_frame.grid(row=1, column=0, sticky="nw", pady=(10, 0))
        self.cover_frame.grid_propagate(False)
        self.cover_photo: ImageTk.PhotoImage | None = None
        self.cover_label = ttk.Label(
            self.cover_frame,
            anchor="center",
            justify="center",
            wraplength=COVER_BOX - 20,
            relief="solid",
            borderwidth=1,
        )
        self.cover_label.pack(fill="both", expand=True)
        self.cover_label.configure(cursor="hand2")
        self.cover_label.bind("<Button-1>", lambda _event: self._open_cover())

        self.container = ttk.Frame(self.window)
        self.container.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=(0, 6))
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(2, weight=1)
        self.title_var = tk.StringVar()
        self.description_var = tk.StringVar()
        ttk.Label(
            self.container,
            textvariable=self.title_var,
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.description_label = ttk.Label(
            self.container,
            textvariable=self.description_var,
            wraplength=700,
            justify="left",
        )
        self.description_label.grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.container.bind("<Configure>", self._resize_description)

        actions = ttk.Frame(self.window)
        actions.grid(row=2, column=0, columnspan=2, sticky="e", padx=12, pady=(0, 12))
        ttk.Button(actions, text="Закрыть", command=self.close).pack(side="right")

        if UTILITY_PANELS:
            self.list.selection_set("0")
            self.list.focus("0")
            self._show(0)

    def _show_cover(self, data: bytes | None, text: str = "") -> None:
        """The left column of the dialog: the cover, or words about it."""
        if not data:
            self.cover_photo = None
            self.cover_label.configure(image="", text=text)
            return
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.thumbnail((COVER_BOX, COVER_BOX))
                photo = ImageTk.PhotoImage(image.convert("RGB"))
        except Exception:
            self.cover_photo = None
            self.cover_label.configure(image="", text="Обложка не загружена")
            return
        self.cover_photo = photo
        self.cover_label.configure(image=photo, text="")

    def _open_cover(self) -> None:
        panel = self.panels.get(self.current_key)
        opener = getattr(panel, "open_cover_preview", None)
        if callable(opener):
            opener()

    def _resize_description(self, event) -> None:
        self.description_label.configure(wraplength=max(320, event.width - 12))

    def _selection_changed(self, _event=None) -> None:
        selection = self.list.selection()
        if selection:
            self._show(int(selection[0]))

    def _show(self, index: int) -> None:
        panel_class = UTILITY_PANELS[index]
        key = panel_class.__name__
        if key == self.current_key:
            return
        current = self.panels.get(self.current_key)
        if current is not None and not current.can_close():
            # Keep the list on the panel that is still working.
            self.list.selection_set(str(UTILITY_PANELS.index(type(current))))
            return
        panel = self.panels.get(key)
        if panel is None:
            panel = panel_class(
                self.container, replace(self.context, on_cover=self._show_cover)
            )
            self.panels[key] = panel
            panel.frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        panel.frame.tkraise()
        self.title_var.set(panel.title)
        self.description_var.set(panel.description)
        self.current_key = key
        # The left column belongs to whichever utility is open now.
        refresh = getattr(panel, "report_cover", None)
        if callable(refresh):
            refresh()
        else:
            self._show_cover(None, "")

    def close(self) -> None:
        for panel in self.panels.values():
            if not panel.can_close():
                return
        for panel in self.panels.values():
            panel.close()
        self.window.destroy()
