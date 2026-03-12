"""
Unit tests for TagMappingService.

Run: uv run python SyncEngine/test_tag_mapping.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from SyncEngine.tag_mapping import TagMappingService  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal PCTrack stub — only the fields we need for testing
# ---------------------------------------------------------------------------

class _PCTrack:
    """Minimal stub that mimics the PCTrack interface."""

    def __init__(self, **kwargs):
        self.title = kwargs.get("title", "")
        self.artist = kwargs.get("artist", "")
        self.album = kwargs.get("album", "")
        self.album_artist = kwargs.get("album_artist", None)
        self.genre = kwargs.get("genre", None)
        self.track_number = kwargs.get("track_number", None)
        self.composer = kwargs.get("composer", None)
        self.comment = kwargs.get("comment", None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_mapping_returns_same_object():
    """Empty mapping must return the original object unchanged."""
    print("test_empty_mapping_returns_same_object ... ", end="")
    track = _PCTrack(title="Song", artist="Artist", album_artist="Album Artist")
    result = TagMappingService.apply(track, {})
    assert result is track, "Expected the same object for empty mapping"
    print("PASS")


def test_single_field_substitution():
    """artist → %album_artist replaces artist with album_artist value."""
    print("test_single_field_substitution ... ", end="")
    track = _PCTrack(
        title="Song",
        artist="Solo Artist",
        album_artist="Various Artists",
    )
    mapping = {"artist": "%album_artist"}
    result = TagMappingService.apply(track, mapping)

    assert result is not track, "Expected a copy, not the original"
    assert result.artist == "Various Artists", (
        f"Expected 'Various Artists', got {result.artist!r}"
    )
    # Unmapped fields must be unchanged
    assert result.title == "Song"
    assert result.album_artist == "Various Artists"
    print("PASS")


def test_composite_template():
    """%tracknumber - %title produces a formatted string."""
    print("test_composite_template ... ", end="")
    track = _PCTrack(title="Bohemian Rhapsody", track_number=1)
    mapping = {"title": "%track_number - %title"}
    result = TagMappingService.apply(track, mapping)

    assert result.title == "1 - Bohemian Rhapsody", (
        f"Expected '1 - Bohemian Rhapsody', got {result.title!r}"
    )
    print("PASS")


def test_missing_source_field_skips_override():
    """If the referenced source field does not exist, the target is not changed."""
    print("test_missing_source_field_skips_override ... ", end="")
    track = _PCTrack(artist="My Artist")
    mapping = {"artist": "%nonexistent_field"}
    result = TagMappingService.apply(track, mapping)

    # artist must remain unchanged because source field does not exist
    assert result.artist == "My Artist", (
        f"Expected 'My Artist' (unchanged), got {result.artist!r}"
    )
    print("PASS")


def test_none_source_value_skips_override():
    """A bare %field template that resolves to None must not override the target."""
    print("test_none_source_value_skips_override ... ", end="")
    track = _PCTrack(artist="Known Artist", album_artist=None)
    mapping = {"artist": "%album_artist"}
    result = TagMappingService.apply(track, mapping)

    # album_artist is None → artist should remain unchanged
    assert result.artist == "Known Artist", (
        f"Expected 'Known Artist' (unchanged), got {result.artist!r}"
    )
    print("PASS")


def test_composite_with_none_field_uses_empty_string():
    """In a composite template a None field becomes an empty string."""
    print("test_composite_with_none_field_uses_empty_string ... ", end="")
    track = _PCTrack(title="Track", album_artist=None)
    mapping = {"title": "%album_artist - %title"}
    result = TagMappingService.apply(track, mapping)

    # album_artist is None → substituted with ""
    assert result.title == " - Track", (
        f"Expected ' - Track', got {result.title!r}"
    )
    print("PASS")


def test_original_fields_unmodified():
    """Non-mapped fields on the source must not be altered."""
    print("test_original_fields_unmodified ... ", end="")
    track = _PCTrack(
        title="Original Title",
        artist="Original Artist",
        album="Original Album",
        genre="Rock",
    )
    mapping = {"artist": "%album_artist"}  # album_artist is None → no override
    result = TagMappingService.apply(track, mapping)

    assert result.title == "Original Title"
    assert result.album == "Original Album"
    assert result.genre == "Rock"
    # artist unchanged because album_artist was None
    assert result.artist == "Original Artist"
    print("PASS")


def test_multiple_rules():
    """Multiple mapping rules are all applied to the same copy."""
    print("test_multiple_rules ... ", end="")
    track = _PCTrack(
        title="Song",
        artist="Solo",
        album_artist="Band",
        genre="Pop",
        composer="Songwriter",
    )
    mapping = {
        "artist": "%album_artist",
        "comment": "%composer",
    }
    result = TagMappingService.apply(track, mapping)

    assert result.artist == "Band"
    assert result.comment == "Songwriter"
    assert result.title == "Song"  # untouched
    print("PASS")


def test_unknown_target_field_is_skipped():
    """An unknown target field logs a warning and does not raise."""
    print("test_unknown_target_field_is_skipped ... ", end="")
    track = _PCTrack(artist="Artist", album_artist="Album Artist")
    mapping = {"totally_unknown_field": "%album_artist"}
    # Must not raise
    result = TagMappingService.apply(track, mapping)
    assert result is not track  # still returns a copy
    assert not hasattr(result, "totally_unknown_field")
    print("PASS")


def test_compute_hash_empty_mapping():
    """Empty mapping must return empty string."""
    print("test_compute_hash_empty_mapping ... ", end="")
    assert TagMappingService.compute_hash({}) == ""
    assert TagMappingService.compute_hash(None) == ""
    print("PASS")


def test_compute_hash_is_stable():
    """Same mapping must always produce the same hash."""
    print("test_compute_hash_is_stable ... ", end="")
    mapping = {"artist": "%album_artist", "title": "%track_number - %title"}
    h1 = TagMappingService.compute_hash(mapping)
    h2 = TagMappingService.compute_hash(mapping)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest
    print("PASS")


def test_compute_hash_order_independent():
    """Insertion order must not affect the hash."""
    print("test_compute_hash_order_independent ... ", end="")
    m1 = {"artist": "%album_artist", "title": "%track_number - %title"}
    m2 = {"title": "%track_number - %title", "artist": "%album_artist"}
    assert TagMappingService.compute_hash(m1) == TagMappingService.compute_hash(m2)
    print("PASS")


def test_compute_hash_different_mappings():
    """Different mappings must produce different hashes."""
    print("test_compute_hash_different_mappings ... ", end="")
    m1 = {"artist": "%album_artist"}
    m2 = {"artist": "%composer"}
    assert TagMappingService.compute_hash(m1) != TagMappingService.compute_hash(m2)
    print("PASS")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== TagMappingService Tests ===\n")
    test_empty_mapping_returns_same_object()
    test_single_field_substitution()
    test_composite_template()
    test_missing_source_field_skips_override()
    test_none_source_value_skips_override()
    test_composite_with_none_field_uses_empty_string()
    test_original_fields_unmodified()
    test_multiple_rules()
    test_unknown_target_field_is_skipped()
    test_compute_hash_empty_mapping()
    test_compute_hash_is_stable()
    test_compute_hash_order_independent()
    test_compute_hash_different_mappings()
    print("\n✅ All tests passed.")
