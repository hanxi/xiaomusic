FROM python:3.10 AS builder
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv .venv && .venv/bin/pip install --no-cache-dir -r requirements.txt
COPY install_dependencies.sh .
RUN bash install_dependencies.sh

FROM python:3.10-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/ffmpeg /app/ffmpeg
COPY xiaomusic/ ./xiaomusic/
COPY xiaomusic.py .
ENV XDG_CONFIG_HOME=/config
ENV XIAOMUSIC_HOSTNAME=192.168.2.5
ENV XIAOMUSIC_PORT=8090
VOLUME /config
EXPOSE 8090
ENV PATH=/app/.venv/bin:$PATH
ENTRYPOINT [".venv/bin/python3","xiaomusic.py"]
