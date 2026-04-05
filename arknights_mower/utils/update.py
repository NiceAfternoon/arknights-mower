import contextlib
import json
import os
import re
import sys
import zipfile
import subprocess
import shutil
from typing import Any, Dict, Optional

import requests

from .. import __version__
from .log import logger

class UpdateManager:
    def __init__(self):
        self.this_dir = os.path.dirname(os.path.abspath(__file__))
        
        if getattr(sys, 'frozen', False):
            self.root = os.path.dirname(os.path.abspath(sys.executable))
            self.res_json_path = os.path.join(self.root, "_internal", "arknights_mower", "data", "version.json")
        else:
            self.root = os.path.dirname(os.path.dirname(os.path.dirname(self.this_dir)))
            self.res_json_path = os.path.join(self.root, "arknights_mower", "data", "version.json")
            
        self.tmp_dir = os.path.join(self.root, "tmp")
        
        self.github_api = "https://api.github.com/repos/NiceAfternoon/arknights-mower/releases/latest"
        self.res_repo_url = "https://raw.githubusercontent.com/NiceAfternoon/MowerResource/main"
        self.patch_base_url = f"{self.res_repo_url}/patch"
        
        self.status = "idle"
        self.progress = 0
        self.last_error = None

    def _fetch(self, url: str, as_json: bool = False, is_check: bool = False) -> Optional[Any]:
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
        rel = self._fetch(self.github_api, as_json=True)
        if rel:
            remote_tag = rel["tag_name"]
            local_v = __version__.lstrip('v')
            remote_v = remote_tag.lstrip('v')
            
            if self._compare_ver(local_v, remote_v) == 1:
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
                    "version": remote_tag, 
                    "asset": best_asset,
                    "is_patch": is_patch
                }

        remote_info_url = f"{self.res_repo_url}/resource/arknights_mower/data/version.json"
        remote_info = self._fetch(remote_info_url, as_json=True)
        
        if remote_info:
            local_info = self.load_local_res()
            # 从 res_version 读取进行比对
            local_res_full = local_info.get("res_version", "0000.0000.0000")
            remote_res_full = remote_info.get("res_version", "")

            # 字符串字典序比对即可区分时间戳的新旧
            if remote_res_full and remote_res_full > local_res_full:
                local_short = local_res_full.replace(".", "")
                remote_short = remote_res_full.replace(".", "")
                app_tag = rel["tag_name"] if rel else __version__

                res_to_res_name = f"from-{local_short}-to-{remote_short}-{app_tag}.zip"
                patch_url = f"{self.patch_base_url}/{res_to_res_name}"
                
                if not self._fetch(patch_url, is_check=True):
                    app_to_res_name = f"from-{app_tag}-to-{remote_short}-{app_tag}.zip"
                    patch_url = f"{self.patch_base_url}/{app_to_res_name}"

                return {
                    "type": "resources", 
                    "version": remote_res_full, 
                    "patch_url": patch_url,
                    "remote_info": remote_info
                }
        
        return {"type": "none"}

    def start_res_upgrade(self, patch_url: str, remote_info: Dict):
        try:
            self.status, self.progress = "res_updating", 0
            os.makedirs(self.tmp_dir, exist_ok=True)
            zip_path = os.path.join(self.tmp_dir, "res_patch.zip")

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

            self.status = "extracting"
            # 创建临时解压目录
            extract_tmp = os.path.join(self.tmp_dir, "res_extract")
            if os.path.exists(extract_tmp):
                shutil.rmtree(extract_tmp)
            os.makedirs(extract_tmp, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_tmp)

            # 路径校正：判断解压出的内容是否包含 resource 文件夹
            source_path = extract_tmp
            if "resource" in os.listdir(extract_tmp):
                source_path = os.path.join(extract_tmp, "resource")
            
            # 确定移动的目标根目录（frozen 模式下为 _internal）
            move_target = os.path.dirname(os.path.dirname(os.path.dirname(self.res_json_path)))

            # 将内容移动到正确位置
            for item in os.listdir(source_path):
                s = os.path.join(source_path, item)
                d = os.path.join(move_target, item)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    shutil.move(s, d)
                else:
                    shutil.move(s, d)

            # 写入版本号文件
            os.makedirs(os.path.dirname(self.res_json_path), exist_ok=True)
            with open(self.res_json_path, "w", encoding="utf-8") as f:
                json.dump(remote_info, f, indent=4, ensure_ascii=False)

            # 清理
            shutil.rmtree(extract_tmp, ignore_errors=True)
            with contextlib.suppress(OSError):
                os.remove(zip_path)

            self.status, self.progress = "idle", 100
            logger.info("资源更新完成")
        except Exception as e:
            self._handle_err(f"资源更新执行失败: {e}")

    def load_local_res(self) -> Dict:
        if os.path.exists(self.res_json_path):
            try:
                with open(self.res_json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"res_version": "0000.0000.0000"}

    def _compare_ver(self, local: str, remote: str) -> int:
        def n(v): return [int(m.group(1)) for x in str(v).split('.') if (m := re.match(r'^(\d+)', x))]
        try:
            v1, v2 = n(local), n(remote)
            for a, b in zip(v1 + [0]*3, v2 + [0]*3):
                if b > a: return 1
                if b < a: return -1
        except Exception:
            return 1 if local != remote else 0
        return 0

    def _handle_err(self, msg):
        logger.error(msg)
        self.status, self.last_error = "error", msg

    def start_software_download(self, asset: Dict):
        try:
            self.status, self.progress = "downloading", 0
            if os.path.exists(self.tmp_dir):
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
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

            self.status = "extracting" 
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(self.tmp_dir)
            
            items = os.listdir(self.tmp_dir)
            if len(items) <= 2: 
                for item in items:
                    path = os.path.join(self.tmp_dir, item)
                    if os.path.isdir(path) and "mower.exe" in os.listdir(path):
                        self.tmp_dir = path
                        break

            self.status = "ready_to_restart"
            with contextlib.suppress(OSError):
                os.remove(zip_path)
        except Exception as e:
            self._handle_err(f"软件下载失败: {e}")

    def execute_restart(self):
        bat_path = os.path.join(self.root, "upgrade.bat")
        target_dir = os.path.abspath(self.root)
        new_content_dir = os.path.abspath(self.tmp_dir)
        old_exe_name = "mower.exe"
        old_exe_path = os.path.join(target_dir, old_exe_name)

        content = (
            f'@echo off\n'
            f'setlocal enabledelayedexpansion\n'
            f'timeout /t 1 /nobreak >nul\n'
            f'taskkill /f /im "{old_exe_name}" /t >nul 2>&1\n'
            f'taskkill /f /im "多开管理器.exe" /t >nul 2>&1\n'
            f'set /a retry=0\n'
            f':wait_lock\n'
            f'if !retry! leq 10 (\n'
            f'    timeout /t 1 /nobreak >nul\n'
            f'    2>nul ( >>"{old_exe_path}" (call )) && (goto :do_copy) || (set /a retry+=1 & goto :wait_lock)\n'
            f')\n'
            f':do_copy\n'
            f'robocopy "{new_content_dir}" "{target_dir}" /E /MOVE /IS /IT /R:5 /W:1 /XF upgrade.bat\n'
            f'timeout /t 1 /nobreak >nul\n'
            f'start "" "{old_exe_path}"\n'
            f'del "%~f0"'
        )

        try:
            with open(bat_path, "w", encoding="gbk") as f:
                f.write(content)
        except Exception:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(f"@chcp 65001 >nul\n{content}")
        
        logger.info("主程序即将关闭以应用更新...")
        
        if sys.platform == "win32":
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                creationflags=0x08000000, 
                close_fds=True,
                shell=False
            )
        else:
            os.system(f'start "" /b "{bat_path}"')
            
        os._exit(0)