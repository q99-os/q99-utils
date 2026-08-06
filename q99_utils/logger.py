"""Library logging. Configuring it is the host's job, never a library's."""

import logging

_ROOT_NAME = "q99_utils"

logging.getLogger(_ROOT_NAME).addHandler(logging.NullHandler())


def get_logger(name: str | None = None) -> logging.Logger:
    """Child logger under ``q99_utils``, so a host can route the lot at once."""
    if not name or name == _ROOT_NAME:
        return logging.getLogger(_ROOT_NAME)
    if name.startswith(f"{_ROOT_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
