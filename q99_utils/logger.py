"""Library logging.

The ``NullHandler`` keeps q99-utils quiet when the host configures no logging,
while still propagating through its handlers when it does. Configuring logging
is the host's job, never a library's.
"""

import logging

_ROOT_NAME = "q99_utils"

logging.getLogger(_ROOT_NAME).addHandler(logging.NullHandler())


def get_logger(name: str | None = None) -> logging.Logger:
    """Child logger under the ``q99_utils`` namespace.

    Everything nests under one root, so a host can route or silence the whole
    library with a single config.
    """
    if not name or name == _ROOT_NAME:
        return logging.getLogger(_ROOT_NAME)
    if name.startswith(f"{_ROOT_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
