# Multi-platform builder stage
FROM boluofandocker/xiaomusic-online:builder AS builder

RUN pip install -U pdm
ENV PDM_CHECK_UPDATE=false

WORKDIR /app
COPY pyproject.toml README.md package.json .

# Detect architecture and set Rust target only for ARMv7
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "armv7l" ]; then \
        echo "Detected ARMv7, setting Rust target for musl..." && \
        export CARGO_BUILD_TARGET=armv7-unknown-linux-musleabihf && \
        export RUSTFLAGS="--target=armv7-unknown-linux-musleabihf" && \
        pdm install --prod --frozen-lockfile -v; \
    else \
        echo "Building for $ARCH, using default targets..." && \
        pdm install --prod --frozen-lockfile; \
    fi

# Node setup (platform-independent)
RUN node -v && npm -v
RUN uname -m
RUN npm config list
RUN npm install --verbose

# Copy application code
COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY holiday/ ./holiday/
COPY xiaomusic.py .

# ---- Runtime stage ----
FROM hanxi/xiaomusic:runtime

WORKDIR /app

# Copy built artifacts from builder
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/node_modules ./node_modules/
COPY --from=builder /app/xiaomusic/ ./xiaomusic/
COPY --from=builder /app/plugins/ ./plugins/
COPY --from=builder /app/holiday/ ./holiday/
COPY --from=builder /app/xiaomusic.py .
COPY --from=builder /app/xiaomusic/__init__.py /base_version.py
COPY --from=builder /app/package.json .
RUN touch /app/.dockerenv

# Supervisor config
COPY supervisord.conf /etc/supervisor/supervisord.conf
RUN rm -f /var/run/supervisor.sock

# Volumes and ports
VOLUME /app/conf
VOLUME /app/music
EXPOSE 8090

# Environment
ENV TZ=Asia/Shanghai
ENV PATH=/app/.venv/bin:/usr/local/bin:$PATH

# Entrypoint
ENTRYPOINT ["/bin/sh", "-c", "/usr/bin/supervisord -c /etc/supervisor/supervisord.conf && tail -F /app/supervisord.log /app/xiaomusic.log.txt"]
