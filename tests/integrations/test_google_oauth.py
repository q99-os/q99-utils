"""Telling a revoked Google grant apart from a bad minute.

Google's SDK reports both as one ``RefreshError``, and reacting to them the same
way is wrong in both directions: retrying a revoked grant never succeeds, and
disconnecting someone over a network blip throws them out of their own
integration for no reason.

The exception is built here instead of imported because ``google.auth`` is an
optional extra — what the code reads is the shape of ``args``, not the class.
"""

import pytest

from q99_utils.integrations.core import CredentialExpired, translate_refresh_error


class RefreshError(Exception):
    """Same shape google.auth.exceptions.RefreshError arrives with."""




def test_the_parsed_body_google_sends_is_recognised():
    error = RefreshError(
        "bad request",
        {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
    )

    with pytest.raises(CredentialExpired) as exc_info:
        translate_refresh_error(error, source="googledrive")

    assert "Reconnect" in str(exc_info.value)
    assert exc_info.value.source == "googledrive"


def test_the_message_alone_is_enough():
    """A proxy in between can strip the JSON and leave only the text."""
    error = RefreshError("invalid_grant: Token has been expired or revoked.")

    with pytest.raises(CredentialExpired):
        translate_refresh_error(error, source="gmail")


def test_the_original_failure_is_kept_as_the_cause():
    error = RefreshError("invalid_grant")

    with pytest.raises(CredentialExpired) as exc_info:
        translate_refresh_error(error, source="googledrive")

    assert exc_info.value.__cause__ is error




@pytest.mark.parametrize(
    "message",
    [
        "Connection reset by peer",
        "<html>502 Bad Gateway</html>",
        "The read operation timed out",
    ],
)
def test_a_passing_failure_disconnects_nobody(message):
    error = RefreshError(message)

    with pytest.raises(RefreshError):
        translate_refresh_error(error, source="googledrive")


def test_another_google_error_is_not_a_dead_grant():
    """invalid_scope is a misconfiguration, not a revoked access: it needs fixing,
    not asking the user to reconnect."""
    error = RefreshError("bad request", {"error": "invalid_scope"})

    with pytest.raises(RefreshError):
        translate_refresh_error(error, source="googledrive")
