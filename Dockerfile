# 定义构建参数，用于指定架构和基础镜像
ARG PYTHON_VERSION=3.14

# 根据不同架构选择对应的基础镜像
FROM python:${PYTHON_VERSION}-alpine AS base-linux-amd64
FROM python:${PYTHON_VERSION}-alpine AS base-linux-arm64
FROM python:${PYTHON_VERSION}-bookworm AS base-linux-arm-v7

FROM python:${PYTHON_VERSION}-alpine AS run-linux-amd64
FROM python:${PYTHON_VERSION}-alpine AS run-linux-arm64
FROM python:${PYTHON_VERSION}-bookworm AS run-linux-arm-v7

FROM --platform=$BUILDPLATFORM alpine AS shelf
# 这里的逻辑是关键：接收标准的 TARGETPLATFORM (如 linux/amd64)
# 并将其转换为我们定义的别名格式 (如 linux-amd64)
ARG TARGETPLATFORM
RUN echo ${TARGETPLATFORM//\//-} > /platform_id

# 根据TARGETPLATFORM自动选择对应的builder阶段
ARG TARGETPLATFORM
FROM base-${TARGETPLATFORM/linux\//linux-} AS builder

# 安装构建依赖（根据基础镜像类型区分）
RUN if [ -f /etc/alpine-release ]; then \
        # Alpine系统依赖
        apk add --no-cache \
        build-base \
        nodejs \
        npm \
        zlib-dev \
        jpeg-dev \
        freetype-dev \
        lcms2-dev \
        openjpeg-dev \
        tiff-dev \
        libwebp-dev; \
    else \
        # Debian系统依赖
        apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        nodejs \
        npm \
        zlib1g-dev \
        libjpeg-dev \
        libfreetype6-dev \
        liblcms2-dev \
        libopenjp2-7-dev \
        libtiff5-dev \
        libwebp-dev \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# 安装PDM
RUN pip install -U pdm
ENV PDM_CHECK_UPDATE=false

WORKDIR /app
COPY pyproject.toml README.md package.json ./

# 安装Python和Node.js依赖
RUN pdm install --prod --no-editable -v
RUN npm install --loglevel=verbose

# 复制应用代码
COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY holiday/ ./holiday/
COPY xiaomusic.py .

# -------------------------- 运行阶段 --------------------------
# 根据TARGETPLATFORM自动选择对应的runner阶段
ARG TARGETPLATFORM
FROM run-${TARGETPLATFORM/linux\//linux-} AS runner

# 安装运行时依赖（区分Alpine和Debian）
RUN if [ -f /etc/alpine-release ]; then \
        # Alpine运行时依赖
        apk add --no-cache \
        ffmpeg \
        nodejs \
        npm; \
    else \
        # Debian运行时依赖
        apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        nodejs \
        npm \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# 设置工作目录
WORKDIR /app

# 从构建阶段复制产物
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/node_modules ./node_modules/
COPY --from=builder /app/xiaomusic/ ./xiaomusic/
COPY --from=builder /app/plugins/ ./plugins/
COPY --from=builder /app/holiday/ ./holiday/
COPY --from=builder /app/xiaomusic.py .
COPY --from=builder /app/xiaomusic/__init__.py /base_version.py
COPY --from=builder /app/package.json .

# 创建FFmpeg软链接目录（兼容不同系统的ffmpeg路径）
RUN mkdir -p /app/ffmpeg/bin \
    && ln -s $(which ffmpeg) /app/ffmpeg/bin/ffmpeg \
    && ln -s $(which ffprobe) /app/ffmpeg/bin/ffprobe

RUN touch /app/.dockerenv

# 设置卷和暴露端口
VOLUME /app/conf
VOLUME /app/music
EXPOSE 8090

# 设置环境变量
ENV TZ=Asia/Shanghai
ENV PATH=/app/.venv/bin:/usr/local/bin:$PATH

# 直接启动xiaomusic应用
CMD ["/app/.venv/bin/python3", "/app/xiaomusic.py"]
