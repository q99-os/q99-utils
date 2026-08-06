"""ACL token vocabulary.

The format is a contract between two packages: the host builds user-side
tokens, integrations build file-side ones, and access is string equality.
"""

from __future__ import annotations

from q99_utils.models import PermissionTokens


def test_constant_tokens():
    assert PermissionTokens.AUTHENTICATED == "quantos:authenticated"
    assert PermissionTokens.ADMIN_ONLY == "quantos:group:quantos-admin"
    assert PermissionTokens.APP_SCOPE == "quantos"


def test_admin_token_is_a_group_token_in_the_app_scope():
    # The two must stay consistent: ADMIN_ONLY is what group() would produce.
    assert PermissionTokens.ADMIN_ONLY == PermissionTokens.group(
        PermissionTokens.APP_SCOPE, "quantos-admin"
    )


def test_group_normalises_case_and_whitespace():
    assert PermissionTokens.group("azure_ad", "  Data Team  ") == "azure_ad:group:data team"


def test_group_scope_is_the_identity_provider_that_owns_the_source():
    assert PermissionTokens.group_scope_for_source("sharepoint") == "azure_ad"
    assert PermissionTokens.group_scope_for_source("googledrive") == "google_workspace"


def test_unmapped_sources_scope_to_themselves():
    # Keeps groups from different providers from colliding by default.
    assert PermissionTokens.group_scope_for_source("s3") == "s3"


def test_group_for_source_combines_scope_and_name():
    assert PermissionTokens.group_for_source("sharepoint", "Engineering") == "azure_ad:group:engineering"
    assert PermissionTokens.group_for_source("googledrive", "Sales") == "google_workspace:group:sales"


def test_email_and_domain_tokens_are_normalised():
    assert PermissionTokens.email("  Ana@Q99.com ") == "email:ana@q99.com"
    assert PermissionTokens.domain(" Q99.COM ") == "domain:q99.com"


def test_sharepoint_and_drive_groups_of_the_same_name_do_not_collide():
    sharepoint = PermissionTokens.group_for_source("sharepoint", "admins")
    drive = PermissionTokens.group_for_source("googledrive", "admins")
    assert sharepoint != drive
