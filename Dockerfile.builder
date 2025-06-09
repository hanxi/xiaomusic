FROM python:3.10.18-alpine3.22 AS builder

RUN apk add --no-cache --virtual .build-deps build-base python3-dev libffi-dev openssl-dev
RUN pip install -U pdm
ENV PDM_CHECK_UPDATE=false
WORKDIR /app
COPY pyproject.toml README.md ./

RUN pdm install --prod --no-editable

FROM python:3.10.18-alpine3.22

WORKDIR /app

COPY --from=builder /app/.venv ./.venv

COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY holiday/ ./holiday/
COPY xiaomusic.py .
