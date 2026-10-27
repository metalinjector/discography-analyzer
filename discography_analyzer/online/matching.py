"""Is a release the local album? Text keys, release score and track matching.

The normalisation and the release score follow global-music-scanner-2
(``lib/utils.ts`` and the Apple album choice in ``services/apple/api.ts``), so
both projects call the same pair of names «one album».
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..completeness import parse_position
from ..models import Track
from .album import AlbumGuess, LocalAlbum
from .release import Release, ReleaseTrack

# Latin letters that NFKD does not split into a base letter and a mark:
# Deezer writes «Erik Wollo», Apple and Discogs «Erik Wøllo».
LATIN_FOLD = str.maketrans(
    {
        "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
        "ß": "ss", "ẞ": "SS", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
        "ð": "d", "Ð": "D", "þ": "th", "Þ": "TH", "ħ": "h", "Ħ": "H",
        "ŧ": "t", "Ŧ": "T", "ı": "i", "ŀ": "l", "Ŀ": "L", "ŋ": "n", "Ŋ": "N",
    }
)
YEAR_REMASTER_RE = re.compile(
    r"[(\[]\s*\d{4}\s+(?:digital\s+)?remaster(?:ed)?(?:\s+version)?\s*[)\]]", re.IGNORECASE
)
RELEASE_SUFFIX_RE = re.compile(
    r"\s-\s(?:single|ep|lp|mini album|deluxe edition|special edition)$", re.IGNORECASE
)
EDITION_PARENS_RE = re.compile(r"\((?:deluxe|remastered|expanded|special|version|edition).*\)", re.IGNORECASE)
EDITION_BRACKETS_RE = re.compile(r"\[(?:deluxe|remastered|expanded|special|version|edition).*\]", re.IGNORECASE)
FEATURING_RE = re.compile(r"[(\[]\s*(?:feat\.?|ft\.?|featuring|with|w/)\s+[^)\]]*[)\]]", re.IGNORECASE)
FEATURING_TAIL_RE = re.compile(r"\s[-–—]\s*(?:feat\.?|ft\.?|featuring|with|w/)\s+.*$", re.IGNORECASE)
EDITION_FLAGS = tuple(
    (flag, re.compile(pattern, re.IGNORECASE))
    for flag, pattern in (
        ("deluxe", r"\bdeluxe\b"),
        ("expanded", r"\bexpanded\b"),
        ("anniversary", r"\banniversary\b"),
        ("remastered", r"\bremaster(?:ed)?\b"),
        ("live", r"\blive\b"),
        ("acoustic", r"\bacoustic\b"),
        ("instrumental", r"\binstrumental\b"),
        ("acapella", r"\ba[\s-]?cap+el+a\b"),
        ("karaoke", r"\bkaraoke\b"),
        ("remix", r"\bremix(?:es|ed)?\b"),
        ("bonus", r"\bbonus(?:\s+tracks?)?\b"),
        ("special", r"\bspecial\s+edition\b"),
        # «- Single» and «- EP» are release types, not editions: Apple appends
        # them to the very album the folder names without a suffix. A single
        # is rejected by its track list and coverage, not by its name.
    )
)
REMASTER_YEAR_RE = re.compile(
    r"\b((?:19|20)\d{2})\s+remaster(?:ed)?\b|\bremaster(?:ed)?(?:\s+in)?\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
# «02. Battery.flac», «1-02 Battery.flac», «CD2 - 02 - Battery.flac», «02.flac».
FILENAME_POSITION_RE = re.compile(
    r"^\s*(?:(?:cd|disc|disk)\s*(?P<disc>\d{1,2})\s*[-_. ]+)?"
    r"(?:(?P<side>\d)[-.](?=\d{2}(?:\D|$)))?"
    r"(?P<number>\d{1,3})(?=\s*[-_.)\]]|\s|$)",
    re.IGNORECASE,
)
TRACK_WORD_RE = re.compile(r"^\s*(?:track|трек|audio\s*track)\s*(?P<number>\d{1,3})\b", re.IGNORECASE)
# «Track 01», «Трек 1», «Piste 3»: a ripper's placeholder, not a title.
GENERIC_TITLE_RE = re.compile(
    r"^\s*(?:track|трек|piste|titel|audio\s*track|дорожка)\s*\d*\s*$", re.IGNORECASE
)

MATCH_THRESHOLD = 40


def fold(text: str) -> str:
    """Lower-case letters and digits; Latin diacritics dropped, other scripts kept.

    Dropping every combining mark would turn Japanese «だ» into «た» and
    Russian «й» into «и», so only the marks of Latin letters go.
    """
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(LATIN_FOLD))
    kept: list[str] = []
    latin_base = False
    for character in decomposed:
        if unicodedata.category(character).startswith("M"):
            if not latin_base:
                kept.append(character)
            continue
        latin_base = "LATIN" in unicodedata.name(character, "")
        kept.append(character)
    composed = unicodedata.normalize("NFKC", "".join(kept)).casefold()
    return "".join(character for character in composed if character.isalnum())


def normalize_name(name: str) -> str:
    return fold(name)


def normalize_title(title: str) -> str:
    """Album title key: no «- Single», «(Deluxe…)», «[2011 Remaster]» or punctuation."""
    if not title:
        return ""
    text = re.sub(r"(\S)\s+EP\s*$", r"\1", title).lower()
    text = re.sub(r"\breh\.(?=\s|$)", "rehearsal", text)
    text = re.sub(r"\s+and\s+", " & ", text)
    for pattern in (YEAR_REMASTER_RE, RELEASE_SUFFIX_RE, EDITION_PARENS_RE, EDITION_BRACKETS_RE):
        text = pattern.sub("", text)
    return fold(text)


def normalize_track_title(title: str) -> str:
    """Track title key: like the album key, and without the guests."""
    return normalize_title(FEATURING_TAIL_RE.sub("", FEATURING_RE.sub("", title or "")))


@dataclass(frozen=True, slots=True)
class Edition:
    flags: frozenset[str]
    remaster_year: int | None = None


def edition_of(title: str) -> Edition:
    """Deluxe, live, remastered 2011… — the words that make another edition.

    Explicit and clean versions are one recording, so they are not flags.
    The trailing release type («- EP», «- Single») is not an edition either:
    Apple names the same album «Christmas & Chill - EP» while the folder says
    «Christmas & Chill», and normalize_title drops the suffix for the title
    key — the flags must agree with that.
    """
    cleaned = RELEASE_SUFFIX_RE.sub("", title or "")
    flags = {flag for flag, pattern in EDITION_FLAGS if pattern.search(cleaned)}
    match = REMASTER_YEAR_RE.search(cleaned)
    year = int(match.group(1) or match.group(2)) if match else None
    return Edition(frozenset(flags), year)


def editions_compatible(left: Edition, right: Edition) -> bool:
    if left.flags != right.flags:
        return False
    return not (
        left.remaster_year and right.remaster_year and left.remaster_year != right.remaster_year
    )


def _similar(left: str, right: str) -> bool:
    """One key contains the other: «metallica» and «metallicasanfranciscosymphony»."""
    return min(len(left), len(right)) >= 4 and (left in right or right in left)


def release_fits(guess: AlbumGuess, release: Release) -> bool:
    """Nothing known about the local album contradicts the release.

    The title (with its edition) and the artist must agree when the tags or
    folders name them. The score alone is not enough: a tribute album with the
    same title and track list loses only 80 points for its artist.
    """
    expected_title = normalize_title(guess.title)
    if expected_title:
        title = normalize_title(release.title)
        if title != expected_title and not _similar(title, expected_title):
            return False
        if not editions_compatible(edition_of(guess.title), edition_of(release.title)):
            return False
    expected_artist = normalize_name(guess.artist)
    if expected_artist:
        artist = normalize_name(release.artist)
        if artist != expected_artist and not _similar(artist, expected_artist):
            return False
    return bool(expected_title or expected_artist)


def score_release(guess: AlbumGuess, release: Release) -> int:
    """How well a release fits the local album; the weights of the Apple UPC choice."""
    score = 0
    expected_title = normalize_title(guess.title)
    if expected_title:
        title = normalize_title(release.title)
        if title == expected_title:
            score += 100
        elif _similar(title, expected_title):
            score += 40
        else:
            score -= 20
        compatible = editions_compatible(edition_of(guess.title), edition_of(release.title))
        score += 35 if compatible else -100
    expected_artist = normalize_name(guess.artist)
    if expected_artist:
        artist = normalize_name(release.artist)
        if artist == expected_artist:
            score += 40
        elif _similar(artist, expected_artist):
            score += 10
        else:
            score -= 80
    if guess.disc is not None and release.detailed and release.disc_total == 1:
        # A disc folder against a one-disc release that holds every disc: the
        # release is probably a digital edition, a real multi-disc one is a
        # better answer — it carries the disc numbers the folder is named after.
        score -= 100
        count = 0
    elif guess.disc is not None and release.detailed:
        count = release.disc_size(guess.disc)
    elif guess.disc is None:
        count = len(release.tracks) or release.track_count
    else:
        count = 0  # one disc of a set: the album's total says nothing yet
    if guess.track_count and count:
        score += 50 if count == guess.track_count else -25
    if guess.year and release.year:
        difference = abs(guess.year - release.year)
        score += 20 if difference == 0 else 5 if difference == 1 else -10
    return score


def filename_position(filename: str) -> tuple[int | None, int | None]:
    """(disc, number) from the file name, or (None, None)."""
    stem = Path(filename).stem
    match = FILENAME_POSITION_RE.match(stem)
    if match:
        disc = match.group("disc") or match.group("side")
        return (int(disc) if disc else None), int(match.group("number"))
    word = TRACK_WORD_RE.match(stem)
    if word:
        return None, int(word.group("number"))
    return None, None


def local_position(track: Track, disc_hint: int | None) -> tuple[int | None, int | None]:
    number, _total = parse_position(track.track_number)
    disc, _discs = parse_position(track.disc_number)
    if number is None:
        file_disc, number = filename_position(track.filename)
        disc = disc or file_disc
    return disc or disc_hint, number


def local_title(track: Track) -> str:
    title = track.title.strip() or track.filename_title.strip()
    return "" if GENERIC_TITLE_RE.match(title) else title


def title_keys(title: str, artist_hint: str) -> list[str]:
    """Keys to compare with a release track: the title itself and, for the
    «Artist - Title» file names rippers produce, the part after the dash.

    The tail is used only when the head is the album artist, so «Love - Hate»
    by someone else is not silently read as «Hate».
    """
    keys = [normalize_track_title(title)]
    if " - " in title:
        head, tail = title.split(" - ", 1)
        head_key = normalize_name(head)
        artist_key = normalize_name(artist_hint)
        if (
            head_key
            and artist_key
            and (head_key == artist_key or _similar(head_key, artist_key))
        ):
            keys.append(normalize_track_title(tail))
    unique: list[str] = []
    for key in keys:
        if key and key not in unique:
            unique.append(key)
    return unique


def pair_score(
    track: Track,
    disc_hint: int | None,
    candidate: ReleaseTrack,
    single_disc: bool,
    artist_hint: str = "",
) -> int:
    score = 0
    disc, number = local_position(track, disc_hint)
    if number is not None and number == candidate.number:
        # A position is evidence only when the disc context is unambiguous.
        # For a «CD2» folder matched against a one-disc release holding all
        # discs' tracks, the file's number 1 would otherwise take track 1 of
        # disc 1 — the titles of the wrong disc were written in a live run.
        if disc is None:
            position_agrees = single_disc or candidate.disc == 1
        else:
            position_agrees = disc == candidate.disc
        if position_agrees:
            score += 50
    mine_keys = title_keys(local_title(track), artist_hint)
    theirs = normalize_track_title(candidate.title)
    if mine_keys and theirs:
        if theirs in mine_keys:
            score += 40
        elif any(
            min(len(mine), len(theirs)) >= 5 and (mine in theirs or theirs in mine)
            for mine in mine_keys
        ):
            score += 25
        else:
            score -= 10
    duration = track.comparison_duration
    if duration and candidate.duration:
        difference = abs(float(duration) - candidate.duration)
        if difference <= 2:
            score += 30
        elif difference <= 5:
            score += 10
        elif difference > 20:
            score -= 30
    return score


@dataclass(frozen=True, slots=True)
class TrackMatch:
    track: Track
    source: ReleaseTrack | None
    score: int = 0


def match_tracks(album: LocalAlbum, release: Release) -> tuple[TrackMatch, ...]:
    """Pair local files with release tracks, best pairs first, one to one.

    A pair needs 40 points: the same position (50), the same title (40), or a
    similar title (25) with a duration within 2 s (30). A position whose
    title and duration both disagree (50 − 10 − 30) is another edition.
    """
    single_disc = release.disc_total <= 1
    pairs = sorted(
        (
            (
                pair_score(
                    track, album.guess.disc, candidate, single_disc, album.guess.artist
                ),
                mine,
                theirs,
            )
            for mine, track in enumerate(album.tracks)
            for theirs, candidate in enumerate(release.tracks)
        ),
        key=lambda pair: (-pair[0], pair[1], pair[2]),
    )
    chosen: dict[int, tuple[int, int]] = {}
    taken: set[int] = set()
    for score, mine, theirs in pairs:
        if score < MATCH_THRESHOLD:
            break
        if mine in chosen or theirs in taken:
            continue
        chosen[mine] = (theirs, score)
        taken.add(theirs)
    return tuple(
        TrackMatch(track, release.tracks[chosen[index][0]], chosen[index][1])
        if index in chosen
        else TrackMatch(track, None)
        for index, track in enumerate(album.tracks)
    )
