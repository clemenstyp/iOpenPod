"""
Test script for the fingerprint-based sync engine.

Run: uv run python SyncEngine/test_fingerprint_sync.py
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from SyncEngine import (  # noqa: E402
    is_fpcalc_available,
    is_ffmpeg_available,
    compute_fingerprint,
    read_fingerprint,
    MappingFile,
    needs_transcoding,
)
from SyncEngine.mapping import MappingManager  # noqa: E402
from SyncEngine.integrity import check_integrity, IntegrityReport  # noqa: E402
from SyncEngine.fingerprint_diff_engine import (  # noqa: E402
    FingerprintDiffEngine,
    SyncAction,
)
from SyncEngine.pc_library import PCTrack  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pc_track(
    fp_path: str = "/pc/music/song.mp3",
    title: str = "Bohemian Rhapsody",
    artist: str = "Queen",
    album: str = "A Night at the Opera",
    mtime: float = 1_700_000_000.0,
    size: int = 5_000_000,
    duration_ms: int = 355_000,
) -> PCTrack:
    """Return a minimal PCTrack for testing."""
    return PCTrack(
        path=fp_path,
        relative_path=Path(fp_path).name,
        filename=Path(fp_path).name,
        extension=Path(fp_path).suffix,
        mtime=mtime,
        size=size,
        title=title,
        artist=artist,
        album=album,
        album_artist=artist,
        genre="Rock",
        year=1975,
        track_number=11,
        track_total=12,
        disc_number=1,
        disc_total=1,
        duration_ms=duration_ms,
        bitrate=320,
        sample_rate=44100,
        rating=None,
    )


def _run_compute_diff(
    ipod_tracks: list,
    mapping: MappingFile,
    pc_tracks: list,
    fingerprint: str,
    ipod_path: str,
) -> "SyncPlan":  # type: ignore[name-defined]
    """
    Call FingerprintDiffEngine.compute_diff with all external dependencies
    mocked away so no real files, fpcalc, or GUI are required.
    """
    mock_library = MagicMock()
    mock_library.scan.return_value = pc_tracks

    engine = FingerprintDiffEngine(mock_library, ipod_path)
    # Inject pre-built mapping so the engine doesn't try to load from disk.
    engine.mapping_manager = MagicMock(spec=MappingManager)
    engine.mapping_manager.load.return_value = mapping

    with patch(
        "SyncEngine.fingerprint_diff_engine.is_fpcalc_available", return_value=True
    ), patch(
        "SyncEngine.fingerprint_diff_engine.get_or_compute_fingerprint",
        return_value=fingerprint,
    ):
        plan = engine.compute_diff(list(ipod_tracks))

    return plan


def test_dependencies():
    """Check if required tools are available."""
    print("=== Dependency Check ===")
    print(f"fpcalc (Chromaprint): {'✅ Available' if is_fpcalc_available() else '❌ Not found'}")
    print(f"ffmpeg (Transcoding): {'✅ Available' if is_ffmpeg_available() else '❌ Not found'}")

    if not is_fpcalc_available():
        print("\n⚠️  fpcalc not found!")
        print("   Download from: https://acoustid.org/chromaprint")
        print("   Windows: Extract fpcalc.exe to C:\\Program Files\\fpcalc\\ or add to PATH")
    print()


def test_mapping_file():
    """Test the mapping file CRUD operations."""
    print("=== Mapping File Test ===")

    # Create a test mapping in memory
    mapping = MappingFile()
    print(f"New mapping created: {mapping.track_count} tracks")

    # Add a track
    mapping.add_track(
        fingerprint="AQADtNQyRUkSRZEiJYqSKMmS",
        dbid=0x1234567890ABCDEF,
        source_format="flac",
        ipod_format="alac",
        source_size=45000000,
        source_mtime=1738756200.0,
        was_transcoded=True,
        source_path_hint="D:/Music/Queen/Bohemian Rhapsody.flac",
    )
    print(f"Added track: {mapping.track_count} tracks")

    # Lookup by fingerprint
    track = mapping.get_single("AQADtNQyRUkSRZEiJYqSKMmS")
    if track:
        print(f"Found track: dbid=0x{track.dbid:016X}, format={track.source_format}→{track.ipod_format}")

    # Lookup by dbid
    result = mapping.get_by_dbid(0x1234567890ABCDEF)
    if result:
        fp, track = result
        print(f"Found by dbid: fingerprint={fp[:20]}...")

    # Serialize to dict
    data = mapping.to_dict()
    print(f"Serialized: {len(data['tracks'])} tracks in JSON")

    # Deserialize
    restored = MappingFile.from_dict(data)
    print(f"Restored: {restored.track_count} tracks")
    print()


def test_transcoding_detection():
    """Test format detection for transcoding."""
    print("=== Transcoding Detection ===")

    test_files = [
        "song.mp3",
        "song.m4a",
        "song.flac",
        "song.wav",
        "song.ogg",
        "song.opus",
    ]

    for filename in test_files:
        needs = needs_transcoding(filename)
        print(f"  {filename}: {'Needs transcoding' if needs else 'iPod-native'}")
    print()


def test_fingerprinting(test_file: str | None = None):
    """Test fingerprint computation on a real file."""
    print("=== Fingerprint Test ===")

    if not is_fpcalc_available():
        print("⚠️  Skipping: fpcalc not available")
        return

    if test_file is None:
        print("Usage: Pass a music file path to test fingerprinting")
        print("Example: python test_fingerprint_sync.py D:/Music/song.mp3")
        return

    path = Path(test_file)
    if not path.exists():
        print(f"❌ File not found: {path}")
        return

    print(f"File: {path}")

    # Check for existing fingerprint
    existing = read_fingerprint(path)
    if existing:
        print(f"Existing fingerprint: {existing[:40]}...")
    else:
        print("No existing fingerprint stored")

    # Compute fingerprint
    print("Computing fingerprint...")
    fp = compute_fingerprint(path)
    if fp:
        print(f"Computed: {fp[:40]}...")
        print(f"Length: {len(fp)} chars")
    else:
        print("❌ Failed to compute fingerprint")


# ---------------------------------------------------------------------------
# Duplicate-add prevention tests
# ---------------------------------------------------------------------------


def test_no_duplicate_add_on_resync():
    """
    A track already present in the mapping AND the iPod DB must NOT be
    scheduled for re-addition on a subsequent compute_diff call.

    This is the core idempotency guarantee: syncing the same library twice
    must not copy any file to the iPod a second time.
    """
    print("test_no_duplicate_add_on_resync ... ", end="")

    FINGERPRINT = "AQADtNQyRUkSRZEiJYqSKMmS"
    DBID = 0x1234567890ABCDEF

    pc_track = _make_pc_track()

    # Mapping already records this track from a previous sync.
    mapping = MappingFile()
    mapping.add_track(
        fingerprint=FINGERPRINT,
        dbid=DBID,
        source_format="mp3",
        ipod_format="mp3",
        source_size=pc_track.size,
        source_mtime=pc_track.mtime,
        was_transcoded=False,
        source_path_hint=pc_track.relative_path,
    )

    # iPod DB contains the same track.
    ipod_tracks = [
        {
            "db_id": DBID,
            "Title": pc_track.title,
            "Artist": pc_track.artist,
            "Album": pc_track.album,
            # No 'Location' key → integrity check A skips the file-exists test.
        }
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        plan = _run_compute_diff(
            ipod_tracks=ipod_tracks,
            mapping=mapping,
            pc_tracks=[pc_track],
            fingerprint=FINGERPRINT,
            ipod_path=tmpdir,
        )

    assert len(plan.to_add) == 0, (
        f"Expected 0 adds on re-sync, got {len(plan.to_add)}: "
        f"{[i.description for i in plan.to_add]}"
    )
    assert plan.matched_tracks == 1, (
        f"Expected 1 matched track, got {plan.matched_tracks}"
    )
    print("PASS")


def test_integrity_check_removes_stale_mapping():
    """
    check_integrity must remove mapping entries whose dbid is absent from the
    iTunesDB and report them as stale.  After the check the mapping must
    contain no entry for that fingerprint.
    """
    print("test_integrity_check_removes_stale_mapping ... ", end="")

    FINGERPRINT = "AQADtNQyRUkSRZEiJYqSKMmS"
    STALE_DBID = 0xDEADBEEFDEADBEEF

    mapping = MappingFile()
    mapping.add_track(
        fingerprint=FINGERPRINT,
        dbid=STALE_DBID,
        source_format="mp3",
        ipod_format="mp3",
        source_size=1_000_000,
        source_mtime=1_700_000_000.0,
        was_transcoded=False,
    )

    # iTunesDB is empty → STALE_DBID is not a valid dbid.
    ipod_tracks: list[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        report = check_integrity(
            ipod_path=tmpdir,
            ipod_tracks=ipod_tracks,
            mapping=mapping,
            delete_orphans=False,
        )

    assert len(report.stale_mappings) == 1, (
        f"Expected 1 stale mapping entry, got {len(report.stale_mappings)}"
    )
    assert report.stale_mappings[0] == (FINGERPRINT, STALE_DBID), (
        f"Unexpected stale entry: {report.stale_mappings[0]}"
    )
    # The entry must have been removed from the mapping object in-place.
    assert mapping.get_entries(FINGERPRINT) == [], (
        "Stale mapping entry was not removed from the MappingFile"
    )
    print("PASS")


def test_stale_mapping_causes_single_readd():
    """
    When the mapping has a stale dbid (track removed externally from the DB),
    the integrity check cleans the mapping, and compute_diff schedules exactly
    ONE re-add — not zero, not two.
    """
    print("test_stale_mapping_causes_single_readd ... ", end="")

    FINGERPRINT = "AQADtNQyRUkSRZEiJYqSKMmS"
    STALE_DBID = 0xAAAABBBBCCCCDDDD

    pc_track = _make_pc_track()

    # Mapping has the stale entry.
    mapping = MappingFile()
    mapping.add_track(
        fingerprint=FINGERPRINT,
        dbid=STALE_DBID,
        source_format="mp3",
        ipod_format="mp3",
        source_size=pc_track.size,
        source_mtime=pc_track.mtime,
        was_transcoded=False,
    )

    # The track is ABSENT from the iPod DB (stale scenario).
    ipod_tracks: list[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        plan = _run_compute_diff(
            ipod_tracks=ipod_tracks,
            mapping=mapping,
            pc_tracks=[pc_track],
            fingerprint=FINGERPRINT,
            ipod_path=tmpdir,
        )

    assert len(plan.to_add) == 1, (
        f"Expected exactly 1 re-add for stale mapping, got {len(plan.to_add)}: "
        f"{[i.description for i in plan.to_add]}"
    )
    assert plan.matched_tracks == 0, (
        f"Expected 0 matched tracks (stale), got {plan.matched_tracks}"
    )
    print("PASS")


def test_pc_true_duplicate_not_added_twice():
    """
    Two PC files with identical fingerprint and identical album (true duplicates)
    must result in only ONE add, and the pair must be reported as a duplicate.
    """
    print("test_pc_true_duplicate_not_added_twice ... ", end="")

    FINGERPRINT = "AQADtNQyRUkSRZEiJYqSKMmS"

    # Both tracks have the same fingerprint AND the same album.
    track_a = _make_pc_track(fp_path="/pc/music/copy1.mp3")
    track_b = _make_pc_track(fp_path="/pc/music/copy2.mp3")

    # Empty mapping — neither track has been synced before.
    mapping = MappingFile()

    # iPod DB is empty.
    ipod_tracks: list[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        plan = _run_compute_diff(
            ipod_tracks=ipod_tracks,
            mapping=mapping,
            pc_tracks=[track_a, track_b],
            fingerprint=FINGERPRINT,
            ipod_path=tmpdir,
        )

    # Only one copy should be scheduled for addition.
    assert len(plan.to_add) == 1, (
        f"Expected 1 add for true duplicate pair, got {len(plan.to_add)}: "
        f"{[i.description for i in plan.to_add]}"
    )
    # The duplicate pair must be reported.
    assert len(plan.duplicates) == 1, (
        f"Expected 1 duplicate group, got {len(plan.duplicates)}"
    )
    print("PASS")


def test_no_add_after_simulated_executor_backpatch():
    """
    Simulates what happens after a full first-sync cycle:
      1. compute_diff returns a plan with one ADD.
      2. The executor copies the file and adds a mapping entry (dbid backpatch).
      3. compute_diff is called again with the updated mapping — must return 0 ADDs.

    This validates the end-to-end duplicate-prevention across both compute_diff
    and the mapping-backpatch that the executor performs.
    """
    print("test_no_add_after_simulated_executor_backpatch ... ", end="")

    FINGERPRINT = "AQADtNQyRUkSRZEiJYqSKMmS"
    ASSIGNED_DBID = 0xFEEDFACECAFEBEEF

    pc_track = _make_pc_track()

    # ── First sync: mapping is empty ──────────────────────────────────────
    mapping = MappingFile()

    with tempfile.TemporaryDirectory() as tmpdir:
        plan1 = _run_compute_diff(
            ipod_tracks=[],
            mapping=mapping,
            pc_tracks=[pc_track],
            fingerprint=FINGERPRINT,
            ipod_path=tmpdir,
        )

        assert len(plan1.to_add) == 1, (
            f"Expected 1 add on first sync, got {len(plan1.to_add)}"
        )

        # ── Simulate executor backpatch ───────────────────────────────────
        # The executor copies the file, receives ASSIGNED_DBID from the writer,
        # and calls mapping.add_track().
        mapping.add_track(
            fingerprint=FINGERPRINT,
            dbid=ASSIGNED_DBID,
            source_format="mp3",
            ipod_format="mp3",
            source_size=pc_track.size,
            source_mtime=pc_track.mtime,
            was_transcoded=False,
            source_path_hint=pc_track.relative_path,
        )

        # ── Second sync: mapping now has the entry ────────────────────────
        ipod_tracks_after = [
            {
                "db_id": ASSIGNED_DBID,
                "Title": pc_track.title,
                "Artist": pc_track.artist,
                "Album": pc_track.album,
            }
        ]

        plan2 = _run_compute_diff(
            ipod_tracks=ipod_tracks_after,
            mapping=mapping,
            pc_tracks=[pc_track],
            fingerprint=FINGERPRINT,
            ipod_path=tmpdir,
        )

    assert len(plan2.to_add) == 0, (
        f"Expected 0 adds on second sync, got {len(plan2.to_add)}: "
        f"{[i.description for i in plan2.to_add]}"
    )
    assert plan2.matched_tracks == 1, (
        f"Expected 1 matched track on second sync, got {plan2.matched_tracks}"
    )
    print("PASS")


if __name__ == "__main__":
    test_dependencies()
    test_mapping_file()
    test_transcoding_detection()

    # Duplicate-add prevention tests (no fpcalc required)
    print("\n=== Duplicate-Add Prevention Tests ===\n")
    test_no_duplicate_add_on_resync()
    test_integrity_check_removes_stale_mapping()
    test_stale_mapping_causes_single_readd()
    test_pc_true_duplicate_not_added_twice()
    test_no_add_after_simulated_executor_backpatch()
    print("\n✅ All duplicate-add tests passed.\n")

    # If a file path was provided, test fingerprinting
    if len(sys.argv) > 1:
        test_fingerprinting(sys.argv[1])
    else:
        test_fingerprinting()
