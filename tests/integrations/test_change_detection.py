"""The change-classification policy shared by SharePoint and Google Drive.

The last two cases pin the one term the two providers disagree on, which was
invisible while the logic was copy-pasted into each of them.
"""

from __future__ import annotations

from q99_utils.integrations.core.change_detection import classify_change
from q99_utils.integrations.discovery import ChangeKind


def _classify(**overrides):
    args = dict(
        stored_modified_at=1000,
        stored_hash="hash-a",
        stored_perms=["email:ana@q99.com"],
        content_hash="hash-a",
        source_modified_at=1000,
        source_perms=["email:ana@q99.com"],
    )
    args.update(overrides)
    return classify_change(**args)


def test_nothing_changed():
    assert _classify() is None


def test_different_hash_is_an_update():
    assert _classify(content_hash="hash-b") == ChangeKind.UPDATED


def test_same_hash_different_permissions():
    assert _classify(source_perms=["email:bea@q99.com"]) == ChangeKind.PERMISSIONS_CHANGED


def test_content_wins_when_both_changed():
    # A re-ingest rewrites the permissions anyway, so UPDATED subsumes it.
    result = _classify(content_hash="hash-b", source_perms=["email:bea@q99.com"])
    assert result == ChangeKind.UPDATED


def test_hashes_beat_timestamps():
    # Equal hashes settle it even when the provider bumped the mtime.
    assert _classify(source_modified_at=9999) is None


def test_newer_timestamp_is_an_update_when_hashes_are_missing():
    result = _classify(content_hash=None, stored_hash=None, source_modified_at=2000)
    assert result == ChangeKind.UPDATED


def test_older_timestamp_is_not_an_update():
    result = _classify(content_hash=None, stored_hash=None, source_modified_at=500)
    assert result is None


def test_equal_timestamp_is_not_an_update():
    result = _classify(content_hash=None, stored_hash=None, source_modified_at=1000)
    assert result is None


def test_missing_timestamps_never_report_an_update():
    result = _classify(
        content_hash=None, stored_hash=None, source_modified_at=None, stored_modified_at=None
    )
    assert result is None


def test_empty_stored_permissions_count_as_a_permission_change():
    assert _classify(stored_perms=None) == ChangeKind.PERMISSIONS_CHANGED
    assert _classify(stored_perms=[]) == ChangeKind.PERMISSIONS_CHANGED


def test_permission_order_is_not_a_change():
    result = _classify(
        stored_perms=["b", "a"],
        source_perms=["a", "b"],
        content_hash=None,
        stored_hash=None,
    )
    assert result is None


# The SharePoint / Google Drive divergence.

def test_perm_change_wins_suppresses_the_mtime_comparison():
    # Provider bumped mtime *because of* the ACL edit — not new content.
    result = _classify(
        content_hash=None,
        stored_hash=None,
        source_modified_at=2000,
        source_perms=["email:bea@q99.com"],
        perm_change_wins=True,
    )
    assert result == ChangeKind.PERMISSIONS_CHANGED


def test_without_perm_change_wins_the_same_inputs_are_an_update():
    result = _classify(
        content_hash=None,
        stored_hash=None,
        source_modified_at=2000,
        source_perms=["email:bea@q99.com"],
        perm_change_wins=False,
    )
    assert result == ChangeKind.UPDATED


# ── identify_change: the same file seen under a different reference ──────────

from q99_utils.integrations.core.change_detection import identify_change, references_by_file_id  # noqa: E402


def test_references_by_file_id_groups_by_last_segment():
    grouped = references_by_file_id(["x", "Docs/y", "Docs/Sub/y", "Archive/x"])
    assert grouped == {"x": ["x", "Archive/x"], "y": ["Docs/y", "Docs/Sub/y"]}


def _identify(reference, file_id, ingested_refs, hashes=(), **overrides):
    args = dict(
        reference=reference,
        file_id=file_id,
        ingested_refs=ingested_refs,
        refs_by_file_id=references_by_file_id(ingested_refs),
        ingested_hashes=set(hashes),
        content_hash="hash-a",
        source_modified_at=1000,
        source_perms=["email:ana@q99.com"],
    )
    args.update(overrides)
    return identify_change(**args)


STORED = (1000, "hash-a", ["email:ana@q99.com"])


def test_unknown_file_is_added():
    found = _identify("QTEST/x", "x", {})
    assert found.change_kind == ChangeKind.ADDED
    assert found.previous_reference is None
    assert found.stale_references == []


def test_known_reference_without_changes_is_skipped():
    found = _identify("QTEST/x", "x", {"QTEST/x": STORED})
    assert found.change_kind is None
    assert found.stale_references == []


def test_known_reference_marks_other_rows_of_the_same_file_stale():
    found = _identify("QTEST2/x", "x", {"QTEST/x": STORED, "QTEST2/x": STORED})
    assert found.change_kind is None
    assert found.previous_reference is None
    assert found.stale_references == ["QTEST/x"]


def test_same_file_under_a_new_reference_is_moved():
    found = _identify("QTEST2/x", "x", {"QTEST/x": STORED})
    assert found.change_kind == ChangeKind.MOVED
    assert found.previous_reference == "QTEST/x"
    assert found.stale_references == []


def test_moved_file_with_new_content_is_updated_not_moved():
    found = _identify("QTEST2/x", "x", {"QTEST/x": STORED}, content_hash="hash-b")
    assert found.change_kind == ChangeKind.UPDATED
    assert found.previous_reference == "QTEST/x"


def test_moved_google_doc_without_hash_is_moved_when_unmodified():
    stored = (1000, None, ["email:ana@q99.com"])
    found = _identify("QTEST2/x", "x", {"QTEST/x": stored}, content_hash=None, source_modified_at=1000)
    assert found.change_kind == ChangeKind.MOVED


def test_moved_file_with_several_old_rows_renames_one_and_marks_the_rest_stale():
    found = _identify("New/x", "x", {"Old/x": STORED, "Older/x": STORED})
    assert found.change_kind == ChangeKind.MOVED
    assert found.previous_reference == "Old/x"
    assert found.stale_references == ["Older/x"]


def test_new_file_id_with_a_known_hash_is_a_copy_and_skipped():
    found = _identify("QTEST/y", "y", {"QTEST/x": STORED}, hashes={"hash-a"})
    assert found.change_kind is None
    assert found.previous_reference is None
