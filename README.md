# XiaoMusic: 无限听歌，解放小爱音箱

[![GitHub License](https://img.shields.io/github/license/hanxi/xiaomusic)](https://github.com/hanxi/xiaomusic)
[![Docker Image Version](https://img.shields.io/docker/v/hanxi/xiaomusic?sort=semver&label=docker%20image)](https://hub.docker.com/r/hanxi/xiaomusic)
[![Docker Pulls](https://img.shields.io/docker/pulls/hanxi/xiaomusic)](https://hub.docker.com/r/hanxi/xiaomusic)
[![PyPI - Version](https://img.shields.io/pypi/v/xiaomusic)](https://pypi.org/project/xiaomusic/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/xiaomusic)](https://pypi.org/project/xiaomusic/)
[![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fhanxi%2Fxiaomusic%2Fmain%2Fpyproject.toml)](https://pypi.org/project/xiaomusic/)
[![GitHub Release](https://img.shields.io/github/v/release/hanxi/xiaomusic)](https://github.com/hanxi/xiaomusic/releases)
[![Visitors](https://api.visitorbadge.io/api/daily?path=hanxi%2Fxiaomusic&label=daily%20visitor&countColor=%232ccce4&style=flat)](https://visitorbadge.io/status?path=hanxi%2Fxiaomusic)
[![Visitors](https://api.visitorbadge.io/api/visitors?path=hanxi%2Fxiaomusic&label=total%20visitor&countColor=%232ccce4&style=flat)](https://visitorbadge.io/status?path=hanxi%2Fxiaomusic)

使用小爱音箱播放音乐，音乐使用 yt-dlp 下载。

<https://github.com/hanxi/xiaomusic>

> [!TIP]
> 初次安装遇到问题请查阅 [💬 FAQ问题集合](https://github.com/hanxi/xiaomusic/issues/99) ，一般遇到的问题都已经有解决办法。

## 👋 最简配置运行

已经支持在 web 页面配置其他参数，docker 启动命令如下:

```bash
docker run -p 58090:8090 -e XIAOMUSIC_PUBLIC_PORT=58090 -v /xiaomusic_music:/app/music -v /xiaomusic_conf:/app/conf hanxi/xiaomusic
```

🔥 国内：

```bash
docker run -p 58090:8090 -e XIAOMUSIC_PUBLIC_PORT=58090 -v /xiaomusic_music:/app/music -v /xiaomusic_conf:/app/conf m.daocloud.io/docker.io/hanxi/xiaomusic
```

对应的 docker compose 配置如下：

```yaml
services:
  xiaomusic:
    image: hanxi/xiaomusic
    container_name: xiaomusic
    restart: unless-stopped
    ports:
      - 58090:8090
    environment:
      XIAOMUSIC_PUBLIC_PORT: 58090
    volumes:
      - /xiaomusic_music:/app/music
      - /xiaomusic_conf:/app/conf
```

🔥 国内：

```yaml
services:
  xiaomusic:
    image: m.daocloud.io/docker.io/hanxi/xiaomusic
    container_name: xiaomusic
    restart: unless-stopped
    ports:
      - 58090:8090
    environment:
      XIAOMUSIC_PUBLIC_PORT: 58090
    volumes:
      - /xiaomusic_music:/app/music
      - /xiaomusic_conf:/app/conf
```

- 其中 conf 目录为配置文件存放目录，music 目录为音乐存放目录，建议分开配置为不同的目录。
- /xiaomusic_music 和 /xiaomusic_conf 是 docker 主机里的目录，可以修改为其他目录。如果报错找不到 /xiaomusic_music 目录，可以先执行 `mkdir -p /xiaomusic_{music,conf}` 命令新建目录。
- XIAOMUSIC_PUBLIC_PORT 是用来配置 NAS 本地端口的。8090 是容器端口，不要去修改。
- 后台访问地址为： http://NAS_IP:58090

> [!NOTE]
> docker 和 docker compose 二选一即可，启动成功后，在 web 页面可以配置其他参数，带有 `*` 号的配置是必须要配置的，其他的用不上时不用修改。初次配置时需要在页面上输入小米账号和密码保存后才能获取到设备列表。

> [!TIP]
> 目前安装步骤已经是最简化了，如果还是嫌安装麻烦，可以微信或者 QQ 约我远程安装，我一般周末和晚上才有时间，收个辛苦费 :moneybag: 50 元一次，安装失败不收费。

遇到问题可以去 web 设置页面底部点击【下载日志文件】按钮，然后搜索一下日志文件内容确保里面没有账号密码信息后(有就删除这些敏感信息)，然后在提 issues 反馈问题时把下载的日志文件带上。

> [!TIP]
> 海外 RackNerd VPS 机器推荐，可支付宝付款。
> - [🔥1 GB KVM VPS $11.29/年](https://my.racknerd.com/aff.php?aff=1177&pid=903)
> - [2 GB KVM VPS](https://my.racknerd.com/aff.php?aff=1177&pid=904)
> - [3.5 GB KVM VPS](https://my.racknerd.com/aff.php?aff=1177&pid=905)
> - [4 GB KVM VPS](https://my.racknerd.com/aff.php?aff=1177&pid=906)
> - [6 GB KVM VPS](https://my.racknerd.com/aff.php?aff=1177&pid=907)

### 🤐 支持语音口令

- 【播放歌曲】，播放本地的歌曲
- 【播放歌曲+歌名】，比如：播放歌曲周杰伦晴天
- 【上一首】
- 【下一首】
- 【单曲循环】
- 【全部循环】
- 【随机播放】
- 【关机】，【停止播放】，两个效果是一样的。
- 【刷新列表】，当复制了歌曲进 music 目录后，可以用这个口令刷新歌单。
- 【播放列表+列表名】，比如：播放列表其他。
- 【加入收藏】，把当前播放的歌曲加入收藏歌单。
- 【取消收藏】，把当前播放的歌曲从收藏歌单里移除。
- 【播放列表收藏】，这个用于播放收藏歌单。
- 【播放本地歌曲+歌名】，这个口令和播放歌曲的区别是本地找不到也不会去下载。
- 【播放列表第几个+列表名】，具体见： <https://github.com/hanxi/xiaomusic/issues/158>
- 【搜索播放+关键词】，会搜索关键词作为临时搜索列表播放，比如说【搜索播放林俊杰】，会播放所有林俊杰的歌。
- 【本地搜索播放+关键词】，跟搜索播放的区别是本地找不到也不会去下载。

> [!TIP]
> 隐藏玩法: 对小爱同学说播放歌曲小猪佩奇的故事，会先下载小猪佩奇的故事，然后再播放小猪佩奇的故事。

## 🛠️ pip 方式安装运行

```shell
> pip install -U xiaomusic
> xiaomusic --help
 __  __  _                   __  __                 _
 \ \/ / (_)   __ _    ___   |  \/  |  _   _   ___  (_)   ___
  \  /  | |  / _` |  / _ \  | |\/| | | | | | / __| | |  / __|
  /  \  | | | (_| | | (_) | | |  | | | |_| | \__ \ | | | (__
 /_/\_\ |_|  \__,_|  \___/  |_|  |_|  \__,_| |___/ |_|  \___|
          XiaoMusic v0.3.65 by: github.com/hanxi

usage: xiaomusic [-h] [--port PORT] [--hardware HARDWARE] [--account ACCOUNT]
                 [--password PASSWORD] [--cookie COOKIE] [--verbose]
                 [--config CONFIG] [--ffmpeg_location FFMPEG_LOCATION]

options:
  -h, --help            show this help message and exit
  --port PORT           监听端口
  --hardware HARDWARE   小爱音箱型号
  --account ACCOUNT     xiaomi account
  --password PASSWORD   xiaomi password
  --cookie COOKIE       xiaomi cookie
  --verbose             show info
  --config CONFIG       config file path
  --ffmpeg_location FFMPEG_LOCATION
                        ffmpeg bin path
> xiaomusic --config config.json
```

其中 `config.json` 文件可以参考 `config-example.json` 文件配置。见 <https://github.com/hanxi/xiaomusic/issues/94>

不修改默认端口 8090 的情况下，只需要执行 `xiaomusic` 即可启动。

## 🔩 开发环境运行

- 使用 install_dependencies.sh 下载依赖
- 使用 pdm 安装环境
- 默认监听了端口 8090 , 使用其他端口自行修改。

```shell
pdm run xiaomusic.py
````

如果是开发前端界面，可以通过 <http://localhost:8090/docs>
查看有什么接口。目前的 web 控制台非常简陋，欢迎有兴趣的朋友帮忙实现一个漂亮的前端，需要什么接口可以随时提需求。

### 🚦 代码提交规范

提交前请执行

```
pdm lintfmt
```

用于检查代码和格式化代码。

### 本地编译 Docker Image

```shell
docker build -t xiaomusic .
```

### 技术栈

- 后端代码使用 Python 语言编写。
- HTTP 服务使用的是 FastAPI 框架，~~早期版本使用的是 Flask~~。
- 使用了 Docker ，在 NAS 上安装更方便。
- 默认的前端主题使用了 jQuery 。

## 已测试支持的设备

| 型号   | 名称                                                                                             |
| ---- | ---------------------------------------------------------------------------------------------- |
| L06A | [小爱音箱](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l06a)             |
| L07A | [Redmi小爱音箱 Play](https://home.mi.com/webapp/content/baike/product/index.html?model=xiaomi.wifispeaker.l7a)                     |
| S12/S12A/MDZ-25-DA | [小米AI音箱](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.s12)            |
| LX5A | [小爱音箱 万能遥控版](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.lx5a)       |
| LX05 | [小爱音箱Play（2019款）](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.lx05)  |
| L15A | [小米AI音箱（第二代）](https://home.mi.com/webapp/content/baike/product/index.html?model=xiaomi.wifispeaker.l15a#/) |
| L16A | [Xiaomi Sound](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l16a)     |
| L17A | [Xiaomi Sound Pro](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l17a) |
| LX06 | [小爱音箱Pro](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.lx06)          |
| LX01 | [小爱音箱mini](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.lx01)         |
| L05B | [小爱音箱Play](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l05b)         |
| L05C | [小米小爱音箱Play 增强版](https://home.mi.com/baike/index.html#/detail?model=xiaomi.wifispeaker.l05c)   |
| L09A | [小米音箱Art](https://home.mi.com/webapp/content/baike/product/index.html?model=xiaomi.wifispeaker.l09a) |
| LX04 X10A X08A | 已经支持的触屏版 |
| X08C X08E X8F | 需要设置【型号兼容模式】选项为 true |
| M01/XMYX01JY | 小米小爱音箱HD 需要设置【特殊型号获取对话记录】选项为 true 才能语音播放|

型号与产品名称对照可以在这里查询 <https://home.miot-spec.com/s/xiaomi.wifispeaker>

> [!NOTE]
> 如果你的设备支持播放，请反馈给我添加到支持列表里，谢谢。
> 目前应该所有设备类型都已经支持播放，有问题随时反馈。
> 其他触屏版不能播放可以设置【型号兼容模式】选项为 true 试试。见 <https://github.com/hanxi/xiaomusic/issues/30>

## 🎵 支持音乐格式

- mp3
- flac
- wav
- ape
- ogg
- m4a

> [!NOTE]
> 本地音乐会搜索目录下上面格式的文件，下载的歌曲是 mp3 格式的。
> 已知 L05B L05C LX06 L16A 不支持 flac 格式。
> 如果格式不能播放可以打开【转换为MP3】和【型号兼容模式】选项。具体见 <https://github.com/hanxi/xiaomusic/issues/153#issuecomment-2328168689>

## 🌏 网络歌单功能

可以配置一个 json 格式的歌单，支持电台和歌曲，也可以直接用别人分享的链接，同时配备了 m3u 文件格式转换工具，可以很方便的把 m3u 电台文件转换成网络歌单格式的 json 文件，具体用法见  <https://github.com/hanxi/xiaomusic/issues/78>

> [!NOTE]
> 欢迎有想法的朋友们制作更多的歌单转换工具。

## 🍺 更多其他可选配置

见 <https://github.com/hanxi/xiaomusic/issues/333>

## ⚠️ 安全提醒

> [!IMPORTANT]
>
> 1. 如果配置了公网访问 xiaomusic ，请一定要开启密码登陆，并设置复杂的密码。且不要在公共场所的 WiFi 环境下使用，否则可能造成小米账号密码泄露。
> 2. 强烈不建议将小爱音箱的小米账号绑定摄像头，代码难免会有 bug ，一旦小米账号密码泄露，可能监控录像也会泄露。

## 🤔 高级篇

- 自定义口令功能 <https://github.com/hanxi/xiaomusic/issues/105>
- [ ] 缺少一篇教程 [如何写自定义插件](https://github.com/hanxi/xiaomusic/issues/105)

## 📢 讨论区

- [点击链接加入QQ频道【xiaomusic】](https://pd.qq.com/s/e2jybz0ss)
- [点击链接加入群聊【xiaomusic】 604526973](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=13St5PLVcTxYlWTAs_iAawazjtdD1l-a&authKey=dJWEpaT2fDBDpdUUOWj%2FLt6NS1ePBfShDfz7a6seNURi05VvVnAGQzXF%2FM%2F5HgIm&noverify=0&group_code=604526973)
- <https://github.com/hanxi/xiaomusic/issues>
- [微信群二维码](https://github.com/hanxi/xiaomusic/issues/86)

## ❤️ 感谢

- [xiaomi](https://www.mi.com/)
- [PDM](https://pdm.fming.dev/latest/)
- [xiaogpt](https://github.com/yihong0618/xiaogpt)
- [MiService](https://github.com/yihong0618/MiService)
- [实现原理](https://github.com/yihong0618/gitblog/issues/258)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [awesome-xiaoai](https://github.com/zzz6519003/awesome-xiaoai)
- [微信小程序: XIAO晓音](https://github.com/F-loat/xiaoplayer)
- [pure 主题 xiaomusicUI](https://github.com/52fisher/xiaomusicUI)
- [移动端的播放器主题](https://github.com/52fisher/XMusicPlayer)
- [一个第三方的主题](https://github.com/DarrenWen/xiaomusicui)
- [Umami 统计](https://github.com/umami-software/umami)
- [Sentry 报错监控](https://github.com/getsentry/sentry)
- 所有帮忙调试和测试的朋友
- 所有反馈问题和建议的朋友

### 👉 其他教程

更多功能见 [📝 文档汇总](https://github.com/hanxi/xiaomusic/issues/211)

## 🚨 免责声明

本项目仅供学习和研究目的，不得用于任何商业活动。用户在使用本项目时应遵守所在地区的法律法规，对于违法使用所导致的后果，本项目及作者不承担任何责任。
本项目可能存在未知的缺陷和风险（包括但不限于设备损坏和账号封禁等），使用者应自行承担使用本项目所产生的所有风险及责任。
作者不保证本项目的准确性、完整性、及时性、可靠性，也不承担任何因使用本项目而产生的任何损失或损害责任。
使用本项目即表示您已阅读并同意本免责声明的全部内容。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=hanxi/xiaomusic&type=Date)](https://star-history.com/#hanxi/xiaomusic&Date)

## 赞赏

- :moneybag: 爱发电 <https://afdian.com/a/imhanxi>
- 点个 Star :star:
- 谢谢 :heart:
- ![喝杯奶茶](https://i.v2ex.co/7Q03axO5l.png)

## License

[MIT](https://github.com/hanxi/xiaomusic/blob/main/LICENSE) License © 2024 涵曦
