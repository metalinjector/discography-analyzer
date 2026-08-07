from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

TRACK_PREFIX_RE = re.compile(
    r"^\s*(?:(?:cd|disc)\s*\d+\s*[-_. ]+)?(?:\d{1,3}\s*[-_.]\s*|\d{1,3}\s+)",
    re.IGNORECASE,
)
ARTIST_SEPARATOR_RE = re.compile(
    r"\s*(?:,|;|&|\+|\bfeat(?:uring)?\b\.?|\bft\b\.?)\s*"
    r"|\s+(?:with|x|and)\s+",
    re.IGNORECASE,
)


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    return TRACK_PREFIX_RE.sub("", stem, count=1).strip()


def artist_set(artist: str) -> set[str]:
    if not artist or not artist.strip():
        return set()
    return {
        re.sub(r"\s+", " ", part).strip().casefold()
        for part in ARTIST_SEPARATOR_RE.split(artist)
        if part.strip()
    }


def _contains_marker(text: str, markers: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(
        re.search(rf"(?<!\w){re.escape(marker.casefold())}(?!\w)", lowered)
        for marker in markers
        if marker.strip()
    )


def detect_variation(title: str, markers: Iterable[str]) -> tuple[str, str] | None:
    """Return a possible (base, variation) without changing the displayed title."""
    title = title.strip()
    if not title:
        return None

    bracket = re.match(r"^(?P<base>.+?)\s*[\(\[]\s*(?P<var>[^\)\]]+)\s*[\)\]]\s*$", title)
    if bracket and _contains_marker(bracket.group("var"), markers):
        return bracket.group("base").strip(), bracket.group("var").strip()

    hyphen = re.match(r"^(?P<base>.+?)\s+-\s+(?P<var>.+?)\s*$", title)
    if hyphen and _contains_marker(hyphen.group("var"), markers):
        return hyphen.group("base").strip(), hyphen.group("var").strip()

    sorted_markers = sorted(
        (m.strip() for m in markers if m.strip()),
        key=lambda item: (len(item.split()), len(item)),
        reverse=True,
    )
    one_word_markers = {
        marker.casefold() for marker in sorted_markers if len(marker.split()) == 1
    }
    for marker in sorted_markers:
        match = re.match(
            rf"^(?P<base>.+?)\s+(?P<var>{re.escape(marker)})\s*$",
            title,
            re.IGNORECASE,
        )
        if not match:
            continue
        base = match.group("base").strip()
        variation = match.group("var").strip()
        # Adjacent marker words form one designation: "Radio Edit",
        # "Acoustic Version", "Extended Club Mix".
        while True:
            prefix = re.match(r"^(?P<base>.*\S)\s+(?P<word>[\w'-]+)$", base)
            if not prefix or prefix.group("word").casefold() not in one_word_markers:
                break
            variation = f"{prefix.group('word')} {variation}"
            base = prefix.group("base").strip()
        return base, variation
    return None


def validate_markers(lines: Iterable[str]) -> list[str]:
    result: list[str] = []
    for number, raw in enumerate(lines, start=1):
        marker = raw.strip()
        if not marker:
            continue
        if len(marker) > 80 or not re.fullmatch(r"[\wÀ-žА-Яа-яЁё' -]+", marker):
            raise ValueError(f"Некорректное обозначение вариации в строке {number}: {raw!r}")
        if marker.casefold() not in {item.casefold() for item in result}:
            result.append(marker)
    return result
