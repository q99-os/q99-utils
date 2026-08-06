from __future__ import annotations

from q99_utils.integrations.core import SqlIntegrationBase, register
from q99_utils.enums import SourceEnum


@register(SourceEnum.bigquery)
class BigQueryIntegration(SqlIntegrationBase):
    SQL_DIALECT = "bigquery"
    SQL_BACKEND = "bigquery"


__all__ = ["BigQueryIntegration"]
