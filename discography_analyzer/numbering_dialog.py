"""Preview and apply «Исправить нумерацию» — one total for the whole group.

The dialog never decides on its own: it shows every file with its current
``1/6`` and the proposed ``1/7``, lets the user deselect rows, and asks for
confirmation before any tag is written.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .numbering_fix import (
    NumberingChange,
    NumberingPlan,
    NumberingResult,
    apply_numbering_fix,
)

TITLE = "Исправить нумерацию"


class NumberingFixDialog:
    """Show the proposed Track # totals and rewrite the selected files."""

    def __init__(
        self,
        parent: tk.Misc,
        plan: NumberingPlan,
        collection_root: Path,
        *,
        backup_enabled: bool,
        on_backup_changed: Callable[[bool], None],
        on_completed: Callable[[], None],
    ) -> None:
        self.parent = parent
        self.plan = plan
        self.collection_root = collection_root
        self.on_backup_changed = on_backup_changed
        self.on_completed = on_completed
        self.changes: dict[str, NumberingChange] = {
            change.relative_path: change for change in plan.changes
        }
        self.selected: set[str] = set(self.changes)
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.window = tk.Toplevel(parent)
        self.window.title(TITLE)
        self.window.geometry("980x620")
        self.window.minsize(820, 520)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)

        self.backup_enabled_var = tk.BooleanVar(value=backup_enabled)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.backup_path_var = tk.StringVar(
            value=str(
                collection_root.parent
                / f"{collection_root.name}_numbering_backup_{stamp}"
            )
        )
        self.status_var = tk.StringVar(value="Готово к проверке")
        self.count_var = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0)

        self._build()
        self._refresh_rows()

    def _build(self) -> None:
        totals = ", ".join(str(total) for total in self.plan.totals) or "—"
        intro = ttk.LabelFrame(self.window, text="Предлагаемое исправление", padding=10)
        intro.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "Номера файлов не меняются — выравнивается только общий итог "
                f"Track #: он станет {totals} (по максимальному найденному номеру). "
                "Например 1/6 станет 1/7."
            ),
            wraplength=900,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        if self.plan.unnumbered:
            ttk.Label(
                intro,
                text=(
                    "Файлы без Track # не изменяются: "
                    + ", ".join(self.plan.unnumbered[:6])
                    + (" …" if len(self.plan.unnumbered) > 6 else "")
                ),
                wraplength=900,
                justify="left",
            ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        holder = ttk.Frame(self.window)
        holder.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        columns = ("selected", "file", "folder", "current", "proposed")
        self.tree = ttk.Treeview(
            holder,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=14,
        )
        headings = {
            "selected": "Исправить",
            "file": "Файл",
            "folder": "Папка",
            "current": "Сейчас",
            "proposed": "Будет",
        }
        widths = {
            "selected": 80,
            "file": 260,
            "folder": 240,
            "current": 110,
            "proposed": 110,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                minwidth=70,
                stretch=column in {"file", "folder"},
            )
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._toggle_selected)
        self.tree.bind("<space>", self._toggle_selected)

        selection = ttk.Frame(self.window)
        selection.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 6))
        ttk.Button(
            selection, text="Выбрать все", command=self._select_all
        ).pack(side="left")
        ttk.Button(
            selection, text="Снять выбор", command=self._select_none
        ).pack(side="left", padx=6)
        ttk.Label(selection, textvariable=self.count_var).pack(side="right")

        backup = ttk.LabelFrame(
            self.window, text="Резервная копия исходных файлов", padding=9
        )
        backup.grid(row=4, column=0, sticky="ew", padx=12, pady=6)
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

        progress_holder = ttk.Frame(self.window)
        progress_holder.grid(row=5, column=0, sticky="ew", padx=12, pady=6)
        progress_holder.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            progress_holder, maximum=100, variable=self.progress_var
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_holder, textvariable=self.status_var).grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )

        actions = ttk.Frame(self.window)
        actions.grid(row=6, column=0, sticky="e", padx=12, pady=(6, 12))
        self.start_button = ttk.Button(
            actions,
            text="Применить",
            command=self.start,
            style="Accent.TButton",
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            actions, text="Остановить", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=6)
        self.close_button = ttk.Button(actions, text="Закрыть", command=self.close)
        self.close_button.pack(side="left")

        self._backup_state_changed()

    def _refresh_rows(self) -> None:
        focused = self.tree.focus()
        self.tree.delete(*self.tree.get_children())
        for change in self.plan.changes:
            self.tree.insert(
                "",
                "end",
                iid=change.relative_path,
                values=(
                    "✓" if change.relative_path in self.selected else "",
                    change.path.name,
                    (
                        "(корень)"
                        if str(Path(change.relative_path).parent) == "."
                        else str(Path(change.relative_path).parent)
                    ),
                    change.current,
                    change.new_value,
                ),
            )
        if focused and self.tree.exists(focused):
            self.tree.focus(focused)
            self.tree.selection_set(focused)
        self.count_var.set(f"Выбрано: {len(self.selected)} из {len(self.changes)}")
        self.start_button.configure(
            state="normal"
            if self.selected and not (self.worker and self.worker.is_alive())
            else "disabled"
        )

    def _toggle_selected(self, _event=None):
        row = self.tree.focus()
        if row not in self.changes:
            return None
        if row in self.selected:
            self.selected.discard(row)
        else:
            self.selected.add(row)
        self._refresh_rows()
        return "break"

    def _select_all(self) -> None:
        self.selected = set(self.changes)
        self._refresh_rows()

    def _select_none(self) -> None:
        self.selected.clear()
        self._refresh_rows()

    def _backup_state_changed(self) -> None:
        enabled = self.backup_enabled_var.get()
        self.backup_entry.configure(state="readonly" if enabled else "disabled")
        self.backup_button.configure(state="normal" if enabled else "disabled")
        self.on_backup_changed(enabled)

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
            change for key, change in self.changes.items() if key in self.selected
        ]
        if not selected:
            return
        backup_root: Path | None = None
        if self.backup_enabled_var.get():
            raw = self.backup_path_var.get().strip()
            if not raw:
                messagebox.showwarning(
                    TITLE,
                    "Укажите папку для резервной копии или отключите её",
                    parent=self.window,
                )
                return
            backup_root = Path(raw)
            try:
                backup_root.resolve().relative_to(self.collection_root.resolve())
            except ValueError:
                pass
            else:
                messagebox.showwarning(
                    TITLE,
                    "Папка резервной копии не должна находиться внутри "
                    "анализируемой коллекции.",
                    parent=self.window,
                )
                return
        self.stop_event.clear()
        self.progress_var.set(0)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.close_button.configure(state="disabled")
        self.status_var.set("Подготовка...")
        root = self.collection_root

        def progress(current: int, total: int, name: str) -> None:
            self.events.put(("progress", current, total, name))

        def run() -> None:
            try:
                result = apply_numbering_fix(
                    selected,
                    root=root,
                    backup_root=backup_root,
                    stop_event=self.stop_event,
                    progress=progress,
                )
                self.events.put(("result", result))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        self.window.after(100, self._poll_events)

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
                    _, current, total, name = event
                    self.progress_var.set(round(current / total * 100) if total else 0)
                    self.status_var.set(f"{current} из {total}: {name}")
                elif event[0] == "result":
                    self._finished(event[1])
                elif event[0] == "error":
                    self._failed(event[1])
        except queue.Empty:
            pass
        self.window.after(100, self._poll_events)

    def _finished(self, result: NumberingResult) -> None:
        self.worker = None
        self.stop_button.configure(state="disabled")
        self.close_button.configure(state="normal")
        self.status_var.set(
            "Нумерация исправлена" if not result.stopped else "Исправление остановлено"
        )
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
        messagebox.showinfo(TITLE, "\n".join(details), parent=self.window)
        if result.updated_files:
            self.window.destroy()
            self.parent.after(100, self.on_completed)
        else:
            self._refresh_rows()

    def _failed(self, reason: str) -> None:
        self.worker = None
        self.stop_button.configure(state="disabled")
        self.close_button.configure(state="normal")
        self.status_var.set("Не удалось применить исправление")
        self._refresh_rows()
        messagebox.showerror(
            TITLE,
            f"Исправление не применено.\n\nПричина: {reason}",
            parent=self.window,
        )

    def close(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(
                TITLE,
                "Сначала дождитесь завершения или нажмите «Остановить».",
                parent=self.window,
            )
            return
        self.window.destroy()
