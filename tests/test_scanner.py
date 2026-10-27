import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from discography_analyzer.scanner import _collect_files, analyze_collection


class ScannerTests(unittest.TestCase):
    def test_non_recursive_scan_order_is_stable(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "zeta.mp3").write_bytes(b"")
            (root / "Alpha.mp3").write_bytes(b"")

            files, folders = _collect_files(
                root=root,
                include_subfolders=False,
                excluded_folders=[],
                selected_extensions={".mp3"},
                stop_event=threading.Event(),
                progress=lambda *_args: None,
            )

            self.assertEqual(
                [path.name for path in files],
                ["Alpha.mp3", "zeta.mp3"],
            )
            self.assertEqual(folders, 1)

    def test_hidden_files_are_not_collected(self) -> None:
        # macOS leaves AppleDouble "._" companions on FAT/exFAT/SMB volumes and
        # an interrupted tag write leaves its hidden temporary copy behind.
        # Both used to become tracks: the temporary copy even won the copy plan
        # over the real file, and the AppleDouble file was copied as unique.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "01 Song.flac",
                "._01 Song.flac",
                ".01 Song-audit-k3j2h1.flac",
            ):
                (root / name).write_bytes(b"")

            for include_subfolders in (True, False):
                with self.subTest(include_subfolders=include_subfolders):
                    files, _folders = _collect_files(
                        root=root,
                        include_subfolders=include_subfolders,
                        excluded_folders=[],
                        selected_extensions={".flac"},
                        stop_event=threading.Event(),
                        progress=lambda *_args: None,
                    )

                    self.assertEqual(
                        [path.name for path in files],
                        ["01 Song.flac"],
                    )

    def test_unreadable_file_does_not_discard_readable_results(self) -> None:
        root = Path("/music")
        unreadable = root / "unreadable.mp3"
        readable = root / "readable.mp3"
        progress_updates: list[int] = []
        states: list[str] = []

        def fake_stat(path: Path, *_args, **_kwargs):
            if path == unreadable:
                raise PermissionError("access denied")
            return SimpleNamespace(st_size=1024, st_mtime=0, st_ctime=0)

        with (
            patch(
                "discography_analyzer.scanner._collect_files",
                return_value=([unreadable, readable], 1),
            ),
            patch(
                "discography_analyzer.scanner.Path.stat",
                autospec=True,
                side_effect=fake_stat,
            ),
            patch("discography_analyzer.scanner.read_metadata"),
        ):
            result = analyze_collection(
                root=root,
                include_subfolders=True,
                selected_formats=["MP3"],
                excluded_folders=[],
                use_tags=False,
                detect_variations=False,
                check_track_gaps=False,
                variation_markers=[],
                stop_event=threading.Event(),
                progress=lambda percent, state, *_args: (
                    progress_updates.append(percent),
                    states.append(state),
                ),
            )

        self.assertEqual([track.filename for track in result.tracks], ["readable.mp3"])
        self.assertTrue(result.audit_issues)
        self.assertEqual(progress_updates[-1], 100)
        self.assertIn("Аудит метаданных...", states)
        self.assertIn("Пропущено недоступных файлов: 1", states[-1])


if __name__ == "__main__":
    unittest.main()
