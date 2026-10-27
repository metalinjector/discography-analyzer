"""Save the cover embedded in an album's tags into the folder itself.

foobar2000, Kodi, Plex and the Windows explorer read a cover file next to the
audio; some collections only carry the picture inside the tags. This module
plans and writes that file. Audio files are never modified, so no backups are
needed here — unlike :mod:`cover_embedding`, which writes tags.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .cover_embedding import CoverTaskStopped, _audio_files, _iter_folders
from .metadata import read_embedded_cover
from .metadata_audit import find_folder_cover

SUFFIX_BY_FORMAT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MIME_BY_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}

PlanProgress = Callable[[int, int, str], None]
WriteProgress = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class ExtractionTarget:
    """One folder that will receive ``cover.<suffix>``."""

    folder: Path
    relative_folder: str
    source: Path
    destination: Path
    data: bytes
    mime: str
    width: int
    height: int
    matching: int
    total: int

    @property
    def size_kb(self) -> float:
        return len(self.data) / 1024


@dataclass(frozen=True, slots=True)
class ExtractionSkip:
    relative_folder: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExtractionProblem:
    relative_path: str
    reason: str


@dataclass(frozen=True, slots=True)
class CoverExtractionPlan:
    root: Path
    targets: tuple[ExtractionTarget, ...] = ()
    skipped: tuple[ExtractionSkip, ...] = ()
    problems: tuple[ExtractionProblem, ...] = ()
    folders_scanned: int = 0
    files_scanned: int = 0

    @property
    def writable(self) -> int:
        return len(self.targets)


@dataclass(frozen=True, slots=True)
class ExtractionFailure:
    destination: Path
    reason: str


@dataclass(frozen=True, slots=True)
class CoverExtractionResult:
    written: int
    failures: tuple[ExtractionFailure, ...] = ()
    stopped: bool = False


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _wanted_extensions(extensions: Iterable[str]) -> set[str]:
    wanted: set[str] = set()
    for extension in extensions:
        text = str(extension).strip().casefold()
        if not text:
            continue
        wanted.add(text if text.startswith(".") else f".{text}")
    return wanted


def _validate(data: bytes) -> tuple[str, int, int]:
    """Return (image format, width, height) or raise ``ValueError``."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
            image.verify()
    except Exception as exc:
        raise ValueError(f"встроенная обложка не читается: {exc}") from exc
    if image_format not in SUFFIX_BY_FORMAT:
        raise ValueError(
            f"формат изображения {image_format or '?'} не поддерживается "
            "(нужны JPEG, PNG или WebP)"
        )
    return image_format, width, height


def _pick_majority(counts: Counter[str]) -> tuple[str, int] | None:
    """Cover hash shared by the strict majority of readable covers.

    Files without any embedded cover do not vote: one cover among three files
    where only one has art is still the album's cover. A tie means the folder
    has no single answer and is skipped by the caller.
    """
    if not counts:
        return None
    ranked = counts.most_common(2)
    digest, count = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if count <= second:
        return None
    return digest, count


def plan_cover_extraction(
    root: Path,
    *,
    extensions: Iterable[str],
    include_subfolders: bool = True,
    excluded_folders: Iterable[str] = (),
    stop_event=None,
    progress: PlanProgress | None = None,
) -> CoverExtractionPlan:
    """Find folders without a cover file whose tracks share one embedded cover."""
    root = Path(root)
    wanted = _wanted_extensions(extensions)
    targets: list[ExtractionTarget] = []
    skipped: list[ExtractionSkip] = []
    problems: list[ExtractionProblem] = []
    folders_scanned = 0
    files_scanned = 0

    for folder in _iter_folders(root, include_subfolders, excluded_folders):
        if stop_event is not None and stop_event.is_set():
            raise CoverTaskStopped
        folders_scanned += 1
        audio_files = _audio_files(folder, wanted)
        if not audio_files:
            continue
        files_scanned += len(audio_files)
        if progress is not None:
            progress(files_scanned, folders_scanned, _relative(folder, root))
        if find_folder_cover(folder) is not None:
            continue

        counts: Counter[str] = Counter()
        data_by_hash: dict[str, bytes] = {}
        source_by_hash: dict[str, Path] = {}
        for path in audio_files:
            if stop_event is not None and stop_event.is_set():
                raise CoverTaskStopped
            data, _mime, error = read_embedded_cover(path)
            if error:
                problems.append(
                    ExtractionProblem(_relative(path, root), error)
                )
                continue
            if not data:
                continue
            digest = hashlib.sha256(data).hexdigest()
            counts[digest] += 1
            data_by_hash.setdefault(digest, data)
            source_by_hash.setdefault(digest, path)

        if not counts:
            skipped.append(
                ExtractionSkip(
                    _relative(folder, root), "у треков нет встроенной обложки"
                )
            )
            continue
        picked = _pick_majority(counts)
        if picked is None:
            reason = "у треков разные обложки, ни одна не преобладает"
            skipped.append(ExtractionSkip(_relative(folder, root), reason))
            continue
        digest, matching = picked
        data = data_by_hash[digest]
        try:
            image_format, width, height = _validate(data)
        except ValueError as exc:
            problems.append(
                ExtractionProblem(_relative(source_by_hash[digest], root), str(exc))
            )
            continue
        destination = folder / f"cover{SUFFIX_BY_FORMAT[image_format]}"
        if destination.exists():
            continue
        targets.append(
            ExtractionTarget(
                folder=folder,
                relative_folder=_relative(folder, root),
                source=source_by_hash[digest],
                destination=destination,
                data=data,
                mime=MIME_BY_FORMAT[image_format],
                width=width,
                height=height,
                matching=matching,
                total=len(audio_files),
            )
        )

    return CoverExtractionPlan(
        root=root,
        targets=tuple(targets),
        skipped=tuple(skipped),
        problems=tuple(problems),
        folders_scanned=folders_scanned,
        files_scanned=files_scanned,
    )


def write_covers(
    plan: CoverExtractionPlan,
    *,
    stop_event=None,
    progress: WriteProgress | None = None,
) -> CoverExtractionResult:
    """Write every planned cover through a hidden temporary file.

    The file is verified by SHA-256 and only then renamed, so an interrupted
    write leaves nothing behind and an existing file is never overwritten.
    """
    written = 0
    failures: list[ExtractionFailure] = []
    stopped = False
    total = len(plan.targets)
    for index, target in enumerate(plan.targets, start=1):
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        if progress is not None:
            progress(index - 1, total, target.relative_folder)
        partial: Path | None = None
        try:
            if target.destination.exists():
                raise OSError("файл обложки уже существует")
            descriptor, name = tempfile.mkstemp(
                prefix=".cover-", suffix=".part", dir=target.folder
            )
            partial = Path(name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(target.data)
                handle.flush()
                os.fsync(handle.fileno())
            written_digest = hashlib.sha256(partial.read_bytes()).hexdigest()
            if written_digest != hashlib.sha256(target.data).hexdigest():
                raise OSError("контрольная сумма записанной обложки не совпала")
            os.replace(partial, target.destination)
            partial = None
            written += 1
        except OSError as exc:
            failures.append(ExtractionFailure(target.destination, str(exc)))
        finally:
            if partial is not None:
                with contextlib.suppress(OSError):
                    partial.unlink(missing_ok=True)
        if progress is not None:
            progress(index, total, target.relative_folder)
    return CoverExtractionResult(
        written=written, failures=tuple(failures), stopped=stopped
    )
