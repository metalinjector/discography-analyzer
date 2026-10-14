from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .audit_models import MetadataAuditIssue
from .metadata_writer import MetadataFixResult, apply_metadata_fixes
from .models import Track


class AuditFixDialog:
    """Preview and apply only explicitly selected mechanical metadata fixes."""

    def __init__(
        self,
        parent: tk.Misc,
        tracks: list[Track],
        issues: list[MetadataAuditIssue],
        collection_root: Path,
        on_completed: Callable[[], None],
    ) -> None:
        self.parent = parent
        self.tracks_by_id = {track.id: track for track in tracks}
        self.issues = [issue for issue in issues if issue.fixable]
        self.issue_by_id = {issue.id: issue for issue in self.issues}
        self.collection_root = collection_root
        self.on_completed = on_completed
        self.selected_ids = {
            issue.id for issue in self.issues if issue.safe_fix
        }
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.window = tk.Toplevel(parent)
        self.window.title("Безопасное исправление метаданных")
        self.window.geometry("1040x650")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        self.backup_enabled_var = tk.BooleanVar(value=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.backup_path_var = tk.StringVar(
            value=str(
                collection_root.parent
                / f"{collection_root.name}_metadata_backup_{timestamp}"
            )
        )
        self.status_var = tk.StringVar(value="Готово к проверке")
        self.count_var = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0)

        self._build()
        self._refresh_rows()
        self.window.after(100, self._poll_events)

    def _build(self) -> None:
        intro = ttk.LabelFrame(
            self.window,
            text="Предпросмотр механических исправлений",
            padding=10,
        )
        intro.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "Автоматически выбраны только исправления с высокой "
                "уверенностью: разделители исполнителей и лишние пробелы. "
                "Остальные замечания программа не изменяет."
            ),
            wraplength=980,
            justify="left",
        ).grid(row=0, column=0, sticky="w")

        table_holder = ttk.Frame(self.window)
        table_holder.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        table_holder.columnconfigure(0, weight=1)
        table_holder.rowconfigure(0, weight=1)
        columns = ("selected", "file", "field", "current", "suggested", "confidence")
        self.tree = ttk.Treeview(
            table_holder,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=15,
        )
        headings = {
            "selected": "Исправить",
            "file": "Файл",
            "field": "Поле",
            "current": "Сейчас",
            "suggested": "Будет",
            "confidence": "Уверенность",
        }
        widths = {
            "selected": 75,
            "file": 210,
            "field": 105,
            "current": 205,
            "suggested": 205,
            "confidence": 105,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                minwidth=60,
                stretch=column in {"file", "current", "suggested"},
            )
        scroll = ttk.Scrollbar(
            table_holder,
            orient="vertical",
            command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._toggle_selected)
        self.tree.bind("<space>", self._toggle_selected)

        selection = ttk.Frame(self.window)
        selection.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        ttk.Button(
            selection,
            text="Выбрать безопасные",
            command=self._select_safe,
        ).pack(side="left")
        ttk.Button(
            selection,
            text="Снять выбор",
            command=self._select_none,
        ).pack(side="left", padx=6)
        ttk.Label(selection, textvariable=self.count_var).pack(side="right")

        backup = ttk.LabelFrame(
            self.window,
            text="Резервная копия исходных файлов",
            padding=9,
        )
        backup.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        backup.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            backup,
            text="Создать перед изменением",
            variable=self.backup_enabled_var,
            command=self._backup_state_changed,
        ).grid(row=0, column=0, padx=(0, 8))
        self.backup_entry = ttk.Entry(
            backup,
            textvariable=self.backup_path_var,
            state="readonly",
        )
        self.backup_entry.grid(row=0, column=1, sticky="ew")
        self.backup_button = ttk.Button(
            backup,
            text="Выбрать...",
            command=self._choose_backup,
        )
        self.backup_button.grid(row=0, column=2, padx=(8, 0))

        progress_holder = ttk.Frame(self.window)
        progress_holder.grid(row=4, column=0, sticky="ew", padx=12, pady=6)
        progress_holder.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            progress_holder,
            maximum=100,
            variable=self.progress_var,
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_holder, textvariable=self.status_var).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(3, 0),
        )

        actions = ttk.Frame(self.window)
        actions.grid(row=5, column=0, sticky="e", padx=12, pady=(6, 12))
        self.start_button = ttk.Button(
            actions,
            text="Применить выбранные",
            command=self.start,
            style="Accent.TButton",
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            actions,
            text="Остановить",
            command=self.stop,
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=6)
        self.close_button = ttk.Button(
            actions,
            text="Закрыть",
            command=self.close,
        )
        self.close_button.pack(side="left")

    def _refresh_rows(self) -> None:
        selected_row = self.tree.focus()
        self.tree.delete(*self.tree.get_children())
        for issue in self.issues:
            track = self.tracks_by_id.get(issue.track_id)
            self.tree.insert(
                "",
                "end",
                iid=issue.id,
                values=(
                    "✓" if issue.id in self.selected_ids else "",
                    track.filename if track else "Неизвестный файл",
                    issue.field_label,
                    issue.current_value,
                    issue.suggested_value,
                    issue.confidence.value,
                ),
            )
        if selected_row and self.tree.exists(selected_row):
            self.tree.selection_set(selected_row)
            self.tree.focus(selected_row)
        self.count_var.set(
            f"Выбрано: {len(self.selected_ids)} из {len(self.issues)}"
        )
        self.start_button.configure(
            state="normal"
            if self.selected_ids and not (self.worker and self.worker.is_alive())
            else "disabled"
        )

    def _toggle_selected(self, _event=None):
        issue_id = self.tree.focus()
        if issue_id not in self.issue_by_id:
            return None
        if issue_id in self.selected_ids:
            self.selected_ids.remove(issue_id)
        else:
            self.selected_ids.add(issue_id)
        self._refresh_rows()
        return "break"

    def _select_safe(self) -> None:
        self.selected_ids = {
            issue.id for issue in self.issues if issue.safe_fix
        }
        self._refresh_rows()

    def _select_none(self) -> None:
        self.selected_ids.clear()
        self._refresh_rows()

    def _backup_state_changed(self) -> None:
        state = "normal" if self.backup_enabled_var.get() else "disabled"
        self.backup_button.configure(state=state)

    def _choose_backup(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.window,
            title="Папка для резервных копий",
            initialdir=str(Path(self.backup_path_var.get()).parent),
        )
        if chosen:
            self.backup_path_var.set(chosen)

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        selected = [
            self.issue_by_id[issue_id]
            for issue_id in self.selected_ids
            if issue_id in self.issue_by_id
        ]
        if not selected:
            return
        backup_root = (
            Path(self.backup_path_var.get())
            if self.backup_enabled_var.get()
            else None
        )
        if backup_root is not None:
            try:
                backup_root.resolve().relative_to(self.collection_root.resolve())
            except ValueError:
                pass
            else:
                messagebox.showwarning(
                    "Безопасное исправление метаданных",
                    (
                        "Папка резервной копии не должна находиться внутри "
                        "анализируемой коллекции."
                    ),
                    parent=self.window,
                )
                return
        self.stop_event.clear()
        self.progress_var.set(0)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.close_button.configure(state="disabled")
        self.status_var.set("Подготовка...")

        def progress(current: int, total: int, filename: str) -> None:
            self.events.put(("progress", current, total, filename))

        def run() -> None:
            try:
                result = apply_metadata_fixes(
                    self.tracks_by_id,
                    selected,
                    backup_root=backup_root,
                    stop_event=self.stop_event,
                    progress=progress,
                )
                self.events.put(("result", result))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def stop(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.stop_button.configure(state="disabled")
            self.status_var.set("Остановка после текущего файла...")

    def _poll_events(self) -> None:
        if not self.window.winfo_exists():
            return
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, current, total, filename = event
                    self.progress_var.set(
                        round(current / total * 100) if total else 0
                    )
                    self.status_var.set(
                        f"{current} из {total}: {filename}"
                    )
                elif event[0] == "result":
                    self._finished(event[1])
                elif event[0] == "error":
                    self._failed(event[1])
        except queue.Empty:
            pass
        self.window.after(100, self._poll_events)

    def _finished(self, result: MetadataFixResult) -> None:
        self.worker = None
        self.stop_button.configure(state="disabled")
        self.close_button.configure(state="normal")
        if result.stopped:
            self.status_var.set("Исправление остановлено")
        else:
            self.status_var.set("Исправление завершено")
        details = [
            f"Изменено файлов: {result.updated_files}.",
            f"Создано резервных копий: {result.backup_files}.",
        ]
        if result.failures:
            details.append(f"Не удалось изменить: {len(result.failures)}.")
            details.extend(
                f"• {failure.path.name}: {failure.reason}"
                for failure in result.failures[:8]
            )
        messagebox.showinfo(
            "Безопасное исправление метаданных",
            "\n".join(details),
            parent=self.window,
        )
        if result.updated_files:
            self.window.destroy()
            self.parent.after(100, self.on_completed)
        else:
            self._refresh_rows()

    def _failed(self, reason: str) -> None:
        self.worker = None
        self.stop_button.configure(state="disabled")
        self.close_button.configure(state="normal")
        self.status_var.set("Не удалось применить исправления")
        self._refresh_rows()
        messagebox.showerror(
            "Безопасное исправление метаданных",
            f"Исправления не применены.\n\nПричина: {reason}",
            parent=self.window,
        )

    def close(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(
                "Безопасное исправление метаданных",
                "Сначала дождитесь завершения или нажмите «Остановить».",
                parent=self.window,
            )
            return
        self.window.destroy()
