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


__all__ = ["IntegrationTypeEnum"]
