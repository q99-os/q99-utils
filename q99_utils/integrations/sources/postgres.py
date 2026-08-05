from __future__ import annotations

from q99_utils.integrations.core import SqlIntegrationBase, register
from q99_utils.enums import SourceEnum


@register(SourceEnum.postgres)
class PostgresIntegration(SqlIntegrationBase):
    SQL_DIALECT = "postgres"
    SQL_BACKEND = "postgres"


__all__ = ["PostgresIntegration"]
