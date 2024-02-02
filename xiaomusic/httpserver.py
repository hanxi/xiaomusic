#!/usr/bin/env python3
import os
import traceback

from flask import Flask, request, send_from_directory
from threading import Thread

from xiaomusic.config import (
    KEY_WORD_DICT,
)

app = Flask(__name__)
host = "0.0.0.0"
port = 8090
static_path = "music"
xiaomusic = None
log = None


@app.route("/allcmds")
def allcmds():
    return KEY_WORD_DICT


@app.route("/getvolume")
def getvolume():
    return {
        "volume": xiaomusic.get_volume(),
    }


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
