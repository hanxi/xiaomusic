# xiaomusic

使用小爱/红米音箱播放音乐，音乐使用 yt-dlp 下载。

## 运行

- 使用 install_dependencies.sh 下载依赖
- 使用 pdm 安装环境
- 参考 [xiaogpt](https://github.com/yihong0618/xiaogpt) 设置好环境变量

```shell
export MI_USER="xxxxx"
export MI_PASS="xxxx"
export MI_DID=00000
export XIAOMUSIC_SEARCH='bilisearch:'
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

> 隐藏玩法: 对小爱同学说播放歌曲小猪佩奇的故事，会播放小猪佩奇的故事。

## 已测试设备

```txt
"L07A": ("5-1", "5-5"),  # Redmi小爱音箱Play(l7a)
````
## 支持音乐格式

- mp3
- flac

> 本地音乐会搜索 mp3 和 flac 格式的文件，下载的歌曲是 mp3 格式的。

## 其他参数

- XIAOMUSIC_ACTIVE_CMD 环境变量，配置成'play,random_play'，在非播放状态下，只有这两个指令（播放歌曲和随机播放）可以触发，触发后，xiaomusic进入playing状态，其他指令则可以正常触发。

## 在 Docker 里使用

```shell
docker run -e MI_USER=<your-xiaomi-account> -e MI_PASS=<your-xiaomi-password> -e MI_DID=<your-xiaomi-speaker-mid> -e MI_HARDWARE='L07A' -e XIAOMUSIC_PROXY=<proxy-for-yt-dlp> -e XIAOMUSIC_HOSTNAME=192.168.2.5 -e XIAOMUSIC_SEARCH='bilisearch:' -p 8090:8090 -v ./music:/app/music hanxi/xiaomusic
```
- XIAOMUSIC_SEARCH 可以配置为 'bilisearch:' 表示歌曲从哔哩哔哩下载;
    - 配置为 'ytsearch:' 表示歌曲从 youtube 下载。
- XIAOMUSIC_PROXY 用于配置代理，默认为空;
    - 当 XIAOMUSIC_SEARCH 配置为 'ytsearch:' 时在国内需要用到。
- MI_HARDWARE 是小米音箱的型号，默认为'L07A'
- 注意端口必须映射为与容器内一致， XIAOMUSIC_HOSTNAME 需要设置为宿主机的 IP 地址，否则小爱无法正常播放。
- 可以把 /app/music 目录映射到本地，用于保存下载的歌曲。

XIAOMUSIC_PROXY 参数格式参考 yt-dlp 文档说明:
```
Use the specified HTTP/HTTPS/SOCKS proxy. To
enable SOCKS proxy, specify a proper scheme,
e.g. socks5://user:pass@127.0.0.1:1080/.
Pass in an empty string (--proxy "") for
direct connection
```

见 <https://github.com/hanxi/xiaomusic/issues/2> 和 <https://github.com/hanxi/xiaomusic/issues/11>

### 本地编译Docker Image

```shell
docker build -t xiaomusic .
```

### docker compose 示例

使用哔哩哔哩下载歌曲:

```yaml
version: '3'

services:
  xiaomusic:
    image: hanxi/xiaomusic
    container_name: xiaomusic
    restart: unless-stopped
    ports:
      - 8090:8090
    volumes:
      - ./music:/app/music
    environment:
      MI_USER: '小米账号'
      MI_PASS: '小米密码'
      MI_DID: 00000
      MI_HARDWARE: 'L07A'
      XIAOMUSIC_SEARCH: 'bilisearch:'
      XIAOMUSIC_HOSTNAME: '192.168.2.5'
```


使用 youtobe 下载歌曲:

```yaml
version: '3'

services:
  xiaomusic:
    image: hanxi/xiaomusic
    container_name: xiaomusic
    restart: unless-stopped
    ports:
      - 8090:8090
    volumes:
      - ./music:/app/music
    environment:
      MI_USER: '小米账号'
      MI_PASS: '小米密码'
      MI_DID: 00000
      MI_HARDWARE: 'L07A'
      XIAOMUSIC_SEARCH: 'ytsearch:'
      XIAOMUSIC_PROXY: 'http://192.168.2.5:8080'
      XIAOMUSIC_HOSTNAME: '192.168.2.5'
```


## 简易的控制面板

浏览器进入 <http://192.168.2.5:8090>

- ip 是 XIAOMUSIC_HOSTNAME 设置的
- 8090 是默认端口
- 新功能
    - 显示正在播放的歌曲
    - 模糊搜索本地歌曲

## 讨论区

- [点击链接加入QQ频道【xiaomusic】](https://pd.qq.com/s/e2jybz0ss)
- [点击链接加入群聊【xiaomusic】 604526973](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=13St5PLVcTxYlWTAs_iAawazjtdD1l-a&authKey=dJWEpaT2fDBDpdUUOWj%2FLt6NS1ePBfShDfz7a6seNURi05VvVnAGQzXF%2FM%2F5HgIm&noverify=0&group_code=604526973)
- https://github.com/hanxi/xiaomusic/issues

## 感谢

- [xiaomi](https://www.mi.com/)
- [PDM](https://pdm.fming.dev/latest/)
- [xiaogpt](https://github.com/yihong0618/xiaogpt)
- [MiService](https://github.com/yihong0618/MiService)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [NAS部署教程](https://post.m.smzdm.com/p/avpe7n99/)
- [群晖部署教程](https://post.m.smzdm.com/p/a7px7dol/)
- [QNAS部署教程](https://post.smzdm.com/p/a5xz5x63/)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=hanxi/xiaomusic&type=Date)](https://star-history.com/#hanxi/xiaomusic&Date)
