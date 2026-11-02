"""The wells client passes on what the wells service says, and never sends a browser a 401."""

import httpx

from q99_utils.wells_sdk import _as_error


def _response(code: int, body) -> httpx.Response:
    return httpx.Response(code, json=body)


def test_a_refusal_says_what_the_wells_service_said():
    approved = _as_error(_response(409, {"error": "This plan is approved. Its numbers are final."}))
    denied = _as_error(_response(403, {"error": "You do not have permission to access this feature.",
                                       "missing_permissions": ["wells.db:update"]}))

    assert (approved.status_code, approved.detail) == (409, "This plan is approved. Its numbers are final.")
    assert (denied.status_code, denied.detail) == (403, "You do not have permission to access this feature.")


def test_a_permission_refusal_without_words_still_says_it_is_one():
    error = _as_error(httpx.Response(403, text="forbidden"))

    assert (error.status_code, error.detail) == (403, "You don't have permission to do this in qWells. Ask your administrator.")


def test_a_refused_payload_names_each_field_and_why():
    error = _as_error(_response(422, {"error": "Validation failed", "errors": [
        {"loc": ["body", "add", 0, "hours"], "msg": "Input should be a valid number", "type": "float_parsing"},
        {"loc": ["body", "version"], "msg": "Input should be a valid integer", "type": "int_parsing"}]}))

    assert error.status_code == 422
    assert error.detail == "add.0.hours: Input should be a valid number; version: Input should be a valid integer"


def test_a_rejected_credential_never_reaches_the_browser_as_a_401():
    error = _as_error(_response(401, {"error": "Invalid token"}))

    assert error.status_code == 503 and "service key" not in error.detail
