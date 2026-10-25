"""Filesystem primitives shared by the tag writers.

Both writers (text fixes and cover embedding) must never damage the source
file: the new tag block is written into a temporary copy, verified, and only
then swapped in with ``os.replace``. Backup and timestamp handling are the
same in both cases, so they live here instead of being duplicated.
"""

from __future__ import annotations

import os
import shutil
import tempfile
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
