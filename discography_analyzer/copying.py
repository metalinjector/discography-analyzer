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
