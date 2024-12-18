FROM hanxi/xiaomusic:builder AS builder
ENV DEBIAN_FRONTEND=noninteractive
RUN pip install -U pdm
ENV PDM_CHECK_UPDATE=false
WORKDIR /app
COPY pyproject.toml README.md .
COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY xiaomusic.py .
RUN pdm install --prod --no-editable

FROM hanxi/xiaomusic:runtime
WORKDIR /app
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/xiaomusic/ ./xiaomusic/
COPY --from=builder /app/plugins/ ./plugins/
COPY --from=builder /app/xiaomusic.py .
COPY --from=builder /app/xiaomusic/__init__.py /base_version.py
RUN touch /app/.dockerenv

COPY supervisor.conf /etc/supervisor.conf

ENV XIAOMUSIC_HOSTNAME=192.168.2.5
ENV XIAOMUSIC_PORT=8090
VOLUME /app/conf
VOLUME /app/music
EXPOSE 8090
ENV TZ=Asia/Shanghai
ENV PATH=/app/.venv/bin:$PATH

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor.conf"]
