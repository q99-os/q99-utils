"""What an integration needs from its host, as structural protocols."""

from q99_utils.integrations.ports.company_app import CompanyAppProvider
from q99_utils.integrations.ports.files import FileReferenceStore, IndexedFile
from q99_utils.integrations.ports.sql import (
    ConnectionRegistry,
    InMemoryConnectionRegistry,
    SqlDriver,
    SqlDriverFactory,
)
from q99_utils.integrations.ports.storage import (
    ManagedBucket,
    ManagedBucketProvider,
    StorageService,
    StorageServiceFactory,
)

__all__ = [
    "CompanyAppProvider",
    "ConnectionRegistry",
    "FileReferenceStore",
    "InMemoryConnectionRegistry",
    "IndexedFile",
    "ManagedBucket",
    "ManagedBucketProvider",
    "SqlDriver",
    "SqlDriverFactory",
    "StorageService",
    "StorageServiceFactory",
]
