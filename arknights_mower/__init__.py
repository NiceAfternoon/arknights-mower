import json
import os
import platform
import sys
from pathlib import Path

__version__ = "v4.1.8"

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    __rootdir__ = Path(sys._MEIPASS).joinpath("arknights_mower").resolve()
else:
    __rootdir__ = Path(__file__).parent.resolve()

    from arknights_mower.utils.git_rev import revision_info

    __version__ += "+" + revision_info()[:7]

RES_PATH = os.path.join(__rootdir__, "data", "version.json")

with open(RES_PATH, "r", encoding="utf-8") as f:
    res = json.load(f)

if res["activity"]["time"] >= res["gacha"]["time"]:
    res_version = f"{res['activity']['name']}#{res['last_updated'][:8]}"
else:
    res_version = f"{res['gacha']['name']}#{res['last_updated'][:8]}"

__resource_tag__ = res['last_updated']
__resource_version__ = res_version

__system__ = platform.system().lower()
