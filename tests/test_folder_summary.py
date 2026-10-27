import unittest
from pathlib import Path

from discography_analyzer.audit_models import (
    AuditCategory,
    AuditSeverity,
    MetadataAuditIssue,
)
from discography_analyzer.models import (
    AlbumCompletenessIssue,
    Track,
    TrackStatus,
    folder_summary_text,
)


def make_track(identifier: str, folder: str, file_format: str, **values) -> Track:
    path = Path("/music") / folder / identifier
    return Track(
        id=identifier,
        path=path,
        root=Path("/music"),
        filename=identifier,
        relative_path=f"{folder}/{identifier}",
        relative_folder=folder,
        format=file_format,
        size_bytes=1024 * 1024,
        **values,
    )


def audit_issue(track_id: str, severity: AuditSeverity) -> MetadataAuditIssue:
    return MetadataAuditIssue(
        id=f"{track_id}-{severity.name}",
        track_id=track_id,
        severity=severity,
        category=AuditCategory.REQUIRED,
        field="year",
        message="Не указан год",
    )


class FolderSummaryTests(unittest.TestCase):
    def test_artist_folder_summarises_every_album_below_it(self) -> None:
        tracks = [
            make_track(
                "1.flac",
                "Artist/(2015) A",
                "FLAC",
                album="A",
                year="2015",
                album_artist="Artist",
                duration_seconds=200,
                sample_rate=44100,
                bit_depth=16,
                cover_hash="front",
            ),
            make_track(
                "2.flac",
                "Artist/(2015) A",
                "FLAC",
                album="A",
                year="2015",
                album_artist="Artist",
                duration_seconds=100,
                sample_rate=96000,
                bit_depth=24,
            ),
            make_track(
                "3.mp3",
                "Artist/(2017) B",
                "MP3",
                album="B",
                year="2017-05-01",
                artist="Artist",
                duration_seconds=3600,
                bitrate=320_000,
                status=TrackStatus.DUPLICATE,
                cover_hash="broken",
                cover_error="broken PNG file",
            ),
        ]
        gap = AlbumCompletenessIssue(
            id="gap",
            relative_folder="Artist/(2015) A",
            album="A",
            disc=1,
            present_numbers=(1, 2),
            missing_numbers=(3,),
            expected_total=3,
            total_from_tags=True,
        )

        text = folder_summary_text(
            "Artist",
            "Artist",
            tracks,
            [gap],
            [
                audit_issue("1.flac", AuditSeverity.ERROR),
                audit_issue("3.mp3", AuditSeverity.WARNING),
            ],
            cover_file="folder.jpg",
        )

        for line in (
            "Файлов: 3 · подпапок с файлами: 2",
            "Длительность: 1:05:00",
            "Размер: 3.00 MB",
            "Форматы: FLAC — 2 (44.1 kHz/16 bit; 96 kHz/24 bit) · MP3 — 1 (320 kbps)",
            "Альбомы: A (2015), B (2017)",
            "Исполнители: Artist",
            "Статусы: уникальных 2 · дубликатов 1 · вариаций 0 · конфликтов 0",
            "Встроенная обложка: 1 из 3 · повреждена: 1",
            "Файл обложки в папке: folder.jpg",
            "• Artist/(2015) A · A: ⚠ пропущены № 3; ожидается 3",
            "Ошибок 1 · предупреждений 1 · рекомендаций 0",
        ):
            self.assertIn(line, text.splitlines())

    def test_album_folder_without_problems_says_so(self) -> None:
        tracks = [
            make_track(
                f"{number}.mp3",
                "Album",
                "MP3",
                album="Album",
                duration_seconds=180,
                bitrate=bitrate,
            )
            for number, bitrate in ((1, 192_000), (2, 256_000))
        ]

        lines = folder_summary_text("Album", "Album", tracks, [], []).splitlines()

        # Variable bitrates read as a range, not as one entry per value.
        self.assertIn("Форматы: MP3 — 2 (192–256 kbps)", lines)
        self.assertIn("Файлов: 2", lines)
        self.assertIn("Встроенная обложка: 0 из 2", lines)
        self.assertIn("Пропуски по тегам Track # не обнаружены", lines)
        self.assertIn("Замечаний не обнаружено", lines)
        self.assertFalse(any(line.startswith("Файл обложки") for line in lines))


if __name__ == "__main__":
    unittest.main()
