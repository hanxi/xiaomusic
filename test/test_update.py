from xiaomusic.utils import (
    download_and_extract,
)

if __name__ == "__main__":
    import asyncio

    url = "https://github.hanxi.cc/proxy/hanxi/xiaomusic/releases/download/main/app-amd64-lite.tar.gz"
    target_directory = "./tmp/app"
    asyncio.run(download_and_extract(url, target_directory))
