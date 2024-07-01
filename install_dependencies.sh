#!/bin/bash

# yt-dlp 依赖 ffmpeg
# https://github.com/yt-dlp/yt-dlp#dependencies

# 判断系统架构
arch=$(uname -m)

pkg="none"
if [[ "${arch}" == "x86_64" ]]; then
	pkg=ffmpeg-master-latest-linux64-gpl
elif [[ "${arch}" == "arm64" ]]; then
	pkg=ffmpeg-master-latest-linuxarm64-gpl
fi

if [[ "${pkg}" != "none" ]]; then
	wget https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/$pkg.tar.xz
	tar -xvJf $pkg.tar.xz
	mv $pkg ffmpeg
else
	apt-get update
	apt-get install -y ffmpeg
	rm -rf /var/lib/apt/lists/*
	mkdir -p /app/ffmpeg/bin
	ln -s /usr/bin/ffmpeg /app/ffmpeg/bin/ffmpeg
	ln -s /usr/bin/ffprobe /app/ffmpeg/bin/ffprobe
fi
