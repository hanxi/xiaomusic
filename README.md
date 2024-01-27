# xiaomusic

使用小爱同学播放音乐，音乐使用 yt-dlp 下载。

## 运行

- 使用 install_dependencies.sh 下载依赖
- 使用 pdm 安装环境
- 参考 [xiaogpt](https://github.com/yihong0618/xiaogpt) 设置好环境变量

```shell
export MI_USER="xxxxx"
export MI_PASS="xxxx"
export MI_DID=00000
```

然后启动即可。默认监听了端口 8090 , 使用其他端口自行修改。

```shell
pdm run xiaomusic.py
````

### 支持口令

- **播放歌曲**
- **播放歌曲**+歌名 比如：播放歌曲周杰伦晴天
- 下一首
- 单曲循环
- 全部循环

## 已测试设备

```txt
"L07A": ("5-1", "5-5"),  # Redmi小爱音箱Play(l7a)
````
## 支持音乐格式

- mp3
- flac

> 本地音乐会搜索 mp3 和 flac 格式的文件，下载的歌曲是 mp3 格式的。

## 在 Docker 里使用

```shell
docker run -e MI_USER=<your-xiaomi-account> -e MI_PASS=<your-xiaomi-password> -e MI_DID=<your-xiaomi-speaker-mid> -e MI_HARDWARE='L07A' -e XIAOMUSIC_PROXY=<proxy-for-yt-dlp> -e XIAOMUSIC_HOSTNAME=192.168.2.5 -p 8090:8090 -v ./music:/app/music hanxi/xiaomusic
```

- XIAOMUSIC_PROXY 用于配置代理，默认为空，yt-dlp 工具下载歌曲会用到。
- MI_HARDWARE 是小米音箱的型号，默认为'L07A'
- 注意端口必须映射为与容器内一致，XIAOMUSIC_HOSTNAME 需要设置为宿主机的 IP 地址，否则小爱无法正常播放。
- 可以把 /app/music 目录映射到本地，用于保存下载的歌曲。

### 本地编译Docker Image

```shell
docker build -t xiaomusic .
```

## 感谢

- [xiaomi](https://www.mi.com/)
- [PDM](https://pdm.fming.dev/latest/)
- [xiaogpt](https://github.com/yihong0618/xiaogpt)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)

