from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .models import Track, TrackStatus
from .parsing import artist_set, detect_variation


def prepare_titles(
    tracks: Iterable[Track],
    use_tags: bool,
    detect_variations: bool,
    variation_markers: list[str],
) -> None:
    for track in tracks:
        track.comparison_title = (
            track.title.strip() if use_tags and track.title.strip() else track.filename_title.strip()
        )
        track.base_title = track.comparison_title
        track.variation = ""
        track.potential_base = ""
        track.potential_variation = ""
        track.source_track_id = None
        track.relation = ""
        track.related_track_ids.clear()
        track.duplicate_group_id = ""
        track.status = TrackStatus.UNIQUE

        if not detect_variations:
            continue
        candidate = detect_variation(track.comparison_title, variation_markers)
        if candidate is None and track.filename_title != track.comparison_title:
            candidate = detect_variation(track.filename_title, variation_markers)
        if candidate:
            track.potential_base, track.potential_variation = candidate


def classify_tracks(
    tracks: list[Track],
    use_tags: bool = True,
    detect_variations: bool = True,
    variation_markers: list[str] | None = None,
) -> list[Track]:
    """Apply the strict, deterministic rules from the functional specification."""
    if variation_markers is None:
        from .constants import DEFAULT_VARIATION_MARKERS

        variation_markers = DEFAULT_VARIATION_MARKERS

    prepare_titles(tracks, use_tags, detect_variations, variation_markers)

    # A possible variation is linked only to exactly one real, non-variation source.
    artist_sets = {track.id: artist_set(track.artist) for track in tracks}
    sources_by_title: dict[str, list[Track]] = defaultdict(list)
    for origin in tracks:
        if not origin.potential_variation:
            sources_by_title[origin.comparison_title].append(origin)
    for track in tracks:
        if not track.potential_variation:
            continue
        track_artists = artist_sets[track.id]
        candidates = [
            origin
            for origin in sources_by_title.get(track.potential_base, ())
            if origin.id != track.id
            and bool(artist_sets[origin.id])
            and bool(track_artists)
            and bool(artist_sets[origin.id] & track_artists)
        ]
        if len(candidates) == 1:
            track.base_title = track.potential_base
            track.variation = track.potential_variation
            track.source_track_id = candidates[0].id
            track.status = TrackStatus.VARIATION

    # When the version marker came only from the filename and no unique source
    # was found, the complete filename title remains the standalone title.
    for track in tracks:
        if (
            track.potential_variation
            and track.status != TrackStatus.VARIATION
            and track.comparison_title == track.potential_base
            and track.filename_title != track.comparison_title
        ):
            track.base_title = track.filename_title

    ordinary = [track for track in tracks if track.status != TrackStatus.VARIATION]
    groups: dict[str, list[Track]] = defaultdict(list)
    for track in ordinary:
        groups[track.base_title].append(track)

    duplicate_ids: set[str] = set()
    conflict_ids: set[str] = set()
    duplicate_neighbors: dict[str, set[str]] = defaultdict(set)
    conflict_neighbors: dict[str, set[str]] = defaultdict(set)
    for title_group in groups.values():
        for index, left in enumerate(title_group):
            for right in title_group[index + 1 :]:
                left_duration = left.comparison_duration
                right_duration = right.comparison_duration
                # A known duration difference always means different tracks.
                if (
                    left_duration is not None
                    and right_duration is not None
                    and left_duration != right_duration
                ):
                    continue
                if left_duration is None or right_duration is None:
                    conflict_ids.update((left.id, right.id))
                    conflict_neighbors[left.id].add(right.id)
                    conflict_neighbors[right.id].add(left.id)
                    continue

                left_artists = artist_sets[left.id]
                right_artists = artist_sets[right.id]
                if not left_artists or not right_artists:
                    conflict_ids.update((left.id, right.id))
                    conflict_neighbors[left.id].add(right.id)
                    conflict_neighbors[right.id].add(left.id)
                elif left_artists & right_artists:
                    duplicate_ids.update((left.id, right.id))
                    duplicate_neighbors[left.id].add(right.id)
                    duplicate_neighbors[right.id].add(left.id)
                elif not left.album.strip() or not right.album.strip():
                    conflict_ids.update((left.id, right.id))
                    conflict_neighbors[left.id].add(right.id)
                    conflict_neighbors[right.id].add(left.id)

    for track in ordinary:
        # Manual-review uncertainty takes precedence when a file participates
        # in both a confirmed and an incomplete comparison group.
        if track.id in conflict_ids:
            track.status = TrackStatus.CONFLICT
        elif track.id in duplicate_ids:
            track.status = TrackStatus.DUPLICATE
        else:
            track.status = TrackStatus.UNIQUE

    by_id = {track.id: track for track in tracks}

    # Build explicit duplicate components so every row names the other files
    # that caused its classification.
    seen: set[str] = set()
    for track_id in sorted(duplicate_neighbors):
        if track_id in seen or by_id[track_id].status != TrackStatus.DUPLICATE:
            continue
        stack = [track_id]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component or by_id[current].status != TrackStatus.DUPLICATE:
                continue
            component.add(current)
            stack.extend(duplicate_neighbors[current] - component)
        seen.update(component)
        group_id = min(component) if len(component) > 1 else ""
        for current in component:
            by_id[current].duplicate_group_id = group_id

    # Confirmed duplicate edges remain visible even when one endpoint also
    # participates in an incomplete comparison and therefore has CONFLICT
    # as its primary status.
    for track_id, neighbors in duplicate_neighbors.items():
        item = by_id[track_id]
        others = sorted(
            (by_id[other] for other in neighbors),
            key=lambda other: (
                other.relative_folder.casefold(),
                other.filename.casefold(),
            ),
        )
        item.related_track_ids.extend(
            other.id for other in others if other.id not in item.related_track_ids
        )
        if others:
            prefix = (
                "Дубли"
                if item.status == TrackStatus.DUPLICATE
                else "Подтверждённые дубли"
            )
            item.relation = prefix + ": " + "; ".join(
                f"{other.filename} [{other.relative_folder}]" for other in others
            )

    for track_id, neighbors in conflict_neighbors.items():
        item = by_id[track_id]
        if item.status != TrackStatus.CONFLICT:
            continue
        others = sorted(
            (by_id[other] for other in neighbors),
            key=lambda other: (other.relative_folder.casefold(), other.filename.casefold()),
        )
        item.related_track_ids.extend(
            other.id for other in others if other.id not in item.related_track_ids
        )
        if others:
            conflict_text = "Проверить с: " + "; ".join(
                f"{other.filename} [{other.relative_folder}]" for other in others
            )
            item.relation = (
                f"{item.relation} · {conflict_text}"
                if item.relation
                else conflict_text
            )

    source_to_variations: dict[str, list[Track]] = defaultdict(list)
    for track in tracks:
        if track.status == TrackStatus.VARIATION and track.source_track_id:
            source_to_variations[track.source_track_id].append(track)
            source = by_id[track.source_track_id]
            track.related_track_ids.append(source.id)
            track.relation = f"Исходник: {source.filename} [{source.relative_folder}]"
    for source_id, variations in source_to_variations.items():
        source = by_id[source_id]
        source.related_track_ids.extend(
            variation.id
            for variation in variations
            if variation.id not in source.related_track_ids
        )
        variation_text = "Вариации: " + "; ".join(
            f"{variation.filename} ({variation.variation})"
            for variation in sorted(variations, key=lambda item: item.filename.casefold())
        )
        source.relation = (
            f"{source.relation} · {variation_text}" if source.relation else variation_text
        )
    return tracks
