import requests


def httpget(url):
    global log

    # 发起请求
    response = requests.get(url, timeout=5)  # 增加超时以避免长时间挂起
    response.raise_for_status()  # 如果响应不是200，引发HTTPError异常
    log.info(f"httpget url:{url} response:{response.text}")
