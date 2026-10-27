from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .audit_models import (
    AUDIT_FIELD_LABELS,
    AuditCategory,
    AuditConfidence,
    AuditFixKind,
    AuditSeverity,
    MetadataAuditIssue,
)
from .completeness import parse_position
from .models import Track
from .parsing import artist_set

ARTIST_DELIMITER_RE = re.compile(r"[;,]")
REPEATED_DELIMITER_RE = re.compile(r"[;,]\s*[;,]")
CONTROL_OR_WHITESPACE_RE = re.compile(r"\s+")
POSITION_RE = re.compile(
    r"^\s*\d+\s*(?:(?:/|of|из)\s*\d+\s*)?$",
    re.IGNORECASE,
)
COMPILATION_ARTISTS = {
    "various artists",
    "various",
    "разные исполнители",
    "сборник",
}
EXTERNAL_COVER_STEMS = {
    "cover",
    "folder",
    "front",
    "albumart",
    "album art",
}
EXTERNAL_COVER_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
# A folder may contain several art files; "cover.*" wins over "folder.*".
COVER_STEM_ORDER = ("cover", "folder", "front", "albumart", "album art")
SUFFIX_ORDER = (".jpg", ".jpeg", ".png", ".webp")
TEXT_FIELDS = (
    "title",
    "artist",
    "album",
    "album_artist",
    "year",
    "genre",
)


def normalize_whitespace(value: str) -> str:
    return CONTROL_OR_WHITESPACE_RE.sub(" ", value).strip()


def normalize_artist_value(value: str) -> tuple[str, bool]:
    """Return a comma-separated suggestion and whether it changes the value."""
    collapsed = normalize_whitespace(value)
    if not ARTIST_DELIMITER_RE.search(collapsed):
        return collapsed, collapsed != value
    raw_parts = ARTIST_DELIMITER_RE.split(collapsed)
    parts = [normalize_whitespace(part) for part in raw_parts if part.strip()]
    suggestion = ", ".join(parts)
    return suggestion, suggestion != value


def _canonical_values(track: Track, field: str) -> list[str]:
    canonical = getattr(track, "canonical_tags", {})
    values = canonical.get(field, [])
    if values:
        return [str(value) for value in values if str(value).strip()]
    value = str(getattr(track, field, "") or "")
    return [value] if value.strip() else []


def _artist_tokens(track: Track, field: str) -> set[str]:
    tokens: set[str] = set()
    for value in _canonical_values(track, field):
        tokens.update(artist_set(value))
    return tokens


def _dominant_value(values: list[str]) -> str | None:
    normalized = [normalize_whitespace(value) for value in values if value.strip()]
    if len(normalized) < 2:
        return None
    counts = Counter(value.casefold() for value in normalized)
    key, count = counts.most_common(1)[0]
    second = counts.most_common(2)[1][1] if len(counts) > 1 else 0
    if count < 2 or count <= second:
        return None
    return next(value for value in normalized if value.casefold() == key)


def find_folder_cover(folder: Path) -> Path | None:
    """Return the cover image of ``folder``, preferring ``cover`` over ``folder``.

    The audit suggestion, the folder summary and the cover utility all use
    this one choice, so they always name the same picture. Matching is
    case-insensitive so ``Cover.JPG`` on a case-sensitive volume is found
    too. Stems outside the known list are ignored on purpose: a random
    ``back.jpg`` is not necessarily the album cover.
    """
    try:
        entries = [
            entry
            for entry in folder.iterdir()
            if entry.is_file() and entry.suffix.casefold() in EXTERNAL_COVER_SUFFIXES
        ]
    except OSError:
        return None
    ranked: list[tuple[int, int, str, Path]] = []
    for entry in entries:
        stem = entry.stem.casefold()
        if stem not in EXTERNAL_COVER_STEMS:
            continue
        suffix = entry.suffix.casefold()
        suffix_rank = (
            SUFFIX_ORDER.index(suffix) if suffix in SUFFIX_ORDER else len(SUFFIX_ORDER)
        )
        stem_rank = (
            COVER_STEM_ORDER.index(stem)
            if stem in COVER_STEM_ORDER
            else len(COVER_STEM_ORDER)
        )
        ranked.append((stem_rank, suffix_rank, entry.name.casefold(), entry))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][3]



# Quality thresholds: a lossy track is an outlier when its bitrate is below
# three quarters of the album median and at least 64 kbps under it. Both
# numbers are starting points and can be tuned from what E: shows.
LOSSLESS_FORMATS = {"FLAC", "APE"}
LOSSLESS_CODECS = {"alac"}
BITRATE_RATIO = 0.75
BITRATE_DELTA_KBPS = 64


def _is_lossless(track: Track) -> bool:
    fmt = track.format.strip().upper()
    if fmt in LOSSLESS_FORMATS:
        return True
    return fmt == "M4A" and (track.codec or "").strip().casefold() in LOSSLESS_CODECS


def _is_lossy(track: Track) -> bool:
    fmt = track.format.strip().upper()
    if fmt == "MP3":
        return True
    return fmt == "M4A" and not _is_lossless(track)


def _resolution_text(sample_rate: int, bit_depth: int) -> str:
    return f"{sample_rate / 1000:g} kHz/{bit_depth} bit"


def _strict_majority(counts: Counter) -> tuple[object, int, int] | None:
    """Most common value when it beats the runner-up, else ``None``."""
    if len(counts) < 2:
        return None
    ranked = counts.most_common(2)
    value, count = ranked[0]
    second = ranked[1][1]
    if count < 2 or count <= second:
        return None
    return value, count, second


def _audit_quality(add, group: list[Track]) -> None:
    """Flag albums assembled from different sources — no fixes on purpose."""
    if len(group) < 2:
        return

    formats = Counter(
        track.format.strip().upper() for track in group if track.format.strip()
    )
    if len(formats) > 1:
        majority = _strict_majority(formats)
        if majority is not None:
            dominant = str(majority[0])
            for track in group:
                if track.format.strip().upper() != dominant:
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.QUALITY,
                        "format",
                        (
                            f"Формат {track.format.strip().upper()} отличается от "
                            f"большинства треков альбома ({dominant})"
                        ),
                        current=track.format.strip().upper(),
                    )
        else:
            for track in group:
                add(
                    track,
                    AuditSeverity.INFO,
                    AuditCategory.QUALITY,
                    "format",
                    "В альбоме нет преобладающего формата: треки из разных источников",
                    current=track.format.strip().upper(),
                )

    by_format: dict[str, list[Track]] = defaultdict(list)
    for track in group:
        if _is_lossy(track) and track.bitrate and track.bitrate > 0:
            by_format[track.format.strip().upper()].append(track)
    for items in by_format.values():
        if len(items) < 2:
            continue
        median = statistics.median(track.bitrate for track in items)
        for track in items:
            if (
                track.bitrate < median * BITRATE_RATIO
                and median - track.bitrate >= BITRATE_DELTA_KBPS
            ):
                add(
                    track,
                    AuditSeverity.WARNING,
                    AuditCategory.QUALITY,
                    "bitrate",
                    (
                        f"Битрейт {track.bitrate} kbps заметно ниже остальных "
                        f"треков альбома (медиана {round(median)} kbps)"
                    ),
                    current=f"{track.bitrate} kbps",
                )

    lossless = [
        track
        for track in group
        if _is_lossless(track) and track.sample_rate and track.bit_depth
    ]
    if len(lossless) < 2:
        return
    resolutions = Counter(
        (track.sample_rate, track.bit_depth) for track in lossless
    )
    majority = _strict_majority(resolutions)
    if majority is None:
        return
    rate, depth = majority[0]
    for track in lossless:
        if (track.sample_rate, track.bit_depth) == (rate, depth):
            continue
        add(
            track,
            AuditSeverity.INFO,
            AuditCategory.QUALITY,
            "quality",
            (
                f"{_resolution_text(track.sample_rate, track.bit_depth)} при "
                f"{_resolution_text(rate, depth)} у большинства треков альбома"
            ),
            current=_resolution_text(track.sample_rate, track.bit_depth),
        )


def audit_metadata(tracks: list[Track]) -> list[MetadataAuditIssue]:
    ordered = sorted(
        tracks,
        key=lambda track: (
            track.relative_folder.casefold(),
            track.filename.casefold(),
        ),
    )
    track_sort_keys = {
        track.id: (
            track.relative_folder.casefold(),
            track.filename.casefold(),
        )
        for track in ordered
    }
    issues: list[MetadataAuditIssue] = []
    issue_number = 0

    def add(
        track: Track,
        severity: AuditSeverity,
        category: AuditCategory,
        field: str,
        message: str,
        *,
        current: str = "",
        suggested: str = "",
        fix_kind: AuditFixKind | None = None,
        confidence: AuditConfidence = AuditConfidence.NONE,
    ) -> None:
        nonlocal issue_number
        issue_number += 1
        issues.append(
            MetadataAuditIssue(
                id=f"{issue_number:06d}-{track.id}",
                track_id=track.id,
                severity=severity,
                category=category,
                field=field,
                message=message,
                current_value=current,
                suggested_value=suggested,
                fix_kind=fix_kind,
                confidence=confidence,
            )
        )

    folder_tracks: dict[str, list[Track]] = defaultdict(list)
    album_tracks: dict[tuple[str, str], list[Track]] = defaultdict(list)
    external_covers: dict[Path, Path | None] = {}
    for track in ordered:
        folder_tracks[track.relative_folder].append(track)
        album_key = normalize_whitespace(track.album).casefold()
        if album_key:
            album_tracks[(track.relative_folder, album_key)].append(track)

        if track.metadata_errors:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.READABILITY,
                "metadata",
                "Файл или его теги прочитаны с ошибками",
                current="; ".join(track.metadata_errors),
            )
        if track.duration_exact is None or track.duration_exact <= 0:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.READABILITY,
                "duration",
                "Не удалось определить корректную длительность аудио",
                current=str(track.duration_exact or ""),
            )

        for field in ("title", "artist", "album"):
            value = str(getattr(track, field, "") or "")
            if not value.strip():
                add(
                    track,
                    AuditSeverity.ERROR,
                    AuditCategory.REQUIRED,
                    field,
                    (
                        "Отсутствует обязательный тег "
                        f"{AUDIT_FIELD_LABELS.get(field, field)}"
                    ),
                )
        if not track.album_artist.strip():
            add(
                track,
                AuditSeverity.WARNING,
                AuditCategory.REQUIRED,
                "album_artist",
                "Не заполнен Album Artist",
            )
        if not track.year.strip():
            add(
                track,
                AuditSeverity.INFO,
                AuditCategory.REQUIRED,
                "year",
                "Не указан год или дата релиза",
            )

        for field in TEXT_FIELDS:
            values = _canonical_values(track, field)
            if len(values) != 1:
                continue
            value = values[0]
            if field in ("artist", "album_artist"):
                suggestion, changed = normalize_artist_value(value)
                malformed_separator = (
                    ";" in value
                    or bool(re.search(r",\S|\s+,", value))
                    or bool(REPEATED_DELIMITER_RE.search(value))
                )
                if changed and malformed_separator and suggestion:
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.ARTISTS,
                        field,
                        "Нестандартные разделители или пробелы между исполнителями",
                        current=value,
                        suggested=suggestion,
                        fix_kind=AuditFixKind.NORMALIZE_ARTISTS,
                        confidence=AuditConfidence.HIGH,
                    )
                    continue
            suggestion = normalize_whitespace(value)
            if suggestion != value:
                add(
                    track,
                    AuditSeverity.WARNING,
                    AuditCategory.FORMATTING,
                    field,
                    "Лишние пробелы или управляющие символы в значении тега",
                    current=value,
                    suggested=suggestion,
                    fix_kind=AuditFixKind.NORMALIZE_WHITESPACE,
                    confidence=AuditConfidence.HIGH,
                )

        artist_tokens = _artist_tokens(track, "artist")
        album_artist_tokens = _artist_tokens(track, "album_artist")
        if artist_tokens and album_artist_tokens:
            album_artist_text = " ".join(album_artist_tokens).casefold()
            is_compilation = any(
                marker in album_artist_text for marker in COMPILATION_ARTISTS
            )
            if not is_compilation and not (artist_tokens & album_artist_tokens):
                add(
                    track,
                    AuditSeverity.WARNING,
                    AuditCategory.ARTISTS,
                    "album_artist",
                    "Artist и Album Artist не содержат общего исполнителя",
                    current=track.album_artist,
                )
            elif (
                not is_compilation
                and album_artist_tokens < artist_tokens
                and len(artist_tokens) > 1
            ):
                add(
                    track,
                    AuditSeverity.INFO,
                    AuditCategory.ARTISTS,
                    "album_artist",
                    (
                        "В Artist есть дополнительные исполнители. Это может "
                        "быть корректным оформлением приглашённых участников"
                    ),
                    current=track.album_artist,
                    suggested=track.artist,
                    confidence=AuditConfidence.LOW,
                )

        number, total = parse_position(track.track_number)
        if track.track_number.strip() and (
            number is None or not POSITION_RE.fullmatch(track.track_number)
        ):
            add(
                track,
                AuditSeverity.WARNING,
                AuditCategory.NUMBERING,
                "track_number",
                "Некорректный номер трека",
                current=track.track_number,
            )
        elif number is not None and total is not None and total < number:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.NUMBERING,
                "track_number",
                "Номер трека больше общего количества треков",
                current=track.track_number,
            )

        disc, disc_total = parse_position(track.disc_number)
        if track.disc_number.strip() and (
            disc is None or not POSITION_RE.fullmatch(track.disc_number)
        ):
            add(
                track,
                AuditSeverity.WARNING,
                AuditCategory.NUMBERING,
                "disc_number",
                "Некорректный номер диска",
                current=track.disc_number,
            )
        elif disc is not None and disc_total is not None and disc_total < disc:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.NUMBERING,
                "disc_number",
                "Номер диска больше общего количества дисков",
                current=track.disc_number,
            )

        if track.cover_error:
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.COVER,
                "cover",
                "Встроенная обложка повреждена или не читается",
                current=track.cover_error,
            )
        elif not track.cover_hash:
            folder = track.path.parent
            if folder not in external_covers:
                external_covers[folder] = find_folder_cover(folder)
            external = external_covers[folder]
            suggestion = (
                f"Встроить файл {external.name}" if external is not None else ""
            )
            add(
                track,
                AuditSeverity.ERROR,
                AuditCategory.COVER,
                "cover",
                "Внутри аудиофайла отсутствует встроенная обложка",
                current="Отсутствует",
                suggested=suggestion,
                confidence=(
                    AuditConfidence.MEDIUM
                    if external is not None
                    else AuditConfidence.NONE
                ),
            )

    for group in folder_tracks.values():
        if len(group) > 1:
            for track in group:
                if not track.track_number.strip():
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.NUMBERING,
                        "track_number",
                        "В папке с несколькими треками отсутствует Track #",
                    )

        albums = [track.album for track in group if track.album.strip()]
        dominant_album = _dominant_value(albums)
        if dominant_album and len(group) >= 3:
            matching = sum(
                normalize_whitespace(track.album).casefold()
                == dominant_album.casefold()
                for track in group
            )
            if matching / len(group) >= 0.75:
                for track in group:
                    if (
                        track.album.strip()
                        and normalize_whitespace(track.album).casefold()
                        != dominant_album.casefold()
                    ):
                        add(
                            track,
                            AuditSeverity.WARNING,
                            AuditCategory.ALBUM,
                            "album",
                            "Название альбома отличается от большинства файлов папки",
                            current=track.album,
                            suggested=dominant_album,
                            confidence=AuditConfidence.MEDIUM,
                        )

    for (_folder, _album), group in album_tracks.items():
        if len(group) < 2:
            continue
        numbered: dict[tuple[int, int], list[Track]] = defaultdict(list)
        for track in group:
            number, _total = parse_position(track.track_number)
            disc, _disc_total = parse_position(track.disc_number)
            if number is not None:
                numbered[(disc or 1, number)].append(track)
        for (disc, number), duplicates in numbered.items():
            if len(duplicates) < 2:
                continue
            filenames = ", ".join(track.filename for track in duplicates)
            for track in duplicates:
                add(
                    track,
                    AuditSeverity.ERROR,
                    AuditCategory.NUMBERING,
                    "track_number",
                    f"Номер {number} на диске {disc} повторяется: {filenames}",
                    current=track.track_number,
                )

        # A declared total below the highest number found on the same disc is a
        # definite contradiction (the tags claim 6 tracks while track 7 exists).
        # Checked per disc: multi-disc sets legitimately declare different
        # totals. Reported per file without a mechanical fix — whether the
        # extra track belongs to the release is the user's decision.
        totals_by_disc: dict[int, list[tuple[Track, int, int]]] = defaultdict(list)
        numbers_by_disc: dict[int, list[int]] = defaultdict(list)
        for track in group:
            disc, _disc_total = parse_position(track.disc_number)
            number, total = parse_position(track.track_number)
            if number is None:
                continue
            numbers_by_disc[disc or 1].append(number)
            if total is not None:
                totals_by_disc[disc or 1].append((track, number, total))
        for key, entries in totals_by_disc.items():
            highest = max(numbers_by_disc[key])
            for track, number, total in entries:
                if total >= highest:
                    continue
                add(
                    track,
                    AuditSeverity.WARNING,
                    AuditCategory.NUMBERING,
                    "track_number",
                    (
                        "Итог Track # меньше найденного номера "
                        f"на диске ({highest})"
                    ),
                    current=f"{number}/{total}",
                    suggested=f"{number}/{highest}",
                    confidence=AuditConfidence.LOW,
                )

        album_artists = [
            track.album_artist for track in group if track.album_artist.strip()
        ]
        dominant_artist = _dominant_value(album_artists)
        if dominant_artist:
            for track in group:
                if not track.album_artist.strip():
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.ALBUM,
                        "album_artist",
                        (
                            "Album Artist отсутствует, но для остальных "
                            "треков альбома найдено согласованное значение"
                        ),
                        suggested=dominant_artist,
                        confidence=AuditConfidence.MEDIUM,
                    )
                    continue
                if (
                    track.album_artist.strip()
                    and normalize_whitespace(track.album_artist).casefold()
                    != dominant_artist.casefold()
                ):
                    add(
                        track,
                        AuditSeverity.WARNING,
                        AuditCategory.ALBUM,
                        "album_artist",
                        "Album Artist отличается от большинства треков альбома",
                        current=track.album_artist,
                        suggested=dominant_artist,
                        confidence=AuditConfidence.MEDIUM,
                    )

        years = [track.year for track in group if track.year.strip()]
        dominant_year = _dominant_value(years)
        if dominant_year:
            for track in group:
                if (
                    track.year.strip()
                    and normalize_whitespace(track.year).casefold()
                    != dominant_year.casefold()
                ):
                    add(
                        track,
                        AuditSeverity.INFO,
                        AuditCategory.ALBUM,
                        "year",
                        "Дата отличается от большинства треков альбома",
                        current=track.year,
                        suggested=dominant_year,
                        confidence=AuditConfidence.LOW,
                    )

        cover_counts = Counter(
            track.cover_hash for track in group if track.cover_hash
        )
        if cover_counts:
            ranked = cover_counts.most_common(2)
            dominant_cover, count = ranked[0]
            second = ranked[1][1] if len(ranked) > 1 else 0
            if count >= 2 and count > second:
                source = next(
                    track for track in group if track.cover_hash == dominant_cover
                )
                for track in group:
                    if track.cover_hash and track.cover_hash != dominant_cover:
                        add(
                            track,
                            AuditSeverity.WARNING,
                            AuditCategory.COVER,
                            "cover",
                            "Обложка отличается от большинства треков альбома",
                            current=f"{track.cover_width}×{track.cover_height}",
                            suggested=f"Использовать обложку из {source.filename}",
                            confidence=AuditConfidence.MEDIUM,
                        )

        _audit_quality(add, group)

    return sorted(
        issues,
        key=lambda issue: (
            issue.severity.order,
            track_sort_keys.get(issue.track_id, ("", "")),
            issue.category.value,
            issue.field,
            issue.id,
        ),
    )
