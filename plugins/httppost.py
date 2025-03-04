import requests

target = "HTTP://192.168.1.10:58091/items/"


def httppost(data, url=target):
    global log
    # 发起请求,
    with requests.post(
        url, json=data, timeout=5
    ) as response:  # 增加超时以避免长时间挂起
        response.raise_for_status()  # 如果响应不是200，引发HTTPError异常
        log.info(f"httppost url:{url} data :{data} response:{response.text}")
