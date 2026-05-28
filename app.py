import json
import math
import os
import random
import sys
import time
from copy import deepcopy
from pathlib import Path

import imageio
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat, ImageTk


APP_TITLE = "奶牛猫桌面助手"
def get_runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = get_runtime_dir()
DATA_PATH = BASE_DIR / "assistant_state.json"
LOG_PATH = BASE_DIR / "assistant_runtime.log"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


DEFAULT_STATE = {
    "tasks": [
        {"text": "先推进今天最重要的一件事", "done": False},
        {"text": "留一个 25 分钟专注块", "done": False},
    ],
    "notes": "欢迎来到奶牛猫驾驶舱。\n把今天要推进的事留在这里。",
    "focus_minutes": 25,
}


CAT_LINES = {
    "idle": [
        "路还很长，但先动起来就已经赢一半。",
        "今天不用全通关，先把第一段路跑顺。",
        "方向盘很稳，我们先做最重要的那件事。",
    ],
    "focus": [
        "进入专注路段，别切太多窗口。",
        "这段路我陪你盯着，先把它开过去。",
        "现在适合埋头推进，不适合分神乱转。",
    ],
    "break": [
        "靠边歇一下，回来会更清醒。",
        "喝口水，肩膀松一点，再继续上路。",
        "暂停不是掉队，是给续航充电。",
    ],
}


class CowCatAssistantApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1240x820")
        self.root.minsize(1120, 760)
        self.root.configure(bg="#fff3fa")

        self.hero_width = 408
        self.hero_height = 230
        self.hero_tick = 0
        self.hero_photo = None
        self.hero_after_id = None
        self.task_mousewheel_bound = False

        self.state = self.load_state()
        self.timer_running = False
        self.current_mode = "idle"
        self.task_vars: list[tk.BooleanVar] = []
        self.task_rows: list[tk.Frame] = []

        self.video_path = self.find_video_path()
        self.video_reader = None
        self.video_playing = False
        self.video_ready = False
        self.video_error_message = ""
        self.video_frame_index = 0
        self.video_frame_total = 0
        self.video_fps_ms = 42
        self.last_video_frame = None

        self.source_image = self.load_media_cover()
        self.palette = self.build_palette()
        self.root.configure(bg=self.palette["bg"])
        self.remaining_seconds = self.state["focus_minutes"] * 60

        self.configure_styles()
        self.build_ui()
        self.refresh_task_list()
        self.reset_timer(save_state=False)
        self.refresh_clock()
        self.refresh_status_line()
        self.render_current_hero_state(animated=False)

    def find_video_path(self) -> Path | None:
        preferred = sorted(
            path for path in BASE_DIR.glob("video.*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        )
        if preferred:
            return preferred[0]

        video_files = sorted(
            path for path in BASE_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        )
        return video_files[0] if video_files else None

    def log_runtime(self, message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")

    def build_placeholder_frame(self) -> Image.Image:
        frame = Image.new("RGB", (1280, 720), "#fff3fa")
        draw = ImageDraw.Draw(frame)
        rainbow_blocks = [
            ((50, 52, 320, 180), "#ff7eb6"),
            ((332, 52, 602, 180), "#ffb86b"),
            ((614, 52, 884, 180), "#fff07a"),
            ((896, 52, 1166, 180), "#7af7c4"),
            ((1178, 52, 1230, 180), "#7dd3ff"),
        ]
        for box, color in rainbow_blocks:
            draw.rounded_rectangle(box, radius=26, fill=color)
        draw.rounded_rectangle((36, 36, 1244, 684), radius=36, outline="#b469ff", width=5)
        draw.text((88, 248), "video source missing", fill="#31164f")
        draw.text((88, 294), "put video.mp4 in the project root", fill="#775c9f")
        return frame

    def load_media_cover(self) -> Image.Image:
        if self.video_path is not None:
            self.setup_video_reader()
            if self.video_reader is not None:
                try:
                    frame = self.video_reader.get_data(0)
                    image = Image.fromarray(frame).convert("RGB")
                    self.last_video_frame = image
                    self.video_ready = True
                    self.video_error_message = ""
                    return image
                except Exception as exc:
                    self.video_error_message = f"cover frame failed: {exc}"
                    self.log_runtime(self.video_error_message)
        self.video_ready = False
        placeholder = self.build_placeholder_frame()
        self.last_video_frame = placeholder
        return placeholder

    def setup_video_reader(self) -> None:
        if self.video_path is None or self.video_reader is not None:
            return
        try:
            video_source = str(self.video_path.resolve())
            self.video_reader = imageio.get_reader(video_source, format="ffmpeg")
            meta = self.video_reader.get_meta_data()
            fps = float(meta.get("fps") or 24.0)
            duration = float(meta.get("duration") or 0)
            self.video_fps_ms = max(24, int(1000 / fps))
            if duration > 0:
                self.video_frame_total = max(1, int(round(duration * fps)))
            self.video_ready = True
            self.video_error_message = ""
            self.log_runtime(f"video reader ready: {video_source}")
        except Exception as exc:
            self.video_reader = None
            self.video_ready = False
            self.video_error_message = f"reader init failed: {exc}"
            self.log_runtime(self.video_error_message)

    def load_state(self) -> dict:
        if not DATA_PATH.exists():
            return deepcopy(DEFAULT_STATE)
        try:
            data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            state = deepcopy(DEFAULT_STATE)
            state.update(data)
            if not isinstance(state.get("tasks"), list):
                state["tasks"] = deepcopy(DEFAULT_STATE["tasks"])
            if not isinstance(state.get("notes"), str):
                state["notes"] = DEFAULT_STATE["notes"]
            if not isinstance(state.get("focus_minutes"), int):
                state["focus_minutes"] = DEFAULT_STATE["focus_minutes"]
            return state
        except (json.JSONDecodeError, OSError):
            return deepcopy(DEFAULT_STATE)

    def save_state(self) -> None:
        if hasattr(self, "notes_text"):
            notes = self.notes_text.get("1.0", "end-1c").strip()
            self.state["notes"] = notes or DEFAULT_STATE["notes"]
        if hasattr(self, "minutes_var"):
            try:
                self.state["focus_minutes"] = max(5, min(90, int(self.minutes_var.get())))
            except ValueError:
                self.state["focus_minutes"] = DEFAULT_STATE["focus_minutes"]
        DATA_PATH.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_palette(self) -> dict:
        return {
            "bg": "#fff3fa",
            "panel": "#fffaff",
            "panel_alt": "#eef8ff",
            "panel_soft": "#fff0b8",
            "panel_deep": "#f6e9ff",
            "text": "#2f1848",
            "muted": "#7a5e9d",
            "accent": "#ff5fa2",
            "accent_soft": "#6ae7ff",
            "accent_dim": "#7c6cff",
            "accent_warm": "#ffad42",
            "accent_lime": "#d7f55f",
            "accent_green": "#4be29d",
            "accent_violet": "#bb65ff",
            "rose": "#ff78b2",
            "success": "#3dd298",
            "warning": "#ffb84d",
            "border": "#c881ff",
            "border_soft": "#ff9ad8",
            "task_card_a": "#fff7fd",
            "task_card_b": "#effbff",
            "task_done": "#f3efff",
            "task_canvas": "#fff8fe",
            "clock_bg": "#fff2be",
            "hero_bg": "#f5e8ff",
        }

    def configure_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Accent.TButton",
            background=self.palette["accent"],
            foreground=self.palette["text"],
            borderwidth=0,
            padding=(14, 8),
            focusthickness=0,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map("Accent.TButton", background=[("active", self.palette["accent_warm"])])

        style.configure(
            "Ghost.TButton",
            background=self.palette["panel_soft"],
            foreground=self.palette["text"],
            borderwidth=0,
            padding=(12, 8),
            focusthickness=0,
            font=("Microsoft YaHei UI", 9),
        )
        style.map("Ghost.TButton", background=[("active", self.palette["accent_lime"])])

        style.configure(
            "Route.Vertical.TScrollbar",
            background=self.palette["accent_violet"],
            troughcolor=self.palette["task_canvas"],
            bordercolor=self.palette["task_canvas"],
            arrowcolor=self.palette["text"],
            darkcolor=self.palette["accent_soft"],
            lightcolor=self.palette["accent"],
            relief="flat",
        )

        style.configure(
            "Drive.Horizontal.TProgressbar",
            troughcolor=self.palette["panel_alt"],
            background=self.palette["accent_violet"],
            bordercolor=self.palette["panel_alt"],
            lightcolor=self.palette["accent_soft"],
            darkcolor=self.palette["accent"],
            thickness=10,
        )

    def build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=self.palette["bg"])
        shell.pack(fill="both", expand=True, padx=20, pady=20)

        left = tk.Frame(shell, bg=self.palette["bg"], width=440)
        right = tk.Frame(shell, bg=self.palette["bg"])
        left.pack(side="left", fill="y", padx=(0, 16))
        left.pack_propagate(False)
        right.pack(side="left", fill="both", expand=True)

        self.build_left_column(left)
        self.build_right_column(right)

    def build_left_column(self, parent: tk.Frame) -> None:
        hero_card = self.make_card(parent, padding=16)
        hero_card.pack(fill="x")

        top_row = tk.Frame(hero_card, bg=self.palette["panel"])
        top_row.pack(fill="x")

        tk.Label(
            top_row,
            text="FOCUS VIDEO",
            font=("Segoe UI", 9, "bold"),
            fg=self.palette["accent_soft"],
            bg=self.palette["panel"],
        ).pack(side="left")

        self.mode_badge = tk.Label(
            top_row,
            text="IDLE",
            font=("Segoe UI", 8, "bold"),
            fg=self.palette["text"],
            bg=self.palette["accent_lime"],
            padx=10,
            pady=4,
        )
        self.mode_badge.pack(side="right")

        self.hero_canvas = tk.Canvas(
            hero_card,
            width=self.hero_width,
            height=self.hero_height,
            bg=self.palette["hero_bg"],
            highlightthickness=0,
            bd=0,
        )
        self.hero_canvas.pack(fill="x", pady=(12, 12))

        self.hero_image_item = self.hero_canvas.create_image(
            self.hero_width // 2,
            self.hero_height // 2,
            anchor="center",
        )
        self.hero_canvas.create_rectangle(
            1,
            1,
            self.hero_width - 1,
            self.hero_height - 1,
            outline=self.palette["border_soft"],
            width=1,
        )
        self.hero_canvas.create_text(
            16,
            18,
            text="cowcat // route mode",
            anchor="w",
            fill=self.palette["accent_soft"],
            font=("Consolas", 10, "bold"),
        )
        self.hero_canvas.create_text(
            16,
            self.hero_height - 18,
            text="driver view",
            anchor="w",
            fill=self.palette["muted"],
            font=("Consolas", 9),
        )
        self.hero_media_label = self.hero_canvas.create_text(
            self.hero_width - 16,
            self.hero_height - 18,
            text="",
            anchor="e",
            fill=self.palette["accent_soft"],
            font=("Consolas", 9, "bold"),
        )

        self.hero_lane_lines = []
        for _ in range(6):
            line = self.hero_canvas.create_line(0, 0, 0, 0, fill=self.palette["accent"], width=3, capstyle="round")
            self.hero_lane_lines.append(line)

        self.hero_ring = self.hero_canvas.create_oval(
            self.hero_width - 86,
            18,
            self.hero_width - 28,
            76,
            outline=self.palette["accent_dim"],
            width=2,
        )
        self.hero_orbit = self.hero_canvas.create_oval(0, 0, 0, 0, fill=self.palette["accent_soft"], outline="")

        self.status_message = tk.Label(
            hero_card,
            text="",
            justify="left",
            wraplength=380,
            font=("Microsoft YaHei UI", 13, "bold"),
            fg=self.palette["text"],
            bg=self.palette["panel"],
        )
        self.status_message.pack(anchor="w", pady=(2, 6))

        self.summary_label = tk.Label(
            hero_card,
            text="",
            justify="left",
            wraplength=390,
            font=("Microsoft YaHei UI", 9),
            fg=self.palette["muted"],
            bg=self.palette["panel"],
        )
        self.summary_label.pack(anchor="w")

        quick_row = tk.Frame(parent, bg=self.palette["bg"])
        quick_row.pack(fill="x", pady=(12, 0))
        quick_row.grid_columnconfigure((0, 1, 2), weight=1)

        ttk.Button(quick_row, text="项目目录", style="Ghost.TButton", command=self.open_project_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(quick_row, text="打开视频", style="Ghost.TButton", command=self.open_video_file).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(quick_row, text="换一句", style="Accent.TButton", command=self.shuffle_status).grid(row=0, column=2, sticky="ew", padx=(6, 0))

    def build_right_column(self, parent: tk.Frame) -> None:
        top_strip = self.make_card(parent, padding=18)
        top_strip.pack(fill="x", pady=(0, 14))

        left_block = tk.Frame(top_strip, bg=self.palette["panel"])
        left_block.pack(side="left", fill="x", expand=True)
        tk.Label(
            left_block,
            text="奶牛猫桌面助手",
            font=("Microsoft YaHei UI", 22, "bold"),
            fg=self.palette["text"],
            bg=self.palette["panel"],
        ).pack(anchor="w")
        tk.Label(
            left_block,
            text="更轻、更冷静，也更像在认真开车。",
            font=("Microsoft YaHei UI", 10),
            fg=self.palette["muted"],
            bg=self.palette["panel"],
        ).pack(anchor="w", pady=(4, 0))

        self.clock_label = tk.Label(
            top_strip,
            text="",
            font=("Consolas", 12, "bold"),
            fg=self.palette["text"],
            bg=self.palette["clock_bg"],
            padx=14,
            pady=10,
        )
        self.clock_label.pack(side="right")

        content = tk.Frame(parent, bg=self.palette["bg"])
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=3)
        content.grid_rowconfigure(1, weight=2)

        self.build_tasks_panel(content)
        self.build_timer_panel(content)
        self.build_notes_panel(content)

    def build_tasks_panel(self, parent: tk.Frame) -> None:
        panel = self.make_card(parent, padding=16)
        panel.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 14))

        header = tk.Frame(panel, bg=self.palette["panel"])
        header.pack(fill="x")

        tk.Label(
            header,
            text="今日路线",
            font=("Microsoft YaHei UI", 16, "bold"),
            fg=self.palette["text"],
            bg=self.palette["panel"],
        ).pack(side="left")

        self.task_stats = tk.Label(
            header,
            text="",
            font=("Microsoft YaHei UI", 9),
            fg=self.palette["muted"],
            bg=self.palette["panel"],
        )
        self.task_stats.pack(side="right")

        add_row = tk.Frame(panel, bg=self.palette["panel"])
        add_row.pack(fill="x", pady=(12, 12))

        self.task_entry = tk.Entry(
            add_row,
            relief="flat",
            bg=self.palette["panel_alt"],
            fg=self.palette["text"],
            insertbackground=self.palette["text"],
            font=("Microsoft YaHei UI", 10),
            highlightthickness=1,
            highlightbackground=self.palette["border_soft"],
            highlightcolor=self.palette["accent"],
        )
        self.task_entry.pack(side="left", fill="x", expand=True, ipady=11)
        self.task_entry.bind("<Return>", lambda _event: self.add_task())

        ttk.Button(add_row, text="新增路线", style="Accent.TButton", command=self.add_task).pack(side="left", padx=(10, 0))

        route_frame = tk.Frame(panel, bg=self.palette["task_canvas"], highlightthickness=1, highlightbackground=self.palette["border_soft"])
        route_frame.pack(fill="both", expand=True)

        self.task_canvas = tk.Canvas(
            route_frame,
            bg=self.palette["task_canvas"],
            highlightthickness=0,
            bd=0,
            yscrollincrement=24,
        )
        self.task_canvas.pack(side="left", fill="both", expand=True)

        task_scrollbar = ttk.Scrollbar(route_frame, orient="vertical", command=self.task_canvas.yview, style="Route.Vertical.TScrollbar")
        task_scrollbar.pack(side="right", fill="y")
        self.task_canvas.configure(yscrollcommand=task_scrollbar.set)

        self.task_list_frame = tk.Frame(self.task_canvas, bg=self.palette["task_canvas"])
        self.task_window_id = self.task_canvas.create_window((0, 0), window=self.task_list_frame, anchor="nw")
        self.task_list_frame.bind("<Configure>", self.on_task_frame_configure)
        self.task_canvas.bind("<Configure>", self.on_task_canvas_configure)
        self.task_canvas.bind("<Enter>", self.bind_task_mousewheel)
        self.task_canvas.bind("<Leave>", self.unbind_task_mousewheel)
        self.task_list_frame.bind("<Enter>", self.bind_task_mousewheel)
        self.task_list_frame.bind("<Leave>", self.unbind_task_mousewheel)

        footer = tk.Frame(panel, bg=self.palette["panel"])
        footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="删除已完成", style="Ghost.TButton", command=self.clear_completed_tasks).pack(side="left")
        ttk.Button(footer, text="立即保存", style="Ghost.TButton", command=self.manual_save).pack(side="left", padx=8)

    def build_timer_panel(self, parent: tk.Frame) -> None:
        panel = self.make_card(parent, padding=16)
        panel.grid(row=1, column=0, sticky="nsew", padx=(0, 14))

        tk.Label(
            panel,
            text="专注巡航",
            font=("Microsoft YaHei UI", 16, "bold"),
            fg=self.palette["text"],
            bg=self.palette["panel"],
        ).pack(anchor="w")

        self.timer_label = tk.Label(
            panel,
            text="25:00",
            font=("Consolas", 34, "bold"),
            fg=self.palette["text"],
            bg=self.palette["panel"],
        )
        self.timer_label.pack(anchor="w", pady=(8, 2))

        self.timer_hint = tk.Label(
            panel,
            text="准备出发。",
            font=("Microsoft YaHei UI", 10),
            fg=self.palette["accent_soft"],
            bg=self.palette["panel"],
        )
        self.timer_hint.pack(anchor="w", pady=(0, 12))

        self.timer_progress = ttk.Progressbar(panel, style="Drive.Horizontal.TProgressbar", maximum=100, value=100)
        self.timer_progress.pack(fill="x", pady=(0, 14))

        controls = tk.Frame(panel, bg=self.palette["panel"])
        controls.pack(fill="x")
        tk.Label(
            controls,
            text="分钟",
            font=("Microsoft YaHei UI", 10),
            fg=self.palette["muted"],
            bg=self.palette["panel"],
        ).pack(side="left")

        self.minutes_var = tk.StringVar(value=str(self.state["focus_minutes"]))
        self.minutes_spin = tk.Spinbox(
            controls,
            from_=5,
            to=90,
            increment=5,
            width=6,
            textvariable=self.minutes_var,
            relief="flat",
            justify="center",
            bg=self.palette["panel_alt"],
            fg=self.palette["text"],
            insertbackground=self.palette["text"],
            highlightthickness=1,
            highlightbackground=self.palette["border_soft"],
            highlightcolor=self.palette["accent"],
            font=("Consolas", 13, "bold"),
            command=self.reset_timer,
        )
        self.minutes_spin.pack(side="left", padx=(10, 0), ipady=4)

        buttons = tk.Frame(panel, bg=self.palette["panel"])
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="开始", style="Accent.TButton", command=self.start_timer).pack(side="left")
        ttk.Button(buttons, text="暂停", style="Ghost.TButton", command=self.pause_timer).pack(side="left", padx=8)
        ttk.Button(buttons, text="重置", style="Ghost.TButton", command=self.reset_timer).pack(side="left")

    def build_notes_panel(self, parent: tk.Frame) -> None:
        panel = self.make_card(parent, padding=16)
        panel.grid(row=1, column=1, sticky="nsew")

        head = tk.Frame(panel, bg=self.palette["panel"])
        head.pack(fill="x")
        tk.Label(
            head,
            text="驾驶舱便签",
            font=("Microsoft YaHei UI", 16, "bold"),
            fg=self.palette["text"],
            bg=self.palette["panel"],
        ).pack(side="left")
        tk.Label(
            head,
            text="自动保存",
            font=("Segoe UI", 9, "bold"),
            fg=self.palette["rose"],
            bg=self.palette["panel"],
        ).pack(side="right")

        self.notes_text = tk.Text(
            panel,
            height=12,
            relief="flat",
            wrap="word",
            bg=self.palette["panel_alt"],
            fg=self.palette["text"],
            insertbackground=self.palette["text"],
            selectbackground=self.palette["accent_dim"],
            highlightthickness=1,
            highlightbackground=self.palette["border_soft"],
            highlightcolor=self.palette["accent"],
            font=("Microsoft YaHei UI", 10),
            padx=14,
            pady=14,
        )
        self.notes_text.pack(fill="both", expand=True, pady=(12, 12))
        self.notes_text.insert("1.0", self.state["notes"])
        self.notes_text.bind("<KeyRelease>", self.debounced_save)

        ttk.Button(panel, text="保存当前状态", style="Ghost.TButton", command=self.manual_save).pack(anchor="w")

    def make_card(self, parent: tk.Widget, padding: int = 14) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=self.palette["panel"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette["border"],
            padx=padding,
            pady=padding,
        )

    def render_hero_frame(self, source_frame: Image.Image | None = None, animated: bool = False) -> Image.Image:
        frame = source_frame or self.last_video_frame or self.source_image
        frame = ImageOps.fit(frame, (self.hero_width, self.hero_height), centering=(0.5, 0.5))
        frame = ImageEnhance.Contrast(frame).enhance(1.05)
        overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        rainbow_overlay = [
            ((255, 95, 162, 48), (0, 0, self.hero_width * 0.34, self.hero_height)),
            ((255, 173, 66, 42), (self.hero_width * 0.2, 0, self.hero_width * 0.56, self.hero_height)),
            ((215, 245, 95, 38), (self.hero_width * 0.42, 0, self.hero_width * 0.74, self.hero_height)),
            ((106, 231, 255, 36), (self.hero_width * 0.62, 0, self.hero_width, self.hero_height)),
        ]
        for color, box in rainbow_overlay:
            draw.rectangle(tuple(int(v) for v in box), fill=color)
        draw.rectangle((0, self.hero_height - 64, self.hero_width, self.hero_height), fill=(255, 250, 255, 120))
        draw.line((18, 44, self.hero_width - 28, 22), fill=(255, 95, 162, 88), width=3)
        draw.line((self.hero_width - 120, 0, self.hero_width, 78), fill=(106, 231, 255, 54), width=8)
        draw.rounded_rectangle(
            (10, 10, self.hero_width - 10, self.hero_height - 10),
            radius=18,
            outline=(187, 101, 255, 120),
            width=2,
        )

        if animated:
            trail_colors = [
                (255, 95, 162, 190),
                (255, 173, 66, 176),
                (215, 245, 95, 162),
                (106, 231, 255, 148),
            ]
            for idx in range(4):
                offset = (self.hero_tick * 12 + idx * 76) % (self.hero_height + 100) - 50
                y = int(self.hero_height * 0.62 + offset)
                color = trail_colors[idx % len(trail_colors)]
                draw.line(
                    (int(self.hero_width * 0.68), y, self.hero_width - 16, y + 18),
                    fill=color,
                    width=max(2, 6 - idx),
                )

        frame = Image.alpha_composite(frame.convert("RGBA"), overlay)
        return frame.filter(ImageFilter.GaussianBlur(radius=0.15)).convert("RGB")

    def render_current_hero_state(self, animated: bool) -> None:
        frame = self.render_hero_frame(animated=animated)
        self.hero_photo = ImageTk.PhotoImage(frame)
        self.hero_canvas.itemconfigure(self.hero_image_item, image=self.hero_photo)
        self.update_hero_overlay(animated)
        if self.video_ready:
            self.hero_canvas.itemconfigure(self.hero_media_label, text="video ready")
        elif self.video_path is not None:
            self.hero_canvas.itemconfigure(self.hero_media_label, text="video error")
        else:
            self.hero_canvas.itemconfigure(self.hero_media_label, text="video missing")

    def update_hero_overlay(self, animated: bool) -> None:
        if not animated:
            for line in self.hero_lane_lines:
                self.hero_canvas.itemconfigure(line, state="hidden")
            self.hero_canvas.itemconfigure(self.hero_orbit, state="hidden")
            return

        orbit_angle = (self.hero_tick * 9) % 360
        radians = math.radians(orbit_angle)
        cx = self.hero_width - 57
        cy = 47
        radius = 21
        dot_x = cx + math.cos(radians) * radius
        dot_y = cy + math.sin(radians) * radius
        self.hero_canvas.itemconfigure(self.hero_orbit, state="normal")
        orbit_colors = [self.palette["accent"], self.palette["accent_warm"], self.palette["accent_green"], self.palette["accent_soft"], self.palette["accent_violet"]]
        self.hero_canvas.itemconfigure(self.hero_orbit, fill=orbit_colors[(self.hero_tick // 2) % len(orbit_colors)])
        self.hero_canvas.coords(self.hero_orbit, dot_x - 4, dot_y - 4, dot_x + 4, dot_y + 4)

        line_colors = [
            self.palette["accent"],
            self.palette["accent_warm"],
            self.palette["accent_lime"],
            self.palette["accent_green"],
            self.palette["accent_soft"],
            self.palette["accent_violet"],
        ]
        for idx, line in enumerate(self.hero_lane_lines):
            offset = (self.hero_tick * 14 + idx * 54) % (self.hero_height + 140) - 80
            y = self.hero_height * 0.62 + offset
            start_x = self.hero_width * 0.67 + math.sin((self.hero_tick / 6) + idx) * 10
            end_x = self.hero_width - 24
            self.hero_canvas.itemconfigure(line, state="normal")
            self.hero_canvas.coords(line, start_x, y, end_x, y + 16)
            self.hero_canvas.itemconfigure(line, fill=line_colors[idx % len(line_colors)])

    def schedule_next_hero_frame(self) -> None:
        if self.hero_after_id is not None:
            self.root.after_cancel(self.hero_after_id)
        if self.video_playing:
            self.hero_after_id = self.root.after(self.video_fps_ms, self.animate_hero)
        else:
            self.hero_after_id = None

    def get_next_video_frame(self) -> Image.Image | None:
        if self.video_reader is None:
            return None
        try:
            frame = self.video_reader.get_data(self.video_frame_index)
        except Exception as exc:
            self.log_runtime(f"frame read failed at {self.video_frame_index}: {exc}")
            self.video_frame_index = 0
            try:
                frame = self.video_reader.get_data(self.video_frame_index)
            except Exception as retry_exc:
                self.video_error_message = f"frame retry failed: {retry_exc}"
                self.log_runtime(self.video_error_message)
                self.video_ready = False
                return None

        self.video_frame_index += 1
        if self.video_frame_total and self.video_frame_index >= self.video_frame_total:
            self.video_frame_index = 0

        image = Image.fromarray(frame).convert("RGB")
        self.last_video_frame = image
        return image

    def animate_hero(self) -> None:
        if not self.video_playing:
            self.render_current_hero_state(animated=False)
            return

        source_frame = self.get_next_video_frame()
        frame = self.render_hero_frame(source_frame=source_frame, animated=True)
        self.hero_photo = ImageTk.PhotoImage(frame)
        self.hero_canvas.itemconfigure(self.hero_image_item, image=self.hero_photo)
        self.update_hero_overlay(animated=True)
        self.hero_tick += 1
        self.schedule_next_hero_frame()

    def start_video_playback(self) -> None:
        if self.video_path is None:
            return
        if self.video_reader is None:
            self.setup_video_reader()
        if self.video_reader is None and self.video_path is not None:
            self.log_runtime("retrying video reader init before playback")
        self.setup_video_reader()
        if self.video_reader is None:
            return
        self.video_ready = True
        self.video_playing = True
        self.animate_hero()

    def pause_video_playback(self) -> None:
        self.video_playing = False
        if self.hero_after_id is not None:
            self.root.after_cancel(self.hero_after_id)
            self.hero_after_id = None
        self.render_current_hero_state(animated=False)

    def refresh_clock(self) -> None:
        self.clock_label.configure(text=time.strftime("%Y-%m-%d  %H:%M:%S"))
        self.root.after(1000, self.refresh_clock)

    def refresh_task_list(self) -> None:
        for widget in self.task_list_frame.winfo_children():
            widget.destroy()
        self.task_vars.clear()
        self.task_rows.clear()

        tasks = self.state["tasks"]
        if not tasks:
            empty = tk.Label(
                self.task_list_frame,
                text="还没有路线点。先加一条今天最重要的事。",
                justify="left",
                wraplength=620,
                font=("Microsoft YaHei UI", 10),
                fg=self.palette["muted"],
                bg=self.palette["task_canvas"],
                padx=14,
                pady=18,
            )
            empty.pack(fill="x")
        else:
            for index, task in enumerate(tasks):
                row_bg = self.palette["task_done"] if task.get("done") else (
                    self.palette["task_card_a"] if index % 2 == 0 else self.palette["task_card_b"]
                )
                row = tk.Frame(
                    self.task_list_frame,
                    bg=row_bg,
                    highlightthickness=1,
                    highlightbackground=self.palette["border"],
                    padx=10,
                    pady=8,
                )
                row.pack(fill="x", pady=(0, 8))
                self.task_rows.append(row)

                bullet = tk.Canvas(row, width=14, height=14, bg=row_bg, highlightthickness=0, bd=0)
                bullet.pack(side="left", padx=(2, 10))
                bullet.create_oval(
                    2,
                    2,
                    12,
                    12,
                    outline=self.palette["accent_violet"],
                    fill=self.palette["accent"] if task.get("done") else row_bg,
                    width=2,
                )

                var = tk.BooleanVar(value=task.get("done", False))
                self.task_vars.append(var)
                check = tk.Checkbutton(
                    row,
                    text=task.get("text", ""),
                    variable=var,
                    onvalue=True,
                    offvalue=False,
                    command=lambda idx=index, value=var: self.toggle_task(idx, value.get()),
                    wraplength=600,
                    justify="left",
                    anchor="w",
                    relief="flat",
                    bd=0,
                    bg=row_bg,
                    activebackground=row_bg,
                    fg=self.palette["muted"] if task.get("done") else self.palette["text"],
                    activeforeground=self.palette["text"],
                    selectcolor=row_bg,
                    font=("Microsoft YaHei UI", 10),
                    padx=0,
                    pady=4,
                )
                check.pack(side="left", fill="x", expand=True)

        done_count = sum(1 for item in tasks if item.get("done"))
        self.task_stats.configure(text=f"{done_count}/{len(tasks)} 已完成")
        self.on_task_frame_configure()
        self.refresh_status_line()

    def refresh_status_line(self) -> None:
        done_count = sum(1 for item in self.state["tasks"] if item.get("done"))
        total = len(self.state["tasks"])

        if self.current_mode == "focus":
            mode_line = random.choice(CAT_LINES["focus"])
            badge = "FOCUS"
            badge_color = self.palette["accent"]
        elif self.current_mode == "break":
            mode_line = random.choice(CAT_LINES["break"])
            badge = "BREAK"
            badge_color = self.palette["accent_soft"]
        else:
            mode_line = random.choice(CAT_LINES["idle"])
            badge = "IDLE"
            badge_color = self.palette["accent_lime"]

        self.status_message.configure(text=mode_line)
        self.summary_label.configure(text=f"任务进度 {done_count}/{total}   |   专注时长 {self.minutes_var.get()} 分钟")
        self.mode_badge.configure(text=badge, bg=badge_color)

    def shuffle_status(self) -> None:
        self.refresh_status_line()

    def add_task(self) -> None:
        text = self.task_entry.get().strip()
        if not text:
            return
        self.state["tasks"].append({"text": text, "done": False})
        self.task_entry.delete(0, "end")
        self.refresh_task_list()
        self.save_state()

    def toggle_task(self, index: int, done: bool) -> None:
        self.state["tasks"][index]["done"] = done
        self.refresh_task_list()
        self.save_state()

    def clear_completed_tasks(self) -> None:
        self.state["tasks"] = [task for task in self.state["tasks"] if not task.get("done")]
        self.refresh_task_list()
        self.save_state()

    def start_timer(self) -> None:
        if self.timer_running:
            return
        self.current_mode = "focus"
        self.timer_running = True
        self.timer_hint.configure(text="专注巡航中。先把这一段安稳跑完。")
        self.refresh_status_line()
        self.start_video_playback()
        self.run_timer()

    def pause_timer(self) -> None:
        self.timer_running = False
        self.current_mode = "break"
        self.timer_hint.configure(text="已经暂停。歇一下，再继续。")
        self.refresh_status_line()
        self.pause_video_playback()

    def reset_timer(self, save_state: bool = True) -> None:
        self.timer_running = False
        self.current_mode = "idle"
        try:
            minutes = max(5, min(90, int(self.minutes_var.get())))
        except ValueError:
            minutes = 25
            self.minutes_var.set("25")
        self.remaining_seconds = minutes * 60
        self.update_timer_label()
        self.timer_hint.configure(text="准备出发。")
        self.refresh_status_line()
        self.pause_video_playback()
        if save_state:
            self.save_state()

    def run_timer(self) -> None:
        if not self.timer_running:
            return
        if self.remaining_seconds <= 0:
            self.timer_running = False
            self.current_mode = "break"
            self.timer_hint.configure(text="这段路跑完了，休息一下。")
            self.refresh_status_line()
            self.pause_video_playback()
            messagebox.showinfo(APP_TITLE, "专注时间结束，奶牛猫提醒你可以休息一下。")
            return

        self.remaining_seconds -= 1
        self.update_timer_label()
        self.root.after(1000, self.run_timer)

    def update_timer_label(self) -> None:
        minutes, seconds = divmod(max(self.remaining_seconds, 0), 60)
        try:
            total_minutes = int(self.minutes_var.get() or 25)
        except ValueError:
            total_minutes = 25
        total = max(1, total_minutes * 60)
        progress = max(0, min(100, self.remaining_seconds / total * 100))
        self.timer_label.configure(text=f"{minutes:02d}:{seconds:02d}")
        self.timer_progress.configure(value=progress)

    def manual_save(self) -> None:
        self.save_state()
        self.timer_hint.configure(text="已保存当前状态。")

    def debounced_save(self, _event=None) -> None:
        if hasattr(self, "_save_after_id"):
            self.root.after_cancel(self._save_after_id)
        self._save_after_id = self.root.after(420, self.save_state)

    def on_task_frame_configure(self, _event=None) -> None:
        self.task_canvas.configure(scrollregion=self.task_canvas.bbox("all"))

    def on_task_canvas_configure(self, event=None) -> None:
        width = event.width if event else self.task_canvas.winfo_width()
        self.task_canvas.itemconfigure(self.task_window_id, width=width)

    def bind_task_mousewheel(self, _event=None) -> None:
        if not self.task_mousewheel_bound:
            self.root.bind_all("<MouseWheel>", self.on_task_mousewheel)
            self.task_mousewheel_bound = True

    def unbind_task_mousewheel(self, _event=None) -> None:
        if self.task_mousewheel_bound:
            self.root.unbind_all("<MouseWheel>")
            self.task_mousewheel_bound = False

    def on_task_mousewheel(self, event) -> None:
        if not self.task_canvas.winfo_exists():
            return
        self.task_canvas.yview_scroll(int(-event.delta / 120), "units")

    def open_project_dir(self) -> None:
        os.startfile(BASE_DIR)

    def open_video_file(self) -> None:
        if self.video_path is not None:
            os.startfile(self.video_path)

    def on_close(self) -> None:
        self.pause_video_playback()
        if self.video_reader is not None:
            self.video_reader.close()
        self.save_state()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = CowCatAssistantApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
