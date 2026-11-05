from __future__ import annotations

import hashlib
import struct
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mutagen.flac import FLAC
from openpyxl import load_workbook

from discography_analyzer.completeness import RELEASE_TOTAL
from discography_analyzer.exporter import export_xlsx
from discography_analyzer.models import Track, folder_summary_text
from discography_analyzer.releases import (
    ReleaseStatus,
    build_release,
    build_releases,
    cover_file_matches,
    quality_summary,
    raw_tag_values,
    release_artists,
    release_card_text,
    release_type,
)
from discography_analyzer.scanner import analyze_collection

ROOT = Path("/music")


def make(folder: str, number: int | str, **values) -> Track:
    name = f"{number}.flac" if isinstance(number, int) else number
    path = ROOT / folder / name
    values.setdefault("format", "FLAC")
    return Track(
        id=f"{folder}/{name}/{values.get('disc_number', '')}",
        path=path,
        root=ROOT,
        filename=name,
        relative_path=f"{folder}/{name}",
        relative_folder=folder,
        size_bytes=1024 * 1024,
        **values,
    )


def disc_tracks(
    folder: str,
    album: str,
    disc: str,
    numbers,
    total: int | None,
    **values,
) -> list[Track]:
    return [
        make(
            folder,
            number,
            album=album,
            disc_number=disc,
            track_number=f"{number}/{total}" if total else str(number),
            **values,
        )
        for number in numbers
    ]


def qobuz_box() -> list[Track]:
    """12 + 12 + 9 tracks, every disc from 1, TRACKTOTAL 33 in every file."""
    return [
        *disc_tracks("Box/CD1", "Vol. 13", "1/3", range(1, 13), 33),
        *disc_tracks("Box/CD2", "Vol. 13", "2/3", range(1, 13), 33),
        *disc_tracks("Box/CD3", "Vol. 13", "3/3", range(1, 10), 33),
    ]


class ReleaseNumberingTests(unittest.TestCase):
    def test_a_box_short_of_a_disc_is_an_incomplete_release(self) -> None:
        # «The Dark Side of the Moog, Vol. 3»: 6 + 6 + 4 of 18, disc 4 gone.
        tracks = [
            *disc_tracks("Moog/CD1", "Moog", "1/4", range(1, 7), 18),
            *disc_tracks("Moog/CD2", "Moog", "2/4", range(1, 7), 18),
            *disc_tracks("Moog/CD3", "Moog", "3/4", range(1, 5), 18),
        ]

        release = build_release("Moog", tracks, ROOT)

        self.assertEqual(release.numbering.mode, RELEASE_TOTAL)
        self.assertEqual(release.status, ReleaseStatus.INCOMPLETE)
        self.assertEqual(release.status_text, "Не хватает 2")
        self.assertEqual(release.counts_text, "16/18 · 4 CD")
        self.assertEqual(release.notes[:2], ("нет диска 4", "ещё 2 по итогу 18"))

    def test_disc_folders_without_totals_make_a_release_without_gaps(self) -> None:
        tracks = [
            *disc_tracks("Live/CD1", "Live", "", range(1, 4), None),
            *disc_tracks("Live/CD2", "Live", "", range(1, 3), None),
        ]

        release = build_release("Live", tracks, ROOT)

        self.assertEqual(release.numbering.discs, (1, 2))
        self.assertEqual(release.status, ReleaseStatus.NO_TOTAL)
        self.assertEqual(release.counts_text, "5 · 2 CD")


class ReleaseTests(unittest.TestCase):
    def test_discs_of_one_release_and_albums_of_one_folder(self) -> None:
        tracks = [
            *qobuz_box(),
            make("Singles", "a.flac", album="One", track_number="1/1"),
            make("Singles", "b.flac", album="Two", track_number="1/1"),
        ]

        releases = build_releases(tracks, ROOT)

        self.assertEqual(
            [(release.folder, release.album) for release in releases],
            [("Box", "Vol. 13"), ("Singles", "One"), ("Singles", "Two")],
        )
        self.assertEqual(releases[0].found, 33)
        self.assertEqual(releases[0].status, ReleaseStatus.COMPLETE)
        self.assertEqual(releases[0].counts_text, "33/33 · 3 CD")
        self.assertEqual(
            [release.id for release in releases],
            ["release::Box::vol. 13", "release::Singles::one", "release::Singles::two"],
        )

    def test_raw_tags_are_found_in_every_container(self) -> None:
        track = make("A", 1)
        track.all_tags = {
            "barcode": ["0885513007728"],
            "TPUB": ["Brain"],
            "TXXX:UPC": ["0602547022868"],
            "TSRC": ["DEA111"],
            "----:com.apple.iTunes:LABEL": ["Republic Records"],
            "----:com.apple.iTunes:EAN": ["<двоичные данные: 12 байт>"],
        }

        self.assertEqual(
            raw_tag_values(track, ("barcode", "upc", "ean")),
            ["0885513007728", "0602547022868"],
        )
        self.assertEqual(
            raw_tag_values(track, ("label",)), ["Brain", "Republic Records"]
        )
        self.assertEqual(raw_tag_values(track, ("isrc",)), ["DEA111"])

    def test_guests_co_artists_and_compilations(self) -> None:
        album = [
            make("AG", number, album="My Everything", album_artist="Ariana Grande", artist="Ariana Grande")
            for number in range(1, 13)
        ]
        album.append(
            make(
                "AG",
                13,
                album="My Everything",
                album_artist="Ariana Grande",
                artist="Jessie J, Ariana Grande & Nicki Minaj",
            )
        )
        duet = [
            make("KS", number, album_artist="Klaus Schulze", canonical_tags={"artist": ["Klaus Schulze", "Lisa Gerrard"]})
            for number in (1, 2)
        ]
        no_album_artist = [
            make("X", number, artist="Band" if number < 4 else "Band feat. Guest")
            for number in range(1, 5)
        ]
        various = [
            make("V", number, album_artist="Various Artists", artist=f"Artist {number}")
            for number in range(1, 4)
        ]

        self.assertEqual(
            release_artists(album),
            ("Ariana Grande", "Ariana Grande", ("Jessie J", "Nicki Minaj"), False),
        )
        self.assertEqual(
            release_artists(duet)[1:], ("Klaus Schulze, Lisa Gerrard", (), False)
        )
        self.assertEqual(release_artists(no_album_artist), ("Band", "Band", ("Guest",), False))
        self.assertEqual(
            release_artists(various), ("Various Artists", "Various Artists", (), True)
        )

    def test_type_comes_from_the_tag_or_from_the_normalizer_rule(self) -> None:
        tagged = make("T", 1)
        tagged.all_tags = {"releasetype": ["album", "compilation"]}
        id3 = make("T", 2)
        id3.all_tags = {"TXXX:MusicBrainz Album Type": ["single"]}

        self.assertEqual(release_type([tagged], 0, 60), ("Album (Compilation)", True))
        self.assertEqual(release_type([id3], 0, 60), ("Single", True))
        tracks = [make("T", number) for number in range(1, 8)]
        self.assertEqual(release_type(tracks, 0, 7 * 60), ("Album", False))
        self.assertEqual(release_type(tracks[:4], 0, 12 * 60), ("EP", False))
        # Irrlicht: three long tracks are an album, not a single.
        self.assertEqual(release_type(tracks[:3], 0, 52 * 60), ("Album", False))
        self.assertEqual(release_type(tracks[:1], 0, 22 * 60), ("EP", False))
        self.assertEqual(release_type(tracks[:2], 0, 7 * 60), ("Single", False))
        # A short copy of a 12-track album is still an album.
        self.assertEqual(release_type(tracks[:5], 12, 15 * 60), ("Album", False))

    def test_quality_per_format(self) -> None:
        flac = [make("Q", n, sample_rate=44100, bit_depth=16) for n in (1, 2)]
        hires = [make("Q", 3, sample_rate=96000, bit_depth=24)]
        mp3 = [make("Q", n, format="MP3", bitrate=bitrate) for n, bitrate in ((4, 192000), (5, 320000))]

        self.assertEqual(quality_summary(flac), ("FLAC", "44.1/16"))
        self.assertEqual(quality_summary(flac + hires), ("FLAC", "44.1/16, 96/24"))
        self.assertEqual(quality_summary(mp3), ("MP3", "192–320 kbps"))
        self.assertEqual(
            quality_summary(flac + mp3), ("FLAC + MP3", "FLAC 44.1/16 · MP3 192–320 kbps")
        )

    def test_editions_paths_and_covers_become_notes(self) -> None:
        first = disc_tracks("A/Irrlicht", "Irrlicht", "", range(1, 4), 3)
        copy = disc_tracks("B/Irrlicht", "Irrlicht", "", range(1, 4), 3)
        for track in first + copy:
            track.all_tags = {"BARCODE": ["0004228331272"]}
        mixed = disc_tracks("C", "Mixed", "", (1, 2), 2)
        mixed[0].all_tags = {"BARCODE": ["111"]}
        mixed[1].all_tags = {"BARCODE": ["222"]}
        mixed[0].cover_hash = "front"
        long_folder = "D/" + "x" * 260
        long_path = disc_tracks(long_folder, "Long", "", (1,), 1)

        releases = {
            release.folder: release
            for release in build_releases(first + copy + mixed + long_path, ROOT)
        }

        self.assertIn("то же издание в: B/Irrlicht", releases["A/Irrlicht"].notes)
        self.assertIn("то же издание в: A/Irrlicht", releases["B/Irrlicht"].notes)
        self.assertIn("разные издания: 111, 222", releases["C"].notes)
        self.assertIn("обложка встроена не везде (1/2)", releases["C"].notes)
        self.assertIn("нет обложки", releases[long_folder].notes)
        self.assertTrue(
            any(
                note.startswith("путь ") and note.endswith("> 259")
                for note in releases[long_folder].notes
            )
        )

    def test_the_cover_file_is_compared_with_the_embedded_picture(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "cover.jpg").write_bytes(b"picture")
            tracks = [
                Track(
                    id=str(number),
                    path=folder / f"{number}.flac",
                    root=folder,
                    filename=f"{number}.flac",
                    relative_path=f"{number}.flac",
                    relative_folder=str(folder),
                    format="FLAC",
                    size_bytes=1,
                    album="A",
                    track_number=str(number),
                    cover_hash=hashlib.sha256(b"picture").hexdigest(),
                )
                for number in (1, 2)
            ]
            release = build_release(str(folder), tracks, folder)

            self.assertEqual(release.cover_file, "cover.jpg")
            self.assertTrue(cover_file_matches(release))
            for track in tracks:
                track.cover_hash = "other"
            self.assertFalse(cover_file_matches(release))

    def test_the_release_card_says_what_is_missing_and_where_to_look(self) -> None:
        tracks = [
            *disc_tracks("Moog/CD1", "Moog", "1/2", range(1, 7), 14),
            *disc_tracks("Moog/CD2", "Moog", "2/2", (1, 2, 4, 5, 6), 14),
        ]
        for track in tracks:
            track.all_tags = {"BARCODE": ["0885513014023"], "LABEL": ["Synthetic Symphony"]}
            track.album_artist = "Klaus Schulze"
            track.year = "1996"
        release = build_release("Moog", tracks, ROOT)

        card = release_card_text(release)

        self.assertTrue(card.startswith("РЕЛИЗ\nMoog (1996)\n"))
        self.assertIn("Лейбл: Synthetic Symphony", card)
        self.assertIn("нумерация по дискам, итог 14 — на весь релиз", card)
        self.assertIn("• CD2: нет № 3", card)
        self.assertIn("• ещё 2 по итогу 14, диск не определить", card)
        self.assertIn("Искать это издание по BARCODE 0885513014023.", card)
        self.assertIn("CD2 · 06  6.flac", card)

    def test_the_folder_summary_lists_its_releases(self) -> None:
        tracks = qobuz_box() + disc_tracks("Box2", "Short", "1/1", (1, 3), 3)
        releases = build_releases(tracks, ROOT)

        text = folder_summary_text("Artist", "Artist", tracks, [], [], "", releases)

        self.assertIn("РЕЛИЗЫ\nВсего 2: полных 1 · неполных 1", text)
        self.assertIn("• Short: Не хватает 1, 2/3, Single * — нет № 2", text)


def _flac(seconds: float) -> bytes:
    samples = int(seconds * 44100)
    info = (44100 << 44) | (1 << 41) | (15 << 36) | samples
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6 + info.to_bytes(8, "big") + b"\x00" * 16
    return b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo


class ScannedReleaseTests(unittest.TestCase):
    def test_a_scanned_qobuz_box_is_one_complete_release(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for disc in (1, 2):
                for number in (1, 2):
                    path = root / "Klaus Schulze" / "Box" / f"CD{disc}" / f"{number:02d}.flac"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(_flac(600))
                    audio = FLAC(path)
                    audio["ALBUM"] = "Box"
                    audio["ALBUMARTIST"] = "Klaus Schulze"
                    audio["ARTIST"] = "Klaus Schulze"
                    audio["TRACKNUMBER"] = str(number)
                    audio["TRACKTOTAL"] = "4"
                    audio["DISCNUMBER"] = str(disc)
                    audio["DISCTOTAL"] = "2"
                    audio["BARCODE"] = "0885513007728"
                    audio["LABEL"] = "Revisited Records"
                    audio.save()

            result = analyze_collection(
                root, True, ["FLAC"], [], True, True, True, [],
                threading.Event(), lambda *_args: None,
            )

        self.assertEqual(result.completeness_issues, [])
        self.assertEqual(len(result.releases), 1)
        release = result.releases[0]
        self.assertEqual(release.folder, str(Path("Klaus Schulze/Box")))
        self.assertEqual(release.status, ReleaseStatus.COMPLETE)
        self.assertEqual(release.barcodes, ("0885513007728",))
        self.assertEqual(release.label, "Revisited Records")
        self.assertEqual(release.type_text, "Album *")
        self.assertTrue(result.gaps_checked)


class ReleaseSheetTests(unittest.TestCase):
    def test_the_report_has_a_releases_sheet(self) -> None:
        tracks = qobuz_box() + disc_tracks("Short", "Short", "1/1", (1, 3), 3)
        releases = build_releases(tracks, ROOT)
        with TemporaryDirectory() as directory:
            path = export_xlsx(
                tracks,
                Path(directory) / "report.xlsx",
                {"releases": True},
                ["base_title"],
                {},
                [],
                releases,
            )
            workbook = load_workbook(path)
            sheet = workbook["Релизы"]
            headers = [cell.value for cell in sheet[4]]
            rows = [
                [cell.value for cell in row]
                for row in sheet.iter_rows(min_row=5, max_row=6)
            ]
            fill = sheet.cell(6, headers.index("Комплект") + 1).fill.fgColor.rgb
            workbook.close()

        self.assertEqual(workbook.sheetnames, ["Релизы"])
        self.assertEqual(headers[:3], ["Год", "Альбом", "Тип"])
        self.assertEqual(rows[0][headers.index("Комплект")], "Полный")
        self.assertEqual(rows[1][headers.index("Комплект")], "Не хватает 1")
        self.assertEqual(rows[1][headers.index("Замечания")], "нет № 2 · нет обложки")
        self.assertTrue(fill.endswith("F8DFDA"))


if __name__ == "__main__":
    unittest.main()
