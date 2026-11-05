from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from .models import AlbumCompletenessIssue, Track
from .parsing import disc_number_of_folder

TRACK_POSITION_RE = re.compile(
    r"^\s*(?P<number>\d+)(?:\s*(?:/|of|из)\s*(?P<total>\d+))?",
    re.IGNORECASE,
)

# How a release with several discs numbers its tracks.
# «По дискам»: every disc starts at 1, Track # totals belong to the disc.
PER_DISC = "per_disc"
# Qobuz and other stores: every disc starts at 1, but TRACKTOTAL counts the
# whole release (12 + 12 + 9 tracks, TRACKTOTAL 33 in every file).
RELEASE_TOTAL = "release_total"
# One sequence over all discs: disc 2 continues where disc 1 ended.
CONTINUOUS = "continuous"


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


def release_folder(track: Track) -> str:
    """The folder of the whole release: «Album/CD2» belongs to «Album».

    The files of the collection folder itself carry its full path, and a disc
    folder right inside the collection belongs to the collection folder.
    """
    folder = track.relative_folder
    if folder == str(track.root):
        return folder
    path = Path(folder)
    if disc_number_of_folder(path.name) is None:
        return folder
    parent = str(path.parent)
    return str(track.root) if parent in ("", ".") else parent


def release_key(track: Track) -> tuple[str, str]:
    """Release folder + album: the discs of one release share it."""
    return (release_folder(track), " ".join(track.album.split()).casefold())


def track_disc(track: Track) -> int:
    """Disc # from the tags, else from a «CD2» folder, else disc 1."""
    disc, _disc_total = parse_position(track.disc_number)
    if disc is not None:
        return disc
    if track.relative_folder != str(track.root):
        folder_disc = disc_number_of_folder(Path(track.relative_folder).name)
        if folder_disc:
            return folder_disc
    return 1


def numbering_mode(discs: dict[int, tuple[set[int], set[int]]]) -> str:
    """Which numbering a release uses; ``discs``: disc → (numbers, totals).

    A total equal on every disc and larger than any number can only count the
    whole release; numbers that carry on from the previous disc form one
    sequence. Anything else — one disc, per-disc totals, contradictions — is
    checked disc by disc, exactly as before.
    """
    numbered = [
        (numbers, totals) for _disc, (numbers, totals) in sorted(discs.items()) if numbers
    ]
    if len(numbered) < 2:
        return PER_DISC
    declared = set().union(*(totals for _numbers, totals in numbered))
    if len(declared) > 1:
        return PER_DISC
    total = next(iter(declared), None)
    highest = max(max(numbers) for numbers, _totals in numbered)
    follows = all(
        min(later) > max(earlier)
        for (earlier, _), (later, _) in pairwise(numbered)
    )
    if follows:
        return CONTINUOUS if total is None or total >= highest else PER_DISC
    if (
        total is not None
        and total > highest
        and total >= sum(max(numbers) for numbers, _totals in numbered)
    ):
        return RELEASE_TOTAL
    return PER_DISC


@dataclass(frozen=True, slots=True)
class ReleaseNumbering:
    """What the Track #/Disc # tags of one release say about its completeness."""

    mode: str
    discs: tuple[int, ...]
    disc_total: int  # declared number of discs, 0 when no file declares it
    absent_discs: tuple[int, ...]
    expected: int  # expected number of tracks, 0 when nothing is numbered
    numbered: int  # distinct numbered positions found
    # Known gaps: (disc, numbers). Disc 0 holds release-wide numbers of a
    # continuous sequence.
    missing: tuple[tuple[int, tuple[int, ...]], ...]
    # Tracks missing by the release total whose disc and number cannot be
    # told: every disc starts at 1, so the short disc is unknown.
    unplaced: int
    unnumbered: int
    conflicting_totals: tuple[int, ...]
    verified: bool  # the expected count comes from declared totals

    @property
    def missing_count(self) -> int:
        return sum(len(numbers) for _disc, numbers in self.missing) + self.unplaced


def release_numbering(tracks: Iterable[Track]) -> ReleaseNumbering:
    """Completeness of one release across all its discs."""
    tracks = list(tracks)
    discs: dict[int, tuple[set[int], set[int]]] = {}
    disc_totals: set[int] = set()
    unnumbered = 0
    for track in tracks:
        numbers, totals = discs.setdefault(track_disc(track), (set(), set()))
        _disc, disc_total = parse_position(track.disc_number)
        if disc_total:
            disc_totals.add(disc_total)
        number, total = parse_position(track.track_number)
        if number is None:
            unnumbered += 1
            continue
        numbers.add(number)
        if total:
            totals.add(total)

    mode = numbering_mode(discs)
    disc_total = max(disc_totals, default=0)
    absent = tuple(disc for disc in range(1, disc_total + 1) if disc not in discs)
    numbered = [
        (disc, numbers, totals)
        for disc, (numbers, totals) in sorted(discs.items())
        if numbers
    ]
    present = sum(len(numbers) for _disc, numbers, _totals in numbered)
    missing: list[tuple[int, tuple[int, ...]]] = []
    unplaced = 0
    conflicts: set[int] = set()
    expected = 0
    verified = bool(numbered) and all(totals for _disc, _numbers, totals in numbered)
    if mode == CONTINUOUS:
        sequence = set().union(*(numbers for _disc, numbers, _totals in numbered))
        declared = set().union(*(totals for _disc, _numbers, totals in numbered))
        expected = max(max(sequence), max(declared, default=0))
        gaps = tuple(sorted(set(range(1, expected + 1)) - sequence))
        if gaps:
            missing.append((0, gaps))
        verified = bool(declared)
    elif mode == RELEASE_TOTAL:
        # One value by definition, though not every disc has to declare it.
        expected = max(set().union(*(totals for _disc, _numbers, totals in numbered)))
        verified = True
        for disc, numbers, _totals in numbered:
            gaps = tuple(sorted(set(range(1, max(numbers) + 1)) - numbers))
            if gaps:
                missing.append((disc, gaps))
        known = sum(len(gaps) for _disc, gaps in missing)
        unplaced = max(0, expected - present - known)
    else:
        for disc, numbers, totals in numbered:
            disc_expected = max(max(numbers), max(totals, default=0))
            expected += disc_expected
            gaps = tuple(sorted(set(range(1, disc_expected + 1)) - numbers))
            if gaps:
                missing.append((disc, gaps))
            if len(totals) > 1 or any(total < max(numbers) for total in totals):
                conflicts.update(totals)
    return ReleaseNumbering(
        mode=mode,
        discs=tuple(sorted(discs)),
        disc_total=disc_total,
        absent_discs=absent,
        expected=expected,
        numbered=present,
        missing=tuple(missing),
        unplaced=unplaced,
        unnumbered=unnumbered,
        conflicting_totals=tuple(sorted(conflicts)),
        verified=verified,
    )


def _release_modes(tracks: list[Track]) -> dict[tuple[str, str], tuple[str, int]]:
    """Numbering mode of every release and its first numbered disc."""
    releases: dict[tuple[str, str], dict[int, tuple[set[int], set[int]]]] = (
        defaultdict(dict)
    )
    for track in tracks:
        number, total = parse_position(track.track_number)
        numbers, totals = releases[release_key(track)].setdefault(
            track_disc(track), (set(), set())
        )
        if number is not None:
            numbers.add(number)
            if total:
                totals.add(total)
    modes: dict[tuple[str, str], tuple[str, int]] = {}
    for key, discs in releases.items():
        numbered = [disc for disc, (numbers, _totals) in discs.items() if numbers]
        modes[key] = (numbering_mode(discs), min(numbered, default=1))
    return modes


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
    modes = _release_modes(tracks)

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
        mode, first_disc = modes.get(release_key(group[0]), (PER_DISC, 1))
        start = 1
        if mode == PER_DISC:
            expected_total = max(max(present), max(totals) if totals else 0)
            inconsistent_totals = (
                tuple(sorted(totals))
                if len(totals) > 1 or any(total < max(present) for total in totals)
                else ()
            )
        else:
            # The total counts the whole release, so a disc is checked only up
            # to its own last number; what is missing beyond it belongs to the
            # release and is shown on the «Релизы» tab.
            expected_total = max(present)
            inconsistent_totals = ()
            if mode == CONTINUOUS and track_disc(group[0]) != first_disc:
                start = min(present)
        missing = tuple(sorted(set(range(start, expected_total + 1)) - present))

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
            total_from_tags=bool(totals) and mode == PER_DISC,
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
