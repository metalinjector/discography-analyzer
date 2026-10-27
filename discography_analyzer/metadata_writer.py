from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .audit_models import MetadataAuditIssue
from .fileops import backup_copy, replace_preserving_times, temporary_copy
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


def write_text_tags(path: Path, changes: dict[str, str]) -> None:
    """Write ``changes`` (``EASY_TAG_KEYS`` fields) into ``path`` and read them back.

    Callers pass a temporary copy, never the original file.
    """
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    save_options = _save_options(path)
    audio = mutagen.File(path, easy=True)
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

    verified = mutagen.File(path, easy=True)
    if verified is None or getattr(verified, "tags", None) is None:
        raise ValueError("не удалось повторно прочитать записанные теги")
    for field, expected in changes.items():
        values = _text_values(verified.tags.get(keys[field]))
        if not values or values[0] != expected:
            raise ValueError(
                f"проверка тега {keys[field]} после записи не пройдена"
            )


def _write_verified_copy(
    track: Track,
    changes: dict[str, str],
    backup_root: Path | None,
) -> bool:
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    source = track.path
    temporary = temporary_copy(source, prefix=f".{source.stem}-audit-")
    backup_created = False
    try:
        write_text_tags(temporary, changes)
        if backup_root is not None:
            backup_copy(source, track.root, backup_root)
            backup_created = True
        replace_preserving_times(temporary, source)
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
