from abc import ABC, abstractmethod


class OpenWellsAgentMapper(ABC):
    """Backend-agnostic data access for OpenWells agent tools.

    Implementations translate logical fetch/search calls into backend-specific
    SQL. Each method returns plain ``list[dict]`` rows so callers (tools) can
    remain backend-agnostic.
    """

    @abstractmethod
    async def fetch_general(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_activities(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_activity_span(self, well_id: str) -> dict | None: ...

    @abstractmethod
    async def fetch_activity_days(self) -> list[dict]: ...

    @abstractmethod
    async def fetch_events(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_surveys(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_depth_offset(self, well_id: str) -> float: ...

    @abstractmethod
    async def fetch_datum(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_formations(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_casing(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_pipe_tally(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_bha(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_bha_components(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_fluids(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_cement(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_npt_events(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_mud_products(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_solids_control(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_plan_operations(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_plan_headers(self, well_id: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_wells(self) -> list[dict]: ...

    @abstractmethod
    async def fetch_npt_last_end(self, well_ids: list[str] | None = None) -> list[dict]: ...

    @abstractmethod
    async def search_wells_text(self, search_query: str) -> list[dict]: ...

    @abstractmethod
    async def fetch_reference_well(self, well_id: str) -> dict | None: ...

    @abstractmethod
    async def search_offset_wells(
        self,
        *,
        reference_well_id: str,
        field_name: str | None,
        target_formation: str | None,
        max_wells: int,
    ) -> list[dict]: ...

    @abstractmethod
    async def get_well_names(self, well_ids: list[str]) -> dict[str, str]: ...

    @abstractmethod
    async def apply_spud_fallback(self, rows: list[dict]) -> None: ...
