"""In-memory stand-ins for the ports, so tests need no database or app."""

from q99_utils.models import SourceEnum


class FakeDriver:
    """Stand-in satisfying the SqlDriver protocol."""

    def __init__(self):
        self.closed = False

    async def query(self, sql, *args, **kwargs):
        return [{"ok": 1}]

    async def get_schema(self, tables=None, exclude_empty=False):
        return f"schema(tables={tables}, exclude_empty={exclude_empty})"

    async def close(self):
        self.closed = True


class FakeDriverFactory:
    """Records the backend each connection was requested for."""

    def __init__(self):
        self.calls = []

    async def create(self, backend, credentials):
        self.calls.append((backend, credentials))
        return FakeDriver()

    @property
    def backends(self):
        return [backend for backend, _ in self.calls]


class FakeFileStore:
    """In-memory FileReferenceStore recording the calls it receives."""

    def __init__(self, references=None, latest=0, indexed=True, hashes=None, files=None):
        self._references = set(references or [])
        self._latest = latest
        self._indexed = indexed
        self._hashes = set(hashes or [])
        self._files = dict(files or {})
        self.calls = []

    def patterns_for(self, method):
        """Patterns passed to *method*, in call order."""
        return [patterns for name, _, patterns in self.calls if name == method]

    async def known_references(self, *, credential_id, source=None, reference_patterns=None):
        self.calls.append(("known_references", source, reference_patterns))
        return set(self._references)

    async def indexed_files(self, *, credential_id, source=None, reference_patterns=None):
        self.calls.append(("indexed_files", source, reference_patterns))
        return dict(self._files)

    async def known_content_hashes(self, *, credential_id):
        self.calls.append(("known_content_hashes", None, None))
        return set(self._hashes)

    async def latest_source_modified_at(self, *, credential_id, source=None, reference_patterns=None):
        self.calls.append(("latest_source_modified_at", source, reference_patterns))
        return self._latest

    async def latest_ingested_at(self, *, credential_id, reference_patterns=None):
        self.calls.append(("latest_ingested_at", None, reference_patterns))
        return self._latest

    async def has_indexed_files(self, *, credential_id, source=None, reference_patterns=None):
        self.calls.append(("has_indexed_files", source, reference_patterns))
        return self._indexed


class FakeUserManagerSDK:
    """Only the methods the base class touches."""

    def __init__(self, credential=None, **overrides):
        self.credential = {"id": "cred-1", "source": SourceEnum.postgres, **(credential or {}), **overrides}
        self.sync_state_calls = []

    async def get_credential(self, credential_id):
        return dict(self.credential)

    async def update_sync_state(self, credential_id, sync_cursors, last_sync):
        self.sync_state_calls.append((credential_id, sync_cursors, last_sync))
