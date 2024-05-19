#!/usr/bin/env python3
import os
import sys
import traceback
import asyncio

from flask import Flask, request, send_from_directory
from threading import Thread

from xiaomusic.config import (
    KEY_WORD_DICT,
)

from xiaomusic import (
    __version__,
)

# 隐藏 flask 启动告警
# https://gist.github.com/jerblack/735b9953ba1ab6234abb43174210d356
cli = sys.modules['flask.cli']
cli.show_server_banner = lambda *x: None

app = Flask(__name__)
host = "0.0.0.0"
port = 8090
static_path = "music"
xiaomusic = None
log = None


@app.route("/allcmds")
def allcmds():
    return KEY_WORD_DICT

@app.route("/getversion", methods=["GET"])
def getversion():
    log.debug("getversion %s", __version__)
    return {
        "version": __version__,
    }

@app.route("/getvolume", methods=["GET"])
def getvolume():
    volume = xiaomusic.get_volume_ret()
    return {
        "volume": volume,
    }

@app.route("/searchmusic", methods=["GET"])
def searchmusic():
    name = request.args.get('name')
    return xiaomusic.searchmusic(name)

@app.route("/playingmusic", methods=["GET"])
def playingmusic():
    return xiaomusic.playingmusic()

@app.route("/", methods=["GET"])
def redirect_to_index():
    return send_from_directory("static", "index.html")


@app.route("/cmd", methods=["POST"])
async def do_cmd():
    data = request.get_json()
    cmd = data.get("cmd")
    if len(cmd) > 0:
        log.debug("docmd. cmd:%s", cmd)
        xiaomusic.set_last_record(cmd)
        return {"ret": "OK"}
    return {"ret": "Unknow cmd"}

@app.route("/getsetting", methods=["GET"])
async def getsetting():
    config = xiaomusic.getconfig()
    log.debug(config)

    alldevices = await xiaomusic.call_main_thread_function(xiaomusic.getalldevices)
    log.info(alldevices)
    data = {
        "mi_did": config.mi_did,
        "mi_did_list": alldevices["did_list"],
        "mi_hardware": config.hardware,
        "mi_hardware_list": alldevices["hardware_list"],
        "xiaomusic_search": config.search_prefix,
        "xiaomusic_proxy": config.proxy,
    }
    return data

@app.route("/savesetting", methods=["POST"])
async def savesetting():
    data = request.get_json()
    log.info(data)
    await xiaomusic.saveconfig(data)
    return "save success"

def static_path_handler(filename):
    log.debug(filename)
    log.debug(static_path)
    absolute_path = os.path.abspath(static_path)
    log.debug(absolute_path)
    return send_from_directory(absolute_path, filename)


def run_app():
    app.run(host=host, port=port)


def StartHTTPServer(_port, _static_path, _xiaomusic):
    global port, static_path, xiaomusic, log
    port = _port
    static_path = _static_path
    xiaomusic = _xiaomusic
    log = xiaomusic.log

    app.add_url_rule(
        f"/{static_path}/<path:filename>", "static_path_handler", static_path_handler
    )

    server_thread = Thread(target=run_app)
    server_thread.daemon = True
    server_thread.start()
    xiaomusic.log.info(f"Serving on {host}:{port}")
