"""Datawell connection for a customer installation."""

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.registry import register
from q99_utils.integrations.sources.dccsoft_connection import DccsoftConnectionIntegration


@register(SourceEnum.datawell)
class DatawellIntegration(DccsoftConnectionIntegration):
    pass
