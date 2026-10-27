"""M3U8 playlists for the current selection or the visible table."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .models import Track

EXTM3U = "#EXTM3U"
PLAYLIST_SUFFIX = ".m3u8"


def _seconds(track: Track) -> int:
    duration = track.comparison_duration
    if duration is None:
        return -1
    return round(duration)


def _title(track: Track) -> str:
    title = track.title.strip() or track.filename_title.strip()
    artist = track.artist.strip()
    return f"{artist} - {title}" if artist else title


def _entry_path(track: Track, playlist_folder: Path) -> str:
    """Relative path, or absolute when the file is on another Windows drive."""
    try:
        return os.path.relpath(track.path, playlist_folder)
    except ValueError:
        return str(track.path)


def build_m3u8(tracks: Iterable[Track], playlist_folder: Path) -> str:
    """Return the playlist text: ``#EXTM3U`` plus ``#EXTINF`` for every track."""
    lines = [EXTM3U]
    for track in tracks:
        lines.append(f"#EXTINF:{_seconds(track)},{_title(track)}")
        lines.append(_entry_path(track, playlist_folder))
    return "\n".join(lines) + "\n"


def write_playlist(tracks: Iterable[Track], destination: Path) -> Path:
    """Write the playlist through a hidden temporary file and ``os.replace``."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = build_m3u8(tracks, destination.parent)
    descriptor, name = tempfile.mkstemp(
        prefix=".playlist-", suffix=".part", dir=destination.parent
    )
    partial = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, destination)
    except BaseException:
        # A failed write must not damage the playlist that was there before.
        partial.unlink(missing_ok=True)
        raise
    return destination
