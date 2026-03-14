import os
import threading
import yaml
import structlog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

log = structlog.get_logger()

_lock = threading.Lock()
_config: dict = {"subreddits": [], "scrape_interval_hours": 1, "lookback_hours": 24}


def _load_file(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _apply(raw: dict):
    global _config
    with _lock:
        _config = raw
    log.info(
        "config reloaded",
        subreddits=raw.get("subreddits"),
        interval=raw.get("scrape_interval_hours"),
    )


def get_subreddits() -> list[str]:
    # SUBREDDITS env var overrides YAML
    env = os.environ.get("SUBREDDITS", "").strip()
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    with _lock:
        subs = _config.get("subreddits", [])
    return [f"r/{s}" if not s.startswith("r/") else s for s in subs]


def get_lookback_hours() -> int:
    with _lock:
        return int(_config.get("lookback_hours", os.environ.get("LOOKBACK_HOURS", 24)))


class _ReloadHandler(FileSystemEventHandler):
    def __init__(self, path: str):
        self._path = path

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(
            os.path.basename(self._path)
        ):
            try:
                _apply(_load_file(self._path))
            except Exception:
                log.exception("failed to reload config")

    on_created = on_modified


def start(config_path: str | None = None):
    path = config_path or os.environ.get("CONFIG_PATH", "/app/config/subreddits.yaml")
    try:
        _apply(_load_file(path))
    except FileNotFoundError:
        log.warning("config file not found, using defaults", path=path)

    observer = Observer()
    observer.schedule(_ReloadHandler(path), path=os.path.dirname(path), recursive=False)
    observer.daemon = True
    observer.start()
    log.info("watching config file", path=path)
