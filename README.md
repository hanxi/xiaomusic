# XiaoMusic-Online: Xiaomusic在线版

对XiaoMusic项目进行了二次开发，增加了开放接口和MusicFree插件调用能力，可实现在线搜索、播放歌曲功能。

原项目: <https://github.com/hanxi/xiaomusic>

当前项目: <https://github.com/boluofan/xiaomusic-online>

原项目文档: <https://xdocs.hanxi.cc/>

> [!TIP]
> 初次安装遇到问题请查阅 [💬 FAQ问题集合](https://github.com/hanxi/xiaomusic/issues/99) ，一般遇到的问题都已经有解决办法。

## 🙏 致敬

- **原项目**: 本项目基于 [hanxi/xiaomusic](https://github.com/hanxi/xiaomusic) 进行开发，感谢原作者的支持
- **MusicFree项目**: 集成了 [MusicFree](https://github.com/maotoumao/MusicFree) 的JS插件功能，感谢其开源贡献
- **开放接口**: 集成了 [TuneFree API](https://api.tunefree.fun/) 开放接口，感谢其提供了更丰富的音乐接口

## 🚀 扩展功能与实现逻辑

### 扩展功能概述
本项目在原版 xiaomusic 基础上，增加了以下扩展功能：

1. **JS插件支持**: 集成 MusicFree 的 JS 插件系统，支持多种音乐源
2. **开放接口集成**: 支持通过开放接口获取音乐资源
3. **智能搜索排序**: 基于匹配度的搜索结果优化排序
4. **插件管理**: 提供插件启用/禁用/卸载等功能

### 实现逻辑
- 通过 [JSPluginManager](file://C:\dev\boluofan\xiaomusic-online\xiaomusic\js_plugin_manager.py#L16-L999) 类管理 JS 插件
- 使用 Node.js 子进程运行 JS 插件代码
- 提供 [search](file://C:\dev\boluofan\xiaomusic-online\xiaomusic\js_plugin_runner.js#L261-L322)、[get_media_source](file://C:\dev\boluofan\xiaomusic-online\xiaomusic\httpserver.py#L291-L301)、[get_lyric](file://C:\dev\boluofan\xiaomusic-online\xiaomusic\js_plugin_manager.py#L641-L658) 等接口与插件交互
- 支持调用开放接口[TuneFree API](https://api.tunefree.fun/)直接获取音乐数据（高优先级）
- 通过匹配度算法优化搜索结果排序（多插件混合搜索场景）
#### 调用策略
- 调用策略：
  - 配置了开放接口且启用，只调用开放接口。
  - 未配置或启用接口时，会调用MusicFree插件搜索（需存在且启用）
- MusicFree插件搜索结果，优先级规则：
  - 【歌手名】与关键字匹配度（完全匹配1000分，开头匹配800分，部分匹配600分）
  - 【歌曲名】与关键字匹配度（完全匹配400分，开头匹配300分，部分匹配200分）
  - 插件平台权重（启用插件列表中前9个插件，排名越靠前权重越高，最高9分）

## 🔧 新增功能介绍

### WEB端搜索、配置
- 支持网页端搜索/播放歌曲及推送小爱音响(部分MusicFree获取的资源类型小爱不适用)
- 支持网页端管理插件、接口

### JS插件管理
- 支持加载和管理 MusicFree JS 插件
- 提供插件导入/启用/禁用/卸载功能
- 支持插件配置文件管理

### 开放接口支持
- 集成外部音乐API接口
- 支持在线搜索和播放
- 可配置开放接口地址

### 智能搜索排序
- 根据歌曲名、艺术家匹配度排序
- 支持按平台优先级排序
- 提供更精准的搜索结果

### 语音指令扩展
- 新增【在线播放】语音控制指令

## 👨‍💻 最简配置运行

已经支持在 web 页面配置其他参数，docker 启动命令如下:

```bash
docker run -d \
  --name xiaomusic-online \
  --restart unless-stopped \
  -p 58090:8090 \
  -e XIAOMUSIC_PUBLIC_PORT=58090 \
  -e TZ=Asia/Shanghai \
  -v /vol1/1000/**/music:/app/music \
  -v /vol1/1000/**/conf:/app/conf \
  -v /vol1/1000/**/logs:/app/logs \
  boluofandocker/xiaomusic-online
```

对应的 docker compose 配置如下：

```yaml
services:
  xiaomusic-online:
    image: boluofandocker/xiaomusic-online
    container_name: xiaomusic-online
    restart: unless-stopped
    ports:
      - "58090:8090"
    environment:
      - XIAOMUSIC_PUBLIC_PORT=58090
      - TZ=Asia/Shanghai
    volumes:
      - /vol1/1000/**/music:/app/music
      - /vol1/1000/**/conf:/app/conf
      - /vol1/1000/**/logs:/app/logs
```
- /vol1/1000/**/ 是 docker 所在的主机的真实目录，需根据自身修改

### 🤐 新增语音口令

- 【播放/在线播放+关键词(歌手、歌曲名)】，会直接调用接口或插件，搜索关键词,返回匹配后的第一个资源进行播放。比如说：【播放】林俊杰||江南||林俊杰+江南。

## 📋 待办优化项

- [ ] 歌手列表播放: 指定歌手名播放，可随机播放该歌手的列表歌曲【播放歌手：陈奕迅】。
- [ ] 智能续播: 指定歌名播放完毕后，可随机播放这个歌手的其他歌曲、或类似风格歌曲（当前会单曲循环）。
- [ ] 播放链接优化: 接口或插件可能会返回加密音乐的播放地址（.qmc .mflac .mgg .kwm），应将其排除。
- [ ] 指令播放优化: 当前会在排序后取第一个资源播放，但可能取到的非最佳项。应考虑优化。

## 写在最后
本项目只是因个人兴趣和家人需要进行的简单二开。如果您有好的建议或问题，欢迎在 GitHub 上提交 issue。但本人不保证会对项目长期、持续的更新和全方位支持响应，建议自行fork进行定制开发。
