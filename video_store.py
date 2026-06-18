"""
Agnes Video 历史存储

SQLite 存储生成历史，视频文件存到用户数据目录，并抽取首帧作为缩略图。
配置（API Key 等）用 JSON 持久化。
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = "AgnesVideoStudio"
DATA_DIR = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
VIDEOS_DIR = DATA_DIR / "videos"
THUMBS_DIR = DATA_DIR / "thumbs"
DB_PATH = DATA_DIR / "history.db"


def _ensure_dirs():
    for d in (DATA_DIR, VIDEOS_DIR, THUMBS_DIR):
        d.mkdir(parents=True, exist_ok=True)


@dataclass
class VideoItem:
    id: int | None
    prompt: str
    mode: str                      # text2video / image2video
    resolution: str
    ratio: str
    seconds: str
    video_path: str                # 相对 VIDEOS_DIR
    thumb_path: str                # 相对 THUMBS_DIR
    task_id: str | None
    video_url: str | None          # 原始直链（可选）
    size_mb: float
    params: str                    # JSON
    created_at: float
    favorite: int = 0


class VideoStore:
    """SQLite 历史存储。线程安全（加锁）。"""

    def __init__(self, db_path: Path = DB_PATH):
        _ensure_dirs()
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt       TEXT NOT NULL,
                mode         TEXT NOT NULL,
                resolution   TEXT,
                ratio        TEXT,
                seconds      TEXT,
                video_path   TEXT NOT NULL,
                thumb_path   TEXT NOT NULL,
                task_id      TEXT,
                video_url    TEXT,
                size_mb      REAL,
                params       TEXT,
                created_at   REAL NOT NULL,
                favorite     INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_v_created ON history(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_v_fav ON history(favorite, created_at DESC);
            """)

    # ---- 写入 ----

    def _extract_thumbnail(self, video_path: Path, name: str) -> str:
        """用 ffmpeg 抽取首帧作为缩略图；无 ffmpeg 则生成占位图。"""
        thumb_name = f"{name}.png"
        thumb_path = THUMBS_DIR / thumb_name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1",
                 "-q:v", "3", "-vf", "scale=320:-1", str(thumb_path)],
                capture_output=True, timeout=30,
            )
            if thumb_path.exists() and thumb_path.stat().st_size > 0:
                return thumb_name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        # 无 ffmpeg：写一个占位文件名，UI 会显示默认占位图
        thumb_path.write_bytes(b"")
        return thumb_name

    def add(self, *, prompt: str, mode: str, resolution: str, ratio: str,
            seconds: str, video_bytes: bytes, task_id: str | None = None,
            video_url: str | None = None, params: dict | None = None) -> VideoItem:
        with self._lock:
            name = f"{int(time.time()*1000)}"
            video_name = f"{name}.mp4"
            (VIDEOS_DIR / video_name).write_bytes(video_bytes)
            thumb_name = self._extract_thumbnail(VIDEOS_DIR / video_name, name)
            ts = time.time()
            size_mb = len(video_bytes) / 1024 / 1024
            self._conn.execute(
                """INSERT INTO history
                   (prompt, mode, resolution, ratio, seconds, video_path, thumb_path,
                    task_id, video_url, size_mb, params, created_at, favorite)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (prompt, mode, resolution, ratio, seconds, video_name, thumb_name,
                 task_id, video_url, size_mb,
                 json.dumps(params or {}, ensure_ascii=False), ts),
            )
            self._conn.commit()
            row_id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return self._row_to_item(
                self._conn.execute("SELECT * FROM history WHERE id=?", (row_id,)).fetchone())

    # ---- 查询 ----

    def _row_to_item(self, row: sqlite3.Row) -> VideoItem:
        return VideoItem(
            id=row["id"], prompt=row["prompt"], mode=row["mode"],
            resolution=row["resolution"], ratio=row["ratio"], seconds=row["seconds"],
            video_path=row["video_path"], thumb_path=row["thumb_path"],
            task_id=row["task_id"], video_url=row["video_url"],
            size_mb=row["size_mb"], params=row["params"],
            created_at=row["created_at"], favorite=row["favorite"],
        )

    def list_all(self, favorites_only: bool = False, limit: int = 500) -> list[VideoItem]:
        with self._lock:
            if favorites_only:
                sql = "SELECT * FROM history WHERE favorite=1 ORDER BY created_at DESC LIMIT ?"
            else:
                sql = "SELECT * FROM history ORDER BY created_at DESC LIMIT ?"
            return [self._row_to_item(r) for r in self._conn.execute(sql, (limit,)).fetchall()]

    def search(self, keyword: str, limit: int = 200) -> list[VideoItem]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM history WHERE prompt LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{keyword}%", limit)).fetchall()
            return [self._row_to_item(r) for r in rows]

    def set_favorite(self, item_id: int, favorite: bool):
        with self._lock:
            self._conn.execute("UPDATE history SET favorite=? WHERE id=?",
                               (1 if favorite else 0, item_id))
            self._conn.commit()

    def delete(self, item_id: int):
        with self._lock:
            row = self._conn.execute("SELECT * FROM history WHERE id=?", (item_id,)).fetchone()
            if not row:
                return
            for rel, base in ((row["video_path"], VIDEOS_DIR), (row["thumb_path"], THUMBS_DIR)):
                try:
                    p = base / rel
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
            self._conn.execute("DELETE FROM history WHERE id=?", (item_id,))
            self._conn.commit()

    def clear_all(self):
        with self._lock:
            self._conn.execute("DELETE FROM history")
            self._conn.commit()
        for d in (VIDEOS_DIR, THUMBS_DIR):
            for p in d.glob("*"):
                try:
                    p.unlink()
                except OSError:
                    pass

    @staticmethod
    def video_fullpath(item: VideoItem) -> Path:
        return VIDEOS_DIR / item.video_path

    @staticmethod
    def thumb_fullpath(item: VideoItem) -> Path:
        return THUMBS_DIR / item.thumb_path

    def close(self):
        with self._lock:
            self._conn.close()


class ConfigStore:
    """应用配置的 JSON 持久化。"""

    def __init__(self):
        _ensure_dirs()
        self.path = DATA_DIR / "config.json"
        self._data: dict = {}
        self._lock = threading.Lock()
        self.load()

    def load(self):
        with self._lock:
            if self.path.exists():
                try:
                    self._data = json.loads(self.path.read_text(encoding="utf-8"))
                except Exception:
                    self._data = {}

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._data[key] = value
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def all(self) -> dict:
        with self._lock:
            return dict(self._data)
