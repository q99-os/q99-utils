"""test_connection on Drive, Gmail and Outlook — the primitive the proactive
company-app-rotation check needs: force a real refresh, not a cached-token
pass, and classify a dead grant the same way the rest of the code already does.
"""

import pytest
from google.auth.exceptions import RefreshError

from q99_utils.integrations.core import CredentialExpired
from q99_utils.integrations.sources.google_drive import GoogleDriveIntegration
from q99_utils.integrations.sources.gmail import GmailIntegration
from q99_utils.integrations.sources.outlook import OutlookIntegration
from q99_utils.models import OnboardingData


class _NoCompanyAppContext:
    """with_company_app short-circuits on company_app is None — exactly the
    fallback-to-stored-credentials path these tests want."""
    company_app = None


def _bare(cls, source):
    instance = object.__new__(cls)
    instance.context = _NoCompanyAppContext()
    instance.source = source
    return instance


FAKE_DATA = OnboardingData(
    source="googledrive",
    integration_type="file_system",
    api_key="ya29.fake",
    refresh_token="1//fake",
    client_id="client-1",
    client_secret="secret-1",
)


@pytest.mark.asyncio
async def test_drive_test_connection_forces_a_refresh_and_classifies_it(monkeypatch):
    from google.oauth2.credentials import Credentials

    def _raise_refresh(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", _raise_refresh)

    integration = _bare(GoogleDriveIntegration, "googledrive")
    with pytest.raises(CredentialExpired):
        await integration.test_connection(FAKE_DATA)


@pytest.mark.asyncio
async def test_gmail_test_connection_forces_a_refresh_and_classifies_it(monkeypatch):
    from google.oauth2.credentials import Credentials

    def _raise_refresh(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", _raise_refresh)

    integration = _bare(GmailIntegration, "gmail")
    with pytest.raises(CredentialExpired):
        await integration.test_connection(FAKE_DATA)


@pytest.mark.asyncio
async def test_outlook_test_connection_forces_a_refresh_and_classifies_it(monkeypatch):
    from q99_utils.integrations.core import CredentialExpired as CoreCredentialExpired
    import q99_utils.integrations.sources.outlook as outlook_module

    async def _raise_refresh_grant(**kwargs):
        raise CoreCredentialExpired("Microsoft no longer accepts this connection.", source=kwargs.get("source"))

    monkeypatch.setattr(outlook_module, "refresh_delegated_token", _raise_refresh_grant)

    outlook_data = OnboardingData(
        source="outlook",
        integration_type="email",
        api_key="fake-access",
        refresh_token="fake-refresh",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
    )

    integration = _bare(OutlookIntegration, "outlook")
    with pytest.raises(CoreCredentialExpired):
        await integration.test_connection(outlook_data)
