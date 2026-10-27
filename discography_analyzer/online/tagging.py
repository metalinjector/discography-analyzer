"""Fill the empty tags of an album from a release; download and save its cover.

Only empty fields are planned: a value already in the file is never
replaced. Every file goes through one temporary copy — text tags, numbers and
cover are written there, the copy is read back with the analysis' own reader,
and only then a backup is made and the original replaced, as in the other
tag writers.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from ..completeness import parse_position
from ..cover_embedding import (
    CoverImage,
    cover_image_from_bytes,
    verify_cover,
    write_cover,
)
from ..fileops import (
    backup_copy,
    replace_preserving_times,
    temporary_copy,
    write_new_file,
)
from ..metadata import id3_save_options, read_metadata
from ..metadata_writer import write_text_tags
from ..models import Track
from ..numbering_fix import write_total
from .album import LocalAlbum, track_has_cover
from .http import HttpClient, LookupStopped
from .matching import TrackMatch, normalize_title
from .release import Release, ReleaseTrack

try:
    import mutagen
    from mutagen.apev2 import TEXT, APEv2, APEValue
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, TPOS
    from mutagen.mp4 import MP4
except ImportError:  # The GUI provides a friendly dependency message.
    mutagen = None
    TEXT = APEv2 = APEValue = None
    FLAC = None
    ID3 = TPOS = None
    MP4 = None

TEXT_FIELDS = ("title", "artist", "album", "album_artist", "year", "genre")
FIELD_LABELS = {
    "title": "название",
    "artist": "исполнитель",
    "album": "альбом",
    "album_artist": "исполнитель альбома",
    "year": "год",
    "genre": "жанр",
    "track": "номер трека",
    "disc": "номер диска",
    "cover": "обложка",
}
COVER_SUFFIX_BY_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class FillOptions:
    fields: frozenset[str] = frozenset((*TEXT_FIELDS, "track", "disc"))
    embed_cover: bool = True
    save_cover_file: bool = True


@dataclass(frozen=True, slots=True)
class FileChange:
    track: Track
    source: ReleaseTrack
    text: tuple[tuple[str, str], ...] = ()
    track_position: tuple[int, int] | None = None
    disc_position: tuple[int, int] | None = None
    embed_cover: bool = False

    @property
    def empty(self) -> bool:
        return not (self.text or self.track_position or self.disc_position or self.embed_cover)

    def describe(self) -> str:
        parts = [f"{FIELD_LABELS[field]}: {value}" for field, value in self.text]
        if self.track_position:
            parts.append("№ {}/{}".format(*self.track_position))
        if self.disc_position:
            parts.append("диск {}/{}".format(*self.disc_position))
        if self.embed_cover:
            parts.append("обложка")
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class AlbumPlan:
    album: LocalAlbum
    release: Release
    changes: tuple[FileChange, ...]
    save_cover_file: bool
    unmatched: tuple[Track, ...] = ()

    @property
    def needs_cover(self) -> bool:
        return self.save_cover_file or any(change.embed_cover for change in self.changes)

    @property
    def fields(self) -> list[str]:
        """Labels of everything the plan fills, in a fixed order."""
        filled = {field for change in self.changes for field, _value in change.text}
        if any(change.track_position for change in self.changes):
            filled.add("track")
        if any(change.disc_position for change in self.changes):
            filled.add("disc")
        if self.needs_cover:
            filled.add("cover")
        return [label for field, label in FIELD_LABELS.items() if field in filled]

    @property
    def empty(self) -> bool:
        return not self.changes and not self.save_cover_file


def missing_fields(album: LocalAlbum, options: FillOptions) -> list[str]:
    """Labels of the selected fields that are empty somewhere in the album.

    Only a missing track number counts, not a missing total, and disc numbers
    do not count at all: they are filled on the way, but on their own they
    would send almost every album of a collection to the service.
    """
    missing: set[str] = set()
    for track in album.tracks:
        missing.update(
            field
            for field in TEXT_FIELDS
            if field in options.fields and not getattr(track, field).strip()
        )
        if "track" in options.fields and parse_position(track.track_number)[0] is None:
            missing.add("track")
    if (options.embed_cover or options.save_cover_file) and not album.has_cover:
        missing.add("cover")
    return [label for field, label in FIELD_LABELS.items() if field in missing]


def _release_value(
    field: str, release: Release, source: ReleaseTrack, album_title: str = ""
) -> str:
    if field == "title":
        return source.title
    if field == "artist":
        return source.artist or release.artist
    if field == "album":
        # Apple names the same album «Christmas & Chill - EP»; keep the
        # collection's own name when both are the same album.
        local = album_title.strip()
        if local and normalize_title(local) == normalize_title(release.title):
            return local
        return release.title
    if field == "album_artist":
        return release.artist
    if field == "year":
        return str(release.year) if release.year else ""
    return release.genre


def _position(current: str, number: int, total: int) -> tuple[int, int] | None:
    """``number/total`` for an empty value, ``current/total`` when only the total is missing."""
    if total <= 0:
        return None
    mine, mine_total = parse_position(current)
    if mine is None:
        return (number, total) if 0 < number <= total else None
    if mine_total is None and mine <= total:
        return mine, total
    return None


def plan_album(
    album: LocalAlbum,
    release: Release,
    matches: Iterable[TrackMatch],
    options: FillOptions,
) -> AlbumPlan:
    """The empty fields of every matched file, filled from ``release``.

    A release without a single matched track plans nothing, not even the
    cover file: it is another album or another edition.
    """
    matches = list(matches)
    matched = any(match.source is not None for match in matches)
    cover_wanted = matched and bool(release.cover_url) and not album.has_cover
    changes: list[FileChange] = []
    unmatched: list[Track] = []
    for match in matches:
        track, source = match.track, match.source
        if source is None:
            unmatched.append(track)
            continue
        text = tuple(
            (field, value)
            for field in TEXT_FIELDS
            if field in options.fields
            and not getattr(track, field).strip()
            and (
                value := _release_value(
                    field, release, source, album.guess.title
                ).strip()
            )
        )
        track_position = None
        if "track" in options.fields:
            track_position = _position(
                track.track_number,
                source.number,
                release.disc_size(source.disc) or release.track_count,
            )
        disc_position = None
        if "disc" in options.fields and release.disc_total > 1:
            disc_position = _position(track.disc_number, source.disc, release.disc_total)
        change = FileChange(
            track=track,
            source=source,
            text=text,
            track_position=track_position,
            disc_position=disc_position,
            embed_cover=options.embed_cover and cover_wanted and not track_has_cover(track),
        )
        if not change.empty:
            changes.append(change)
    return AlbumPlan(
        album=album,
        release=release,
        changes=tuple(changes),
        save_cover_file=options.save_cover_file and cover_wanted,
        unmatched=tuple(unmatched),
    )


def _key(tags, wanted: str, fallback: str) -> str:
    """The key case the file already uses, so it keeps one tag, not two."""
    # Vorbis tag dicts iterate as (key, value) pairs, so .keys() is required.
    for key in tags.keys():  # noqa: SIM118
        if str(key).casefold() == wanted.casefold():
            return str(key)
    return fallback


def write_disc(path: Path, number: int, total: int) -> None:
    """Write ``number/total`` as the disc position, in the file's own format."""
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    audio = mutagen.File(path)
    if audio is None:
        raise ValueError("формат файла не распознан")
    if FLAC is not None and isinstance(audio, FLAC):
        audio[_key(audio, "discnumber", "discnumber")] = [str(number)]
        audio[_key(audio, "disctotal", "disctotal")] = [str(total)]
        audio.save()
        return
    if MP4 is not None and isinstance(audio, MP4):
        if getattr(audio, "tags", None) is None:
            audio.add_tags()
        audio["disk"] = [(number, total)]
        audio.save()
        return
    tags = getattr(audio, "tags", None)
    if tags is None:
        add_tags = getattr(audio, "add_tags", None)
        if callable(add_tags):
            add_tags()
            tags = getattr(audio, "tags", None)
    if ID3 is not None and isinstance(tags, ID3):
        tags["TPOS"] = TPOS(encoding=3, text=f"{number}/{total}")
        audio.save(**id3_save_options(tags))
        return
    if APEv2 is not None and isinstance(tags, APEv2):
        tags[_key(tags, "disc", "Disc")] = APEValue(f"{number}/{total}", TEXT)
        audio.save()
        return
    raise ValueError(f"формат {type(audio).__name__} не поддерживается")


def _verify(path: Path, change: FileChange, cover: CoverImage | None) -> None:
    """Read the written copy with the analysis' reader: it must see the plan."""
    check = Track(
        id="verify",
        path=path,
        root=path.parent,
        filename=path.name,
        relative_path=path.name,
        relative_folder="",
        format=path.suffix[1:].upper(),
        size_bytes=0,
    )
    read_metadata(check)
    if check.metadata_errors:
        raise ValueError(f"файл не читается после записи: {check.metadata_errors[0]}")
    for field, value in change.text:
        if getattr(check, field) != value:
            raise ValueError(f"проверка тега «{FIELD_LABELS[field]}» после записи не пройдена")
    for position, value, label in (
        (change.track_position, check.track_number, "номера трека"),
        (change.disc_position, check.disc_number, "номера диска"),
    ):
        if position is not None and value != "{}/{}".format(*position):
            raise ValueError(f"проверка {label} после записи не пройдена: {value or 'пусто'}")
    if cover is not None:
        verify_cover(path, cover)


def write_change(
    change: FileChange,
    cover: CoverImage | None,
    root: Path,
    backup_root: Path | None,
) -> bool:
    """Apply one file's change; True if a backup copy was made."""
    source = change.track.path
    temporary = temporary_copy(source, prefix=f".{source.stem}-online-")
    try:
        if change.text:
            write_text_tags(temporary, dict(change.text))
        if change.track_position is not None:
            write_total(temporary, *change.track_position)
        if change.disc_position is not None:
            write_disc(temporary, *change.disc_position)
        if cover is not None:
            write_cover(temporary, cover)
        _verify(temporary, change, cover)
        backup_created = False
        if backup_root is not None:
            backup_copy(source, root, backup_root)
            backup_created = True
        replace_preserving_times(temporary, source)
        return backup_created
    finally:
        temporary.unlink(missing_ok=True)


def download_cover(client: HttpClient, release: Release, folder: Path) -> CoverImage:
    """The release cover as a validated JPEG or PNG named ``cover.<ext>``."""
    data = client.get_bytes(release.cover_url)
    cover = cover_image_from_bytes(folder / "cover.jpg", data)
    suffix = COVER_SUFFIX_BY_MIME.get(cover.mime)
    if suffix is None:
        # M4A keeps only JPEG and PNG, and players expect cover.jpg/png.
        raise ValueError(f"сервис отдал обложку {cover.mime}, нужен JPEG или PNG")
    return replace(cover, path=folder / f"cover{suffix}")


@dataclass(frozen=True, slots=True)
class TaggingFailure:
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class TaggingResult:
    albums: int
    updated_files: int
    backup_files: int
    covers_saved: int
    failures: tuple[TaggingFailure, ...] = ()
    stopped: bool = False


def apply_plans(
    plans: Iterable[AlbumPlan],
    *,
    client: HttpClient,
    root: Path,
    backup_root: Path | None = None,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> TaggingResult:
    """Write every plan; a failed cover download leaves the tags to be written."""
    jobs = [plan for plan in plans if not plan.empty]
    total = sum(len(plan.changes) + int(plan.save_cover_file) for plan in jobs)
    done = 0
    albums = updated_files = backup_files = covers_saved = 0
    failures: list[TaggingFailure] = []
    stopped = False
    for plan in jobs:
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        folder = plan.album.folder
        cover: CoverImage | None = None
        if plan.needs_cover:
            try:
                cover = download_cover(client, plan.release, folder)
            except LookupStopped:
                stopped = True
                break
            except Exception as exc:
                failures.append(TaggingFailure(folder, f"обложка не загружена: {exc}"))
        album_changed = False
        for change in plan.changes:
            if stop_event is not None and stop_event.is_set():
                stopped = True
                break
            done += 1
            if progress is not None:
                progress(done, total, change.track.relative_path)
            file_cover = cover if change.embed_cover else None
            change = replace(change, embed_cover=file_cover is not None)
            if change.empty:
                continue  # only the cover was planned, and it did not download
            try:
                backup_files += int(write_change(change, file_cover, root, backup_root))
                updated_files += 1
                album_changed = True
            except Exception as exc:
                failures.append(TaggingFailure(change.track.path, str(exc)))
        if stopped:
            break
        if plan.save_cover_file:
            done += 1
            if progress is not None:
                progress(done, total, plan.album.relative_folder)
            if cover is not None:
                try:
                    write_new_file(cover.path, cover.data, prefix=".cover-")
                    covers_saved += 1
                    album_changed = True
                except OSError as exc:
                    failures.append(TaggingFailure(cover.path, str(exc)))
        albums += int(album_changed)
    return TaggingResult(
        albums=albums,
        updated_files=updated_files,
        backup_files=backup_files,
        covers_saved=covers_saved,
        failures=tuple(failures),
        stopped=stopped,
    )
