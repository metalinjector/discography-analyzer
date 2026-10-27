"""Filesystem primitives shared by the tag writers and the utilities.

No writer may damage the source file: the new tag block is written into a
temporary copy, verified, and only then swapped in with ``os.replace``.
Backup and timestamp handling are the same everywhere, and so is the walk
over the collection folders, so they live here instead of being duplicated.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path


def available_path(path: Path) -> Path:
    """Return a non-existing path by appending " (2)", " (3)", ... to the stem."""
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def create_partial_file(folder: Path, prefix: str) -> tuple[int, Path]:
    """Create a hidden ``<prefix>XXXXXXXX.part`` file in ``folder``: (fd, path).

    ``tempfile.mkstemp`` always creates 0600 files. This one becomes a new
    cover or playlist after ``os.replace``, so it gets the permissions of any
    new file (0o666 minus the umask): a media server running as another user
    must be able to read it.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    while True:
        path = folder / f"{prefix}{secrets.token_hex(4)}.part"
        try:
            return os.open(path, flags, 0o666), path
        except FileExistsError:
            continue


def write_new_file(destination: Path, data: bytes, *, prefix: str) -> None:
    """Create ``destination`` holding ``data``; an existing file is never replaced.

    The bytes go to a hidden partial file, are read back and compared by
    SHA-256, and only then renamed, so an interrupted write leaves nothing.
    """
    if destination.exists():
        raise FileExistsError("файл уже существует")
    descriptor, partial = create_partial_file(destination.parent, prefix)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if hashlib.sha256(partial.read_bytes()).digest() != hashlib.sha256(data).digest():
            raise OSError("контрольная сумма записанного файла не совпала")
        os.replace(partial, destination)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink(missing_ok=True)
        raise


def iter_folders(
    root: Path,
    include_subfolders: bool,
    excluded_folders: Iterable[str],
) -> Iterator[Path]:
    """``root`` and, if asked, every subfolder; hidden and excluded ones are skipped."""
    if not include_subfolders:
        yield root
        return
    excluded = {
        name.casefold() for name in excluded_folders if str(name).strip()
    }
    for current, directories, _names in os.walk(root):
        directories[:] = [
            name
            for name in directories
            if name.casefold() not in excluded and not name.startswith(".")
        ]
        directories.sort(key=str.casefold)
        yield Path(current)


def list_audio_files(folder: Path, extensions: set[str]) -> list[Path]:
    """Files of ``folder`` with one of ``extensions`` (lower case), by name."""
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    return sorted(
        (
            entry
            for entry in entries
            # Hidden "._" AppleDouble files are not audio, same as in the scan.
            if not entry.name.startswith(".")
            and entry.is_file()
            and entry.suffix.casefold() in extensions
        ),
        key=lambda entry: entry.name.casefold(),
    )


def temporary_copy(source: Path, *, prefix: str) -> Path:
    """Copy ``source`` next to itself so the final replace stays on one volume."""
    descriptor, name = tempfile.mkstemp(
        prefix=prefix,
        suffix=source.suffix,
        dir=source.parent,
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def backup_copy(source: Path, root: Path | None, backup_root: Path) -> Path:
    """Mirror ``source`` under ``backup_root`` keeping its path inside ``root``."""
    try:
        relative = source.relative_to(root) if root is not None else Path(source.name)
    except ValueError:
        relative = Path(source.name)
    backup = available_path(backup_root / relative)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def replace_preserving_times(temporary: Path, source: Path) -> None:
    """Give ``temporary`` the source timestamps, then atomically replace it."""
    source_stat = source.stat()
    os.utime(
        temporary,
        ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
    )
    os.replace(temporary, source)
