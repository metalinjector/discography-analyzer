"""Releases: the album (edition) as one entity instead of a list of files.

A release is the folder of an album — its «CD1»/«Disc 2» subfolders included —
together with the Album tag. Everything shown on the «Релизы» tab is derived
from tags the analysis has already read: completeness across all discs, the
release type, the artists and the guests, the label and the barcode, the
sound quality, the cover and the length of the longest path. Nothing here
reads or writes audio files.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .completeness import (
    CONTINUOUS,
    RELEASE_TOTAL,
    ReleaseNumbering,
    parse_position,
    release_key,
    release_numbering,
    track_disc,
)
from .metadata_audit import COMPILATION_ARTISTS, find_folder_cover
from .models import Track, _clock
from .parsing import files_word

# Windows (Explorer, many players) cannot open a path longer than this.
WINDOWS_PATH_LIMIT = 259
# An artist outside the album artists on fewer tracks than this is a guest:
# «Bang Bang» on one track of fourteen does not make the album a duet.
GUEST_SHARE = 0.30
# Without Album Artist the album artists are the names on half the tracks.
ALBUM_ARTIST_SHARE = 0.50

LOSSLESS_FORMATS = {"FLAC", "APE"}
# Display names: «A, B», «A; B», «A & B», «A feat. B», «A (feat. B)».
NAME_SEPARATOR_RE = re.compile(
    r"\s*(?:[,;&()]|\bfeat(?:uring)?\b\.?|\bft\b\.?)\s*", re.IGNORECASE
)
# Raw tag keys: ID3 frames, iTunes freeform atoms and plain Vorbis/APE names
# all end in the same word once the container prefix is dropped.
RAW_KEY_PREFIXES = ("txxx:", "----:com.apple.itunes:", "----:")
ID3_KEY_ALIASES = {"tpub": "label", "tsrc": "isrc", "tcop": "copyright"}
LABEL_KEYS = ("label", "organization", "publisher")
BARCODE_KEYS = ("barcode", "upc", "ean")
ISRC_KEYS = ("isrc",)
RELEASE_TYPE_KEYS = (
    "releasetype",
    "musicbrainz_albumtype",
    "musicbrainz album type",
)
PRIMARY_TYPES = {
    "album": "Album",
    "single": "Single",
    "ep": "EP",
    "broadcast": "Broadcast",
    "other": "Other",
}


class ReleaseStatus(str, Enum):
    COMPLETE = "Полный"
    NO_TOTAL = "Без пропусков"
    INCOMPLETE = "Неполный"
    UNKNOWN = "Не проверить"

    @property
    def order(self) -> int:
        return {
            ReleaseStatus.INCOMPLETE: 0,
            ReleaseStatus.UNKNOWN: 1,
            ReleaseStatus.NO_TOTAL: 2,
            ReleaseStatus.COMPLETE: 3,
        }[self]


@dataclass(slots=True)
class Release:
    id: str
    folder: str  # as Track.relative_folder: relative, or the collection path
    path: Path
    tracks: list[Track]
    album: str
    album_artist: str
    artists: str  # album artists and the regular co-artists, for display
    co_artists: tuple[str, ...]  # on 30 % of the tracks or more, not album artists
    guests: tuple[str, ...]
    compilation: bool
    year: str
    genre: str
    label: str
    barcodes: tuple[str, ...]
    type_name: str
    type_from_tag: bool
    numbering: ReleaseNumbering
    status: ReleaseStatus
    duration: float
    size_bytes: int
    formats: str
    quality: str
    cover_file: str  # a cover image next to the files, "" without one
    cover_path: Path | None
    embedded_covers: int  # tracks with a readable embedded cover
    cover_variants: int  # distinct embedded pictures
    longest_path: int
    # Folders of other releases with the same barcode: one edition, split.
    shared_barcode_folders: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def title(self) -> str:
        """«Irrlicht (1972)» — the label of the release row."""
        return f"{self.album} ({self.year})" if self.year else self.album

    @property
    def found(self) -> int:
        return len(self.tracks)

    @property
    def missing_count(self) -> int:
        return self.numbering.missing_count

    @property
    def disc_count(self) -> int:
        return max(len(self.numbering.discs), self.numbering.disc_total)

    @property
    def counts_text(self) -> str:
        """«9/9», «7/9», «5» without a known total, «18/18 · 2 CD»."""
        expected = self.numbering.expected
        text = (
            f"{self.found}/{expected}"
            if self.numbering.verified and expected
            else str(self.found)
        )
        if self.disc_count > 1:
            text += f" · {self.disc_count} CD"
        return text

    @property
    def status_text(self) -> str:
        if self.status == ReleaseStatus.INCOMPLETE:
            if self.missing_count:
                return f"Не хватает {self.missing_count}"
            absent = self.numbering.absent_discs
            return f"Нет диска {absent[0]}" if len(absent) == 1 else "Нет дисков"
        return self.status.value

    @property
    def type_text(self) -> str:
        """«Album» from RELEASETYPE, «Album *» when estimated."""
        return self.type_name if self.type_from_tag else f"{self.type_name} *"

    @property
    def cover_text(self) -> str:
        parts: list[str] = []
        if self.cover_file:
            parts.append(self.cover_file)
        if self.embedded_covers:
            parts.append(f"встроена {self.embedded_covers}/{self.found}")
        if self.cover_variants > 1:
            parts.append(f"{self.cover_variants} разных")
        return " · ".join(parts) or "нет"

    @property
    def artists_text(self) -> str:
        if not self.guests:
            return self.artists
        return f"{self.artists} · гости: {', '.join(self.guests)}"

    @property
    def notes_text(self) -> str:
        return " · ".join(self.notes) or "—"

    def search_text(self) -> str:
        return "\n".join(
            (
                self.album,
                self.album_artist,
                self.artists,
                *self.guests,
                self.year,
                self.genre,
                self.label,
                *self.barcodes,
                self.type_name,
                self.folder,
                self.status_text,
                *self.notes,
                *(track.title for track in self.tracks),
                *(track.filename for track in self.tracks),
            )
        ).casefold()


def raw_tag_values(track: Track, names: Iterable[str]) -> list[str]:
    """Values of raw tags by name in any container, e.g. BARCODE or TPUB."""
    wanted = {name.casefold() for name in names}
    values: list[str] = []
    for key, items in track.all_tags.items():
        name = key.casefold()
        for prefix in RAW_KEY_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break
        name = ID3_KEY_ALIASES.get(name, name)
        if name not in wanted:
            continue
        for item in items:
            text = " ".join(str(item).split())
            # Binary data and read errors are shown as «<…>» placeholders.
            if text and not text.startswith("<") and text not in values:
                values.append(text)
    return values


def _dominant(values: Iterable[str]) -> str:
    """The most common non-empty value; ties go to the first one seen."""
    counts = Counter(" ".join(value.split()) for value in values if value.strip())
    return counts.most_common(1)[0][0] if counts else ""


def split_names(value: str) -> list[str]:
    """«Jessie J, Ariana Grande & Nicki Minaj» → three display names."""
    names: list[str] = []
    seen: set[str] = set()
    for part in NAME_SEPARATOR_RE.split(value):
        name = " ".join(part.split()).strip(" .")
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    return names


def _track_artist_values(track: Track) -> list[str]:
    values = track.canonical_tags.get("artist") or [track.artist]
    return [value for value in values if value and value.strip()]


def release_artists(
    tracks: list[Track],
) -> tuple[str, str, tuple[str, ...], bool]:
    """(album artist, artists for display, guests, is compilation).

    The album artists come from Album Artist, or — without it — from the
    names found on at least half of the tracks. Another name on at least
    30 % of the tracks is a co-artist and joins the list; on fewer it is a
    guest («Bang Bang» on one track of an album).
    """
    album_artist, artists, _co_artists, guests, compilation = _artist_roles(tracks)
    return album_artist, artists, guests, compilation


def _artist_roles(
    tracks: list[Track],
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], bool]:
    """(album artist, artists for display, co-artists, guests, compilation)."""
    album_artist = _dominant(track.album_artist for track in tracks)
    compilation = any(
        marker in album_artist.casefold() for marker in COMPILATION_ARTISTS
    )
    if compilation:
        return album_artist, album_artist, (), (), True

    display: dict[str, str] = {}
    shares: Counter[str] = Counter()
    order: list[str] = []
    for track in tracks:
        names = {
            name.casefold(): name
            for value in _track_artist_values(track)
            for name in split_names(value)
        }
        for key, name in names.items():
            display.setdefault(key, name)
            shares[key] += 1
            if key not in order:
                order.append(key)
    total = len(tracks) or 1
    if album_artist:
        core = {name.casefold() for name in split_names(album_artist)}
        main = album_artist
    else:
        core = {key for key in order if shares[key] / total >= ALBUM_ARTIST_SHARE}
        main = ", ".join(display[key] for key in order if key in core)
        album_artist = main
    others = [key for key in order if key not in core]
    co_artists = [display[key] for key in others if shares[key] / total >= GUEST_SHARE]
    guests = tuple(display[key] for key in others if shares[key] / total < GUEST_SHARE)
    artists = ", ".join(([main] if main else []) + co_artists)
    return album_artist, artists, tuple(co_artists), guests, False


def release_type(
    tracks: list[Track], expected: int, duration: float
) -> tuple[str, bool]:
    """(type, taken from a tag). Without RELEASETYPE — an estimate.

    The estimate is the rule the normalizer scripts settled on: an album has
    at least 7 tracks or lasts 30 minutes; 4–6 tracks, or up to three tracks
    of 20 minutes and more, are an EP; anything shorter is a single.
    """
    values = [
        part.strip().casefold()
        for track in tracks
        for value in raw_tag_values(track, RELEASE_TYPE_KEYS)
        for part in re.split(r"[;/,]", value)
        if part.strip()
    ]
    primary = next((PRIMARY_TYPES[value] for value in values if value in PRIMARY_TYPES), "")
    if primary:
        secondary = list(
            dict.fromkeys(
                value.title() for value in values if value not in PRIMARY_TYPES
            )
        )
        return (f"{primary} ({', '.join(secondary)})" if secondary else primary), True
    count = max(len(tracks), expected)
    if count >= 7 or duration >= 30 * 60:
        return "Album", False
    if count >= 4 or duration >= 20 * 60:
        return "EP", False
    return "Single", False


def _is_lossless(track: Track) -> bool:
    fmt = track.format.strip().upper()
    return fmt in LOSSLESS_FORMATS or (
        fmt == "M4A" and (track.codec or "").strip().casefold() == "alac"
    )


def track_quality(track: Track) -> str:
    """«44.1/16», «96/24» or «320 kbps» for one file."""
    if _is_lossless(track) and track.sample_rate and track.bit_depth:
        return f"{track.sample_rate / 1000:g}/{track.bit_depth}"
    if track.bitrate:
        return f"{round(track.bitrate / 1000)} kbps"
    return ""


def quality_summary(tracks: list[Track]) -> tuple[str, str]:
    """(formats, quality): «FLAC», «44.1/16» — or per format when mixed."""
    by_format: dict[str, list[Track]] = defaultdict(list)
    for track in tracks:
        by_format[track.format.strip().upper() or "?"].append(track)
    ordered = sorted(by_format.items(), key=lambda item: (-len(item[1]), item[0]))
    parts: list[str] = []
    for name, group in ordered:
        if all(_is_lossless(track) for track in group):
            detail = ", ".join(
                f"{rate / 1000:g}/{depth}"
                for rate, depth in sorted(
                    {
                        (track.sample_rate, track.bit_depth)
                        for track in group
                        if track.sample_rate and track.bit_depth
                    }
                )
            )
        else:
            rates = sorted(
                {round(track.bitrate / 1000) for track in group if track.bitrate}
            )
            detail = ""
            if rates:
                detail = (
                    f"{rates[0]} kbps"
                    if rates[0] == rates[-1]
                    else f"{rates[0]}–{rates[-1]} kbps"
                )
        parts.append((name, detail))
    formats = " + ".join(name for name, _detail in parts)
    if len(parts) == 1:
        return formats, parts[0][1]
    return formats, " · ".join(f"{name} {detail}".strip() for name, detail in parts)


def _numbers_text(numbers: tuple[int, ...], limit: int = 6) -> str:
    text = ", ".join(str(number) for number in numbers[:limit])
    if len(numbers) > limit:
        text += f" и ещё {len(numbers) - limit}"
    return text


def _missing_note(numbering: ReleaseNumbering) -> list[str]:
    notes: list[str] = []
    multi = len(numbering.discs) > 1
    for disc, numbers in numbering.missing:
        if disc == 0:
            notes.append(f"нет № {_numbers_text(numbers)} (сквозная нумерация)")
        elif multi:
            notes.append(f"CD{disc}: нет № {_numbers_text(numbers)}")
        else:
            notes.append(f"нет № {_numbers_text(numbers)}")
    if numbering.absent_discs:
        discs = ", ".join(str(disc) for disc in numbering.absent_discs)
        word = "диска" if len(numbering.absent_discs) == 1 else "дисков"
        notes.append(f"нет {word} {discs}")
    if numbering.unplaced:
        text = f"ещё {numbering.unplaced} по итогу {numbering.expected}"
        if not numbering.absent_discs:
            text += ", диск не определить"
        notes.append(text)
    if numbering.unnumbered:
        notes.append(f"без Track #: {numbering.unnumbered}")
    if numbering.conflicting_totals:
        totals = ", ".join(str(total) for total in numbering.conflicting_totals)
        notes.append(f"итоги расходятся: {totals}")
    return notes


def _status(numbering: ReleaseNumbering) -> ReleaseStatus:
    if numbering.missing_count or numbering.absent_discs:
        return ReleaseStatus.INCOMPLETE
    if not numbering.numbered or numbering.unnumbered:
        return ReleaseStatus.UNKNOWN
    return ReleaseStatus.COMPLETE if numbering.verified else ReleaseStatus.NO_TOTAL


def _sort_tracks(tracks: list[Track]) -> list[Track]:
    def key(track: Track):
        number, _total = parse_position(track.track_number)
        return (
            track_disc(track),
            number is None,
            number or 0,
            track.filename.casefold(),
        )

    return sorted(tracks, key=key)


def _plural(count: int, one: str, few: str, many: str) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def _release_cover(
    path: Path, tracks: list[Track], cache: dict[Path, Path | None]
) -> Path | None:
    """The cover file of the release folder, else of one of its disc folders.

    ``cache`` keeps one directory listing per folder: a «Singles» folder with
    hundreds of single releases is listed once, not once per single.
    """
    for folder in dict.fromkeys((path, *(track.path.parent for track in tracks))):
        if folder not in cache:
            cache[folder] = find_folder_cover(folder)
        if cache[folder] is not None:
            return cache[folder]
    return None


def build_release(
    folder: str,
    tracks: list[Track],
    root: Path,
    release_id: str = "",
    cover_cache: dict[Path, Path | None] | None = None,
) -> Release:
    tracks = _sort_tracks(tracks)
    path = root if folder == str(root) else root / folder
    numbering = release_numbering(tracks)
    album = _dominant(track.album for track in tracks) or (
        path.name or str(path)
    )
    album_artist, artists, co_artists, guests, compilation = _artist_roles(tracks)
    years = [track.year.strip()[:4] for track in tracks if track.year.strip()[:4].isdigit()]
    duration = sum(
        track.comparison_duration
        for track in tracks
        if track.comparison_duration is not None
    )
    type_name, type_from_tag = release_type(tracks, numbering.expected, duration)
    formats, quality = quality_summary(tracks)
    barcodes: list[str] = []
    for track in tracks:
        for value in raw_tag_values(track, BARCODE_KEYS):
            if value not in barcodes:
                barcodes.append(value)
    cover_path = _release_cover(path, tracks, {} if cover_cache is None else cover_cache)
    readable = [
        track.cover_hash for track in tracks if track.cover_hash and not track.cover_error
    ]
    release = Release(
        # Folder + album key: the same release keeps its row (and the
        # selection) when the analysis runs again after a utility.
        id=release_id or f"release::{folder}::{release_key(tracks[0])[1]}",
        folder=folder,
        path=path,
        tracks=tracks,
        album=album,
        album_artist=album_artist,
        artists=artists or album_artist,
        co_artists=co_artists,
        guests=guests,
        compilation=compilation,
        year=_dominant(years),
        genre=_dominant(track.genre for track in tracks),
        label=_dominant(
            value for track in tracks for value in raw_tag_values(track, LABEL_KEYS)
        ),
        barcodes=tuple(barcodes),
        type_name=type_name,
        type_from_tag=type_from_tag,
        numbering=numbering,
        status=_status(numbering),
        duration=duration,
        size_bytes=sum(track.size_bytes for track in tracks),
        formats=formats,
        quality=quality,
        cover_file=cover_path.name if cover_path else "",
        cover_path=cover_path,
        embedded_covers=len(readable),
        cover_variants=len(set(readable)),
        longest_path=max((len(str(track.path)) for track in tracks), default=0),
    )
    release.notes = tuple(_notes(release))
    return release


def _notes(release: Release) -> list[str]:
    notes = _missing_note(release.numbering)
    if len(release.barcodes) > 1:
        notes.append(f"разные издания: {', '.join(release.barcodes)}")
    if release.shared_barcode_folders:
        notes.append(f"то же издание в: {', '.join(release.shared_barcode_folders)}")
    if not release.cover_file and not release.embedded_covers:
        notes.append("нет обложки")
    elif 0 < release.embedded_covers < release.found:
        notes.append(f"обложка встроена не везде ({release.embedded_covers}/{release.found})")
    if release.cover_variants > 1:
        notes.append(f"разные обложки в файлах: {release.cover_variants}")
    if release.longest_path > WINDOWS_PATH_LIMIT:
        notes.append(f"путь {release.longest_path} > {WINDOWS_PATH_LIMIT}")
    return notes


def build_releases(tracks: list[Track], root: Path) -> list[Release]:
    """Every release of the analysed collection, in folder order."""
    groups: dict[tuple[str, str], list[Track]] = defaultdict(list)
    for track in tracks:
        groups[release_key(track)].append(track)
    ordered = sorted(groups.items(), key=lambda item: (item[0][0].casefold(), item[0][1]))
    covers: dict[Path, Path | None] = {}
    releases = [
        build_release(folder, group, root, f"release::{folder}::{album}", covers)
        for (folder, album), group in ordered
    ]
    # One edition in several folders: the barcode names the same release.
    by_barcode: dict[str, list[Release]] = defaultdict(list)
    for release in releases:
        for barcode in release.barcodes:
            by_barcode[barcode].append(release)
    for release in releases:
        others = {
            other.folder
            for barcode in release.barcodes
            for other in by_barcode[barcode]
            if other is not release and other.folder != release.folder
        }
        if others:
            release.shared_barcode_folders = tuple(sorted(others, key=str.casefold))
            release.notes = tuple(_notes(release))
    return releases


def cover_file_matches(release: Release) -> bool | None:
    """Whether the folder cover is the picture embedded in the files.

    ``None`` when there is nothing to compare. Read only when the release is
    opened, so the analysis does not read every cover file of the collection.
    """
    if release.cover_path is None or not release.embedded_covers:
        return None
    hashes = Counter(
        track.cover_hash for track in release.tracks if track.cover_hash and not track.cover_error
    )
    try:
        digest = hashlib.sha256(release.cover_path.read_bytes()).hexdigest()
    except OSError:
        return None
    return digest == hashes.most_common(1)[0][0]


def _numbering_text(numbering: ReleaseNumbering) -> str:
    if numbering.mode == RELEASE_TOTAL:
        return (
            f"по дискам, итог {numbering.expected} — на весь релиз "
            "(так пишет Qobuz и другие магазины)"
        )
    if numbering.mode == CONTINUOUS:
        return "сквозная по всем дискам"
    return "по дискам" if len(numbering.discs) > 1 else "обычная"


def release_card_text(release: Release, cover_matches: bool | None = None) -> str:
    """Info panel text of a release row: everything known about the edition."""
    numbering = release.numbering
    type_line = release.type_name
    if release.type_from_tag:
        type_line += " (тег RELEASETYPE)"
    else:
        type_line += (
            f" — оценка по числу треков ({max(release.found, numbering.expected)}) "
            f"и длительности ({_clock(round(release.duration))}); "
            "тега RELEASETYPE нет"
        )
    if release.status == ReleaseStatus.COMPLETE:
        completeness = f"полный: {release.found} из {numbering.expected}"
    elif release.status == ReleaseStatus.NO_TOTAL:
        completeness = (
            f"без пропусков: {release.found} {files_word(release.found)}, "
            "общее число треков в тегах не указано"
        )
    elif release.status == ReleaseStatus.INCOMPLETE:
        expected = f" из {numbering.expected}" if numbering.verified else ""
        completeness = f"неполный: есть {release.found}{expected}"
    else:
        completeness = "не проверить: у файлов нет Track #"
    discs = str(release.disc_count)
    if numbering.disc_total and numbering.disc_total != len(numbering.discs):
        discs = f"{len(numbering.discs)} из {numbering.disc_total}"
    cover_line = release.cover_text
    if cover_matches is True:
        cover_line += " · файл совпадает со встроенной"
    elif cover_matches is False:
        cover_line += " · файл отличается от встроенной"
    lines = [
        "РЕЛИЗ",
        release.title,
        f"Исполнитель альбома: {release.album_artist or '—'}",
        f"Исполнители: {release.artists or '—'}",
    ]
    if release.guests:
        lines.append(f"Гости (меньше 30 % треков): {', '.join(release.guests)}")
    if release.compilation:
        artists = {
            name.casefold()
            for track in release.tracks
            for value in _track_artist_values(track)
            for name in split_names(value)
        }
        lines.append(f"Сборник: исполнителей {len(artists)}")
    lines.extend(
        [
            f"Тип: {type_line}",
            f"Лейбл: {release.label or '—'}",
            f"BARCODE: {', '.join(release.barcodes) or '—'}",
            f"Год: {release.year or '—'} · Жанр: {release.genre or '—'}",
            f"Комплект: {completeness}",
            f"Диски: {discs} · нумерация {_numbering_text(numbering)}",
            f"Длительность: {_clock(round(release.duration))} · "
            f"Размер: {release.size_bytes / 1024 / 1024:.2f} MB",
            f"Формат: {release.formats} · Качество: {release.quality or '—'}",
            f"Обложка: {cover_line}",
            f"Самый длинный путь: {release.longest_path} "
            f"{_plural(release.longest_path, 'символ', 'символа', 'символов')}"
            + (
                f" — больше {WINDOWS_PATH_LIMIT}, Windows не откроет"
                if release.longest_path > WINDOWS_PATH_LIMIT
                else ""
            ),
            f"Папка: {release.folder}",
        ]
    )
    missing = _missing_note(numbering)
    if release.status == ReleaseStatus.INCOMPLETE or missing:
        lines.extend(["", "ЧЕГО НЕ ХВАТАЕТ"])
        lines.extend(f"• {note}" for note in missing)
        if numbering.unplaced and not numbering.absent_discs:
            lines.append(
                "  Номера на каждом диске начинаются с 1, поэтому по тегам "
                "не определить, какой диск короче."
            )
        if release.barcodes:
            lines.append(
                f"  Искать это издание по BARCODE {release.barcodes[0]}."
            )
    other = [
        note
        for note in release.notes
        if note not in missing
    ]
    if other:
        lines.extend(["", "ЗАМЕЧАНИЯ"])
        lines.extend(f"• {note}" for note in other)
    lines.extend(["", "ТРЕКИ"])
    for track in release.tracks:
        number, _total = parse_position(track.track_number)
        position = f"{number:02d}" if number else "—"
        if len(numbering.discs) > 1:
            position = f"CD{track_disc(track)} · {position}"
        lines.append(
            f"{position}  {track.title or track.filename}"
            + (f" — {track.artist}" if track.artist and track.artist != release.album_artist else "")
            + (f" · {track.duration_display}" if track.duration_display else "")
        )
    return "\n".join(lines)
