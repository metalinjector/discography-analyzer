import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discography_analyzer.copying import (
    NOT_COPIED_FOLDER,
    CopyMode,
    build_copy_plan,
    execute_copy_plan,
    flat_copy_filename,
    order_tracks_for_copy,
)
from discography_analyzer.models import Track, TrackStatus


def make_track(
    identifier: str,
    status: TrackStatus,
    *,
    root: Path = Path("/music"),
    folder: str = "Artist/Album",
    year: str = "2009",
    artist: str = "Yanni",
    album: str = "If I Could Tell You",
    title: str = "With An Orchid",
    track_number: str = "5/11",
    related: list[str] | None = None,
    variation: str = "",
    duration: int | None = 180,
) -> Track:
    path = root / folder / f"{identifier}.flac"
    return Track(
        id=identifier,
        path=path,
        root=root,
        filename=path.name,
        relative_path=str(path.relative_to(root)),
        relative_folder=folder,
        format="FLAC",
        size_bytes=100,
        filename_title=title,
        comparison_title=title,
        base_title="Smile" if variation else title,
        variation=variation,
        related_track_ids=list(related or []),
        status=status,
        title=title,
        artist=artist,
        album=album,
        track_number=track_number,
        year=year,
        duration_seconds=duration,
    )


class CopyingTests(unittest.TestCase):
    def test_flat_filename_matches_requested_pattern(self) -> None:
        track = make_track("orchid", TrackStatus.UNIQUE)

        self.assertEqual(
            flat_copy_filename(track, 1, 3),
            (
                "01 Yanni - If I Could Tell You (2009) - "
                "05-With An Orchid.flac"
            ),
        )

    def test_oldest_direct_duplicate_is_kept_without_transitive_data_loss(self) -> None:
        first = make_track(
            "a",
            TrackStatus.DUPLICATE,
            year="2000",
            related=["b"],
        )
        bridge = make_track(
            "b",
            TrackStatus.DUPLICATE,
            year="2001",
            related=["a", "c"],
        )
        last = make_track(
            "c",
            TrackStatus.DUPLICATE,
            year="2002",
            related=["b"],
        )

        plan = build_copy_plan([last, bridge, first])

        self.assertEqual([track.id for track in plan.selected], ["a", "c"])
        self.assertEqual([item.track.id for item in plan.rejected], ["b"])
        self.assertEqual(plan.rejected[0].duplicate_of_id, "a")

    def test_identical_later_variation_is_rejected(self) -> None:
        source = make_track(
            "source",
            TrackStatus.UNIQUE,
            year="2000",
            title="Smile",
        )
        older_mix = make_track(
            "mix-old",
            TrackStatus.VARIATION,
            year="2001",
            title="Smile (Mix)",
            variation="Mix",
            duration=210,
        )
        newer_mix = make_track(
            "mix-new",
            TrackStatus.VARIATION,
            year="2005",
            title="Smile (Mix)",
            variation="mix",
            duration=210,
        )
        conflict = make_track(
            "conflict",
            TrackStatus.CONFLICT,
            year="2006",
        )

        plan = build_copy_plan([newer_mix, conflict, source, older_mix])

        self.assertEqual(
            [track.id for track in plan.selected],
            ["source", "mix-old"],
        )
        self.assertEqual(
            [item.track.id for item in plan.rejected],
            ["mix-new", "conflict"],
        )
        self.assertEqual(plan.rejected[0].duplicate_of_id, "mix-old")

    def test_variations_with_incomplete_identity_are_not_discarded(self) -> None:
        missing_artist = make_track(
            "missing-artist",
            TrackStatus.VARIATION,
            year="2001",
            artist="",
            title="Smile (Mix)",
            variation="Mix",
            duration=210,
        )
        missing_duration = make_track(
            "missing-duration",
            TrackStatus.VARIATION,
            year="2002",
            title="Smile (Mix)",
            variation="Mix",
            duration=None,
        )

        plan = build_copy_plan([missing_duration, missing_artist])

        self.assertEqual(
            [track.id for track in plan.selected],
            ["missing-artist", "missing-duration"],
        )
        self.assertEqual(plan.rejected, ())

    def test_artist_grouping_is_alphabetical_with_descending_dates(self) -> None:
        beta_old = make_track(
            "beta-old",
            TrackStatus.UNIQUE,
            artist="Beta",
            year="1999",
        )
        alpha_old = make_track(
            "alpha-old",
            TrackStatus.UNIQUE,
            artist="Alpha",
            year="2001",
        )
        alpha_new = make_track(
            "alpha-new",
            TrackStatus.UNIQUE,
            artist="Alpha",
            year="2020",
        )

        ordered = order_tracks_for_copy(
            [beta_old, alpha_old, alpha_new],
            group_by_artist=True,
        )

        self.assertEqual(
            [track.id for track in ordered],
            ["alpha-new", "alpha-old", "beta-old"],
        )

    def test_flat_copy_numbering_uses_artist_grouping(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            destination = Path(directory) / "destination"
            beta = make_track(
                "beta",
                TrackStatus.UNIQUE,
                root=root,
                artist="Beta",
                year="1999",
            )
            alpha = make_track(
                "alpha",
                TrackStatus.UNIQUE,
                root=root,
                artist="Alpha",
                year="2020",
            )
            beta.path.parent.mkdir(parents=True)
            beta.path.write_bytes(b"beta")
            alpha.path.write_bytes(b"alpha")

            result = execute_copy_plan(
                build_copy_plan([beta, alpha]),
                destination,
                CopyMode.FLAT,
                group_by_artist=True,
            )

            names = sorted(path.name for path in destination.glob("*.flac"))
            self.assertEqual(result.copied_selected, 2)
            self.assertTrue(names[0].startswith("01 Alpha - "))
            self.assertTrue(names[1].startswith("02 Beta - "))

    def test_flat_copy_and_rejected_folder_do_not_overwrite(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            destination = Path(directory) / "destination"
            selected = make_track(
                "selected",
                TrackStatus.UNIQUE,
                root=root,
            )
            rejected = make_track(
                "rejected",
                TrackStatus.CONFLICT,
                root=root,
                title="Rejected",
            )
            selected.path.parent.mkdir(parents=True)
            selected.path.write_bytes(b"selected")
            rejected.path.write_bytes(b"rejected")
            plan = build_copy_plan([selected, rejected])

            first_result = execute_copy_plan(
                plan,
                destination,
                CopyMode.FLAT,
                include_rejected=True,
            )
            second_result = execute_copy_plan(
                plan,
                destination,
                CopyMode.FLAT,
                include_rejected=True,
            )

            self.assertEqual(first_result.copied_selected, 1)
            self.assertEqual(first_result.copied_rejected, 1)
            self.assertEqual(second_result.copied_selected, 1)
            self.assertEqual(second_result.copied_rejected, 1)
            self.assertEqual(len(list(destination.glob("*.flac"))), 2)
            rejected_root = destination / NOT_COPIED_FOLDER
            self.assertEqual(len(list(rejected_root.glob("*.flac"))), 2)
            self.assertEqual(
                {path.read_bytes() for path in destination.glob("*.flac")},
                {b"selected"},
            )

    def test_tree_copy_preserves_relative_structure_for_both_sets(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            destination = Path(directory) / "destination"
            selected = make_track(
                "selected",
                TrackStatus.UNIQUE,
                root=root,
                folder="Artist/Album A",
            )
            rejected = make_track(
                "rejected",
                TrackStatus.CONFLICT,
                root=root,
                folder="Artist/Album B",
            )
            selected.path.parent.mkdir(parents=True)
            rejected.path.parent.mkdir(parents=True)
            selected.path.write_bytes(b"selected")
            rejected.path.write_bytes(b"rejected")
            plan = build_copy_plan([selected, rejected])

            result = execute_copy_plan(
                plan,
                destination,
                CopyMode.TREE,
                include_rejected=True,
            )

            self.assertEqual(result.copied_selected, 1)
            self.assertEqual(result.copied_rejected, 1)
            self.assertTrue(
                (destination / "Artist/Album A/selected.flac").is_file()
            )
            self.assertTrue(
                (
                    destination
                    / NOT_COPIED_FOLDER
                    / "Artist/Album B/rejected.flac"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()
