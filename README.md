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

## 感谢

- [xiaomi](https://www.mi.com/)
- [PDM](https://pdm.fming.dev/latest/)
- [xiaogpt](https://github.com/yihong0618/xiaogpt)

