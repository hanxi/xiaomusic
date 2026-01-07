FROM python:3.12-alpine3.22

# Install system build dependencies (C/C++/Python/Rust)
RUN apk add --no-cache --virtual .build-deps \
        build-base \
        python3-dev \
        libffi-dev \
        openssl-dev \
        zlib-dev \
        jpeg-dev \
        musl-dev \
        linux-headers \
        curl \
    && apk add --no-cache nodejs npm

# Install Rust via rustup
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Add commonly needed Rust targets for multi-platform builds
RUN rustup target add \
        x86_64-unknown-linux-musl \
        aarch64-unknown-linux-musl \
        armv7-unknown-linux-musleabihf

# Install PDM
RUN pip install -U pdm
ENV PDM_CHECK_UPDATE=false

WORKDIR /app
COPY pyproject.toml README.md package.json ./

# Now pdm install can compile Rust extensions on any platform
RUN pdm install --prod --frozen-lockfile

# Node setup
RUN node -v && npm -v
RUN uname -m
RUN npm config list
RUN npm install --verbose

# Copy app code
COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY holiday/ ./holiday/
COPY xiaomusic.py .
