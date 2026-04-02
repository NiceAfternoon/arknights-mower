import contextlib
import json
import os
import re
import zipfile
from typing import Any, Dict, Optional

import requests

from .. import __version__
from .log import logger


class UpdateManager:
    def __init__(self):
        # 1. 路径配置
        self.this_dir = os.path.dirname(os.path.abspath(__file__))
        # self.root 为项目根目录 (包含 mower.exe, arknights_mower 文件夹的地方)
        self.root = os.path.dirname(os.path.dirname(self.this_dir))
        
        # 资源版本文件路径：[根目录]/arknights_mower/data/version.json
        self.res_json_path = os.path.join(self.root, "arknights_mower", "data", "version.json")
        self.tmp_dir = os.path.join(self.root, "tmp")
        
        # 2. URL 配置
        self.github_api = "https://api.github.com/repos/NiceAfternoon/arknights-mower/releases/latest"
        # 资源仓库基础路径
        self.res_repo_url = "https://raw.githubusercontent.com/NiceAfternoon/MowerResource/main"
        self.patch_base_url = f"{self.res_repo_url}/patch"
        
        # 3. 状态管理
        self.status = "idle"  # idle, downloading, extracting, ready_to_restart, res_updating, error
        self.progress = 0
        self.last_error = None

    def _fetch(self, url: str, as_json: bool = False, is_check: bool = False) -> Optional[Any]:
        """封装请求逻辑，is_check 为 True 时用于快速检测文件是否存在"""
        try:
            if is_check:
                resp = requests.head(url, timeout=5)
                return resp.status_code == 200
            
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json() if as_json else resp.text.strip()
        except Exception as e:
            if not is_check:
                logger.warning(f"网络请求失败: {url} -> {e}")
            return None

    def check(self) -> Dict[str, Any]:
        """检查软件和资源更新，精准定位增量 ZIP 包"""
        # 1. 软件更新检查 (保持原逻辑)
        rel = self._fetch(self.github_api, as_json=True)
        if rel and self._compare_ver(__version__, rel["tag_name"]) == 1:
            best_asset = rel["assets"][0]
            is_patch = False
            patch_flag = f"from-{__version__}"
            for asset in rel["assets"]:
                if patch_flag in asset["name"]:
                    best_asset = asset
                    is_patch = True
                    break
            return {
                "type": "software", 
                "version": rel["tag_name"], 
                "asset": best_asset,
                "is_patch": is_patch
            }

        # 2. 资源更新检查
        # 获取远端最新的 version.json
        remote_info_url = f"{self.res_repo_url}/resource/arknights_mower/data/version.json"
        remote_info = self._fetch(remote_info_url, as_json=True)
        
        if not remote_info:
            return {"type": "none"}

        local_info = self.load_local_res()
        local_res_full = local_info.get("last_updated", "00-00-00-00-00-00_000000")
        remote_res_full = remote_info.get("last_updated", "")

        if local_res_full != remote_res_full:
            # 执行 8 位切片逻辑
            local_8 = local_res_full[:8]
            remote_8 = remote_res_full[:8]
            app_tag = rel["tag_name"] if rel else __version__

            # 优先级 1: 尝试找资源对资源的增量包 (from-旧资源8位-to-新资源8位-软件Tag.zip)
            res_to_res_name = f"from-{local_8}-to-{remote_8}-{app_tag}.zip"
            patch_url = f"{self.patch_base_url}/{res_to_res_name}"
            
            if not self._fetch(patch_url, is_check=True):
                # 优先级 2: 找不到则使用软件对资源的增量包 (from-软件Tag-to-新资源8位-软件Tag.zip)
                app_to_res_name = f"from-{app_tag}-to-{remote_8}-{app_tag}.zip"
                patch_url = f"{self.patch_base_url}/{app_to_res_name}"

            return {
                "type": "resources", 
                "version": remote_res_full, 
                "patch_url": patch_url,
                "remote_info": remote_info
            }
        
        return {"type": "none"}

    def start_res_upgrade(self, patch_url: str, remote_info: Dict):
        """下载增量 ZIP 并直接解压到根目录覆盖"""
        try:
            self.status, self.progress = "res_updating", 0
            os.makedirs(self.tmp_dir, exist_ok=True)
            zip_path = os.path.join(self.tmp_dir, "res_patch.zip")

            # 1. 下载增量包
            logger.info(f"正在获取资源增量包: {patch_url}")
            with requests.get(patch_url, stream=True, timeout=15) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=128*1024):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if total:
                                self.progress = int(done * 100 / total)

            # 2. 解压覆盖
            # 此时 ZIP 内部结构已经是 arknights_mower/... 和 ui/...
            # 直接解压到 self.root 即可完成覆盖
            self.status = "extracting"
            logger.info("正在应用资源更新...")
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(self.root)

            # 3. 强制更新本地 version.json，确保版本号对齐
            os.makedirs(os.path.dirname(self.res_json_path), exist_ok=True)
            with open(self.res_json_path, "w", encoding="utf-8") as f:
                json.dump(remote_info, f, indent=4, ensure_ascii=False)

            # 4. 清理临时文件
            with contextlib.suppress(OSError):
                os.remove(zip_path)

            self.status, self.progress = "idle", 100
            logger.info("资源更新完成")

        except Exception as e:
            self._handle_err(f"资源更新执行失败: {e}")

    def load_local_res(self) -> Dict:
        """加载本地资源版本信息"""
        if os.path.exists(self.res_json_path):
            try:
                with open(self.res_json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"last_updated": "00-00-00-00-00-00_000000"}

    def _compare_ver(self, local: str, remote: str) -> int:
        """版本号比对逻辑"""
        def n(v): return [int(m.group(1)) for x in str(v).split('.') if (m := re.match(r'^(\d+)', x))]
        try:
            v1, v2 = n(local), n(remote)
            for a, b in zip(v1 + [0]*3, v2 + [0]*3):
                if b > a:
                    return 1
                if b < a:
                    return -1
        except Exception:
            return 1 if local != remote else 0
        return 0

    def _handle_err(self, msg):
        """统一错误处理"""
        logger.error(msg)
        self.status, self.last_error = "error", msg

    def start_software_download(self, asset: Dict):
        """下载并解压软件更新包 (原有逻辑)"""
        try:
            self.status, self.progress = "downloading", 0
            os.makedirs(self.tmp_dir, exist_ok=True)
            zip_path = os.path.join(self.tmp_dir, "mower_update.zip")
            
            with requests.get(asset["browser_download_url"], stream=True, timeout=15) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            self.progress = int(done * 100 / total) if total else 0

            self.status = "extractall" 
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(self.tmp_dir)
            
            self.status = "ready_to_restart"
            with contextlib.suppress(OSError):
                os.remove(zip_path)
        except Exception as e:
            self._handle_err(f"软件下载失败: {e}")

    def execute_restart(self):
        """执行替换重启 (原有逻辑)"""
        bat_path = os.path.join(self.root, "upgrade.bat")
        new_exe = os.path.normpath(os.path.join(self.tmp_dir, "mower.exe"))
        old_exe = os.path.normpath(os.path.join(self.root, "mower.exe"))
        
        content = (
            f'@echo off\n'
            f'timeout /t 2 /nobreak >nul\n'
            f'del /f /q "{old_exe}"\n'
            f'copy /y "{new_exe}" "{old_exe}"\n'
            f'start "" "{old_exe}"\n'
            f'del "%~f0"'
        )
        with open(bat_path, "w") as f:
            f.write(content)
        os.system(f"start /b {bat_path}")
        os._exit(0)