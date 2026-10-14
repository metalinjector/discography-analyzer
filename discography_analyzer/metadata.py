from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .models import Track

try:
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.id3 import APIC, ID3
    from mutagen.mp4 import MP4, MP4Cover
except ImportError:  # The GUI provides a friendly dependency message.
    mutagen = None
    FLAC = ID3 = MP4 = APIC = MP4Cover = None


class MetadataDependencyError(RuntimeError):
    pass


EASY_FIELDS = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "albumartist": "album_artist",
    "tracknumber": "track_number",
    "discnumber": "disc_number",
    "date": "year",
    "year": "year",
    "genre": "genre",
    "comment": "comment",
    "description": "comment",
}


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bytes):
        return [f"<двоичные данные: {len(value)} байт>"]
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        result: list[str] = []
        for item in value:
            result.extend(_as_text_list(item))
        return result
    if hasattr(value, "data") and isinstance(value.data, bytes):
        mime = getattr(value, "mime", "изображение")
        return [f"<встроенная обложка: {mime}, {len(value.data)} байт>"]
    text = str(value)
    if len(text) > 4000:
        return [f"<данные типа {type(value).__name__}, {len(text)} символов>"]
    return [text]


def _first(tags: Any, key: str) -> str:
    # Compare with ``None`` rather than testing truthiness: ``bool(EasyID3)``
    # enumerates every registered easy key through ``keys()`` and was the
    # single most expensive operation of the whole analysis.
    if tags is None:
        return ""
    value = tags.get(key)
    values = _as_text_list(value)
    return "; ".join(v for v in values if v).strip()


def _values(tags: Any, key: str) -> list[str]:
    if tags is None:
        return []
    return [value for value in _as_text_list(tags.get(key)) if value.strip()]


def _first_any(tags: Any, keys: Iterable[str]) -> str:
    for key in keys:
        value = _first(tags, key)
        if value:
            return value
    return ""


def _values_any(tags: Any, keys: Iterable[str]) -> list[str]:
    for key in keys:
        values = _values(tags, key)
        if values:
            return values
    return []


def _merge_position(number: str, total: str) -> str:
    if not number or not total or "/" in number:
        return number
    total_digits = "".join(character for character in total if character.isdigit())
    return f"{number}/{total_digits}" if total_digits else number


def _cover_details(data: bytes, mime: str) -> tuple[str, int, str, int, int, str]:
    digest = hashlib.sha256(data).hexdigest()
    width = 0
    height = 0
    error = ""
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        error = str(exc)
    return mime or "image/unknown", len(data), digest, width, height, error


def _extract_cover_details(
    audio: Any,
    path: Path,
) -> tuple[str, int, str, int, int, str]:
    if FLAC is not None and isinstance(audio, FLAC) and audio.pictures:
        picture = next(
            (item for item in audio.pictures if getattr(item, "type", 0) == 3),
            audio.pictures[0],
        )
        return _cover_details(picture.data, picture.mime or "image/unknown")
    if MP4 is not None and isinstance(audio, MP4) and audio.tags:
        covers = audio.tags.get("covr", [])
        if covers:
            cover = covers[0]
            image_format = getattr(cover, "imageformat", None)
            mime = "image/png" if image_format == MP4Cover.FORMAT_PNG else "image/jpeg"
            return _cover_details(bytes(cover), mime)
    tags = getattr(audio, "tags", None)
    if tags and hasattr(tags, "values"):
        pictures = [
            frame
            for frame in tags.values()
            if APIC is not None and isinstance(frame, APIC)
        ]
        if pictures:
            picture = next(
                (item for item in pictures if getattr(item, "type", 0) == 3),
                pictures[0],
            )
            return _cover_details(
                picture.data,
                picture.mime or "image/unknown",
            )
    if path.suffix.casefold() == ".ape" and tags:
        for key in ("Cover Art (Front)", "Cover Art (Back)"):
            value = tags.get(key)
            raw = getattr(value, "value", value)
            if isinstance(raw, bytes):
                _, _, data = raw.partition(b"\x00")
                if data:
                    return _cover_details(data, "image/unknown")
    return "", 0, "", 0, 0, ""


def read_metadata(track: Track) -> None:
    if mutagen is None:
        raise MetadataDependencyError(
            "Не установлена библиотека Mutagen. Выполните: pip install -r requirements.txt"
        )
    try:
        easy = mutagen.File(track.path, easy=True)
        raw = mutagen.File(track.path, easy=False)
        if raw is None:
            raise ValueError("формат файла не распознан")

        easy_tags = getattr(easy, "tags", None)
        for key, attr in EASY_FIELDS.items():
            values = _values(easy_tags, key)
            if values and attr not in track.canonical_tags:
                track.canonical_tags[attr] = values
            value = "; ".join(values).strip()
            if value and not getattr(track, attr):
                setattr(track, attr, value)

        raw_tags = getattr(raw, "tags", None)
        raw_fallbacks = {
            "title": ("Title", "TITLE"),
            "artist": ("Artist", "ARTIST"),
            "album": ("Album", "ALBUM"),
            "album_artist": ("Album Artist", "ALBUMARTIST", "ALBUM ARTIST"),
            "track_number": ("Track", "TRACK", "TRACKNUMBER"),
            "disc_number": ("Disc", "DISC", "DISCNUMBER"),
            "year": ("Year", "YEAR", "DATE"),
            "genre": ("Genre", "GENRE"),
            "comment": ("Comment", "COMMENT", "DESCRIPTION"),
        }
        for attr, keys in raw_fallbacks.items():
            if not getattr(track, attr):
                values = _values_any(raw_tags, keys)
                if values and attr not in track.canonical_tags:
                    track.canonical_tags[attr] = values
                value = "; ".join(values).strip()
                if value:
                    setattr(track, attr, value)

        track_total = _first_any(
            easy_tags, ("tracktotal", "totaltracks", "totaltrack")
        ) or _first_any(raw_tags, ("TrackTotal", "TRACKTOTAL", "TOTALTRACKS"))
        disc_total = _first_any(
            easy_tags, ("disctotal", "totaldiscs", "totaldisc")
        ) or _first_any(raw_tags, ("DiscTotal", "DISCTOTAL", "TOTALDISCS"))

        # MP4 stores positions as numeric tuples in the raw trkn/disk atoms.
        if MP4 is not None and isinstance(raw, MP4) and raw_tags:
            for key, attr in (("trkn", "track_number"), ("disk", "disc_number")):
                values = raw_tags.get(key, [])
                if values and isinstance(values[0], tuple):
                    number = values[0][0] if values[0] else 0
                    total = values[0][1] if len(values[0]) > 1 else 0
                    if number:
                        setattr(
                            track,
                            attr,
                            f"{number}/{total}" if total else str(number),
                        )
        track.track_number = _merge_position(track.track_number, track_total)
        track.disc_number = _merge_position(track.disc_number, disc_total)

        info = getattr(raw, "info", None)
        if info is not None:
            exact = getattr(info, "length", None)
            if exact is not None:
                track.duration_exact = float(exact)
                # Rounded seconds are only for user-friendly display. The
                # classifier uses the exact value above with no tolerance.
                track.duration_seconds = int(round(float(exact)))
            for source, target in (
                ("bitrate", "bitrate"),
                ("sample_rate", "sample_rate"),
                ("bits_per_sample", "bit_depth"),
                ("channels", "channels"),
                ("channel_mode", "channel_mode"),
                ("bitrate_mode", "bitrate_mode"),
                ("codec", "codec"),
                ("encoder_info", "encoder"),
                ("encoder_settings", "encoder_settings"),
                ("version", "version"),
                ("layer", "layer"),
                ("protected", "protection"),
            ):
                value = getattr(info, source, None)
                if value is not None:
                    setattr(track, target, value)

        if raw_tags:
            for key in raw_tags.keys():
                try:
                    track.all_tags[str(key)] = _as_text_list(raw_tags[key])
                except Exception as exc:  # One broken tag must not hide the rest.
                    track.all_tags[str(key)] = [f"<ошибка чтения: {exc}>"]

        for key, attr in (
            ("replaygain_track_gain", "track_gain"),
            ("replaygain_track_peak", "track_peak"),
            ("replaygain_album_gain", "album_gain"),
            ("replaygain_album_peak", "album_peak"),
        ):
            value = _first(easy_tags, key)
            if value:
                setattr(track, attr, value)

        (
            track.cover_mime,
            track.cover_size,
            track.cover_hash,
            track.cover_width,
            track.cover_height,
            track.cover_error,
        ) = _extract_cover_details(raw, track.path)
    except MetadataDependencyError:
        raise
    except Exception as exc:
        track.metadata_errors.append(str(exc))


def read_embedded_cover(path: Path) -> tuple[bytes | None, str, str]:
    """Return (data, mime, error_message)."""
    if mutagen is None:
        return None, "", "Не установлена библиотека Mutagen"
    try:
        audio = mutagen.File(path, easy=False)
        if audio is None:
            return None, "", "Формат файла не распознан"
        if FLAC is not None and isinstance(audio, FLAC) and audio.pictures:
            picture = audio.pictures[0]
            return picture.data, picture.mime or "image/unknown", ""
        if MP4 is not None and isinstance(audio, MP4) and audio.tags:
            covers = audio.tags.get("covr", [])
            if covers:
                cover = covers[0]
                image_format = getattr(cover, "imageformat", None)
                mime = "image/png" if image_format == MP4Cover.FORMAT_PNG else "image/jpeg"
                return bytes(cover), mime, ""
        tags = getattr(audio, "tags", None)
        if tags and hasattr(tags, "values"):
            for frame in tags.values():
                if APIC is not None and isinstance(frame, APIC):
                    return frame.data, frame.mime or "image/unknown", ""
        if path.suffix.casefold() == ".ape" and tags:
            for key in ("Cover Art (Front)", "Cover Art (Back)"):
                value = tags.get(key)
                raw = getattr(value, "value", value)
                if isinstance(raw, bytes):
                    _, _, data = raw.partition(b"\x00")
                    if data:
                        return data, "image/unknown", ""
        return None, "", ""
    except Exception as exc:
        return None, "", str(exc)
