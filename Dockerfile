# Polling-бот: исходящий HTTPS, входящие порты не нужны.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Фиксированный uid/gid — на хосте: mkdir -p data && sudo chown 1000:1000 data
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --system --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app

USER app

CMD ["python", "-m", "tg_digest_bot"]
