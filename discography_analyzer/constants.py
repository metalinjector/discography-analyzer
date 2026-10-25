from __future__ import annotations

from collections import OrderedDict

APP_NAME = "Discography Analyzer"
SUPPORTED_FORMATS = OrderedDict(
    (
        ("MP3", ".mp3"),
        ("FLAC", ".flac"),
        ("M4A", ".m4a"),
        ("APE", ".ape"),
    )
)

DEFAULT_VARIATION_MARKERS = [
    "Remix",
    "Mix",
    "Edit",
    "Live",
    "Acoustic",
    "Version",
    "Instrumental",
    "Extended",
    "Radio",
    "Club",
    "Remastered",
    "Demo",
    "Bonus",
    "Alternative",
    "Unplugged",
    "Stripped",
    "Session",
    "Reprise",
    "Interlude",
    "Intro",
    "Outro",
    "Dub",
    "VIP",
    "Bootleg",
    "Rework",
    "Reimagined",
    "Cover",
    "Karaoke",
    "Clean",
    "Explicit",
    "Deluxe",
    "Original",
    "Single",
]

DEFAULT_EXCLUDED_FOLDERS = ["__MACOSX", ".thumbnails", ".DS_Store"]

REPORT_COLOR_CHOICES = OrderedDict(
    (
        ("Тёплый оранжевый", "FCE6D3"),
        ("Светло-зелёный", "E5F3E8"),
        ("Светло-голубой", "E2EFFB"),
        ("Мягкий коралловый", "F8DFDA"),
        ("Металлический серый", "E3E5E7"),
        ("Тёплый белый", "FFFDF9"),
        ("Графитовый", "D2D5D8"),
    )
)

DEFAULT_REPORT_COLORS = {
    "Уникальный": "E5F3E8",
    "Дубликат": "FCE6D3",
    "Вариация": "E2EFFB",
    "Конфликт": "F8DFDA",
}

STATUS_ROW_COLORS_LIGHT = {
    "Уникальный": "#e5f3e8",
    "Дубликат": "#fce6d3",
    "Вариация": "#e2effb",
    "Конфликт": "#f8dfda",
}

STATUS_ROW_COLORS_DARK = {
    "Уникальный": "#254231",
    "Дубликат": "#56371f",
    "Вариация": "#263f55",
    "Конфликт": "#53312f",
}

TABLE_COLUMNS = [
    ("status", "Статус", 125),
    ("track_number", "№ трека (m/n)", 115),
    ("base_title", "Базовое имя", 220),
    ("variation", "Вариация", 130),
    ("relation", "Связь с файлами", 300),
    ("collection_warning", "Проверка комплекта", 260),
    ("relative_folder", "Папка", 180),
    ("title", "Title", 200),
    ("artist", "Artist", 180),
    ("album", "Album", 180),
    ("year", "Year", 70),
    ("genre", "Genre", 120),
    ("duration", "Duration", 90),
    ("bitrate", "Bitrate", 90),
    ("format", "Format", 75),
    ("size_mb", "Size MB", 90),
]

EXPORT_COLUMNS = OrderedDict(
    (
        ("base_title", ("Базовое имя", True)),
        ("status", ("Статус", True)),
        ("variation", ("Вариация", True)),
        ("relation", ("Связь с файлами", True)),
        ("collection_warning", ("Проверка комплекта", True)),
        ("relative_folder", ("Папка", True)),
        ("filename", ("Имя файла", True)),
        ("title", ("Title", True)),
        ("artist", ("Artist", True)),
        ("album", ("Album", True)),
        ("year", ("Year", True)),
        ("genre", ("Genre", True)),
        ("duration", ("Duration", True)),
        ("bitrate", ("Bitrate", True)),
        ("sample_rate", ("Sample Rate", False)),
        ("bit_depth", ("Bit Depth", False)),
        ("format", ("Format", True)),
        ("size_mb", ("File Size (MB)", True)),
        ("track_number", ("Track #", False)),
        ("disc_number", ("Disc #", False)),
        ("album_artist", ("Album Artist", False)),
        ("comment", ("Comment", False)),
        ("path", ("Полный путь", False)),
    )
)
