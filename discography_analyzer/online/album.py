"""Local album folders: their tracks, what is known about the album, its cover.

The tracks are read with the analysis' own :func:`read_metadata`, so «пустой
тег» here means exactly what the table and the audit show as empty.
"""

from __future__ import annotations

import re
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..fileops import iter_folders, list_audio_files
from ..metadata import read_metadata
from ..metadata_audit import find_folder_cover
from ..models import Track
from ..parsing import title_from_filename
from .http import LookupStopped
from .release import parse_year

# «CD1», «CD 2», «Disc 1», «Disk2 - Bonus», «Диск 1».
DISC_FOLDER_RE = re.compile(r"^(?:cd|dis[ck]|диск)\s*[-_.]?\s*(\d{1,2})(?:\D.*)?$", re.IGNORECASE)
# Bracketed rip details that are not part of the album title: [FLAC], (24-96),
# {WEB}, [2CD]. «(Remastered)» or «(Deluxe Edition)» stay: they name the edition.
SOURCE_DETAILS_RE = re.compile(
    r"\s*[\[({][^\])}]*\b(?:flac|mp3|ape|alac|aac|m4a|wav|wv|ogg|opus|dsd|sacd|"
    r"web|\d*\s*cd|vinyl|lp|\d+\s*kbps|v0|v2|\d{2}\s*bit|\d{2}[-/]\d{2,3}|hi-?res|"
    r"lossless|scene)\b[^\])}]*[\])}]\s*",
    re.IGNORECASE,
)
YEAR_PART_RE = re.compile(r"^[\[(]?((?:19|20)\d{2})[\])]?$")
LEADING_YEAR_RE = re.compile(r"^[\[(]?((?:19|20)\d{2})[\])]?\s*[-–—.]?\s+(?=\S)")
TRAILING_YEAR_RE = re.compile(r"\s*[\[(]((?:19|20)\d{2})[\])]\s*$")
DASH_RE = re.compile(r"\s+[-–—]\s+")
# Folders that group albums instead of naming the artist.
GROUPING_FOLDERS = {
    "albums",
    "album",
    "альбомы",
    "singles",
    "синглы",
    "eps",
    "ep",
    "compilations",
    "сборники",
    "live",
    "концерты",
    "discography",
    "дискография",
    "studio albums",
    "студийные альбомы",
    "demos",
    "демо",
    "bootlegs",
    "music",
    "музыка",
    "lossless",
    "flac",
    "mp3",
    "downloads",
    "загрузки",
    "new",
    "misc",
    "разное",
}

ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True, slots=True)
class AlbumGuess:
    """The album as the tags (or, failing them, the folder names) describe it."""

    artist: str
    title: str
    year: int | None
    track_count: int
    disc: int | None  # disc folder «CD2» → 2


@dataclass(slots=True)
class LocalAlbum:
    folder: Path
    relative_folder: str
    tracks: list[Track]
    guess: AlbumGuess
    folder_cover: Path | None

    @property
    def has_cover(self) -> bool:
        """A cover file in the folder or a readable cover in any track."""
        return self.folder_cover is not None or any(
            track_has_cover(track) for track in self.tracks
        )


def track_has_cover(track: Track) -> bool:
    return track.cover_size > 0 and not track.cover_error


def disc_number_of_folder(name: str) -> int | None:
    match = DISC_FOLDER_RE.match(name.strip())
    return int(match.group(1)) if match else None


def parse_folder_name(name: str) -> tuple[str, str, int | None]:
    """(artist, title, year) from «Artist - 1986 - Title», «1986 - Title», «Title (1986)»."""
    text = SOURCE_DETAILS_RE.sub(" ", name).strip()
    year: int | None = None
    trailing = TRAILING_YEAR_RE.search(text)
    if trailing:
        year = int(trailing.group(1))
        text = text[: trailing.start()].strip()
    parts = [part.strip() for part in DASH_RE.split(text) if part.strip()]
    for index, part in enumerate(parts):
        match = YEAR_PART_RE.match(part)
        # «Van Halen - 1984» and a lone «1984» are titles, not years.
        if match and (index < len(parts) - 1 or len(parts) > 2):
            year = year or int(match.group(1))
            del parts[index]
            break
    else:
        if parts:
            leading = LEADING_YEAR_RE.match(parts[0])
            if leading:
                year = year or int(leading.group(1))
                parts[0] = parts[0][leading.end() :].strip()
    if len(parts) >= 2:
        return parts[0], " - ".join(parts[1:]), year
    return "", parts[0] if parts else "", year


def folder_artist(album_folder: Path, root: Path) -> str:
    """The artist folder above an album folder, skipping «Albums», «Singles», …

    Only folders of the collection count: above the root lie unrelated names
    such as «Downloads», unless the root itself is the album folder.
    """
    limit = root.parent if album_folder == root else root
    current = album_folder.parent
    for _level in range(2):
        name = current.name.strip()
        inside = current == limit or limit in current.parents
        if not name or not inside or current == current.parent:
            return ""
        cleaned = SOURCE_DETAILS_RE.sub(" ", name).strip()
        if cleaned.casefold() not in GROUPING_FOLDERS and not re.fullmatch(
            r"(?:19|20)\d0s?|\d{4}", cleaned
        ):
            return cleaned
        current = current.parent
    return ""


def _most_common(values: Iterable[str]) -> str:
    counts = Counter(value.strip() for value in values if value and value.strip())
    return counts.most_common(1)[0][0] if counts else ""


def guess_album(folder: Path, tracks: list[Track], root: Path) -> AlbumGuess:
    disc = disc_number_of_folder(folder.name)
    album_folder = folder.parent if disc is not None else folder
    folder_artist_name, folder_title, folder_year = parse_folder_name(album_folder.name)
    artist = (
        _most_common(track.album_artist for track in tracks)
        or _most_common(track.artist for track in tracks)
        or folder_artist_name
        or folder_artist(album_folder, root)
    )
    title = _most_common(track.album for track in tracks) or folder_title
    year = parse_year(_most_common(track.year for track in tracks)) or folder_year
    return AlbumGuess(
        artist=artist,
        title=title,
        year=year,
        track_count=len(tracks),
        disc=disc,
    )


def read_track(path: Path, root: Path) -> Track:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)
    relative_folder = str(relative.parent)
    track = Track(
        id=uuid.uuid4().hex,
        path=path,
        root=root,
        filename=path.name,
        relative_path=str(relative),
        relative_folder=str(root) if relative_folder == "." else relative_folder,
        format=path.suffix[1:].upper(),
        size_bytes=path.stat().st_size,
        filename_title=title_from_filename(path.name),
    )
    read_metadata(track)
    return track


def read_album(folder: Path, root: Path, extensions: set[str]) -> LocalAlbum | None:
    """The album in ``folder`` (its own files only), or None without audio."""
    paths = list_audio_files(folder, extensions)
    if not paths:
        return None
    tracks: list[Track] = []
    for path in paths:
        try:
            tracks.append(read_track(path, root))
        except OSError:
            continue  # vanished or unreadable file, same as in the scan
    if not tracks:
        return None
    try:
        relative_folder = str(folder.relative_to(root))
    except ValueError:
        relative_folder = str(folder)
    return LocalAlbum(
        folder=folder,
        # The chosen folder is the album itself: the list shows its name.
        relative_folder=(folder.name or str(folder)) if relative_folder == "." else relative_folder,
        tracks=tracks,
        guess=guess_album(folder, tracks, root),
        folder_cover=find_folder_cover(folder),
    )


def iter_albums(
    root: Path,
    *,
    extensions: Iterable[str],
    include_subfolders: bool = True,
    excluded_folders: Iterable[str] = (),
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> Iterator[LocalAlbum]:
    """Every folder with audio files directly inside it, as one album."""
    wanted = {extension.casefold() for extension in extensions if extension.strip()}
    for index, folder in enumerate(
        iter_folders(root, include_subfolders, excluded_folders), start=1
    ):
        if stop_event is not None and stop_event.is_set():
            raise LookupStopped
        if progress is not None:
            progress(index, str(folder))
        album = read_album(folder, root, wanted)
        if album is not None:
            yield album
