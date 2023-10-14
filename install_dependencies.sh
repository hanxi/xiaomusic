#!/bin/bash

# yt-dlp 依赖 ffmpeg
# https://github.com/yt-dlp/yt-dlp#dependencies

wget https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
tar -xvJf ffmpeg-master-latest-linux64-gpl.tar.xz
mv ffmpeg-master-latest-linux64-gpl ffmpeg
