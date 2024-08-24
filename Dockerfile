FROM python:3.10 AS builder
ENV DEBIAN_FRONTEND=noninteractive
RUN pip install -U pdm
ENV PDM_CHECK_UPDATE=false
WORKDIR /app
COPY pyproject.toml README.md .
COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY xiaomusic.py .
RUN pdm install --prod --no-editable
COPY install_dependencies.sh .
RUN bash install_dependencies.sh

FROM python:3.10-slim
RUN pip install pydub
RUN python3 -m venv /app/.venv
RUN /app/.venv/bin/pip install pydub
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/ffmpeg /app/ffmpeg
COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY xiaomusic.py .
ENV XIAOMUSIC_HOSTNAME=192.168.2.5
ENV XIAOMUSIC_PORT=8090
VOLUME /app/conf
VOLUME /app/music
EXPOSE 8090
ENV PATH=/app/.venv/bin:$PATH
ENTRYPOINT [".venv/bin/python3","xiaomusic.py"]
