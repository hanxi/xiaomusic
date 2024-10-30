#!/bin/bash

# yt-dlp 依赖 ffmpeg
# https://github.com/yt-dlp/yt-dlp#dependencies

# 判断系统架构
arch=$(uname -m)

# 输出架构信息
echo "当前系统架构是：$arch"

install_from_github() {
	pkg=$1
	wget https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/$pkg.tar.xz
	tar -xvJf $pkg.tar.xz
	mkdir -p ffmpeg/bin
	mv $pkg/bin/ffmpeg ffmpeg/bin/
	mv $pkg/bin/ffprobe ffmpeg/bin/
 	rm -rf $pkg $pkg.tar.xz
}

install_from_ffmpeg() {
	pkg=$1
	wget https://johnvansickle.com/ffmpeg/builds/$pkg.tar.xz
	mkdir -p $pkg
	tar -xvJf $pkg.tar.xz -C $pkg
	mkdir -p ffmpeg/bin
	mv $pkg/*/ffmpeg ffmpeg/bin/
	mv $pkg/*/ffprobe ffmpeg/bin/
 	rm -rf $pkg $pkg.tar.xz
}

# 基于架构执行不同的操作
case "$arch" in
x86_64)
	echo "64位 x86 架构"
	install_from_github ffmpeg-master-latest-linux64-gpl
	#install_from_ffmpeg ffmpeg-git-amd64-static
	;;
arm64 | aarch64)
	echo "64位 ARM 架构"
	install_from_github ffmpeg-master-latest-linuxarm64-gpl
	#install_from_ffmpeg ffmpeg-git-arm64-static
	;;
armv7l)
	echo "armv7l 架构"
	install_from_ffmpeg ffmpeg-git-armhf-static
	;;
*)
	echo "未知架构 $arch"
	;;
esac
