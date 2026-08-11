from enum import StrEnum


class IntegrationTypeEnum(StrEnum):
    file_system = "file_system"
    database = "database"
    chat_model = "chat_model"
    embeddings_model = "embeddings_model"
    reasoning_model = "reasoning_model"
    bot = "bot"
    email = "email"
    idp = "idp"
    bucket = "bucket"
    quantos_bucket = "quantos_bucket"
    local_db = "local_db"
    greenapi_partner = "greenapi-partner"
    external_api = "external_api"
    sso = "sso"


__all__ = ["IntegrationTypeEnum"]
