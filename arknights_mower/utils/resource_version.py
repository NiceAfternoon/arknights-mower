"""资源包 version.json 的客户端读取与更新检测（#189/#190）。

- 只读正式 ``data/version.json``（安装状态由 #191 拥有），远端先拉 tmp 再比对，**不覆盖正式文件**。
- 展示用 ``display_version``（可读名+#MMDD），比较用 ``res_version``（日期+内容哈希，只升不降），两者分离。
- 镜像 ``hot_update.py`` 模式：fetch 不抛异常、失败回退 tmp 缓存。
"""

import json
import re
from pathlib import Path

import requests

from arknights_mower.utils.log import logger
from arknights_mower.utils.path import get_path
from arknights_mower.utils.res_version import display_version
from arknights_mower.utils.resource_pkg import resource_pkg_path

RESOURCE_VERSION_URL = (
    "https://raw.githubusercontent.com/ArkMowers/MowerResource/main/version.json"
)
LOCAL_VERSION_PATH = resource_pkg_path("arknights_mower/data/version.json")
TMP_VERSION_PATH = get_path("@install/tmp/resource_version.json")

_RES_VERSION_RE = re.compile(r"^v?(\d{4})\.(\d{2})\.(\d{2})-([0-9a-fA-F]{6,40})$")


def _parse_res_version(v: str) -> tuple | None:
    """解析「日期-内容哈希」res_version -> (年, 月, 日, 哈希)；前导 v 可带可不带，非法返回 None。"""
    m = _RES_VERSION_RE.match(v or "")
    if not m:
        return None
    return (
        int(m.group(1)),
        int(m.group(2)),
        int(m.group(3)),
        m.group(4),
    )


def _res_version_newer(remote: str, local: str) -> bool:
    """remote 严格新于 local 才 True（防手滑发旧版降级）。

    日期不同按日期定序；同日哈希不同 = 内容变了 = 视为更新。本地缺失时 remote 恒新。
    无法解析的版本回退到「不同即更新」的保守行为。
    """
    remote_t, local_t = _parse_res_version(remote), _parse_res_version(local)
    if remote_t is None or local_t is None:
        return remote != local
    if remote_t[:3] != local_t[:3]:
        return remote_t[:3] > local_t[:3]
    return remote_t[3] != local_t[3]


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _read_local_version_json() -> dict | None:
    return _read_json(LOCAL_VERSION_PATH)


def _read_tmp_cache() -> dict | None:
    return _read_json(TMP_VERSION_PATH)


def _write_tmp_cache(data: dict) -> None:
    TMP_VERSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    TMP_VERSION_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _fetch_remote_version_json() -> dict | None:
    try:
        r = requests.get(RESOURCE_VERSION_URL, timeout=30)
        if r.status_code != 200:
            logger.warning(f"资源版本拉取失败: HTTP {r.status_code}")
            return None
        return _read_json_from_bytes(r.content)
    except Exception as e:
        logger.warning(f"资源版本拉取失败: {e}")
        return None


def _read_json_from_bytes(raw: bytes) -> dict | None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def check_resource_update() -> dict:
    """拉远端 version.json 到 tmp、比对本地 res_version，返回展示与更新状态。"""
    local = _read_local_version_json() or {}
    current_version = local.get("res_version") or ""
    current_display = display_version(local) or ""

    remote = _fetch_remote_version_json()
    if remote is None:
        remote = _read_tmp_cache()
        if remote is None:
            return {
                "current_version": current_version,
                "current_display": current_display,
                "remote_version": "",
                "remote_display": "",
                "update_available": None,
                "error": "网络错误：无法获取远程版本号",
            }
    else:
        _write_tmp_cache(remote)

    remote_version = remote.get("res_version") or ""
    if not remote_version:
        return {
            "current_version": current_version,
            "current_display": current_display,
            "remote_version": "",
            "remote_display": display_version(remote) or "",
            "update_available": None,
            "error": "远程版本号缺失",
        }
    return {
        "current_version": current_version,
        "current_display": current_display,
        "remote_version": remote_version,
        "remote_display": display_version(remote) or "",
        "update_available": _res_version_newer(remote_version, current_version),
        "error": None,
    }
