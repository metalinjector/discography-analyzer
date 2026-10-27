from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

AUDIT_FIELD_LABELS = {
    "metadata": "Метаданные",
    "duration": "Длительность",
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album Artist",
    "track_number": "Track #",
    "disc_number": "Disc #",
    "year": "Year/Date",
    "genre": "Genre",
    "cover": "Встроенная обложка",
    "format": "Формат",
    "bitrate": "Битрейт",
    "quality": "Частота и разрядность",
}


class AuditSeverity(str, Enum):
    ERROR = "Ошибка"
    WARNING = "Предупреждение"
    INFO = "Рекомендация"

    @property
    def order(self) -> int:
        return {
            AuditSeverity.ERROR: 0,
            AuditSeverity.WARNING: 1,
            AuditSeverity.INFO: 2,
        }[self]

    @property
    def decorated(self) -> str:
        return {
            AuditSeverity.ERROR: "● Ошибка",
            AuditSeverity.WARNING: "● Предупреждение",
            AuditSeverity.INFO: "● Рекомендация",
        }[self]


class AuditCategory(str, Enum):
    REQUIRED = "Обязательные теги"
    ARTISTS = "Исполнители"
    ALBUM = "Согласованность альбома"
    NUMBERING = "Нумерация"
    COVER = "Обложка"
    READABILITY = "Чтение файла"
    FORMATTING = "Форматирование"
    QUALITY = "Качество звука"


class AuditConfidence(str, Enum):
    HIGH = "Высокая"
    MEDIUM = "Средняя"
    LOW = "Низкая"
    NONE = "Без предложения"


class AuditFixKind(str, Enum):
    NORMALIZE_ARTISTS = "normalize_artists"
    NORMALIZE_WHITESPACE = "normalize_whitespace"


@dataclass(frozen=True, slots=True)
class MetadataAuditIssue:
    id: str
    track_id: str
    severity: AuditSeverity
    category: AuditCategory
    field: str
    message: str
    current_value: str = ""
    suggested_value: str = ""
    fix_kind: AuditFixKind | None = None
    confidence: AuditConfidence = AuditConfidence.NONE

    @property
    def fixable(self) -> bool:
        return self.fix_kind is not None and bool(self.suggested_value)

    @property
    def safe_fix(self) -> bool:
        return self.fixable and self.confidence == AuditConfidence.HIGH

    @property
    def field_label(self) -> str:
        return AUDIT_FIELD_LABELS.get(self.field, self.field)

    def search_text(self) -> str:
        return "\n".join(
            (
                self.severity.value,
                self.category.value,
                self.field,
                self.message,
                self.current_value,
                self.suggested_value,
            )
        ).casefold()
