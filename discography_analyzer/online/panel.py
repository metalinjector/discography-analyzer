"""«Теги и обложки из интернета» — the panel of the «Утилиты» window."""

from __future__ import annotations

import contextlib
import io
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from ..parsing import files_word
from ..utility_panel import WINDOW_TITLE, BackgroundUtilityPanel
from .album import iter_albums
from .apple import STOREFRONTS
from .discogs import TOKEN_HINT
from .http import LookupStopped
from .lookup import (
    PROVIDERS,
    SERVICE_NAMES,
    AlbumLookup,
    LookupCache,
    load_details,
    look_up,
    make_client,
    provider_class,
)
from .preferences import OnlinePreferences, load_preferences, save_preferences
from .proxy import ProxySettings
from .proxy_dialog import ProxyDialog
from .release import AlbumQuery, LookupOptions, Provider
from .tagging import AlbumPlan, FillOptions, apply_plans, missing_fields, plan_album

NO_CHOICE = "— не записывать —"
# Three albums in a row without an answer: the service is down or blocked.
MAX_FAILURES_IN_ROW = 3
THUMBNAIL_SIZE = 56
FIELD_CHOICES = (
    ("title", "Название"),
    ("artist", "Исполнитель"),
    ("album", "Альбом"),
    ("album_artist", "Исполнитель альбома"),
    ("year", "Год"),
    ("genre", "Жанр"),
    ("track", "Номер трека"),
    ("disc", "Номер диска"),
)


def _clock(seconds: float | None) -> str:
    if not seconds:
        return ""
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes}:{rest:02d}"


class OnlineTagsPanel(BackgroundUtilityPanel):
    """Find albums with empty tags online and fill only the empty fields."""

    title = "Теги и обложки из интернета"
    description = (
        "Ищет альбомы с пустыми тегами или без обложки в Apple Music, Deezer, "
        "MusicBrainz или Discogs и заполняет только пустые поля. Сомнительное "
        "совпадение не записывается, пока вы не выберете вариант сами."
    )

    def build(self) -> None:
        self.preferences: OnlinePreferences = load_preferences()
        self.proxy = self.preferences.proxy
        self.proxy_var = tk.StringVar()
        self._make_clients()
        self.cache = LookupCache()
        # Services already reported closed in this country (Deezer /infos).
        self.warned_services: set[str] = set()
        self.lookups: dict[str, AlbumLookup] = {}
        self.manual_queries: dict[Path, AlbumQuery] = {}
        self.current: str | None = None
        self.result_provider = ""
        self.thumbnails: dict[str, ImageTk.PhotoImage | None] = {}
        self.blank_image = tk.PhotoImage(width=THUMBNAIL_SIZE, height=THUMBNAIL_SIZE)

        folder = self.context.selected_folder or self.context.root_folder
        self.root_var = tk.StringVar(value=str(folder) if folder else "")
        self.include_subfolders_var = tk.BooleanVar(value=self.context.include_subfolders)
        self.provider_var = tk.StringVar(value=provider_class(self.preferences.provider).name)
        country = self.preferences.country if self.preferences.country in STOREFRONTS else "US"
        self.country_var = tk.StringVar(value=country)
        self.token_var = tk.StringVar(value=self.preferences.discogs_token)
        self.field_vars = {
            name: tk.BooleanVar(value=name in self.preferences.fields)
            for name, _label in FIELD_CHOICES
        }
        self.embed_cover_var = tk.BooleanVar(value=self.preferences.embed_cover)
        self.cover_file_var = tk.BooleanVar(value=self.preferences.save_cover_file)
        self.backup_enabled_var = tk.BooleanVar(value=self.context.backup_enabled)
        self.backup_path_var = tk.StringVar(value=self._default_backup_path(folder))
        self.query_artist_var = tk.StringVar()
        self.query_title_var = tk.StringVar()
        self.candidate_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value="Нажмите «Найти совпадения»" if folder else "Папка коллекции не выбрана"
        )
        self.summary_var = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0)

        # The window is 760 px high: every frame is kept short so the album
        # list, the only part that grows, keeps several rows.
        self._build_source()
        self._build_results()
        self._build_backup()
        self._build_actions()
        self._show_provider_options()

    # -- layout ----------------------------------------------------------------
    def _build_source(self) -> None:
        source = ttk.LabelFrame(self.frame, text="Источник и папка", padding=(9, 6))
        source.grid(row=0, column=0, sticky="ew")
        source.columnconfigure(1, weight=1)
        self.provider_line = ttk.Frame(source)
        self.provider_line.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.proxy_button = ttk.Button(
            self.provider_line, text="Прокси...", command=self._open_proxy
        )
        self.proxy_button.pack(side="right")
        ttk.Label(self.provider_line, textvariable=self.proxy_var).pack(
            side="right", padx=(0, 8)
        )
        ttk.Label(self.provider_line, text="Сервис").pack(side="left")
        self.provider_box = ttk.Combobox(
            self.provider_line,
            textvariable=self.provider_var,
            values=[provider.name for provider in PROVIDERS],
            state="readonly",
            width=14,
        )
        self.provider_box.pack(side="left", padx=(6, 14))
        self.provider_box.bind("<<ComboboxSelected>>", self._provider_changed)
        self.country_label = ttk.Label(self.provider_line, text="Страна витрины")
        self.country_box = ttk.Combobox(
            self.provider_line,
            textvariable=self.country_var,
            values=STOREFRONTS,
            state="readonly",
            width=5,
        )
        self.country_box.bind("<<ComboboxSelected>>", self._provider_changed)
        self.token_label = ttk.Label(self.provider_line, text="Токен Discogs")
        self.token_entry = ttk.Entry(
            self.provider_line, textvariable=self.token_var, show="•", width=34
        )

        ttk.Label(source, text="Папка").grid(row=1, column=0, padx=(0, 8), pady=(7, 0))
        ttk.Entry(source, textvariable=self.root_var, state="readonly").grid(
            row=1, column=1, sticky="ew", pady=(7, 0)
        )
        ttk.Button(source, text="Выбрать...", command=self._choose_root).grid(
            row=1, column=2, padx=(8, 0), pady=(7, 0)
        )
        ttk.Checkbutton(
            source,
            text="Включать подпапки",
            variable=self.include_subfolders_var,
            command=self._clear_results,
        ).grid(row=1, column=3, padx=(12, 0), pady=(7, 0))

        options = ttk.Frame(source)
        options.grid(row=2, column=0, columnspan=4, sticky="w", pady=(7, 0))
        ttk.Label(options, text="Заполнять пустые:").grid(
            row=0, column=0, rowspan=2, sticky="nw", padx=(0, 10)
        )
        checks = [(label, self.field_vars[name]) for name, label in FIELD_CHOICES]
        checks += [
            ("Обложку в теги", self.embed_cover_var),
            ("Файл обложки", self.cover_file_var),
        ]
        for index, (label, variable) in enumerate(checks):
            ttk.Checkbutton(
                options, text=label, variable=variable, command=self._options_changed
            ).grid(row=index // 5, column=1 + index % 5, sticky="w", padx=(0, 12))

    def _build_results(self) -> None:
        results = ttk.LabelFrame(self.frame, text="Альбомы и файлы", padding=(9, 6))
        results.grid(row=1, column=0, sticky="nsew", pady=(7, 0))
        self.frame.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            results,
            columns=("release", "match", "fill"),
            show="tree headings",
            selectmode="browse",
            height=6,
        )
        for column, heading, width, stretch in (
            ("#0", "Папка / файл", 240, True),
            ("release", "Найдено / трек источника", 250, True),
            ("match", "Совпало", 80, False),
            ("fill", "Будет заполнено", 270, True),
        ):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, minwidth=70, stretch=stretch)
        scroll = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        hscroll = ttk.Scrollbar(results, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=hscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._tree_selection_changed)
        ttk.Label(results, textvariable=self.summary_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        # The album selected above: its query, the release variants, the cover.
        selected = ttk.Frame(results)
        selected.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        selected.columnconfigure(2, weight=1)
        selected.columnconfigure(4, weight=1)
        self.thumbnail_label = ttk.Label(selected, image=self.blank_image)
        self.thumbnail_label.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ttk.Label(selected, text="Исполнитель").grid(row=0, column=1, sticky="w")
        self.artist_entry = ttk.Entry(selected, textvariable=self.query_artist_var)
        self.artist_entry.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        ttk.Label(selected, text="Альбом").grid(row=0, column=3, padx=(10, 6))
        self.album_entry = ttk.Entry(selected, textvariable=self.query_title_var)
        self.album_entry.grid(row=0, column=4, sticky="ew")
        self.search_again_button = ttk.Button(
            selected, text="Искать снова", command=self.search_again, state="disabled"
        )
        self.search_again_button.grid(row=0, column=5, padx=(8, 0), sticky="ew")
        ttk.Label(selected, text="Вариант").grid(row=1, column=1, sticky="w", pady=(6, 0))
        self.candidate_box = ttk.Combobox(
            selected, textvariable=self.candidate_var, state="disabled"
        )
        self.candidate_box.grid(
            row=1, column=2, columnspan=3, sticky="ew", padx=(6, 0), pady=(6, 0)
        )
        self.candidate_box.bind("<<ComboboxSelected>>", self._candidate_changed)
        self.page_button = ttk.Button(
            selected, text="Страница релиза", command=self._open_page, state="disabled"
        )
        self.page_button.grid(row=1, column=5, padx=(8, 0), pady=(6, 0), sticky="ew")

    def _build_backup(self) -> None:
        backup = ttk.Frame(self.frame)
        backup.grid(row=2, column=0, sticky="ew", pady=7)
        backup.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            backup,
            text="Делать резервную копию перед записью",
            variable=self.backup_enabled_var,
            command=self._backup_state_changed,
        ).grid(row=0, column=0, padx=(0, 8))
        self.backup_entry = ttk.Entry(backup, textvariable=self.backup_path_var)
        self.backup_entry.grid(row=0, column=1, sticky="ew")
        self.backup_button = ttk.Button(backup, text="Выбрать...", command=self._choose_backup)
        self.backup_button.grid(row=0, column=2, padx=(8, 0))
        self._backup_state_changed(remember=False)

    def _build_actions(self) -> None:
        holder = ttk.Frame(self.frame)
        holder.grid(row=3, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(
            holder, mode="determinate", maximum=100, variable=self.progress_var
        )
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(holder, textvariable=self.status_var).grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )
        actions = ttk.Frame(self.frame)
        actions.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        self.search_button = ttk.Button(
            actions, text="Найти совпадения", command=self.search
        )
        self.search_button.pack(side="left")
        self.apply_button = ttk.Button(
            actions,
            text="Записать теги",
            command=self.apply,
            style="Accent.TButton",
            state="disabled",
        )
        self.apply_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(
            actions, text="Остановить", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left")

    # -- options -----------------------------------------------------------------
    def _provider_class(self) -> type[Provider]:
        name = self.provider_var.get()
        return next((item for item in PROVIDERS if item.name == name), PROVIDERS[0])

    def _lookup_options(self) -> LookupOptions:
        return LookupOptions(
            country=self.country_var.get(), discogs_token=self.token_var.get().strip()
        )

    def _provider(self, key: str) -> Provider:
        return provider_class(key)(self.client, self._lookup_options())

    def _fill_options(self) -> FillOptions:
        return FillOptions(
            fields=frozenset(name for name, variable in self.field_vars.items() if variable.get()),
            embed_cover=self.embed_cover_var.get(),
            save_cover_file=self.cover_file_var.get(),
        )

    def _show_provider_options(self) -> None:
        key = self._provider_class().key
        for widget in (self.country_label, self.country_box, self.token_label, self.token_entry):
            widget.pack_forget()
        if key == "apple":
            self.country_label.pack(side="left")
            self.country_box.pack(side="left", padx=(6, 0))
        elif key == "discogs":
            self.token_label.pack(side="left")
            self.token_entry.pack(side="left", padx=(6, 0))

    def _provider_changed(self, _event=None) -> None:
        self._show_provider_options()
        if self.lookups:
            # Results of another service or storefront would mix two catalogues.
            self._clear_results()
            self.status_var.set("Сервис изменён — нажмите «Найти совпадения»")

    def _options_changed(self) -> None:
        for row in self.lookups:
            self._refresh_album(row)
        self._refresh_summary()

    def _save_preferences(self) -> None:
        options = self._fill_options()
        self.preferences = OnlinePreferences(
            provider=self._provider_class().key,
            country=self.country_var.get(),
            discogs_token=self.token_var.get().strip(),
            fields=[name for name, _label in FIELD_CHOICES if name in options.fields],
            embed_cover=options.embed_cover,
            save_cover_file=options.save_cover_file,
            proxy_mode=self.proxy.mode,
            proxy_url=self.proxy.url,
            proxy_services=sorted(self.proxy.services),
        )
        # An unwritable settings folder must not stop the utility.
        with contextlib.suppress(OSError):
            save_preferences(self.preferences)

    # -- proxy -------------------------------------------------------------------
    def _make_clients(self) -> None:
        """Clients for the current proxy; an unusable address falls back to the system one."""
        try:
            self.client = make_client(self.stop_event, self.proxy)
        except ValueError:
            self.proxy = ProxySettings()
            self.client = make_client(self.stop_event, self.proxy)
        self.thumbnail_client = make_client(proxy=self.proxy, timeout=10)
        self.proxy_var.set(f"Прокси: {self.proxy.describe(SERVICE_NAMES)}")

    def _open_proxy(self) -> None:
        if not self.busy:
            ProxyDialog(self.frame, self.proxy, self._lookup_options(), self._proxy_saved)

    def _proxy_saved(self, settings: ProxySettings) -> None:
        self.proxy = settings
        self._make_clients()
        # Answers that came another way (or failed) must be asked again.
        self.cache = LookupCache()
        self.thumbnails.clear()
        self.warned_services.clear()
        self._save_preferences()
        if self.lookups:
            self.status_var.set("Прокси изменён — нажмите «Найти совпадения»")

    # -- folders and backup ------------------------------------------------------
    def _root(self) -> Path | None:
        value = self.root_var.get().strip()
        return Path(value) if value else None

    def _collection_of(self, folder: Path | None) -> Path | None:
        """The collection of the main window when ``folder`` lies inside it."""
        collection = self.context.root_folder
        if folder is not None and collection is not None and (
            folder == collection or collection in folder.parents
        ):
            return collection
        return folder

    def _default_backup_path(self, folder: Path | None) -> str:
        # Next to the whole collection, not next to the album: copies inside
        # the collection would turn up as duplicates in the next analysis.
        base = self._collection_of(folder)
        if base is None:
            return ""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(base.parent / f"{base.name}_tags_backup_{stamp}")

    def _choose_root(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.frame,
            title="Папка коллекции",
            initialdir=self.root_var.get() or None,
        )
        if not chosen:
            return
        self.root_var.set(chosen)
        self.backup_path_var.set(self._default_backup_path(Path(chosen)))
        self._clear_results()

    def _choose_backup(self) -> None:
        current = self.backup_path_var.get()
        chosen = filedialog.askdirectory(
            parent=self.frame,
            title="Папка для резервных копий",
            initialdir=str(Path(current).parent) if current else None,
        )
        if chosen:
            self.backup_path_var.set(chosen)

    def _backup_state_changed(self, remember: bool = True) -> None:
        enabled = self.backup_enabled_var.get()
        self.backup_button.configure(state="normal" if enabled else "disabled")
        self.backup_entry.configure(state="readonly" if enabled else "disabled")
        if remember:
            self.context.on_backup_changed(enabled)

    def _backup_root(self, root: Path) -> tuple[bool, Path | None]:
        """(may write, backup folder); warns the user when the folder is unusable."""
        if not self.backup_enabled_var.get():
            return True, None
        raw = self.backup_path_var.get().strip()
        if not raw:
            messagebox.showwarning(
                WINDOW_TITLE,
                "Укажите папку для резервной копии или отключите её",
                parent=self.frame,
            )
            return False, None
        backup_root = Path(raw)
        collection = self._collection_of(root) or root
        try:
            backup_root.resolve().relative_to(collection.resolve())
        except ValueError:
            return True, backup_root
        messagebox.showwarning(
            WINDOW_TITLE,
            "Папка резервной копии не должна находиться внутри обрабатываемой коллекции.",
            parent=self.frame,
        )
        return False, None

    # -- results -----------------------------------------------------------------
    def _clear_results(self) -> None:
        self.lookups.clear()
        self.current = None
        self.tree.delete(*self.tree.get_children())
        self.summary_var.set("")
        self._show_selected()
        self._refresh_apply_button()

    def _plan(self, lookup: AlbumLookup) -> AlbumPlan | None:
        choice = lookup.choice
        if choice is None or not choice.release.detailed:
            return None
        return plan_album(lookup.album, choice.release, choice.matches, self._fill_options())

    def _writable_plans(self) -> list[AlbumPlan]:
        plans = (self._plan(lookup) for lookup in self.lookups.values())
        return [plan for plan in plans if plan is not None and not plan.empty]

    def _album_values(self, lookup: AlbumLookup) -> tuple[str, str, str]:
        choice = lookup.choice
        if lookup.error:
            release = f"ошибка: {lookup.error}"
        elif choice is not None:
            release = choice.release.label()
        elif lookup.candidates:
            release = f"выберите вариант ({len(lookup.candidates)})"
        else:
            release = "не найдено — уточните запрос"
        matched = (
            f"{choice.matched} из {len(lookup.album.tracks)}"
            if choice is not None and choice.release.detailed
            else ""
        )
        plan = self._plan(lookup)
        if plan is not None:
            fill = ", ".join(plan.fields) or "нечего заполнять"
        else:
            fill = "пусто: " + ", ".join(missing_fields(lookup.album, self._fill_options()))
        return release, matched, fill

    def _refresh_album(self, row: str) -> None:
        lookup = self.lookups[row]
        self.tree.item(row, values=self._album_values(lookup))
        self.tree.delete(*self.tree.get_children(row))
        choice = lookup.choice
        sources = {match.track.path: match.source for match in choice.matches} if choice else {}
        plan = self._plan(lookup)
        changes = {change.track.path: change for change in plan.changes} if plan else {}
        several_discs = choice is not None and choice.release.disc_total > 1
        for track in lookup.album.tracks:
            source = sources.get(track.path)
            if source is not None:
                position = f"{source.disc}-{source.number}" if several_discs else str(source.number)
                duration = _clock(source.duration)
                source_text = f"{position}. {source.title}" + (f" ({duration})" if duration else "")
            else:
                source_text = "—" if choice is None else "не сопоставлен"
            change = changes.get(track.path)
            self.tree.insert(
                row,
                "end",
                text=track.filename,
                values=(source_text, "", change.describe() if change else "—"),
            )
        if row == self.current:
            self._show_selected()

    def _refresh_summary(self) -> None:
        plans = self._writable_plans()
        undecided = sum(1 for lookup in self.lookups.values() if lookup.choice is None)
        files = sum(len(plan.changes) for plan in plans)
        details = [f"Альбомов с пустыми тегами: {len(self.lookups)}"]
        details.append(f"к записи: {len(plans)} ({files} {files_word(files)})")
        if undecided:
            details.append(f"без выбранного варианта: {undecided}")
        self.summary_var.set("; ".join(details))
        self._refresh_apply_button()

    def _refresh_apply_button(self) -> None:
        writable = not self.busy and bool(self._writable_plans())
        self.apply_button.configure(state="normal" if writable else "disabled")

    def _add_album(self, lookup: AlbumLookup) -> None:
        # The summary is counted once the search ends: per album it would
        # re-plan every album found so far.
        row = f"album-{len(self.lookups)}"
        self.lookups[row] = lookup
        self.tree.insert("", "end", iid=row, text=lookup.album.relative_folder)
        self._refresh_album(row)

    # -- selected album ------------------------------------------------------------
    def _tree_selection_changed(self, _event=None) -> None:
        focused = self.tree.focus()
        if not focused or not self.tree.exists(focused):
            return
        row = focused if focused in self.lookups else self.tree.parent(focused)
        if row not in self.lookups or row == self.current:
            return
        self.current = row
        lookup = self.lookups[row]
        self.query_artist_var.set(lookup.query.artist)
        self.query_title_var.set(lookup.query.title)
        self._show_selected()

    def _show_selected(self) -> None:
        lookup = self.lookups.get(self.current) if self.current else None
        if lookup is None:
            self.candidate_box.configure(values=(), state="disabled")
            self.candidate_var.set("")
            self.search_again_button.configure(state="disabled")
            self.page_button.configure(state="disabled")
            self.thumbnail_label.configure(image=self.blank_image)
            return
        labels = [NO_CHOICE]
        for candidate in lookup.candidates:
            label = candidate.release.label()
            if candidate.release.detailed:
                label += f" — совпало {candidate.matched} из {len(lookup.album.tracks)}"
            labels.append(label)
        self.candidate_box.configure(
            values=labels, state="disabled" if self.busy else "readonly"
        )
        self.candidate_box.current(0 if lookup.chosen is None else lookup.chosen + 1)
        self.search_again_button.configure(state="disabled" if self.busy else "normal")
        choice = lookup.choice
        page = choice.release.page_url if choice is not None else ""
        self.page_button.configure(state="normal" if page and not self.busy else "disabled")
        self._show_thumbnail(choice.release.thumbnail_url if choice is not None else "")

    def _show_thumbnail(self, url: str) -> None:
        if not url:
            self.thumbnail_label.configure(image=self.blank_image)
            return
        if url in self.thumbnails:
            self.thumbnail_label.configure(image=self.thumbnails[url] or self.blank_image)
            return
        self.thumbnails[url] = None  # requested; stays None if it fails
        self.thumbnail_label.configure(image=self.blank_image)

        def fetch() -> None:
            try:
                data = self.thumbnail_client.get_bytes(url)
            except Exception:
                data = b""
            self.post("thumbnail", url, data)

        threading.Thread(target=fetch, daemon=True).start()

    def _thumbnail_loaded(self, url: str, data: bytes) -> None:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
                self.thumbnails[url] = ImageTk.PhotoImage(image.convert("RGB"))
        except Exception:
            return
        lookup = self.lookups.get(self.current) if self.current else None
        choice = lookup.choice if lookup is not None else None
        if choice is not None and choice.release.thumbnail_url == url:
            self.thumbnail_label.configure(image=self.thumbnails[url])

    def _candidate_changed(self, _event=None) -> None:
        row = self.current
        lookup = self.lookups.get(row) if row else None
        if lookup is None or self.busy:
            return
        index = self.candidate_box.current()
        if index <= 0:
            lookup.chosen = None
            self._refresh_album(row)
            self._refresh_summary()
            return
        lookup.chosen = index - 1
        candidate = lookup.candidates[lookup.chosen]
        if candidate.release.detailed:
            self._refresh_album(row)
            self._refresh_summary()
            return
        provider = self._provider(candidate.release.provider)

        def run() -> None:
            try:
                load_details(provider, candidate, lookup.album, self.cache)
            except LookupStopped:
                self.post("stopped")
                return
            except Exception as exc:
                self.post("details_failed", row, str(exc))
                return
            self.post("details", row)

        self._start("Загрузка трек-листа...")
        self.run_in_background(run)

    def search_again(self) -> None:
        row = self.current
        lookup = self.lookups.get(row) if row else None
        if lookup is None or self.busy:
            return
        query = AlbumQuery(self.query_artist_var.get().strip(), self.query_title_var.get().strip())
        if query.empty:
            messagebox.showwarning(
                WINDOW_TITLE, "Введите исполнителя или название альбома", parent=self.frame
            )
            return
        provider = self._provider(self.result_provider or self._provider_class().key)
        # Remembered for the next «Найти совпадения» (the one after a write too).
        self.manual_queries[lookup.album.folder] = query

        def run() -> None:
            try:
                result = look_up(provider, lookup.album, query, cache=self.cache)
            except LookupStopped:
                self.post("stopped")
                return
            except Exception as exc:
                result = AlbumLookup(album=lookup.album, query=query, error=str(exc))
            self.post("relookup", row, result)

        self._start(f"Поиск в {provider.name}...")
        self.run_in_background(run)

    def _open_page(self) -> None:
        lookup = self.lookups.get(self.current) if self.current else None
        choice = lookup.choice if lookup is not None else None
        if choice is not None and choice.release.page_url.startswith("https://"):
            webbrowser.open(choice.release.page_url)

    # -- search ------------------------------------------------------------------
    def search(self) -> None:
        if self.busy:
            return
        root = self._root()
        if root is None or not root.is_dir():
            messagebox.showwarning(
                WINDOW_TITLE, "Выберите существующую папку коллекции", parent=self.frame
            )
            return
        provider_type = self._provider_class()
        options = self._lookup_options()
        if provider_type.key == "discogs" and not options.discogs_token:
            messagebox.showwarning(WINDOW_TITLE, TOKEN_HINT, parent=self.frame)
            return
        fill = self._fill_options()
        if not fill.fields and not fill.embed_cover and not fill.save_cover_file:
            messagebox.showwarning(
                WINDOW_TITLE, "Отметьте хотя бы одно поле для заполнения", parent=self.frame
            )
            return
        self._save_preferences()
        self._clear_results()
        self.result_provider = provider_type.key
        provider = provider_type(self.client, options)
        include_subfolders = self.include_subfolders_var.get()
        excluded = self.context.excluded_folders
        extensions = self.context.extensions
        queries = dict(self.manual_queries)
        check_service = provider.key == "deezer" and provider.key not in self.warned_services

        def run() -> None:
            try:
                if check_service:
                    self._warn_if_closed(provider)
                albums = complete = failures = 0
                for album in iter_albums(
                    root,
                    extensions=extensions,
                    include_subfolders=include_subfolders,
                    excluded_folders=excluded,
                    stop_event=self.stop_event,
                    progress=lambda index, label: self.post("scan", index, label),
                ):
                    albums += 1
                    if not missing_fields(album, fill):
                        complete += 1
                        continue
                    self.post("searching", album.relative_folder)
                    query = queries.get(album.folder) or AlbumQuery(
                        album.guess.artist, album.guess.title
                    )
                    try:
                        lookup = look_up(provider, album, query, cache=self.cache)
                        failures = 0
                    except LookupStopped:
                        raise
                    except Exception as exc:
                        lookup = AlbumLookup(album=album, query=query, error=str(exc))
                        failures += 1
                    self.post("album", lookup)
                    if failures >= MAX_FAILURES_IN_ROW:
                        self.post("search_failed", lookup.error)
                        return
                self.post("search_done", albums, complete)
            except LookupStopped:
                self.post("stopped")
            except Exception as exc:
                self.post("task_error", str(exc))

        self._start(f"Поиск в {provider.name}...")
        self.run_in_background(run)

    # -- write -------------------------------------------------------------------
    def apply(self) -> None:
        if self.busy:
            return
        plans = self._writable_plans()
        root = self._root()
        if not plans or root is None or not root.is_dir():
            return
        may_write, backup_root = self._backup_root(root)
        if not may_write:
            return
        files = sum(len(plan.changes) for plan in plans)
        covers = sum(1 for plan in plans if plan.save_cover_file)
        lines = [
            f"Заполнить пустые теги? Файлов: {files}, папок: {len(plans)}.",
            "",
            "Существующие значения не меняются, аудио не перекодируется.",
        ]
        if covers:
            lines.append(f"Новых файлов обложки: {covers}.")
        lines.append(
            "Резервные копии будут созданы."
            if backup_root is not None
            else "Резервные копии отключены."
        )
        if not messagebox.askyesno(WINDOW_TITLE, "\n".join(lines), parent=self.frame):
            return

        def progress(done: int, total: int, label: str) -> None:
            self.post("write_progress", done, total, label)

        # Backups mirror the paths inside the whole collection.
        backup_base = self._collection_of(root) or root

        def run() -> None:
            try:
                result = apply_plans(
                    plans,
                    client=self.client,
                    root=backup_base,
                    backup_root=backup_root,
                    stop_event=self.stop_event,
                    progress=progress,
                )
            except Exception as exc:
                self.post("task_error", str(exc))
                return
            self.post("write_done", result)

        self._start("Запись тегов...", determinate=True)
        self.run_in_background(run)

    def _write_finished(self, result) -> None:
        details = [
            f"Изменено файлов: {result.updated_files}, папок: {result.albums}.",
            f"Сохранено файлов обложки: {result.covers_saved}.",
            f"Создано резервных копий: {result.backup_files}.",
        ]
        if result.failures:
            details.append(f"Ошибок: {len(result.failures)}.")
            details.extend(
                f"• {failure.path.name}: {failure.reason}" for failure in result.failures[:8]
            )
        if result.stopped:
            details.append("Запись была остановлена до конца списка.")
        messagebox.showinfo(WINDOW_TITLE, "\n".join(details), parent=self.frame)
        root = self._root()
        if (result.updated_files or result.covers_saved) and root is not None:
            self.context.on_completed(root)
            # The same check again: the network answers come from the cache.
            self.search()

    # -- background work ---------------------------------------------------------
    def _start(self, status: str, determinate: bool = False) -> None:
        self.status_var.set(status)
        self.progress_var.set(0)
        if determinate:
            self.progress.configure(mode="determinate")
        else:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.search_button.configure(state=state)
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.provider_box.configure(state="disabled" if busy else "readonly")
        self.country_box.configure(state="disabled" if busy else "readonly")
        if not busy:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress_var.set(0)
        self._show_selected()
        self._refresh_apply_button()

    def stop(self) -> None:
        if self.busy:
            super().stop()
            self.stop_button.configure(state="disabled")
            self.status_var.set("Остановка...")

    def handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "scan":
            self.status_var.set(f"Чтение папок: {event[1]} — …{event[2][-70:]}")
        elif kind == "searching":
            name = provider_class(self.result_provider).name
            self.status_var.set(f"Поиск в {name}: {event[1][-80:]}")
        elif kind == "album":
            self._add_album(event[1])
        elif kind == "search_done":
            self.finish_background()
            _kind, albums, complete = event
            self._refresh_summary()
            if self.lookups:
                self.status_var.set(
                    "Проверьте варианты и нажмите «Записать теги». "
                    f"Заполненных альбомов пропущено: {complete} из {albums}."
                )
            else:
                self.status_var.set(
                    f"Заполнять нечего: у всех альбомов ({albums}) теги и обложка на месте"
                    if albums
                    else "В папке нет аудиофайлов"
                )
        elif kind == "search_failed":
            self.finish_background()
            self._refresh_summary()
            self.status_var.set("Сервис не отвечает")
            messagebox.showerror(
                WINDOW_TITLE,
                "Поиск прерван: сервис не ответил три раза подряд.\n\n"
                f"Причина: {event[1]}",
                parent=self.frame,
            )
        elif kind == "relookup":
            self.finish_background()
            _kind, row, lookup = event
            if row in self.lookups:
                self.lookups[row] = lookup
                self._refresh_album(row)
            self._refresh_summary()
            self.status_var.set(lookup.error or "Готово")
        elif kind == "details":
            self.finish_background()
            if event[1] in self.lookups:
                self._refresh_album(event[1])
            self._refresh_summary()
            self.status_var.set("Готово")
        elif kind == "details_failed":
            self.finish_background()
            lookup = self.lookups.get(event[1])
            if lookup is not None:
                lookup.chosen = None
                self._refresh_album(event[1])
            self.status_var.set("Не удалось загрузить трек-лист")
            messagebox.showerror(WINDOW_TITLE, f"Причина: {event[2]}", parent=self.frame)
        elif kind == "stopped":
            self.finish_background()
            self._refresh_summary()
            self.status_var.set("Остановлено")
        elif kind == "task_error":
            self.finish_background()
            self._refresh_summary()
            self.status_var.set("Ошибка")
            messagebox.showerror(WINDOW_TITLE, f"Причина: {event[1]}", parent=self.frame)
        elif kind == "write_progress":
            _kind, done, total, label = event
            self.progress_var.set(round(done / total * 100) if total else 0)
            self.status_var.set(f"{done} из {total}: …{label[-70:]}")
        elif kind == "write_done":
            self.finish_background()
            self.status_var.set("Готово" if not event[1].stopped else "Остановлено")
            self._write_finished(event[1])
        elif kind == "thumbnail":
            self._thumbnail_loaded(event[1], event[2])
        elif kind == "service_closed":
            _kind, key, text = event
            self.warned_services.add(key)
            messagebox.showwarning(
                WINDOW_TITLE,
                f"{text}.\n\nПоиск продолжается, но ответы могут быть пустыми. "
                "Прокси задаётся кнопкой «Прокси...».",
                parent=self.frame,
            )

    def _warn_if_closed(self, provider: Provider) -> None:
        """Worker: report once if the service says it is closed in this country."""
        try:
            status = provider.check()
        except LookupStopped:
            raise
        except Exception:
            return  # no answer at all: the search itself will show the error
        if not status.available:
            self.post("service_closed", provider.key, status.text)

    def close(self) -> None:
        self._save_preferences()
        super().close()
