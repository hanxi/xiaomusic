FROM python:3.12-alpine3.22

RUN apk add --no-cache --virtual .build-deps build-base python3-dev libffi-dev openssl-dev zlib-dev jpeg-dev libc6-compat gcc musl-dev \
    && apk add --no-cache nodejs npm

RUN pip install -U pdm
ENV PDM_CHECK_UPDATE=false
WORKDIR /app
COPY pyproject.toml README.md package.json ./

RUN pdm install --prod --no-editable -v
RUN node -v && npm -v
RUN uname -m
RUN npm config list
RUN npm install --verbose

COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY holiday/ ./holiday/
COPY xiaomusic.py .
