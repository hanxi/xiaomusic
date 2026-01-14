# 第一阶段：构建阶段
FROM python:3.14-alpine AS builder

# 安装构建依赖
RUN apk add --no-cache \
    build-base \
    nodejs \
    npm \
    zlib-dev \
    jpeg-dev \
    freetype-dev \
    lcms2-dev \
    openjpeg-dev \
    tiff-dev \
    libwebp-dev

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

# 第二阶段：运行阶段
FROM python:3.14-alpine

# 安装运行时依赖
RUN apk add --no-cache \
    ffmpeg \
    nodejs \
    npm

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

# 创建FFmpeg软链接目录
RUN mkdir -p /app/ffmpeg/bin \
    && ln -s /usr/bin/ffmpeg /app/ffmpeg/bin/ffmpeg \
    && ln -s /usr/bin/ffprobe /app/ffmpeg/bin/ffprobe

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