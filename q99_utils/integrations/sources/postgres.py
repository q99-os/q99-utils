"""PostgreSQL integration."""

from __future__ import annotations

from q99_utils.integrations.registry import register
from q99_utils.integrations.sql_base import SqlIntegrationBase
from q99_utils.models import SourceEnum


@register(SourceEnum.postgres)
class PostgresIntegration(SqlIntegrationBase):
    SQL_DIALECT = "postgres"
    SQL_BACKEND = "postgres"


__all__ = ["PostgresIntegration"]
