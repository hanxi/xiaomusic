#!/bin/bash

# yt-dlp 依赖 ffmpeg
# https://github.com/yt-dlp/yt-dlp#dependencies

# 判断系统架构
arch=$(arch)

pkg=ffmpeg-master-latest-linuxarm64-gpl
if [[ "${arch}" == "x86_64" ]]; then
	pkg=ffmpeg-master-latest-linux64-gpl
fi

#export ALL_PROXY=http://192.168.2.5:8080
wget https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/$pkg.tar.xz
tar -xvJf $pkg.tar.xz
mv $pkg ffmpeg
