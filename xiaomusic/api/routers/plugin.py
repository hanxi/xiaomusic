"""插件管理路由"""

import asyncio
import os

import aiofiles
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)

from xiaomusic.api.dependencies import (
    verification,
    xiaomusic,
)

router = APIRouter(dependencies=[Depends(verification)])


@router.get("/api/platforms")
def get_js_plugins():
    """获取平台列表"""
    try:
        if (
            not hasattr(xiaomusic, "js_plugin_manager")
            or not xiaomusic.js_plugin_manager
        ):
            return {"success": False, "error": "JS Plugin Manager not available"}

        platforms = xiaomusic.js_plugin_manager.get_platforms()
        return {"success": True, "data": platforms}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/js-plugins")
def get_js_plugins(
    enabled_only: bool = Query(False, description="是否只返回启用的插件"),
):
    """获取插件列表"""
    try:
        if (
            not hasattr(xiaomusic, "js_plugin_manager")
            or not xiaomusic.js_plugin_manager
        ):
            return {"success": False, "error": "JS Plugin Manager not available"}

        if enabled_only:
            plugins = xiaomusic.js_plugin_manager.get_enabled_plugins()
        else:
            plugins = xiaomusic.js_plugin_manager.refresh_plugin_list()
        return {"success": True, "data": plugins}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.put("/api/js-plugins/{plugin_name}/enable")
def enable_js_plugin(plugin_name: str):
    """启用插件"""
    try:
        if (
            not hasattr(xiaomusic, "js_plugin_manager")
            or not xiaomusic.js_plugin_manager
        ):
            return {"success": False, "error": "JS Plugin Manager not available"}

        success = xiaomusic.js_plugin_manager.enable_plugin(plugin_name)
        return {"success": success}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.put("/api/js-plugins/{plugin_name}/disable")
def disable_js_plugin(plugin_name: str):
    """禁用插件"""
    try:
        if (
            not hasattr(xiaomusic, "js_plugin_manager")
            or not xiaomusic.js_plugin_manager
        ):
            return {"success": False, "error": "JS Plugin Manager not available"}

        success = xiaomusic.js_plugin_manager.disable_plugin(plugin_name)
        return {"success": success}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.delete("/api/js-plugins/{plugin_name}/uninstall")
def uninstall_js_plugin(plugin_name: str):
    """卸载插件"""
    try:
        if (
            not hasattr(xiaomusic, "js_plugin_manager")
            or not xiaomusic.js_plugin_manager
        ):
            return {"success": False, "error": "JS Plugin Manager not available"}

        success = xiaomusic.js_plugin_manager.uninstall_plugin(plugin_name)
        return {"success": success}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/js-plugins/upload")
async def upload_js_plugin(file: UploadFile = File(...)):
    """上传 JS 插件"""
    try:
        # 验证文件扩展名
        if not file.filename.endswith(".js"):
            raise HTTPException(status_code=400, detail="只允许上传 .js 文件")

        # 使用 JSPluginManager 中定义的插件目录
        if (
            not hasattr(xiaomusic, "js_plugin_manager")
            or not xiaomusic.js_plugin_manager
        ):
            raise HTTPException(
                status_code=500, detail="JS Plugin Manager not available"
            )

        plugin_dir = xiaomusic.js_plugin_manager.plugins_dir
        os.makedirs(plugin_dir, exist_ok=True)
        # 校验命名是否是保留字段【ALL/all/OpenAPI】，是的话抛错
        sys_files = ["ALL.js", "all.js", "OpenAPI.js", "OPENAPI.js"]
        if file.filename in sys_files:
            raise HTTPException(
                status_code=409,
                detail=f"插件名非法，不能命名为： {sys_files} ，请修改后再上传！",
            )
        file_path = os.path.join(plugin_dir, file.filename)
        # 校验是否已存在同名js插件 存在则提示，停止上传
        if os.path.exists(file_path):
            raise HTTPException(
                status_code=409,
                detail=f"插件 {file.filename} 已存在，请重命名后再上传！",
            )
        file_path = os.path.join(plugin_dir, file.filename)

        # 写入文件内容
        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        # 更新插件配置文件
        plugin_name = os.path.splitext(file.filename)[0]
        xiaomusic.js_plugin_manager.update_plugin_config(plugin_name, file.filename)

        # 重新加载插件
        xiaomusic.js_plugin_manager.reload_plugins()

        return {"success": True, "message": "插件上传成功"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/js-plugins/import-online")
async def import_online_plugin(request: Request):
    """在线导入 JS 插件"""
    try:
        request_json = await request.json()
        url = request_json.get("url")

        if not url:
            return {"success": False, "error": "请输入插件地址"}

        if not url.startswith(("http://", "https://")):
            return {"success": False, "error": "请输入有效的HTTP地址"}

        if (
            not hasattr(xiaomusic, "js_plugin_manager")
            or not xiaomusic.js_plugin_manager
        ):
            return {"success": False, "error": "JS Plugin Manager not available"}

        import re
        from urllib.parse import urlparse

        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        if not filename.endswith(".js"):
            filename = re.sub(r"[^\w\-]", "_", parsed.netloc) + ".js"

        plugin_name = os.path.splitext(filename)[0]

        sys_files = ["ALL", "all", "OpenAPI", "OPENAPI"]
        if plugin_name in sys_files:
            return {"success": False, "error": f"插件名非法，不能命名为：{sys_files}"}

        success = await asyncio.to_thread(
            xiaomusic.js_plugin_manager.download_single_plugin, plugin_name, url
        )

        if success:
            xiaomusic.js_plugin_manager.reload_plugins()
            return {"success": True, "message": f"插件 {filename} 导入成功"}
        else:
            return {"success": False, "error": "下载或保存插件失败"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ----------------------------LX Server接口相关函数---------------------------------------


@router.get("/api/lxServer/test")
async def get_openapi_info():
    """测试lxServer接口"""
    try:
        return await xiaomusic.js_plugin_manager.test_lx_server()
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/lxServer/load")
def get_openapi_info():
    """获取开放接口配置信息"""
    try:
        lx_server_info = xiaomusic.js_plugin_manager.get_lx_server_info()
        return {"success": True, "data": lx_server_info}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/lxServer/toggle")
def toggle_openapi():
    """开放接口状态切换"""
    try:
        return xiaomusic.js_plugin_manager.toggle_openapi()
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/lxServer/updateUrl")
async def update_openapi_url(request: Request):
    """更新开放接口地址"""
    try:
        request_json = await request.json()
        search_url = request_json.get("search_url")
        if not request_json or "search_url" not in request_json:
            return {"success": False, "error": "Missing 'search_url' in request body"}
        return xiaomusic.js_plugin_manager.update_openapi_url(search_url)
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/lxServer/updatePlatforms")
async def update_lxserver_platforms(request: Request):
    """更新LXServer平台配置"""
    try:
        request_json = await request.json()
        platforms = request_json.get("platforms")
        if platforms is None:
            return {"success": False, "error": "Missing 'platforms' in request body"}
        return xiaomusic.js_plugin_manager.update_lxserver_platforms(platforms)
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/lxServer/updateAuth")
async def update_lxserver_auth(request: Request):
    """更新LXServer认证信息"""
    try:
        request_json = await request.json()
        username = request_json.get("x-user-name")
        token = request_json.get("x-user-token")
        if not username or not token:
            return {
                "success": False,
                "error": "Missing 'x-user-name' or 'x-user-token' in request body",
            }
        return xiaomusic.js_plugin_manager.update_lxserver_auth(username, token)
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/lxServer/userList")
async def get_lxserver_user_list():
    """获取LXServer用户歌单"""
    try:
        lx_server_info = xiaomusic.js_plugin_manager.get_lx_server_info()
        if not lx_server_info.get("base_url"):
            return {"success": False, "error": "LX Server未配置"}
        headers = xiaomusic.js_plugin_manager._build_lx_server_headers(lx_server_info)
        if not headers:
            return {
                "success": False,
                "error": "LX Server认证信息未配置，请先配置用户名和Token",
            }
        return xiaomusic.js_plugin_manager.get_local_lxserver_user_list()
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/lxServer/pullPlaylist")
async def pull_lxserver_playlist():
    """拉取LXServer用户歌单到plugins-config.json"""
    try:
        return await xiaomusic.js_plugin_manager.pull_lxserver_playlist()
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/lxServer/convertPlaylist")
async def convert_lxserver_playlist(
    playlists: str = Query(
        default=None,
        description="指定要转换的歌单名称，多个用逗号分隔。为空则全量转换。可选值：我喜欢的音乐,默认歌单,或userList中的歌单名称",
    ),
):
    """将LXServer歌单转换为xiaomusic格式并保存到setting.json"""
    try:
        target_playlists = None
        if playlists:
            target_playlists = [p.strip() for p in playlists.split(",") if p.strip()]
        return xiaomusic.js_plugin_manager.convert_lxserver_playlist(target_playlists)
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/lxServer/deletePlaylists")
async def delete_lxserver_playlists(request: Request):
    """删除LXServer歌单"""
    try:
        request_json = await request.json()
        delete_list = request_json.get("deleteList", [])
        user_list_indexes = request_json.get("userListIndexes", [])
        return xiaomusic.js_plugin_manager.delete_lxserver_playlists(
            delete_list, user_list_indexes
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/lxServer/clearXiaomusicPlaylists")
async def clear_xiaomusic_playlists():
    """清空xiaomusic中所有_online_lx_前缀的歌单"""
    try:
        return xiaomusic.js_plugin_manager.clear_xiaomusic_playlists()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ----------------------------插件源接口---------------------------------------


@router.get("/api/plugin-source/load")
def get_plugin_source_info():
    """获取插件源配置信息"""
    try:
        plugin_source = xiaomusic.js_plugin_manager.get_plugin_source()
        return {"success": True, "data": plugin_source}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/plugin-source/refresh")
def refresh_plugin_source():
    """更新订阅源"""
    try:
        return xiaomusic.js_plugin_manager.refresh_plugin_source()
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/plugin-source/updateUrl")
async def update_plugin_source(request: Request):
    """更新插件源地址"""
    try:
        request_json = await request.json()
        source_url = request_json.get("source_url")
        if not request_json or "source_url" not in request_json:
            return {"success": False, "error": "Missing 'search_url' in request body"}
        return xiaomusic.js_plugin_manager.update_plugin_source_url(source_url)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ----------------------------后台类型配置接口---------------------------------------
@router.get("/api/back-conf/load")
def get_back_conf_info():
    """获取后台类型配置信息"""
    try:
        back_conf_info = xiaomusic.js_plugin_manager.get_back_conf_info()
        return {"success": True, "data": back_conf_info}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/back-conf/update")
async def update_back_conf(request: Request):
    """更新后台类型配置"""
    try:
        request_json = await request.json()
        api_type = request_json.get("api_type")
        if api_type is None:
            return {"success": False, "error": "Missing 'api_type' in request body"}
        return xiaomusic.js_plugin_manager.update_back_conf_api_type(api_type)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ----------------------------高级配置接口---------------------------------------
@router.get("/api/advanced-config/load")
def get_advanced_config():
    """获取高级配置信息"""
    try:
        advanced_config = xiaomusic.js_plugin_manager.get_advanced_config()
        return {"success": True, "data": advanced_config}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/advanced-config/update")
async def update_advanced_config(request: Request):
    """更新高级配置信息"""
    try:
        request_json = await request.json()
        auto_add_song = request_json.get("auto_add_song")
        auto_convert = request_json.get("auto_convert")
        aiapi_info = request_json.get("aiapi_info")
        voice_playlist_strategy = request_json.get("voice_playlist_strategy")
        return xiaomusic.js_plugin_manager.update_advanced_config(
            auto_add_song, auto_convert, aiapi_info, voice_playlist_strategy
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/box-play-platform/load")
def get_box_play_platform():
    """获取音响口令搜索平台偏好"""
    try:
        platform = xiaomusic.js_plugin_manager.get_box_play_platform_preference()
        platforms = xiaomusic.js_plugin_manager.get_platforms()
        return {
            "success": True,
            "data": {
                "platform": platform,
                "platforms": platforms,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/box-play-platform/update")
async def update_box_play_platform(request: Request):
    """更新口令搜索平台偏好"""
    try:
        request_json = await request.json()
        platform = request_json.get("platform")

        if platform is None:
            return {"success": False, "error": "Missing parameters"}

        return xiaomusic.js_plugin_manager.update_box_play_platform(platform)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ----------------------------密码验证接口---------------------------------------
@router.get("/api/password/check")
def check_password_required():
    """检查是否需要密码验证"""
    try:
        config = xiaomusic.js_plugin_manager._get_config_data()
        password = config.get("password", "")
        return {"success": True, "data": {"required": bool(password)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/password/verify")
async def verify_password(request: Request):
    """验证密码"""
    try:
        request_json = await request.json()
        password = request_json.get("password", "")

        config = xiaomusic.js_plugin_manager._get_config_data()
        stored_password = config.get("password", "")

        if stored_password and password == stored_password:
            return {"success": True}
        else:
            return {"success": False, "error": "密码错误"}
    except Exception as e:
        return {"success": False, "error": str(e)}
