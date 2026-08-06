from __future__ import annotations


class PermissionTokens:
    """Canonical Layer-2 ACL token vocabulary, shared by the user side
    (the host's security service) and the file side (each integration's
    ``_extract_permissions``) so the token format lives in one place.

    Group tokens are scoped by identity provider — ``<scope>:group:<name>`` —
    so groups from different providers can't collide.
    """

    AUTHENTICATED = "quantos:authenticated"
    ADMIN_ONLY = "quantos:group:quantos-admin"
    APP_SCOPE = "quantos"

    _GROUP_SCOPE_BY_SOURCE = {
        "sharepoint": "azure_ad",
        "googledrive": "google_workspace",
    }

    @classmethod
    def group_scope_for_source(cls, source: str) -> str:
        return cls._GROUP_SCOPE_BY_SOURCE.get(str(source), str(source))

    @staticmethod
    def group(scope: str, name: str) -> str:
        return f"{scope}:group:{name.strip().lower()}"

    @classmethod
    def group_for_source(cls, source: str, name: str) -> str:
        return cls.group(cls.group_scope_for_source(source), name)

    @staticmethod
    def email(address: str) -> str:
        return f"email:{address.strip().lower()}"

    @staticmethod
    def domain(value: str) -> str:
        return f"domain:{value.strip().lower()}"


__all__ = ["PermissionTokens"]
