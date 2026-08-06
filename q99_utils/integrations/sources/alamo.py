"""Alamo Analytics external API integration.

A read-only client for Alamo's well production/diagnostics platform. Eight
endpoints, all ``POST``, all sharing one request envelope::

    {"version": 1, "apiKey": ..., "tipo": <endpoint>, "parametros": {...}}

Two things about this API drive the shape of this module: the API key travels in
the request *body* rather than a header, and the tenant is part of the hostname,
so both come off the credential and neither can be a module-level constant.

Dates are Argentina time (UTC-3) and the filters are half-open —
``fecha_inicial <= fecha < fecha_final``. Callers may pass either a preformatted
string or a ``datetime``.

Pagination is deliberately not implemented: Alamo has no cursor or offset, and
the only way to page is to narrow the date range and re-query. Each endpoint
silently caps its response instead of signalling truncation, so a response that
arrives at exactly the cap is logged as a warning and ``ENDPOINT_LIMITS`` is
public for callers that want to detect it themselves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import httpx

from q99_utils.integrations.base import SourceIntegrationInterface
from q99_utils.integrations.exceptions import CredentialValidationError, IntegrationError
from q99_utils.integrations.registry import register
from q99_utils.logger import get_logger
from q99_utils.models import OnboardingData, SourceEnum

logger = get_logger(__name__)

HOST_TEMPLATE = "https://{tenant}-api.alamo-analytics.com/externalApi"

#: The envelope's format version. Alamo's docs say to always send 1.
REQUEST_VERSION = 1

TIMEOUT = 120

#: Argentina time (UTC-3); the API neither sends nor accepts an offset.
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Max records Alamo returns per call, per endpoint. A response of exactly this
#: length means data was almost certainly dropped.
ENDPOINT_LIMITS = {
    "readComments": 1000,
    "readCommentsMasicos": 1000,
    "readControlesSinteticos": 1000,
    "presionesFondo": 10_000,
    "produccionSolidos": 10_000,
    "diagnosticos": 10_000,
    "actionHub": 10_000,
    "ensayoPozo": 10_000,
}

# A one-minute window far enough in the past to be certain it is cheap, used to
# prove a credential works without needing a clock or a known well name.
_PROBE_RANGE = ("2000-01-01 00:00:00", "2000-01-01 00:01:00")


@register(SourceEnum.alamo)
class AlamoIntegration(SourceIntegrationInterface):
    """Read-only client for Alamo Analytics' external API.

    Every public method returns the response's ``data`` array as a list of
    dicts. Fields are passed through untranslated — the host decides what to do
    with them.
    """

    # Credentials and URL

    async def _resolve_credentials(
        self, data: Optional[OnboardingData] = None
    ) -> OnboardingData:
        """Use the caller's credentials, or fetch this credential's from UM."""
        return data if data is not None else await self.get_credentials()

    def _base_url(self, credentials: OnboardingData) -> str:
        """Resolve the API root: an explicit ``api_base`` wins, else the tenant template."""
        if credentials.api_base:
            return str(credentials.api_base).rstrip("/")
        if credentials.tenant_name:
            return HOST_TEMPLATE.format(tenant=credentials.tenant_name)
        raise CredentialValidationError(
            "Alamo Analytics needs either a tenant name or an explicit API base URL. "
            "The tenant is the identifier Alamo assigned to your organisation.",
            source=str(self.source),
        )

    @staticmethod
    def _fmt(value: Any) -> Any:
        """Format a ``datetime`` the way Alamo expects; pass anything else through."""
        if isinstance(value, datetime):
            return value.strftime(DATE_FORMAT)
        return value

    # Transport

    async def _call(
        self,
        tipo: str,
        parametros: Dict[str, Any],
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """POST one request envelope and return its ``data`` array.

        Transport failures propagate: retry and backoff are the host's call, not
        a library's. A 200 that isn't the documented envelope is an
        ``IntegrationError`` — it means we are not talking to the API we think.
        """
        credentials = await self._resolve_credentials(data)
        url = f"{self._base_url(credentials)}/{tipo}"
        payload = {
            "version": REQUEST_VERSION,
            "apiKey": credentials.api_key,
            "tipo": tipo,
            "parametros": parametros,
        }

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError:  # non-JSON body — maintenance page, proxy error, ...
                raise IntegrationError(
                    f"Alamo '{tipo}' returned a non-JSON body."
                )

        records = body.get("data") if isinstance(body, dict) else None
        if not isinstance(records, list):
            raise IntegrationError(
                f"Alamo '{tipo}' response has no 'data' array."
            )

        limit = ENDPOINT_LIMITS.get(tipo)
        if limit is not None and len(records) == limit:
            logger.warning(
                "Alamo '%s' returned exactly its %d-record limit — the result is "
                "probably truncated. Narrow the date range and query again.",
                tipo,
                limit,
            )

        return records

    def _range(self, fecha_inicial: Any, fecha_final: Any) -> Dict[str, Any]:
        return {
            "fecha_inicial": self._fmt(fecha_inicial),
            "fecha_final": self._fmt(fecha_final),
        }

    async def _by_pozos(
        self,
        tipo: str,
        fecha_inicial: Any,
        fecha_final: Any,
        pozos: Optional[Sequence[str]],
        data: Optional[OnboardingData],
    ) -> List[dict]:
        """Shared shape for the six endpoints filtered by well name."""
        return await self._call(
            tipo,
            {"pozos": list(pozos) if pozos else None, **self._range(fecha_inicial, fecha_final)},
            data=data,
        )

    # Credential validation

    async def test_connection(self, data: Optional[OnboardingData] = None) -> None:
        """Verify the API key and tenant by making one deliberately tiny read.

        Alamo exposes no auth-check endpoint, so this reads ``readComments`` over
        a one-minute window in the year 2000 — cheap, deterministic, and it
        returns an empty array rather than real data.
        """
        credentials = await self._resolve_credentials(data)
        fecha_inicial, fecha_final = _PROBE_RANGE

        try:
            await self.read_comments(fecha_inicial, fecha_final, data=credentials)
        except CredentialValidationError:
            raise
        except (httpx.HTTPError, IntegrationError):
            logger.warning("Alamo connection test failed", exc_info=True)
            raise CredentialValidationError(
                "Alamo Analytics connection test failed. Verify the API key and "
                "tenant name are correct and that this deployment can reach "
                "Alamo's API.",
                source=str(self.source),
            )

    # Endpoints

    async def read_comments(
        self,
        fecha_inicial: Any,
        fecha_final: Any,
        pozos: Optional[Sequence[str]] = None,
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """Well comments. Records: fecha, fecha_ref, pozo, comentario, tipo, usuario."""
        return await self._by_pozos(
            "readComments", fecha_inicial, fecha_final, pozos, data
        )

    async def read_comments_masicos(
        self,
        fecha_inicial: Any,
        fecha_final: Any,
        masicos: Optional[Sequence[str]] = None,
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """Mass-meter comments. Filtered by ``masicos``, not ``pozos``."""
        return await self._call(
            "readCommentsMasicos",
            {
                "masicos": list(masicos) if masicos else None,
                **self._range(fecha_inicial, fecha_final),
            },
            data=data,
        )

    async def presiones_fondo(
        self,
        fecha_inicial: Any,
        fecha_final: Any,
        pozos: Optional[Sequence[str]] = None,
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """Bottom-hole pressures in PSI. Records: fecha, pozo, presion_fondo,
        presion_fondo_inicial."""
        return await self._by_pozos(
            "presionesFondo", fecha_inicial, fecha_final, pozos, data
        )

    async def read_controles_sinteticos(
        self,
        fecha_inicial: Any,
        fecha_final: Any,
        pozos: Optional[Sequence[str]] = None,
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """Synthetic controls: measured gross/net/gas flow, pressures, line
        temperature, choke opening and state."""
        return await self._by_pozos(
            "readControlesSinteticos", fecha_inicial, fecha_final, pozos, data
        )

    async def produccion_solidos(
        self,
        fecha_inicial: Any,
        fecha_final: Any,
        pozos: Optional[Sequence[str]] = None,
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """Solids production in kg/d, plus the accumulated total in kg."""
        return await self._by_pozos(
            "produccionSolidos", fecha_inicial, fecha_final, pozos, data
        )

    async def diagnosticos(
        self,
        fecha_inicial: Any,
        fecha_final: Any,
        pozos: Optional[Sequence[str]] = None,
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """Diagnostic history. Records: pozo, fecha, motivo, diagnostico,
        comentario, creador."""
        return await self._by_pozos(
            "diagnosticos", fecha_inicial, fecha_final, pozos, data
        )

    async def action_hub(
        self,
        fecha_inicial: Any,
        fecha_final: Any,
        entity_type: Optional[str] = None,
        entity_names: Optional[Sequence[str]] = None,
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """Action Hub optimisation actions, filtered on the item's creation date.

        Unlike the other endpoints this spans entity types, so it takes
        ``entity_type`` ("Pozo", "Masico", "SlotQuimico", "Separador", "Ducto")
        and ``entity_names`` instead of ``pozos``. The API only honours
        ``entity_names`` alongside an ``entity_type``.
        """
        if entity_names and not entity_type:
            raise ValueError(
                "action_hub(entity_names=...) also requires entity_type — "
                "Alamo ignores the name filter without it."
            )

        return await self._call(
            "actionHub",
            {
                **self._range(fecha_inicial, fecha_final),
                "entity_type": entity_type,
                "entity_names": list(entity_names) if entity_names else None,
            },
            data=data,
        )

    async def ensayo_pozo(
        self,
        fecha_inicial: Any,
        fecha_final: Any,
        pozos: Optional[Sequence[str]] = None,
        data: Optional[OnboardingData] = None,
    ) -> List[dict]:
        """Well tests: stabilisation times, gross/gas/net flow, separator used.

        Note the record's own date field is ``fecha_inicial`` rather than
        ``fecha``.
        """
        return await self._by_pozos(
            "ensayoPozo", fecha_inicial, fecha_final, pozos, data
        )


__all__ = ["AlamoIntegration", "ENDPOINT_LIMITS", "HOST_TEMPLATE"]
