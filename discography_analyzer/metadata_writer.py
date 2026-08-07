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
        audio = mutagen.File(temporary, easy=True)
        if audio is None:
            raise ValueError("формат файла не распознан")
        if getattr(audio, "tags", None) is None:
            add_tags = getattr(audio, "add_tags", None)
            if not callable(add_tags):
                raise ValueError("формат не поддерживает создание тегов")
            add_tags()
        for field, value in changes.items():
            key = EASY_TAG_KEYS[field]
            audio[key] = [value]
        audio.save()

        verified = mutagen.File(temporary, easy=True)
        if verified is None or getattr(verified, "tags", None) is None:
            raise ValueError("не удалось повторно прочитать записанные теги")
        for field, expected in changes.items():
            values = _text_values(verified.tags.get(EASY_TAG_KEYS[field]))
            if not values or values[0] != expected:
                raise ValueError(
                    f"проверка тега {EASY_TAG_KEYS[field]} после записи не пройдена"
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
