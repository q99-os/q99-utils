"""Query mappers: a source opens the connection, a mapper knows the SQL."""

from q99_utils.integrations.mappers.openwells_base import OpenWellsAgentMapper
from q99_utils.integrations.mappers.openwells_edm import OpenWellsEDMMapper

__all__ = ["OpenWellsAgentMapper", "OpenWellsEDMMapper"]
