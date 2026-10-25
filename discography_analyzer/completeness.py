from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict

from .models import AlbumCompletenessIssue, Track

TRACK_POSITION_RE = re.compile(
    r"^\s*(?P<number>\d+)(?:\s*(?:/|of|из)\s*(?P<total>\d+))?",
    re.IGNORECASE,
)


def parse_position(value: str) -> tuple[int | None, int | None]:
    """Parse common Track#/Disc# values such as 4, 4/10 or 4 of 10."""
    if not value:
        return None, None
    match = TRACK_POSITION_RE.match(value)
    if not match:
        return None, None
    number = int(match.group("number"))
    total = int(match.group("total")) if match.group("total") else None
    if number < 1:
        return None, total
    return number, total


def album_group_key(track: Track) -> tuple[str, str, int]:
    """Folder + album + disc: the unit used by the completeness check."""
    disc, _disc_total = parse_position(track.disc_number)
    return (track.relative_folder, track.album.strip().casefold(), disc or 1)


def analyze_track_completeness(
    tracks: list[Track],
) -> list[AlbumCompletenessIssue]:
    """Find missing album track numbers without guessing beyond available tags."""
    for track in tracks:
        track.collection_warning = ""
        track.collection_issue_id = ""

    groups: dict[tuple[str, str, int], list[Track]] = defaultdict(list)
    for track in tracks:
        groups[album_group_key(track)].append(track)

    issues: list[AlbumCompletenessIssue] = []
    for (_folder, _album_key, disc), group in groups.items():
        numbered: dict[int, list[Track]] = defaultdict(list)
        totals: set[int] = set()
        # One total per file: «6» six times and «7» once, not just {6, 7}.
        total_files: Counter[int] = Counter()
        unnumbered: list[Track] = []
        for track in group:
            number, total = parse_position(track.track_number)
            if number is None:
                unnumbered.append(track)
                continue
            numbered[number].append(track)
            if total is not None and total > 0:
                totals.add(total)
                total_files[total] += 1

        if not numbered:
            continue
        present = set(numbered)
        expected_total = max(max(present), max(totals) if totals else 0)
        missing = tuple(sorted(set(range(1, expected_total + 1)) - present))
        inconsistent_totals = (
            tuple(sorted(totals))
            if len(totals) > 1 or any(total < max(present) for total in totals)
            else ()
        )

        # Missing numbers are actionable. Incomplete numbering or contradictory
        # totals are also shown because they make the completeness check uncertain.
        if not missing and not unnumbered and not inconsistent_totals:
            continue

        first = group[0]
        issue = AlbumCompletenessIssue(
            id=uuid.uuid4().hex,
            relative_folder=first.relative_folder,
            album=first.album,
            disc=disc,
            present_numbers=tuple(sorted(present)),
            missing_numbers=missing,
            expected_total=expected_total,
            total_from_tags=bool(totals),
            unnumbered_files=tuple(track.filename for track in unnumbered),
            inconsistent_totals=inconsistent_totals,
            total_counts=tuple(sorted(total_files.items())),
        )
        issues.append(issue)
        for track in group:
            track.collection_warning = issue.short_text
            track.collection_issue_id = issue.id

    return sorted(
        issues,
        key=lambda issue: (
            issue.relative_folder.casefold(),
            issue.album.casefold(),
            issue.disc,
        ),
    )
