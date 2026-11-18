import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0, str(Path.cwd()))
from scripts import smoke_linux_desktop as original

wait = original.wait_for_desktop
def verified(bundle, process, state, timeout=120):
    try:
        return wait(bundle, process, state, timeout)
    except Exception:
        print("Window tree at failure:", flush=True)
        subprocess.run(["xwininfo","-root","-tree"],timeout=3)
        subprocess.run(["ps", "-g",str(process.pid),"-o","pid,ppid,stat,comm,wchan"],timeout=3)
        workspace = Path(os.environ["MOWER_DATA_DIR"])
        print("Workspace:",[x.name for x in workspace.iterdir()], "state:",state,flush=True)
        for p in workspace.rglob("*.json"):
            if p.parent.name != "instances":
                continue
            item=json.loads(p.read_text())
            print("Instance:", {k:item.get(k) for k in ("ready","kind","pid","root","port")},flush=True)
            if item.get("port"):
                try:
                    with urlopen("http://127.0.0.1:%s/"%item["port"],timeout=2) as resp:
                        print("HTTP:",resp.status,"index matches",resp.read()==(bundle / "_internal/ui/dist/index.html").read_bytes(),flush=True)
                except Exception as exc:
                    print(type(exc).__name__)
        for p in workspace.rglob("*.log"):
            print("Application log:",p.name,flush=True)
            for line in p.read_text(errors="replace").splitlines()[-150:]:
                if re.search("(?i)token|secret|http[s]?://",line):
                    continue
                if re.search("(?i)error|exception|traceback|failed|失败|异常|窗口|托盘|正在|permission denied|import",line):
                    print(line[:350])
        raise
original.wait_for_desktop = verified
original.main()
