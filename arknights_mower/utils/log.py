import atexit
import logging
import re
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from pathlib import Path
from queue import Queue
from threading import Lock, Thread

import colorlog

from arknights_mower.utils import config
from arknights_mower.utils.path import get_path

BASIC_FORMAT = (
    "%(asctime)s %(relativepath)s:%(lineno)d %(levelname)s %(funcName)s: %(message)s"
)
COLOR_FORMAT = f"%(log_color)s{BASIC_FORMAT}"
DATE_FORMAT = None
LOG_TIMESTAMP_RE = re.compile(
    rb"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s"
    rb".+:\d+\s(?:DEBUG|INFO|WARNING|ERROR|CRITICAL|NOTSET)\s\S+:\s"
)
basic_formatter = logging.Formatter(BASIC_FORMAT, DATE_FORMAT)
color_formatter = colorlog.ColoredFormatter(COLOR_FORMAT, DATE_FORMAT)


class PackagePathFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        relativepath = Path(record.pathname)
        try:
            relativepath = relativepath.relative_to(get_path("@install"))
        except ValueError:
            pass
        record.relativepath = relativepath
        return True


filter = PackagePathFilter()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# d(ebug)hlr: 终端输出
dhlr = logging.StreamHandler(stream=sys.stdout)
dhlr.setFormatter(color_formatter)
dhlr.setLevel(logging.DEBUG)
dhlr.addFilter(filter)

# f(ile)hlr: 文件记录
fhlr = None


class Handler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord):
        msg = f"{record.asctime} {record.levelname} {record.message}"
        if record.exc_info:
            msg += "\n" + "".join(traceback.format_exception(*record.exc_info))
        entry = {"data": msg}
        if screenshot := getattr(record, "screenshot", None):
            entry["screenshot"] = screenshot
        config.log_queue.put(entry)


# w(ebsocket)hlr: WebSocket
whlr = Handler()
whlr.setLevel(logging.INFO)

log_queue = Queue()
listener = None
listener_lock = Lock()

folder = Path(get_path("@app/log"))
folder.mkdir(exist_ok=True, parents=True)
fhlr = TimedRotatingFileHandler(
    folder.joinpath("runtime.log"), encoding="utf8", backupCount=168
)
fhlr.setFormatter(basic_formatter)
fhlr.setLevel("DEBUG")
fhlr.addFilter(filter)
queue_handler = QueueHandler(log_queue)
logger.addHandler(queue_handler)
listener = QueueListener(log_queue, dhlr, fhlr, whlr, respect_handler_level=True)
listener.start()


def stop_logging() -> None:
    global listener
    with listener_lock:
        active_listener = listener
        listener = None
    if active_listener is not None:
        active_listener.stop()


atexit.register(stop_logging)

screenshot_folder = get_path("@app/screenshot")
screenshot_folder.mkdir(exist_ok=True, parents=True)
screenshot_queue = Queue()
cleanup_time = datetime.now()


class SceneSnapshotStore:
    def __init__(self, folder: Path):
        self.folder = folder
        self.folder.mkdir(exist_ok=True, parents=True)
        self.latest_filename = None
        self.latest_scene = None
        self._lock = Lock()

    def publish(self, scene: int, image: bytes) -> str | None:
        with self._lock:
            if scene == self.latest_scene:
                return None
            filename = f"{time.time_ns()}.jpg"
            self.folder.joinpath(filename).write_bytes(image)
            self.latest_scene = scene
            self.latest_filename = filename
            return filename


scene_snapshot_store = SceneSnapshotStore(screenshot_folder)


def publish_scene_snapshot(scene: int, image: bytes) -> str | None:
    return scene_snapshot_store.publish(scene, image)


def get_latest_scene_snapshot() -> str:
    return scene_snapshot_store.latest_filename or ""


def screenshot_cleanup():
    start_time_ns = time.time_ns() - config.conf.screenshot * 3600 * 10**9
    latest_scene_snapshot = get_latest_scene_snapshot()
    for i in screenshot_folder.iterdir():
        if i.is_dir():
            if i.name in ["run_order", "workshop", "solve_captcha"]:
                # 处理run_order文件夹，只保留最后100张图片
                images = sorted(
                    [f for f in i.iterdir() if f.is_file() and f.stem.isnumeric()],
                    key=lambda x: int(x.stem),
                )
                if len(images) > 100:
                    for img in images[:-100]:  # 保留最后100张，删除其余的
                        img.unlink()
                continue
            shutil.rmtree(i)
        elif not i.stem.isnumeric():
            i.unlink()
        elif i.name != latest_scene_snapshot and int(i.stem) < start_time_ns:
            i.unlink()
    global cleanup_time
    cleanup_time = datetime.now()
    logger.info("operation=%s result=%s", "screenshot_cleanup", "completed")


def screenshot_worker():
    screenshot_cleanup()
    while True:
        now = datetime.now()
        if now - cleanup_time > timedelta(hours=1):
            screenshot_cleanup()
        img, filename = screenshot_queue.get()
        with screenshot_folder.joinpath(filename).open("wb") as f:
            f.write(img)


Thread(target=screenshot_worker, daemon=True).start()


def save_screenshot(img: bytes, sub_folder=None) -> None:
    filename = f"{time.time_ns()}.jpg"
    if sub_folder:
        sub_folder_path = Path(screenshot_folder) / sub_folder
        sub_folder_path.mkdir(parents=True, exist_ok=True)
        filename = f"{sub_folder}/{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    screenshot_queue.put((img, filename))


def _parse_log_timestamp(line: bytes) -> datetime | None:
    match = LOG_TIMESTAMP_RE.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(
            match.group("timestamp").decode("ascii"), "%Y-%m-%d %H:%M:%S,%f"
        )
    except ValueError:
        return None


def _reverse_lines(stream, chunk_size: int = 64 * 1024):
    stream.seek(0, 2)
    position = stream.tell()
    buffer = b""
    while position > 0:
        read_size = min(chunk_size, position)
        position -= read_size
        stream.seek(position)
        buffer = stream.read(read_size) + buffer
        lines = buffer.split(b"\n")
        buffer = lines[0]
        for line in reversed(lines[1:]):
            yield line.rstrip(b"\r")
    if buffer:
        yield buffer.rstrip(b"\r")


def _log_file_bounds(file_path: Path) -> tuple[datetime, datetime] | None:
    with file_path.open("rb") as stream:
        first_timestamp = next(
            (
                timestamp
                for line in stream
                if (timestamp := _parse_log_timestamp(line)) is not None
            ),
            None,
        )
        if first_timestamp is None:
            return None
        last_timestamp = next(
            (
                timestamp
                for line in _reverse_lines(stream)
                if (timestamp := _parse_log_timestamp(line)) is not None
            ),
            first_timestamp,
        )
    return first_timestamp, last_timestamp


def get_log_by_time(target_time: datetime, time_range: float = 1) -> list[Path]:
    folder = Path(get_path("@app/log"))
    range_delta = timedelta(hours=time_range)
    range_start = target_time - range_delta
    range_end = target_time + range_delta
    matching_files = []
    skipped_count = 0
    for file_path in folder.glob("runtime.log*"):
        if not file_path.is_file():
            continue
        try:
            bounds = _log_file_bounds(file_path)
        except OSError:
            skipped_count += 1
            continue
        if bounds is None:
            continue
        first_timestamp, last_timestamp = bounds
        if first_timestamp <= range_end and last_timestamp >= range_start:
            matching_files.append((first_timestamp, last_timestamp, file_path))
    if skipped_count:
        logger.warning(
            "operation=%s result=%s skipped_count=%d",
            "log_time_query",
            "partial",
            skipped_count,
        )
    matching_files.sort(key=lambda item: (item[0], item[1], item[2].name))
    return [item[2] for item in matching_files]
