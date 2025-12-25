FROM hanxi/xiaomusic:builder AS builder

RUN pip install -U pdm
ENV PDM_CHECK_UPDATE=false
WORKDIR /app
COPY pyproject.toml README.md package.json .

RUN pdm install --prod --no-editable -v
RUN node -v && npm -v
RUN uname -m
RUN npm config list
RUN npm install --verbose

COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY holiday/ ./holiday/
COPY xiaomusic.py .

FROM hanxi/xiaomusic:runtime

WORKDIR /app

COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/node_modules ./node_modules/
COPY --from=builder /app/xiaomusic/ ./xiaomusic/
COPY --from=builder /app/plugins/ ./plugins/
COPY --from=builder /app/holiday/ ./holiday/
COPY --from=builder /app/xiaomusic.py .
COPY --from=builder /app/xiaomusic/__init__.py /base_version.py
COPY --from=builder /app/package.json .
RUN touch /app/.dockerenv

COPY supervisord.conf /etc/supervisor/supervisord.conf
RUN rm -f /var/run/supervisor.sock

VOLUME /app/conf
VOLUME /app/music
EXPOSE 8090
ENV TZ=Asia/Shanghai
ENV PATH=/app/.venv/bin:/usr/local/bin:$PATH

ENTRYPOINT ["/bin/sh", "-c", "/usr/bin/supervisord -c /etc/supervisor/supervisord.conf && tail -F /app/supervisord.log /app/xiaomusic.log.txt"]
