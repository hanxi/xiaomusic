#!/bin/bash

# yt-dlp 依赖 ffmpeg
# https://github.com/yt-dlp/yt-dlp#dependencies

# 判断系统架构
arch=$(uname -m)

# 输出架构信息
echo "当前系统架构是：$arch"

install_from_build() {
	pkg=$1
	wget https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/$pkg.tar.xz
	tar -xvJf $pkg.tar.xz
	mv $pkg ffmpeg
}

install_from_apt() {
	apt-get update
	apt-get install -y ffmpeg
	rm -rf /var/lib/apt/lists/*
	mkdir -p /app/ffmpeg/bin
	ln -s /usr/bin/ffmpeg /app/ffmpeg/bin/ffmpeg
	ln -s /usr/bin/ffprobe /app/ffmpeg/bin/ffprobe
}

# 基于架构执行不同的操作
case "$arch" in
x86_64)
	echo "64位 x86 架构"
	pkg=ffmpeg-master-latest-linux64-gpl
	install_from_build "$pkg"
	;;
arm64 | aarch64)
	echo "64位 ARM 架构"
	pkg=ffmpeg-master-latest-linuxarm64-gpl
	install_from_build "$pkg"
	;;
*)
	echo "未知架构 $arch"
	install_from_apt
	;;
esac
