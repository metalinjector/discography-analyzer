from pathlib import Path
import unittest

from discography_analyzer.classifier import classify_tracks
from discography_analyzer.models import Track, TrackStatus


def make_track(
    identifier: str,
    filename_title: str,
    artist: str = "Artist A",
    duration: int | None = 180,
    title: str = "",
    album: str = "Album",
) -> Track:
    path = Path(f"/music/{identifier}.mp3")
    return Track(
        id=identifier,
        path=path,
        root=Path("/music"),
        filename=path.name,
        relative_path=path.name,
        relative_folder="(корень)",
        format="MP3",
        size_bytes=100,
        filename_title=filename_title,
        title=title,
        artist=artist,
        album=album,
        duration_seconds=duration,
    )


class ClassifierTests(unittest.TestCase):
    def test_duplicate_requires_one_common_artist(self) -> None:
        tracks = [
            make_track("a", "Song", "Artist A"),
            make_track("b", "Song", "Artist A feat. Guest"),
        ]
        classify_tracks(tracks)
        self.assertEqual(
            [track.status for track in tracks],
            [TrackStatus.DUPLICATE, TrackStatus.DUPLICATE],
        )
        self.assertIn("b.mp3", tracks[0].relation)
        self.assertIn("a.mp3", tracks[1].relation)

    def test_duplicate_component_keeps_only_direct_relations(self) -> None:
        first = make_track("a", "Song", "Artist 1")
        bridge = make_track("b", "Song", "Artist 1 & Artist 2")
        last = make_track("c", "Song", "Artist 2")

        classify_tracks([first, bridge, last])

        self.assertTrue(
            all(
                track.status == TrackStatus.DUPLICATE
                for track in (first, bridge, last)
            )
        )
        self.assertEqual(first.related_track_ids, [bridge.id])
        self.assertEqual(set(bridge.related_track_ids), {first.id, last.id})
        self.assertEqual(last.related_track_ids, [bridge.id])
        self.assertNotIn(last.filename, first.relation)
        self.assertNotIn(first.filename, last.relation)
        self.assertEqual(
            {track.duplicate_group_id for track in (first, bridge, last)},
            {first.duplicate_group_id},
        )

    def test_duplicate_relation_survives_when_partner_is_conflict(self) -> None:
        duplicate = make_track(
            "duplicate",
            "Song",
            artist="Artist A",
            album="Album",
        )
        mixed = make_track(
            "mixed",
            "Song",
            artist="Artist A",
            album="",
        )
        conflict = make_track(
            "conflict",
            "Song",
            artist="Artist B",
            album="Album",
        )

        classify_tracks([duplicate, mixed, conflict])

        self.assertEqual(duplicate.status, TrackStatus.DUPLICATE)
        self.assertEqual(mixed.status, TrackStatus.CONFLICT)
        self.assertEqual(conflict.status, TrackStatus.CONFLICT)
        self.assertEqual(duplicate.related_track_ids, [mixed.id])
        self.assertIn(duplicate.id, mixed.related_track_ids)
        self.assertIn(mixed.filename, duplicate.relation)
        self.assertIn(duplicate.filename, mixed.relation)
        self.assertIn(conflict.filename, mixed.relation)

    def test_known_duration_difference_means_different_tracks(self) -> None:
        tracks = [
            make_track("a", "Song", duration=180),
            make_track("b", "Song", duration=181),
        ]
        classify_tracks(tracks)
        self.assertTrue(all(track.status == TrackStatus.UNIQUE for track in tracks))

    def test_fractional_duration_difference_has_no_tolerance(self) -> None:
        left = make_track("a", "Song", duration=180)
        right = make_track("b", "Song", duration=180)
        left.duration_exact = 180.001
        right.duration_exact = 180.002
        classify_tracks([left, right])
        self.assertEqual(left.status, TrackStatus.UNIQUE)
        self.assertEqual(right.status, TrackStatus.UNIQUE)

    def test_title_comparison_is_case_sensitive(self) -> None:
        tracks = [make_track("a", "Song"), make_track("b", "song")]
        classify_tracks(tracks)
        self.assertTrue(all(track.status == TrackStatus.UNIQUE for track in tracks))

    def test_missing_required_artist_creates_conflict(self) -> None:
        tracks = [make_track("a", "Song", artist=""), make_track("b", "Song")]
        classify_tracks(tracks)
        self.assertTrue(
            all(track.status == TrackStatus.CONFLICT for track in tracks)
        )

    def test_different_artists_and_complete_albums_are_not_conflict(self) -> None:
        tracks = [
            make_track("a", "Song", artist="Artist A", album="Album A"),
            make_track("b", "Song", artist="Artist B", album="Album B"),
        ]
        classify_tracks(tracks)
        self.assertTrue(all(track.status == TrackStatus.UNIQUE for track in tracks))

    def test_different_artists_and_missing_album_are_conflict(self) -> None:
        tracks = [
            make_track("a", "Song", artist="Artist A", album=""),
            make_track("b", "Song", artist="Artist B", album="Album B"),
        ]
        classify_tracks(tracks)
        self.assertTrue(
            all(track.status == TrackStatus.CONFLICT for track in tracks)
        )

    def test_variation_links_to_exactly_one_source(self) -> None:
        source = make_track("source", "Smile")
        remix = make_track("remix", "Smile (Remix)", duration=220)
        classify_tracks([source, remix])
        self.assertEqual(source.status, TrackStatus.UNIQUE)
        self.assertEqual(remix.status, TrackStatus.VARIATION)
        self.assertEqual(remix.base_title, "Smile")
        self.assertEqual(remix.variation, "Remix")
        self.assertEqual(remix.source_track_id, source.id)
        self.assertIn("Исходник", remix.relation)
        self.assertIn("Вариации", source.relation)

    def test_variation_without_source_stays_standalone(self) -> None:
        remix = make_track("remix", "Smile (Remix)")
        classify_tracks([remix])
        self.assertEqual(remix.status, TrackStatus.UNIQUE)
        self.assertEqual(remix.base_title, "Smile (Remix)")
        self.assertIsNone(remix.source_track_id)

    def test_variation_with_multiple_sources_is_ambiguous(self) -> None:
        source_a = make_track("source-a", "Smile")
        source_b = make_track("source-b", "Smile")
        remix = make_track("remix", "Smile (Remix)")
        classify_tracks([source_a, source_b, remix])
        self.assertEqual(remix.status, TrackStatus.UNIQUE)
        self.assertEqual(remix.base_title, "Smile (Remix)")
        self.assertIsNone(remix.source_track_id)

    def test_variation_can_be_detected_from_filename_when_tag_title_is_plain(self) -> None:
        source = make_track("source", "Smile", title="Smile")
        live = make_track("live", "Smile (Live)", title="Smile", duration=200)
        classify_tracks([source, live], use_tags=True)
        self.assertEqual(live.status, TrackStatus.VARIATION)
        self.assertEqual(live.variation, "Live")

    def test_unlinked_filename_only_variation_keeps_full_filename_title(self) -> None:
        live = make_track("live", "Smile (Live)", title="Smile", duration=200)
        classify_tracks([live], use_tags=True)
        self.assertEqual(live.status, TrackStatus.UNIQUE)
        self.assertEqual(live.base_title, "Smile (Live)")


if __name__ == "__main__":
    unittest.main()
