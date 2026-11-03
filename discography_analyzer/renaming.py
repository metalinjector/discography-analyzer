"""«Имена по тегам»: release folders, disc folders and files named by templates.

The rules are those of the Tags-Discography-Normalizer scripts (steps 08, 15,
22, 27, 28, 33, 46, 47): a release folder «1972 Irrlicht (Qobuz, Brain,
0004228331272)», a disc folder «CD2», a file «01. Satz Ebene.flac», a guest
track «13. Bang Bang (Jessie J, Nicki Minaj feat. Ariana Grande).flac». Names
come from the tags only. Nothing is moved to another folder and nothing is
overwritten; every rename goes to a journal line before the next one starts,
so a whole run can be undone.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from .completeness import parse_position, track_disc
from .fileops import iter_folders, list_audio_files
from .models import Track
from .online.album import read_track
from .parsing import disc_number_of_folder
from .releases import (
    WINDOWS_PATH_LIMIT,
    Release,
    build_releases,
    split_names,
)
from .settings import settings_path

# Longest file or folder name NTFS, ext4 and APFS accept.
NAME_LIMIT = 255

RELEASE_FIELDS = {
    "year": "год (4 цифры)",
    "album": "альбом",
    "albumartist": "исполнитель альбома",
    "artists": "исполнители релиза",
    "duo": "два исполнителя через запятую, если их ровно два",
    "label": "лейбл",
    "barcode": "BARCODE",
    "source": "источник: поле «Источник» или сайт из тега URL",
    "type": "Album, EP или Single",
    "genre": "жанр",
    "24bit": "«24Bit», если все файлы 24-битные",
}
TRACK_FIELDS = {
    "track": "номер трека, {track:02} — двумя цифрами",
    "disc": "номер диска",
    "title": "название",
    "artist": "исполнитель трека",
    "guests": "гости этого трека (меньше 30 % треков релиза)",
}
FIELD_LABELS = {
    "year": "года",
    "album": "тега Album",
    "albumartist": "исполнителя альбома",
    "artists": "исполнителей",
    "duo": "двух исполнителей",
    "label": "лейбла",
    "barcode": "BARCODE",
    "source": "источника",
    "type": "типа",
    "genre": "жанра",
    "24bit": "24 бит",
    "track": "Track #",
    "disc": "Disc #",
    "title": "тега Title",
    "artist": "исполнителя",
    "guests": "гостей",
}

# The schemes of the archive first: what the normalizer scripts produced.
FOLDER_TEMPLATES = (
    "{year} {album}< [{duo}]>< ({source}, {label}, {barcode})>< {24bit}>",
    "{year} - {album}",
    "{album}< ({year})>",
    "{albumartist} - {year} - {album}",
)
FILE_TEMPLATES = (
    "{track:02}. {title}< ({guests} feat. {albumartist})>",
    "{track:02}. {title}",
    "{track:02} - {title}",
    "{track:02}. {artist} - {title}",
)

# The site in a URL tag names the shop the files came from:
# «https://open.qobuz.com/track/45973622» → Qobuz.
SOURCE_SITES = (
    ("qobuz.com", "Qobuz"),
    ("deezer.com", "Deezer"),
    ("tidal.com", "Tidal"),
    ("music.apple.com", "Apple Music"),
    ("itunes.apple.com", "Apple Music"),
    ("bandcamp.com", "Bandcamp"),
    ("beatport.com", "Beatport"),
    ("7digital.com", "7digital"),
    ("hdtracks.com", "HDtracks"),
    ("prestomusic.com", "Presto Music"),
    ("spotify.com", "Spotify"),
    ("amazon.", "Amazon Music"),
)
URL_KEY_RE = re.compile(r"url|www|^w[a-z]{3}(?::|$)")
FIELD_RE = re.compile(r"(?P<name>[a-z0-9]+)(?::0?(?P<width>[1-9]))?")
# Windows refuses these names with any extension.
RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}

ProgressCallback = Callable[[int, int, str], None]


class TemplateError(ValueError):
    """The template cannot be read: the message says what is wrong."""


class RenameStopped(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Field:
    name: str
    width: int


@dataclass(frozen=True, slots=True)
class _Group:
    parts: tuple


def parse_template(text: str, allowed: Iterable[str]) -> tuple:
    """Literal text, ``{field}`` and ``<optional part>``.

    A part in angle brackets disappears when a field directly inside it is
    empty. «<» and «>» can never be part of a file name, so they are free to
    mark the optional parts.
    """
    allowed = set(allowed)
    stack: list[list] = [[]]
    literal: list[str] = []

    def flush() -> None:
        if literal:
            stack[-1].append("".join(literal))
            literal.clear()

    index = 0
    while index < len(text):
        char = text[index]
        if char == "{":
            end = text.find("}", index)
            if end == -1:
                raise TemplateError("Нет закрывающей скобки «}»")
            body = text[index + 1 : end].strip().casefold()
            match = FIELD_RE.fullmatch(body)
            if not match:
                raise TemplateError(f"Непонятное поле «{{{body}}}»")
            name = match.group("name")
            if name not in allowed:
                if name in TRACK_FIELDS:
                    raise TemplateError(f"Поле {{{name}}} есть только в имени файла")
                raise TemplateError(f"Неизвестное поле {{{name}}}")
            flush()
            stack[-1].append(_Field(name, int(match.group("width") or 0)))
            index = end + 1
            continue
        if char == "}":
            raise TemplateError("Лишняя скобка «}»")
        if char == "<":
            flush()
            stack.append([])
        elif char == ">":
            flush()
            if len(stack) == 1:
                raise TemplateError("Лишняя скобка «>»")
            group = _Group(tuple(stack.pop()))
            stack[-1].append(group)
        else:
            literal.append(char)
        index += 1
    flush()
    if len(stack) > 1:
        raise TemplateError("Нет закрывающей скобки «>»")
    if not any(isinstance(part, (_Field, _Group)) for part in stack[0]):
        raise TemplateError("В шаблоне нет ни одного поля")
    return tuple(stack[0])


def _render(parts: tuple, values: dict[str, str]) -> tuple[str, list[str], int, bool]:
    """(text, empty fields, fields seen, an optional part was kept)."""
    out: list[str] = []
    missing: list[str] = []
    direct = 0
    kept = False
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif isinstance(part, _Field):
            direct += 1
            value = values.get(part.name, "")
            if not value:
                missing.append(part.name)
                continue
            if part.width and value.isdigit():
                value = value.zfill(part.width)
            out.append(value)
        else:
            text, inner_missing, inner_direct, inner_kept = _render(part.parts, values)
            if not inner_missing and (inner_direct or inner_kept):
                out.append(text)
                kept = True
    return "".join(out), missing, direct, kept


def clean_component(value: str) -> str:
    """A tag value made fit for a name — the normalizer's ``pretty()``.

    «Title: Part» → «Title - Part», «AC/DC» → «AC - DC», «?» dropped,
    «"» → «'», runs of spaces and dangling dashes tidied, no trailing dot.
    """
    text = value.replace(": (", " (").replace(": ", " - ").replace(":", "-")
    text = text.replace("/", " - ").replace("?", "").replace('"', "'")
    text = text.replace("*", " ").replace("\\", " - ")
    text = text.replace("<", "").replace(">", "").replace("|", "")
    text = "".join(char for char in text if char >= " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*-\s*-\s*", " - ", text)
    text = re.sub(r"(?<=\S)-\s", " - ", text)
    text = re.sub(r"\s+-\s*", " - ", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return text.strip(" -").rstrip(" .")


def _safe_name(name: str, *, folder: bool) -> str:
    """What a template's own text may still carry: no «/», no «:», no «?»."""
    name = "".join(char for char in name if char >= " ")
    name = re.sub(r"[/\\]", " - ", name).replace(":", "-")
    name = re.sub(r'[?*<>|"]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    if folder:
        name = name.rstrip(" .")
    if name.split(".")[0].casefold() in RESERVED_NAMES:
        name = f"{name}_"
    return name


def render_name(
    parts: tuple, values: dict[str, str], *, suffix: str = ""
) -> tuple[str, list[str]]:
    """(name, empty required fields). An empty field outside ``<…>`` stops it."""
    text, missing, _direct, _kept = _render(parts, values)
    if missing:
        return "", missing
    name = _safe_name(text, folder=not suffix)
    return (f"{name}{suffix}" if name else ""), []


def detect_source(tracks: Iterable[Track]) -> str:
    """«Qobuz» from «https://open.qobuz.com/track/…» in a URL tag."""
    for track in tracks:
        for key, values in track.all_tags.items():
            if not URL_KEY_RE.search(key.casefold()):
                continue
            for value in values:
                lowered = str(value).casefold()
                for site, name in SOURCE_SITES:
                    if site in lowered:
                        return name
    return ""


def source_from_folder(name: str, barcode: str) -> str:
    """«Qobuz» from a folder already named «… (Qobuz, Brain, 0004228331272)».

    Only next to the release's own barcode: a folder of the archive scheme
    keeps its source even when the files carry no URL tag.
    """
    if not barcode:
        return ""
    match = re.search(r"\(([^,()]+),[^()]*,\s*" + re.escape(barcode) + r"\)", name)
    return match.group(1).strip() if match else ""


def release_values(release: Release, source: str) -> dict[str, str]:
    """The release fields of a template, already fit for a name."""
    has_album = any(track.album.strip() for track in release.tracks)
    # «The Weeknd, Ariana Grande» are two names; «Simon & Garfunkel» is one.
    names: list[str] = []
    for name in (
        *re.split(r"\s*[,;]\s*", release.album_artist),
        *release.co_artists,
    ):
        if name.strip() and name.casefold() not in {item.casefold() for item in names}:
            names.append(name.strip())
    lossless_24 = bool(release.tracks) and all(
        track.bit_depth == 24 for track in release.tracks
    )
    values = {
        "year": release.year,
        "album": release.album if has_album else "",
        "albumartist": release.album_artist,
        "artists": release.artists,
        "duo": ", ".join(names) if len(names) == 2 else "",
        "label": release.label,
        "barcode": release.barcodes[0] if release.barcodes else "",
        "source": source.strip()
        or detect_source(release.tracks)
        or source_from_folder(
            release.path.name, release.barcodes[0] if release.barcodes else ""
        ),
        "type": release.type_name,
        "genre": release.genre,
        "24bit": "24Bit" if lossless_24 else "",
    }
    return {key: clean_component(value) for key, value in values.items()}


def track_values(
    track: Track, release: Release, base: dict[str, str]
) -> dict[str, str]:
    number, _total = parse_position(track.track_number)
    guest_keys = {name.casefold() for name in release.guests}
    artist_values = track.canonical_tags.get("artist") or [track.artist]
    names = [
        name
        for value in artist_values
        if value and value.strip()
        for name in split_names(value)
    ]
    guests = list(
        dict.fromkeys(name for name in names if name.casefold() in guest_keys)
    )
    values = dict(base)
    values.update(
        {
            "track": str(number) if number else "",
            "disc": str(track_disc(track)),
            "title": clean_component(track.title),
            "artist": clean_component(
                ", ".join(value for value in artist_values if value.strip())
            ),
            "guests": clean_component(", ".join(guests)),
        }
    )
    return values


@dataclass(frozen=True, slots=True)
class NamingScheme:
    folder_template: str = FOLDER_TEMPLATES[0]
    file_template: str = FILE_TEMPLATES[0]
    rename_folders: bool = True
    rename_files: bool = True
    disc_folders: bool = True
    source: str = ""


@dataclass(slots=True)
class RenameItem:
    kind: str  # "folder" — a release folder, "disc" — «CD2», "file"
    source: Path
    target: Path
    release: str
    problem: str = ""
    selected: bool = True
    folder: Path | None = None  # the release folder, to group the preview by

    @property
    def changes(self) -> bool:
        return self.source.name != self.target.name


@dataclass(slots=True)
class RenamePlan:
    root: Path
    items: list[RenameItem]
    unchanged: int = 0
    releases: int = 0

    def chosen(self) -> list[RenameItem]:
        return [item for item in self.items if item.selected and not item.problem]

    def count(self, kind: str) -> int:
        return sum(item.kind == kind for item in self.chosen())

    @property
    def problems(self) -> int:
        return sum(bool(item.problem) for item in self.items)


def read_tracks(
    root: Path,
    *,
    extensions: Iterable[str],
    include_subfolders: bool = True,
    excluded_folders: Iterable[str] = (),
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> list[Track]:
    """Read the tags of every audio file below ``root``, as the analysis does."""
    wanted = {extension.casefold() for extension in extensions}
    paths = [
        path
        for folder in iter_folders(root, include_subfolders, excluded_folders)
        for path in list_audio_files(folder, wanted)
    ]
    tracks: list[Track] = []
    for index, path in enumerate(paths, start=1):
        if stop_event is not None and stop_event.is_set():
            raise RenameStopped
        if progress is not None:
            progress(index, len(paths), str(path))
        try:
            tracks.append(read_track(path, root))
        except OSError:
            continue  # vanished or unreadable, as in the scan
    return tracks


def _missing_text(missing: list[str]) -> str:
    labels = list(dict.fromkeys(FIELD_LABELS.get(name, name) for name in missing))
    return "нет " + ", ".join(labels)


def plan_renames(
    root: Path,
    tracks: list[Track],
    scheme: NamingScheme,
    *,
    protected: Path | None = None,
) -> RenamePlan:
    """Every name the scheme changes, with the reason when one cannot change.

    ``protected`` is a folder that must keep its name: the collection open in
    the main window.
    """
    folder_parts = (
        parse_template(scheme.folder_template, RELEASE_FIELDS)
        if scheme.rename_folders
        else None
    )
    file_parts = (
        parse_template(scheme.file_template, {*RELEASE_FIELDS, *TRACK_FIELDS})
        if scheme.rename_files
        else None
    )
    releases = build_releases(tracks, root)
    items: list[RenameItem] = []
    unchanged = 0
    for release in releases:
        base = release_values(release, scheme.source)
        first = len(items)
        if file_parts is not None:
            for track in release.tracks:
                name, missing = render_name(
                    file_parts,
                    track_values(track, release, base),
                    suffix=track.path.suffix,
                )
                if missing:
                    items.append(
                        RenameItem(
                            "file",
                            track.path,
                            track.path,
                            release.title,
                            _missing_text(missing),
                            False,
                        )
                    )
                elif name == track.path.name:
                    unchanged += 1
                else:
                    items.append(
                        RenameItem(
                            "file",
                            track.path,
                            track.path.with_name(name),
                            release.title,
                        )
                    )
        if scheme.disc_folders:
            unchanged += _plan_disc_folders(release, root, protected, items)
        if folder_parts is not None:
            unchanged += _plan_release_folder(
                release, releases, root, protected, folder_parts, base, items
            )
        for item in items[first:]:
            item.folder = release.path
    _check_names(items)
    _check_lengths(items, tracks)
    for item in items:
        if item.problem:
            item.selected = False
    return RenamePlan(
        root=root, items=items, unchanged=unchanged, releases=len(releases)
    )


def _plan_disc_folders(
    release: Release, root: Path, protected: Path | None, items: list[RenameItem]
) -> int:
    unchanged = 0
    folders = dict.fromkeys(
        track.path.parent
        for track in release.tracks
        if track.path.parent != release.path
    )
    for folder in folders:
        number = disc_number_of_folder(folder.name)
        if number is None or folder in (root, protected):
            continue
        name = f"CD{number}"
        if folder.name == name:
            unchanged += 1
            continue
        discs = {
            track_disc(track) for track in release.tracks if track.path.parent == folder
        }
        problem = "" if discs == {number} else "Disc # в тегах не совпадает с папкой"
        items.append(
            RenameItem("disc", folder, folder.with_name(name), release.title, problem)
        )
    return unchanged


def _plan_release_folder(
    release: Release,
    releases: list[Release],
    root: Path,
    protected: Path | None,
    parts: tuple,
    values: dict[str, str],
    items: list[RenameItem],
) -> int:
    folder = release.path
    if folder == protected or folder.parent == folder:
        return 0
    if folder == root and disc_number_of_folder(folder.name) is not None:
        return 0  # a «CD2» chosen alone: its files only
    name, missing = render_name(parts, values)
    problem = _missing_text(missing) if missing else ""
    others = [
        other
        for other in releases
        if other is not release
        and (other.path == folder or folder in other.path.parents)
    ]
    if others:
        problem = "в папке не один релиз"
    if not problem and name == folder.name:
        return 1
    target = folder.with_name(name) if name else folder
    items.append(RenameItem("folder", folder, target, release.title, problem))
    return 0


def _same_entry(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(_os_path(first), _os_path(second))
    except OSError:
        return False


def _check_names(items: list[RenameItem]) -> None:
    """Too long, already taken, or the same new name twice in one folder."""
    by_target: dict[tuple[str, str], list[RenameItem]] = defaultdict(list)
    for item in items:
        if item.problem:
            continue
        if len(item.target.name) > NAME_LIMIT:
            item.problem = f"имя длиннее {NAME_LIMIT} символов"
            continue
        if _exists(item.target) and not _same_entry(item.source, item.target):
            item.problem = f"«{item.target.name}» уже есть"
            continue
        key = (str(item.target.parent).casefold(), item.target.name.casefold())
        by_target[key].append(item)
    for group in by_target.values():
        if len(group) > 1:
            for item in group:
                item.problem = "у другого файла то же новое имя"


def _final_path(
    path: Path, files: dict[Path, Path], folders: list[tuple[Path, Path]]
) -> Path:
    """Where ``path`` ends up: its own new name, then its renamed folders."""
    result = files.get(path, path)
    for old, new in folders:  # deepest first
        if old in result.parents:
            result = new / result.relative_to(old)
    return result


def _check_lengths(items: list[RenameItem], tracks: list[Track]) -> None:
    """No rename may push a path over the 259 characters Windows can open.

    A folder is blamed only when its new name is longer than the old one; a
    file whose own new name makes the path too long is skipped itself.
    """

    def mappings() -> tuple[dict[Path, Path], list[tuple[Path, Path]]]:
        ok = [item for item in items if not item.problem]
        files = {item.source: item.target for item in ok if item.kind == "file"}
        folders = sorted(
            ((item.source, item.target) for item in ok if item.kind != "file"),
            key=lambda pair: len(pair[0].parts),
            reverse=True,
        )
        return files, folders

    files, folders = mappings()
    growing = {
        item.source: item
        for item in items
        if not item.problem
        and item.kind != "file"
        and len(item.target.name) > len(item.source.name)
    }
    if growing:
        for track in tracks:
            owners = [
                growing[parent] for parent in track.path.parents if parent in growing
            ]
            if not owners:
                continue
            final = len(str(_final_path(track.path, files, folders)))
            if final > WINDOWS_PATH_LIMIT and final > len(str(track.path)):
                for owner in owners:
                    owner.problem = owner.problem or (
                        f"путь файла станет {final} > {WINDOWS_PATH_LIMIT}"
                    )
    files, folders = mappings()
    for item in items:
        if item.problem or item.kind != "file":
            continue
        final = len(str(_final_path(item.source, files, folders)))
        if final > WINDOWS_PATH_LIMIT and final > len(str(item.source)):
            item.problem = f"путь станет {final} > {WINDOWS_PATH_LIMIT}"


# -- doing it --------------------------------------------------------------


def _os_path(path: Path) -> str:
    """Windows opens a path over 259 characters only with the «\\\\?\\» prefix."""
    text = str(path)
    if sys.platform != "win32" or len(text) < 240 or text.startswith("\\\\?\\"):
        return text
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _exists(path: Path) -> bool:
    return os.path.lexists(_os_path(path))


# Explorer, the search indexer or an antivirus may hold a folder for a moment
# on Windows: the normalizer scripts retried such a rename and so does this.
RENAME_ATTEMPTS = 3
RENAME_RETRY_DELAY = 1.0


def _os_rename(source: Path, target: Path) -> None:
    attempts = RENAME_ATTEMPTS if sys.platform == "win32" else 1
    for attempt in range(attempts):
        try:
            os.rename(_os_path(source), _os_path(target))
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(RENAME_RETRY_DELAY)


def rename_entry(source: Path, target: Path) -> None:
    """Rename one file or folder; an existing name is never overwritten.

    A change of letter case only («cd1» → «CD1») goes through a temporary
    name: on Windows and macOS the new name «exists» — it is the same entry.
    """
    if not _exists(source):
        raise FileNotFoundError("его больше нет на месте")
    if _exists(target):
        if not _same_entry(source, target):
            raise FileExistsError(f"«{target.name}» уже есть")
        if source.name == target.name:
            return
        temporary = source.with_name(f".{source.name}.{secrets.token_hex(4)}.renaming")
        _os_rename(source, temporary)
        try:
            _os_rename(temporary, target)
        except OSError:
            _os_rename(temporary, source)
            raise
        return
    _os_rename(source, target)


@dataclass(slots=True)
class RenameResult:
    renamed: int = 0
    failures: list[tuple[Path, str]] = field(default_factory=list)
    journal: Path | None = None
    stopped: bool = False
    root: Path | None = None  # the chosen folder after the run (renamed or not)


def journal_folder() -> Path:
    return settings_path().with_name("renames")


def apply_renames(
    plan: RenamePlan,
    *,
    journal_dir: Path | None = None,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> RenameResult:
    """Rename the chosen items: files, then disc folders, then release folders.

    Children go first so every recorded path is valid when it is renamed;
    undoing in the reverse order restores the folders before their files.
    """
    order = {"file": 0, "disc": 1, "folder": 2}
    chosen = sorted(
        plan.chosen(),
        key=lambda item: (order[item.kind], -len(item.source.parts)),
    )
    result = RenameResult(root=plan.root)
    if not chosen:
        return result
    folder = journal_dir or journal_folder()
    folder.mkdir(parents=True, exist_ok=True)
    journal = folder / f"{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}.jsonl"
    with journal.open("w", encoding="utf-8") as handle:
        header = {
            "journal": 1,
            "root": str(plan.root),
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        handle.flush()
        for index, item in enumerate(chosen, start=1):
            if stop_event is not None and stop_event.is_set():
                result.stopped = True
                break
            if progress is not None:
                progress(index, len(chosen), item.source.name)
            try:
                rename_entry(item.source, item.target)
            except OSError as exc:
                result.failures.append((item.source, str(exc) or type(exc).__name__))
                continue
            entry = {
                "kind": item.kind,
                "old": str(item.source),
                "new": str(item.target),
            }
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
            result.renamed += 1
            if item.source == plan.root:
                result.root = item.target
    if result.renamed:
        result.journal = journal
    else:
        journal.unlink(missing_ok=True)
    return result


@dataclass(slots=True)
class RenameJournal:
    path: Path
    root: Path
    created: str
    entries: list[tuple[str, Path, Path]]  # (kind, old, new) in the order done


def read_journal(path: Path) -> RenameJournal | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lines:
        return None
    try:
        header = json.loads(lines[0])
        entries = [json.loads(line) for line in lines[1:] if line.strip()]
    except ValueError:
        return None
    if not isinstance(header, dict) or header.get("journal") != 1:
        return None
    done = [
        (str(entry.get("kind", "")), Path(entry["old"]), Path(entry["new"]))
        for entry in entries
        if isinstance(entry, dict) and "old" in entry and "new" in entry
    ]
    return RenameJournal(
        path, Path(str(header.get("root", ""))), str(header.get("created", "")), done
    )


def latest_journal(journal_dir: Path | None = None) -> RenameJournal | None:
    """The last run that has not been undone yet."""
    folder = journal_dir or journal_folder()
    try:
        candidates = sorted(
            folder.glob("*.jsonl"), key=lambda path: path.name, reverse=True
        )
    except OSError:
        return None
    for path in candidates:
        if path.name.endswith(".undone.jsonl"):
            continue
        journal = read_journal(path)
        if journal is not None and journal.entries:
            return journal
    return None


def undo_journal(
    journal: RenameJournal,
    *,
    stop_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> RenameResult:
    """Give every name of a run back, the last rename first.

    What could not be undone stays in the journal, so the next attempt tries
    only those; a fully undone journal is kept as «….undone.jsonl».
    """
    result = RenameResult(root=journal.root)
    remaining: list[tuple[str, Path, Path]] = []
    entries = list(reversed(journal.entries))
    for index, (kind, old, new) in enumerate(entries, start=1):
        if stop_event is not None and stop_event.is_set():
            result.stopped = True
            remaining.extend(entries[index - 1 :])
            break
        if progress is not None:
            progress(index, len(entries), new.name)
        try:
            rename_entry(new, old)
        except OSError as exc:
            result.failures.append((new, str(exc) or type(exc).__name__))
            remaining.append((kind, old, new))
            continue
        result.renamed += 1
    if remaining:
        header = {"journal": 1, "root": str(journal.root), "created": journal.created}
        lines = [json.dumps(header, ensure_ascii=False)] + [
            json.dumps(
                {"kind": kind, "old": str(old), "new": str(new)}, ensure_ascii=False
            )
            for kind, old, new in reversed(remaining)
        ]
        journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result.journal = journal.path
    else:
        undone = journal.path.with_name(
            journal.path.name.removesuffix(".jsonl") + ".undone.jsonl"
        )
        journal.path.replace(undone)
        result.journal = undone
    return result


# -- remembered choices ----------------------------------------------------


def preferences_path() -> Path:
    return settings_path().with_name("renaming.json")


def load_scheme(path: Path | None = None) -> NamingScheme:
    defaults = NamingScheme()
    try:
        data = json.loads((path or preferences_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    values = {
        item.name: data[item.name]
        for item in fields(NamingScheme)
        if type(data.get(item.name)) is type(getattr(defaults, item.name))
    }
    return NamingScheme(**values)


def save_scheme(scheme: NamingScheme, path: Path | None = None) -> None:
    target = path or preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(scheme), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(target)
