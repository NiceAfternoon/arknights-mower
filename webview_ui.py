#!/usr/bin/env python3
import multiprocessing as mp
from urllib.parse import quote

# 托盘开关窗口是杀进程重建（见 webview_window / start_tray），新窗口尺寸读
# conf.yml。Windows WebView2 在窗口销毁路径会触发极小/零尺寸 resized，若被
# 写回 conf.yml，下次托盘打开就缩成一团——下限钳制挡住这些残留事件。
MIN_WINDOW_SIZE = 100
# 与 arknights_mower/utils/config/conf.py 的 WebViewConf 默认值一致，仅在
# conf.yml 里已有损坏（极小/零）尺寸时兜底，避免坏尺寸被读进创建并再次持久化。
DEFAULT_WINDOW_SIZE = (1450, 850)


def sanitize_window_size(width, height, min_size=MIN_WINDOW_SIZE):
    """返回合法的窗口尺寸；极小/零/非数字视为销毁路径的残留事件，返回 None。"""
    try:
        w = int(width)
        h = int(height)
    except (TypeError, ValueError, OverflowError):
        return None
    if w < min_size or h < min_size:
        return None
    return (w, h)


def resolve_window_size(width, height, min_size=MIN_WINDOW_SIZE):
    """读取 conf 的初始尺寸；损坏（极小/零/非数字）时兜底到默认启动尺寸。"""
    return sanitize_window_size(width, height, min_size) or DEFAULT_WINDOW_SIZE


def splash_screen(queue: mp.Queue):
    import tkinter as tk
    from tkinter.font import Font

    from PIL import Image, ImageTk

    from arknights_mower.utils.path import get_path

    root = tk.Tk()
    container = tk.Frame(root)

    logo_path = get_path("@internal/logo.png")
    img = Image.open(logo_path)
    img = ImageTk.PhotoImage(img)
    canvas = tk.Canvas(container, width=256, height=256)
    canvas.create_image(128, 128, image=img)
    canvas.pack()

    title_font = Font(size=24)
    title_label = tk.Label(
        container,
        text="arknights-mower",
        font=title_font,
    )
    title_label.pack()

    loading_label = tk.Label(container)
    loading_label.pack()

    container.pack(expand=1)
    root.overrideredirect(True)

    window_width = 500
    window_height = 400
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = int(screen_width / 2 - window_width / 2)
    y = int(screen_height / 2 - window_height / 2)
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    def recv_msg():
        try:
            msg = queue.get(False)
            if msg["type"] == "text":
                loading_label.config(text=msg["data"] + "……")
                root.after(100, recv_msg)
            elif msg["type"] == "dialog":
                from tkinter import messagebox

                root.withdraw()
                messagebox.showerror("arknights-mower", msg["data"])
                root.destroy()
        except Exception:
            pass

    root.after(100, recv_msg)
    root.mainloop()


def build_window_title(instance_name, port):
    if instance_name:
        return f"mower@{port}({instance_name})"
    return f"mower@{port}"


def append_query_param(url, key, value):
    if not value:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{key}={quote(value)}"


def start_tray(queue: mp.Queue, instance_name, port, url):
    from PIL import Image
    from pystray import Icon, Menu, MenuItem

    from arknights_mower.utils.path import get_path

    logo_path = get_path("@internal/logo.png")
    img = Image.open(logo_path)

    title = build_window_title(instance_name, port)

    def open_browser():
        import webbrowser

        webbrowser.open(url)

    icon = Icon(
        name="arknights-mower",
        icon=img,
        menu=Menu(
            MenuItem(
                text=title,
                action=None,
                enabled=False,
            ),
            Menu.SEPARATOR,
            MenuItem(
                text="打开/关闭窗口",
                action=lambda: queue.put("toggle"),
                default=True,
            ),
            MenuItem(
                text="在浏览器中打开网页面板",
                action=open_browser,
            ),
            Menu.SEPARATOR,
            MenuItem(
                text="退出",
                action=lambda: queue.put("exit"),
            ),
        ),
        title=title,
    )
    icon.run()


def webview_window(child_conn, global_space, instance_name, host, port, url, tray):
    import sys
    from threading import Thread

    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True

    from arknights_mower.__init__ import __version__
    from arknights_mower.utils import config, path

    path.global_space = global_space

    global width
    global height

    config.load_conf()
    width, height = resolve_window_size(
        config.conf.webview.width, config.conf.webview.height
    )

    def window_size(w, h):
        global width
        global height
        size = sanitize_window_size(w, h)
        if size is not None:
            width, height = size

    window = webview.create_window(
        f"arknights-mower {__version__} - {build_window_title(instance_name, port)}",
        url,
        text_select=True,
        confirm_close=not tray,
        width=width,
        height=height,
    )
    window.events.resized += window_size

    def recv_msg():
        while True:
            msg = child_conn.recv()
            if msg == "exit":
                window.confirm_close = False
                window.destroy()
                return
            if msg == "file":
                result = window.create_file_dialog(
                    dialog_type=webview.OPEN_DIALOG,
                )
            elif msg == "folder":
                result = window.create_file_dialog(
                    dialog_type=webview.FOLDER_DIALOG,
                )
            if result is None:
                result = ""
            elif not isinstance(result, str):
                if len(result) == 0:
                    result = ""
                else:
                    result = result[0]
            child_conn.send(result)

    Thread(target=recv_msg, daemon=True).start()

    try:
        webview.start()

        size = sanitize_window_size(width, height)
        if size is not None:
            config.load_conf()
            config.conf.webview.width, config.conf.webview.height = size
            config.save_conf()
        sys.exit()
    except Exception:
        import webbrowser

        webbrowser.open(url)


if __name__ == "__main__":
    mp.freeze_support()

    splash_queue = mp.Queue()
    splash_process = mp.Process(target=splash_screen, args=(splash_queue,), daemon=True)
    splash_process.start()

    splash_queue.put({"type": "text", "data": "加载配置文件"})

    import sys

    from arknights_mower.utils import path

    instance_name = ""
    if len(sys.argv) >= 2:
        path.global_space = sys.argv[1]
    if len(sys.argv) >= 3:
        instance_name = sys.argv[2]

    from arknights_mower.utils import config

    conf = config.conf
    tray = conf.webview.tray
    token = conf.webview.token
    host = "0.0.0.0" if token else "127.0.0.1"

    splash_queue.put({"type": "text", "data": "检测端口占用"})

    from arknights_mower.utils.network import get_new_port, is_port_in_use

    if token:
        port = conf.webview.port

        if is_port_in_use(port):
            splash_queue.put(
                {"type": "dialog", "data": f"端口{port}已被占用，无法启动！"}
            )
            sys.exit()
    else:
        port = get_new_port()

    url = f"http://127.0.0.1:{port}"
    if token:
        url += f"?token={token}"
    url = append_query_param(url, "instance_name", instance_name)

    splash_queue.put({"type": "text", "data": "加载Flask依赖"})

    from server import app

    splash_queue.put({"type": "text", "data": "启动Flask网页服务器"})

    from threading import Thread
    from time import sleep

    flask_thread = Thread(
        target=app.run,
        kwargs={"host": host, "port": port},
        daemon=True,
    )
    flask_thread.start()

    while not is_port_in_use(port):
        sleep(0.1)

    url = f"http://127.0.0.1:{port}"
    if token:
        url += f"?token={token}"
    url = append_query_param(url, "instance_name", instance_name)

    if tray:
        splash_queue.put({"type": "text", "data": "加载托盘图标"})
        tray_queue = mp.Queue()
        tray_process = mp.Process(
            target=start_tray,
            args=(tray_queue, instance_name or path.global_space, port, url),
            daemon=True,
        )
        tray_process.start()

    splash_queue.put({"type": "text", "data": "创建主窗口"})

    config.parent_conn, child_conn = mp.Pipe()
    config.webview_process = mp.Process(
        target=webview_window,
        args=(child_conn, path.global_space, instance_name, host, port, url, tray),
        daemon=True,
    )
    config.webview_process.start()

    splash_process.terminate()

    if tray:
        while True:
            msg = tray_queue.get()
            if msg == "toggle":
                if config.webview_process.is_alive():
                    config.parent_conn.send("exit")
                    if config.webview_process.join(3) is None:
                        config.webview_process.terminate()
                else:
                    config.parent_conn, child_conn = mp.Pipe()
                    config.webview_process = mp.Process(
                        target=webview_window,
                        args=(
                            child_conn,
                            path.global_space,
                            instance_name,
                            host,
                            port,
                            url,
                            tray,
                        ),
                        daemon=True,
                    )
                    config.webview_process.start()
            elif msg == "exit":
                config.parent_conn.send("exit")
                if config.webview_process.join(3) is None:
                    config.webview_process.terminate()
                break
    else:
        config.webview_process.join()
