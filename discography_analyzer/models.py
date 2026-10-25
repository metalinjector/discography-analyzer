from __future__ import annotations

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
        minutes, seconds = divmod(self.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

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
