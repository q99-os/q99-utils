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
