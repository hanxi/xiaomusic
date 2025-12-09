#!/bin/bash

# wsl-proxy.sh - 在 WSL2 中自动配置使用 Windows 主机上的代理（端口 7890）

set -e

# Windows 代理端口（默认 Clash/V2Ray 常用端口）
PROXY_PORT=7890

# 获取 Windows 主机 IP（WSL2 中通过 /etc/ressov.conf 的 nameserver）
WIN_HOST=$(cat /etc/resolv.conf | grep "nameserver" | awk '{print $2}' | head -n1)

if [ -z "$WIN_HOST" ]; then
    echo "❌ 无法获取 Windows 主机 IP，请检查 /etc/resolv.conf"
    exit 1
fi

PROXY_URL="http://$WIN_HOST:$PROXY_PORT"

NO_PROXY="localhost,127.0.0.1,::1,$WIN_HOST"

# 函数：启用代理
enable_proxy() {
    echo "🌐 Windows 主机 IP: $WIN_HOST"
    echo "🔌 代理地址: $PROXY_URL"

    # 设置环境变量（当前 shell 生效）
    export http_proxy="$PROXY_URL"
    export https_proxy="$PROXY_URL"
    export no_proxy="$NO_PROXY"

    # 永久写入 ～/.bashrc（可选，取消注释下面几行）
    # grep -q "export http_proxy" ～/.bashrc || echo "export http_proxy=$PROXY_URL" >> ～/.bashrc
    # grep -q "export https_proxy" ～/.bashrc || echo "export https_proxy=$PROXY_URL" >> ～/.bashrc
    # grep -q "export no_proxy" ～/.bashrc || echo "export no_proxy=$NO_PROXY" >> ～/.bashrc

    # 配置 Git
    git config --global http.proxy "$PROXY_URL"
    git config --global https.proxy "$PROXY_URL"

    # 配置 APT（Debian/Ubuntu）
    echo 'Acquire::http::Proxy "'"$PROXY_URL"'";' | sudo tee /etc/apt/apt.conf.d/80proxy > /dev/null
    echo 'Acquire::https::Proxy "'"$PROXY_URL"'";' | sudo tee -a /etc/apt/apt.conf.d/80proxy > /dev/null

    # 配置 NPM（如果已安装）
    if command -v npm &> /dev/null; then
        npm config set proxy "$PROXY_URL"
        npm config set https-proxy "$PROXY_URL"
    fi

    echo "✅ 代理已启用！"
}

# 函数：禁用代理
disable_proxy() {
    unset http_proxy
    unset https_proxy
    unset no_proxy

    # 取消 Git 代理
    git config --global --unset http.proxy
    git config --global --unset https.proxy

    # 删除 APT 代理配置
    sudo rm -f /etc/apt/apt.conf.d/80proxy

    # 清除 NPM 代理（如果存在）
    if command -v npm &> /dev/null; then
        npm config delete proxy
        npm config delete https-proxy
    fi

    # 从 ～/.bashrc 中移除（如果之前写入过）
    sed -i '/export http_proxy/d' ～/.bashrc
    sed -i '/export https_proxy/d' ～/.bashrc
    sed -i '/export no_proxy/d' ～/.bashrc

    echo "🚫 代理已禁用！"
}

# 主逻辑
case "$1" in
    enable|on)
        enable_proxy
        ;;
    disable|off)
        disable_proxy
        ;;
    status)
        echo "当前代理状态："
        echo "http_proxy:  ${http_proxy:-未设置}"
        echo "https_proxy: ${https_proxy:-未设置}"
        echo "no_proxy:     ${no_proxy:-未设置}"
        echo "Windows Host: $WIN_HOST"
        ;;
    *)
        echo "用法: $0 {enable|disable|status}"
        echo "示例: $0 enable   # 启用代理"
        echo "      $0 disable  # 禁用代理"
        echo "      $0 status   # 查看状态"
        exit 1
        ;;
esac
