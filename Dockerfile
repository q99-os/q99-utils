# Dev container for debugging q99-utils in VSCode (attach via docker compose).
FROM python:3.12-slim

WORKDIR /code

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY ./pyproject.toml ./uv.lock /code/

# Install locked dependencies (including the dev group: pip-audit, bandit)
# into the system interpreter so they survive the compose volume mount.
RUN python3 -m pip install --no-cache-dir uv \
    && uv export --frozen --no-emit-project --no-hashes --format requirements-txt -o /tmp/requirements.lock \
    && uv pip install --system --no-cache -r /tmp/requirements.lock

COPY ./ /code/

RUN uv pip install --system --no-cache --no-deps -e .
