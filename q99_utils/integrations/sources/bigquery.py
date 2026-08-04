"""Google BigQuery integration."""

from __future__ import annotations

from q99_utils.integrations.registry import register
from q99_utils.integrations.sql_base import SqlIntegrationBase
from q99_utils.models import SourceEnum


@register(SourceEnum.bigquery)
class BigQueryIntegration(SqlIntegrationBase):
    SQL_DIALECT = "bigquery"
    SQL_BACKEND = "bigquery"


__all__ = ["BigQueryIntegration"]
