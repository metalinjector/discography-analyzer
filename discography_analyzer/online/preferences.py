"""The utility's own settings, next to the program's ``settings.json``.

Kept apart from :class:`AppSettings` so the package stays self-contained. The
Discogs token and the login of a proxy are the user's own and are stored in
this file as they are.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from ..settings import settings_path
from .proxy import MODES, ProxySettings

DEFAULT_FIELDS = ("title", "artist", "album", "year", "genre", "track", "disc")


@dataclass
class OnlinePreferences:
    provider: str = "apple"
    country: str = "US"
    discogs_token: str = ""
    # «Исполнитель альбома» is off: it is empty in many well-tagged albums,
    # and filling it alone would send the whole collection to the service.
    fields: list[str] = field(default_factory=lambda: list(DEFAULT_FIELDS))
    embed_cover: bool = True
    save_cover_file: bool = True
    proxy_mode: str = "system"
    proxy_url: str = ""
    proxy_services: list[str] = field(default_factory=lambda: ["deezer"])
    # "auto": the panel chooses a release when it is sure; "manual": the user
    # always picks from the found variants.
    selection_mode: str = "auto"

    @property
    def auto_select(self) -> bool:
        return self.selection_mode != "manual"

    @property
    def proxy(self) -> ProxySettings:
        mode = self.proxy_mode if self.proxy_mode in MODES else "system"
        return ProxySettings(mode, self.proxy_url, frozenset(self.proxy_services))


def preferences_path() -> Path:
    return settings_path().with_name("online_tags.json")


def load_preferences(path: Path | None = None) -> OnlinePreferences:
    defaults = OnlinePreferences()
    try:
        data = json.loads((path or preferences_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    values = {}
    for item in fields(OnlinePreferences):
        value = data.get(item.name)
        default = getattr(defaults, item.name)
        if isinstance(default, list):
            if isinstance(value, list) and all(isinstance(entry, str) for entry in value):
                values[item.name] = value
        elif type(value) is type(default):
            values[item.name] = value
    return OnlinePreferences(**values)


def save_preferences(preferences: OnlinePreferences, path: Path | None = None) -> None:
    target = path or preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(preferences), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(target)
