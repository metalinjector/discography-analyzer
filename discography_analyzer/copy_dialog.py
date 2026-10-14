from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .constants import APP_NAME
from .copying import (
    NOT_COPIED_FOLDER,
    CopyMode,
    CopyPlan,
    CopyResult,
    build_copy_plan,
    execute_copy_plan,
)
from .models import Track


class UniqueCopyDialog:
    """Modal UI for the copy operation; selection and I/O live in copying.py."""

    def __init__(
        self,
        parent: tk.Misc,
        tracks: list[Track],
        collection_root: Path,
    ) -> None:
        self.parent = parent
        self.collection_root = collection_root.resolve()
        self.plan: CopyPlan = build_copy_plan(tracks)
        self.events: queue.Queue[tuple] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.running = False

        self.window = tk.Toplevel(parent)
        self.window.title("Копировать уникальные")
        self.window.geometry("780x650")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self.window.columnconfigure(0, weight=1)

        self.destination_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=CopyMode.FLAT.value)
        self.include_rejected_var = tk.BooleanVar(value=False)
        self.group_by_artist_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Готово к копированию")
        self.progress_text_var = tk.StringVar(value="0 / 0")

        self._build()
        self.window.after(100, self._poll_events)

    def _build(self) -> None:
        intro = ttk.LabelFrame(
            self.window,
            text="Отбор файлов",
            padding=9,
        )
        intro.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "Программа идёт от старых дат к новым, оставляет один файл "
                "из подтверждённых дублей и одну копию каждой одинаковой "
                "вариации. Конфликты относятся к исключённым файлам."
            ),
            wraplength=730,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            intro,
            text=(
                f"В основную подборку: {len(self.plan.selected)}  ·  "
                f"Исключено: {len(self.plan.rejected)}  ·  "
                f"Всего проанализировано: {self.plan.total}"
            ),
            font=("TkDefaultFont", 9, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        destination = ttk.LabelFrame(
            self.window,
            text="1. Куда копировать",
            padding=9,
        )
        destination.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        destination.columnconfigure(0, weight=1)
        ttk.Entry(
            destination,
            textvariable=self.destination_var,
            state="readonly",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            destination,
            text="Выбрать папку...",
            command=self._choose_destination,
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(
            destination,
            text=(
                "Существующие файлы не перезаписываются: при совпадении "
                "имени добавляется суффикс (2), (3) и т. д."
            ),
            wraplength=720,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

        mode = ttk.LabelFrame(
            self.window,
            text="2. Способ и порядок копирования",
            padding=9,
        )
        mode.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        mode.columnconfigure(0, weight=1)
        ttk.Radiobutton(
            mode,
            text="Единым списком",
            value=CopyMode.FLAT.value,
            variable=self.mode_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            mode,
            text=(
                "Все файлы помещаются в выбранную папку и получают имена "
                "вида: 01 Исполнитель - Альбом (Год) - 05-Название.flac"
            ),
            wraplength=720,
        ).grid(row=1, column=0, sticky="w", padx=(24, 0), pady=(1, 5))
        ttk.Radiobutton(
            mode,
            text="С сохранением структуры папок",
            value=CopyMode.TREE.value,
            variable=self.mode_var,
        ).grid(row=2, column=0, sticky="w")
        ttk.Label(
            mode,
            text=(
                "Воссоздаётся исходная структура, но повторные файлы, уже "
                "отобранные из более ранних папок, не копируются."
            ),
            wraplength=720,
        ).grid(row=3, column=0, sticky="w", padx=(24, 0), pady=(2, 0))
        ttk.Checkbutton(
            mode,
            text="Разобрать по исполнителям",
            variable=self.group_by_artist_var,
        ).grid(row=4, column=0, sticky="w", pady=(7, 0))
        ttk.Label(
            mode,
            text=(
                "Сначала исполнители по алфавиту, внутри каждого исполнителя "
                "релизы от новых дат к старым. На отбор дублей это не влияет."
            ),
            wraplength=720,
        ).grid(row=5, column=0, sticky="w", padx=(24, 0), pady=(1, 0))

        extra = ttk.LabelFrame(
            self.window,
            text="3. Исключённые файлы",
            padding=9,
        )
        extra.grid(row=3, column=0, sticky="ew", padx=12, pady=4)
        ttk.Checkbutton(
            extra,
            text=(
                f"Также создать папку «{NOT_COPIED_FOLDER}» и скопировать "
                "в неё файлы, исключённые из основной подборки"
            ),
            variable=self.include_rejected_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            extra,
            text=(
                "Для исключённых файлов используется выбранный выше способ: "
                "единый список или исходная структура папок."
            ),
            wraplength=720,
        ).grid(row=1, column=0, sticky="w", padx=(24, 0), pady=(3, 0))

        progress_frame = ttk.Frame(self.window, padding=(12, 5))
        progress_frame.grid(row=4, column=0, sticky="ew")
        progress_frame.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            progress_frame,
            maximum=1,
            mode="determinate",
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            progress_frame,
            textvariable=self.progress_text_var,
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(
            progress_frame,
            textvariable=self.status_var,
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))

        actions = ttk.Frame(self.window, padding=(12, 4, 12, 10))
        actions.grid(row=5, column=0, sticky="e")
        self.start_button = ttk.Button(
            actions,
            text="Начать копирование",
            command=self._start_copy,
            style="Accent.TButton",
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            actions,
            text="Остановить",
            command=self._stop_copy,
            state="disabled",
            style="Stop.TButton",
        )
        self.stop_button.pack(side="left", padx=7)
        self.close_button = ttk.Button(
            actions,
            text="Закрыть",
            command=self._close,
        )
        self.close_button.pack(side="left")

    def _choose_destination(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.window,
            title="Куда копировать уникальные файлы",
            initialdir=str(self.collection_root.parent),
        )
        if selected:
            self.destination_var.set(selected)

    def _target_is_inside_collection(self, target: Path) -> bool:
        try:
            target.relative_to(self.collection_root)
            return True
        except ValueError:
            return False

    def _start_copy(self) -> None:
        if self.running:
            return
        if not self.destination_var.get():
            messagebox.showwarning(
                APP_NAME,
                "Выберите папку назначения",
                parent=self.window,
            )
            return
        try:
            destination = Path(self.destination_var.get()).resolve()
        except OSError as exc:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось определить папку назначения.\n\nПричина: {exc}",
                parent=self.window,
            )
            return
        if destination == self.collection_root:
            messagebox.showerror(
                APP_NAME,
                "Нельзя копировать файлы прямо в исходную корневую папку.",
                parent=self.window,
            )
            return
        if self._target_is_inside_collection(destination):
            proceed = messagebox.askyesno(
                APP_NAME,
                (
                    "Папка назначения находится внутри анализируемой "
                    "коллекции. При следующем анализе копии также будут "
                    "найдены.\n\nПродолжить?"
                ),
                parent=self.window,
            )
            if not proceed:
                return

        include_rejected = self.include_rejected_var.get()
        group_by_artist = self.group_by_artist_var.get()
        total_jobs = len(self.plan.selected) + (
            len(self.plan.rejected) if include_rejected else 0
        )
        if total_jobs == 0:
            messagebox.showinfo(
                APP_NAME,
                "По выбранным правилам нет файлов для копирования.",
                parent=self.window,
            )
            return
        mode = CopyMode(self.mode_var.get())
        confirmed = messagebox.askyesno(
            APP_NAME,
            (
                f"Будет обработано файлов: {total_jobs}\n"
                f"Режим: "
                f"{'единый список' if mode == CopyMode.FLAT else 'структура папок'}\n"
                f"Порядок: "
                f"{'по исполнителям А–Я, даты по убыванию' if group_by_artist else 'от старых дат к новым'}\n"
                f"Папка: {destination}\n\nНачать копирование?"
            ),
            parent=self.window,
        )
        if not confirmed:
            return

        self.stop_event.clear()
        self.running = True
        self.progress.configure(maximum=max(total_jobs, 1), value=0)
        self.progress_text_var.set(f"0 / {total_jobs}")
        self.status_var.set("Подготовка к копированию...")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.close_button.configure(state="disabled")

        def report(done: int, total: int, filename: str) -> None:
            self.events.put(("progress", done, total, filename))

        def run() -> None:
            try:
                result = execute_copy_plan(
                    self.plan,
                    destination,
                    mode,
                    include_rejected=include_rejected,
                    group_by_artist=group_by_artist,
                    stop_event=self.stop_event,
                    progress=report,
                )
                self.events.put(("done", result, destination))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _stop_copy(self) -> None:
        if self.running:
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
                    _, done, total, filename = event
                    self.progress.configure(value=done)
                    self.progress_text_var.set(f"{done} / {total}")
                    self.status_var.set(f"Копирование: {filename}")
                elif event[0] == "done":
                    self._copy_finished(event[1], event[2])
                elif event[0] == "error":
                    self._copy_failed(event[1])
        except queue.Empty:
            pass
        self.window.after(100, self._poll_events)

    def _restore_buttons(self) -> None:
        self.running = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.close_button.configure(state="normal")

    def _copy_finished(self, result: CopyResult, destination: Path) -> None:
        self._restore_buttons()
        if result.stopped:
            self.status_var.set("Копирование остановлено")
        elif result.failures:
            self.status_var.set("Копирование завершено с ошибками")
        else:
            self.status_var.set("Копирование завершено")
        lines = [
            f"Скопировано в основную подборку: {result.copied_selected}",
            f"Скопировано в «{NOT_COPIED_FOLDER}»: {result.copied_rejected}",
            f"Ошибок: {len(result.failures)}",
            f"Папка назначения: {destination}",
        ]
        if result.stopped:
            lines.insert(0, "Операция была остановлена.")
        if result.failures:
            lines.extend(
                [
                    "",
                    "Первые ошибки:",
                    *[
                        f"• {failure.source.name}: {failure.reason}"
                        for failure in result.failures[:5]
                    ],
                ]
            )
            messagebox.showwarning(
                APP_NAME,
                "\n".join(lines),
                parent=self.window,
            )
        else:
            messagebox.showinfo(
                APP_NAME,
                "\n".join(lines),
                parent=self.window,
            )

    def _copy_failed(self, reason: str) -> None:
        self._restore_buttons()
        self.status_var.set("Ошибка копирования")
        messagebox.showerror(
            APP_NAME,
            f"Не удалось выполнить копирование.\n\nПричина: {reason}",
            parent=self.window,
        )

    def _close(self) -> None:
        if self.running:
            self._stop_copy()
            messagebox.showinfo(
                APP_NAME,
                "Сначала дождитесь остановки текущего файла.",
                parent=self.window,
            )
            return
        self.window.grab_release()
        self.window.destroy()
