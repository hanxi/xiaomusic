# xiaomusic
[![GitHub License](https://img.shields.io/github/license/hanxi/xiaomusic)](https://github.com/hanxi/xiaomusic)
[![Docker Image Version](https://img.shields.io/docker/v/hanxi/xiaomusic?sort=semver&label=docker%20image)](https://hub.docker.com/r/hanxi/xiaomusic)
[![Docker Pulls](https://img.shields.io/docker/pulls/hanxi/xiaomusic)](https://hub.docker.com/r/hanxi/xiaomusic)
[![PyPI - Version](https://img.shields.io/pypi/v/xiaomusic)](https://pypi.org/project/xiaomusic/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/xiaomusic)](https://pypi.org/project/xiaomusic/)
[![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fhanxi%2Fxiaomusic%2Fmain%2Fpyproject.toml)](https://pypi.org/project/xiaomusic/)
[![GitHub Release](https://img.shields.io/github/v/release/hanxi/xiaomusic)](https://github.com/hanxi/xiaomusic/releases)



使用小爱音箱播放音乐，音乐使用 yt-dlp 下载。

<https://github.com/hanxi/xiaomusic>

> 初次安装遇到问题请查阅 FAQ: <https://github.com/hanxi/xiaomusic/issues/99> 上是否已经有解决办法。

## 最简配置运行

已经支持在 web 页面配置其他参数，docker 启动命令如下:

```bash
docker run -p 8090:8090 -v /xiaomusic/music:/app/music -v /xiaomusic/conf:/app/conf hanxi/xiaomusic
```

对应的 docker compose 配置如下：

```yaml
services:
  xiaomusic:
    image: hanxi/xiaomusic
    container_name: xiaomusic
    restart: unless-stopped
    ports:
      - 8090:8090
    volumes:
      - /xiaomusic/music:/app/music
      - /xiaomusic/conf:/app/conf
```

其中 conf 目录为配置文件存放目录，music 目录为音乐存放目录，建议分开配置为不同的目录。

> 上面配置的 /xiaomusic/music 和 /xiaomusic/conf 是 docker 主机里的 /xiaomusic 目录下的，可以修改为其他目录。如果报错找不到 /xiaomusic/music 目录，可以先执行 `mkdir -p /xiaomusic/{music,conf}` 命令新建目录。

docker 和 docker compose 二选一即可，启动成功后，在 web 页面可以配置其他参数，带有 `*` 号的配置是必须要配置的，其他的用不上时不用修改。初次配置时需要在页面上输入小米账号和密码保存后才能获取到设备列表。

> 目前安装步骤已经是最简化了，如果还是嫌安装麻烦，可以微信或者 QQ 约我远程安装，我一般周末和晚上才有时间，收个辛苦费 :moneybag: 50 元一次，安装失败不收费。

### 修改默认8090端口映射

如果需要修改 8090 端口为其他端口，比如 5678，需要这样配，3个数字都需要是 5678 。见 <https://github.com/hanxi/xiaomusic/issues/19>

```yaml
services:
  xiaomusic:
    image: hanxi/xiaomusic
    container_name: xiaomusic
    restart: unless-stopped
    ports:
      - 5678:5678
    volumes:
      - /xiaomusic/music:/app/music
      - /xiaomusic/conf:/app/conf
    environment:
      XIAOMUSIC_PORT: 5678
```

如果不是首次修改端口，还需要修改 /xiaomusic/conf/setting.json 文件里的端口。

遇到问题可以去 web 设置页面底部点击【下载日志文件】按钮，然后搜索一下日志文件内容确保里面没有账号密码信息后(有就删除这些敏感信息)，然后在提 issues 反馈问题时把下载的日志文件带上。

> 目前除了 XIAOMUSIC_PORT 只能在启动前配置，其他参数都可以在 web 网页里配置。

## pip 方式安装运行

```shell
> pip install -U xiaomusic
> xiaomusic --help
 __  __  _                   __  __                 _
 \ \/ / (_)   __ _    ___   |  \/  |  _   _   ___  (_)   ___
  \  /  | |  / _` |  / _ \  | |\/| | | | | | / __| | |  / __|
  /  \  | | | (_| | | (_) | | |  | | | |_| | \__ \ | | | (__
 /_/\_\ |_|  \__,_|  \___/  |_|  |_|  \__,_| |___/ |_|  \___|
          XiaoMusic v0.3.29 by: github.com/hanxi

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

## 开发环境运行

- 使用 install_dependencies.sh 下载依赖
- 使用 pdm 安装环境
- 默认监听了端口 8090 , 使用其他端口自行修改。

```shell
pdm run xiaomusic.py
````

如果是开发前端界面，可以通过 <http://localhost:8090/docs>
查看有什么接口。目前的 web 控制台非常简陋，欢迎有兴趣的朋友帮忙实现一个漂亮的前端，需要什么接口可以随时提需求。

### 代码提交规范

提交前请执行

```
pdm fmt
pdm lint --fix
```

用于检查代码和格式化代码。

### 本地编译 Docker Image

```shell
docker build -t xiaomusic .
```

### 支持口令

- **播放歌曲**
- **播放歌曲**+歌名 比如：播放歌曲周杰伦晴天
- 下一首
- 单曲循环
- 全部循环
- 随机播放
- 关机
- 停止播放
- 刷新列表
- 播放列表+列表名 比如：播放列表其他
- 加入收藏
- 取消收藏
- 播放列表收藏
- 播放本地歌曲+歌名

> 隐藏玩法: 对小爱同学说播放歌曲小猪佩奇的故事，会播放小猪佩奇的故事。

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

型号与产品名称对照可以在这里查询 <https://home.miot-spec.com/s/xiaomi.wifispeaker>

> 如果你的设备支持播放，请反馈给我添加到支持列表里，谢谢。
> 目前应该所有设备类型都已经支持播放，有问题随时反馈。
> 其他触屏版不能播放可以设置【触屏版兼容模式】选项为 true 试试。见 <https://github.com/hanxi/xiaomusic/issues/30>

## 支持音乐格式

- mp3
- flac
- wav
- ape
- ogg
- m4a

> 本地音乐会搜索目录下上面格式的文件，下载的歌曲是 mp3 格式的。
> 已知 L05B L05C LX06 L16A 不支持 flac 格式。
> 如果格式不能播放可以打开【转换为MP3】和【触屏版兼容模式】选项。具体见 <https://github.com/hanxi/xiaomusic/issues/153#issuecomment-2328168689>


## 简易的控制面板

浏览器进入 <http://192.168.2.5:8090>

- ip 是 XIAOMUSIC_HOSTNAME 设置的
- 8090 是默认端口
- 支持功能
    - 显示正在播放的歌曲
    - 模糊搜索本地歌曲
    - 播放列表
    - 删除歌曲
    - 设置页面
    - 配置网络歌单
    - 日志文件下载

采用新的设置页面之后，没有必须在启动前配置的环境变量了，除非是改默认的 8090 端口才需要配置环境变量。

## 网络歌单功能

可以配置一个 json 格式的歌单，支持电台和歌曲，也可以直接用别人分享的链接，同时配备了 m3u 文件格式转换工具，可以很方便的把 m3u 电台文件转换成网络歌单格式的 json 文件，具体用法见  <https://github.com/hanxi/xiaomusic/issues/78>

> 欢迎有想法的朋友们制作更多的歌单转换工具。

## 更多其他可选配置

- XIAOMUSIC_ACTIVE_CMD 环境变量，对应后台的 【允许唤醒的命令】，用于唤醒口令，配置成'play,random_play'，在非播放状态下，只有这两个指令（播放歌曲和随机播放）可以触发，触发后，xiaomusic进入playing状态，其他指令则可以正常触发。具体见 <https://github.com/hanxi/xiaomusic/pull/43>
- XIAOMUSIC_EXCLUDE_DIRS 配置歌曲目录里需要忽略的目录，对应后台的 【忽略目录】
- XIAOMUSIC_MUSIC_PATH_DEPTH 配置歌曲目录搜索深度，对应后台的 【目录深度】，具体见 <https://github.com/hanxi/xiaomusic/issues/76>
- XIAOMUSIC_DISABLE_HTTPAUTH 配置成 false 表示开启密码访问web控制台，对应后台的 【关闭密码验证】，具体见 <https://github.com/hanxi/xiaomusic/issues/47>
- XIAOMUSIC_HTTPAUTH_USERNAME 配置 web 控制台用户，对应后台的 【web控制台账户】
- XIAOMUSIC_HTTPAUTH_PASSWORD 配置 web 控制台密码，对应后台的 【web控制台密码】
- XIAOMUSIC_CONF_PATH 用来存放配置文件的目录，对应后台的 【配置文件目录】，记得把目录映射到主机，默认为 `/app/config` ，具体见 <https://github.com/hanxi/xiaomusic/issues/74>
- XIAOMUSIC_DISABLE_DOWNLOAD 设为 true 时关闭下载功能，对应后台的 【关闭下载功能】，见 <https://github.com/hanxi/xiaomusic/issues/82>
- XIAOMUSIC_USE_MUSIC_API 设为 true 时使用 player_play_music 接口播放音乐，对应后台的 【触屏版兼容模式】，用于兼容不能播放的型号，如果发现需要设置这个选项的时候请告知我加一下设备型号，方便以后不用设置。 见 <https://github.com/hanxi/xiaomusic/issues/30>
- XIAOMUSIC_KEYWORDS_PLAY 用来播放歌曲的口令前缀，对应后台的 【播放歌曲口令】，默认是 "播放歌曲,放歌曲" ，可以用英文逗号分割配置多个
- XIAOMUSIC_KEYWORDS_STOP 用来关机的口令，对应后台的 【停止口令】，默认是 "关机,暂停,停止" ，可以用英文逗号分割配置多个。
- XIAOMUSIC_KEYWORDS_PLAYLOCAL 用来播放本地歌曲的口令前缀，对应后台的 【播放本地歌曲口令】，本地找不到时不会下载歌曲，默认是 "播放本地歌曲,本地播放歌曲" ，可以用英文逗号分割配置多个。
- XIAOMUSIC_ENABLE_FUZZY_MATCH 设为 true 时开启模糊匹配（默认），设为 false 时关闭模糊匹配，对应后台的 【开启模糊搜索】，支持模糊匹配歌名和歌单名。 具体见 <https://github.com/hanxi/xiaomusic/issues/52>
- XIAOMUSIC_FUZZY_MATCH_CUTOFF 设置模糊搜索匹配的最低相似度阈值（默认0.6，可以配0到1直接的小数），越小越模糊，越大越精准，对应后台的 【模糊匹配阈值】。具体见 <https://github.com/hanxi/xiaomusic/issues/52>
- XIAOMUSIC_PUBLIC_PORT 用于设置外网端口，对应后台的 【外网访问端口】，当使用反向代理时可以设置为外网端口，XIAOMUSIC_HOSTNAME 设为外网IP或者域名即可。
- XIAOMUSIC_DOWNLOAD_PATH 变量可以配置下载目录，默认为空，表示使用 music 目录为下载目录，对应后台的 【音乐下载目录】。设置这个目录必须是 music 的子目录，否则刷新列表后会找不到歌曲。具体见 <https://github.com/hanxi/xiaomusic/issues/98>
- XIAOMUSIC_PROXY 用于配置国内使用 youtube 源下载歌曲时使用的代理，参数格式参考 yt-dlp 文档说明。 见 <https://github.com/hanxi/xiaomusic/issues/2> 和 <https://github.com/hanxi/xiaomusic/issues/11>


### :warning: 安全提醒

- 如果配置了公网访问 xiaomusic ，请一定要开启密码登陆，并设置复杂的密码。且不要在公共场所的 WiFi 环境下使用，否则可能造成小米账号密码泄露。

## 高级篇

- 自定义口令功能 <https://github.com/hanxi/xiaomusic/issues/105>
- [ ] 缺少一篇教程 [如何写自定义插件](https://github.com/hanxi/xiaomusic/issues/105)

## 讨论区

- [点击链接加入QQ频道【xiaomusic】](https://pd.qq.com/s/e2jybz0ss)
- [点击链接加入群聊【xiaomusic】 604526973](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=13St5PLVcTxYlWTAs_iAawazjtdD1l-a&authKey=dJWEpaT2fDBDpdUUOWj%2FLt6NS1ePBfShDfz7a6seNURi05VvVnAGQzXF%2FM%2F5HgIm&noverify=0&group_code=604526973)
- <https://github.com/hanxi/xiaomusic/issues>
- [微信群二维码](https://github.com/hanxi/xiaomusic/issues/86)

## 感谢

- [xiaomi](https://www.mi.com/)
- [PDM](https://pdm.fming.dev/latest/)
- [xiaogpt](https://github.com/yihong0618/xiaogpt)
- [MiService](https://github.com/yihong0618/MiService)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [awesome-xiaoai](https://github.com/zzz6519003/awesome-xiaoai)
- [微信小程序: XIAO晓音](https://github.com/F-loat/xiaoplayer)
- [pure 主题 xiaomusicUI](https://github.com/52fisher/xiaomusicUI)
- 所有帮忙调试和测试的朋友
- 所有反馈问题和建议的朋友

### 其他教程

> 下面教程可能比较旧，只供参考

- [NAS部署教程](https://post.m.smzdm.com/p/avpe7n99/)
- [群晖部署教程](https://post.m.smzdm.com/p/a7px7dol/)
- [QNAS部署教程](https://post.smzdm.com/p/a5xz5x63/)
- [视频教程](https://www.bilibili.com/video/BV1ZZpweHEtT/)
- [TechHive](https://mp.weixin.qq.com/s/4a41muFtPaFKtHeZYu795w)
- [弹个AI](https://mp.weixin.qq.com/s/sIsKxB7Y8b83AhnvaWiMog)
- [简单免费！教你用绿联NAS联动小爱音箱，私人音乐库也能语音点播](https://post.m.smzdm.com/p/a8pldgg7/)


## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=hanxi/xiaomusic&type=Date)](https://star-history.com/#hanxi/xiaomusic&Date)

## 赞赏

- :moneybag: 爱发电 <https://afdian.com/a/imhanxi>
- 点个 Star :star:
- 谢谢 :heart:
- ![喝杯奶茶](https://i.v2ex.co/7Q03axO5l.png)
