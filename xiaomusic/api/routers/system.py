"""系统管理路由"""

import json
import os
import shutil
import tempfile
from dataclasses import (
    asdict,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
)
from fastapi.openapi.utils import (
    get_openapi,
)
from fastapi.responses import (
    FileResponse,
)
from starlette.background import (
    BackgroundTask,
)

from xiaomusic import (
    __version__,
)
from xiaomusic.api.dependencies import (
    config,
    log,
    verification,
    xiaomusic,
)
from xiaomusic.utils import (
    deepcopy_data_no_sensitive_info,
    get_latest_version,
    restart_xiaomusic,
    update_version,
)

router = APIRouter()


@router.get("/")
async def read_index(Verifcation=Depends(verification)):
    """首页"""
    folder = os.path.dirname(
        os.path.dirname(os.path.dirname(__file__))
    )  # xiaomusic 目录
    return FileResponse(f"{folder}/static/index.html")


@router.get("/getversion")
def getversion(Verifcation=Depends(verification)):
    """获取版本"""
    log.debug("getversion %s", __version__)
    return {"version": __version__}


@router.get("/getsetting")
async def getsetting(need_device_list: bool = False, Verifcation=Depends(verification)):
    """获取设置"""
    config_data = xiaomusic.getconfig()
    data = asdict(config_data)
    data["password"] = "******"
    data["httpauth_password"] = "******"
    if need_device_list:
        device_list = await xiaomusic.getalldevices()
        log.info(f"getsetting device_list: {device_list}")
        data["device_list"] = device_list
    return data


@router.post("/savesetting")
async def savesetting(request: Request, Verifcation=Depends(verification)):
    """保存设置"""
    try:
        data_json = await request.body()
        data = json.loads(data_json.decode("utf-8"))
        debug_data = deepcopy_data_no_sensitive_info(data)
        log.info(f"saveconfig: {debug_data}")
        config_obj = xiaomusic.getconfig()
        if data["password"] == "******" or data["password"] == "":
            data["password"] = config_obj.password
        if data["httpauth_password"] == "******" or data["httpauth_password"] == "":
            data["httpauth_password"] = config_obj.httpauth_password
        await xiaomusic.saveconfig(data)

        # 重置 HTTP 服务器配置
        from xiaomusic.api.app import app
        from xiaomusic.api.dependencies import reset_http_server

        reset_http_server(app)

        return "save success"
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON") from err


@router.get("/downloadlog")
def downloadlog(Verifcation=Depends(verification)):
    """下载日志"""
    file_path = config.log_file
    if os.path.exists(file_path):
        # 创建一个临时文件来保存日志的快照
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        try:
            with open(file_path, "rb") as f:
                shutil.copyfileobj(f, temp_file)
            temp_file.close()

            # 使用BackgroundTask在响应发送完毕后删除临时文件
            def cleanup_temp_file(tmp_file_path):
                os.remove(tmp_file_path)

            background_task = BackgroundTask(cleanup_temp_file, temp_file.name)
            return FileResponse(
                temp_file.name,
                media_type="text/plain",
                filename="xiaomusic.txt",
                background=background_task,
            )
        except Exception as e:
            os.remove(temp_file.name)
            raise HTTPException(
                status_code=500, detail="Error capturing log file"
            ) from e
    else:
        return {"message": "File not found."}


@router.get("/latestversion")
async def latest_version(Verifcation=Depends(verification)):
    """获取最新版本"""
    version = await get_latest_version("xiaomusic")
    if version:
        return {"ret": "OK", "version": version}
    else:
        return {"ret": "Fetch version failed"}


@router.post("/updateversion")
async def updateversion(
    version: str = "", lite: bool = True, Verifcation=Depends(verification)
):
    """更新版本"""
    import asyncio

    ret = await update_version(version, lite)
    if ret != "OK":
        return {"ret": ret}

    asyncio.create_task(restart_xiaomusic())
    return {"ret": "OK"}


@router.get("/docs", include_in_schema=False)
async def get_swagger_documentation(Verifcation=Depends(verification)):
    """Swagger 文档"""
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


@router.get("/redoc", include_in_schema=False)
async def get_redoc_documentation(Verifcation=Depends(verification)):
    """ReDoc 文档"""
    return get_redoc_html(openapi_url="/openapi.json", title="docs")


@router.get("/openapi.json", include_in_schema=False)
async def openapi(Verifcation=Depends(verification)):
    """OpenAPI 规范"""
    from xiaomusic.api.app import app

    return get_openapi(title=app.title, version=app.version, routes=app.routes)
