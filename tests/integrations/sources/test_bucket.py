"""Object-storage integration.

What decides where a request goes: provider resolution, which credentials
travel with it, and how discovery is scoped to a prefix.
"""

from __future__ import annotations

import pytest

from q99_utils.integrations import IntegrationConfig, IntegrationContext, ManagedBucket
from q99_utils.integrations.sources import BucketIntegration
from q99_utils.enums import SourceEnum

from tests.integrations.fakes import FakeFileStore, FakeUserManagerSDK


class FakeObject:
    def __init__(self, path, file_size=10, source_modified_at=100, content_hash="h", mime_type=None):
        self.path = path
        self.file_size = file_size
        self.source_modified_at = source_modified_at
        self.content_hash = content_hash
        self.mime_type = mime_type


class FakeStorageService:
    def __init__(self, objects=None, credentials=None):
        self.objects = objects or []
        self.credentials = credentials or {}
        self.discovery_calls = []

    def download_bites_file(self, container, key):
        import io

        self.last_download = (container, key)
        return io.BytesIO(b"payload")

    async def files_discovery(self, container, ingested_paths, latest_modified_at, max_file_size_mb=None, prefix=""):
        self.discovery_calls.append(
            {
                "container": container,
                "ingested_paths": set(ingested_paths),
                "latest_modified_at": latest_modified_at,
                "max_file_size_mb": max_file_size_mb,
                "prefix": prefix,
            }
        )
        return list(self.objects)

    def list_tree(self, container, prefixes, depth):
        return [], False


class FakeStorageFactory:
    def __init__(self, objects=None):
        self.objects = objects or []
        self.calls = []
        self.services = []

    def get(self, provider, **credentials):
        self.calls.append((provider, credentials))
        service = FakeStorageService(self.objects, credentials)
        self.services.append(service)
        return service


class FakeManagedBucketProvider:
    def __init__(self, bucket=None):
        self.bucket = bucket

    async def managed_bucket(self):
        return self.bucket


def _integration(
    source=SourceEnum.s3,
    store=None,
    factory=None,
    managed=None,
    credential_id="cred-1",
    sdk=None,
    **config_kwargs,
):
    config = IntegrationConfig(
        cloud_provider="aws",
        object_storage_name="default-bucket",
        managed_bucket_source="quantos_bucket",
        **config_kwargs,
    )
    integration = BucketIntegration(
        source=source,
        um_sdk=sdk or FakeUserManagerSDK(source=SourceEnum.s3),
        context=IntegrationContext(
            config=config,
            file_store=store,
            storage_factory=factory or FakeStorageFactory(),
            managed_bucket=managed,
        ),
    )
    integration.credential_id = credential_id
    return integration


# ── provider resolution ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "source,expected_provider",
    [(SourceEnum.s3, "aws"), (SourceEnum.blob, "azure"), (SourceEnum.gcs, "gcp")],
)
def test_provider_is_derived_from_the_source(source, expected_provider):
    assert _integration(source=source).cloud_provider == expected_provider


def test_unknown_source_falls_back_to_the_deployment_default():
    # The managed-bucket source isn't one of s3/blob/gcs.
    assert _integration(source="quantos_bucket").cloud_provider == "aws"


@pytest.mark.parametrize(
    "reference,expected",
    [
        ("s3://bucket/key.txt", ("s3", "bucket", "key.txt")),
        ("gcs://b/nested/key.txt", ("gcs", "b", "nested/key.txt")),
        ("plain/path.txt", (None, None, "plain/path.txt")),
        ("weird://nokey", (None, None, "weird://nokey")),
    ],
)
def test_reference_splitting(reference, expected):
    assert BucketIntegration._split_reference(reference) == expected


def test_prefix_normalisation_strips_slashes_and_space():
    assert BucketIntegration._normalize_prefix("  /docs/reports/  ") == "docs/reports"
    assert BucketIntegration._normalize_prefix("") == ""


# ── download ─────────────────────────────────────────────────────────


async def test_download_uses_the_provider_from_the_uri_scheme():
    factory = FakeStorageFactory()
    integration = _integration(factory=factory)

    await integration.get_files_from_path("gcs://other-bucket/a/b.txt")

    provider, _ = factory.calls[-1]
    assert provider == "gcp"


async def test_credentials_are_withheld_when_the_provider_differs():
    # Our stored creds belong to our own provider; sending them elsewhere
    # would authenticate against the wrong cloud.
    factory = FakeStorageFactory()
    integration = _integration(factory=factory, sdk=FakeUserManagerSDK(source=SourceEnum.s3, api_key="k", client_secret="s"))

    await integration.get_files_from_path("gcs://other/a.txt")

    provider, credentials = factory.calls[-1]
    assert provider == "gcp"
    assert credentials == {}


async def test_credentials_travel_when_the_provider_matches():
    factory = FakeStorageFactory()
    integration = _integration(factory=factory, sdk=FakeUserManagerSDK(source=SourceEnum.s3, api_key="key", client_secret="secret"))

    await integration.get_files_from_path("s3://mine/a.txt")

    provider, credentials = factory.calls[-1]
    assert provider == "aws"
    assert credentials == {"aws_key": "key", "aws_secret": "secret"}


async def test_download_failure_returns_none_instead_of_raising():
    class ExplodingFactory(FakeStorageFactory):
        def get(self, provider, **credentials):
            service = FakeStorageService()
            service.download_bites_file = lambda container, key: (_ for _ in ()).throw(OSError("boom"))
            return service

    integration = _integration(factory=ExplodingFactory())
    assert await integration.get_files_from_path("s3://b/k.txt") is None


async def test_missing_storage_factory_fails_loudly():
    integration = BucketIntegration(
        source=SourceEnum.s3,
        um_sdk=FakeUserManagerSDK(source=SourceEnum.s3),
        context=IntegrationContext(),
    )
    integration.credential_id = "cred-1"

    with pytest.raises(RuntimeError, match="storage_factory"):
        await integration.get_files_from_path("s3://b/k.txt")


# ── discovery ────────────────────────────────────────────────────────


async def test_discovery_maps_provider_objects_to_discovered_files():
    factory = FakeStorageFactory(objects=[FakeObject("docs/report.pdf", file_size=42)])
    integration = _integration(factory=factory, store=FakeFileStore())

    files, cursors = await integration.files_discovery()

    (found,) = files
    assert found.name == "report.pdf"
    assert found.reference == "docs/report.pdf"
    assert found.file_size == 42
    assert cursors is None


async def test_discovery_passes_known_references_and_watermark_to_the_provider():
    factory = FakeStorageFactory()
    store = FakeFileStore(references=["docs/seen.pdf"], latest=555)
    integration = _integration(factory=factory, store=store)

    await integration.files_discovery()

    call = factory.services[-1].discovery_calls[0]
    assert call["ingested_paths"] == {"docs/seen.pdf"}
    assert call["latest_modified_at"] == 555


async def test_watermark_is_scoped_to_the_prefix_and_its_children():
    store = FakeFileStore()
    integration = _integration(
        store=store, sdk=FakeUserManagerSDK(source=SourceEnum.s3, root_folders=["/docs/"])
    )

    await integration.files_discovery()

    patterns = store.patterns_for("latest_source_modified_at")[0]
    # The prefix itself plus everything below it — a file stored exactly at the
    # prefix would otherwise be missed.
    assert patterns == ["docs", "docs/%"]


async def test_whole_bucket_scan_uses_no_reference_patterns():
    store = FakeFileStore()
    integration = _integration(store=store, sdk=FakeUserManagerSDK(source=SourceEnum.s3, root_folders=[]))

    await integration.files_discovery()

    patterns = store.patterns_for("latest_source_modified_at")[0]
    assert patterns is None


async def test_provider_without_discovery_support_is_skipped():
    class UnsupportedFactory(FakeStorageFactory):
        def get(self, provider, **credentials):
            service = FakeStorageService()

            async def _unsupported(*args, **kwargs):
                raise NotImplementedError

            service.files_discovery = _unsupported
            return service

    integration = _integration(factory=UnsupportedFactory(), store=FakeFileStore())
    files, _ = await integration.files_discovery()
    assert files == []


async def test_discovery_works_without_a_file_store():
    factory = FakeStorageFactory(objects=[FakeObject("a.txt")])
    integration = _integration(factory=factory, store=None)

    files, _ = await integration.files_discovery()

    assert len(files) == 1
    assert factory.services[-1].discovery_calls[0]["ingested_paths"] == set()


# ── managed bucket ───────────────────────────────────────────────────


async def test_managed_bucket_credential_overrides_defaults():
    managed = FakeManagedBucketProvider(
        ManagedBucket(cloud_provider="gcp", bucket_name="platform-bucket", storage_creds={"service_account_json": "{}"})
    )
    factory = FakeStorageFactory()
    integration = _integration(source="quantos_bucket", factory=factory, managed=managed)

    await integration._load_external_config()

    assert integration.cloud_provider == "gcp"
    assert integration.bucket_name == "platform-bucket"
    assert integration._external_creds == {"service_account_json": "{}"}


async def test_missing_managed_bucket_leaves_deployment_defaults():
    integration = _integration(
        source="quantos_bucket", managed=FakeManagedBucketProvider(None)
    )

    await integration._load_external_config()

    assert integration.cloud_provider == "aws"
    assert integration.bucket_name == "default-bucket"


async def test_external_config_is_loaded_once():
    calls = []

    class CountingProvider(FakeManagedBucketProvider):
        async def managed_bucket(self):
            calls.append(1)
            return None

    integration = _integration(source="quantos_bucket", managed=CountingProvider())

    await integration._load_external_config()
    await integration._load_external_config()

    assert len(calls) == 1


async def test_onboarded_bucket_name_comes_from_the_credential_url():
    integration = _integration(sdk=FakeUserManagerSDK(source=SourceEnum.s3, url="customer-bucket"))

    await integration._load_external_config()

    assert integration.bucket_name == "customer-bucket"
