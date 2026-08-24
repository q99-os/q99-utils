"""Build the token against the company app, and never stop working if you cannot.

Reading the app is what lets a rotated secret reach every integration at once. But it
is read over the network, with rights the caller may not have, so every way that
answer can fail to arrive has to end in the stored copy rather than in an error — a
deployment that never wires a provider has to behave exactly as it did before.
"""

import pytest

from q99_utils.enums import IntegrationTypeEnum, SourceEnum
from q99_utils.integrations.core import IntegrationContext, SourceIntegrationInterface
from q99_utils.models import OnboardingData

APP = {
    "client_id": "app-client-id",
    "client_secret": "app-secret",
    "tenant_id": "app-tenant",
}


def _stored(**overrides):
    return OnboardingData(
        source=SourceEnum.outlook,
        integration_type=IntegrationTypeEnum.email,
        client_id="stored-client-id",
        client_secret="stored-secret",
        tenant_id="stored-tenant",
        **overrides,
    )


class _Provider:
    def __init__(self, answer=None, boom=False):
        self.answer = answer
        self.boom = boom
        self.asked = []

    async def app_credentials(self, app_source):
        self.asked.append(app_source)
        if self.boom:
            raise RuntimeError("the User Manager is unreachable")
        return self.answer


def _integration(provider=None, source=SourceEnum.outlook):
    context = IntegrationContext(company_app=provider) if provider else IntegrationContext()
    return SourceIntegrationInterface(source=source, um_sdk=None, context=context)


@pytest.mark.asyncio
async def test_the_app_wins_over_the_stored_copy():
    provider = _Provider(APP)

    resolved = await _integration(provider).with_company_app(_stored())

    assert resolved.client_id == "app-client-id"
    assert resolved.client_secret == "app-secret"
    assert resolved.tenant_id == "app-tenant"
    assert provider.asked == ["microsoft_oauth_app"]


@pytest.mark.asyncio
async def test_it_asks_for_the_app_the_source_actually_runs_against():
    provider = _Provider(APP)

    await _integration(provider, source=SourceEnum.googledrive).with_company_app(_stored())

    assert provider.asked == ["google_oauth_app"]


@pytest.mark.asyncio
async def test_without_a_provider_nothing_changes():
    """A deployment that never wires one keeps working exactly as before."""
    resolved = await _integration().with_company_app(_stored())

    assert resolved.client_secret == "stored-secret"


@pytest.mark.asyncio
async def test_a_source_with_no_company_app_is_left_alone():
    provider = _Provider(APP)

    resolved = await _integration(provider, source=SourceEnum.slack).with_company_app(_stored())

    assert resolved.client_secret == "stored-secret"
    assert provider.asked == []


@pytest.mark.asyncio
async def test_an_unreachable_user_manager_falls_back_instead_of_failing():
    resolved = await _integration(_Provider(boom=True)).with_company_app(_stored())

    assert resolved.client_secret == "stored-secret"


@pytest.mark.asyncio
async def test_no_app_loaded_falls_back():
    """What a regular user's token would answer: nothing, and no error."""
    resolved = await _integration(_Provider(None)).with_company_app(_stored())

    assert resolved.client_secret == "stored-secret"


@pytest.mark.asyncio
async def test_a_half_filled_app_only_overrides_what_it_carries():
    """Google's app has no tenant: the missing field must not blank the stored one."""
    provider = _Provider({"client_id": "app-client-id", "client_secret": "app-secret"})

    resolved = await _integration(provider).with_company_app(_stored())

    assert resolved.client_id == "app-client-id"
    assert resolved.tenant_id == "stored-tenant"


@pytest.mark.asyncio
async def test_it_does_not_mutate_what_it_was_given():
    """The stored copy stays intact, so a failed refresh cannot corrupt it."""
    stored = _stored()

    await _integration(_Provider(APP)).with_company_app(stored)

    assert stored.client_secret == "stored-secret"
