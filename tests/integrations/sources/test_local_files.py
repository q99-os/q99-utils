"""Incremental discovery over the local filesystem.

What matters is which files get skipped: already indexed, older than the last
ingest, or too big.
"""

from __future__ import annotations

import os

import pytest

from q99_utils.integrations import IntegrationConfig, IntegrationContext
from q99_utils.integrations.sources import LocalFilesIntegration
from q99_utils.models import SourceEnum

from tests.integrations.fakes import FakeFileStore, FakeUserManagerSDK


def _integration(tmp_path, store=None, credential_id="cred-1", max_size_mb=200):
    integration = LocalFilesIntegration(
        source=SourceEnum.local_files,
        um_sdk=FakeUserManagerSDK(source=SourceEnum.local_files, root_folders=[str(tmp_path)]),
        context=IntegrationContext(
            config=IntegrationConfig(upload_max_size_mb=max_size_mb),
            file_store=store,
        ),
    )
    integration.credential_id = credential_id
    return integration


def _write(path, content=b"x", mtime=None):
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return str(path)


async def test_discovers_files_under_the_configured_root(tmp_path):
    _write(tmp_path / "a.txt", mtime=1000)
    _write(tmp_path / "b.txt", mtime=1000)

    files, cursors = await _integration(tmp_path, FakeFileStore()).files_discovery()

    assert sorted(f.name for f in files) == ["a.txt", "b.txt"]
    assert cursors is None  # local files carry no incremental cursor


async def test_already_ingested_references_are_skipped(tmp_path):
    kept = _write(tmp_path / "new.txt", mtime=1000)
    seen = _write(tmp_path / "old.txt", mtime=1000)

    store = FakeFileStore(references=[seen])
    files, _ = await _integration(tmp_path, store).files_discovery()

    assert [f.reference for f in files] == [os.path.normpath(kept)]


async def test_files_not_newer_than_the_last_ingest_are_skipped(tmp_path):
    _write(tmp_path / "stale.txt", mtime=500)
    fresh = _write(tmp_path / "fresh.txt", mtime=1500)

    store = FakeFileStore(references=["/somewhere/else"], latest=1000)
    files, _ = await _integration(tmp_path, store).files_discovery()

    assert [f.reference for f in files] == [os.path.normpath(fresh)]


async def test_boundary_mtime_is_treated_as_already_seen(tmp_path):
    # The comparison is `<=`, so a file stamped exactly at the cursor is skipped.
    _write(tmp_path / "edge.txt", mtime=1000)

    store = FakeFileStore(references=["/x"], latest=1000)
    files, _ = await _integration(tmp_path, store).files_discovery()

    assert files == []


async def test_oversized_files_are_skipped(tmp_path):
    _write(tmp_path / "big.bin", content=b"0" * (2 * 1024 * 1024), mtime=1000)
    small = _write(tmp_path / "small.txt", content=b"0", mtime=1000)

    integration = _integration(tmp_path, FakeFileStore(), max_size_mb=1)
    files, _ = await integration.files_discovery()

    assert [f.reference for f in files] == [os.path.normpath(small)]


async def test_discovery_walks_subdirectories(tmp_path):
    nested = tmp_path / "sub" / "deep"
    nested.mkdir(parents=True)
    _write(nested / "buried.txt", mtime=1000)

    files, _ = await _integration(tmp_path, FakeFileStore()).files_discovery()

    assert [f.name for f in files] == ["buried.txt"]


async def test_reference_patterns_are_scoped_to_the_root(tmp_path):
    _write(tmp_path / "a.txt", mtime=1000)
    store = FakeFileStore()

    await _integration(tmp_path, store).files_discovery()

    patterns = store.patterns_for("known_references")[0]
    assert len(patterns) == 1
    # Trailing separator + wildcard: everything under the root, nothing beside it.
    assert patterns[0].endswith(f"{os.sep}%")
    assert patterns[0].startswith(str(tmp_path))


async def test_discovery_requires_a_credential_id(tmp_path):
    # files_discovery() resolves credentials before anything else, so a missing
    # credential_id fails fast rather than silently scanning with no scoping.
    _write(tmp_path / "a.txt", mtime=1000)

    integration = _integration(tmp_path, FakeFileStore(), credential_id=None)

    with pytest.raises(ValueError, match="credential_id"):
        await integration.files_discovery()


async def test_discovery_works_without_a_file_store(tmp_path):
    # A host that wires no store still gets a full (non-incremental) scan
    # rather than a crash.
    _write(tmp_path / "a.txt", mtime=1000)

    files, _ = await _integration(tmp_path, store=None).files_discovery()

    assert len(files) == 1


async def test_discovered_metadata_is_populated(tmp_path):
    path = _write(tmp_path / "doc.txt", content=b"hello", mtime=1234)

    files, _ = await _integration(tmp_path, FakeFileStore()).files_discovery()

    (found,) = files
    assert found.name == "doc.txt"
    assert found.reference == os.path.normpath(path)
    assert found.file_size == 5
    assert found.source_modified_at == 1234
    assert found.mime_type == "text/plain"
