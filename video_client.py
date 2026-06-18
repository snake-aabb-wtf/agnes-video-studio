"""
Agnes Video v2.0 — API 客户端封装

基于真实接口探测结果实现（文档 URL 有误，实际端点为单数 video）：
  - 提交任务：POST https://apihub.agnes-ai.com/v1/video/generations
  - 轮询任务：GET  https://apihub.agnes-ai.com/v1/video/generations/{task_id}
  - 模型：agnes-video-v2.0
  - 支持文生视频（text）与图生视频（image 作为首帧）
  - 异步任务模式：提交后返回 task_id，需轮询直到 status=SUCCESS
  - 完成后从 result_url 或 data.remixed_from_video_id 获取 mp4

文档参考：https://agnes-ai.com/doc/agnes-video-v20
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image

# 注意：实际端点是单数 /video/，文档里写的 /videos/ 是 404
BASE_URL = "https://apihub.agnes-ai.com/v1"
SUBMIT_URL = f"{BASE_URL}/video/generations"
MODEL = "agnes-video-v2.0"

# 分辨率（实测：API 接受 720p/480p/1080p，而非像素值；ratio 独立指定）
RESOLUTIONS = ["720p", "480p", "1080p"]
DEFAULT_RESOLUTION = "720p"
RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4"]
DEFAULT_RATIO = "16:9"
DEFAULT_SECONDS = "5"          # 视频时长（秒）
SECONDS_OPTIONS = ["5", "10"]

# 超时：提交 60s，轮询单次 30s，整体等待上限
SUBMIT_TIMEOUT = 60
POLL_TIMEOUT = 30
DEFAULT_MAX_WAIT = 600         # 最长轮询 10 分钟


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class VideoAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class VideoRequest:
    """一次视频生成请求。"""
    prompt: str
    api_key: str
    image: str | None = None        # 图生视频的首帧：URL 或本地路径
    resolution: str = DEFAULT_RESOLUTION   # 720p / 480p / 1080p
    ratio: str = DEFAULT_RATIO              # 16:9 / 9:16 / 1:1 / 4:3 / 3:4
    seconds: str = "5"
    model: str = MODEL

    def __post_init__(self):
        if not self.prompt.strip() and not self.image:
            raise ValueError("prompt 和 image 至少需要一项")
        if not self.api_key.strip():
            raise ValueError("api_key 不能为空")


@dataclass
class VideoTask:
    """任务状态（轮询结果）。"""
    task_id: str
    status: str                      # queued / IN_PROGRESS / SUCCESS / FAILED
    progress: int = 0                # 0-100
    video_url: str | None = None     # 完成后的 mp4 直链
    result_url: str | None = None    # 完成后的代理下载 URL
    seconds: str | None = None
    size: str | None = None
    fail_reason: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_done(self) -> bool:
        return self.status in ("SUCCESS", "FAILED", "failed", "succeeded")

    @property
    def is_success(self) -> bool:
        return self.status in ("SUCCESS", "succeeded")

    @property
    def best_url(self) -> str | None:
        """优先用直链 mp4，否则用代理下载 URL。"""
        return self.video_url or self.result_url


# ---------------------------------------------------------------------------
# 图片工具
# ---------------------------------------------------------------------------

def image_to_data_uri(path: str | Path, max_dim: int = 1280) -> str:
    """本地图片转 data URI 供图生视频使用。"""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

class VideoClient:
    """Agnes Video API 客户端。"""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or ""

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ---- 提交任务 ----

    def submit(self, req: VideoRequest, retries: int = 3) -> str:
        """提交视频生成任务，返回 task_id。网络错误自动重试。"""
        if not self.api_key:
            raise VideoAPIError("未设置 API Key")

        payload: dict = {
            "model": req.model,
            "prompt": req.prompt,
        }
        # 图生视频：image 字段
        if req.image:
            if req.image.startswith(("http://", "https://", "data:")):
                payload["image"] = req.image
            else:
                payload["image"] = image_to_data_uri(req.image)
        if req.resolution:
            payload["resolution"] = req.resolution
        if req.ratio:
            payload["ratio"] = req.ratio
        if req.seconds:
            payload["seconds"] = req.seconds

        last_err = None
        for attempt in range(retries):
            try:
                with httpx.Client(timeout=SUBMIT_TIMEOUT, follow_redirects=True) as c:
                    resp = c.post(SUBMIT_URL, json=payload, headers=self._headers())
            except httpx.TimeoutException as e:
                last_err = VideoAPIError(f"提交任务超时（{SUBMIT_TIMEOUT}s）")
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last_err from e
            except (httpx.ConnectError, httpx.ReadError) as e:
                # 网络/SSL 抖动，重试
                last_err = VideoAPIError(f"提交任务网络错误：{e}")
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last_err from e

        body = resp.text
        if resp.status_code >= 400:
            msg = body
            try:
                j = resp.json()
                err = j.get("error") or j
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                pass
            raise VideoAPIError(f"提交失败 {resp.status_code}: {msg}",
                                status_code=resp.status_code, body=body)
        try:
            data = resp.json()
        except ValueError as e:
            raise VideoAPIError(f"提交响应非 JSON: {body[:300]}") from e

        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise VideoAPIError(f"提交响应缺少 task_id: {data}")
        return task_id

    # ---- 轮询任务 ----

    def poll(self, task_id: str) -> VideoTask:
        """查询一次任务状态。"""
        url = f"{BASE_URL}/video/generations/{task_id}"
        try:
            with httpx.Client(timeout=POLL_TIMEOUT, follow_redirects=True) as c:
                resp = c.get(url, headers=self._headers())
        except httpx.TimeoutException as e:
            raise VideoAPIError(f"轮询超时（{POLL_TIMEOUT}s），稍后重试") from e
        except httpx.HTTPError as e:
            raise VideoAPIError(f"轮询网络错误：{e}") from e

        if resp.status_code >= 404:
            raise VideoAPIError(f"任务不存在或已过期 ({resp.status_code})",
                                status_code=resp.status_code)
        try:
            data = resp.json()
        except ValueError as e:
            raise VideoAPIError(f"轮询响应非 JSON") from e

        return self._parse_task(task_id, data)

    def _parse_task(self, task_id: str, data: dict) -> VideoTask:
        """从轮询响应解析任务状态。兼容两种结构（顶层 / data.data 嵌套）。"""
        d = data.get("data") if isinstance(data.get("data"), dict) else data
        status = (d.get("status") or "").upper()
        # progress 可能是 "30%" 字符串或 30 数字
        prog = d.get("progress", 0)
        if isinstance(prog, str):
            prog = int("".join(ch for ch in prog if ch.isdigit()) or 0)

        video_url = None
        result_url = d.get("result_url")
        # 完成时 mp4 直链可能藏在 data.remixed_from_video_id（实测字段名如此）
        inner = d.get("data") if isinstance(d.get("data"), dict) else {}
        if inner.get("remixed_from_video_id"):
            video_url = inner["remixed_from_video_id"]
        if not video_url and inner.get("url"):
            video_url = inner["url"]

        return VideoTask(
            task_id=task_id, status=status, progress=prog,
            video_url=video_url, result_url=result_url,
            seconds=d.get("seconds") or inner.get("seconds"),
            size=d.get("size") or inner.get("size"),
            fail_reason=d.get("fail_reason") or (inner.get("error") or ""),
            raw=data,
        )

    # ---- 等待完成（阻塞，带进度回调）----

    def wait_until_done(self, task_id: str, interval: float = 5.0,
                        max_wait: float = DEFAULT_MAX_WAIT,
                        on_progress=None) -> VideoTask:
        """轮询直到任务结束，on_progress(task) 回调用于 UI 更新。"""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                task = self.poll(task_id)
            except VideoAPIError as e:
                # 轮询单次失败不致命，继续重试
                if on_progress:
                    on_progress(None)
                time.sleep(interval)
                continue
            if on_progress:
                on_progress(task)
            if task.is_done:
                return task
            time.sleep(interval)
        raise VideoAPIError(f"任务等待超时（{max_wait:.0f}s）")

    # ---- 下载视频 ----

    def download(self, task: VideoTask, save_path: str | Path,
                 prefer_direct: bool = True) -> Path:
        """下载完成的视频到本地。优先直链 mp4（无需鉴权），回退代理 URL（需带 token）。"""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # (url, need_auth) —— 直链通常无需鉴权，代理 URL 需要 Bearer token
        attempts: list[tuple[str, bool]] = []
        if prefer_direct and task.video_url:
            attempts.append((task.video_url, False))
            attempts.append((task.video_url, True))   # 直链也试一次带鉴权
        if task.result_url:
            attempts.append((task.result_url, True))
        if not attempts:
            raise VideoAPIError("任务完成但未找到视频下载地址")

        last_err = None
        for url, need_auth in attempts:
            headers = self._headers() if need_auth else {"User-Agent": "agnes-video-tool/1.0"}
            try:
                with httpx.Client(timeout=300, follow_redirects=True) as c:
                    r = c.get(url, headers=headers)
                    r.raise_for_status()
                    if len(r.content) < 1000:
                        last_err = f"内容过小 ({len(r.content)}B)：{url}"
                        continue
                    save_path.write_bytes(r.content)
                    return save_path
            except httpx.HTTPError as e:
                last_err = f"{url} (auth={need_auth}): {e}"
                continue
        raise VideoAPIError(f"下载失败：{last_err}")


# ---------------------------------------------------------------------------
# CLI 自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, os, sys
    p = argparse.ArgumentParser(description="Agnes Video v2.0 客户端自测")
    p.add_argument("--api-key", "-k", default=os.environ.get("AGNES_API_KEY"))
    p.add_argument("--prompt", "-p", default="a cat walking on a beach, cinematic, 4k")
    p.add_argument("--image", "-i", help="图生视频首帧（路径或URL）")
    p.add_argument("--resolution", "-r", default=DEFAULT_RESOLUTION)
    p.add_argument("--seconds", default="5")
    p.add_argument("--out", "-o", default="agnes_video.mp4")
    args = p.parse_args()

    if not args.api_key:
        print("错误：请提供 --api-key 或环境变量 AGNES_API_KEY")
        sys.exit(1)

    client = VideoClient(args.api_key)
    req = VideoRequest(prompt=args.prompt, api_key=args.api_key,
                       image=args.image, resolution=args.resolution,
                       seconds=args.seconds)

    print(f"提交任务：{args.prompt[:50]}")
    t0 = time.time()
    task_id = client.submit(req)
    print(f"已提交，task_id={task_id}")

    def show_progress(task):
        if task is None:
            print("  轮询中…")
        else:
            print(f"  {task.status} {task.progress}%  ({time.time()-t0:.0f}s)")

    task = client.wait_until_done(task_id, on_progress=show_progress)
    if not task.is_success:
        print(f"\n[FAIL] {task.fail_reason or task.status}")
        sys.exit(1)

    print(f"\n[OK] 完成，耗时 {time.time()-t0:.0f}s")
    print(f"  视频直链：{task.video_url}")
    print(f"  代理 URL：{task.result_url}")
    path = client.download(task, args.out)
    print(f"  已保存：{path} ({path.stat().st_size/1024/1024:.1f}MB)")
