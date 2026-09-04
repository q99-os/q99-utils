"""A dead token must reach translate_refresh_error, not get lost as a warning.

Two spots used to swallow ``RefreshError`` under a broad ``except Exception``:
the incremental Changes-API loop, and ``list_tree``'s folder resolution. Both
are exercised here against the smallest possible surface — no real Google
client, no full integration context, just the one method that used to hide it.
"""

import pytest
from google.auth.exceptions import RefreshError

from q99_utils.integrations.sources.google_drive import GoogleDriveIntegration


def _bare_instance():
    """A GoogleDriveIntegration with no context — enough for methods that
    only touch their explicit arguments, not self.*."""
    return object.__new__(GoogleDriveIntegration)


class _RaisingChangesList:
    def execute(self):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")


class _ChangesService:
    def changes(self):
        return self

    def list(self, **kwargs):
        return _RaisingChangesList()


def test_discover_via_changes_lets_a_dead_token_through():
    integration = _bare_instance()

    with pytest.raises(RefreshError):
        integration._discover_via_changes(
            _ChangesService(),
            page_token="some-token",
            root_folder_to_selector={},
            d_files=[],
            ingested_refs={},
            ingested_hashes=set(),
            max_file_size_mb=25,
        )


class _RaisingFilesList:
    def execute(self):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")


class _FilesService:
    def files(self):
        return self

    def list(self, **kwargs):
        return _RaisingFilesList()


def test_list_folder_children_lets_a_dead_token_through():
    integration = _bare_instance()

    with pytest.raises(RefreshError):
        integration._list_folder_children(_FilesService(), "some-folder-id")
