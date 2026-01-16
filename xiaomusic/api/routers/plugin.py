"""插件管理路由"""

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


# ----------------------------开放接口相关函数---------------------------------------


@router.get("/api/openapi/load")
def get_openapi_info():
    """获取开放接口配置信息"""
    try:
        openapi_info = xiaomusic.js_plugin_manager.get_openapi_info()
        return {"success": True, "data": openapi_info}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/openapi/toggle")
def toggle_openapi():
    """开放接口状态切换"""
    try:
        return xiaomusic.js_plugin_manager.toggle_openapi()
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/openapi/updateUrl")
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
