"""Rewrite the declared Track # total of an album group.

The completeness check can see that a folder's files disagree about their
total (``1/6 … 6/6`` next to ``7/7``). This module turns that observation into
an explicit, reviewable fix: keep every file's own number and write the total
derived from the highest number found in the group, so ``1/6`` becomes ``1/7``.

Nothing here decides *silently*: the caller passes the exact changes a user
selected, and every file goes through the same temp-copy → verify → backup →
replace cycle as the other tag writers.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .completeness import album_group_key, parse_position
from .fileops import backup_copy, replace_preserving_times, temporary_copy
from .metadata import id3_save_options, read_positions
from .models import AlbumCompletenessIssue, Track

try:
    import mutagen
    from mutagen.apev2 import TEXT, APEv2, APEValue
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, TRCK
    from mutagen.mp4 import MP4
except ImportError:  # The GUI provides a friendly dependency message.
    mutagen = None
    TEXT = APEv2 = APEValue = None
    FLAC = None
    ID3 = TRCK = None
    MP4 = None

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class NumberingChange:
    path: Path
    relative_path: str
    number: int
    current: str
    new_total: int

    @property
    def new_value(self) -> str:
        return f"{self.number}/{self.new_total}"


@dataclass(frozen=True, slots=True)
class NumberingPlan:
    changes: tuple[NumberingChange, ...]
    unnumbered: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.changes)

    @property
    def totals(self) -> tuple[int, ...]:
        return tuple(sorted({change.new_total for change in self.changes}))


@dataclass(frozen=True, slots=True)
class NumberingFailure:
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class NumberingResult:
    updated_files: int
    backup_files: int
    failures: tuple[NumberingFailure, ...]
    stopped: bool = False


def plan_numbering_fix(
    tracks: Iterable[Track],
    issues: Iterable[AlbumCompletenessIssue],
) -> NumberingPlan:
    """Build the changes that give every numbered file the group's highest total.

    The target never goes below a total the tags already declare: lowering
    ``12`` to ``10`` would hide tracks that are really missing.
    """
    track_list = list(tracks)
    changes: dict[Path, NumberingChange] = {}
    unnumbered: list[str] = []
    for issue in issues:
        if not issue.inconsistent_totals:
            continue
        key = (
            issue.relative_folder,
            issue.album.strip().casefold(),
            issue.disc,
        )
        group = [track for track in track_list if album_group_key(track) == key]
        numbered: dict[str, tuple[int, str]] = {}
        for track in group:
            number, _total = parse_position(track.track_number)
            if number is None:
                unnumbered.append(track.relative_path)
                continue
            numbered[track.id] = (number, track.track_number)
        if not numbered:
            continue
        highest = max(number for number, _current in numbered.values())
        target = max(highest, max(issue.inconsistent_totals))
        for track in group:
            entry = numbered.get(track.id)
            if entry is None:
                continue
            number, current = entry
            _number, total = parse_position(current)
            if total == target:
                continue
            changes[track.path] = NumberingChange(
                path=track.path,
                relative_path=track.relative_path,
                number=number,
                current=current,
                new_total=target,
            )
    return NumberingPlan(
        changes=tuple(
            sorted(changes.values(), key=lambda change: change.relative_path.casefold())
        ),
        unnumbered=tuple(sorted(set(unnumbered), key=str.casefold)),
    )


def _text_keys(tags, wanted: str, fallback: str) -> str:
    """Prefer the key case already present so a file keeps one tag, not two."""
    # Vorbis tag dicts iterate as (key, value) pairs, so .keys() is required.
    for key in tags.keys():  # noqa: SIM118
        if str(key).casefold() == wanted.casefold():
            return str(key)
    return fallback


def write_total(path: Path, number: int, total: int) -> None:
    """Write ``number/total`` in the format the file actually uses."""
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    audio = mutagen.File(path)
    if audio is None:
        raise ValueError("формат файла не распознан")
    if FLAC is not None and isinstance(audio, FLAC):
        audio[_text_keys(audio, "tracknumber", "tracknumber")] = [str(number)]
        audio[_text_keys(audio, "tracktotal", "tracktotal")] = [str(total)]
        for alias in ("totaltracks", "totaltrack"):
            if any(str(key).casefold() == alias for key in audio.keys()):  # noqa: SIM118
                audio[_text_keys(audio, alias, alias)] = [str(total)]
        audio.save()
        return
    if MP4 is not None and isinstance(audio, MP4):
        if getattr(audio, "tags", None) is None:
            audio.add_tags()
        # mutagen's trkn renderer expects (track, total) pairs.
        audio["trkn"] = [(number, total)]
        audio.save()
        return
    tags = getattr(audio, "tags", None)
    if tags is None:
        add_tags = getattr(audio, "add_tags", None)
        if callable(add_tags):
            add_tags()
            tags = getattr(audio, "tags", None)
    if ID3 is not None and isinstance(tags, ID3):
        tags["TRCK"] = TRCK(encoding=3, text=f"{number}/{total}")
        audio.save(**id3_save_options(tags))
        return
    if APEv2 is not None and isinstance(tags, APEv2):
        track_key = _text_keys(tags, "track", "Track")
        tags[track_key] = APEValue(f"{number}/{total}", TEXT)
        if any(str(key).casefold() == "tracktotal" for key in tags.keys()):  # noqa: SIM118
            total_key = _text_keys(tags, "tracktotal", "TrackTotal")
            tags[total_key] = APEValue(str(total), TEXT)
        audio.save()
        return
    raise ValueError(f"формат {type(audio).__name__} не поддерживается исправлением")


def verify_total(path: Path, number: int, total: int) -> None:
    """Read the written file back with the analysis' own position reader."""
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    raw = mutagen.File(path)
    if raw is None:
        raise ValueError("формат файла не распознан")
    easy = mutagen.File(path, easy=True)
    position, _disc = read_positions(
        getattr(easy, "tags", None),
        getattr(raw, "tags", None),
        raw,
    )
    expected = f"{number}/{total}"
    if position != expected:
        raise ValueError(
            f"проверка нумерации после записи не пройдена: {position} вместо {expected}"
        )


def _rewrite(
    change: NumberingChange,
    root: Path,
    backup_root: Path | None,
) -> bool:
    temporary = temporary_copy(change.path, prefix=f".{change.path.stem}-numbering-")
    try:
        write_total(temporary, change.number, change.new_total)
        verify_total(temporary, change.number, change.new_total)
        backup_created = False
        if backup_root is not None:
            backup_copy(change.path, root, backup_root)
            backup_created = True
        replace_preserving_times(temporary, change.path)
        return backup_created
    finally:
        temporary.unlink(missing_ok=True)


def apply_numbering_fix(
    changes: Iterable[NumberingChange],
    *,
    root: Path,
    backup_root: Path | None = None,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> NumberingResult:
    """Rewrite the selected files, verifying each one before it replaces the original."""
    jobs = list(changes)
    updated_files = 0
    backup_files = 0
    failures: list[NumberingFailure] = []
    stopped = False
    for index, change in enumerate(jobs, start=1):
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        try:
            backup_created = _rewrite(change, root, backup_root)
            updated_files += 1
            backup_files += int(backup_created)
        except Exception as exc:
            failures.append(NumberingFailure(change.path, str(exc)))
        if progress is not None:
            progress(index, len(jobs), change.relative_path)
    return NumberingResult(
        updated_files=updated_files,
        backup_files=backup_files,
        failures=tuple(failures),
        stopped=stopped,
    )
