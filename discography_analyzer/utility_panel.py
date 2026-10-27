"""Base classes of the «Утилиты» window panels.

They live apart from :mod:`utilities_dialog` so a utility can sit in its own
module or package and still be listed in ``UTILITY_PANELS`` without an
import cycle.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

WINDOW_TITLE = "Утилиты"


@dataclass(frozen=True, slots=True)
class UtilityContext:
    """Everything a utility panel needs to know about the main window."""

    root_folder: Path | None
    include_subfolders: bool
    excluded_folders: tuple[str, ...]
    extensions: frozenset[str]
    backup_enabled: bool
    on_backup_changed: Callable[[bool], None]
    on_completed: Callable[[Path], None]
    # The folder row (or the folder of the track) selected in the main window.
    selected_folder: Path | None = None


class UtilityPanel:
    """Base class of one utility: title, short description and its widgets."""

    title = ""
    description = ""

    def __init__(self, parent: tk.Misc, context: UtilityContext) -> None:
        self.context = context
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.build()

    def build(self) -> None:
        raise NotImplementedError

    def can_close(self) -> bool:
        return True

    def close(self) -> None:
        """Release resources (background polling, worker threads)."""


class BackgroundUtilityPanel(UtilityPanel):
    """A panel whose long tasks run in a worker thread.

    The worker never touches widgets: it calls :meth:`post`, and the panel
    handles each event on the Tk thread in :meth:`handle_event`.
    """

    def __init__(self, parent: tk.Misc, context: UtilityContext) -> None:
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.busy = False
        self._poll_job: str | None = None
        super().__init__(parent, context)
        self._schedule_poll()

    def handle_event(self, event: tuple) -> None:
        raise NotImplementedError

    def set_busy(self, busy: bool) -> None:
        """Enable or disable the panel's own buttons."""

    def run_in_background(self, task: Callable[[], None]) -> None:
        self.busy = True
        self.stop_event.clear()
        self.set_busy(True)
        self.worker = threading.Thread(target=task, daemon=True)
        self.worker.start()

    def finish_background(self) -> None:
        self.busy = False
        self.worker = None
        self.set_busy(False)

    def post(self, *event) -> None:
        self.events.put(event)

    def stop(self) -> None:
        if self.busy and self.worker is not None and self.worker.is_alive():
            self.stop_event.set()

    def _schedule_poll(self) -> None:
        self._poll_job = self.frame.after(100, self._poll_events)

    def _poll_events(self) -> None:
        if not self.frame.winfo_exists():
            return
        try:
            while True:
                self.handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        finally:
            # A failing handler must not stop the polling: the worker's
            # final event would never arrive and the panel would stay busy.
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
