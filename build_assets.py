import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _require_path(relative_path: str) -> str:
    path = PROJECT_ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(f"required build asset is missing: {path}")
    return str(path)


def _find_npm_executable() -> str:
    for candidate in ("npm.cmd", "npm"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FileNotFoundError("npm executable not found in PATH")


def ensure_frontend_built():
    ui_dir = PROJECT_ROOT / "ui"
    package_json = ui_dir / "package.json"
    if not package_json.exists():
        raise FileNotFoundError(f"frontend package.json is missing: {package_json}")

    if sys.platform.startswith("win"):
        subprocess.run(
            ["cmd", "/c", "npm", "run", "build"],
            cwd=ui_dir,
            check=True,
        )
        return

    npm_executable = _find_npm_executable()
    subprocess.run([npm_executable, "run", "build"], cwd=ui_dir, check=True)


def get_pyinstaller_common_datas():
    ensure_frontend_built()
    return [
        (_require_path("arknights_mower"), "arknights_mower"),
        (_require_path("logo.png"), "."),
        (_require_path("CHANGELOG.md"), "."),
        (_require_path("ui/dist"), "./ui/dist"),
    ]
