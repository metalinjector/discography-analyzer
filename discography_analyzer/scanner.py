from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .classifier import classify_tracks
from .completeness import analyze_track_completeness
from .constants import SUPPORTED_FORMATS
from .metadata import read_metadata
from .metadata_audit import audit_metadata
from .models import AnalysisResult, Track, TrackStatus
from .parsing import title_from_filename

ProgressCallback = Callable[[int, str, int, int, int], None]


class AnalysisStopped(RuntimeError):
    pass


class NoAudioFilesError(RuntimeError):
    pass


class NoSelectedFormatsError(RuntimeError):
    pass


def _date_text(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _collect_files(
    root: Path,
    include_subfolders: bool,
    excluded_folders: list[str],
    selected_extensions: set[str],
    stop_event: threading.Event,
    progress: ProgressCallback,
) -> tuple[list[Path], int]:
    files: list[Path] = []
    supported_seen = 0
    folders_scanned = 0
    excluded = {name.casefold() for name in excluded_folders if name.strip()}

    if include_subfolders:
        for current, directories, names in os.walk(root):
            if stop_event.is_set():
                raise AnalysisStopped
            directories[:] = [
                name
                for name in directories
                if name.casefold() not in excluded and not name.startswith(".")
            ]
            directories.sort(key=str.casefold)
            names.sort(key=str.casefold)
            folders_scanned += 1
            progress(0, f"Сканирование папки: {current}", len(files), folders_scanned, 0)
            for name in names:
                suffix = Path(name).suffix.casefold()
                if suffix in SUPPORTED_FORMATS.values():
                    supported_seen += 1
                    if suffix in selected_extensions:
                        files.append(Path(current) / name)
    else:
        folders_scanned = 1
        for item in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if stop_event.is_set():
                raise AnalysisStopped
            if item.is_file() and item.suffix.casefold() in SUPPORTED_FORMATS.values():
                supported_seen += 1
                if item.suffix.casefold() in selected_extensions:
                    files.append(item)
        progress(0, f"Сканирование папки: {root}", len(files), folders_scanned, 0)

    if supported_seen == 0:
        raise NoAudioFilesError("Аудиофайлы не найдены в выбранной директории")
    if not files:
        raise NoSelectedFormatsError("Аудиофайлы выбранных форматов не найдены")
    return files, folders_scanned


def analyze_collection(
    root: Path,
    include_subfolders: bool,
    selected_formats: list[str],
    excluded_folders: list[str],
    use_tags: bool,
    detect_variations: bool,
    check_track_gaps: bool,
    variation_markers: list[str],
    stop_event: threading.Event,
    progress: ProgressCallback,
) -> AnalysisResult:
    selected_extensions = {
        SUPPORTED_FORMATS[name] for name in selected_formats if name in SUPPORTED_FORMATS
    }
    progress(0, "Подсчёт файлов...", 0, 0, 0)
    files, folders_scanned = _collect_files(
        root,
        include_subfolders,
        excluded_folders,
        selected_extensions,
        stop_event,
        progress,
    )

    tracks: list[Track] = []
    skipped_files = 0
    total = len(files)
    for index, path in enumerate(files, start=1):
        if stop_event.is_set():
            raise AnalysisStopped
        try:
            stat = path.stat()
            relative = path.relative_to(root)
            relative_folder = str(relative.parent)
            if relative_folder == ".":
                relative_folder = "(корень)"
            track = Track(
                id=uuid.uuid4().hex,
                path=path,
                root=root,
                filename=path.name,
                relative_path=str(relative),
                relative_folder=relative_folder,
                format=path.suffix[1:].upper(),
                size_bytes=stat.st_size,
                modified_at=_date_text(stat.st_mtime),
                created_at=_date_text(stat.st_ctime),
                filename_title=title_from_filename(path.name),
            )
            read_metadata(track)
            tracks.append(track)
        except OSError:
            skipped_files += 1
            continue
        percent = min(95, round(index / total * 95))
        progress(
            percent,
            f"Анализ файла: …{str(path)[-90:]}",
            len(tracks),
            folders_scanned,
            0,
        )

    if stop_event.is_set():
        raise AnalysisStopped
    classify_tracks(tracks, use_tags, detect_variations, variation_markers)
    completeness_issues = (
        analyze_track_completeness(tracks) if check_track_gaps else []
    )
    progress(
        97,
        "Аудит метаданных...",
        len(tracks),
        folders_scanned,
        sum(track.status == TrackStatus.VARIATION for track in tracks),
    )
    audit_issues = audit_metadata(tracks)
    variations = sum(track.status == TrackStatus.VARIATION for track in tracks)
    final_state = "Анализ завершён!"
    if skipped_files:
        final_state += f" Пропущено недоступных файлов: {skipped_files}"
    progress(100, final_state, len(tracks), folders_scanned, variations)
    return AnalysisResult(
        tracks=tracks,
        folders_scanned=folders_scanned,
        root=root,
        completeness_issues=completeness_issues,
        audit_issues=audit_issues,
    )
