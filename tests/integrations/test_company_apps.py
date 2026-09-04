"""sources_for_app — the reverse of app_source_for, used to size the blast
radius before an admin rotates a company app's credentials."""

from q99_utils.integrations.core import sources_for_app
from q99_utils.enums import SourceEnum


def test_google_oauth_app_covers_drive_and_gmail():
    assert set(sources_for_app("google_oauth_app")) == {SourceEnum.googledrive, SourceEnum.gmail}


def test_microsoft_oauth_app_covers_outlook_sharepoint_and_azure_ad():
    assert set(sources_for_app("microsoft_oauth_app")) == {
        SourceEnum.outlook, SourceEnum.sharepoint, SourceEnum.azure_ad,
    }


def test_a_source_with_no_app_has_no_dependents():
    assert sources_for_app("slack") == []


def test_an_unknown_app_source_has_no_dependents():
    assert sources_for_app("not-a-real-source") == []
