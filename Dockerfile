FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 qadam \
    && useradd --uid 10001 --gid qadam --no-create-home --shell /usr/sbin/nologin qadam \
    && mkdir -p /data/uploads /data/menu_images \
    && chown -R qadam:qadam /data

COPY --chown=qadam:qadam alembic.ini run_server.py run_bot.py ./
COPY --chown=qadam:qadam alembic ./alembic
COPY --chown=qadam:qadam src ./src
COPY --chown=qadam:qadam scripts/__init__.py scripts/safe_seed.py ./scripts/
COPY --chown=qadam:qadam static ./static
COPY --chown=qadam:qadam web ./web

USER qadam

EXPOSE 8000
CMD ["python", "run_server.py"]
