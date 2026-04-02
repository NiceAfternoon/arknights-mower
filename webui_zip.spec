# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import rapidocr_onnxruntime
# 导入收集 webview 依赖的工具
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# --- RapidOCR 数据收集逻辑 ---
package_name = "rapidocr_onnxruntime"
install_dir = Path(rapidocr_onnxruntime.__file__).resolve().parent
onnx_paths = list(install_dir.rglob("*.onnx"))
yaml_paths = list(install_dir.rglob("*.yaml"))
onnx_add_data = [(str(v.parent), f"{package_name}/{v.parent.name}") for v in onnx_paths]
yaml_add_data = []
for v in yaml_paths:
    if package_name == v.parent.name:
        yaml_add_data.append((str(v.parent / "*.yaml"), package_name))
    else:
        yaml_add_data.append((str(v.parent / "*.yaml"), f"{package_name}/{v.parent.name}"))
add_data = list(set(yaml_add_data + onnx_add_data))
site_packages = install_dir.parent

# --- Webview 依赖收集逻辑 (新增) ---
# 这步非常关键，它会收集 pywebview 运行所需的各种 dll 和 hiddenimports
wv_datas, wv_binaries, wv_hidden = collect_all('webview')

# --- Mower 主程序分析 ---
mower_a = Analysis(
    ["webview_ui.py"],
    pathex=[],
    binaries=wv_binaries, # 注入 webview 二进制
    datas=[
        ("arknights_mower", "arknights_mower"),
        ("logo.png", "."),
        (f"{site_packages}/onnxruntime/capi/onnxruntime_providers_shared.dll", "onnxruntime/capi/"),
        (f"{site_packages}/pyzbar/libzbar-64.dll", "."),
        (f"{site_packages}/pyzbar/libiconv.dll", "."),
        ("./ui/dist","./ui/dist"),
    ] + add_data + wv_datas, # 注入 webview 数据
    hiddenimports=wv_hidden, # 注入 webview 隐式导入
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

mower_pure = [i for i in mower_a.pure if not i[0].startswith("arknights_mower")]

mower_pyz = PYZ(
    mower_pure,
    mower_a.zipped_data,
    cipher=block_cipher,
)

mower_exe = EXE(
    mower_pyz,
    mower_a.scripts,
    [],
    exclude_binaries=True,
    name="mower",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="logo.ico",
)

# --- 多开管理器分析 (保持不变) ---
manager_a = Analysis(
    ["manager.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

manager_pyz = PYZ(
    manager_a.pure,
    manager_a.zipped_data,
    cipher=block_cipher,
)

manager_exe = EXE(
    manager_pyz,
    manager_a.scripts,
    [],
    exclude_binaries=True,
    name="多开管理器",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="logo.ico",
)

# --- 最终收集归档 ---
coll = COLLECT(
    mower_exe,
    mower_a.binaries,
    mower_a.zipfiles,
    mower_a.datas,
    manager_exe,
    manager_a.binaries,
    manager_a.zipfiles,
    manager_a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="mower",
)