from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_EXCLUDED_FOLDERS,
    DEFAULT_REPORT_COLORS,
    DEFAULT_VARIATION_MARKERS,
    SUPPORTED_FORMATS,
)


def settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "DiscographyAnalyzer" / "settings.json"


def _setting_type_matches(default_value: Any, value: Any) -> bool:
    if isinstance(default_value, bool):
        return isinstance(value, bool)
    if isinstance(default_value, str):
        return isinstance(value, str)
    if isinstance(default_value, list):
        return isinstance(value, list)
    if isinstance(default_value, dict):
        return isinstance(value, dict)
    return isinstance(value, type(default_value))


def _clean_string_list(values: list[Any], defaults: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    if values and not result:
        return list(defaults)
    return result


def _valid_report_color(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.lstrip("#")
    return len(normalized) == 6 and all(
        character in "0123456789abcdefABCDEF" for character in normalized
    )


@dataclass
class AppSettings:
    last_folder: str = ""
    remember_folder: bool = True
    autosave: bool = True
    use_tags: bool = True
    detect_variations: bool = True
    check_track_gaps: bool = True
    include_subfolders: bool = True
    folder_tree_mode: bool = False
    dark_theme: bool = True
    formats: dict[str, bool] = field(
        default_factory=lambda: {name: True for name in SUPPORTED_FORMATS}
    )
    variation_markers: list[str] = field(
        default_factory=lambda: list(DEFAULT_VARIATION_MARKERS)
    )
    excluded_folders: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_FOLDERS)
    )
    report_colors: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_REPORT_COLORS)
    )

    @classmethod
    def load(cls, path: Path | None = None) -> "AppSettings":
        target = path or settings_path()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return cls()
            valid: dict[str, Any] = {}
            defaults = cls()
            for key, default_value in asdict(defaults).items():
                if key in data and _setting_type_matches(default_value, data[key]):
                    valid[key] = data[key]
            loaded = cls(**valid)
            loaded.formats = {
                name: (
                    loaded.formats[name]
                    if isinstance(loaded.formats.get(name), bool)
                    else defaults.formats[name]
                )
                for name in SUPPORTED_FORMATS
            }
            loaded.report_colors = {
                status: (
                    loaded.report_colors[status].lstrip("#").upper()
                    if _valid_report_color(loaded.report_colors.get(status))
                    else color
                )
                for status, color in DEFAULT_REPORT_COLORS.items()
            }
            loaded.variation_markers = _clean_string_list(
                loaded.variation_markers,
                list(DEFAULT_VARIATION_MARKERS),
            )
            loaded.excluded_folders = _clean_string_list(
                loaded.excluded_folders,
                list(DEFAULT_EXCLUDED_FOLDERS),
            )
            if not loaded.remember_folder:
                loaded.last_folder = ""
            return loaded
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        target = path or settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        if not self.remember_folder:
            payload["last_folder"] = ""
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(target)
