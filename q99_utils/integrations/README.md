# q99_utils.integrations

Source integrations, independent of any host application.

Nothing here imports a web framework, an ORM, or a settings module. Whatever an
integration needs from the outside arrives through `IntegrationContext`;
whatever it cannot do itself is declared as a `Protocol` under `ports/` and
supplied by the host.

## Layout

```
q99_utils/integrations/
├── core/                       the machinery every integration is built on
│   ├── source.py               SourceIntegrationInterface — the contract
│   ├── sql_source.py           SqlIntegrationBase — connect / cache / close
│   ├── context.py              IntegrationContext + IntegrationConfig
│   ├── registry.py             @register, register_alias, create_integration
│   ├── exceptions.py           IntegrationError, CredentialValidationError
│   └── change_detection.py     classify_change — what changed about an indexed file
├── discovery.py                DiscoveredFile, ResourceNode, ChangeKind
├── ports/                      what the host must provide
│   ├── sql.py                  SqlDriver, SqlDriverFactory, ConnectionRegistry
│   ├── files.py                FileReferenceStore, IndexedFile
│   └── storage.py              StorageService, StorageServiceFactory, ManagedBucketProvider
├── sources/                    one integration per module, named after its source
│   ├── slack.py                greenapi.py   azure_ad.py     databricks.py
│   ├── postgres.py             mssql.py      bigquery.py     openwells.py
│   ├── local_files.py          bucket.py     sharepoint.py   google_drive.py
│   └── alamo.py                google_sso.py
└── mappers/                    query layers over a source's own schema
    ├── openwells_base.py       OpenWellsAgentMapper (the contract)
    └── openwells_edm.py        OpenWellsEDMMapper (the EDM SQL)

tests/integrations/
├── fakes.py                    in-memory stand-in per port
├── test_registry_and_context.py
├── test_change_detection.py
└── sources/                    one module per integration
```

The ACL vocabulary (`PermissionTokens`) lives in `q99_utils.models` — the host's
security layer builds user-side tokens with the same class.

## Extras

| Extra | Needed for |
|---|---|
| `google` | the Google Drive integration |
| `openwells` | OpenWells on any backend other than MSSQL (SQL is transpiled at query time) |

`sources/` and `mappers/` are different things. A source integration is
registered and built through `create_integration`; a mapper is not — it takes
the connection a source opened and knows the SQL to ask domain questions of it.
Agents import mappers directly.

## How a call flows

```
host                          library                       host again
────                          ───────                       ──────────
build the context      →   create_integration(source)
(config + adapters)        looks up the registry
                       →   Integration(source, um_sdk, context)
                           runs its own provider logic
                           needs infrastructure?      →   calls a port
                                                          (the host's adapter)
                       ←   returns DiscoveredFile / ResourceNode / a driver
```

The library never reaches for the host. Anything it can't do itself is a port
call, and the host decides what sits behind it.

## Using it from a host

```python
from q99_utils.integrations import (
    IntegrationConfig,
    IntegrationContext,
    create_integration,
)

context = IntegrationContext(
    config=IntegrationConfig(
        environment=str(settings.ENVIRONMENT),
        webhook_base_url=settings.DO_URL,
        upload_max_size_mb=settings.UPLOAD_MAX_SIZE_MB,
    ),
    connections=MyConnectionRegistry(),   # adapter over the host's connection pool
    driver_factory=MyDriverFactory(),     # builds Postgres/MSSQL/BigQuery drivers
    file_store=MyFileReferenceStore(),    # reads the host's ingested-file index
    storage_factory=MyStorageFactory(),   # builds S3/Blob/GCS clients
    managed_bucket=MyManagedBucket(),     # the host's own bucket credential
)

integration = create_integration(source, um_sdk=um_sdk, context=context)
```

`create_integration` returns `None` for sources with no integration class (LLM
providers, webpages) — callers already treat that as a valid state.

## Ports

| Port | Why | Notes |
|---|---|---|
| `ConnectionRegistry` | Caches live SQL connections per credential | Defaults to `InMemoryConnectionRegistry`; a real host wraps its own pool |
| `SqlDriverFactory` | Builds an initialised driver from a credential | Keyed on `SQL_BACKEND`, not on the source |
| `FileReferenceStore` | Reads what the host has already ingested | Drives incremental discovery |
| `StorageServiceFactory` | Builds a client for a cloud provider | Keeps the cloud SDKs host-side |
| `ManagedBucketProvider` | The host's own object-storage credential | Provisioned by the platform, not by a user |

Each is optional. An integration that needs one and doesn't get it fails with a
clear error at the point of use, not at construction.

## Errors

Integrations raise the framework-agnostic errors in `exceptions.py`. The host
maps them at its edge — for FastAPI:

```python
@app.exception_handler(CredentialValidationError)
async def _credential_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": exc.message})
```

`CredentialValidationError.message` is written for end users and is safe to
return in a response body; provider internals are logged, never included.

## Adding an integration

Subclass `SourceIntegrationInterface` (or `SqlIntegrationBase` for a SQL
backend), decorate it, and import it from `sources/__init__.py` — that import is
what registers it.

```python
@register(SourceEnum.my_source)
class MySourceIntegration(SourceIntegrationInterface):
    ...
```

For SQL backends, declare the two values and inherit the rest:

```python
@register(SourceEnum.postgres)
class PostgresIntegration(SqlIntegrationBase):
    SQL_DIALECT = "postgres"   # what sqlglot should parse as
    SQL_BACKEND = "postgres"   # which driver the host must build
```

If it needs something from the host that no port covers yet: add the protocol
under `ports/`, add an optional field to `IntegrationContext`, implement it in
the host's adapters, and wire it where the context is built.

## Logging

Use `q99_utils.logger.get_logger(__name__)`. The library attaches a
`NullHandler` and configures nothing else — routing and levels belong to the
host.
