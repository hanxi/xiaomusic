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

1. **MusicFree插件支持**:（需自行获取音源） 集成 MusicFree 的 JS 插件系统，支持多种音乐源
2. **开放接口支持**:(默认启用) 支持通过TuneFree API进行音乐搜索和播放
3. **插件管理**: 提供插件启用/禁用/卸载等功能
4. **自动追加歌曲功能**:(默认未启用) 播放到歌单末尾时自动搜索并播放相同歌手的歌曲
5. **用户口令智能提取**（默认未启用）: 支持对用户语音指令的智能分析，自动提取歌名、歌手名（需用户配置AI API密钥，默认不启用）

#### 调用策略
- 调用策略：
  - 配置了开放接口且启用，只调用开放接口。
  - 未配置或启用接口时，会调用MusicFree插件搜索（需导入且启用）
- 搜索结果优先级规则：
  - 【歌曲名】>【歌手名】>【插件平台权重】
  - 插件平台权重（启用插件列表中前9个插件，排名越靠前权重越高，最高9分）

## 🔧 新增功能介绍

### 🤐 新增语音口令
- 【在线播放+关键词(歌手/歌曲名组合)】，会直接调用接口或插件，搜索关键词,返回匹配后的第一个资源进行播放。比如说：【在线播放】林俊杰||江南||林俊杰+江南。
- 【播放歌手+歌手名】，会在线搜索该歌手的歌曲并创建歌单进行播放。比如说：【播放歌手：陈奕迅】。

### WEB端搜索、配置
- 支持网页端搜索/播放歌曲及推送小爱音响(部分MusicFree插件获取的资源小爱音响不适用，如Bilibili插件)
- 支持网页端管理插件、接口
- 支持歌曲列表的全部推送功能

### JS插件管理
- 支持加载和管理 MusicFree JS 插件
- 提供插件导入/启用/禁用/卸载功能
- 支持插件配置文件管理

### 开放接口支持
- 集成TuneFree API接口
- 支持在线搜索和播放
- 可配置开放接口地址

## 👨‍💻 最简Docker配置

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

## ✨高级功能

### 用户口令智能提取
- 默认不启用，需用户主动配置API密钥后方可使用
- 使用AI大模型分析用户语音指令，自动提取歌曲名和歌手名信息
- 启用后会提高搜索精确的，非必须

### 自动追加歌曲功能
- 当播放到歌单最后一首歌时，可设置是否追加相同歌手的歌曲(默认未启用，仅【全部播放】模式适用）
- 默认未启用，只会根据当前歌单播放，不会自动搜索、添加歌曲

### 配置示例：

`** /conf/plugins-config.json` 文件配置如下：

```json
{
  ......
  // 启用自动添加歌曲功能
  "auto_add_song": true,

  // OpenAI 兼容 API 配置（支持阿里百炼、质谱 AI 等符合 OpenAI API 规范的大模型）
  "aiapi_info": {
    // OpenAI API 的基础 URL（默认指向阿里百炼）
    "base_url": "",
    // API 密钥
    "api_key": "API密钥",
    // 使用的模型名称（默认 qwen-flash，当前配置为 qwen-plus）
    "model": "qwen-plus",
    // 是否启用 AI 功能
    "enabled": true
  },

  ......
}
```

## 📋 待办优化项

- [x] 歌手列表播放: 指定歌手名播放，可随机播放该歌手的列表歌曲【播放歌手：陈奕迅】。
- [x] 智能续播: 指定歌名播放完毕后，可随机播放这个歌手的其他歌曲、或类似风格歌曲（当前会单曲循环）。
- [x] 指令播放优化: 当前会在排序后取第一个资源播放，但可能取到的非最佳项。应考虑优化。（使用AI提取关键字）
- [ ] 播放链接优化: 接口或插件可能会返回加密音乐的播放地址（.qmc .mflac .mgg .kwm），应将其排除。
- [ ] 搜索源优化: 将开放接口与插件平台融合展示，方便用户手动指定搜索源
- [ ] 播放失效替换: 某个歌曲播放链接失效，如果配置了其他源，进行自动切换。

## 写在最后
本项目只是因个人兴趣和家人需要进行的简单二开。如果您有好的建议或问题，欢迎在 GitHub 上提交 issue。但本人不保证会对项目长期、持续的更新和全方位支持响应，建议自行fork进行定制开发。
