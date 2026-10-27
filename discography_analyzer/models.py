from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .audit_models import AuditSeverity, MetadataAuditIssue
from .parsing import files_word


class TrackStatus(str, Enum):
    UNIQUE = "Уникальный"
    DUPLICATE = "Дубликат"
    VARIATION = "Вариация"
    CONFLICT = "Конфликт"

    @property
    def decorated(self) -> str:
        return {
            TrackStatus.UNIQUE: "● Уникальный",
            TrackStatus.DUPLICATE: "● Дубликат",
            TrackStatus.VARIATION: "● Вариация",
            TrackStatus.CONFLICT: "● Конфликт",
        }[self]


def _clock(seconds: int) -> str:
    """«3:05» or «1:02:13» for a duration in whole seconds."""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


@dataclass(slots=True)
class Track:
    id: str
    path: Path
    root: Path
    filename: str
    relative_path: str
    relative_folder: str
    format: str
    size_bytes: int
    modified_at: str = ""
    created_at: str = ""
    filename_title: str = ""
    comparison_title: str = ""
    base_title: str = ""
    variation: str = ""
    potential_base: str = ""
    potential_variation: str = ""
    source_track_id: str | None = None
    relation: str = ""
    related_track_ids: list[str] = field(default_factory=list)
    duplicate_group_id: str = ""
    collection_warning: str = ""
    collection_issue_id: str = ""
    status: TrackStatus = TrackStatus.UNIQUE
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: str = ""
    disc_number: str = ""
    year: str = ""
    genre: str = ""
    comment: str = ""
    duration_seconds: int | None = None
    duration_exact: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    channel_mode: str = ""
    bitrate_mode: str = ""
    codec: str = ""
    encoder: str = ""
    encoder_settings: str = ""
    version: str = ""
    layer: str = ""
    protection: str = ""
    track_gain: str = ""
    track_peak: str = ""
    album_gain: str = ""
    album_peak: str = ""
    all_tags: dict[str, list[str]] = field(default_factory=dict)
    canonical_tags: dict[str, list[str]] = field(default_factory=dict)
    cover_mime: str = ""
    cover_size: int = 0
    cover_hash: str = ""
    cover_width: int = 0
    cover_height: int = 0
    cover_error: str = ""
    metadata_errors: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1024 / 1024

    @property
    def duration_display(self) -> str:
        if self.duration_seconds is None:
            return ""
        return _clock(self.duration_seconds)

    @property
    def bitrate_display(self) -> str:
        return f"{round(self.bitrate / 1000)} kbps" if self.bitrate else ""

    @property
    def comparison_duration(self) -> float | int | None:
        """Single duration contract shared by classification and copying."""
        if self.duration_exact is not None:
            return self.duration_exact
        return self.duration_seconds

    def _table_values(self) -> dict[str, Any]:
        return {
            "status": self.status.decorated,
            "base_title": self.base_title,
            "variation": self.variation or "—",
            "relation": self.relation or "—",
            "collection_warning": self.collection_warning or "—",
            "relative_folder": self.relative_folder,
            "filename": self.filename,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "genre": self.genre,
            "duration": self.duration_display,
            "bitrate": self.bitrate_display,
            "sample_rate": self.sample_rate or "",
            "bit_depth": self.bit_depth or "",
            "format": self.format,
            "size_mb": round(self.size_mb, 2),
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "album_artist": self.album_artist,
            "comment": self.comment,
            "path": str(self.path),
        }

    def table_value(self, field_name: str) -> Any:
        return self._table_values().get(field_name, "")

    def table_row(self, fields: list[str]) -> list[Any]:
        values = self._table_values()
        return [values.get(field, "") for field in fields]

    def search_text(self) -> str:
        return "\n".join(
            (
                self.base_title,
                self.title,
                self.artist,
                self.album,
                Path(self.relative_folder).name,
                self.relative_folder,
                self.filename,
                self.variation,
                self.relation,
                self.collection_warning,
            )
        ).casefold()


@dataclass(slots=True)
class AlbumCompletenessIssue:
    id: str
    relative_folder: str
    album: str
    disc: int
    present_numbers: tuple[int, ...]
    missing_numbers: tuple[int, ...]
    expected_total: int
    total_from_tags: bool
    unnumbered_files: tuple[str, ...] = ()
    inconsistent_totals: tuple[int, ...] = ()
    # (total, file count) pairs: which totals the files actually declare.
    total_counts: tuple[tuple[int, int], ...] = ()

    @property
    def context(self) -> str:
        parts = [self.relative_folder]
        if self.album:
            parts.append(self.album)
        if self.disc > 1:
            parts.append(f"диск {self.disc}")
        return " · ".join(parts)

    @property
    def totals_summary(self) -> str:
        """«6, 7» — the conflicting totals, compact enough for a table cell."""
        return ", ".join(str(total) for total in self.inconsistent_totals)

    @property
    def total_breakdown_text(self) -> str:
        """«6 (6 файлов), 7 (1 файл)» — totals with the number of files each."""
        if not self.total_counts:
            return self.totals_summary
        return ", ".join(
            f"{total} ({count} {files_word(count)})"
            for total, count in self.total_counts
        )

    @property
    def short_text(self) -> str:
        details: list[str] = []
        if self.missing_numbers:
            numbers = ", ".join(str(number) for number in self.missing_numbers)
            details.append(f"пропущены № {numbers}")
        if self.unnumbered_files:
            details.append(f"без Track #: {len(self.unnumbered_files)}")
        if self.inconsistent_totals:
            if len(self.inconsistent_totals) > 1:
                # The table/export cell keeps only the totals; the card and the
                # audit tab carry the per-file detail.
                details.append(f"итоги в тегах: {self.totals_summary}")
            else:
                # A single total that contradicts the numbers found.
                details.append(
                    "итог в теге меньше номера: "
                    f"{self.inconsistent_totals[0]} < {max(self.present_numbers)}"
                )
        elif self.total_from_tags and (self.missing_numbers or self.unnumbered_files):
            # Without missing or unnumbered files there is nothing to expect.
            details.append(f"ожидается {self.expected_total}")
        prefix = ""
        if self.inconsistent_totals and not (
            self.missing_numbers or self.unnumbered_files
        ):
            # Nothing is missing: the album is complete and only its declared
            # totals contradict each other. Saying «ожидается N» here read as a
            # missing track and sent users to the wrong place.
            prefix = "комплект полный; "
        return "⚠ " + prefix + "; ".join(details)


def album_completeness_text(issue: AlbumCompletenessIssue) -> str:
    """Text of the completeness card shown in the info panel."""
    numbers = ", ".join(str(number) for number in issue.present_numbers) or "—"
    lines = [
        "ПРОВЕРКА КОМПЛЕКТА АЛЬБОМА",
        f"Папка: {issue.relative_folder}",
        f"Album: {issue.album or '—'}",
        f"Диск: {issue.disc}",
        f"Найдены номера: {numbers}",
    ]
    if issue.missing_numbers or issue.unnumbered_files:
        source = (
            "теги Track # и найденная последовательность"
            if issue.total_from_tags
            else "последний найденный номер"
        )
        lines.extend(
            [
                f"Ожидаемое количество: {issue.expected_total}",
                f"Источник ожидаемого количества: {source}",
            ]
        )
    if issue.inconsistent_totals:
        lines.append(f"Итог в тегах: {issue.total_breakdown_text}")
    lines.append(f"Результат: {issue.short_text}")
    if issue.unnumbered_files:
        lines.extend(
            [
                "",
                "Файлы без номера Track #:",
                *[f"• {filename}" for filename in issue.unnumbered_files],
            ]
        )
    return "\n".join(lines)


LOSSLESS_FORMATS = ("FLAC", "APE")


def _format_summary(tracks: list[Track]) -> str:
    """«FLAC — 5 (44.1 kHz/16 bit) · MP3 — 2 (320 kbps)»: sources at a glance."""
    by_format: dict[str, list[Track]] = defaultdict(list)
    for track in tracks:
        by_format[track.format].append(track)
    parts: list[str] = []
    for name, group in sorted(
        by_format.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        if name in LOSSLESS_FORMATS:
            qualities = sorted(
                {
                    (track.sample_rate, track.bit_depth)
                    for track in group
                    if track.sample_rate and track.bit_depth
                }
            )
            detail = "; ".join(
                f"{rate / 1000:g} kHz/{depth} bit" for rate, depth in qualities
            )
        else:
            # A range, so a VBR album is one entry and not one per bitrate.
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
        parts.append(f"{name} — {len(group)}" + (f" ({detail})" if detail else ""))
    return " · ".join(parts) or "—"


def _first_values(values: list[str], limit: int) -> str:
    if not values:
        return "—"
    text = ", ".join(values[:limit])
    if len(values) > limit:
        text += f" и ещё {len(values) - limit}"
    return text


def folder_summary_text(
    name: str,
    relative_folder: str,
    tracks: list[Track],
    completeness_issues: list[AlbumCompletenessIssue],
    audit_issues: list[MetadataAuditIssue],
    cover_file: str = "",
) -> str:
    """Info panel text for a folder row: the album, or everything below it."""
    subfolders = len({track.relative_folder for track in tracks} - {relative_folder})
    files_line = f"Файлов: {len(tracks)}"
    if subfolders:
        files_line += f" · подпапок с файлами: {subfolders}"
    durations = [
        track.comparison_duration
        for track in tracks
        if track.comparison_duration is not None
    ]
    duration_line = f"Длительность: {_clock(round(sum(durations)))}"
    if len(durations) < len(tracks):
        duration_line += f" · без длительности: {len(tracks) - len(durations)}"

    album_order: dict[str, tuple[int, str]] = {}
    for track in tracks:
        album = track.album.strip()
        if not album:
            continue
        year = track.year[:4] if track.year[:4].isdigit() else ""
        label = f"{album} ({year})" if year else album
        album_order.setdefault(label, (int(year or 9999), album.casefold()))
    albums = sorted(album_order, key=album_order.__getitem__)
    artists = sorted(
        {(track.album_artist or track.artist).strip() for track in tracks} - {""},
        key=str.casefold,
    )

    statuses = Counter(track.status for track in tracks)
    readable_covers = sum(
        bool(track.cover_hash and not track.cover_error) for track in tracks
    )
    broken_covers = sum(bool(track.cover_error) for track in tracks)
    cover_line = f"Встроенная обложка: {readable_covers} из {len(tracks)}"
    if broken_covers:
        cover_line += f" · повреждена: {broken_covers}"

    lines = [
        "ПАПКА",
        name,
        f"Путь: {relative_folder}",
        files_line,
        duration_line,
        f"Размер: {sum(track.size_mb for track in tracks):.2f} MB",
        f"Форматы: {_format_summary(tracks)}",
        f"Альбомы: {_first_values(albums, 5)}",
        f"Исполнители: {_first_values(artists, 3)}",
        "Статусы: "
        f"уникальных {statuses[TrackStatus.UNIQUE]} · "
        f"дубликатов {statuses[TrackStatus.DUPLICATE]} · "
        f"вариаций {statuses[TrackStatus.VARIATION]} · "
        f"конфликтов {statuses[TrackStatus.CONFLICT]}",
        cover_line,
    ]
    if cover_file:
        lines.append(f"Файл обложки в папке: {cover_file}")

    lines.extend(["", "ПРОВЕРКА КОМПЛЕКТА"])
    lines.extend(
        f"• {issue.context}: {issue.short_text}" for issue in completeness_issues[:8]
    )
    if len(completeness_issues) > 8:
        lines.append(f"… и ещё {len(completeness_issues) - 8}")
    if not completeness_issues:
        lines.append("Пропуски по тегам Track # не обнаружены")

    severities = Counter(issue.severity for issue in audit_issues)
    lines.extend(
        [
            "",
            "АУДИТ МЕТАДАННЫХ",
            (
                f"Ошибок {severities[AuditSeverity.ERROR]} · "
                f"предупреждений {severities[AuditSeverity.WARNING]} · "
                f"рекомендаций {severities[AuditSeverity.INFO]}"
            )
            if audit_issues
            else "Замечаний не обнаружено",
        ]
    )
    return "\n".join(lines)


@dataclass(slots=True)
class AnalysisResult:
    tracks: list[Track]
    folders_scanned: int
    root: Path
    completeness_issues: list[AlbumCompletenessIssue] = field(default_factory=list)
    audit_issues: list[MetadataAuditIssue] = field(default_factory=list)

    def count(self, status: TrackStatus) -> int:
        return sum(track.status == status for track in self.tracks)

    @property
    def total_size_mb(self) -> float:
        return sum(track.size_bytes for track in self.tracks) / 1024 / 1024

    @property
    def missing_track_count(self) -> int:
        return sum(len(issue.missing_numbers) for issue in self.completeness_issues)

    def audit_count(self, severity: AuditSeverity) -> int:
        return sum(issue.severity == severity for issue in self.audit_issues)
