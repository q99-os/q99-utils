from enum import StrEnum


class DatabaseBackendEnum(StrEnum):
    postgres = "postgresql"
    mssql = "mssql"


__all__ = ["DatabaseBackendEnum"]
