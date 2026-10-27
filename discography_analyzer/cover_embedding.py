"""Embed a folder cover image into the tags of files that have none.

The whole module works on the filesystem, so the utility does not depend on a
previous analysis: it walks the folders, finds a cover image (cover.jpg,
folder.png, …) and writes that picture into every audio file of the same
folder whose tags carry no readable cover.

Every file is rewritten through a temporary copy: the picture is added there,
read back and compared byte for byte, and only then the original is replaced.
A failure therefore leaves the original file untouched.
"""

from __future__ import annotations

import hashlib
import io
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PIL import Image

from .fileops import (
    backup_copy,
    iter_folders,
    list_audio_files,
    replace_preserving_times,
    temporary_copy,
)
from .metadata import (
    embedded_cover,
    front_picture,
    id3_save_options,
    read_embedded_cover,
)
from .metadata_audit import find_folder_cover

try:
    import mutagen
    from mutagen.apev2 import BINARY, APEv2, APEValue
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3
    from mutagen.mp4 import MP4, MP4Cover
except ImportError:  # The GUI provides a friendly dependency message.
    mutagen = None
    APEv2 = APEValue = BINARY = None
    FLAC = Picture = None
    APIC = ID3 = None
    MP4 = MP4Cover = None

FRONT_COVER = 3
COVER_DESCRIPTION = "Cover"
APE_COVER_KEY = "Cover Art (Front)"
IMAGE_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "MPO": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
}
# Picture.depth is bits per pixel; mutagen uses it to describe the image.
BITS_BY_IMAGE_MODE = {
    "1": 1,
    "L": 8,
    "LA": 16,
    "P": 8,
    "RGB": 24,
    "RGBA": 32,
    "CMYK": 32,
    "YCbCr": 24,
    "LAB": 24,
    "HSV": 24,
    "I": 32,
    "I;16": 16,
    "F": 32,
}


class CoverTaskStopped(RuntimeError):
    """Raised when the user stops a planning or embedding run."""


class ArtState(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    BROKEN = "broken"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class CoverImage:
    path: Path
    data: bytes
    mime: str
    width: int
    height: int
    mode: str = "RGB"

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def depth(self) -> int:
        return BITS_BY_IMAGE_MODE.get(self.mode, 24)

    @property
    def colors(self) -> int:
        return 256 if self.mode == "P" else 0

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True, slots=True)
class CoverTarget:
    path: Path
    relative_path: str
    reason: ArtState


@dataclass(frozen=True, slots=True)
class FolderCoverPlan:
    folder: Path
    relative_folder: str
    cover: CoverImage
    targets: tuple[CoverTarget, ...]
    files_with_cover: int


@dataclass(frozen=True, slots=True)
class CoverProblem:
    path: Path
    relative_path: str
    reason: str


@dataclass(frozen=True, slots=True)
class CoverPlan:
    root: Path
    folders: tuple[FolderCoverPlan, ...]
    folders_scanned: int
    files_scanned: int
    files_with_cover: int
    files_with_broken_cover: int
    folders_without_cover: int
    problems: tuple[CoverProblem, ...]

    @property
    def folder_count(self) -> int:
        return len(self.folders)

    @property
    def target_count(self) -> int:
        return sum(len(folder.targets) for folder in self.folders)


@dataclass(frozen=True, slots=True)
class CoverEmbedFailure:
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class CoverEmbedResult:
    folders_updated: int
    updated_files: int
    backup_files: int
    failures: tuple[CoverEmbedFailure, ...]
    stopped: bool = False


PlanProgress = Callable[[int, int, str], None]
EmbedProgress = Callable[[int, int, str], None]


def read_cover_image(path: Path) -> CoverImage:
    """Read and validate a cover file. Raises ``ValueError`` if it is unusable."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"не удалось прочитать файл обложки: {exc}") from exc
    return cover_image_from_bytes(path, data)


def cover_image_from_bytes(path: Path, data: bytes) -> CoverImage:
    """Validate image bytes; ``path`` names the picture (APEv2 stores the name)."""
    if not data:
        raise ValueError("файл обложки пуст")
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            mode = image.mode
            image_format = image.format or ""
            image.verify()
    except Exception as exc:
        raise ValueError(f"файл обложки не является изображением: {exc}") from exc
    mime = IMAGE_MIME_BY_FORMAT.get(image_format.upper(), "")
    if not mime:
        raise ValueError(f"формат изображения {image_format or '?'} не поддерживается")
    return CoverImage(
        path=path,
        data=data,
        mime=mime,
        width=width,
        height=height,
        mode=mode,
    )


def inspect_art(path: Path) -> tuple[ArtState, str]:
    """Return the state of the embedded art of one file and an error text."""
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    try:
        audio = mutagen.File(path)
    except Exception as exc:
        return ArtState.UNREADABLE, str(exc)
    if audio is None:
        return ArtState.UNREADABLE, "формат файла не распознан"
    try:
        cover = embedded_cover(audio, path)
    except Exception as exc:
        return ArtState.BROKEN, str(exc)
    if cover is None:
        return ArtState.MISSING, ""
    data, _mime = cover
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:
        return ArtState.BROKEN, str(exc)
    return ArtState.PRESENT, ""


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def plan_cover_embedding(
    root: Path,
    *,
    extensions: Iterable[str],
    include_subfolders: bool = True,
    excluded_folders: Iterable[str] = (),
    replace_broken: bool = False,
    stop_event: threading.Event | None = None,
    progress: PlanProgress | None = None,
) -> CoverPlan:
    """Build the list of folders and files that would receive a folder cover."""
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    wanted = {extension.casefold() for extension in extensions if extension.strip()}
    folders: list[FolderCoverPlan] = []
    problems: list[CoverProblem] = []
    folders_scanned = 0
    files_scanned = 0
    files_with_cover = 0
    files_with_broken_cover = 0
    folders_without_cover = 0

    for folder in iter_folders(root, include_subfolders, excluded_folders):
        if stop_event is not None and stop_event.is_set():
            raise CoverTaskStopped
        folders_scanned += 1
        audio_files = list_audio_files(folder, wanted)
        if progress is not None:
            progress(files_scanned, folders_scanned, _relative(folder, root))
        if not audio_files:
            continue
        files_scanned += len(audio_files)
        cover_path = find_folder_cover(folder)
        if cover_path is None:
            folders_without_cover += 1
            continue
        try:
            cover = read_cover_image(cover_path)
        except ValueError as exc:
            problems.append(
                CoverProblem(
                    path=cover_path,
                    relative_path=_relative(cover_path, root),
                    reason=str(exc),
                )
            )
            continue

        targets: list[CoverTarget] = []
        with_cover = 0
        for path in audio_files:
            if stop_event is not None and stop_event.is_set():
                raise CoverTaskStopped
            state, error = inspect_art(path)
            if state is ArtState.PRESENT:
                with_cover += 1
                continue
            if state is ArtState.UNREADABLE:
                problems.append(
                    CoverProblem(
                        path=path,
                        relative_path=_relative(path, root),
                        reason=error or "файл не читается",
                    )
                )
                continue
            if state is ArtState.BROKEN and not replace_broken:
                files_with_broken_cover += 1
                continue
            targets.append(
                CoverTarget(
                    path=path,
                    relative_path=_relative(path, root),
                    reason=state,
                )
            )
        files_with_cover += with_cover
        if targets:
            folders.append(
                FolderCoverPlan(
                    folder=folder,
                    relative_folder=_relative(folder, root),
                    cover=cover,
                    targets=tuple(targets),
                    files_with_cover=with_cover,
                )
            )
    return CoverPlan(
        root=root,
        folders=tuple(folders),
        folders_scanned=folders_scanned,
        files_scanned=files_scanned,
        files_with_cover=files_with_cover,
        files_with_broken_cover=files_with_broken_cover,
        folders_without_cover=folders_without_cover,
        problems=tuple(problems),
    )


def _flac_picture(cover: CoverImage) -> Picture:
    picture = Picture()
    picture.type = FRONT_COVER
    picture.mime = cover.mime
    picture.desc = COVER_DESCRIPTION
    picture.width = cover.width
    picture.height = cover.height
    picture.depth = cover.depth
    picture.colors = cover.colors
    picture.data = cover.data
    return picture


def _ape_payload(cover: CoverImage) -> bytes:
    # APEv2 stores the picture as "file name" + NUL + binary image data.
    return cover.path.name.encode("utf-8") + b"\x00" + cover.data


def _kept_pictures(pictures: list) -> list:
    """Pictures that survive replacing the cover of a file.

    Only the picture the analysis shows as the cover and other front covers
    are replaced; a back cover, booklet scans or an artist photo stay.
    """
    if not pictures:
        return []
    replaced = front_picture(pictures)
    return [
        picture
        for picture in pictures
        if picture is not replaced and picture.type != FRONT_COVER
    ]


def write_cover(path: Path, cover: CoverImage) -> None:
    """Write ``cover`` as the front cover of ``path``; other pictures stay."""
    if mutagen is None:
        raise RuntimeError("Не установлена библиотека Mutagen")
    audio = mutagen.File(path)
    if audio is None:
        raise ValueError("формат файла не распознан")
    if FLAC is not None and isinstance(audio, FLAC):
        kept = _kept_pictures(audio.pictures)
        audio.clear_pictures()
        # The new cover goes first: players that show the first picture agree
        # with the analysis.
        audio.add_picture(_flac_picture(cover))
        for picture in kept:
            audio.add_picture(picture)
        audio.save()
        return
    if MP4 is not None and isinstance(audio, MP4):
        if getattr(audio, "tags", None) is None:
            audio.add_tags()
        # The MP4 "covr" atom knows only JPEG and PNG; storing WebP there
        # would produce a cover that players cannot display.
        if cover.mime == "image/png":
            image_format = MP4Cover.FORMAT_PNG
        elif cover.mime == "image/jpeg":
            image_format = MP4Cover.FORMAT_JPEG
        else:
            raise ValueError("M4A поддерживает только обложки JPEG и PNG")
        # covr[0] is the cover the analysis shows; further images stay.
        others = list(audio.tags.get("covr", []))[1:]
        audio["covr"] = [MP4Cover(cover.data, imageformat=image_format), *others]
        audio.save()
        return
    tags = getattr(audio, "tags", None)
    if tags is None:
        add_tags = getattr(audio, "add_tags", None)
        if callable(add_tags):
            add_tags()
            tags = getattr(audio, "tags", None)
    if ID3 is not None and isinstance(tags, ID3):
        kept = _kept_pictures(tags.getall("APIC"))
        tags.delall("APIC")
        for frame in kept:
            tags.add(frame)
        # Frames are keyed "APIC:<desc>": a kept picture that already uses the
        # name must not be overwritten by the new one.
        description = COVER_DESCRIPTION
        while f"APIC:{description}" in tags:
            description += " "
        tags.add(
            APIC(
                encoding=3,
                mime=cover.mime,
                type=FRONT_COVER,
                desc=description,
                data=cover.data,
            )
        )
        audio.save(**id3_save_options(tags))
        return
    if APEv2 is not None and isinstance(tags, APEv2):
        tags[APE_COVER_KEY] = APEValue(_ape_payload(cover), BINARY)
        audio.save()
        return
    raise ValueError(f"формат {type(audio).__name__} не поддерживается утилитой")


def verify_cover(path: Path, cover: CoverImage) -> None:
    """Re-read the written file and compare the embedded picture."""
    data, _mime, error = read_embedded_cover(path)
    if data is None:
        reason = f"обложка не найдена после записи: {error}" if error else (
            "обложка не найдена после записи"
        )
        raise ValueError(reason)
    if hashlib.sha256(data).hexdigest() != cover.digest:
        raise ValueError("проверка обложки после записи не пройдена")


def _embed_file(
    path: Path,
    cover: CoverImage,
    root: Path,
    backup_root: Path | None,
) -> bool:
    temporary = temporary_copy(path, prefix=f".{path.stem}-cover-")
    try:
        write_cover(temporary, cover)
        verify_cover(temporary, cover)
        backup_created = False
        if backup_root is not None:
            backup_copy(path, root, backup_root)
            backup_created = True
        replace_preserving_times(temporary, path)
        return backup_created
    finally:
        temporary.unlink(missing_ok=True)


def embed_covers(
    plan: CoverPlan,
    *,
    backup_root: Path | None = None,
    stop_event: threading.Event | None = None,
    progress: EmbedProgress | None = None,
) -> CoverEmbedResult:
    """Embed every planned cover, verifying each written file."""
    jobs = [
        (target, folder.cover)
        for folder in plan.folders
        for target in folder.targets
    ]
    updated_files = 0
    backup_files = 0
    failures: list[CoverEmbedFailure] = []
    updated_folders: set[Path] = set()
    stopped = False
    for index, (target, cover) in enumerate(jobs, start=1):
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        try:
            backup_created = _embed_file(target.path, cover, plan.root, backup_root)
            updated_files += 1
            backup_files += int(backup_created)
            updated_folders.add(target.path.parent)
        except Exception as exc:
            failures.append(CoverEmbedFailure(target.path, str(exc)))
        if progress is not None:
            progress(index, len(jobs), target.relative_path)
    return CoverEmbedResult(
        folders_updated=len(updated_folders),
        updated_files=updated_files,
        backup_files=backup_files,
        failures=tuple(failures),
        stopped=stopped,
    )
