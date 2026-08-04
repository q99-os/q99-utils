"""What an integration needs from its host.

Structural protocols: the host satisfies them by shape, so this package stays
free of SQLAlchemy, FastAPI and friends, and tests can pass plain fakes.
"""

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
