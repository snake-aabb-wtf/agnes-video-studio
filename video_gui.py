"""
Agnes Video Studio — PySide6 视频生成器 (主程序)

三栏界面：
  左栏：参数面板（API Key、模式切换、Prompt、分辨率/比例/时长、首帧拖拽、生成）
  中栏：视频预览（QMediaPlayer 播放）+ 实时轮询进度条
  右栏：历史画廊（缩略图、复用参数、收藏、搜索）

功能：文生视频 / 图生视频 / 异步轮询进度 / 视频播放 / 历史画廊(SQLite) /
      提示词模板与收藏 / 另存为 / 深色主题

启动：python video_gui.py
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    Qt, QThread, Signal, QSize, QTimer, QUrl, QMimeData, QRectF,
)
from PySide6.QtGui import (
    QPixmap, QImage, QIcon, QKeySequence, QShortcut, QColor, QFont, QPalette,
    QDragEnterEvent, QDropEvent, QPainter,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, QSpinBox, QCheckBox,
    QFileDialog, QMessageBox, QStatusBar, QProgressBar, QGroupBox,
    QGridLayout, QListWidget, QListWidgetItem, QMenu, QToolButton, QFrame,
    QDialog, QFormLayout, QDialogButtonBox, QSlider,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

import qtawesome as qta

from video_client import (
    VideoClient, VideoRequest, VideoTask, VideoAPIError,
    MODEL, RESOLUTIONS, RATIOS, SECONDS_OPTIONS,
    DEFAULT_RESOLUTION, DEFAULT_RATIO,
)
from video_store import VideoStore, ConfigStore, VideoItem

# ===========================================================================
# 提示词模板
# ===========================================================================

BUILTIN_TEMPLATES = [
    ("电影感", "cinematic, dramatic lighting, slow motion, shallow depth of field, 4k, film grain"),
    ("动漫风", "anime style, vibrant colors, cel shading, smooth animation, studio ghibli inspired"),
    ("写实", "photorealistic, ultra detailed, natural lighting, 4k uhd, documentary style"),
    ("梦幻", "dreamy, ethereal, soft glow, particles, bokeh, fantasy atmosphere, magical"),
    ("赛博朋克", "cyberpunk, neon lights, futuristic city, rain reflections, blade runner aesthetic"),
    ("自然纪录", "nature documentary, wildlife, golden hour, ultra detailed, national geographic style"),
    ("3D 动画", "3d animation, pixar style, smooth, colorful, cinematic, high quality render"),
    ("史诗感", "epic, grand scale, sweeping camera, dramatic clouds, cinematic masterpiece"),
]

# ===========================================================================
# 深色主题样式
# ===========================================================================

DARK_QSS = """
QMainWindow, QDialog { background-color: #1e1e2e; }
QWidget { color: #cdd6f4; font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#titleLabel { font-size: 18px; font-weight: bold; color: #89b4fa; }
QLabel#hintLabel { color: #6c7086; font-size: 11px; }
QLabel#infoLabel { color: #a6adc8; font-size: 11px; }
QGroupBox { border: 1px solid #313244; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; background-color: #181825; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #89b4fa; font-weight: bold; }
QLineEdit, QTextEdit, QComboBox, QSpinBox { background-color: #313244; border: 1px solid #45475a; border-radius: 6px; padding: 6px 8px; selection-background-color: #89b4fa; color: #cdd6f4; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #89b4fa; }
QTextEdit { font-size: 13px; }
QPushButton { background-color: #45475a; border: 1px solid #585b70; border-radius: 6px; padding: 7px 14px; color: #cdd6f4; }
QPushButton:hover { background-color: #585b70; border-color: #89b4fa; }
QPushButton:pressed { background-color: #313244; }
QPushButton:disabled { color: #6c7086; background-color: #2a2a3c; }
QPushButton#primaryBtn { background-color: #89b4fa; color: #1e1e2e; font-weight: bold; border: none; }
QPushButton#primaryBtn:hover { background-color: #b4befe; }
QPushButton#primaryBtn:disabled { background-color: #45475a; color: #6c7086; }
QComboBox QAbstractItemView { background-color: #313244; selection-background-color: #89b4fa; color: #cdd6f4; border: 1px solid #45475a; }
QListWidget { background-color: #181825; border: 1px solid #313244; border-radius: 6px; }
QListWidget::item { border-radius: 4px; padding: 2px; }
QListWidget::item:selected { background-color: #313244; }
QScrollBar:vertical { background: #181825; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #45475a; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #181825; height: 12px; margin: 0; }
QScrollBar::handle:horizontal { background: #45475a; border-radius: 6px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #585b70; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background-color: #313244; }
QSplitter::handle:horizontal { width: 2px; }
QStatusBar { background-color: #181825; border-top: 1px solid #313244; }
QProgressBar { background-color: #313244; border: 1px solid #45475a; border-radius: 6px; text-align: center; height: 18px; color: #cdd6f4; }
QProgressBar::chunk { background-color: #89b4fa; border-radius: 5px; }
QMenu { background-color: #313244; border: 1px solid #45475a; }
QMenu::item:selected { background-color: #45475a; }
QToolTip { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; }
QFrame#dropFrame { border: 2px dashed #45475a; border-radius: 8px; background-color: #181825; }
QFrame#dropFrame[dragOver="true"] { border-color: #89b4fa; background-color: #1e1e2e; }
QVideoWidget { background-color: #000000; border-radius: 6px; }
"""


# ===========================================================================
# 工作线程：提交 + 轮询 + 下载
# ===========================================================================

class VideoWorker(QThread):
    """后台：提交任务 → 轮询进度 → 下载视频。"""
    progress = Signal(int, str)        # (percent, status_text)
    submitted = Signal(str)            # task_id
    finished_ok = Signal(object, str)  # (video_bytes, video_url)
    failed = Signal(str)

    def __init__(self, client: VideoClient, req: VideoRequest):
        super().__init__()
        self.client = client
        self.req = req
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            t0 = time.time()
            self.progress.emit(0, "正在提交生成任务…")
            task_id = self.client.submit(self.req)
            self.submitted.emit(task_id)

            # 轮询
            last_pct = -1
            deadline = time.time() + 600
            while time.time() < deadline and not self._stop:
                try:
                    task = self.client.poll(task_id)
                except VideoAPIError:
                    self.progress.emit(last_pct, "轮询中…")
                    self._sleep(5)
                    continue

                status_map = {"QUEUED": "排队中", "NOT_START": "等待开始",
                              "IN_PROGRESS": "生成中", "SUCCESS": "完成", "FAILED": "失败"}
                status_text = status_map.get(task.status, task.status)
                self.progress.emit(task.progress, f"{status_text} {task.progress}%")

                if task.is_done:
                    break
                last_pct = task.progress
                self._sleep(5)

            if self._stop:
                self.failed.emit("已取消")
                return

            if not task.is_success:
                self.failed.emit(f"生成失败：{task.fail_reason or task.status}")
                return

            # 下载
            self.progress.emit(99, "正在下载视频…")
            import tempfile
            tmp = Path(tempfile.gettempdir()) / f"agnes_video_{int(time.time()*1000)}.mp4"
            self.client.download(task, tmp)
            video_bytes = tmp.read_bytes()
            try:
                tmp.unlink()
            except OSError:
                pass
            self.progress.emit(100, f"完成，耗时 {time.time()-t0:.0f}s")
            self.finished_ok.emit(video_bytes, task.best_url or "")
        except VideoAPIError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"未预期的错误：{e}\n{traceback.format_exc()[-300:]}")

    def _sleep(self, secs):
        """可中断的 sleep。"""
        end = time.time() + secs
        while time.time() < end and not self._stop:
            time.sleep(0.2)


# ===========================================================================
# 首帧拖拽区
# ===========================================================================

class FirstFrameDrop(QFrame):
    """图生视频的首帧图片拖拽/选择区。"""
    imageChanged = Signal(object)  # bytes | None

    def __init__(self):
        super().__init__()
        self.setObjectName("dropFrame")
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.setMaximumHeight(140)
        self._bytes = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.label = QLabel("拖拽图片到此处，或点击选择\n作为视频首帧（图生视频）")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(self.label)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.hide()
        layout.addWidget(self.preview)

        btn_row = QHBoxLayout()
        self.browse_btn = QPushButton(qta.icon("fa5s.folder-open", color="#89b4fa"), " 选择")
        self.clear_btn = QPushButton(qta.icon("fa5s.times", color="#f38ba8"), " 清除")
        btn_row.addStretch()
        btn_row.addWidget(self.browse_btn)
        btn_row.addWidget(self.clear_btn)
        layout.addLayout(btn_row)

        self.browse_btn.clicked.connect(self._browse)
        self.clear_btn.clicked.connect(self._clear)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择首帧图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            self._bytes = Path(path).read_bytes()
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return
        pix = QPixmap(path)
        self._show(pix, os.path.basename(path))
        self.imageChanged.emit(self._bytes)

    def _show(self, pix, name):
        self.label.hide()
        self.preview.show()
        self.preview.setPixmap(pix.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.browse_btn.setText(" 更换")
        self.setToolTip(name)

    def _clear(self):
        self._bytes = None
        self.preview.hide()
        self.preview.clear()
        self.label.show()
        self.browse_btn.setText(" 选择")
        self.imageChanged.emit(None)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()
            self.setProperty("dragOver", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, _):
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, e: QDropEvent):
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)
        md = e.mimeData()
        if md.hasImage():
            img = QImage(md.imageData())
            from PySide6.QtCore import QBuffer
            buf = QBuffer()
            buf.open(QBuffer.ReadWrite)
            img.save(buf, "PNG")
            self._bytes = buf.data().data()
            self._show(QPixmap.fromImage(img), "pasted.png")
            self.imageChanged.emit(self._bytes)
            return
        if md.hasUrls():
            for url in md.urls():
                p = url.toLocalFile()
                if p and Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                    self._load_file(p)
                    return

    def get_bytes(self) -> bytes | None:
        return self._bytes


# ===========================================================================
# 历史画廊
# ===========================================================================

class VideoGallery(QListWidget):
    reuseRequested = Signal(object)
    viewRequested = Signal(object)
    favoriteToggled = Signal(object)
    deleted = Signal(int)

    THUMB_W = 150

    def __init__(self, store: VideoStore):
        super().__init__()
        self.store = store
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(self.THUMB_W, self.THUMB_W))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.itemDoubleClicked.connect(self._on_double)
        self.customContextMenuRequested.connect(self._on_context)

    def refresh(self, items: list[VideoItem]):
        self.clear()
        for it in items:
            thumb_path = self.store.thumb_fullpath(it)
            pix = QPixmap(str(thumb_path)) if thumb_path.exists() and thumb_path.stat().st_size > 0 else None
            square = QPixmap(self.THUMB_W, self.THUMB_W)
            square.fill(QColor("#11111b"))
            p = QPainter(square)
            if pix and not pix.isNull():
                scaled = pix.scaled(self.THUMB_W, self.THUMB_W, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap((self.THUMB_W - scaled.width()) // 2,
                             (self.THUMB_W - scaled.height()) // 2, scaled)
            else:
                p.setPen(QColor("#6c7086"))
                p.setFont(QFont("Microsoft YaHei UI", 11))
                p.drawText(QRectF(0, self.THUMB_W/2 - 20, self.THUMB_W, 40),
                           Qt.AlignCenter, "🎬\n视频")
            # 播放图标叠加
            p.setPen(QColor("#89b4fa"))
            p.setFont(QFont("Segoe UI Emoji", 20))
            p.drawText(QRectF(self.THUMB_W/2 - 15, self.THUMB_W/2 - 15, 30, 30), Qt.AlignCenter, "▶")
            if it.favorite:
                p.setPen(QColor("#f9e2af"))
                p.drawText(QRectF(self.THUMB_W - 20, 2, 18, 16), Qt.AlignCenter, "★")
            p.end()

            li = QListWidgetItem(QIcon(square), "")
            li.setData(Qt.UserRole, it)
            mode = {"text2video": "文生视频", "image2video": "图生视频"}.get(it.mode, it.mode)
            li.setToolTip(
                f"{it.prompt[:60]}\n━━━━━━━━\n模式: {mode}\n{it.resolution} {it.ratio} {it.seconds}s\n"
                f"{it.size_mb:.1f}MB\n时间: {datetime.fromtimestamp(it.created_at):%Y-%m-%d %H:%M}"
                f"\n{'★ 已收藏' if it.favorite else '右键收藏'}")
            li.setSizeHint(QSize(self.THUMB_W + 8, self.THUMB_W + 8))
            self.addItem(li)

    def _item(self, item):
        return item.data(Qt.UserRole)

    def _on_double(self, item):
        it = self._item(item)
        if it:
            self.viewRequested.emit(it)

    def _on_context(self, pos):
        item = self.itemAt(pos)
        if not item:
            return
        it = self._item(item)
        if not it:
            return
        menu = QMenu(self)
        a_view = menu.addAction(qta.icon("fa5s.play", color="#89b4fa"), "播放")
        a_reuse = menu.addAction(qta.icon("fa5s.redo", color="#a6e3a1"), "复用参数")
        menu.addSeparator()
        a_fav = menu.addAction(qta.icon("fa5s.star", color="#f9e2af"),
                               "取消收藏" if it.favorite else "加入收藏")
        a_save = menu.addAction(qta.icon("fa5s.download", color="#89b4fa"), "另存为…")
        a_open = menu.addAction(qta.icon("fa5s.folder-open", color="#89b4fa"), "打开所在文件夹")
        menu.addSeparator()
        a_del = menu.addAction(qta.icon("fa5s.trash", color="#f38ba8"), "删除")

        action = menu.exec(self.mapToGlobal(pos))
        if action == a_view:
            self.viewRequested.emit(it)
        elif action == a_reuse:
            self.reuseRequested.emit(it)
        elif action == a_fav:
            self.favoriteToggled.emit(it)
        elif action == a_save:
            dst, _ = QFileDialog.getSaveFileName(
                self, "另存为", f"{it.prompt[:20]}.mp4", "MP4 视频 (*.mp4)")
            if dst:
                try:
                    Path(dst).write_bytes(Path(self.store.video_fullpath(it)).read_bytes())
                except Exception as e:
                    QMessageBox.warning(self, "保存失败", str(e))
        elif action == a_open:
            os.system(f'explorer /select,"{self.store.video_fullpath(it)}"')
        elif action == a_del:
            self.deleted.emit(it.id)


# ===========================================================================
# 主窗口
# ===========================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Agnes Video Studio — 视频生成器")
        self.resize(1280, 820)
        self.setMinimumSize(960, 640)

        self.config = ConfigStore()
        self.store = VideoStore()
        self.worker: VideoWorker | None = None
        self._cur_task_id = None

        # 视频播放器
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)

        self._build_ui()
        self._load_settings()
        self._refresh_history()
        self._setup_shortcuts()
        self.status(f"就绪。模型：{MODEL} ｜ 数据目录：{self.store.db_path.parent}")

    # ------------------- UI -------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        topbar = QHBoxLayout()
        title = QLabel("🎬 Agnes Video Studio")
        title.setObjectName("titleLabel")
        topbar.addWidget(title)
        topbar.addStretch()
        self.fav_only_btn = QPushButton(qta.icon("fa5s.star", color="#f9e2af"), " 仅收藏")
        self.fav_only_btn.setCheckable(True)
        self.fav_only_btn.toggled.connect(lambda _: self._refresh_history())
        topbar.addWidget(self.fav_only_btn)
        self.settings_btn = QPushButton(qta.icon("fa5s.cog", color="#89b4fa"), " 设置")
        self.settings_btn.clicked.connect(self._open_settings)
        topbar.addWidget(self.settings_btn)
        root.addLayout(topbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([320, 640, 260])
        root.addWidget(splitter, 1)

        sb = QStatusBar()
        self.setStatusBar(sb)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(260)
        sb.addPermanentWidget(self.progress_bar)
        self._status_label = QLabel("就绪")
        sb.addWidget(self._status_label, 1)

    def _build_left(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(8)

        # API Key
        gb_key = QGroupBox("API Key")
        gl = QVBoxLayout(gb_key)
        gl.setContentsMargins(10, 16, 10, 10)
        kr = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-...")
        kr.addWidget(self.key_edit, 1)
        self.key_show = QToolButton()
        self.key_show.setCheckable(True)
        self.key_show.setIcon(qta.icon("fa5s.eye", color="#89b4fa"))
        self.key_show.toggled.connect(self._toggle_key)
        kr.addWidget(self.key_show)
        gl.addLayout(kr)
        v.addWidget(gb_key)

        # 模式
        gb_mode = QGroupBox("生成模式")
        gm = QHBoxLayout(gb_mode)
        gm.setContentsMargins(10, 16, 10, 10)
        self.mode_txt = QPushButton(qta.icon("fa5s.keyboard", color="#89b4fa"), " 文生视频")
        self.mode_img = QPushButton(qta.icon("fa5s.image", color="#89b4fa"), " 图生视频")
        for b in (self.mode_txt, self.mode_img):
            b.setCheckable(True)
            gm.addWidget(b)
        self.mode_txt.setChecked(True)
        self.mode_txt.clicked.connect(lambda: self._set_mode("text2video"))
        self.mode_img.clicked.connect(lambda: self._set_mode("image2video"))
        v.addWidget(gb_mode)

        # 首帧拖拽
        self.frame_drop = FirstFrameDrop()
        self.frame_drop.imageChanged.connect(self._on_frame_changed)
        self.frame_drop.hide()
        v.addWidget(self.frame_drop)

        # Prompt
        gb_p = QGroupBox("提示词 Prompt")
        gp = QVBoxLayout(gb_p)
        gp.setContentsMargins(10, 16, 10, 10)
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("描述你想生成的视频…（Ctrl+Enter 生成）")
        self.prompt_edit.setMinimumHeight(80)
        gp.addWidget(self.prompt_edit, 1)

        # 模板
        tr = QHBoxLayout()
        tr.addWidget(QLabel("模板:"))
        self.template_combo = QComboBox()
        self.template_combo.addItem("（不套用模板）", "")
        for name, val in BUILTIN_TEMPLATES:
            self.template_combo.addItem(name, val)
        self.template_combo.setToolTip("选择风格模板后，生成时自动拼接风格词，不改动输入框。")
        tr.addWidget(self.template_combo, 1)
        gp.addLayout(tr)

        # 收藏
        fr = QHBoxLayout()
        self.fav_combo = QComboBox()
        self.fav_combo.addItem("我的收藏提示词…", "")
        self.fav_combo.currentIndexChanged.connect(self._use_fav)
        fr.addWidget(QLabel("收藏:"), 0)
        fr.addWidget(self.fav_combo, 1)
        self.add_fav_btn = QPushButton(qta.icon("fa5s.bookmark", color="#f9e2af"), " 收藏当前")
        self.add_fav_btn.clicked.connect(self._add_fav)
        fr.addWidget(self.add_fav_btn)
        gp.addLayout(fr)
        v.addWidget(gb_p, 1)

        # 参数
        gb_param = QGroupBox("参数")
        gpa = QGridLayout(gb_param)
        gpa.setContentsMargins(10, 16, 10, 10)
        gpa.setHorizontalSpacing(8)
        gpa.setVerticalSpacing(8)
        gpa.addWidget(QLabel("分辨率:"), 0, 0)
        self.res_combo = QComboBox()
        for r in RESOLUTIONS:
            self.res_combo.addItem(r)
        self.res_combo.setCurrentText(DEFAULT_RESOLUTION)
        gpa.addWidget(self.res_combo, 0, 1)
        gpa.addWidget(QLabel("比例:"), 1, 0)
        self.ratio_combo = QComboBox()
        for r in RATIOS:
            self.ratio_combo.addItem(r)
        self.ratio_combo.setCurrentText(DEFAULT_RATIO)
        gpa.addWidget(self.ratio_combo, 1, 1)
        gpa.addWidget(QLabel("时长:"), 2, 0)
        self.seconds_combo = QComboBox()
        for s in SECONDS_OPTIONS:
            self.seconds_combo.addItem(f"{s} 秒", s)
        gpa.addWidget(self.seconds_combo, 2, 1)
        v.addWidget(gb_param)

        # 生成按钮
        self.gen_btn = QPushButton(qta.icon("fa5s.film", color="#1e1e2e"), "  生成视频")
        self.gen_btn.setObjectName("primaryBtn")
        self.gen_btn.setMinimumHeight(42)
        self.gen_btn.clicked.connect(self._on_generate)
        v.addWidget(self.gen_btn)

        self.cur_mode = "text2video"
        self.cur_frame_bytes: bytes | None = None
        return panel

    def _build_center(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("预览"))
        bar.addStretch()
        self.play_btn = QPushButton(qta.icon("fa5s.play", color="#89b4fa"), " 播放")
        self.play_btn.clicked.connect(self._toggle_play)
        self.mute_btn = QPushButton(qta.icon("fa5s.volume-up", color="#89b4fa"), " 静音")
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self._toggle_mute)
        self.save_btn = QPushButton(qta.icon("fa5s.download", color="#89b4fa"), " 另存为")
        self.save_btn.clicked.connect(self._save_current)
        for b in (self.play_btn, self.mute_btn, self.save_btn):
            bar.addWidget(b)
        v.addLayout(bar)

        # 视频播放控件
        self.video_widget = QVideoWidget()
        self.player.setVideoOutput(self.video_widget)
        v.addWidget(self.video_widget, 1)

        # 进度条（生成时显示）
        self.gen_progress = QProgressBar()
        self.gen_progress.setRange(0, 100)
        self.gen_progress.setValue(0)
        self.gen_progress.setFormat("就绪")
        v.addWidget(self.gen_progress)

        # 信息
        self.info_label = QLabel("")
        self.info_label.setObjectName("infoLabel")
        self.info_label.setWordWrap(True)
        self.info_label.setFrameShape(QFrame.StyledPanel)
        self.info_label.setStyleSheet("padding:6px;")
        v.addWidget(self.info_label)

        self._current_video_path: Path | None = None
        return panel

    def _build_right(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)
        h = QHBoxLayout()
        h.addWidget(QLabel("历史画廊"))
        h.addStretch()
        self.history_count = QLabel("0")
        self.history_count.setObjectName("infoLabel")
        h.addWidget(self.history_count)
        v.addLayout(h)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索提示词…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._refresh_history)
        v.addWidget(self.search_edit)

        self.gallery = VideoGallery(self.store)
        self.gallery.viewRequested.connect(self._play_history)
        self.gallery.reuseRequested.connect(self._reuse_history)
        self.gallery.favoriteToggled.connect(self._toggle_fav)
        self.gallery.deleted.connect(self._delete_history)
        v.addWidget(self.gallery, 1)
        return panel

    # ------------------- 行为 -------------------
    def _load_settings(self):
        if self.config.get("save_key", True):
            key = self.config.get("api_key", "")
            if key:
                self.key_edit.setText(key)
        self._reload_fav()

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._on_generate)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._on_generate)
        QShortcut(QKeySequence("Space"), self, activated=self._toggle_play)

    def _toggle_key(self, on):
        self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self.key_show.setIcon(qta.icon("fa5s.eye-slash" if on else "fa5s.eye", color="#89b4fa"))

    def _open_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        dlg.setMinimumWidth(380)
        form = QFormLayout(dlg)
        form.setContentsMargins(20, 20, 20, 20)
        self.save_key_chk = QCheckBox("自动保存 API Key 到本地")
        self.save_key_chk.setChecked(bool(self.config.get("save_key", True)))
        form.addRow("", self.save_key_chk)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec():
            self.config.set("save_key", self.save_key_chk.isChecked())

    def _set_mode(self, mode):
        self.cur_mode = mode
        if mode == "image2video":
            self.mode_txt.setChecked(False)
            self.mode_img.setChecked(True)
            self.frame_drop.show()
        else:
            self.mode_txt.setChecked(True)
            self.mode_img.setChecked(False)
            self.frame_drop.hide()

    def _on_frame_changed(self, data):
        self.cur_frame_bytes = data

    def _build_prompt(self) -> str:
        user = self.prompt_edit.toPlainText().strip()
        snippet = (self.template_combo.currentData() or "").strip()
        if not snippet:
            return user
        return f"{user}, {snippet}" if user else snippet

    def _use_fav(self, idx):
        if idx <= 0:
            return
        text = self.fav_combo.itemData(idx)
        if text:
            self.prompt_edit.setPlainText(text)
        QTimer.singleShot(0, lambda: self.fav_combo.setCurrentIndex(0))

    def _reload_fav(self):
        favs = self.config.get("fav_prompts", []) or []
        self.fav_combo.clear()
        self.fav_combo.addItem("我的收藏提示词…", "")
        for fp in favs:
            self.fav_combo.addItem(fp[:40], fp)

    def _add_fav(self):
        text = self.prompt_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "提示词为空，无法收藏。")
            return
        favs = self.config.get("fav_prompts", []) or []
        if text in favs:
            QMessageBox.information(self, "提示", "该提示词已收藏。")
            return
        favs.append(text)
        self.config.set("fav_prompts", favs)
        self._reload_fav()
        self.status("已收藏当前提示词")

    # ------------------- 生成 -------------------
    def _on_generate(self):
        api_key = self.key_edit.text().strip()
        user_prompt = self.prompt_edit.toPlainText().strip()
        if not api_key:
            QMessageBox.warning(self, "缺少 API Key", "请先输入 Agnes API Key。")
            return
        if not user_prompt:
            QMessageBox.warning(self, "缺少提示词", "请输入提示词 Prompt。")
            return
        if self.cur_mode == "image2video" and not self.cur_frame_bytes:
            QMessageBox.warning(self, "缺少首帧", "图生视频模式下请先拖入或选择首帧图片。")
            return

        final_prompt = self._build_prompt()
        if self.config.get("save_key", True):
            self.config.set("api_key", api_key)

        # 保存首帧到临时文件
        frame_path = None
        if self.cur_mode == "image2video" and self.cur_frame_bytes:
            import tempfile
            frame_path = Path(tempfile.gettempdir()) / f"agnes_frame_{int(time.time()*1000)}.png"
            frame_path.write_bytes(self.cur_frame_bytes)

        try:
            req = VideoRequest(
                prompt=final_prompt, api_key=api_key,
                resolution=self.res_combo.currentText(),
                ratio=self.ratio_combo.currentText(),
                seconds=self.seconds_combo.currentData(),
                image=str(frame_path) if frame_path else None,
            )
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return

        self._set_generating(True)
        self.gen_progress.setValue(0)
        self.gen_progress.setFormat("提交中…")
        self.client = VideoClient(api_key)
        self.worker = VideoWorker(self.client, req)
        self.worker.progress.connect(self._on_progress)
        self.worker.submitted.connect(self._on_submitted)
        self.worker.finished_ok.connect(self._on_result)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_submitted(self, task_id):
        self._cur_task_id = task_id
        self.status(f"已提交，任务 ID：{task_id[:24]}…")

    def _on_progress(self, pct, text):
        self.gen_progress.setValue(pct)
        self.gen_progress.setFormat(f"{text} (%p%)")
        self.status(text)

    def _set_generating(self, on):
        self.gen_btn.setEnabled(not on)
        self.gen_btn.setText("  生成中…" if on else "  生成视频")
        if on:
            self.status("正在生成…")

    def _on_result(self, video_bytes, video_url):
        self._set_generating(False)
        final_prompt = self._build_prompt()
        # 存历史
        try:
            item = self.store.add(
                prompt=final_prompt, mode=self.cur_mode,
                resolution=self.res_combo.currentText(),
                ratio=self.ratio_combo.currentText(),
                seconds=self.seconds_combo.currentData(),
                video_bytes=video_bytes, task_id=self._cur_task_id,
                video_url=video_url,
            )
        except Exception as e:
            print("写入历史失败:", e)
            item = None

        # 播放刚生成的视频
        if item:
            self._play_file(self.store.video_fullpath(item), item)
        self._refresh_history()
        self.gen_progress.setFormat("完成")
        self.status(f"生成完成，已存入历史画廊")

    def _on_failed(self, msg):
        self._set_generating(False)
        self.gen_progress.setFormat("失败")
        self.status("生成失败")
        QMessageBox.critical(self, "生成失败", msg)

    # ------------------- 播放 -------------------
    def _play_file(self, path: Path, item: VideoItem | None = None):
        self._current_video_path = path
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self.play_btn.setText(" ⏸ 暂停")
        if item:
            mode = {"text2video": "文生视频", "image2video": "图生视频"}.get(item.mode, item.mode)
            self.info_label.setText(
                f"{mode}  |  {item.resolution} {item.ratio} {item.seconds}s  |  {item.size_mb:.1f}MB\n"
                f"提示词: {item.prompt}")

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_btn.setText(" ▶ 播放")
        else:
            self.player.play()
            self.play_btn.setText(" ⏸ 暂停")

    def _toggle_mute(self, on):
        self.audio_output.setMuted(on)
        self.mute_btn.setIcon(qta.icon("fa5s.volume-off" if on else "fa5s.volume-up", color="#89b4fa"))
        self.mute_btn.setText(" 取消静音" if on else " 静音")

    def _save_current(self):
        if not self._current_video_path or not self._current_video_path.exists():
            QMessageBox.information(self, "提示", "暂无可保存的视频。")
            return
        name = self.prompt_edit.toPlainText().strip()[:20] or "agnes_video"
        dst, _ = QFileDialog.getSaveFileName(self, "另存为", f"{name}.mp4", "MP4 视频 (*.mp4)")
        if dst:
            try:
                Path(dst).write_bytes(self._current_video_path.read_bytes())
                self.status(f"已保存：{dst}")
            except Exception as e:
                QMessageBox.warning(self, "保存失败", str(e))

    # ------------------- 历史 -------------------
    def _refresh_history(self):
        kw = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
        fav = self.fav_only_btn.isChecked() if hasattr(self, "fav_only_btn") else False
        if kw:
            items = self.store.search(kw)
        elif fav:
            items = self.store.list_all(favorites_only=True)
        else:
            items = self.store.list_all()
        self.gallery.refresh(items)
        self.history_count.setText(f"{len(items)} 个")

    def _play_history(self, it: VideoItem):
        self._play_file(self.store.video_fullpath(it), it)
        self.status(f"播放历史视频 (id={it.id})")

    def _reuse_history(self, it: VideoItem):
        self.prompt_edit.setPlainText(it.prompt)
        self.res_combo.setCurrentText(it.resolution)
        self.ratio_combo.setCurrentText(it.ratio)
        for i in range(self.seconds_combo.count()):
            if self.seconds_combo.itemData(i) == it.seconds:
                self.seconds_combo.setCurrentIndex(i)
                break
        self._set_mode("text2video")
        self.status("已复用历史参数，点击「生成视频」重新生成")

    def _toggle_fav(self, it: VideoItem):
        self.store.set_favorite(it.id, not it.favorite)
        self._refresh_history()

    def _delete_history(self, item_id):
        reply = QMessageBox.question(
            self, "删除确认", "确定删除这个视频吗？不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.store.delete(item_id)
            self._refresh_history()
            self.status(f"已删除 (id={item_id})")

    # ------------------- 杂项 -------------------
    def status(self, msg):
        self._status_label.setText(msg)

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "正在生成", "视频正在生成中，确定退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                e.ignore()
                return
            self.worker.stop()
            self.worker.wait(3000)
        self.player.stop()
        self.store.close()
        e.accept()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Agnes Video Studio")
    app.setWindowIcon(qta.icon("fa5s.film", color="#89b4fa"))
    app.setStyleSheet(DARK_QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
