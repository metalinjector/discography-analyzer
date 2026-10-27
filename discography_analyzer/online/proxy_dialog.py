"""«Прокси для онлайн-сервисов» — the window of the proxy settings and a check."""

from __future__ import annotations

import contextlib
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from ..constants import APP_NAME
from .lookup import PROVIDERS, SERVICE_HOSTS, make_client
from .proxy import ProxySettings, ProxyTransport, parse_proxy_url
from .release import LookupOptions

TITLE = "Прокси для онлайн-сервисов"
MODE_CHOICES = (
    ("system", "Системный — как в настройках Windows или в HTTPS_PROXY"),
    ("direct", "Без прокси — напрямую"),
    ("manual", "Свой прокси для отмеченных сервисов, остальные — по системным настройкам"),
)
ROUTE_LABELS = {
    "own": "через свой прокси",
    "direct": "без прокси",
    "system": "по системным настройкам",
}


class ProxyDialog:
    """Choose the proxy, check a service through it, save or cancel."""

    def __init__(
        self,
        parent: tk.Misc,
        settings: ProxySettings,
        options: LookupOptions,
        on_saved: Callable[[ProxySettings], None],
    ) -> None:
        self.options = options
        self.on_saved = on_saved
        self.events: queue.Queue[tuple] = queue.Queue()
        self._poll_job: str | None = None

        owner = parent.winfo_toplevel()
        self.window = tk.Toplevel(owner)
        self.window.title(f"{APP_NAME} — {TITLE}")
        self.window.configure(bg=owner.cget("bg"))
        self.window.transient(owner)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self.window, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.mode_var = tk.StringVar(value=settings.mode)
        for row, (mode, label) in enumerate(MODE_CHOICES):
            ttk.Radiobutton(
                frame,
                text=label,
                value=mode,
                variable=self.mode_var,
                command=self._mode_changed,
            ).grid(row=row, column=0, sticky="w", pady=1)

        own = ttk.Frame(frame)
        own.grid(row=3, column=0, sticky="ew", padx=(24, 0), pady=(4, 0))
        own.columnconfigure(1, weight=1)
        ttk.Label(own, text="Адрес").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.url_var = tk.StringVar(value=settings.url)
        self.url_entry = ttk.Entry(own, textvariable=self.url_var, width=46)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(
            own,
            text="http://127.0.0.1:8080 · socks5://127.0.0.1:1080 · логин:пароль@хост:порт",
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))
        ttk.Label(own, text="Сервисы").grid(row=2, column=0, sticky="nw", padx=(0, 8), pady=(6, 0))
        services = ttk.Frame(own)
        services.grid(row=2, column=1, sticky="w", pady=(6, 0))
        self.service_vars = {
            provider.key: tk.BooleanVar(value=provider.key in settings.services)
            for provider in PROVIDERS
        }
        self.service_checks = [
            ttk.Checkbutton(services, text=provider.name, variable=self.service_vars[provider.key])
            for provider in PROVIDERS
        ]
        for column, check in enumerate(self.service_checks):
            check.grid(row=0, column=column, sticky="w", padx=(0, 12))

        test = ttk.LabelFrame(frame, text="Проверка", padding=9)
        test.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        test.columnconfigure(2, weight=1)
        self.test_service_var = tk.StringVar(value="Deezer")
        ttk.Combobox(
            test,
            textvariable=self.test_service_var,
            values=[provider.name for provider in PROVIDERS],
            state="readonly",
            width=14,
        ).grid(row=0, column=0, sticky="w")
        self.check_button = ttk.Button(test, text="Проверить", command=self.check)
        self.check_button.grid(row=0, column=1, padx=(8, 0))
        self.result_var = tk.StringVar(value="Запрос к выбранному сервису с этими настройками")
        ttk.Label(test, textvariable=self.result_var, wraplength=520, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        actions = ttk.Frame(frame)
        actions.grid(row=5, column=0, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Сохранить", command=self.save, style="Accent.TButton").pack(
            side="left"
        )
        ttk.Button(actions, text="Отмена", command=self.close).pack(side="left", padx=(6, 0))

        self._mode_changed()
        self.window.grab_set()

    def _mode_changed(self) -> None:
        state = "normal" if self.mode_var.get() == "manual" else "disabled"
        self.url_entry.configure(state=state)
        for check in self.service_checks:
            check.configure(state=state)

    def _settings(self) -> ProxySettings | None:
        """The settings in the window; None after a warning if they are unusable."""
        settings = ProxySettings(
            mode=self.mode_var.get(),
            url=self.url_var.get().strip(),
            services=frozenset(key for key, variable in self.service_vars.items() if variable.get()),
        )
        if settings.mode != "manual":
            return settings
        try:
            parse_proxy_url(settings.url)
        except ValueError as exc:
            messagebox.showwarning(TITLE, str(exc), parent=self.window)
            return None
        if not settings.services:
            messagebox.showwarning(
                TITLE, "Отметьте сервисы, которым нужен свой прокси", parent=self.window
            )
            return None
        return settings

    def check(self) -> None:
        settings = self._settings()
        if settings is None:
            return
        provider_type = next(
            (provider for provider in PROVIDERS if provider.name == self.test_service_var.get()),
            PROVIDERS[0],
        )
        route = ROUTE_LABELS[ProxyTransport(settings, SERVICE_HOSTS).route(provider_type.status_url)]
        self.check_button.configure(state="disabled")
        self.result_var.set(f"{provider_type.name}, {route}: проверка…")

        def run() -> None:
            try:
                provider = provider_type(make_client(proxy=settings, timeout=15), self.options)
                status = provider.check()
                self.events.put(("checked", provider_type.name, route, status.available, status.text))
            except Exception as exc:
                self.events.put(("checked", provider_type.name, route, False, str(exc)))

        threading.Thread(target=run, daemon=True).start()
        self._poll()

    def _poll(self) -> None:
        try:
            _kind, name, route, available, text = self.events.get_nowait()
        except queue.Empty:
            self._poll_job = self.window.after(100, self._poll)
            return
        self._poll_job = None
        self.check_button.configure(state="normal")
        mark = "✓" if available else "✗"
        self.result_var.set(f"{mark} {name}, {route}: {text}")

    def save(self) -> None:
        settings = self._settings()
        if settings is None:
            return
        self.on_saved(settings)
        self.close()

    def close(self) -> None:
        # A running check ends on its own: its answer is simply not shown.
        if self._poll_job is not None:
            with contextlib.suppress(tk.TclError):
                self.window.after_cancel(self._poll_job)
            self._poll_job = None
        with contextlib.suppress(tk.TclError):
            self.window.grab_release()
        self.window.destroy()
