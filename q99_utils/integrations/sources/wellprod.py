"""Wellprod connection for a customer installation."""

from q99_utils.enums import SourceEnum
from q99_utils.integrations.core.registry import register
from q99_utils.integrations.sources.dccsoft_connection import DccsoftConnectionIntegration


@register(SourceEnum.wellprod)
class WellprodIntegration(DccsoftConnectionIntegration):
    pass
