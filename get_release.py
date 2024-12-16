import json
import os

import requests

# 替换为你的 GitHub 仓库信息
GITHUB_OWNER = "hanxi"
GITHUB_REPO = "xiaomusic"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


def fetch_releases():
    headers = {}
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    try:
        response = requests.get(GITHUB_API_URL, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"请求 GitHub API 失败: {e}")
        return []


def extract_tar_gz_files(releases):
    versions = []
    for release in releases:
        version = release.get("tag_name")
        if not version:
            continue

        files = []
        for asset in release.get("assets", []):
            if asset.get("name", "").endswith(".tar.gz"):
                files.append(asset["name"])

        if files:
            versions.append({"version": version, "files": files})
    return versions


def save_to_json(data, filename="versions.json"):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
        print(f"数据已保存到 {filename}")
    except OSError as e:
        print(f"保存文件失败: {e}")


def main():
    releases = fetch_releases()
    if not releases:
        print("未获取到任何 release 数据")
        return

    versions = extract_tar_gz_files(releases)
    save_to_json(versions, "docs/.vitepress/dist/versions.json")


if __name__ == "__main__":
    main()
