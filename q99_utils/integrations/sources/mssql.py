from __future__ import annotations

from q99_utils.integrations.core import SqlIntegrationBase, register
from q99_utils.enums import SourceEnum


@register(SourceEnum.mssql)
class MSSQLIntegration(SqlIntegrationBase):
    SQL_DIALECT = "tsql"
    SQL_BACKEND = "mssql"


__all__ = ["MSSQLIntegration"]
