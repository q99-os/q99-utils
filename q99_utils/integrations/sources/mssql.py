"""Microsoft SQL Server integration."""

from __future__ import annotations

from q99_utils.integrations.registry import register
from q99_utils.integrations.sql_base import SqlIntegrationBase
from q99_utils.models import SourceEnum


@register(SourceEnum.mssql)
class MSSQLIntegration(SqlIntegrationBase):
    # MSSQL speaks T-SQL; sqlglot names that dialect 'tsql'.
    SQL_DIALECT = "tsql"
    SQL_BACKEND = "mssql"


__all__ = ["MSSQLIntegration"]
