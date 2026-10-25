# Discography Analyzer 1.7.0 — код проекта

Полное древо проекта с чистым исходным кодом и пояснением к каждому файлу-узлу. Версия 1.7.0, коммит `513b087`, Python ≥3.10, зависимости: mutagen, openpyxl, Pillow. GUI — чистый tkinter/ttk, без внешних GUI-фреймворков.

Кода: **26 файлов, 6652 строк**.

## Древо проекта

```
Discography_Analyzer_Python (GPT 5.6 Sol)/
├── app.py — точка входа (4 стр.)
├── discography_analyzer/
│   ├── __init__.py — версия пакета (3 стр.)
│   ├── __main__.py — python -m запуск (6 стр.)
│   ├── audit_dialog.py — диалог исправлений аудита (408 стр.)
│   ├── audit_models.py — модели ишьюсов аудита (100 стр.)
│   ├── classifier.py — правила дублей/вариаций/конфликтов (228 стр.)
│   ├── completeness.py — пропуски треков в альбомах (102 стр.)
│   ├── constants.py — константы, форматы, маркеры (130 стр.)
│   ├── copy_dialog.py — диалог копирования (428 стр.)
│   ├── copying.py — план и исполнение копирования (349 стр.)
│   ├── exporter.py — экспорт XLSX (5 листов) (559 стр.)
│   ├── metadata.py — чтение тегов и обложек (mutagen) (340 стр.)
│   ├── metadata_audit.py — правила аудита тегов (513 стр.)
│   ├── metadata_writer.py — безопасные правки тегов (205 стр.)
│   ├── models.py — доменные модели (Track и др.) (226 стр.)
│   ├── parsing.py — парсинг имён файлов (96 стр.)
│   ├── scanner.py — сбор файлов, пайплайн анализа (176 стр.)
│   ├── settings.py — загрузка/сохранение настроек (142 стр.)
│   └── ui.py — главное окно GUI (tkinter) (2487 стр.)
├── .github/workflows/tests.yml — CI (ruff + unittest) (25 стр.)
├── pyproject.toml — метаданные пакета, ruff-конфиг (38 стр.)
├── requirements.txt — зависимости (3 стр.)
├── build_exe.spec — PyInstaller one-file сборка (48 стр.)
├── run.bat — лаунчер Windows (3 стр.)
├── run.sh — лаунчер Unix (2 стр.)
├── .gitignore — исключения git (31 стр.)
├── README.md — описание проекта и правил — документация
├── AUDIT.md — полный отчёт глобального аудита (методика, 19 находок, предложения)
└── CHANGELOG.md — журнал изменений

Не включены: `tests/` (11 файлов, 71 тест), `.venv/`, `build/`, `dist/`, `tools/`, `__pycache__/` — тесты и артефакты сборки.
```

---

## Файлы с пояснениями и кодом

### `app.py`

Точка входа для прямого запуска (`python app.py`). Просто импортирует и вызывает `discography_analyzer.ui:main()` — вся логика живёт в пакете.

```python
from discography_analyzer.ui import main

if __name__ == "__main__":
    main()

```

### `discography_analyzer/__init__.py`

Пакет `discography_analyzer`. Единственное содержимое — `__version__` (дублируется в `pyproject.toml`; аудит отмечал это как пункт гигиены 4.8).

```python
"""Discography Analyzer."""

__version__ = "1.7.0"

```

### `discography_analyzer/__main__.py`

Запуск пакета как модуля: `python -m discography_analyzer`. Добавлен аудитом для второго стандартного способа запуска рядом с `app.py`.

```python
"""Allow ``python -m discography_analyzer`` alongside ``app.py``."""

from .ui import main

if __name__ == "__main__":
    main()

```

### `discography_analyzer/constants.py`

Константы приложения: `APP_NAME`, поддерживаемые форматы (MP3/FLAC/M4A/APE → расширения), маркеры вариаций по умолчанию (Live/Remix/Acoustic/…), дефолтные исключённые папки, цвета статусов для отчёта и пр. Единое место всех «магических строк».

```python
from __future__ import annotations

from collections import OrderedDict

APP_NAME = "Discography Analyzer"
SUPPORTED_FORMATS = OrderedDict(
    (
        ("MP3", ".mp3"),
        ("FLAC", ".flac"),
        ("M4A", ".m4a"),
        ("APE", ".ape"),
    )
)

DEFAULT_VARIATION_MARKERS = [
    "Remix",
    "Mix",
    "Edit",
    "Live",
    "Acoustic",
    "Version",
    "Instrumental",
    "Extended",
    "Radio",
    "Club",
    "Remastered",
    "Demo",
    "Bonus",
    "Alternative",
    "Unplugged",
    "Stripped",
    "Session",
    "Reprise",
    "Interlude",
    "Intro",
    "Outro",
    "Dub",
    "VIP",
    "Bootleg",
    "Rework",
    "Reimagined",
    "Cover",
    "Karaoke",
    "Clean",
    "Explicit",
    "Deluxe",
    "Original",
    "Single",
]

DEFAULT_EXCLUDED_FOLDERS = ["__MACOSX", ".thumbnails", ".DS_Store"]

REPORT_COLOR_CHOICES = OrderedDict(
    (
        ("Тёплый оранжевый", "FCE6D3"),
        ("Светло-зелёный", "E5F3E8"),
        ("Светло-голубой", "E2EFFB"),
        ("Мягкий коралловый", "F8DFDA"),
        ("Металлический серый", "E3E5E7"),
        ("Тёплый белый", "FFFDF9"),
        ("Графитовый", "D2D5D8"),
    )
)

DEFAULT_REPORT_COLORS = {
    "Уникальный": "E5F3E8",
    "Дубликат": "FCE6D3",
    "Вариация": "E2EFFB",
    "Конфликт": "F8DFDA",
}

STATUS_ROW_COLORS_LIGHT = {
    "Уникальный": "#e5f3e8",
    "Дубликат": "#fce6d3",
    "Вариация": "#e2effb",
    "Конфликт": "#f8dfda",
}

STATUS_ROW_COLORS_DARK = {
    "Уникальный": "#254231",
    "Дубликат": "#56371f",
    "Вариация": "#263f55",
    "Конфликт": "#53312f",
}

TABLE_COLUMNS = [
    ("status", "Статус", 125),
    ("base_title", "Базовое имя", 220),
    ("variation", "Вариация", 130),
    ("relation", "Связь с файлами", 300),
    ("collection_warning", "Проверка комплекта", 260),
    ("relative_folder", "Папка", 180),
    ("title", "Title", 200),
    ("artist", "Artist", 180),
    ("album", "Album", 180),
    ("year", "Year", 70),
    ("genre", "Genre", 120),
    ("duration", "Duration", 90),
    ("bitrate", "Bitrate", 90),
    ("format", "Format", 75),
    ("size_mb", "Size MB", 90),
]

EXPORT_COLUMNS = OrderedDict(
    (
        ("base_title", ("Базовое имя", True)),
        ("status", ("Статус", True)),
        ("variation", ("Вариация", True)),
        ("relation", ("Связь с файлами", True)),
        ("collection_warning", ("Проверка комплекта", True)),
        ("relative_folder", ("Папка", True)),
        ("filename", ("Имя файла", True)),
        ("title", ("Title", True)),
        ("artist", ("Artist", True)),
        ("album", ("Album", True)),
        ("year", ("Year", True)),
        ("genre", ("Genre", True)),
        ("duration", ("Duration", True)),
        ("bitrate", ("Bitrate", True)),
        ("sample_rate", ("Sample Rate", False)),
        ("bit_depth", ("Bit Depth", False)),
        ("format", ("Format", True)),
        ("size_mb", ("File Size (MB)", True)),
        ("track_number", ("Track #", False)),
        ("disc_number", ("Disc #", False)),
        ("album_artist", ("Album Artist", False)),
        ("comment", ("Comment", False)),
        ("path", ("Полный путь", False)),
    )
)

```

### `discography_analyzer/models.py`

Доменные модели: `TrackStatus` (Уникальный/Дубликат/Вариация/Конфликт), `Track` — центральный dataclass (~50 полей: пути, теги, техпараметры аудио, обложка, результаты классификации), `AlbumCompletenessIssue` (пропуск трека в альбоме), `AnalysisResult` (итог анализа: треки, ишьюсы комплектности и аудита, счётчики).

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .audit_models import AuditSeverity, MetadataAuditIssue


class TrackStatus(str, Enum):
    UNIQUE = "Уникальный"
    DUPLICATE = "Дубликат"
    VARIATION = "Вариация"
    CONFLICT = "Конфликт"

    @property
    def decorated(self) -> str:
        return {
            TrackStatus.UNIQUE: "● Уникальный",
            TrackStatus.DUPLICATE: "● Дубликат",
            TrackStatus.VARIATION: "● Вариация",
            TrackStatus.CONFLICT: "● Конфликт",
        }[self]


@dataclass(slots=True)
class Track:
    id: str
    path: Path
    root: Path
    filename: str
    relative_path: str
    relative_folder: str
    format: str
    size_bytes: int
    modified_at: str = ""
    created_at: str = ""
    filename_title: str = ""
    comparison_title: str = ""
    base_title: str = ""
    variation: str = ""
    potential_base: str = ""
    potential_variation: str = ""
    source_track_id: str | None = None
    relation: str = ""
    related_track_ids: list[str] = field(default_factory=list)
    duplicate_group_id: str = ""
    collection_warning: str = ""
    collection_issue_id: str = ""
    status: TrackStatus = TrackStatus.UNIQUE
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: str = ""
    disc_number: str = ""
    year: str = ""
    genre: str = ""
    comment: str = ""
    duration_seconds: int | None = None
    duration_exact: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    channel_mode: str = ""
    bitrate_mode: str = ""
    codec: str = ""
    encoder: str = ""
    encoder_settings: str = ""
    version: str = ""
    layer: str = ""
    protection: str = ""
    track_gain: str = ""
    track_peak: str = ""
    album_gain: str = ""
    album_peak: str = ""
    all_tags: dict[str, list[str]] = field(default_factory=dict)
    canonical_tags: dict[str, list[str]] = field(default_factory=dict)
    cover_mime: str = ""
    cover_size: int = 0
    cover_hash: str = ""
    cover_width: int = 0
    cover_height: int = 0
    cover_error: str = ""
    metadata_errors: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1024 / 1024

    @property
    def duration_display(self) -> str:
        if self.duration_seconds is None:
            return ""
        minutes, seconds = divmod(self.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def bitrate_display(self) -> str:
        return f"{round(self.bitrate / 1000)} kbps" if self.bitrate else ""

    @property
    def comparison_duration(self) -> float | int | None:
        """Single duration contract shared by classification and copying."""
        if self.duration_exact is not None:
            return self.duration_exact
        return self.duration_seconds

    def _table_values(self) -> dict[str, Any]:
        return {
            "status": self.status.decorated,
            "base_title": self.base_title,
            "variation": self.variation or "—",
            "relation": self.relation or "—",
            "collection_warning": self.collection_warning or "—",
            "relative_folder": self.relative_folder,
            "filename": self.filename,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "genre": self.genre,
            "duration": self.duration_display,
            "bitrate": self.bitrate_display,
            "sample_rate": self.sample_rate or "",
            "bit_depth": self.bit_depth or "",
            "format": self.format,
            "size_mb": round(self.size_mb, 2),
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "album_artist": self.album_artist,
            "comment": self.comment,
            "path": str(self.path),
        }

    def table_value(self, field_name: str) -> Any:
        return self._table_values().get(field_name, "")

    def table_row(self, fields: list[str]) -> list[Any]:
        values = self._table_values()
        return [values.get(field, "") for field in fields]

    def search_text(self) -> str:
        return "\n".join(
            (
                self.base_title,
                self.title,
                self.artist,
                self.album,
                Path(self.relative_folder).name,
                self.relative_folder,
                self.filename,
                self.variation,
                self.relation,
                self.collection_warning,
            )
        ).casefold()


@dataclass(slots=True)
class AlbumCompletenessIssue:
    id: str
    relative_folder: str
    album: str
    disc: int
    present_numbers: tuple[int, ...]
    missing_numbers: tuple[int, ...]
    expected_total: int
    total_from_tags: bool
    unnumbered_files: tuple[str, ...] = ()
    inconsistent_totals: tuple[int, ...] = ()

    @property
    def context(self) -> str:
        parts = [self.relative_folder]
        if self.album:
            parts.append(self.album)
        if self.disc > 1:
            parts.append(f"диск {self.disc}")
        return " · ".join(parts)

    @property
    def short_text(self) -> str:
        details: list[str] = []
        if self.missing_numbers:
            numbers = ", ".join(str(number) for number in self.missing_numbers)
            details.append(f"пропущены № {numbers}")
        if self.total_from_tags:
            details.append(f"ожидается {self.expected_total}")
        if self.unnumbered_files:
            details.append(f"без Track #: {len(self.unnumbered_files)}")
        if self.inconsistent_totals:
            totals = ", ".join(str(number) for number in self.inconsistent_totals)
            if len(self.inconsistent_totals) == 1:
                details.append(f"итог в теге противоречит номерам: {totals}")
            else:
                details.append(f"разные итоги в тегах: {totals}")
        return "⚠ " + "; ".join(details)


@dataclass(slots=True)
class AnalysisResult:
    tracks: list[Track]
    folders_scanned: int
    root: Path
    completeness_issues: list[AlbumCompletenessIssue] = field(default_factory=list)
    audit_issues: list[MetadataAuditIssue] = field(default_factory=list)

    def count(self, status: TrackStatus) -> int:
        return sum(track.status == status for track in self.tracks)

    @property
    def total_size_mb(self) -> float:
        return sum(track.size_bytes for track in self.tracks) / 1024 / 1024

    @property
    def missing_track_count(self) -> int:
        return sum(len(issue.missing_numbers) for issue in self.completeness_issues)

    def audit_count(self, severity: AuditSeverity) -> int:
        return sum(issue.severity == severity for issue in self.audit_issues)

```

### `discography_analyzer/parsing.py`

Парсинг имён файлов: вырезание номеров треков и CD/Disc-префиксов, извлечение названия из имени файла, разбиение артистов по разделителям (`, ; & + feat. ft. with and`), `detect_variation` — детект маркера вариации в названии → (базовое название, вариация). Используется классификатором как fallback, когда теги пусты.

```python
from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

TRACK_PREFIX_RE = re.compile(
    r"^\s*(?:(?:cd|disc)\s*\d+\s*[-_. ]+)?(?:\d{1,3}\s*[-_.]\s*|\d{1,3}\s+)",
    re.IGNORECASE,
)
ARTIST_SEPARATOR_RE = re.compile(
    r"\s*(?:,|;|&|\+|\bfeat(?:uring)?\b\.?|\bft\b\.?)\s*"
    r"|\s+(?:with|x|and)\s+",
    re.IGNORECASE,
)


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    return TRACK_PREFIX_RE.sub("", stem, count=1).strip()


def artist_set(artist: str) -> set[str]:
    if not artist or not artist.strip():
        return set()
    return {
        re.sub(r"\s+", " ", part).strip().casefold()
        for part in ARTIST_SEPARATOR_RE.split(artist)
        if part.strip()
    }


def _contains_marker(text: str, markers: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(
        re.search(rf"(?<!\w){re.escape(marker.casefold())}(?!\w)", lowered)
        for marker in markers
        if marker.strip()
    )


def detect_variation(title: str, markers: Iterable[str]) -> tuple[str, str] | None:
    """Return a possible (base, variation) without changing the displayed title."""
    title = title.strip()
    if not title:
        return None

    bracket = re.match(r"^(?P<base>.+?)\s*[\(\[]\s*(?P<var>[^\)\]]+)\s*[\)\]]\s*$", title)
    if bracket and _contains_marker(bracket.group("var"), markers):
        return bracket.group("base").strip(), bracket.group("var").strip()

    hyphen = re.match(r"^(?P<base>.+?)\s+-\s+(?P<var>.+?)\s*$", title)
    if hyphen and _contains_marker(hyphen.group("var"), markers):
        return hyphen.group("base").strip(), hyphen.group("var").strip()

    sorted_markers = sorted(
        (m.strip() for m in markers if m.strip()),
        key=lambda item: (len(item.split()), len(item)),
        reverse=True,
    )
    one_word_markers = {
        marker.casefold() for marker in sorted_markers if len(marker.split()) == 1
    }
    for marker in sorted_markers:
        match = re.match(
            rf"^(?P<base>.+?)\s+(?P<var>{re.escape(marker)})\s*$",
            title,
            re.IGNORECASE,
        )
        if not match:
            continue
        base = match.group("base").strip()
        variation = match.group("var").strip()
        # Adjacent marker words form one designation: "Radio Edit",
        # "Acoustic Version", "Extended Club Mix".
        while True:
            prefix = re.match(r"^(?P<base>.*\S)\s+(?P<word>[\w'-]+)$", base)
            if not prefix or prefix.group("word").casefold() not in one_word_markers:
                break
            variation = f"{prefix.group('word')} {variation}"
            base = prefix.group("base").strip()
        return base, variation
    return None


def validate_markers(lines: Iterable[str]) -> list[str]:
    result: list[str] = []
    for number, raw in enumerate(lines, start=1):
        marker = raw.strip()
        if not marker:
            continue
        if len(marker) > 80 or not re.fullmatch(r"[\wÀ-žА-Яа-яЁё' -]+", marker):
            raise ValueError(f"Некорректное обозначение вариации в строке {number}: {raw!r}")
        if marker.casefold() not in {item.casefold() for item in result}:
            result.append(marker)
    return result

```

### `discography_analyzer/scanner.py`

Сбор и чтение коллекции: `_collect_files` — обход дерева (скрытые каталоги пропускаются, учёт исключённых папок и выбранных форматов); `analyze_collection` — оркестратор пайплайна: подсчёт файлов → чтение метаданных по каждому → классификация → комплектность → аудит. Исключения `AnalysisStopped` / `NoAudioFilesError` / `NoSelectedFormatsError`, прогресс-колбэк и `stop_event` для кнопки «Стоп».

```python
from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .classifier import classify_tracks
from .completeness import analyze_track_completeness
from .constants import SUPPORTED_FORMATS
from .metadata import read_metadata
from .metadata_audit import audit_metadata
from .models import AnalysisResult, Track, TrackStatus
from .parsing import title_from_filename

ProgressCallback = Callable[[int, str, int, int, int], None]


class AnalysisStopped(RuntimeError):
    pass


class NoAudioFilesError(RuntimeError):
    pass


class NoSelectedFormatsError(RuntimeError):
    pass


def _date_text(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _collect_files(
    root: Path,
    include_subfolders: bool,
    excluded_folders: list[str],
    selected_extensions: set[str],
    stop_event: threading.Event,
    progress: ProgressCallback,
) -> tuple[list[Path], int]:
    files: list[Path] = []
    supported_seen = 0
    folders_scanned = 0
    excluded = {name.casefold() for name in excluded_folders if name.strip()}

    if include_subfolders:
        for current, directories, names in os.walk(root):
            if stop_event.is_set():
                raise AnalysisStopped
            directories[:] = [
                name
                for name in directories
                if name.casefold() not in excluded and not name.startswith(".")
            ]
            directories.sort(key=str.casefold)
            names.sort(key=str.casefold)
            folders_scanned += 1
            progress(0, f"Сканирование папки: {current}", len(files), folders_scanned, 0)
            for name in names:
                suffix = Path(name).suffix.casefold()
                if suffix in SUPPORTED_FORMATS.values():
                    supported_seen += 1
                    if suffix in selected_extensions:
                        files.append(Path(current) / name)
    else:
        folders_scanned = 1
        for item in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if stop_event.is_set():
                raise AnalysisStopped
            if item.is_file() and item.suffix.casefold() in SUPPORTED_FORMATS.values():
                supported_seen += 1
                if item.suffix.casefold() in selected_extensions:
                    files.append(item)
        progress(0, f"Сканирование папки: {root}", len(files), folders_scanned, 0)

    if supported_seen == 0:
        raise NoAudioFilesError("Аудиофайлы не найдены в выбранной директории")
    if not files:
        raise NoSelectedFormatsError("Аудиофайлы выбранных форматов не найдены")
    return files, folders_scanned


def analyze_collection(
    root: Path,
    include_subfolders: bool,
    selected_formats: list[str],
    excluded_folders: list[str],
    use_tags: bool,
    detect_variations: bool,
    check_track_gaps: bool,
    variation_markers: list[str],
    stop_event: threading.Event,
    progress: ProgressCallback,
) -> AnalysisResult:
    selected_extensions = {
        SUPPORTED_FORMATS[name] for name in selected_formats if name in SUPPORTED_FORMATS
    }
    progress(0, "Подсчёт файлов...", 0, 0, 0)
    files, folders_scanned = _collect_files(
        root,
        include_subfolders,
        excluded_folders,
        selected_extensions,
        stop_event,
        progress,
    )

    tracks: list[Track] = []
    skipped_files = 0
    total = len(files)
    for index, path in enumerate(files, start=1):
        if stop_event.is_set():
            raise AnalysisStopped
        try:
            stat = path.stat()
            relative = path.relative_to(root)
            relative_folder = str(relative.parent)
            if relative_folder == ".":
                relative_folder = "(корень)"
            track = Track(
                id=uuid.uuid4().hex,
                path=path,
                root=root,
                filename=path.name,
                relative_path=str(relative),
                relative_folder=relative_folder,
                format=path.suffix[1:].upper(),
                size_bytes=stat.st_size,
                modified_at=_date_text(stat.st_mtime),
                created_at=_date_text(stat.st_ctime),
                filename_title=title_from_filename(path.name),
            )
            read_metadata(track)
            tracks.append(track)
        except OSError:
            skipped_files += 1
            continue
        percent = min(95, round(index / total * 95))
        progress(
            percent,
            f"Анализ файла: …{str(path)[-90:]}",
            len(tracks),
            folders_scanned,
            0,
        )

    if stop_event.is_set():
        raise AnalysisStopped
    classify_tracks(tracks, use_tags, detect_variations, variation_markers)
    completeness_issues = (
        analyze_track_completeness(tracks) if check_track_gaps else []
    )
    progress(
        97,
        "Аудит метаданных...",
        len(tracks),
        folders_scanned,
        sum(track.status == TrackStatus.VARIATION for track in tracks),
    )
    audit_issues = audit_metadata(tracks)
    variations = sum(track.status == TrackStatus.VARIATION for track in tracks)
    final_state = "Анализ завершён!"
    if skipped_files:
        final_state += f" Пропущено недоступных файлов: {skipped_files}"
    progress(100, final_state, len(tracks), folders_scanned, variations)
    return AnalysisResult(
        tracks=tracks,
        folders_scanned=folders_scanned,
        root=root,
        completeness_issues=completeness_issues,
        audit_issues=audit_issues,
    )

```

### `discography_analyzer/metadata.py`

Чтение тегов через mutagen — самый насыщенный модуль данных. Easy-представление + raw (FLAC/APE парсятся один раз — у них нет easy-обёртки); маппинг полей с fallback-ключами; кадры `COMM:<desc>:<lang>` → поле «Комментарий» (технические iTunNORM не трогаются); позиции трек/диск с тоталами; обложки — единый `_embedded_cover()` для аудита и предпросмотра, валидация картинки через Pillow (`cover_error` ≠ `metadata_errors`: битая обложка не делает весь файл «ошибкой метаданных»); техполя из `info` (битрейт, частота, глубина, кодек…); `all_tags` — полная карта сырых тегов для инфо-панели; `RAW_FALLBACK_KEYS` — модульная константа «родных» ключей форматов без easy-обёртки, переиспользуется `metadata_writer` для записи в ключ, из которого значение прочитано.

```python
from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image

from .models import Track

try:
    import mutagen
    from mutagen.easyid3 import EasyID3
    from mutagen.easymp4 import EasyMP4Tags
    from mutagen.flac import FLAC
    from mutagen.id3 import APIC, ID3
    from mutagen.mp4 import MP4, MP4Cover
except ImportError:  # The GUI provides a friendly dependency message.
    mutagen = None
    FLAC = ID3 = MP4 = APIC = MP4Cover = EasyID3 = EasyMP4Tags = None


class MetadataDependencyError(RuntimeError):
    pass


EASY_FIELDS = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "albumartist": "album_artist",
    "tracknumber": "track_number",
    "discnumber": "disc_number",
    "date": "year",
    "year": "year",
    "genre": "genre",
    "comment": "comment",
    "description": "comment",
}
# Native keys of formats without an "easy" view (APEv2, some Vorbis
# taggers such as foobar2000's "ALBUM ARTIST"). The metadata writer uses the
# same list to update the key the value was actually read from.
RAW_FALLBACK_KEYS = {
    "title": ("Title", "TITLE"),
    "artist": ("Artist", "ARTIST"),
    "album": ("Album", "ALBUM"),
    "album_artist": ("Album Artist", "ALBUMARTIST", "ALBUM ARTIST"),
    "track_number": ("Track", "TRACK", "TRACKNUMBER"),
    "disc_number": ("Disc", "DISC", "DISCNUMBER"),
    "year": ("Year", "YEAR", "DATE"),
    "genre": ("Genre", "GENRE"),
    "comment": ("Comment", "COMMENT", "DESCRIPTION"),
}


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bytes):
        return [f"<двоичные данные: {len(value)} байт>"]
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        result: list[str] = []
        for item in value:
            result.extend(_as_text_list(item))
        return result
    if hasattr(value, "data") and isinstance(value.data, bytes):
        mime = getattr(value, "mime", "изображение")
        return [f"<встроенная обложка: {mime}, {len(value.data)} байт>"]
    text = str(value)
    if len(text) > 4000:
        return [f"<данные типа {type(value).__name__}, {len(text)} символов>"]
    return [text]


def _first(tags: Any, key: str) -> str:
    # Compare with ``None`` rather than testing truthiness: ``bool(EasyID3)``
    # enumerates every registered easy key through ``keys()`` and was the
    # single most expensive operation of the whole analysis.
    if tags is None:
        return ""
    value = tags.get(key)
    values = _as_text_list(value)
    return "; ".join(v for v in values if v).strip()


def _values(tags: Any, key: str) -> list[str]:
    if tags is None:
        return []
    return [value for value in _as_text_list(tags.get(key)) if value.strip()]


def _first_any(tags: Any, keys: Iterable[str]) -> str:
    for key in keys:
        value = _first(tags, key)
        if value:
            return value
    return ""


def _values_any(tags: Any, keys: Iterable[str]) -> list[str]:
    for key in keys:
        values = _values(tags, key)
        if values:
            return values
    return []


def _merge_position(number: str, total: str) -> str:
    if not number or not total or "/" in number:
        return number
    total_digits = "".join(character for character in total if character.isdigit())
    return f"{number}/{total_digits}" if total_digits else number


def _cover_details(data: bytes, mime: str) -> tuple[str, int, str, int, int, str]:
    digest = hashlib.sha256(data).hexdigest()
    width = 0
    height = 0
    error = ""
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image.verify()
    except Exception as exc:
        # Pillow signals broken images with OSError/ValueError, but also with
        # SyntaxError (truncated PNG chunks) and DecompressionBombError. Any
        # of them is a *cover* problem and must not mark the whole file as
        # unreadable - the tags were parsed fine.
        error = str(exc)
    return mime or "image/unknown", len(data), digest, width, height, error


def _front_picture(pictures: list[Any]) -> Any:
    """Prefer the picture marked as front cover (type 3), else the first one."""
    return next(
        (item for item in pictures if getattr(item, "type", 0) == 3),
        pictures[0],
    )


def _embedded_cover(audio: Any, path: Path) -> tuple[bytes, str] | None:
    """Return ``(data, mime)`` of the embedded cover shared by audit and UI.

    One code path guarantees the preview shows exactly the picture whose
    hash and dimensions the metadata audit reasoned about.
    """
    if FLAC is not None and isinstance(audio, FLAC) and audio.pictures:
        picture = _front_picture(audio.pictures)
        return picture.data, picture.mime or "image/unknown"
    if MP4 is not None and isinstance(audio, MP4) and audio.tags:
        covers = audio.tags.get("covr", [])
        if covers:
            cover = covers[0]
            image_format = getattr(cover, "imageformat", None)
            mime = "image/png" if image_format == MP4Cover.FORMAT_PNG else "image/jpeg"
            return bytes(cover), mime
    tags = getattr(audio, "tags", None)
    if tags and hasattr(tags, "values"):
        pictures = [
            frame
            for frame in tags.values()
            if APIC is not None and isinstance(frame, APIC)
        ]
        if pictures:
            picture = _front_picture(pictures)
            return picture.data, picture.mime or "image/unknown"
    if path.suffix.casefold() == ".ape" and tags:
        for key in ("Cover Art (Front)", "Cover Art (Back)"):
            value = tags.get(key)
            raw = getattr(value, "value", value)
            if isinstance(raw, bytes):
                _, _, data = raw.partition(b"\x00")
                if data:
                    return data, "image/unknown"
    return None


def _extract_cover_details(
    audio: Any,
    path: Path,
) -> tuple[str, int, str, int, int, str]:
    cover = _embedded_cover(audio, path)
    if cover is None:
        return "", 0, "", 0, 0, ""
    return _cover_details(*cover)


def read_metadata(track: Track) -> None:
    if mutagen is None:
        raise MetadataDependencyError(
            "Не установлена библиотека Mutagen. Выполните: pip install -r requirements.txt"
        )
    try:
        easy = mutagen.File(track.path, easy=True)
        if easy is None:
            raise ValueError("формат файла не распознан")
        # Only ID3 and MP4 have a distinct "easy" tag view. For FLAC, APE and
        # the other formats both calls return the same class, so the second
        # parse would merely re-read the whole tag block (embedded covers
        # included) from disk.
        if isinstance(getattr(easy, "tags", None), (EasyID3, EasyMP4Tags)):
            raw = mutagen.File(track.path, easy=False)
        else:
            raw = easy

        easy_tags = getattr(easy, "tags", None)
        for key, attr in EASY_FIELDS.items():
            values = _values(easy_tags, key)
            if values and attr not in track.canonical_tags:
                track.canonical_tags[attr] = values
            value = "; ".join(values).strip()
            if value and not getattr(track, attr):
                setattr(track, attr, value)

        raw_tags = getattr(raw, "tags", None)
        for attr, keys in RAW_FALLBACK_KEYS.items():
            if not getattr(track, attr):
                values = _values_any(raw_tags, keys)
                if values and attr not in track.canonical_tags:
                    track.canonical_tags[attr] = values
                value = "; ".join(values).strip()
                if value:
                    setattr(track, attr, value)

        # ID3 keeps comments in COMM frames keyed "COMM:<desc>:<lang>", so the
        # plain-name lookups above never see them. Only the standard comment
        # (empty description) is used; iTunNORM-style technical frames stay
        # in the full tag list.
        if not track.comment and ID3 is not None and isinstance(raw_tags, ID3):
            values = [
                text
                for frame in raw_tags.getall("COMM")
                if not getattr(frame, "desc", "")
                for text in _as_text_list(frame)
                if text.strip()
            ]
            if values:
                track.canonical_tags.setdefault("comment", values)
                track.comment = "; ".join(values).strip()

        track_total = _first_any(
            easy_tags, ("tracktotal", "totaltracks", "totaltrack")
        ) or _first_any(raw_tags, ("TrackTotal", "TRACKTOTAL", "TOTALTRACKS"))
        disc_total = _first_any(
            easy_tags, ("disctotal", "totaldiscs", "totaldisc")
        ) or _first_any(raw_tags, ("DiscTotal", "DISCTOTAL", "TOTALDISCS"))

        # MP4 stores positions as numeric tuples in the raw trkn/disk atoms.
        if MP4 is not None and isinstance(raw, MP4) and raw_tags:
            for key, attr in (("trkn", "track_number"), ("disk", "disc_number")):
                values = raw_tags.get(key, [])
                if values and isinstance(values[0], tuple):
                    number = values[0][0] if values[0] else 0
                    total = values[0][1] if len(values[0]) > 1 else 0
                    if number:
                        setattr(
                            track,
                            attr,
                            f"{number}/{total}" if total else str(number),
                        )
        track.track_number = _merge_position(track.track_number, track_total)
        track.disc_number = _merge_position(track.disc_number, disc_total)

        info = getattr(raw, "info", None)
        if info is not None:
            exact = getattr(info, "length", None)
            if exact is not None:
                track.duration_exact = float(exact)
                # Rounded seconds are only for user-friendly display. The
                # classifier uses the exact value above with no tolerance.
                track.duration_seconds = round(float(exact))
            for source, target in (
                ("bitrate", "bitrate"),
                ("sample_rate", "sample_rate"),
                ("bits_per_sample", "bit_depth"),
                ("channels", "channels"),
                ("channel_mode", "channel_mode"),
                ("bitrate_mode", "bitrate_mode"),
                ("codec", "codec"),
                ("encoder_info", "encoder"),
                ("encoder_settings", "encoder_settings"),
                ("version", "version"),
                ("layer", "layer"),
                ("protected", "protection"),
            ):
                value = getattr(info, source, None)
                if value is not None:
                    setattr(track, target, value)

        if raw_tags:
            # Vorbis comments are a *list* of (key, value) pairs, so plain
            # iteration would yield tuples; .keys() is the portable form.
            for key in raw_tags.keys():  # noqa: SIM118
                try:
                    track.all_tags[str(key)] = _as_text_list(raw_tags[key])
                except Exception as exc:  # One broken tag must not hide the rest.
                    track.all_tags[str(key)] = [f"<ошибка чтения: {exc}>"]

        for key, attr in (
            ("replaygain_track_gain", "track_gain"),
            ("replaygain_track_peak", "track_peak"),
            ("replaygain_album_gain", "album_gain"),
            ("replaygain_album_peak", "album_peak"),
        ):
            value = _first(easy_tags, key)
            if value:
                setattr(track, attr, value)

        (
            track.cover_mime,
            track.cover_size,
            track.cover_hash,
            track.cover_width,
            track.cover_height,
            track.cover_error,
        ) = _extract_cover_details(raw, track.path)
    except MetadataDependencyError:
        raise
    except Exception as exc:
        track.metadata_errors.append(str(exc))


def read_embedded_cover(path: Path) -> tuple[bytes | None, str, str]:
    """Return (data, mime, error_message)."""
    if mutagen is None:
        return None, "", "Не установлена библиотека Mutagen"
    try:
        audio = mutagen.File(path, easy=False)
        if audio is None:
            return None, "", "Формат файла не распознан"
        cover = _embedded_cover(audio, path)
        if cover is None:
            return None, "", ""
        return cover[0], cover[1], ""
    except Exception as exc:
        return None, "", str(exc)

```

### `discography_analyzer/classifier.py`

Строгие детерминированные правила классификации из функциональной спецификации. Дубль = идентичное сравнительное название + точная длительность + общий артист. Вариация = маркер вариации + ровно один исходник с пересечением артистов. Конфликт = отсутствуют обязательные данные. Группировка дублей только внутри групп `base_title` (нет глобального O(n²)). `prepare_titles` выбирает сравнительное название (тег или имя файла).

```python
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .models import Track, TrackStatus
from .parsing import artist_set, detect_variation


def prepare_titles(
    tracks: Iterable[Track],
    use_tags: bool,
    detect_variations: bool,
    variation_markers: list[str],
) -> None:
    for track in tracks:
        track.comparison_title = (
            track.title.strip() if use_tags and track.title.strip() else track.filename_title.strip()
        )
        track.base_title = track.comparison_title
        track.variation = ""
        track.potential_base = ""
        track.potential_variation = ""
        track.source_track_id = None
        track.relation = ""
        track.related_track_ids.clear()
        track.duplicate_group_id = ""
        track.status = TrackStatus.UNIQUE

        if not detect_variations:
            continue
        candidate = detect_variation(track.comparison_title, variation_markers)
        if candidate is None and track.filename_title != track.comparison_title:
            candidate = detect_variation(track.filename_title, variation_markers)
        if candidate:
            track.potential_base, track.potential_variation = candidate


def classify_tracks(
    tracks: list[Track],
    use_tags: bool = True,
    detect_variations: bool = True,
    variation_markers: list[str] | None = None,
) -> list[Track]:
    """Apply the strict, deterministic rules from the functional specification."""
    if variation_markers is None:
        from .constants import DEFAULT_VARIATION_MARKERS

        variation_markers = DEFAULT_VARIATION_MARKERS

    prepare_titles(tracks, use_tags, detect_variations, variation_markers)

    # A possible variation is linked only to exactly one real, non-variation source.
    artist_sets = {track.id: artist_set(track.artist) for track in tracks}
    sources_by_title: dict[str, list[Track]] = defaultdict(list)
    for origin in tracks:
        if not origin.potential_variation:
            sources_by_title[origin.comparison_title].append(origin)
    for track in tracks:
        if not track.potential_variation:
            continue
        track_artists = artist_sets[track.id]
        candidates = [
            origin
            for origin in sources_by_title.get(track.potential_base, ())
            if origin.id != track.id
            and bool(artist_sets[origin.id])
            and bool(track_artists)
            and bool(artist_sets[origin.id] & track_artists)
        ]
        if len(candidates) == 1:
            track.base_title = track.potential_base
            track.variation = track.potential_variation
            track.source_track_id = candidates[0].id
            track.status = TrackStatus.VARIATION

    # When the version marker came only from the filename and no unique source
    # was found, the complete filename title remains the standalone title.
    for track in tracks:
        if (
            track.potential_variation
            and track.status != TrackStatus.VARIATION
            and track.comparison_title == track.potential_base
            and track.filename_title != track.comparison_title
        ):
            track.base_title = track.filename_title

    ordinary = [track for track in tracks if track.status != TrackStatus.VARIATION]
    groups: dict[str, list[Track]] = defaultdict(list)
    for track in ordinary:
        groups[track.base_title].append(track)

    duplicate_ids: set[str] = set()
    conflict_ids: set[str] = set()
    duplicate_neighbors: dict[str, set[str]] = defaultdict(set)
    conflict_neighbors: dict[str, set[str]] = defaultdict(set)
    for title_group in groups.values():
        for index, left in enumerate(title_group):
            for right in title_group[index + 1 :]:
                left_duration = left.comparison_duration
                right_duration = right.comparison_duration
                # A known duration difference always means different tracks.
                if (
                    left_duration is not None
                    and right_duration is not None
                    and left_duration != right_duration
                ):
                    continue
                if left_duration is None or right_duration is None:
                    conflict_ids.update((left.id, right.id))
                    conflict_neighbors[left.id].add(right.id)
                    conflict_neighbors[right.id].add(left.id)
                    continue

                left_artists = artist_sets[left.id]
                right_artists = artist_sets[right.id]
                if not left_artists or not right_artists:
                    conflict_ids.update((left.id, right.id))
                    conflict_neighbors[left.id].add(right.id)
                    conflict_neighbors[right.id].add(left.id)
                elif left_artists & right_artists:
                    duplicate_ids.update((left.id, right.id))
                    duplicate_neighbors[left.id].add(right.id)
                    duplicate_neighbors[right.id].add(left.id)
                elif not left.album.strip() or not right.album.strip():
                    conflict_ids.update((left.id, right.id))
                    conflict_neighbors[left.id].add(right.id)
                    conflict_neighbors[right.id].add(left.id)

    for track in ordinary:
        # Manual-review uncertainty takes precedence when a file participates
        # in both a confirmed and an incomplete comparison group.
        if track.id in conflict_ids:
            track.status = TrackStatus.CONFLICT
        elif track.id in duplicate_ids:
            track.status = TrackStatus.DUPLICATE
        else:
            track.status = TrackStatus.UNIQUE

    by_id = {track.id: track for track in tracks}

    # Build explicit duplicate components so every row names the other files
    # that caused its classification.
    seen: set[str] = set()
    for track_id in sorted(duplicate_neighbors):
        if track_id in seen or by_id[track_id].status != TrackStatus.DUPLICATE:
            continue
        stack = [track_id]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component or by_id[current].status != TrackStatus.DUPLICATE:
                continue
            component.add(current)
            stack.extend(duplicate_neighbors[current] - component)
        seen.update(component)
        group_id = min(component) if len(component) > 1 else ""
        for current in component:
            by_id[current].duplicate_group_id = group_id

    # Confirmed duplicate edges remain visible even when one endpoint also
    # participates in an incomplete comparison and therefore has CONFLICT
    # as its primary status.
    for track_id, neighbors in duplicate_neighbors.items():
        item = by_id[track_id]
        others = sorted(
            (by_id[other] for other in neighbors),
            key=lambda other: (
                other.relative_folder.casefold(),
                other.filename.casefold(),
            ),
        )
        item.related_track_ids.extend(
            other.id for other in others if other.id not in item.related_track_ids
        )
        if others:
            prefix = (
                "Дубли"
                if item.status == TrackStatus.DUPLICATE
                else "Подтверждённые дубли"
            )
            item.relation = prefix + ": " + "; ".join(
                f"{other.filename} [{other.relative_folder}]" for other in others
            )

    for track_id, neighbors in conflict_neighbors.items():
        item = by_id[track_id]
        if item.status != TrackStatus.CONFLICT:
            continue
        others = sorted(
            (by_id[other] for other in neighbors),
            key=lambda other: (other.relative_folder.casefold(), other.filename.casefold()),
        )
        item.related_track_ids.extend(
            other.id for other in others if other.id not in item.related_track_ids
        )
        if others:
            conflict_text = "Проверить с: " + "; ".join(
                f"{other.filename} [{other.relative_folder}]" for other in others
            )
            item.relation = (
                f"{item.relation} · {conflict_text}"
                if item.relation
                else conflict_text
            )

    source_to_variations: dict[str, list[Track]] = defaultdict(list)
    for track in tracks:
        if track.status == TrackStatus.VARIATION and track.source_track_id:
            source_to_variations[track.source_track_id].append(track)
            source = by_id[track.source_track_id]
            track.related_track_ids.append(source.id)
            track.relation = f"Исходник: {source.filename} [{source.relative_folder}]"
    for source_id, variations in source_to_variations.items():
        source = by_id[source_id]
        source.related_track_ids.extend(
            variation.id
            for variation in variations
            if variation.id not in source.related_track_ids
        )
        variation_text = "Вариации: " + "; ".join(
            f"{variation.filename} ({variation.variation})"
            for variation in sorted(variations, key=lambda item: item.filename.casefold())
        )
        source.relation = (
            f"{source.relation} · {variation_text}" if source.relation else variation_text
        )
    return tracks

```

### `discography_analyzer/completeness.py`

Комплектность альбомов: `parse_position` разбирает значения Track#/Disc# («4», «4/10», «4 of 10», «4 из 10»), проверка пропусков номеров треков в пределах альбома → `AlbumCompletenessIssue`. Быстро (0.1 с на 5000 треков) и детерминированно.

```python
from __future__ import annotations

import re
import uuid
from collections import defaultdict

from .models import AlbumCompletenessIssue, Track

TRACK_POSITION_RE = re.compile(
    r"^\s*(?P<number>\d+)(?:\s*(?:/|of|из)\s*(?P<total>\d+))?",
    re.IGNORECASE,
)


def parse_position(value: str) -> tuple[int | None, int | None]:
    """Parse common Track#/Disc# values such as 4, 4/10 or 4 of 10."""
    if not value:
        return None, None
    match = TRACK_POSITION_RE.match(value)
    if not match:
        return None, None
    number = int(match.group("number"))
    total = int(match.group("total")) if match.group("total") else None
    if number < 1:
        return None, total
    return number, total


def analyze_track_completeness(
    tracks: list[Track],
) -> list[AlbumCompletenessIssue]:
    """Find missing album track numbers without guessing beyond available tags."""
    for track in tracks:
        track.collection_warning = ""
        track.collection_issue_id = ""

    groups: dict[tuple[str, str, int], list[Track]] = defaultdict(list)
    for track in tracks:
        disc, _disc_total = parse_position(track.disc_number)
        key = (
            track.relative_folder,
            track.album.strip().casefold(),
            disc or 1,
        )
        groups[key].append(track)

    issues: list[AlbumCompletenessIssue] = []
    for (_folder, _album_key, disc), group in groups.items():
        numbered: dict[int, list[Track]] = defaultdict(list)
        totals: set[int] = set()
        unnumbered: list[Track] = []
        for track in group:
            number, total = parse_position(track.track_number)
            if number is None:
                unnumbered.append(track)
                continue
            numbered[number].append(track)
            if total is not None and total > 0:
                totals.add(total)

        if not numbered:
            continue
        present = set(numbered)
        expected_total = max(max(present), max(totals) if totals else 0)
        missing = tuple(sorted(set(range(1, expected_total + 1)) - present))
        inconsistent_totals = (
            tuple(sorted(totals))
            if len(totals) > 1 or any(total < max(present) for total in totals)
            else ()
        )

        # Missing numbers are actionable. Incomplete numbering or contradictory
        # totals are also shown because they make the completeness check uncertain.
        if not missing and not unnumbered and not inconsistent_totals:
            continue

        first = group[0]
        issue = AlbumCompletenessIssue(
            id=uuid.uuid4().hex,
            relative_folder=first.relative_folder,
            album=first.album,
            disc=disc,
            present_numbers=tuple(sorted(present)),
            missing_numbers=missing,
            expected_total=expected_total,
            total_from_tags=bool(totals),
            unnumbered_files=tuple(track.filename for track in unnumbered),
            inconsistent_totals=inconsistent_totals,
        )
        issues.append(issue)
        for track in group:
            track.collection_warning = issue.short_text
            track.collection_issue_id = issue.id

    return sorted(
        issues,
        key=lambda issue: (
            issue.relative_folder.casefold(),
            issue.album.casefold(),
            issue.disc,
        ),
    )

```

### `discography_analyzer/audit_models.py`

Модели аудита метаданных: enum'ы `AuditSeverity` (Ошибка/Предупреждение/Инфо), `AuditCategory`, `AuditConfidence`, `AuditFixKind`; dataclass `MetadataAuditIssue` (поле, текущее/предлагаемое значение, сообщение, severity, fix_kind); человекочитаемые метки полей для UI.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

AUDIT_FIELD_LABELS = {
    "metadata": "Метаданные",
    "duration": "Длительность",
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album Artist",
    "track_number": "Track #",
    "disc_number": "Disc #",
    "year": "Year/Date",
    "genre": "Genre",
    "cover": "Встроенная обложка",
}


class AuditSeverity(str, Enum):
    ERROR = "Ошибка"
    WARNING = "Предупреждение"
    INFO = "Рекомендация"

    @property
    def order(self) -> int:
        return {
            AuditSeverity.ERROR: 0,
            AuditSeverity.WARNING: 1,
            AuditSeverity.INFO: 2,
        }[self]

    @property
    def decorated(self) -> str:
        return {
            AuditSeverity.ERROR: "● Ошибка",
            AuditSeverity.WARNING: "● Предупреждение",
            AuditSeverity.INFO: "● Рекомендация",
        }[self]


class AuditCategory(str, Enum):
    REQUIRED = "Обязательные теги"
    ARTISTS = "Исполнители"
    ALBUM = "Согласованность альбома"
    NUMBERING = "Нумерация"
    COVER = "Обложка"
    READABILITY = "Чтение файла"
    FORMATTING = "Форматирование"


class AuditConfidence(str, Enum):
    HIGH = "Высокая"
    MEDIUM = "Средняя"
    LOW = "Низкая"
    NONE = "Без предложения"


class AuditFixKind(str, Enum):
    NORMALIZE_ARTISTS = "normalize_artists"
    NORMALIZE_WHITESPACE = "normalize_whitespace"


@dataclass(frozen=True, slots=True)
class MetadataAuditIssue:
    id: str
    track_id: str
    severity: AuditSeverity
    category: AuditCategory
    field: str
    message: str
    current_value: str = ""
    suggested_value: str = ""
    fix_kind: AuditFixKind | None = None
    confidence: AuditConfidence = AuditConfidence.NONE

    @property
    def fixable(self) -> bool:
        return self.fix_kind is not None and bool(self.suggested_value)

    @property
    def safe_fix(self) -> bool:
        return self.fixable and self.confidence == AuditConfidence.HIGH

    @property
    def field_label(self) -> str:
        return AUDIT_FIELD_LABELS.get(self.field, self.field)

    def search_text(self) -> str:
        return "\n".join(
            (
                self.severity.value,
                self.category.value,
                self.field,
                self.message,
                self.current_value,
                self.suggested_value,
            )
        ).casefold()

```

### `discography_analyzer/metadata_audit.py`

Правила аудита тегов → список `MetadataAuditIssue`: разделители артистов («A;B» → «A, B»), повторные разделители («A;;B»), лишние пробелы и контрольные символы, отсутствующие обязательные поля, встроенная обложка (в т.ч. поиск внешнего cover.jpg рядом с файлом), доминирующие значения по коллекции, подозрительная длительность/битрейт. «Доминирующая обложка» альбома требует строгого перевеса (`count > second`): при ничьей хешей (A,A,B,B) ложных предупреждений нет. Каждое ишьюс несёт `suggested_value` для безопасного фикса; severity от ERROR до INFO.

```python
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from .audit_models import (
    AUDIT_FIELD_LABELS,
    AuditCategory,
    AuditConfidence,
    AuditFixKind,
    AuditSeverity,
    MetadataAuditIssue,
)
from .completeness import parse_position
from .models import Track
from .parsing import artist_set

ARTIST_DELIMITER_RE = re.compile(r"[;,]")
REPEATED_DELIMITER_RE = re.compile(r"[;,]\s*[;,]")
CONTROL_OR_WHITESPACE_RE = re.compile(r"\s+")
POSITION_RE = re.compile(
    r"^\s*\d+\s*(?:(?:/|of|из)\s*\d+\s*)?$",
    re.IGNORECASE,
)
COMPILATION_ARTISTS = {
    "various artists",
    "various",
    "разные исполнители",
    "сборник",
}
EXTERNAL_COVER_STEMS = {
    "cover",
    "folder",
    "front",
    "albumart",
    "album art",
}
EXTERNAL_COVER_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
TEXT_FIELDS = (
    "title",
    "artist",
    "album",
    "album_artist",
    "year",
    "genre",
)


def normalize_whitespace(value: str) -> str:
    return CONTROL_OR_WHITESPACE_RE.sub(" ", value).strip()


def normalize_artist_value(value: str) -> tuple[str, bool]:
    """Return a comma-separated suggestion and whether it changes the value."""
    collapsed = normalize_whitespace(value)
    if not ARTIST_DELIMITER_RE.search(collapsed):
        return collapsed, collapsed != value
    raw_parts = ARTIST_DELIMITER_RE.split(collapsed)
    parts = [normalize_whitespace(part) for part in raw_parts if part.strip()]
    suggestion = ", ".join(parts)
    return suggestion, suggestion != value


def _canonical_values(track: Track, field: str) -> list[str]:
    canonical = getattr(track, "canonical_tags", {})
    values = canonical.get(field, [])
    if values:
        return [str(value) for value in values if str(value).strip()]
    value = str(getattr(track, field, "") or "")
    return [value] if value.strip() else []


def _artist_tokens(track: Track, field: str) -> set[str]:
    tokens: set[str] = set()
    for value in _canonical_values(track, field):
        tokens.update(artist_set(value))
    return tokens


def _dominant_value(values: list[str]) -> str | None:
    normalized = [normalize_whitespace(value) for value in values if value.strip()]
    if len(normalized) < 2:
        return None
    counts = Counter(value.casefold() for value in normalized)
    key, count = counts.most_common(1)[0]
    second = counts.most_common(2)[1][1] if len(counts) > 1 else 0
    if count < 2 or count <= second:
        return None
    return next(value for value in normalized if value.casefold() == key)


def _find_external_cover(folder: Path) -> Path | None:
    try:
        candidates = sorted(folder.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        return None
    for path in candidates:
        if (
            path.is_file()
            and path.suffix.casefold() in EXTERNAL_COVER_SUFFIXES
            and path.stem.casefold() in EXTERNAL_COVER_STEMS
        ):
            return path
    return None


def audit_metadata(tracks: list[Track]) -> list[MetadataAuditIssue]:
    ordered = sorted(
        tracks,
        key=lambda track: (
            track.relative_folder.casefold(),
            track.filename.casefold(),
        ),
    )
    track_sort_keys = {
        track.id: (
            track.relative_folder.casefold(),
            track.filename.casefold(),
        )
        for track in ordered
    }
    issues: list[MetadataAuditIssue] = []
    issue_number = 0

    def add(
        track: Track,
        severity: AuditSeverity,
        category: AuditCategory,
        field: str,
        message: str,
        *,
        current: str = "",
        suggested: str = "",
        fix_kind: AuditFixKind | None = None,
        confidence: AuditConfidence = AuditConfidence.NONE,
    ) -> None:
        nonlocal issue_number
        issue_number += 1
        issues.append(
            MetadataAuditIssue(
                id=f"{issue_number:06d}-{track.id}",
                track_id=track.id,
                severity=severity,
                category=category,
                field=field,
                message=message,
                current_value=current,
                suggested_value=suggested,
                fix_kind=fix_kind,
                confidence=confidence,
            )
        )

    folder_tracks: dict[str, list[Track]] = defaultdict(list)
    album_tracks: dict[tuple[str, str], list[Track]] = defaultdict(list)
    external_covers: dict[Path, Path | None] = {}
    for track in ordered:
        folder_tracks[track.relative_folder].append(track)
        album_key = normalize_whitespace(track.album).casefold()
        if album_key:
            album_tracks[(track.relative_folder, album_key)].append(track)

        if track.metadata_errors:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.READABILITY,
                "metadata",
                "Файл или его теги прочитаны с ошибками",
                current="; ".join(track.metadata_errors),
            )
        if track.duration_exact is None or track.duration_exact <= 0:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.READABILITY,
                "duration",
                "Не удалось определить корректную длительность аудио",
                current=str(track.duration_exact or ""),
            )

        for field in ("title", "artist", "album"):
            value = str(getattr(track, field, "") or "")
            if not value.strip():
                add(
                    track,
                    AuditSeverity.ERROR,
                    AuditCategory.REQUIRED,
                    field,
                    (
                        "Отсутствует обязательный тег "
                        f"{AUDIT_FIELD_LABELS.get(field, field)}"
                    ),
                )
        if not track.album_artist.strip():
            add(
                track,
                AuditSeverity.WARNING,
                AuditCategory.REQUIRED,
                "album_artist",
                "Не заполнен Album Artist",
            )
        if not track.year.strip():
            add(
                track,
                AuditSeverity.INFO,
                AuditCategory.REQUIRED,
                "year",
                "Не указан год или дата релиза",
            )

        for field in TEXT_FIELDS:
            values = _canonical_values(track, field)
            if len(values) != 1:
                continue
            value = values[0]
            if field in ("artist", "album_artist"):
                suggestion, changed = normalize_artist_value(value)
                malformed_separator = (
                    ";" in value
                    or bool(re.search(r",\S|\s+,", value))
                    or bool(REPEATED_DELIMITER_RE.search(value))
                )
                if changed and malformed_separator and suggestion:
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.ARTISTS,
                        field,
                        "Нестандартные разделители или пробелы между исполнителями",
                        current=value,
                        suggested=suggestion,
                        fix_kind=AuditFixKind.NORMALIZE_ARTISTS,
                        confidence=AuditConfidence.HIGH,
                    )
                    continue
            suggestion = normalize_whitespace(value)
            if suggestion != value:
                add(
                    track,
                    AuditSeverity.WARNING,
                    AuditCategory.FORMATTING,
                    field,
                    "Лишние пробелы или управляющие символы в значении тега",
                    current=value,
                    suggested=suggestion,
                    fix_kind=AuditFixKind.NORMALIZE_WHITESPACE,
                    confidence=AuditConfidence.HIGH,
                )

        artist_tokens = _artist_tokens(track, "artist")
        album_artist_tokens = _artist_tokens(track, "album_artist")
        if artist_tokens and album_artist_tokens:
            album_artist_text = " ".join(album_artist_tokens).casefold()
            is_compilation = any(
                marker in album_artist_text for marker in COMPILATION_ARTISTS
            )
            if not is_compilation and not (artist_tokens & album_artist_tokens):
                add(
                    track,
                    AuditSeverity.WARNING,
                    AuditCategory.ARTISTS,
                    "album_artist",
                    "Artist и Album Artist не содержат общего исполнителя",
                    current=track.album_artist,
                )
            elif (
                not is_compilation
                and album_artist_tokens < artist_tokens
                and len(artist_tokens) > 1
            ):
                add(
                    track,
                    AuditSeverity.INFO,
                    AuditCategory.ARTISTS,
                    "album_artist",
                    (
                        "В Artist есть дополнительные исполнители. Это может "
                        "быть корректным оформлением приглашённых участников"
                    ),
                    current=track.album_artist,
                    suggested=track.artist,
                    confidence=AuditConfidence.LOW,
                )

        number, total = parse_position(track.track_number)
        if track.track_number.strip() and (
            number is None or not POSITION_RE.fullmatch(track.track_number)
        ):
            add(
                track,
                AuditSeverity.WARNING,
                AuditCategory.NUMBERING,
                "track_number",
                "Некорректный номер трека",
                current=track.track_number,
            )
        elif number is not None and total is not None and total < number:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.NUMBERING,
                "track_number",
                "Номер трека больше общего количества треков",
                current=track.track_number,
            )

        disc, disc_total = parse_position(track.disc_number)
        if track.disc_number.strip() and (
            disc is None or not POSITION_RE.fullmatch(track.disc_number)
        ):
            add(
                track,
                AuditSeverity.WARNING,
                AuditCategory.NUMBERING,
                "disc_number",
                "Некорректный номер диска",
                current=track.disc_number,
            )
        elif disc is not None and disc_total is not None and disc_total < disc:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.NUMBERING,
                "disc_number",
                "Номер диска больше общего количества дисков",
                current=track.disc_number,
            )

        if track.cover_error:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.COVER,
                "cover",
                "Встроенная обложка повреждена или не читается",
                current=track.cover_error,
            )
        elif not track.cover_hash:
            folder = track.path.parent
            if folder not in external_covers:
                external_covers[folder] = _find_external_cover(folder)
            external = external_covers[folder]
            suggestion = (
                f"Встроить файл {external.name}" if external is not None else ""
            )
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.COVER,
                "cover",
                "Внутри аудиофайла отсутствует встроенная обложка",
                current="Отсутствует",
                suggested=suggestion,
                confidence=(
                    AuditConfidence.MEDIUM
                    if external is not None
                    else AuditConfidence.NONE
                ),
            )

    for group in folder_tracks.values():
        if len(group) > 1:
            for track in group:
                if not track.track_number.strip():
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.NUMBERING,
                        "track_number",
                        "В папке с несколькими треками отсутствует Track #",
                    )

        albums = [track.album for track in group if track.album.strip()]
        dominant_album = _dominant_value(albums)
        if dominant_album and len(group) >= 3:
            matching = sum(
                normalize_whitespace(track.album).casefold()
                == dominant_album.casefold()
                for track in group
            )
            if matching / len(group) >= 0.75:
                for track in group:
                    if (
                        track.album.strip()
                        and normalize_whitespace(track.album).casefold()
                        != dominant_album.casefold()
                    ):
                        add(
                            track,
                            AuditSeverity.WARNING,
                            AuditCategory.ALBUM,
                            "album",
                            "Название альбома отличается от большинства файлов папки",
                            current=track.album,
                            suggested=dominant_album,
                            confidence=AuditConfidence.MEDIUM,
                        )

    for (_folder, _album), group in album_tracks.items():
        if len(group) < 2:
            continue
        numbered: dict[tuple[int, int], list[Track]] = defaultdict(list)
        for track in group:
            number, _total = parse_position(track.track_number)
            disc, _disc_total = parse_position(track.disc_number)
            if number is not None:
                numbered[(disc or 1, number)].append(track)
        for (disc, number), duplicates in numbered.items():
            if len(duplicates) < 2:
                continue
            filenames = ", ".join(track.filename for track in duplicates)
            for track in duplicates:
                add(
                    track,
                    AuditSeverity.ERROR,
                    AuditCategory.NUMBERING,
                    "track_number",
                    f"Номер {number} на диске {disc} повторяется: {filenames}",
                    current=track.track_number,
                )

        album_artists = [
            track.album_artist for track in group if track.album_artist.strip()
        ]
        dominant_artist = _dominant_value(album_artists)
        if dominant_artist:
            for track in group:
                if not track.album_artist.strip():
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.ALBUM,
                        "album_artist",
                        (
                            "Album Artist отсутствует, но для остальных "
                            "треков альбома найдено согласованное значение"
                        ),
                        suggested=dominant_artist,
                        confidence=AuditConfidence.MEDIUM,
                    )
                    continue
                if (
                    track.album_artist.strip()
                    and normalize_whitespace(track.album_artist).casefold()
                    != dominant_artist.casefold()
                ):
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.ALBUM,
                        "album_artist",
                        "Album Artist отличается от большинства треков альбома",
                        current=track.album_artist,
                        suggested=dominant_artist,
                        confidence=AuditConfidence.MEDIUM,
                    )

        years = [track.year for track in group if track.year.strip()]
        dominant_year = _dominant_value(years)
        if dominant_year:
            for track in group:
                if (
                    track.year.strip()
                    and normalize_whitespace(track.year).casefold()
                    != dominant_year.casefold()
                ):
                    add(
                        track,
                        AuditSeverity.INFO,
                        AuditCategory.ALBUM,
                        "year",
                        "Дата отличается от большинства треков альбома",
                        current=track.year,
                        suggested=dominant_year,
                        confidence=AuditConfidence.LOW,
                    )

        cover_counts = Counter(
            track.cover_hash for track in group if track.cover_hash
        )
        if cover_counts:
            ranked = cover_counts.most_common(2)
            dominant_cover, count = ranked[0]
            second = ranked[1][1] if len(ranked) > 1 else 0
            if count >= 2 and count > second:
                source = next(
                    track for track in group if track.cover_hash == dominant_cover
                )
                for track in group:
                    if track.cover_hash and track.cover_hash != dominant_cover:
                        add(
                            track,
                            AuditSeverity.WARNING,
                            AuditCategory.COVER,
                            "cover",
                            "Обложка отличается от большинства треков альбома",
                            current=f"{track.cover_width}×{track.cover_height}",
                            suggested=f"Использовать обложку из {source.filename}",
                            confidence=AuditConfidence.MEDIUM,
                        )

    return sorted(
        issues,
        key=lambda issue: (
            issue.severity.order,
            track_sort_keys.get(issue.track_id, ("", "")),
            issue.category.value,
            issue.field,
            issue.id,
        ),
    )

```

### `discography_analyzer/metadata_writer.py`

Применение «безопасных исправлений» тегов: копия во временный файл → правка easy-тегов → перечитывание с проверкой → атомарная замена исходника. `_target_key` пишет значение в тот ключ, из которого оно прочитано (easy-ключ, а при его отсутствии «родной» ключ из `RAW_FALLBACK_KEYS` — например, `ALBUM ARTIST` у foobar2000 или `YEAR` во FLAC/APE), не создавая рядом второй противоречащий ключ. Версия контейнера ID3v2.3 сохраняется (`v2_version=3` — mutagen по умолчанию переписал бы как v2.4, что ломает проводник Windows и автомагнитолы). Бэкапы и защита от перезаписи существующих.

```python
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .audit_models import MetadataAuditIssue
from .metadata import RAW_FALLBACK_KEYS
from .models import Track

try:
    import mutagen
except ImportError:
    mutagen = None

EASY_TAG_KEYS = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "album_artist": "albumartist",
    "year": "date",
    "genre": "genre",
}
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class MetadataFixFailure:
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class MetadataFixResult:
    updated_files: int
    backup_files: int
    failures: tuple[MetadataFixFailure, ...]
    stopped: bool = False


def _text_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _available_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _save_options(path: Path) -> dict[str, int]:
    """Keep ID3v2.3 files at v2.3 instead of silently upgrading them to v2.4.

    Mutagen writes ID3v2.4 by default. Many players, Windows Explorer and car
    stereos still read only v2.3, so a "safe" separator fix must not change
    the tag container version the user already has.
    """
    raw = mutagen.File(path, easy=False)
    version = getattr(getattr(raw, "tags", None), "version", None)
    if isinstance(version, tuple) and tuple(version[:2]) == (2, 3):
        return {"v2_version": 3}
    return {}


def _target_key(tags, field: str) -> str:
    """Update the key the reader took the value from instead of adding a new one."""
    easy_key = EASY_TAG_KEYS[field]
    if tags.get(easy_key) is not None:
        return easy_key
    return next(
        (key for key in RAW_FALLBACK_KEYS.get(field, ()) if tags.get(key) is not None),
        easy_key,
    )


def _write_verified_copy(
    track: Track,
    changes: dict[str, str],
    backup_root: Path | None,
) -> bool:
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    source = track.path
    source_stat = source.stat()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{source.stem}-audit-",
        suffix=source.suffix,
        dir=source.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    backup_created = False
    try:
        shutil.copy2(source, temporary)
        save_options = _save_options(temporary)
        audio = mutagen.File(temporary, easy=True)
        if audio is None:
            raise ValueError("формат файла не распознан")
        if getattr(audio, "tags", None) is None:
            add_tags = getattr(audio, "add_tags", None)
            if not callable(add_tags):
                raise ValueError("формат не поддерживает создание тегов")
            add_tags()
        keys = {field: _target_key(audio.tags, field) for field in changes}
        for field, value in changes.items():
            audio[keys[field]] = [value]
        audio.save(**save_options)

        verified = mutagen.File(temporary, easy=True)
        if verified is None or getattr(verified, "tags", None) is None:
            raise ValueError("не удалось повторно прочитать записанные теги")
        for field, expected in changes.items():
            values = _text_values(verified.tags.get(keys[field]))
            if not values or values[0] != expected:
                raise ValueError(
                    f"проверка тега {keys[field]} после записи не пройдена"
                )

        os.utime(
            temporary,
            ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
        )
        if backup_root is not None:
            try:
                relative = source.relative_to(track.root)
            except ValueError:
                relative = Path(source.name)
            backup = _available_path(backup_root / relative)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            backup_created = True
        os.replace(temporary, source)
        for field, value in changes.items():
            setattr(track, field, value)
            track.canonical_tags[field] = [value]
        return backup_created
    finally:
        temporary.unlink(missing_ok=True)


def apply_metadata_fixes(
    tracks_by_id: dict[str, Track],
    issues: list[MetadataAuditIssue],
    *,
    backup_root: Path | None = None,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> MetadataFixResult:
    changes_by_track: dict[str, dict[str, str]] = defaultdict(dict)
    for issue in issues:
        if not issue.fixable or issue.field not in EASY_TAG_KEYS:
            continue
        if issue.track_id not in tracks_by_id:
            continue
        changes_by_track[issue.track_id][issue.field] = issue.suggested_value

    jobs = [
        (tracks_by_id[track_id], changes)
        for track_id, changes in changes_by_track.items()
    ]
    jobs.sort(
        key=lambda item: (
            item[0].relative_folder.casefold(),
            item[0].filename.casefold(),
        )
    )
    updated_files = 0
    backup_files = 0
    failures: list[MetadataFixFailure] = []
    stopped = False
    for index, (track, changes) in enumerate(jobs, start=1):
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        try:
            backup_created = _write_verified_copy(track, changes, backup_root)
            updated_files += 1
            backup_files += int(backup_created)
        except Exception as exc:
            failures.append(MetadataFixFailure(track.path, str(exc)))
        if progress is not None:
            progress(index, len(jobs), track.filename)
    return MetadataFixResult(
        updated_files=updated_files,
        backup_files=backup_files,
        failures=tuple(failures),
        stopped=stopped,
    )

```

### `discography_analyzer/copying.py`

План копирования и его исполнение: `CopyMode` (FLAT — всё в одну папку / TREE — сохранять структуру), `build_copy_plan` (что и куда; схлопывание вариаций), `execute_copy_plan` с прогрессом и остановкой. Инварианты: источники только читаются, существующие файлы в приёмнике никогда не перезаписываются (`_available_destination` подбирает свободное имя), недопустимые символы имён экранируются, нескопируемое — в папку «Не скопировано».

```python
from __future__ import annotations

import re
import shutil
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .completeness import parse_position
from .models import Track, TrackStatus
from .parsing import artist_set

NOT_COPIED_FOLDER = "Не скопировано"
INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
ProgressCallback = Callable[[int, int, str], None]


class CopyMode(str, Enum):
    FLAT = "flat"
    TREE = "tree"


@dataclass(frozen=True, slots=True)
class RejectedTrack:
    track: Track
    reason: str
    duplicate_of_id: str | None = None


@dataclass(frozen=True, slots=True)
class CopyPlan:
    selected: tuple[Track, ...]
    rejected: tuple[RejectedTrack, ...]

    @property
    def total(self) -> int:
        return len(self.selected) + len(self.rejected)


@dataclass(frozen=True, slots=True)
class CopyFailure:
    source: Path
    destination: Path
    reason: str


@dataclass(frozen=True, slots=True)
class CopyResult:
    copied_selected: int
    copied_rejected: int
    failures: tuple[CopyFailure, ...]
    stopped: bool = False


def _year_value(track: Track) -> int | None:
    for value in (track.year, track.created_at, track.modified_at):
        match = YEAR_RE.search(value or "")
        if match:
            return int(match.group(1))
    return None


def chronological_track_key(track: Track) -> tuple:
    year = _year_value(track)
    disc, _disc_total = parse_position(track.disc_number)
    number, _track_total = parse_position(track.track_number)
    date_text = track.created_at or track.modified_at
    return (
        year is None,
        year or 9999,
        date_text or "9999-99-99 99:99:99",
        track.relative_folder.casefold(),
        disc or 1,
        number is None,
        number or 0,
        track.filename.casefold(),
    )


def artist_grouped_track_key(track: Track) -> tuple:
    """Sort artists A–Z and releases newest-first inside each artist."""
    artist = (
        track.artist.strip()
        or track.album_artist.strip()
        or "Неизвестный исполнитель"
    )
    year = _year_value(track)
    disc, _disc_total = parse_position(track.disc_number)
    number, _track_total = parse_position(track.track_number)
    return (
        artist.casefold(),
        year is None,
        -(year or 0),
        track.album.casefold(),
        disc or 1,
        number is None,
        number or 0,
        track.filename.casefold(),
    )


def order_tracks_for_copy(
    tracks: tuple[Track, ...] | list[Track],
    group_by_artist: bool,
) -> list[Track]:
    if group_by_artist:
        return sorted(tracks, key=artist_grouped_track_key)
    return list(tracks)


def _variation_identity(
    track: Track,
    artists: set[str],
) -> tuple[str, str, float | int] | None:
    duration = track.comparison_duration
    if (
        duration is None
        or not track.base_title
        or not track.variation
        or not artists
    ):
        return None
    return track.base_title, track.variation.casefold(), duration


def build_copy_plan(tracks: list[Track]) -> CopyPlan:
    """Choose an oldest-first, non-repeating subset without guessing on conflicts."""
    ordered = sorted(tracks, key=chronological_track_key)
    by_id = {track.id: track for track in ordered}
    artist_sets = {track.id: artist_set(track.artist) for track in ordered}
    selected: list[Track] = []
    rejected: list[RejectedTrack] = []
    selected_ids: set[str] = set()
    kept_variations: dict[
        tuple[str, str, float | int],
        dict[str, Track],
    ] = defaultdict(dict)

    for track in ordered:
        if track.status == TrackStatus.UNIQUE:
            selected.append(track)
            selected_ids.add(track.id)
            continue

        if track.status == TrackStatus.DUPLICATE:
            duplicate_of = next(
                (
                    by_id[related_id]
                    for related_id in track.related_track_ids
                    if related_id in selected_ids
                    and related_id in by_id
                    and by_id[related_id].status == TrackStatus.DUPLICATE
                ),
                None,
            )
            if duplicate_of is None:
                selected.append(track)
                selected_ids.add(track.id)
            else:
                rejected.append(
                    RejectedTrack(
                        track=track,
                        reason=(
                            "Повторяет ранее выбранный дубликат: "
                            f"{duplicate_of.filename}"
                        ),
                        duplicate_of_id=duplicate_of.id,
                    )
                )
            continue

        if track.status == TrackStatus.VARIATION:
            current_artists = artist_sets[track.id]
            identity = _variation_identity(track, current_artists)
            duplicate_of = None
            if identity is not None:
                kept_by_artist = kept_variations[identity]
                duplicate_of = next(
                    (
                        kept_by_artist[artist]
                        for artist in sorted(current_artists)
                        if artist in kept_by_artist
                    ),
                    None,
                )
            if duplicate_of is None:
                selected.append(track)
                selected_ids.add(track.id)
                if identity is not None:
                    kept_by_artist = kept_variations[identity]
                    for artist in current_artists:
                        kept_by_artist.setdefault(artist, track)
            else:
                rejected.append(
                    RejectedTrack(
                        track=track,
                        reason=(
                            "Повторяет ранее выбранную вариацию: "
                            f"{duplicate_of.filename}"
                        ),
                        duplicate_of_id=duplicate_of.id,
                    )
                )
            continue

        rejected.append(
            RejectedTrack(
                track=track,
                reason="Конфликт: уникальность файла не подтверждена",
            )
        )

    return CopyPlan(tuple(selected), tuple(rejected))


def _clean_component(value: str, fallback: str) -> str:
    cleaned = INVALID_FILENAME_CHARS_RE.sub("_", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    return cleaned or fallback


def _display_year(track: Track) -> str:
    match = YEAR_RE.search(track.year or "")
    return match.group(1) if match else "без даты"


def flat_copy_filename(track: Track, index: int, total: int) -> str:
    sequence_width = max(2, len(str(max(total, 1))))
    sequence = str(index).zfill(sequence_width)
    artist = _clean_component(
        track.artist or track.album_artist,
        "Неизвестный исполнитель",
    )
    album = _clean_component(track.album, "Без альбома")
    title = _clean_component(
        track.title or track.base_title or track.filename_title,
        Path(track.filename).stem or "Без названия",
    )
    track_number, _total = parse_position(track.track_number)
    number_text = str(track_number).zfill(2) if track_number is not None else "00"
    extension = track.path.suffix or Path(track.filename).suffix
    base = (
        f"{sequence} {artist} - {album} ({_display_year(track)})"
        f" - {number_text}-{title}"
    )
    maximum_base_length = max(40, 240 - len(extension))
    if len(base) > maximum_base_length:
        base = base[:maximum_base_length].rstrip(". ")
    return base + extension


def _safe_relative_path(track: Track) -> Path:
    relative = Path(track.relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return Path(track.filename)
    return relative


def _available_destination(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _target_path(
    track: Track,
    destination: Path,
    mode: CopyMode,
    index: int,
    total: int,
) -> Path:
    if mode == CopyMode.FLAT:
        return destination / flat_copy_filename(track, index, total)
    return destination / _safe_relative_path(track)


def execute_copy_plan(
    plan: CopyPlan,
    destination: Path,
    mode: CopyMode,
    *,
    include_rejected: bool = False,
    group_by_artist: bool = False,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> CopyResult:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    rejected_root = destination / NOT_COPIED_FOLDER
    selected_tracks = order_tracks_for_copy(plan.selected, group_by_artist)
    rejected_tracks = order_tracks_for_copy(
        [item.track for item in plan.rejected],
        group_by_artist,
    )
    jobs: list[tuple[Track, bool, int, int]] = [
        (track, False, index, len(selected_tracks))
        for index, track in enumerate(selected_tracks, start=1)
    ]
    if include_rejected:
        jobs.extend(
            (track, True, index, len(rejected_tracks))
            for index, track in enumerate(rejected_tracks, start=1)
        )

    copied_selected = 0
    copied_rejected = 0
    failures: list[CopyFailure] = []
    stopped = False
    total_jobs = len(jobs)
    for done, (track, is_rejected, index, group_total) in enumerate(jobs, start=1):
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        root = rejected_root if is_rejected else destination
        target = _target_path(track, root, mode, index, group_total)
        target = _available_destination(target)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(track.path, target)
            if is_rejected:
                copied_rejected += 1
            else:
                copied_selected += 1
        except OSError as exc:
            failures.append(
                CopyFailure(
                    source=track.path,
                    destination=target,
                    reason=str(exc),
                )
            )
        if progress is not None:
            progress(done, total_jobs, track.filename)

    return CopyResult(
        copied_selected=copied_selected,
        copied_rejected=copied_rejected,
        failures=tuple(failures),
        stopped=stopped,
    )

```

### `discography_analyzer/exporter.py`

Экспорт XLSX через openpyxl: 5 листов — «Все треки», «Только дубликаты», «Матрица дубликатов» (папки × названия), «Сводка по папкам», «Аудит метаданных». Стили: заливки по статусам, шрифты, границы, автоподбор ширины; общие неизменяемые объекты стилей и явная адресация `sheet.cell(row, col)` — экспорт линеен по числу строк (после фикса аудита O(n²) убран). `_safe()` вырезает запрещённые для XLSX управляющие символы (`ILLEGAL_CHARACTERS_RE` из openpyxl) до защиты от формул — один `\x01` в теге не обрывает сохранение всего отчёта. Запись через временный файл + `os.replace`; формулы защищены апострофом.

```python
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .audit_models import AuditSeverity, MetadataAuditIssue
from .constants import DEFAULT_REPORT_COLORS, EXPORT_COLUMNS
from .models import Track, TrackStatus

ORANGE = "E97824"
DARK_ORANGE = "C85A0A"
WARM_WHITE = "FFFDF9"
LIGHT_ORANGE = "FFF0E3"
GRAPHITE = "4B5158"
METAL = "D1D5DB"
TEXT = "2F3439"
MUTED = "737980"
BLUE = "E2EFFB"
BLUE_DARK = "2F75B5"
GREEN = "E5F3E8"
GREEN_DARK = "2E7D32"
CORAL = "F8DFDA"
CORAL_DARK = "A9473E"
ROW_BORDER = Side(style="thin", color="E2DED8")
HEADER_BORDER = Side(style="medium", color=ORANGE)
DATA_ROW_HEIGHT = 17.25
HEADER_ROW = 4
DATA_START_ROW = 5

# openpyxl style objects are immutable and interned per workbook, so sharing
# one instance across thousands of cells is both safe and much cheaper than
# allocating a new Font/Border/Alignment for every cell.
DATA_FONT = Font(color=TEXT, size=9)
DATA_BORDER = Border(bottom=ROW_BORDER)
DATA_ALIGNMENT = Alignment(vertical="center")
CENTER_ALIGNMENT = Alignment(horizontal="center", vertical="center")
_FILL_CACHE: dict[str, PatternFill] = {}


def _fill(color: str) -> PatternFill:
    fill = _FILL_CACHE.get(color)
    if fill is None:
        fill = _FILL_CACHE[color] = PatternFill("solid", fgColor=color)
    return fill


def _safe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    # One control character in any tag must not abort the whole report:
    # openpyxl raises IllegalCharacterError for them.
    value = ILLEGAL_CHARACTERS_RE.sub("", value)
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _color(value: str | None, fallback: str) -> str:
    normalized = (value or "").lstrip("#").upper()
    if len(normalized) == 6 and all(
        character in "0123456789ABCDEF" for character in normalized
    ):
        return normalized
    return fallback


def _status_colors(colors: dict[str, str]) -> dict[str, str]:
    return {
        status: _color(
            colors.get(status),
            DEFAULT_REPORT_COLORS.get(status, WARM_WHITE),
        )
        for status in DEFAULT_REPORT_COLORS
    }


def _summary_text(tracks: list[Track]) -> str:
    counts = Counter(track.status for track in tracks)
    issue_count = len(
        {track.collection_issue_id for track in tracks if track.collection_issue_id}
    )
    return (
        f"Файлов: {len(tracks)}  ·  "
        f"Уникальных: {counts[TrackStatus.UNIQUE]}  ·  "
        f"Дубликатов: {counts[TrackStatus.DUPLICATE]}  ·  "
        f"Вариаций: {counts[TrackStatus.VARIATION]}  ·  "
        f"Конфликтов: {counts[TrackStatus.CONFLICT]}  ·  "
        f"Предупреждений по комплектам: {issue_count}"
    )


def _prepare_sheet(
    sheet,
    title: str,
    subtitle: str,
    headers: list[str],
    *,
    freeze_panes: str = "A5",
    tab_color: str = ORANGE,
) -> None:
    last_column = len(headers)
    last_letter = get_column_letter(last_column)
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.tabColor = tab_color
    sheet.freeze_panes = freeze_panes
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = "1:4"
    sheet.auto_filter.ref = f"A{HEADER_ROW}:{last_letter}{HEADER_ROW}"

    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_column)
    title_cell = sheet.cell(1, 1, title)
    title_cell.fill = PatternFill("solid", fgColor=ORANGE)
    title_cell.font = Font(color="FFFFFF", bold=True, size=15)
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    sheet.row_dimensions[1].height = 28
    for column in range(1, last_column + 1):
        sheet.cell(1, column).fill = PatternFill("solid", fgColor=ORANGE)

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_column)
    subtitle_cell = sheet.cell(2, 1, subtitle)
    subtitle_cell.fill = PatternFill("solid", fgColor=LIGHT_ORANGE)
    subtitle_cell.font = Font(color=MUTED, italic=True, size=9)
    subtitle_cell.alignment = Alignment(horizontal="left", vertical="center")
    sheet.row_dimensions[2].height = 19
    for column in range(1, last_column + 1):
        sheet.cell(2, column).fill = PatternFill("solid", fgColor=LIGHT_ORANGE)

    sheet.row_dimensions[3].height = 7
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(HEADER_ROW, column, header)
        cell.fill = PatternFill("solid", fgColor=GRAPHITE)
        cell.font = Font(color="FFFFFF", bold=True, size=9)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(bottom=HEADER_BORDER)
    sheet.row_dimensions[HEADER_ROW].height = 22


def _style_data_row(
    sheet,
    row_number: int,
    column_count: int,
    fill_color: str = WARM_WHITE,
) -> None:
    # Address cells explicitly: ``sheet[row_number]`` asks openpyxl for
    # ``max_column``, which scans every cell of the sheet and turns row
    # styling into an O(rows²) operation on large reports.
    sheet.row_dimensions[row_number].height = DATA_ROW_HEIGHT
    fill = _fill(fill_color)
    for column in range(1, column_count + 1):
        cell = sheet.cell(row_number, column)
        cell.fill = fill
        cell.font = DATA_FONT
        cell.border = DATA_BORDER
        cell.alignment = DATA_ALIGNMENT


def _fit_columns(
    sheet,
    *,
    header_row: int = HEADER_ROW,
    maximum: int = 48,
    minimum: int = 10,
) -> None:
    # ``max_row``/``max_column`` are full scans in openpyxl; evaluate them once.
    last_row = sheet.max_row
    last_column = sheet.max_column
    for column in range(1, last_column + 1):
        length = len(str(sheet.cell(header_row, column).value or ""))
        for row in range(header_row + 1, last_row + 1):
            value = sheet.cell(row, column).value
            if value is not None:
                line_lengths = [len(part) for part in str(value).splitlines()]
                length = max(length, max(line_lengths, default=0))
        sheet.column_dimensions[get_column_letter(column)].width = min(
            max(length + 2, minimum),
            maximum,
        )


def _finish_table(sheet) -> None:
    last_letter = get_column_letter(sheet.max_column)
    sheet.auto_filter.ref = (
        f"A{HEADER_ROW}:{last_letter}{max(sheet.max_row, HEADER_ROW)}"
    )


def _write_track_sheet(
    workbook: Workbook,
    name: str,
    tracks: list[Track],
    fields: list[str],
    colors: dict[str, str],
) -> None:
    sheet = workbook.create_sheet(name)
    headers = ["№"] + [EXPORT_COLUMNS[field][0] for field in fields]
    _prepare_sheet(sheet, name, _summary_text(tracks), headers)
    status_colors = _status_colors(colors)
    warning_column = (
        fields.index("collection_warning") + 2
        if "collection_warning" in fields
        else None
    )
    warning_font = Font(color=CORAL_DARK, bold=True, size=9)
    for number, track in enumerate(tracks, start=1):
        row_number = DATA_START_ROW + number - 1
        values = [number] + [_safe(value) for value in track.table_row(fields)]
        for column, value in enumerate(values, start=1):
            sheet.cell(row_number, column, value)
        _style_data_row(
            sheet,
            row_number,
            len(headers),
            status_colors.get(track.status.value, WARM_WHITE),
        )
        sheet.cell(row_number, 1).alignment = CENTER_ALIGNMENT
        if warning_column and track.collection_warning:
            warning_cell = sheet.cell(row_number, warning_column)
            warning_cell.fill = _fill(CORAL)
            warning_cell.font = warning_font

    sheet.column_dimensions["A"].width = 7
    _fit_columns(sheet)
    _finish_table(sheet)


def _write_matrix(
    workbook: Workbook,
    tracks: list[Track],
    colors: dict[str, str],
) -> bool:
    attention = [
        track
        for track in tracks
        if track.status
        in (TrackStatus.DUPLICATE, TrackStatus.VARIATION, TrackStatus.CONFLICT)
    ]
    if not attention:
        return False
    folders = sorted({track.relative_folder for track in attention}, key=str.casefold)
    titles = sorted({track.base_title for track in attention}, key=str.casefold)
    sheet = workbook.create_sheet("Матрица дубликатов")
    headers = ["Базовое имя", *folders]
    _prepare_sheet(
        sheet,
        "Матрица дубликатов и вариаций",
        (
            f"Связанных файлов: {len(attention)}  ·  "
            f"Названий: {len(titles)}  ·  Папок: {len(folders)}"
        ),
        headers,
        freeze_panes="B5",
        tab_color=BLUE_DARK,
    )
    status_colors = _status_colors(colors)
    cells: dict[tuple[str, str], list[tuple[TrackStatus, str]]] = defaultdict(list)
    for track in attention:
        if track.status == TrackStatus.VARIATION:
            marker = f"Вариация: {track.variation or 'версия'} — {track.filename}"
        elif track.status == TrackStatus.CONFLICT:
            marker = f"Конфликт — {track.filename}"
        else:
            marker = f"Дубликат — {track.filename}"
        cells[(track.base_title, track.relative_folder)].append(
            (track.status, marker)
        )
    title_font = Font(color=TEXT, bold=True, size=9)
    for offset, title in enumerate(titles):
        row_number = DATA_START_ROW + offset
        sheet.cell(row_number, 1, _safe(title))
        _style_data_row(sheet, row_number, len(headers))
        sheet.cell(row_number, 1).fill = _fill(LIGHT_ORANGE)
        sheet.cell(row_number, 1).font = title_font
        for column, folder in enumerate(folders, start=2):
            items = cells.get((title, folder))
            if not items:
                continue
            sheet.cell(
                row_number,
                column,
                _safe("; ".join(marker for _status, marker in items)),
            )
            statuses = {status for status, _marker in items}
            if TrackStatus.CONFLICT in statuses:
                fill_color = status_colors[TrackStatus.CONFLICT.value]
            elif TrackStatus.VARIATION in statuses:
                fill_color = status_colors[TrackStatus.VARIATION.value]
            else:
                fill_color = status_colors[TrackStatus.DUPLICATE.value]
            sheet.cell(row_number, column).fill = _fill(fill_color)

    _fit_columns(sheet, maximum=55, minimum=14)
    _finish_table(sheet)
    return True


def _write_folder_summary(
    workbook: Workbook,
    tracks: list[Track],
    colors: dict[str, str],
) -> bool:
    if not tracks:
        return False
    grouped: dict[str, list[Track]] = defaultdict(list)
    for track in tracks:
        grouped[track.relative_folder].append(track)
    sheet = workbook.create_sheet("Сводка по папкам")
    headers = [
        "Папка",
        "Всего файлов",
        "Уникальных",
        "Дубликатов",
        "Вариаций",
        "Конфликтов",
        "Форматы",
        "Размер (MB)",
        "Проверка комплекта",
    ]
    issue_count = len(
        {track.collection_issue_id for track in tracks if track.collection_issue_id}
    )
    _prepare_sheet(
        sheet,
        "Сводка по папкам",
        (
            f"Папок: {len(grouped)}  ·  Файлов: {len(tracks)}  ·  "
            f"Папок/альбомов с предупреждениями: {issue_count}"
        ),
        headers,
        tab_color=GREEN_DARK,
    )
    status_colors = _status_colors(colors)
    warning_font = Font(color=CORAL_DARK, bold=True, size=9)
    ok_font = Font(color=GREEN_DARK, bold=True, size=9)
    for offset, folder in enumerate(sorted(grouped, key=str.casefold)):
        rows = grouped[folder]
        counts = Counter(track.status for track in rows)
        warnings = " · ".join(
            sorted(
                {
                    track.collection_warning
                    for track in rows
                    if track.collection_warning
                }
            )
        )
        values = [
            _safe(folder),
            len(rows),
            counts[TrackStatus.UNIQUE],
            counts[TrackStatus.DUPLICATE],
            counts[TrackStatus.VARIATION],
            counts[TrackStatus.CONFLICT],
            ", ".join(sorted({track.format for track in rows})),
            round(sum(track.size_mb for track in rows), 2),
            warnings or "Комплект без обнаруженных пропусков",
        ]
        row_number = DATA_START_ROW + offset
        for column, value in enumerate(values, start=1):
            sheet.cell(row_number, column, value)
        _style_data_row(sheet, row_number, len(headers))
        sheet.cell(row_number, 3).fill = _fill(status_colors[TrackStatus.UNIQUE.value])
        sheet.cell(row_number, 4).fill = _fill(
            status_colors[TrackStatus.DUPLICATE.value]
        )
        sheet.cell(row_number, 5).fill = _fill(
            status_colors[TrackStatus.VARIATION.value]
        )
        sheet.cell(row_number, 6).fill = _fill(status_colors[TrackStatus.CONFLICT.value])
        completeness_cell = sheet.cell(row_number, 9)
        completeness_cell.fill = _fill(CORAL if warnings else GREEN)
        completeness_cell.font = warning_font if warnings else ok_font

    counts = Counter(track.status for track in tracks)
    total_row = DATA_START_ROW + len(grouped)
    total_values = [
        "ИТОГО",
        len(tracks),
        counts[TrackStatus.UNIQUE],
        counts[TrackStatus.DUPLICATE],
        counts[TrackStatus.VARIATION],
        counts[TrackStatus.CONFLICT],
        ", ".join(sorted({track.format for track in tracks})),
        round(sum(track.size_mb for track in tracks), 2),
        f"Папок/альбомов с предупреждениями: {issue_count}",
    ]
    for column, value in enumerate(total_values, start=1):
        sheet.cell(total_row, column, value)
    _style_data_row(sheet, total_row, len(headers), LIGHT_ORANGE)
    total_font = Font(color=DARK_ORANGE, bold=True, size=9)
    total_border = Border(top=HEADER_BORDER, bottom=ROW_BORDER)
    for column in range(1, len(headers) + 1):
        cell = sheet.cell(total_row, column)
        cell.font = total_font
        cell.border = total_border

    _fit_columns(sheet, maximum=52)
    _finish_table(sheet)
    return True


def _write_audit_sheet(
    workbook: Workbook,
    issues: list[MetadataAuditIssue],
    tracks_by_id: dict[str, Track],
) -> None:
    sheet = workbook.create_sheet("Аудит метаданных")
    headers = [
        "№",
        "Уровень",
        "Категория",
        "Поле",
        "Описание",
        "Текущее значение",
        "Предложение",
        "Уверенность",
        "Автоисправление",
        "Папка",
        "Файл",
        "Полный путь",
    ]
    counts = Counter(issue.severity for issue in issues)
    subtitle = (
        f"Замечаний: {len(issues)}  ·  "
        f"Ошибок: {counts[AuditSeverity.ERROR]}  ·  "
        f"Предупреждений: {counts[AuditSeverity.WARNING]}  ·  "
        f"Рекомендаций: {counts[AuditSeverity.INFO]}"
    )
    _prepare_sheet(
        sheet,
        "Аудит метаданных",
        subtitle,
        headers,
        tab_color=CORAL_DARK,
    )
    severity_fills = {
        AuditSeverity.ERROR: CORAL,
        AuditSeverity.WARNING: BLUE,
        AuditSeverity.INFO: GREEN,
    }
    severity_fonts = {
        AuditSeverity.ERROR: Font(color=CORAL_DARK, bold=True, size=9),
        AuditSeverity.WARNING: Font(color=BLUE_DARK, bold=True, size=9),
        AuditSeverity.INFO: Font(color=GREEN_DARK, bold=True, size=9),
    }
    fix_font = Font(color=GREEN_DARK, bold=True, size=9)
    for offset, issue in enumerate(issues):
        row_number = DATA_START_ROW + offset
        track = tracks_by_id.get(issue.track_id)
        values = [
            offset + 1,
            issue.severity.value,
            issue.category.value,
            issue.field_label,
            issue.message,
            issue.current_value,
            issue.suggested_value,
            issue.confidence.value,
            "Да, после подтверждения" if issue.safe_fix else "Нет",
            track.relative_folder if track else "",
            track.filename if track else "",
            str(track.path) if track else "",
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row_number, column, _safe(value))
        _style_data_row(
            sheet,
            row_number,
            len(headers),
            severity_fills[issue.severity],
        )
        sheet.cell(row_number, 2).font = severity_fonts[issue.severity]
        if issue.safe_fix:
            fix_cell = sheet.cell(row_number, 9)
            fix_cell.fill = _fill(GREEN)
            fix_cell.font = fix_font
    _fit_columns(sheet, maximum=60, minimum=11)
    sheet.column_dimensions["A"].width = 7
    _finish_table(sheet)


def export_xlsx(
    tracks: list[Track],
    destination: Path,
    selected_sheets: dict[str, bool],
    selected_columns: list[str],
    colors: dict[str, str],
    audit_issues: list[MetadataAuditIssue] | None = None,
) -> Path:
    if not tracks:
        raise ValueError("Нет данных для экспорта")
    fields = [field for field in selected_columns if field in EXPORT_COLUMNS]
    if not fields:
        fields = ["base_title", "status"]
    if not any(selected_sheets.values()):
        selected_sheets = dict(selected_sheets)
        selected_sheets["all"] = True

    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.title = "Отчёт Discography Analyzer"
    workbook.properties.subject = "Анализ локальной музыкальной коллекции"
    workbook.properties.creator = "Discography Analyzer"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True

    if selected_sheets.get("all"):
        _write_track_sheet(workbook, "Все треки", tracks, fields, colors)
    if selected_sheets.get("attention"):
        attention = [
            track
            for track in tracks
            if track.status
            in (TrackStatus.DUPLICATE, TrackStatus.VARIATION, TrackStatus.CONFLICT)
        ]
        if attention:
            _write_track_sheet(
                workbook, "Только дубликаты", attention, fields, colors
            )
    if selected_sheets.get("matrix"):
        _write_matrix(workbook, tracks, colors)
    if selected_sheets.get("folders"):
        _write_folder_summary(workbook, tracks, colors)
    if selected_sheets.get("audit"):
        _write_audit_sheet(
            workbook,
            list(audit_issues or []),
            {track.id: track for track in tracks},
        )

    if not workbook.sheetnames:
        _write_track_sheet(workbook, "Все треки", tracks, fields, colors)
    destination = destination.with_suffix(".xlsx")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.stem}-",
            suffix=".xlsx",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        workbook.save(temporary)
        temporary.replace(destination)
    finally:
        workbook.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination

```

### `discography_analyzer/settings.py`

Настройки приложения: путь по платформам (`%APPDATA%` на Windows, ~/Library на macOS, ~/.config на Linux), загрузка с дефолтами и валидацией маркеров, сохранение; автосохранение UI-состояния.

```python
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
        default_factory=lambda: dict.fromkeys(SUPPORTED_FORMATS, True)
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
    def load(cls, path: Path | None = None) -> AppSettings:
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

```

### `discography_analyzer/ui.py`

Главный класс GUI `DiscographyAnalyzerApp` — самый большой модуль (~2500 строк, tkinter/ttk, без внешних GUI-зависимостей): тёмная/светлая тема, тулбар (анализ/стоп, копирование уникальных, исправления аудита, «Утилиты», настройки, экспорт), дерево треков с группировкой по статусам и связям, фильтр, статистика, инфо-панель с предпросмотром обложки, прогресс-бар с корректной остановкой, диалоги экспорта и настроек, единый `_clear_results()` для сброса состояния. `main()` — сборка окна.

```python
from __future__ import annotations

import contextlib
import io
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk, UnidentifiedImageError

from .audit_dialog import AuditFixDialog
from .audit_models import AuditSeverity, MetadataAuditIssue
from .completeness import parse_position
from .constants import (
    APP_NAME,
    DEFAULT_REPORT_COLORS,
    DEFAULT_VARIATION_MARKERS,
    EXPORT_COLUMNS,
    REPORT_COLOR_CHOICES,
    STATUS_ROW_COLORS_DARK,
    STATUS_ROW_COLORS_LIGHT,
    SUPPORTED_FORMATS,
    TABLE_COLUMNS,
)
from .copy_dialog import UniqueCopyDialog
from .exporter import export_xlsx
from .metadata import MetadataDependencyError, read_embedded_cover
from .models import AlbumCompletenessIssue, AnalysisResult, Track, TrackStatus
from .parsing import validate_markers
from .scanner import (
    AnalysisStopped,
    NoAudioFilesError,
    NoSelectedFormatsError,
    analyze_collection,
)
from .settings import AppSettings

TABLE_FIELD_IDS = [item[0] for item in TABLE_COLUMNS]


def _files_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "файл"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "файла"
    return "файлов"


def _responsive_group_width(viewport_width: int) -> int:
    if viewport_width <= 1:
        return 335
    return min(620, max(335, round(viewport_width * 0.38)))


class DiscographyAnalyzerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = AppSettings.load()
        self.result: AnalysisResult | None = None
        self.track_by_id: dict[str, Track] = {}
        self.visible_tracks: list[Track] = []
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.sort_column: str | None = None
        self.sort_reverse = False
        self.cover_photo: ImageTk.PhotoImage | None = None
        self.group_labels: dict[str, str] = {}
        self.group_members: dict[str, list[str]] = {}
        self.variation_source_ids: set[str] = set()
        self._group_column_width: int | None = None
        self._folder_column_width: int | None = None
        self._column_widths: dict[str, int] = {}
        self._filter_job: str | None = None
        self.current_tab = tk.StringVar(value="all")
        self.filter_var = tk.StringVar()
        self.issue_by_id: dict[str, AlbumCompletenessIssue] = {}
        self.audit_issue_by_id: dict[str, MetadataAuditIssue] = {}
        self.audit_item_track_ids: dict[str, str] = {}

        self.root.title(APP_NAME)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = min(1450, max(640, screen_width - 80))
        window_height = min(900, max(520, screen_height - 100))
        self.root.geometry(f"{window_width}x{window_height}")
        self.root.minsize(min(960, window_width), min(620, window_height))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")

        self._create_variables()
        self._build_ui()
        self._bind_actions()
        self.apply_theme()
        self._reset_progress()
        self._clear_info()
        self.root.after(100, self._poll_events)

    def _create_variables(self) -> None:
        last = self.settings.last_folder if self.settings.remember_folder else ""
        self.folder_var = tk.StringVar(value=last)
        self.include_subfolders_var = tk.BooleanVar(
            value=self.settings.include_subfolders
        )
        self.use_tags_var = tk.BooleanVar(value=self.settings.use_tags)
        self.detect_variations_var = tk.BooleanVar(
            value=self.settings.detect_variations
        )
        self.check_track_gaps_var = tk.BooleanVar(
            value=self.settings.check_track_gaps
        )
        self.folder_tree_mode_var = tk.BooleanVar(
            value=self.settings.folder_tree_mode
        )
        self.dark_theme_var = tk.BooleanVar(value=self.settings.dark_theme)
        self.format_vars = {
            name: tk.BooleanVar(value=self.settings.formats.get(name, True))
            for name in SUPPORTED_FORMATS
        }
        self.progress_percent_var = tk.StringVar(value="0%")
        self.progress_state_var = tk.StringVar(value="Анализ не запущен")
        self.files_count_var = tk.StringVar(value="Файлов: 0")
        self.folders_count_var = tk.StringVar(value="Папок: 0")
        self.variations_count_var = tk.StringVar(value="Вариаций: 0")
        self.shown_count_var = tk.StringVar(value="0 из 0")
        self.statistics_var = tk.StringVar(value="Статистика: —")

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(4, weight=1)

        header = ttk.Frame(self.root, padding=(14, 9), style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="♫", style="BrandIcon.TLabel").grid(
            row=0, column=0, rowspan=2, padx=(0, 10)
        )
        ttk.Label(header, text=APP_NAME, style="BrandTitle.TLabel").grid(
            row=0, column=1, sticky="sw"
        )
        ttk.Label(
            header,
            text="Анализ локальной музыкальной коллекции",
            style="BrandSub.TLabel",
        ).grid(
            row=1, column=1, sticky="nw"
        )
        ttk.Checkbutton(
            header,
            text="Тёмная тема",
            variable=self.dark_theme_var,
            command=self._theme_changed,
            style="Header.TCheckbutton",
        ).grid(row=0, column=2, rowspan=2)

        source = ttk.LabelFrame(self.root, text="Источник", padding=8)
        source.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 7))
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text="Папка").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(source, textvariable=self.folder_var, state="readonly").grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(source, text="Выбрать...", command=self.choose_folder).grid(
            row=0, column=2, padx=8
        )
        ttk.Checkbutton(
            source,
            text="Включать подпапки",
            variable=self.include_subfolders_var,
        ).grid(row=0, column=3)

        workspace = ttk.Frame(self.root)
        workspace.grid(row=2, column=0, sticky="ew", padx=12)
        workspace.columnconfigure(1, weight=1, minsize=500)

        settings_frame = ttk.LabelFrame(
            workspace, text="Настройки анализа", padding=9
        )
        settings_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(settings_frame, text="Форматы:").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        for index, (name, variable) in enumerate(self.format_vars.items()):
            ttk.Checkbutton(settings_frame, text=name, variable=variable).grid(
                row=1, column=index, sticky="w", padx=(0, 8)
            )
        ttk.Checkbutton(
            settings_frame,
            text="Учитывать теги (не только имена файлов)",
            variable=self.use_tags_var,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(5, 0))
        ttk.Checkbutton(
            settings_frame,
            text="Определять вариации (миксы, ремиксы, live)",
            variable=self.detect_variations_var,
        ).grid(row=3, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(
            settings_frame,
            text="Проверять пропуски номеров треков",
            variable=self.check_track_gaps_var,
        ).grid(row=4, column=0, columnspan=4, sticky="w")

        buttons = ttk.Frame(settings_frame)
        buttons.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(7, 4))
        self.start_button = ttk.Button(
            buttons,
            text="Начать анализ",
            command=self.start_analysis,
            style="Accent.TButton",
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            buttons,
            text="Остановить",
            command=self.stop_analysis,
            state="disabled",
            style="Stop.TButton",
        )
        self.stop_button.pack(side="left", padx=6)
        ttk.Button(
            buttons, text="Дополнительно...", command=self.open_advanced_settings
        ).pack(side="left")

        self.progress = ttk.Progressbar(
            settings_frame, maximum=100, mode="determinate", value=0
        )
        self.progress.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(2, 2))
        status_line = ttk.Frame(settings_frame)
        status_line.grid(row=7, column=0, columnspan=4, sticky="ew")
        status_line.columnconfigure(0, weight=1)
        ttk.Label(
            status_line,
            textvariable=self.progress_state_var,
            width=36,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Label(status_line, textvariable=self.progress_percent_var).grid(
            row=0, column=1, sticky="e"
        )
        counters = ttk.Frame(settings_frame)
        counters.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        ttk.Label(counters, textvariable=self.files_count_var).pack(side="left")
        ttk.Label(counters, textvariable=self.folders_count_var).pack(
            side="left", padx=14
        )
        ttk.Label(counters, textvariable=self.variations_count_var).pack(side="left")

        info_frame = ttk.LabelFrame(
            workspace, text="Информация о выбранном треке", padding=7
        )
        info_frame.grid(row=0, column=1, sticky="nsew")
        info_frame.columnconfigure(0, weight=1, minsize=250)
        info_frame.rowconfigure(0, weight=1)
        info_holder = ttk.Frame(info_frame)
        info_holder.grid(row=0, column=0, sticky="nsew")
        info_holder.columnconfigure(0, weight=1)
        info_holder.rowconfigure(0, weight=1)
        self.info_text = tk.Text(
            info_holder,
            width=36,
            height=13,
            wrap="word",
            state="disabled",
            relief="flat",
        )
        info_scroll = ttk.Scrollbar(
            info_holder, orient="vertical", command=self.info_text.yview
        )
        self.info_text.configure(yscrollcommand=info_scroll.set)
        self.info_text.grid(row=0, column=0, sticky="nsew")
        info_scroll.grid(row=0, column=1, sticky="ns")
        self.cover_holder = ttk.Frame(info_frame, width=205, height=205)
        self.cover_holder.grid(row=0, column=1, padx=(8, 0), sticky="ne")
        self.cover_holder.grid_propagate(False)
        self.cover_label = tk.Label(
            self.cover_holder,
            text="Обложка не выбрана",
            justify="center",
            anchor="center",
        )
        self.cover_label.grid(row=0, column=0, sticky="nsew")
        self.cover_holder.columnconfigure(0, weight=1)
        self.cover_holder.rowconfigure(0, weight=1)

        toolbar = ttk.Frame(self.root, padding=(12, 7), style="Toolbar.TFrame")
        toolbar.grid(row=3, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        tabs_frame = ttk.Frame(toolbar, style="Toolbar.TFrame")
        tabs_frame.grid(row=0, column=0, sticky="w")
        tabs = (
            ("all", "Все треки"),
            ("duplicates", "Дубликаты"),
            ("variations", "Вариации"),
            ("unique", "Уникальные"),
            ("folders", "По папкам"),
            ("audit", "Аудит"),
        )
        for value, text in tabs:
            ttk.Radiobutton(
                tabs_frame,
                text=text,
                value=value,
                variable=self.current_tab,
                command=self.refresh_table,
                style="Tab.TRadiobutton",
            ).pack(side="left", padx=(0, 4))

        controls = ttk.Frame(toolbar, style="Toolbar.TFrame")
        controls.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        controls.columnconfigure(6, weight=1)
        ttk.Label(controls, text="Показано:", style="Toolbar.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            controls,
            textvariable=self.shown_count_var,
            style="Toolbar.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=(4, 14))
        self.folder_tree_check = ttk.Checkbutton(
            controls,
            text="Древовидный вид",
            variable=self.folder_tree_mode_var,
            command=self._tree_mode_changed,
            state="disabled",
            style="Toolbar.TCheckbutton",
        )
        self.folder_tree_check.grid(row=0, column=2, sticky="w")
        self.expand_tree_button = ttk.Button(
            controls,
            text="Развернуть всё",
            command=lambda: self._set_folder_tree_open(True),
            state="disabled",
        )
        self.expand_tree_button.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.collapse_tree_button = ttk.Button(
            controls,
            text="Свернуть всё",
            command=lambda: self._set_folder_tree_open(False),
            state="disabled",
        )
        self.collapse_tree_button.grid(row=0, column=4, sticky="w", padx=(4, 0))
        ttk.Button(
            controls,
            text="Автоподгонка столбцов",
            command=self.autofit_columns,
        ).grid(row=0, column=5, sticky="w", padx=(4, 0))
        self.utilities_button = ttk.Button(
            controls,
            text="Утилиты",
            command=self._open_utilities,
            style="Accent.TButton",
        )
        self.utilities_button.grid(row=0, column=7, sticky="e", padx=(4, 0))
        ttk.Label(controls, text="Фильтр", style="Toolbar.TLabel").grid(
            row=0, column=8, padx=(12, 5)
        )
        ttk.Entry(controls, textvariable=self.filter_var, width=26).grid(
            row=0, column=9
        )
        ttk.Button(
            controls,
            text="×",
            width=3,
            command=lambda: self.filter_var.set(""),
        ).grid(row=0, column=10, padx=(4, 0))

        table_frame = ttk.Frame(self.root)
        table_frame.grid(row=4, column=0, sticky="nsew", padx=12)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame,
            columns=TABLE_FIELD_IDS,
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("#0", text="Структура папок")
        self.tree.column("#0", width=0, minwidth=0, stretch=False)
        for column_id, heading, width in TABLE_COLUMNS:
            self.tree.heading(
                column_id,
                text=heading,
                command=lambda name=column_id: self.sort_by(name),
            )
            self.tree.column(column_id, width=width, minwidth=55, stretch=False)
        vscroll = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.tree.yview
        )
        hscroll = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")

        bottom = ttk.Frame(self.root, padding=12)
        bottom.grid(row=5, column=0, sticky="ew")
        bottom.columnconfigure(5, weight=1)
        ttk.Button(
            bottom,
            text="Экспорт в XLSX",
            command=self.open_export,
            style="Accent.TButton",
        ).grid(row=0, column=0)
        self.unique_copy_button = ttk.Button(
            bottom,
            text="Копировать уникальные...",
            command=self.open_unique_copy,
            state="disabled",
        )
        self.unique_copy_button.grid(row=0, column=1, padx=(6, 0))
        self.audit_fix_button = ttk.Button(
            bottom,
            text="Исправить замечания...",
            command=self.open_audit_fixes,
            state="disabled",
        )
        self.audit_fix_button.grid(row=0, column=2, padx=(6, 0))
        ttk.Button(
            bottom,
            text="Копировать в буфер",
            command=self.copy_selected,
        ).grid(row=0, column=3, padx=6)
        ttk.Button(bottom, text="Открыть файл", command=self.open_selected_file).grid(
            row=0, column=4
        )
        ttk.Label(bottom, textvariable=self.statistics_var, anchor="e").grid(
            row=0, column=5, sticky="e"
        )

        self.context_menu = tk.Menu(self.root, tearoff=False)
        self.context_menu.add_command(
            label="Открыть файл", command=self.open_selected_file
        )
        self.context_menu.add_command(
            label="Открыть папку", command=self.open_selected_folder
        )
        self.context_menu.add_command(
            label="Полная информация", command=self.open_full_info
        )
        self.context_menu.add_command(
            label="Показать исходный трек", command=self.open_source_track
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Копировать путь", command=self.copy_path)
        self.context_menu.add_command(
            label="Копировать строку", command=self.copy_selected
        )

    def _bind_actions(self) -> None:
        self.filter_var.trace_add("write", lambda *_: self._schedule_filter())
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Button-1>", self._tree_group_click, add="+")
        self.tree.bind("<<TreeviewOpen>>", self._tree_group_opened)
        self.tree.bind("<<TreeviewClose>>", self._tree_group_closed)
        self.tree.bind("<Double-1>", self._tree_double_click)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind(
            "<ButtonRelease-1>",
            self._remember_column_widths,
            add="+",
        )
        self.root.bind("<Control-o>", lambda _event: self.choose_folder())
        self.root.bind("<Control-e>", lambda _event: self.open_export())
        self.root.bind("<F5>", lambda _event: self.start_analysis())

    def _schedule_filter(self) -> None:
        if self._filter_job is not None:
            self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(250, self._run_scheduled_filter)

    def _run_scheduled_filter(self) -> None:
        self._filter_job = None
        self.refresh_table()

    def _remember_group_column_width(self, _event=None) -> None:
        if self.current_tab.get() == "folders":
            return
        if "tree" not in self.tree.cget("show"):
            return
        self.root.after_idle(self._capture_group_column_width)

    def _capture_group_column_width(self) -> None:
        if self.current_tab.get() == "folders":
            return
        if "tree" not in self.tree.cget("show"):
            return
        width = int(self.tree.column("#0", "width"))
        if width >= 260:
            self._group_column_width = width
            self.tree.column(
                "#0",
                width=width,
                minwidth=260,
                stretch=False,
            )

    def _remember_column_widths(self, _event=None) -> None:
        self.root.after_idle(self._capture_column_widths)

    def _capture_column_widths(self) -> None:
        for column_id in TABLE_FIELD_IDS:
            width = int(self.tree.column(column_id, "width"))
            if width >= 55:
                self._column_widths[column_id] = width
                self.tree.column(column_id, width=width, stretch=False)
        if "tree" not in self.tree.cget("show"):
            return
        width = int(self.tree.column("#0", "width"))
        if self.current_tab.get() == "folders":
            if width >= 180:
                self._folder_column_width = width
                self.tree.column("#0", width=width, stretch=False)
        elif width >= 260:
            self._group_column_width = width
            self.tree.column("#0", width=width, stretch=False)

    def _all_tree_items(self) -> list[str]:
        items: list[str] = []
        stack = list(reversed(self.tree.get_children("")))
        while stack:
            item_id = stack.pop()
            items.append(item_id)
            stack.extend(reversed(self.tree.get_children(item_id)))
        return items

    def autofit_columns(self) -> None:
        body_font_name = self.style.lookup("Treeview", "font") or "TkDefaultFont"
        heading_font_name = (
            self.style.lookup("Treeview.Heading", "font") or body_font_name
        )
        try:
            body_font = tkfont.nametofont(body_font_name)
        except tk.TclError:
            body_font = tkfont.nametofont("TkDefaultFont")
        try:
            heading_font = tkfont.nametofont(heading_font_name)
        except tk.TclError:
            heading_font = body_font

        show_tree = "tree" in self.tree.cget("show")
        columns = (["#0"] if show_tree else []) + TABLE_FIELD_IDS
        widths = {
            column_id: heading_font.measure(
                str(self.tree.heading(column_id, "text"))
            )
            + 34
            for column_id in columns
        }
        for item_id in self._all_tree_items():
            if show_tree:
                widths["#0"] = max(
                    widths["#0"],
                    body_font.measure(str(self.tree.item(item_id, "text"))) + 32,
                )
            values = self.tree.item(item_id, "values")
            for index, column_id in enumerate(TABLE_FIELD_IDS):
                if index >= len(values):
                    break
                widths[column_id] = max(
                    widths[column_id],
                    body_font.measure(str(values[index])) + 28,
                )

        for column_id in TABLE_FIELD_IDS:
            width = max(70, widths[column_id])
            self._column_widths[column_id] = width
            self.tree.column(column_id, width=width, stretch=False)
        if show_tree:
            minimum = 180 if self.current_tab.get() == "folders" else 260
            width = max(minimum, widths["#0"])
            if self.current_tab.get() == "folders":
                self._folder_column_width = width
            else:
                self._group_column_width = width
            self.tree.column("#0", width=width, stretch=False)

    def _open_utilities(self) -> None:
        messagebox.showinfo(APP_NAME, "В разработке", parent=self.root)

    def apply_theme(self) -> None:
        dark = self.dark_theme_var.get()
        bg = "#1f2225" if dark else "#eeeae4"
        panel = "#2a2e32" if dark else "#fffdf9"
        field = "#24272a" if dark else "#ffffff"
        toolbar = "#30353a" if dark else "#f7f3ed"
        header = "#3b4147" if dark else "#4b5158"
        fg = "#f4efe8" if dark else "#2f3439"
        border = "#555b61" if dark else "#c9c5bf"
        orange = "#df7724" if dark else "#d96813"
        orange_active = "#f08a35" if dark else "#bf570d"
        orange_soft = "#56371f" if dark else "#fff0e3"
        selected = orange
        selected_fg = "#ffffff"
        disabled_fg = "#858b91" if dark else "#8a8f94"
        stop = "#b85549" if dark else "#bd5548"
        self.root.configure(bg=bg)
        self.root.option_add("*selectBackground", selected)
        self.root.option_add("*selectForeground", selected_fg)
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", fg)
        self.root.option_add("*TCombobox*Listbox.selectBackground", selected)
        self.root.option_add("*TCombobox*Listbox.selectForeground", selected_fg)
        self.style.configure(".", background=bg, foreground=fg)
        self.style.configure("TFrame", background=bg)
        self.style.configure("Header.TFrame", background=header)
        self.style.configure("Toolbar.TFrame", background=toolbar)
        self.style.configure("TLabelframe", background=bg, foreground=fg)
        self.style.configure(
            "TLabelframe.Label",
            background=bg,
            foreground=orange_active if dark else "#9f4608",
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure(
            "BrandIcon.TLabel",
            background=header,
            foreground="#ff9b4a",
            font=("TkDefaultFont", 24, "bold"),
        )
        self.style.configure(
            "BrandTitle.TLabel",
            background=header,
            foreground="#ffffff",
            font=("TkDefaultFont", 15, "bold"),
        )
        self.style.configure(
            "BrandSub.TLabel",
            background=header,
            foreground="#d9dde1",
            font=("TkDefaultFont", 9),
        )
        self.style.configure(
            "Toolbar.TLabel",
            background=toolbar,
            foreground=fg,
        )
        self.style.configure(
            "TButton",
            background=panel,
            foreground=fg,
            bordercolor=border,
            lightcolor=panel,
            darkcolor=border,
            padding=(9, 5),
        )
        self.style.map(
            "TButton",
            background=[
                ("pressed", orange_active),
                ("active", orange_soft),
                ("disabled", bg),
            ],
            foreground=[
                ("pressed", selected_fg),
                ("active", fg),
                ("disabled", disabled_fg),
            ],
            bordercolor=[
                ("focus", orange),
                ("active", orange),
                ("disabled", border),
            ],
        )
        self.style.configure(
            "Accent.TButton",
            background=orange,
            foreground=selected_fg,
            bordercolor=orange_active,
            lightcolor=orange,
            darkcolor=orange_active,
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.map(
            "Accent.TButton",
            background=[
                ("pressed", orange_active),
                ("active", "#ee8a38" if dark else "#eb7d28"),
                ("disabled", border),
            ],
            foreground=[
                ("active", selected_fg),
                ("pressed", selected_fg),
                ("disabled", disabled_fg),
            ],
        )
        self.style.configure(
            "Stop.TButton",
            background=panel,
            foreground=stop,
            bordercolor=stop,
            lightcolor=panel,
            darkcolor=border,
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.map(
            "Stop.TButton",
            background=[("pressed", stop), ("active", stop), ("disabled", bg)],
            foreground=[
                ("pressed", "#ffffff"),
                ("active", "#ffffff"),
                ("disabled", disabled_fg),
            ],
        )
        self.style.configure("TCheckbutton", background=bg, foreground=fg)
        self.style.map(
            "TCheckbutton",
            background=[("active", bg)],
            foreground=[("disabled", disabled_fg), ("active", fg)],
        )
        self.style.configure(
            "Header.TCheckbutton",
            background=header,
            foreground="#f5f1ec",
        )
        self.style.map(
            "Header.TCheckbutton",
            background=[("active", header), ("selected", header)],
            foreground=[
                ("active", "#ffffff"),
                ("selected", "#ffffff"),
                ("disabled", "#aeb3b8"),
            ],
            indicatorcolor=[("selected", orange), ("!selected", "#f4efe8")],
        )
        self.style.configure(
            "Toolbar.TCheckbutton",
            background=toolbar,
            foreground=fg,
        )
        self.style.map(
            "Toolbar.TCheckbutton",
            background=[("active", toolbar), ("selected", toolbar)],
            foreground=[
                ("active", fg),
                ("selected", fg),
                ("disabled", disabled_fg),
            ],
            indicatorcolor=[("selected", orange), ("!selected", field)],
        )
        self.style.configure("TRadiobutton", background=bg, foreground=fg)
        self.style.configure(
            "Tab.TRadiobutton",
            padding=(11, 6),
            background=toolbar,
            foreground=fg,
            bordercolor=border,
            relief="flat",
            font=("TkDefaultFont", 9, "bold"),
        )
        self.style.map(
            "Tab.TRadiobutton",
            background=[
                ("selected", selected),
                ("active", orange_soft),
                ("pressed", orange_active),
            ],
            foreground=[
                ("selected", selected_fg),
                ("active", fg),
                ("pressed", selected_fg),
            ],
            indicatorcolor=[
                ("selected", selected),
                ("!selected", toolbar),
            ],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=field,
            foreground=fg,
            insertcolor=fg,
            selectbackground=selected,
            selectforeground=selected_fg,
            bordercolor=border,
        )
        self.style.map(
            "TEntry",
            fieldbackground=[("readonly", field), ("disabled", panel)],
            foreground=[("readonly", fg), ("disabled", disabled_fg)],
            selectbackground=[("focus", selected)],
            selectforeground=[("focus", selected_fg)],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=field,
            background=panel,
            foreground=fg,
            selectbackground=selected,
            selectforeground=selected_fg,
            bordercolor=border,
            arrowcolor=fg,
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", field)],
            background=[("readonly", panel), ("active", selected)],
            foreground=[("readonly", fg), ("active", selected_fg)],
            selectbackground=[("readonly", selected)],
            selectforeground=[("readonly", selected_fg)],
        )
        self.style.configure(
            "Treeview",
            background=field,
            fieldbackground=field,
            foreground=fg,
            rowheight=23,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
        )
        self.style.map(
            "Treeview",
            background=[("selected", selected)],
            foreground=[("selected", selected_fg)],
        )
        self.style.configure(
            "Treeview.Heading",
            background=header,
            foreground="#ffffff",
            font=("TkDefaultFont", 9, "bold"),
            padding=(7, 5),
            bordercolor=border,
            lightcolor=header,
            darkcolor=header,
        )
        self.style.map(
            "Treeview.Heading",
            background=[("active", orange), ("pressed", orange_active)],
            foreground=[
                ("active", selected_fg),
                ("pressed", selected_fg),
            ],
        )
        self.style.configure(
            "Horizontal.TProgressbar",
            background=orange,
            troughcolor=field,
            bordercolor=border,
            lightcolor=orange,
            darkcolor=orange_active,
        )
        self.info_text.configure(
            bg=field,
            fg=fg,
            insertbackground=fg,
            selectbackground=selected,
            selectforeground=selected_fg,
        )
        self.cover_label.configure(bg=field, fg=fg)
        self.context_menu.configure(
            bg=panel,
            fg=fg,
            activebackground=selected,
            activeforeground=selected_fg,
            disabledforeground=disabled_fg,
        )
        colors = STATUS_ROW_COLORS_DARK if dark else STATUS_ROW_COLORS_LIGHT
        for status, color in colors.items():
            self.tree.tag_configure(status, background=color, foreground=fg)
        group_colors = {
            "GroupDuplicate": ("#6a411f", "#fff5eb")
            if dark
            else ("#f7d7bd", "#71340b"),
            "GroupVariation": ("#29465d", "#eef7ff")
            if dark
            else ("#d7eafb", "#174e78"),
            "GroupConflict": ("#613733", "#fff1ef")
            if dark
            else ("#f4d2cd", "#7a2e27"),
            "GroupRelated": ("#41474d", "#f2f3f4")
            if dark
            else ("#e0e2e4", "#333a40"),
        }
        for tag, (background, foreground) in group_colors.items():
            self.tree.tag_configure(
                tag,
                background=background,
                foreground=foreground,
                font=("TkDefaultFont", 9, "bold"),
            )
        self.tree.tag_configure(
            "Folder",
            background=toolbar,
            foreground=fg,
            font=("TkDefaultFont", 9, "bold"),
        )
        self.tree.tag_configure(
            "FolderIssue",
            background="#613733" if dark else "#f8dfda",
            foreground="#fff1ef" if dark else "#7a2e27",
            font=("TkDefaultFont", 9, "bold"),
        )
        audit_colors = {
            "AuditGroup": (
                "#41474d" if dark else "#e5e7e9",
                "#f5f6f7" if dark else "#2f3439",
            ),
            "AuditError": (
                "#613733" if dark else "#f8dfda",
                "#fff1ef" if dark else "#7a2e27",
            ),
            "AuditWarning": (
                "#29465d" if dark else "#e2effb",
                "#eef7ff" if dark else "#174e78",
            ),
            "AuditInfo": (
                "#294b36" if dark else "#e5f3e8",
                "#effbf2" if dark else "#255f2c",
            ),
        }
        for tag, (background, foreground) in audit_colors.items():
            self.tree.tag_configure(
                tag,
                background=background,
                foreground=foreground,
                font=(
                    "TkDefaultFont",
                    9,
                    "bold" if tag == "AuditGroup" else "normal",
                ),
            )

    def _theme_changed(self) -> None:
        self.apply_theme()
        self.settings.dark_theme = self.dark_theme_var.get()
        self._autosave()

    def _tk_palette(self) -> tuple[str, str, str, str, str]:
        if self.dark_theme_var.get():
            return "#1f2225", "#24272a", "#f4efe8", "#df7724", "#ffffff"
        return "#eeeae4", "#ffffff", "#2f3439", "#d96813", "#ffffff"

    def _style_text_widget(self, widget: tk.Text) -> None:
        _bg, field, fg, selected, selected_fg = self._tk_palette()
        widget.configure(
            bg=field,
            fg=fg,
            insertbackground=fg,
            selectbackground=selected,
            selectforeground=selected_fg,
        )

    def _style_toplevel(self, window: tk.Toplevel) -> None:
        bg, _field, _fg, _selected, _selected_fg = self._tk_palette()
        window.configure(bg=bg)

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Выберите корневую директорию",
            initialdir=self.folder_var.get() or None,
        )
        if selected:
            self.folder_var.set(selected)

    def _reset_progress(self) -> None:
        self.progress["value"] = 0
        self.progress_percent_var.set("0%")
        self.progress_state_var.set("Анализ не запущен")
        self.files_count_var.set("Файлов: 0")
        self.folders_count_var.set("Папок: 0")
        self.variations_count_var.set("Вариаций: 0")

    def _clear_info(self) -> None:
        self._set_text(self.info_text, "Выберите трек в таблице")
        self.cover_photo = None
        self.cover_label.configure(image="", text="Обложка не выбрана")

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def start_analysis(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        folder = Path(self.folder_var.get())
        if not self.folder_var.get() or not folder.is_dir():
            messagebox.showwarning(
                APP_NAME,
                "Пожалуйста, выберите корневую директорию",
                parent=self.root,
            )
            return
        self._clear_results()
        self.filter_var.set("")
        self._reset_progress()
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        selected_formats = [
            name for name, variable in self.format_vars.items() if variable.get()
        ]
        include_subfolders = self.include_subfolders_var.get()
        use_tags = self.use_tags_var.get()
        detect_variations = self.detect_variations_var.get()
        check_track_gaps = self.check_track_gaps_var.get()
        excluded_folders = list(self.settings.excluded_folders)
        variation_markers = list(self.settings.variation_markers)

        def progress(percent: int, state: str, files: int, folders: int, variations: int):
            self.events.put(
                ("progress", percent, state, files, folders, variations)
            )

        def run() -> None:
            try:
                result = analyze_collection(
                    root=folder,
                    include_subfolders=include_subfolders,
                    selected_formats=selected_formats,
                    excluded_folders=excluded_folders,
                    use_tags=use_tags,
                    detect_variations=detect_variations,
                    check_track_gaps=check_track_gaps,
                    variation_markers=variation_markers,
                    stop_event=self.stop_event,
                    progress=progress,
                )
                self.events.put(("result", result))
            except AnalysisStopped:
                self.events.put(("stopped",))
            except (
                NoAudioFilesError,
                NoSelectedFormatsError,
                MetadataDependencyError,
            ) as exc:
                self.events.put(("known_error", str(exc)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def stop_analysis(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.stop_button.configure(state="disabled")
            self.progress_state_var.set("Остановка анализа...")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _, percent, state, files, folders, variations = event
                    self.progress["value"] = percent
                    self.progress_percent_var.set(f"{percent}%")
                    self.progress_state_var.set(state)
                    self.files_count_var.set(f"Файлов: {files}")
                    self.folders_count_var.set(f"Папок: {folders}")
                    self.variations_count_var.set(f"Вариаций: {variations}")
                elif kind == "result":
                    self._analysis_finished(event[1])
                elif kind == "stopped":
                    self._analysis_stopped()
                elif kind == "known_error":
                    self._analysis_failed(event[1], generic=False)
                elif kind == "error":
                    self._analysis_failed(event[1], generic=True)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _restore_buttons(self) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _analysis_finished(self, result: AnalysisResult) -> None:
        self.result = result
        self.track_by_id = {track.id: track for track in result.tracks}
        self.variation_source_ids = {
            track.source_track_id
            for track in result.tracks
            if track.source_track_id
        }
        self.issue_by_id = {issue.id: issue for issue in result.completeness_issues}
        self.audit_issue_by_id = {
            issue.id: issue for issue in result.audit_issues
        }
        self._restore_buttons()
        self.unique_copy_button.configure(state="normal")
        self.refresh_table()
        self._update_statistics()
        self._sync_settings_from_ui()
        self._autosave()

    def _clear_results(self) -> None:
        """Drop the previous analysis from memory and from every widget."""
        self.result = None
        self.track_by_id.clear()
        self.variation_source_ids.clear()
        self.issue_by_id.clear()
        self.audit_issue_by_id.clear()
        self.audit_item_track_ids.clear()
        self.visible_tracks.clear()
        self.tree.delete(*self.tree.get_children())
        self.statistics_var.set("Статистика: —")
        self.shown_count_var.set("0 из 0")
        self.unique_copy_button.configure(state="disabled")
        self.audit_fix_button.configure(state="disabled")
        self._clear_info()

    def _analysis_stopped(self) -> None:
        self._restore_buttons()
        self.progress_state_var.set("Анализ остановлен")
        self._clear_results()

    def _analysis_failed(self, reason: str, generic: bool) -> None:
        self._restore_buttons()
        self.progress_state_var.set("Ошибка анализа")
        self._clear_results()
        title = "Произошла ошибка при анализе" if generic else reason
        detail = f"\n\nПричина: {reason}" if generic and reason else ""
        messagebox.showerror(APP_NAME, title + detail, parent=self.root)

    def refresh_table(self) -> None:
        if not self.result:
            return
        active = self.current_tab.get()
        self.folder_tree_check.configure(
            state="normal" if active == "folders" else "disabled"
        )
        tree_controls_enabled = (
            active == "folders" and self.folder_tree_mode_var.get()
        )
        tree_control_state = "normal" if tree_controls_enabled else "disabled"
        self.expand_tree_button.configure(state=tree_control_state)
        self.collapse_tree_button.configure(state=tree_control_state)
        self.audit_fix_button.configure(
            state=(
                "normal"
                if any(issue.fixable for issue in self.result.audit_issues)
                else "disabled"
            )
        )
        query = self.filter_var.get().strip().casefold()
        tracks = list(self.result.tracks)
        if active == "duplicates":
            tracks = [
                track
                for track in tracks
                if track.status in (TrackStatus.DUPLICATE, TrackStatus.CONFLICT)
            ]
        elif active == "variations":
            tracks = [
                track for track in tracks if track.status == TrackStatus.VARIATION
            ]
        elif active == "unique":
            tracks = [
                track for track in tracks if track.status == TrackStatus.UNIQUE
            ]
        self.group_labels.clear()
        self.group_members.clear()
        self.audit_item_track_ids.clear()
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())

        if active == "audit":
            issues = [
                issue
                for issue in self.result.audit_issues
                if (
                    not query
                    or query in issue.search_text()
                    or (
                        issue.track_id in self.track_by_id
                        and query
                        in self.track_by_id[issue.track_id].search_text()
                    )
                )
            ]
            visible_ids = {issue.track_id for issue in issues}
            self.visible_tracks = [
                track for track in tracks if track.id in visible_ids
            ]
            self._insert_audit_groups(issues)
        elif active == "folders":
            if query:
                tracks = [track for track in tracks if query in track.search_text()]
            if self.sort_column:
                tracks.sort(
                    key=lambda track: self._sort_key(
                        track, self.sort_column or ""
                    ),
                    reverse=self.sort_reverse,
                )
                # Stable second pass keeps the tree hierarchy while preserving
                # the requested order inside each folder.
                tracks.sort(key=lambda track: track.relative_folder.casefold())
            else:
                tracks.sort(key=self._folder_sort_key)
            self.visible_tracks = tracks
            if self.folder_tree_mode_var.get():
                self._insert_folder_tree(tracks)
            else:
                self.tree.configure(show="headings")
                self.tree.column("#0", width=0, minwidth=0, stretch=False)
                for track in tracks:
                    self._insert_track_row("", track)
        else:
            entries, visible_tracks = self._build_relation_groups(tracks, query)
            self.visible_tracks = visible_tracks
            self._insert_relation_groups(entries)

        for item_id in selected:
            if self.tree.exists(item_id):
                self.tree.selection_add(item_id)
        self.shown_count_var.set(
            f"{len(self.visible_tracks)} из {len(self.result.tracks)}"
        )
        self._refresh_headings()

    def _tree_mode_changed(self) -> None:
        self.settings.folder_tree_mode = self.folder_tree_mode_var.get()
        self.refresh_table()
        self._autosave()

    def _set_folder_tree_open(self, opened: bool) -> None:
        if (
            self.current_tab.get() != "folders"
            or not self.folder_tree_mode_var.get()
        ):
            return
        top_level = set(self.tree.get_children(""))
        for item_id in self._all_tree_items():
            self.tree.item(
                item_id,
                open=opened or item_id in top_level,
            )

    def _related_component(self, start_id: str) -> set[str]:
        component: set[str] = set()
        stack = [start_id]
        while stack:
            current = stack.pop()
            if current in component or current not in self.track_by_id:
                continue
            component.add(current)
            stack.extend(self.track_by_id[current].related_track_ids)
        return component

    def _group_representative(
        self, members: list[Track], selected_ids: set[str]
    ) -> Track:
        source_ids = {
            track.source_track_id for track in members if track.source_track_id
        }
        for track in members:
            if track.id in source_ids:
                return track
        selected_members = [track for track in members if track.id in selected_ids]
        priority = {
            TrackStatus.DUPLICATE: 0,
            TrackStatus.CONFLICT: 1,
            TrackStatus.UNIQUE: 2,
            TrackStatus.VARIATION: 3,
        }
        return min(
            selected_members or members,
            key=lambda track: (
                priority[track.status],
                track.base_title.casefold(),
                track.filename.casefold(),
            ),
        )

    def _group_member_sort_key(self, track: Track):
        priority = {
            TrackStatus.UNIQUE: 0,
            TrackStatus.DUPLICATE: 1,
            TrackStatus.CONFLICT: 2,
            TrackStatus.VARIATION: 3,
        }
        return (
            0 if track.id in self.variation_source_ids else 1,
            priority[track.status],
            track.variation.casefold(),
            track.relative_folder.casefold(),
            track.filename.casefold(),
        )

    def _build_relation_groups(
        self, selected_tracks: list[Track], query: str
    ) -> tuple[list[tuple[Track, list[Track]]], list[Track]]:
        selected_ids = {track.id for track in selected_tracks}
        processed: set[str] = set()
        entries: list[tuple[Track, list[Track]]] = []
        visible_selected: list[Track] = []

        for track in selected_tracks:
            if track.id in processed:
                continue
            component_ids = self._related_component(track.id)
            selected_component_ids = component_ids & selected_ids
            processed.update(selected_component_ids)
            members = [
                self.track_by_id[item_id]
                for item_id in component_ids
                if item_id in self.track_by_id
            ]
            members.sort(key=self._group_member_sort_key)
            if query and not any(query in member.search_text() for member in members):
                continue
            selected_members = [
                member for member in members if member.id in selected_component_ids
            ]
            visible_selected.extend(selected_members)
            representative = self._group_representative(members, selected_ids)
            entries.append((representative, members))

        def entry_sort_key(entry: tuple[Track, list[Track]]):
            representative = entry[0]
            if self.sort_column:
                return self._sort_key(
                    representative, self.sort_column or ""
                )
            return (
                representative.base_title.casefold(),
                representative.relative_folder.casefold(),
                representative.filename.casefold(),
            )

        entries.sort(
            key=entry_sort_key,
            reverse=self.sort_reverse if self.sort_column else False,
        )
        return entries, visible_selected

    def _group_kind(self, members: list[Track]) -> tuple[str, str]:
        statuses = {member.status for member in members}
        if TrackStatus.VARIATION in statuses:
            return "Вариация", "GroupVariation"
        if statuses == {TrackStatus.DUPLICATE}:
            return "Дубликаты", "GroupDuplicate"
        if TrackStatus.CONFLICT in statuses:
            return "Конфликт", "GroupConflict"
        return "Связанные файлы", "GroupRelated"

    def _insert_relation_groups(
        self, entries: list[tuple[Track, list[Track]]]
    ) -> None:
        self.tree.configure(show=("tree", "headings"))
        self.tree.heading("#0", text="Группы и файлы")
        width = self._group_column_width
        if width is None:
            width = _responsive_group_width(self.tree.winfo_width())
        self.tree.column(
            "#0",
            width=width,
            minwidth=260,
            stretch=False,
        )
        for representative, members in entries:
            if len(members) == 1:
                self._insert_track_row("", representative)
                continue
            group_kind, group_tag = self._group_kind(members)
            group_id = "group::" + min(member.id for member in members)
            base_title = representative.base_title or representative.filename_title
            count = len(members)
            label = f"{group_kind}: {base_title} · {count} {_files_word(count)}"
            folders = {member.relative_folder for member in members}
            variations = sorted(
                {member.variation for member in members if member.variation}
            )
            warnings = sorted(
                {
                    member.collection_warning
                    for member in members
                    if member.collection_warning
                }
            )
            self.tree.insert(
                "",
                "end",
                iid=group_id,
                text=f"[+] {label}",
                values=self._row_values(
                    status=f"{group_kind} · {len(members)}",
                    base_title=base_title,
                    variation=", ".join(variations) or "—",
                    relation="Нажмите [+], чтобы показать связанные файлы",
                    collection_warning="; ".join(warnings) or "—",
                    relative_folder=(
                        next(iter(folders))
                        if len(folders) == 1
                        else f"{len(folders)} папки"
                    ),
                ),
                tags=(group_tag,),
                open=False,
            )
            self.group_labels[group_id] = label
            self.group_members[group_id] = [member.id for member in members]
            for member in members:
                self._insert_track_row(group_id, member)

    def _insert_audit_groups(
        self,
        issues: list[MetadataAuditIssue],
    ) -> None:
        grouped: dict[str, list[MetadataAuditIssue]] = {}
        for issue in issues:
            grouped.setdefault(issue.track_id, []).append(issue)
        ordered_ids = sorted(
            grouped,
            key=lambda track_id: (
                self.track_by_id[track_id].relative_folder.casefold(),
                self.track_by_id[track_id].filename.casefold(),
            )
            if track_id in self.track_by_id
            else ("", ""),
        )
        if self.sort_column:
            def audit_sort_key(track_id: str):
                track = self.track_by_id.get(track_id)
                first = min(
                    grouped[track_id],
                    key=lambda issue: (
                        issue.severity.order,
                        issue.category.value,
                        issue.field,
                    ),
                )
                audit_values = {
                    "status": first.severity.order,
                    "base_title": first.category.value.casefold(),
                    "variation": first.field_label.casefold(),
                    "relation": first.current_value.casefold(),
                    "collection_warning": first.message.casefold(),
                    "artist": first.confidence.value.casefold(),
                }
                if self.sort_column in audit_values:
                    return audit_values[self.sort_column]
                if track is None:
                    return ""
                return self._sort_key(track, self.sort_column or "")

            ordered_ids.sort(
                key=audit_sort_key,
                reverse=self.sort_reverse,
            )
        self.tree.configure(show=("tree", "headings"))
        self.tree.heading("#0", text="Файлы и замечания")
        width = self._group_column_width
        if width is None:
            width = _responsive_group_width(self.tree.winfo_width())
        self.tree.column("#0", width=width, minwidth=260, stretch=False)
        for track_id in ordered_ids:
            track = self.track_by_id.get(track_id)
            if track is None:
                continue
            track_issues = sorted(
                grouped[track_id],
                key=lambda issue: (
                    issue.severity.order,
                    issue.category.value,
                    issue.field,
                ),
            )
            errors = sum(
                issue.severity == AuditSeverity.ERROR
                for issue in track_issues
            )
            warnings = sum(
                issue.severity == AuditSeverity.WARNING
                for issue in track_issues
            )
            safe_fixes = sum(issue.safe_fix for issue in track_issues)
            count = len(track_issues)
            label = f"{track.filename} · {count} замечаний"
            group_id = f"audit-group::{track.id}"
            self.tree.insert(
                "",
                "end",
                iid=group_id,
                text=f"[+] {label}",
                values=self._row_values(
                    status=f"Ошибок {errors} · предупреждений {warnings}",
                    base_title=track.album or track.base_title,
                    variation=f"Безопасных исправлений: {safe_fixes}",
                    relation="Нажмите [+], чтобы показать замечания",
                    relative_folder=track.relative_folder,
                    filename=track.filename,
                    artist=track.artist,
                ),
                tags=("AuditGroup",),
                open=False,
            )
            self.group_labels[group_id] = label
            self.group_members[group_id] = [track.id]
            self.audit_item_track_ids[group_id] = track.id
            for issue in track_issues:
                child_id = f"audit-issue::{issue.id}"
                relation = issue.current_value
                if issue.suggested_value:
                    relation = (
                        f"{issue.current_value or '—'} → "
                        f"{issue.suggested_value}"
                    )
                self.tree.insert(
                    group_id,
                    "end",
                    iid=child_id,
                    text=issue.message,
                    values=self._row_values(
                        status=issue.severity.decorated,
                        base_title=issue.category.value,
                        variation=issue.field_label,
                        relation=relation or "—",
                        collection_warning=issue.message,
                        relative_folder=track.relative_folder,
                        filename=track.filename,
                        artist=issue.confidence.value,
                    ),
                    tags=(f"Audit{issue.severity.name.title()}",),
                )
                self.audit_item_track_ids[child_id] = track.id

    def _set_group_label(self, item_id: str, opened: bool) -> None:
        label = self.group_labels.get(item_id)
        if label and self.tree.exists(item_id):
            self.tree.item(item_id, text=f"{'[-]' if opened else '[+]'} {label}")

    def _tree_group_click(self, event):
        item_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if item_id not in self.group_labels or column != "#0":
            return None
        opened = not bool(self.tree.item(item_id, "open"))
        self.tree.item(item_id, open=opened)
        self._set_group_label(item_id, opened)
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        return "break"

    def _tree_group_opened(self, _event=None) -> None:
        item_id = self.tree.focus()
        if item_id in self.group_labels:
            self.root.after_idle(
                lambda: self._set_group_label(
                    item_id, bool(self.tree.item(item_id, "open"))
                )
            )

    def _tree_group_closed(self, _event=None) -> None:
        item_id = self.tree.focus()
        if item_id in self.group_labels:
            self.root.after_idle(lambda: self._set_group_label(item_id, False))

    def _tree_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id in self.group_labels:
            return "break"
        self.open_selected_file()
        return None

    def _folder_sort_key(self, track: Track):
        disc, _disc_total = parse_position(track.disc_number)
        number, _track_total = parse_position(track.track_number)
        return (
            track.relative_folder.casefold(),
            disc or 1,
            number is None,
            number or 0,
            track.base_title.casefold(),
            track.filename.casefold(),
        )

    def _insert_track_row(self, parent: str, track: Track) -> None:
        values = track.table_row(TABLE_FIELD_IDS)
        number, _total = parse_position(track.track_number)
        tree_text = f"{number:02d} · {track.filename}" if number else track.filename
        self.tree.insert(
            parent,
            "end",
            iid=track.id,
            text=tree_text,
            values=values,
            tags=(track.status.value,),
        )

    def _row_values(self, **values: str) -> list[str]:
        return [values.get(column[0], "") for column in TABLE_COLUMNS]

    def _folder_parts(self, relative_folder: str) -> tuple[str, ...]:
        if relative_folder == "(корень)":
            return ()
        return tuple(part for part in Path(relative_folder).parts if part not in (".", ""))

    def _insert_folder_tree(self, tracks: list[Track]) -> None:
        if not self.result:
            return
        self.tree.configure(show=("tree", "headings"))
        self.tree.column(
            "#0",
            width=self._folder_column_width or 285,
            minwidth=180,
            stretch=False,
        )
        root_id = "folder-root::node"
        root_name = self.result.root.name or str(self.result.root)
        self.tree.insert(
            "",
            "end",
            iid=root_id,
            text=f"📁 {root_name}",
            values=self._row_values(status=f"Папка · {len(tracks)} файлов"),
            tags=("Folder",),
            open=True,
        )
        folder_ids: dict[tuple[str, ...], str] = {(): root_id}

        def ensure_folder(parts: tuple[str, ...]) -> str:
            if parts in folder_ids:
                return folder_ids[parts]
            parent_parts = parts[:-1]
            parent = ensure_folder(parent_parts)
            item_id = "folder-path::" + "/".join(parts)
            self.tree.insert(
                parent,
                "end",
                iid=item_id,
                text=f"📁 {parts[-1]}",
                values=self._row_values(status="Папка"),
                tags=("Folder",),
                open=True,
            )
            folder_ids[parts] = item_id
            return item_id

        for track in tracks:
            ensure_folder(self._folder_parts(track.relative_folder))

        visible_ids = {track.id for track in tracks}
        visible_issue_ids = {
            track.collection_issue_id
            for track in tracks
            if track.collection_issue_id
        }
        for issue in self.result.completeness_issues:
            if issue.id not in visible_issue_ids:
                continue
            parent = ensure_folder(self._folder_parts(issue.relative_folder))
            label = issue.album or "Альбом без тега Album"
            if issue.disc > 1:
                label += f" · диск {issue.disc}"
            self.tree.insert(
                parent,
                "end",
                iid=f"issue::{issue.id}",
                text=f"⚠ {label}",
                values=self._row_values(
                    status="⚠ Пропуски",
                    collection_warning=issue.short_text,
                    album=issue.album,
                    relative_folder=issue.relative_folder,
                ),
                tags=("FolderIssue",),
            )
        for track in tracks:
            if track.id not in visible_ids:
                continue
            parent = ensure_folder(self._folder_parts(track.relative_folder))
            self._insert_track_row(parent, track)

    def _sort_key(self, track: Track, column: str):
        numeric = {
            "duration": track.duration_seconds,
            "bitrate": track.bitrate,
            "size_mb": track.size_mb,
            "year": int(track.year[:4]) if track.year[:4].isdigit() else None,
        }
        if column in numeric:
            value = numeric[column]
            return (value is None, value or 0)
        return str(track.table_value(column)).casefold()

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self.refresh_table()

    def _refresh_headings(self) -> None:
        audit_headings = {
            "status": "Уровень",
            "base_title": "Категория",
            "variation": "Поле",
            "relation": "Было → Предложение",
            "collection_warning": "Описание",
            "relative_folder": "Папка",
            "filename": "Файл",
            "artist": "Уверенность",
        }
        for column_id, heading, _width in TABLE_COLUMNS:
            if self.current_tab.get() == "audit":
                heading = audit_headings.get(column_id, heading)
            arrow = ""
            if column_id == self.sort_column:
                arrow = " ▼" if self.sort_reverse else " ▲"
            self.tree.heading(column_id, text=heading + arrow)

    def _update_statistics(self) -> None:
        if not self.result:
            self.statistics_var.set("Статистика: —")
            return
        result = self.result
        self.statistics_var.set(
            "Статистика: "
            f"всего {len(result.tracks)} · "
            f"уникальных {result.count(TrackStatus.UNIQUE)} · "
            f"дубликатов {result.count(TrackStatus.DUPLICATE)} · "
            f"вариаций {result.count(TrackStatus.VARIATION)} · "
            f"конфликтов {result.count(TrackStatus.CONFLICT)} · "
            f"пропущено номеров {result.missing_track_count} "
            f"в {len(result.completeness_issues)} группах · "
            f"аудит: ошибок {result.audit_count(AuditSeverity.ERROR)}, "
            f"предупреждений {result.audit_count(AuditSeverity.WARNING)}, "
            f"рекомендаций {result.audit_count(AuditSeverity.INFO)} · "
            f"папок {result.folders_scanned} · "
            f"{result.total_size_mb:.2f} MB"
        )

    def _selected_track(self) -> Track | None:
        selection = self.tree.selection()
        if not selection:
            return None
        focused = self.tree.focus()
        for track_id in (focused, *selection):
            mapped_id = self.audit_item_track_ids.get(track_id, track_id)
            track = self.track_by_id.get(mapped_id)
            if track is not None:
                return track
        return None

    def _selection_changed(self, _event=None) -> None:
        focused = self.tree.focus()
        if focused.startswith("audit-issue::"):
            audit_issue = self.audit_issue_by_id.get(
                focused.removeprefix("audit-issue::")
            )
            if audit_issue:
                self._show_audit_issue_in_panel(audit_issue)
                return
        if focused.startswith("audit-group::"):
            self._show_audit_group_in_panel(focused)
            return
        if focused in self.group_members:
            self._show_group_in_panel(focused)
            return
        track = self._selected_track()
        if track:
            self._show_track_in_panel(track)
            return
        if focused.startswith("issue::"):
            issue = self.issue_by_id.get(focused.removeprefix("issue::"))
            if issue:
                self._show_issue_in_panel(issue)

    def _show_audit_group_in_panel(self, group_id: str) -> None:
        track_id = group_id.removeprefix("audit-group::")
        track = self.track_by_id.get(track_id)
        if track is None or not self.result:
            return
        issues = [
            issue
            for issue in self.result.audit_issues
            if issue.track_id == track_id
        ]
        lines = [
            "АУДИТ МЕТАДАННЫХ",
            track.filename,
            f"Папка: {track.relative_folder}",
            "",
            "Нажмите [+], чтобы раскрыть замечания.",
            "",
        ]
        for issue in issues:
            lines.append(
                f"• {issue.severity.value}: {issue.field_label} — "
                f"{issue.message}"
            )
        self._set_text(self.info_text, "\n".join(lines))
        self._load_cover(track, self.cover_label, 190)

    def _show_audit_issue_in_panel(self, issue: MetadataAuditIssue) -> None:
        track = self.track_by_id.get(issue.track_id)
        if track is None:
            return
        lines = [
            "АУДИТ МЕТАДАННЫХ",
            f"Уровень: {issue.severity.value}",
            f"Категория: {issue.category.value}",
            f"Поле: {issue.field_label}",
            f"Файл: {track.filename}",
            f"Папка: {track.relative_folder}",
            "",
            issue.message,
        ]
        if issue.current_value:
            lines.extend(["", f"Сейчас: {issue.current_value}"])
        if issue.suggested_value:
            lines.extend(
                [
                    f"Предложение: {issue.suggested_value}",
                    f"Уверенность: {issue.confidence.value}",
                    (
                        "Можно выбрать в окне безопасного исправления."
                        if issue.safe_fix
                        else "Требуется ручная проверка."
                    ),
                ]
            )
        self._set_text(self.info_text, "\n".join(lines))
        self._load_cover(track, self.cover_label, 190)

    def _show_group_in_panel(self, group_id: str) -> None:
        members = [
            self.track_by_id[track_id]
            for track_id in self.group_members.get(group_id, [])
            if track_id in self.track_by_id
        ]
        if not members:
            return
        kind, _tag = self._group_kind(members)
        lines = [
            f"{kind.upper()}",
            self.group_labels.get(group_id, ""),
            "",
            "Нажмите [+] слева от группы, чтобы раскрыть файлы.",
            "",
        ]
        for index, track in enumerate(members, start=1):
            role = (
                "исходный трек"
                if track.id in self.variation_source_ids
                else track.status.value.casefold()
            )
            lines.extend(
                [
                    f"{index}. {track.filename}",
                    f"   Роль: {role}",
                    f"   Папка: {track.relative_folder}",
                    f"   Формат: {track.format}",
                ]
            )
        self._set_text(self.info_text, "\n".join(lines))
        self.cover_photo = None
        self.cover_label.configure(
            image="", text="Выберите файл\nвнутри раскрытой группы"
        )

    def _track_info_text(self, track: Track) -> str:
        source = self.track_by_id.get(track.source_track_id or "")

        def value(item) -> str:
            return str(item) if item not in ("", None) else "—"

        result_lines = [
            "РЕЗУЛЬТАТ АНАЛИЗА",
            f"Статус: {track.status.value}",
            f"Базовое название: {value(track.base_title)}",
            f"Вариация: {value(track.variation)}",
            f"Связь с файлами: {value(track.relation)}",
        ]
        if source:
            result_lines.append(f"Исходный трек: {source.filename}")
        completeness_lines = [
            "\nПРОВЕРКА КОМПЛЕКТА АЛЬБОМА",
            track.collection_warning or "Пропуски по тегам Track # не обнаружены",
        ]
        track_audit_issues = (
            [
                issue
                for issue in self.result.audit_issues
                if issue.track_id == track.id
            ]
            if self.result
            else []
        )
        audit_lines = ["\nАУДИТ МЕТАДАННЫХ"]
        audit_lines.extend(
            [
                (
                    f"{issue.severity.value}: {issue.field_label} — "
                    f"{issue.message}"
                )
                for issue in track_audit_issues
            ]
            or ["Замечаний не обнаружено"]
        )

        file_lines = [
            "\nФАЙЛ",
            f"Имя файла: {track.filename}",
            f"Полный путь: {track.path}",
            f"Относительный путь: {track.relative_path}",
            f"Относительная папка: {track.relative_folder}",
            f"Формат: {track.format}",
            f"Размер: {track.size_bytes} байт ({track.size_mb:.2f} MB)",
            f"Изменён: {value(track.modified_at)}",
            f"Создан: {value(track.created_at)}",
        ]
        tag_lines = [
            "\nОСНОВНЫЕ ТЕГИ И ПАРАМЕТРЫ",
            f"Title: {value(track.title)}",
            f"Artist: {value(track.artist)}",
            f"Album: {value(track.album)}",
            f"Album Artist: {value(track.album_artist)}",
            f"Track #: {value(track.track_number)}",
            f"Disc #: {value(track.disc_number)}",
            f"Year: {value(track.year)}",
            f"Genre: {value(track.genre)}",
            f"Comment: {value(track.comment)}",
            f"Длительность: {value(track.duration_display)}",
            f"Длительность в секундах: {value(track.duration_seconds)}",
            f"Битрейт: {value(track.bitrate_display)}",
            f"Частота дискретизации: {value(track.sample_rate)}",
            f"Разрядность: {value(track.bit_depth)}",
        ]
        technical_values = [
            ("Точная длительность", track.duration_exact),
            ("Битрейт", track.bitrate),
            ("Частота дискретизации", track.sample_rate),
            ("Разрядность", track.bit_depth),
            ("Каналы", track.channels),
            ("Режим каналов", track.channel_mode),
            ("Режим битрейта", track.bitrate_mode),
            ("Кодек", track.codec),
            ("Кодировщик", track.encoder),
            ("Настройки кодировщика", track.encoder_settings),
            ("Версия", track.version),
            ("Слой", track.layer),
            ("Защита", track.protection),
            ("Track Gain", track.track_gain),
            ("Track Peak", track.track_peak),
            ("Album Gain", track.album_gain),
            ("Album Peak", track.album_peak),
        ]
        technical_lines = ["\nТЕХНИЧЕСКАЯ ИНФОРМАЦИЯ"]
        present = [(label, item) for label, item in technical_values if item not in ("", None)]
        technical_lines.extend(
            [f"{label}: {item}" for label, item in present] or ["Нет данных"]
        )
        all_tag_lines = ["\nВСЕ ИМЕЮЩИЕСЯ ТЕГИ"]
        if track.all_tags:
            for key in sorted(track.all_tags, key=str.casefold):
                all_tag_lines.append(f"{key}: {'; '.join(track.all_tags[key])}")
        else:
            all_tag_lines.append("Нет данных")
        if track.cover_size:
            all_tag_lines.append(
                f"Встроенная обложка: {track.cover_mime or 'изображение'}, "
                f"{track.cover_size} байт"
                + (
                    f", {track.cover_width}×{track.cover_height}"
                    if track.cover_width and track.cover_height
                    else ""
                )
            )
        if track.cover_error:
            all_tag_lines.append(
                f"Ошибка встроенной обложки: {track.cover_error}"
            )
        error_lines: list[str] = []
        if track.metadata_errors:
            error_lines = ["\nОШИБКИ ЧТЕНИЯ", *track.metadata_errors]
        return "\n".join(
            result_lines
            + completeness_lines
            + audit_lines
            + file_lines
            + tag_lines
            + technical_lines
            + all_tag_lines
            + error_lines
        )

    def _show_track_in_panel(self, track: Track) -> None:
        self._set_text(self.info_text, self._track_info_text(track))
        self._load_cover(track, self.cover_label, 190)

    def _show_issue_in_panel(self, issue: AlbumCompletenessIssue) -> None:
        lines = [
            "ПРОВЕРКА КОМПЛЕКТА АЛЬБОМА",
            f"Папка: {issue.relative_folder}",
            f"Album: {issue.album or '—'}",
            f"Диск: {issue.disc}",
            f"Найдены номера: {', '.join(map(str, issue.present_numbers))}",
            f"Ожидаемое количество: {issue.expected_total}",
            f"Источник ожидаемого количества: "
            f"{'теги Track # и найденная последовательность' if issue.total_from_tags else 'последний найденный номер'}",
            f"Результат: {issue.short_text}",
        ]
        if issue.unnumbered_files:
            lines.extend(
                [
                    "",
                    "Файлы без номера Track #:",
                    *[f"• {filename}" for filename in issue.unnumbered_files],
                ]
            )
        self._set_text(self.info_text, "\n".join(lines))
        self.cover_photo = None
        self.cover_label.configure(image="", text="Для проверки папки\nобложка не требуется")

    def _load_cover(self, track: Track, label: tk.Label, size: int) -> None:
        data, _mime, error = read_embedded_cover(track.path)
        if not data:
            label.configure(
                image="", text="Обложка не распознана" if error else "Обложка отсутствует"
            )
            if label is self.cover_label:
                self.cover_photo = None
            return
        try:
            image = Image.open(io.BytesIO(data))
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            label.configure(image=photo, text="")
            label.image = photo
            if label is self.cover_label:
                self.cover_photo = photo
        except (UnidentifiedImageError, OSError):
            label.configure(image="", text="Обложка не распознана")

    def _show_context_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        track_id = self.audit_item_track_ids.get(row, row)
        if not row or track_id not in self.track_by_id:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        track = self.track_by_id.get(track_id)
        state = "normal" if track and track.source_track_id else "disabled"
        self.context_menu.entryconfigure("Показать исходный трек", state=state)
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showwarning(APP_NAME, "Файл не найден", parent=self.root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror(
                APP_NAME, f"Не удалось открыть объект.\n\nПричина: {exc}", parent=self.root
            )

    def open_selected_file(self) -> None:
        track = self._selected_track()
        if track:
            self._open_path(track.path)

    def open_selected_folder(self) -> None:
        track = self._selected_track()
        if track:
            self._open_path(track.path.parent)

    def copy_path(self) -> None:
        track = self._selected_track()
        if track:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(track.path))

    def copy_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        lines = [
            "\t".join(str(value) for value in self.tree.item(item_id, "values"))
            for item_id in selection
        ]
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))

    def open_unique_copy(self) -> None:
        if not self.result or not self.result.tracks:
            messagebox.showinfo(
                APP_NAME,
                "Нет данных для копирования. Сначала выполните анализ",
                parent=self.root,
            )
            return
        dialog = UniqueCopyDialog(
            self.root,
            self.result.tracks,
            self.result.root,
        )
        self._style_toplevel(dialog.window)

    def open_audit_fixes(self) -> None:
        if not self.result:
            return
        fixable = [
            issue for issue in self.result.audit_issues if issue.fixable
        ]
        if not fixable:
            messagebox.showinfo(
                APP_NAME,
                (
                    "Нет замечаний, которые программа может исправить "
                    "механически. Остальные результаты требуют ручной проверки."
                ),
                parent=self.root,
            )
            return
        dialog = AuditFixDialog(
            self.root,
            self.result.tracks,
            self.result.audit_issues,
            self.result.root,
            self.start_analysis,
        )
        self._style_toplevel(dialog.window)

    def open_full_info(self) -> None:
        track = self._selected_track()
        if track:
            self._open_info_dialog(track, "Полная информация о треке")

    def open_source_track(self) -> None:
        track = self._selected_track()
        if not track or not track.source_track_id:
            return
        source = self.track_by_id.get(track.source_track_id)
        if source:
            self._open_info_dialog(
                source, f'Исходный трек для “{track.filename}”'
            )

    def _open_info_dialog(self, track: Track, title: str) -> None:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("950x650")
        window.minsize(720, 480)
        window.transient(self.root)
        self._style_toplevel(window)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        holder = ttk.Frame(window, padding=10)
        holder.grid(row=0, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        text = tk.Text(holder, wrap="word", relief="flat")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        text.insert("1.0", self._track_info_text(track))
        text.configure(state="disabled")
        cover = tk.Label(
            holder,
            text="Обложка не выбрана",
            width=35,
            height=18,
            anchor="center",
            justify="center",
        )
        cover.grid(row=0, column=2, sticky="n", padx=(10, 0))
        _bg, field, fg, _selected, _selected_fg = self._tk_palette()
        self._style_text_widget(text)
        cover.configure(bg=field, fg=fg)
        self._load_cover(track, cover, 300)

    def open_advanced_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Дополнительные настройки")
        window.geometry("690x720")
        window.minsize(580, 520)
        window.transient(self.root)
        self._style_toplevel(window)
        window.grab_set()
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        canvas = tk.Canvas(window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, padding=12)
        content_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        content.columnconfigure(0, weight=1)
        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_id, width=event.width),
        )

        ttk.Label(
            content,
            text="Обозначения вариаций (одно на строку)",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w")
        markers_text = tk.Text(content, height=12, wrap="none")
        markers_text.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        markers_text.insert("1.0", "\n".join(self.settings.variation_markers))
        marker_buttons = ttk.Frame(content)
        marker_buttons.grid(row=2, column=0, sticky="w")
        ttk.Button(
            marker_buttons,
            text="+ Добавить",
            command=lambda: markers_text.insert("end", "\nНовая вариация"),
        ).pack(side="left")
        ttk.Button(
            marker_buttons,
            text="Сбросить",
            command=lambda: (
                markers_text.delete("1.0", "end"),
                markers_text.insert("1.0", "\n".join(DEFAULT_VARIATION_MARKERS)),
            ),
        ).pack(side="left", padx=6)

        ttk.Label(
            content, text="Исключаемые папки (по одной на строку)"
        ).grid(row=3, column=0, sticky="w", pady=(14, 0))
        excluded_text = tk.Text(content, height=6, wrap="none")
        excluded_text.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        excluded_text.insert("1.0", "\n".join(self.settings.excluded_folders))
        bg, _field, _fg, _selected, _selected_fg = self._tk_palette()
        canvas.configure(bg=bg)
        self._style_text_widget(markers_text)
        self._style_text_widget(excluded_text)

        ttk.Label(content, text="Цветовая схема XLSX-отчёта").grid(
            row=5, column=0, sticky="w", pady=(14, 4)
        )
        color_frame = ttk.Frame(content)
        color_frame.grid(row=6, column=0, sticky="ew")
        color_names_by_hex = {value: name for name, value in REPORT_COLOR_CHOICES.items()}
        color_vars: dict[str, tk.StringVar] = {}
        for row, status in enumerate(
            ("Уникальный", "Дубликат", "Вариация", "Конфликт")
        ):
            ttk.Label(color_frame, text=status, width=18).grid(
                row=row, column=0, sticky="w", pady=2
            )
            current = self.settings.report_colors.get(
                status, DEFAULT_REPORT_COLORS[status]
            )
            variable = tk.StringVar(
                value=color_names_by_hex.get(current, next(iter(REPORT_COLOR_CHOICES)))
            )
            color_vars[status] = variable
            ttk.Combobox(
                color_frame,
                textvariable=variable,
                values=list(REPORT_COLOR_CHOICES),
                state="readonly",
                width=20,
            ).grid(row=row, column=1, sticky="w", pady=2)

        remember_var = tk.BooleanVar(value=self.settings.remember_folder)
        autosave_var = tk.BooleanVar(value=self.settings.autosave)
        ttk.Checkbutton(
            content, text="Запомнить последнюю папку", variable=remember_var
        ).grid(row=7, column=0, sticky="w", pady=(14, 0))
        ttk.Checkbutton(
            content, text="Автосохранение настроек", variable=autosave_var
        ).grid(row=8, column=0, sticky="w")
        actions = ttk.Frame(content)
        actions.grid(row=9, column=0, sticky="e", pady=(18, 0))

        def save() -> None:
            try:
                markers = validate_markers(
                    markers_text.get("1.0", "end").splitlines()
                )
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=window)
                return
            self.settings.variation_markers = markers
            self.settings.excluded_folders = [
                line.strip()
                for line in excluded_text.get("1.0", "end").splitlines()
                if line.strip()
            ]
            self.settings.report_colors = {
                status: REPORT_COLOR_CHOICES[color_vars[status].get()]
                for status in color_vars
            }
            self.settings.remember_folder = remember_var.get()
            self.settings.autosave = autosave_var.get()
            self._sync_settings_from_ui()
            self._save_settings_with_warning(window)
            window.destroy()

        ttk.Button(actions, text="Сохранить", command=save).pack(side="left")
        ttk.Button(actions, text="Отмена", command=window.destroy).pack(
            side="left", padx=(6, 0)
        )

    def open_export(self) -> None:
        result = self.result
        if result is None or not result.tracks:
            messagebox.showinfo(
                APP_NAME,
                "Нет данных для экспорта. Сначала выполните анализ",
                parent=self.root,
            )
            return
        window = tk.Toplevel(self.root)
        window.title("Экспорт в XLSX")
        window.geometry("720x680")
        window.minsize(620, 560)
        window.transient(self.root)
        self._style_toplevel(window)
        window.grab_set()
        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)
        sheet_frame = ttk.LabelFrame(window, text="Листы отчёта", padding=10)
        sheet_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        sheet_vars = {
            "all": tk.BooleanVar(value=True),
            "attention": tk.BooleanVar(value=True),
            "matrix": tk.BooleanVar(value=True),
            "folders": tk.BooleanVar(value=True),
            "audit": tk.BooleanVar(value=True),
        }
        for index, (key, label) in enumerate(
            (
                ("all", "Все треки"),
                ("attention", "Только дубликаты"),
                ("matrix", "Матрица дубликатов"),
                ("folders", "Сводка по папкам"),
                ("audit", "Аудит метаданных"),
            )
        ):
            ttk.Checkbutton(
                sheet_frame, text=label, variable=sheet_vars[key]
            ).grid(
                row=index // 3,
                column=index % 3,
                padx=(0, 12),
                pady=2,
                sticky="w",
            )

        column_frame = ttk.LabelFrame(window, text="Столбцы", padding=10)
        column_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        column_vars: dict[str, tk.BooleanVar] = {}
        for index, (key, (label, default)) in enumerate(EXPORT_COLUMNS.items()):
            variable = tk.BooleanVar(value=default)
            column_vars[key] = variable
            ttk.Checkbutton(column_frame, text=label, variable=variable).grid(
                row=index // 3, column=index % 3, sticky="w", padx=(0, 20), pady=2
            )
        controls = ttk.Frame(column_frame)
        controls.grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(
            controls,
            text="Выбрать все",
            command=lambda: [var.set(True) for var in column_vars.values()],
        ).pack(side="left")
        ttk.Button(
            controls,
            text="Сбросить",
            command=lambda: [var.set(False) for var in column_vars.values()],
        ).pack(side="left", padx=6)

        destination_frame = ttk.LabelFrame(window, text="Файл", padding=10)
        destination_frame.grid(
            row=2, column=0, sticky="new", padx=12, pady=(6, 12)
        )
        destination_frame.columnconfigure(1, weight=1)
        filename_var = tk.StringVar(
            value=f"discography_report_{date.today().isoformat()}.xlsx"
        )
        ttk.Label(destination_frame, text="Имя файла").grid(row=0, column=0)
        ttk.Entry(destination_frame, textvariable=filename_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )

        def save_as() -> None:
            filename = filename_var.get().strip() or "discography_report.xlsx"
            if not filename.casefold().endswith(".xlsx"):
                filename += ".xlsx"
            chosen = filedialog.asksaveasfilename(
                parent=window,
                title="Сохранить отчёт",
                initialfile=filename,
                defaultextension=".xlsx",
                filetypes=[("Excel Workbook", "*.xlsx")],
            )
            if not chosen:
                return
            try:
                path = export_xlsx(
                    result.tracks,
                    Path(chosen),
                    {key: variable.get() for key, variable in sheet_vars.items()},
                    [key for key, variable in column_vars.items() if variable.get()],
                    dict(self.settings.report_colors),
                    result.audit_issues,
                )
                messagebox.showinfo(
                    APP_NAME, f"Отчёт успешно сохранён:\n{path}", parent=window
                )
                window.destroy()
            except Exception as exc:
                messagebox.showerror(
                    APP_NAME,
                    f"Не удалось сохранить отчёт.\n\nПричина: {exc}",
                    parent=window,
                )

        actions = ttk.Frame(destination_frame)
        actions.grid(row=1, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(actions, text="Сохранить как...", command=save_as).pack(
            side="left"
        )
        ttk.Button(actions, text="Отмена", command=window.destroy).pack(
            side="left", padx=(6, 0)
        )

    def _sync_settings_from_ui(self) -> None:
        self.settings.last_folder = self.folder_var.get()
        self.settings.include_subfolders = self.include_subfolders_var.get()
        self.settings.use_tags = self.use_tags_var.get()
        self.settings.detect_variations = self.detect_variations_var.get()
        self.settings.check_track_gaps = self.check_track_gaps_var.get()
        self.settings.folder_tree_mode = self.folder_tree_mode_var.get()
        self.settings.dark_theme = self.dark_theme_var.get()
        self.settings.formats = {
            name: variable.get() for name, variable in self.format_vars.items()
        }

    def _save_settings_with_warning(self, parent) -> None:
        try:
            self.settings.save()
        except OSError as exc:
            messagebox.showwarning(
                APP_NAME,
                f"Не удалось сохранить настройки.\n\nПричина: {exc}",
                parent=parent,
            )

    def _autosave(self) -> None:
        if self.settings.autosave:
            self._sync_settings_from_ui()
            with contextlib.suppress(OSError):
                self.settings.save()

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
        self._sync_settings_from_ui()
        if self.settings.autosave:
            with contextlib.suppress(OSError):
                self.settings.save()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    DiscographyAnalyzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

```

### `discography_analyzer/copy_dialog.py`

`UniqueCopyDialog` — модальный диалог копирования: выбор приёмника и режима (плоский/дерево), предпросмотр плана, отчёт о результате. Отвечает только за UI — выбор файлов и весь I/O живут в `copying.py`.

```python
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

```

### `discography_analyzer/audit_dialog.py`

`AuditFixDialog` — предпросмотр и применение только явно выбранных механических исправлений тегов: список ишьюсов с галочками, прогресс, итог; сами правки пишет `metadata_writer.py`.

```python
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

```

### `pyproject.toml`

Метаданные пакета (setuptools): имя, версия 1.7.0, зависимости (mutagen/openpyxl/Pillow), entry point `discography-analyzer = ui:main`, `[tool.ruff]` с консервативным набором правил (E/F/W/B/I/UP/SIM/C4/RUF; игноры для длинных русских строк).

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "discography-analyzer"
version = "1.7.0"
description = "Настольный анализатор локальной музыкальной коллекции"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "mutagen>=1.47",
    "openpyxl>=3.1",
    "Pillow>=10.0",
]

[project.scripts]
discography-analyzer = "discography_analyzer.ui:main"

[tool.setuptools.packages.find]
where = ["."]

[tool.ruff]
target-version = "py310"
extend-exclude = [".venv"]

[tool.ruff.lint]
select = ["E", "F", "W", "B", "I", "UP", "SIM", "C4", "RUF"]
ignore = [
    "E501",    # long lines are mostly Russian UI strings
    "RUF001",  # Cyrillic letters in strings/comments are intentional
    "RUF002",
    "RUF003",
    "RUF012",  # mutable class attributes are used deliberately in dialogs
]

[tool.ruff.lint.isort]
known-first-party = ["discography_analyzer"]

```

### `requirements.txt`

Рантайм-зависимости: mutagen ≥1.47 (теги), openpyxl ≥3.1 (XLSX), Pillow ≥10.0 (валидация обложек).

```text
mutagen>=1.47
openpyxl>=3.1
Pillow>=10.0

```

### `build_exe.spec`

Спецификация PyInstaller для portable one-file exe (`Discography_Analyzer_1.7.0.exe`, `console=False`, UPX). tkinter не исключается (это GUI-фреймворк здесь); `collect_submodules` для mutagen (динамическая фабрика форматов), openpyxl и самого пакета. Сборка: `python -m PyInstaller --clean --noconfirm --upx-dir tools/upx/upx-4.2.4-win64 build_exe.spec`.

```python
# -*- mode: python ; coding: utf-8 -*-
"""Build: python -m PyInstaller --clean --noconfirm --upx-dir tools/upx/upx-4.2.4-win64 build_exe.spec

One-file portable .exe for the Discography Analyzer (tkinter GUI, no console).
tkinter is the GUI framework here and MUST NOT be excluded (unlike Qt specs).
"""
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # mutagen.File is a dynamic format factory - bundle every handler.
    hiddenimports=(
        collect_submodules('mutagen')
        + collect_submodules('discography_analyzer')
        + collect_submodules('openpyxl')
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy', 'scipy', 'pandas', 'matplotlib', 'cv2',
        'jupyter', 'IPython', 'setuptools', 'pip', 'test', 'unittest',
        'PySide6', 'PyQt5', 'PyQt6',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='Discography_Analyzer_1.7.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

### `run.bat`

Лаунчер для Windows (cmd): запуск GUI.

```batch
@echo off
py app.py
if errorlevel 1 pause

```

### `run.sh`

Лаунчер для Unix-систем.

```bash
#!/usr/bin/env sh
exec python3 app.py

```

### `.github/workflows/tests.yml`

CI GitHub Actions: матрица Ubuntu/Windows × Python 3.10/3.12, шаги — `ruff check .` и `python -m unittest discover -s tests`. Гарантирует, что оба «полюса» (старый Python 3.10 и Windows-специфика) не ломаются.

```yaml
name: tests

on:
  push:
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ["3.10", "3.12"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dependencies
        run: python -m pip install -r requirements.txt ruff
      - name: Lint
        run: ruff check .
      - name: Unit tests
        run: python -m unittest discover -s tests -v

```

### `.gitignore`

Исключения git: байткод, .venv, dist/, build/, tools/upx/ (портативный упаковщик), логи, тестовый кэш.

```text
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
*.egg-info/
*.egg
dist/
build/

# Virtual environments
.venv/
venv/
env/

# IDE / OS
.idea/
.vscode/
*.swp
.DS_Store
Thumbs.db

# Test / coverage
.pytest_cache/
.coverage
htmlcov/
.tox/

# Project
*.log
tools/upx/
```
