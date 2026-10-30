# -*- coding: utf-8 -*-
"""DiskProbe 主界面 —— 按《星团扫描 交互设计 V2.0》实现。

和 prototype.py 的区别：这个是能用的程序，不是动效演示。

    真实数据      点「扫描目录」→ 真的扫盘 → 星团真的长出来
    三个区域      顶部状态区 / 中央星团区 / 右侧详情区
    默认倾角      12°（prototype 是 63°，扇区被压得看不清）
    悬浮          浮起 10px、其他下沉 4px、过渡 200ms
    旋转          不做（V2.0 §5.3：第一版默认角度清晰稳定）
    扫描线程      独立线程，动画与扫描解耦；失焦停动画，扫描继续
    口径          扇区按 EXE 文件数量，界面上写清楚

跑法：py -3 ui.py
"""

import math
import os
import random
import sys
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QConicalGradient,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

import classify
import scanner

# ---------------------------------------------------------------- 规范参数
# 数值全部来自 V2.0。改这里就等于改规范。

TILT_DEG = 38.0                 # V2.0 §2.2 写的是 8–15°，但老大要"立体"，改成 38°
DEPTH = 20                      # 盘的厚度（像素），立体感靠它
FLAT = math.cos(math.radians(TILT_DEG))
RING_RATIO = (1.00, 1.22, 1.46)
DIAMETER_RATIO = 0.66           # §2.2 星团直径 = 短边 55%–70%

LIFT_HOVER = 10.0               # §5.1 浮起 6–12px
SINK_OTHER = 4.0                # §5.1 其他下沉 3–6px
DIM_ALPHA = 0.55                # §5.1 其他降到 45%–65%
T_HOVER = 0.20                  # §7 160–260ms
T_SETTLE = 0.45                 # §7 扇区重排 250–450ms
BATCH_MS = 150                  # §8.2 每 100–200ms 合批

STAR_R = 2.0
FLY_SECS = 0.62                 # 一颗星从外面飞进星云用的时间
SPIN_SPEED = 0.85               # 扫描时星云的旋转角速度（弧度/秒）
IDLE_FLOW = 0.045               # 完成后极慢的整体流动（弧度/秒，约 2.6°/s）
BREATH = 0.014                  # 呼吸：星点半径起伏幅度
RELEASE_PER_FRAME = 3           # 每帧最多放几颗星出来（视觉节奏，数据不受影响）
TWINKLE = 90                    # 会闪的背景星数量
STARFIELD = 900                 # 背景星点数量
WEDGE_GAP = 0.014               # 扇区之间的缝，边界不要贴死
GROUP_CAP = 9                  # §4.3 主星团只展示主要分组，其余归「其他」

BG_TOP = QColor("#070b14")
BG_BOTTOM = QColor("#0a0e1a")
INK = QColor("#e8ecf4")
INK_DIM = QColor("#9fb0c8")
INK_FAINT = QColor("#4d5c72")
ACCENT = QColor("#5b9cf6")

PALETTE = ["#5b9cf6", "#d97757", "#f2c14e", "#57b894", "#9b7ede",
           "#4fb0c6", "#e0709a", "#8a8f9c"]

NEBULA_ALPHA = 46               # 每组背后那团星云的中心亮度
STARFIELD = 420                 # 背景星点数量

TEXT = {
    "S0_title": "你的软件星团还未被探索",
    "S0_btn": "扫描目录",
    "scanning": "正在探索：%s",
    "found": "已发现 %d 个 EXE",
    "done": "扫描完成 · 发现 %d 个 EXE · %d 个分组",
    "empty": "扫描完成，没有发现 EXE 文件。",
    "partial": "扫描未完全完成。当前星团仅展示成功读取的结果。",
    "failed": "扫描未能完成",
    "cancelled": "扫描已取消 · 当前结果为部分结果",
    "scale_note": "扇区按 EXE 文件数量分配 · 分组依据是文件所在目录（不是推断的软件类别）",
}


def hash01(s, salt=0):
    """字符串 -> 0..1 的稳定小数。同一路径每次算出来都一样，
    所以重扫不会让星星重新乱排（V2.0 §4.4）。"""
    h = 2166136261 ^ ((salt * 2654435761) & 0xFFFFFFFF)
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h / 4294967295.0


class ScanCancelled(Exception):
    pass


# ---------------------------------------------------------------- 扫描线程

class ScanWorker(QThread):
    """扫描在后台跑，用信号把结果交回界面（V2.0 §8.1）。界面绝不自己遍历磁盘。"""

    found = Signal(list)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, root):
        super().__init__()
        self.root = root
        self._cancel = False
        self._buf = []
        self._last = time.perf_counter()

    def cancel(self):
        self._cancel = True

    def _on_file(self, record):
        if self._cancel:
            raise ScanCancelled()
        self._buf.append(record)
        now = time.perf_counter()
        if (now - self._last) * 1000 >= BATCH_MS:
            self._flush()
            self._last = now

    def _flush(self):
        if self._buf:
            batch, self._buf = self._buf, []
            self.found.emit(batch)

    def run(self):
        try:
            result = scanner.scan(self.root, on_file=self._on_file)
        except ScanCancelled:
            self._flush()
            self.done.emit({"cancelled": True, "files": [], "skipped": [],
                            "complete": False, "error": None, "root": self.root})
            return
        except Exception as exc:            # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self._flush()
        self.done.emit(result)


# ---------------------------------------------------------------- 星团画布

class StarCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 360)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        self.state = "S0"           # S0 / scanning / done / partial / cancelled / empty / failed
        self.files = []
        self._pending = []
        self.groups = []
        self.wedges = []
        self.stars = []
        self.error_text = ""

        self.hover = -1
        self.sel = -1
        self.hi = []
        self.settle = 1.0
        self.newest = 0.0
        self.spin = 0.0
        self.t_anim = 0.0            # 呼吸用的连续时间
        self.yaw = 0.0               # 视角的水平旋转（拖动改它）
        self.flat = FLAT             # 视角的倾斜（上下拖动改它）
        self.vel_yaw = 0.0
        self.vel_flat = 0.0
        self.dragging = False
        self.drag_prev = (0.0, 0.0)
        self._pending = []           # 扫描到但还没轮到出场的星
        self.moved = 0.0

        self.reduce_motion = False

        self._space = None
        self._space_size = None
        self._last_frame = time.perf_counter()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ---------------------------------------------------------- 数据接口

    def reset(self):
        self.state = "S0"
        self.files = []
        self.groups = []
        self.wedges = []
        self.stars = []
        self.hi = []
        self.hover = -1
        self.sel = -1
        self.settle = 1.0
        self.spin = 0.0
        self.update()

    def start_scan(self):
        self.reset()
        self.state = "scanning"
        self.newest = time.perf_counter()
        self.update()

    def add_batch(self, batch):
        """扫描到的文件先进队列，由 _tick 按节奏一颗颗放出来。

        为什么：真扫 1010 个只要 3 秒，全塞进画面就是一片糊。
        数据一条不少（状态栏的计数是真的），只是"出场"慢下来。
        """
        for rec in batch:
            self.files.append(rec)
            self._pending.append(rec)
        self.newest = time.perf_counter()
        self.update()

    def set_result(self, result):
        cancelled = result.get("cancelled")
        err = result.get("error")
        files = result.get("files") or []
        if files:
            self.files = files

        if err:
            self.state = "failed"
            self.error_text = err
            self.update()
            return
        if not self.files:
            self.state = "cancelled" if cancelled else "empty"
            self.update()
            return

        all_groups = classify.build_groups(self.files)
        # §4.3：扇区太多时主星团只显示主要分组，其余合并成「其他」。
        # 合并是视觉聚合，不是篡改数据——真实分组数另存一份用来显示。
        self.total_groups = len(all_groups)
        if len(all_groups) > GROUP_CAP:
            keep = all_groups[:GROUP_CAP - 1]
            rest = all_groups[GROUP_CAP - 1:]
            merged = {
                "key": "其他 %d 个目录" % len(rest),
                "count": sum(x["count"] for x in rest),
                "size": sum(x["size"] for x in rest),
                "files": [f for x in rest for f in x["files"]],
                "is_other": True,
            }
            self.groups = keep + [merged]
        else:
            self.groups = all_groups
        for i, g in enumerate(self.groups):
            g["color"] = QColor(PALETTE[i % len(PALETTE)])
        self._assign_targets()
        self.hi = [0.0] * len(self.groups)
        self.settle = 0.0
        if cancelled:
            self.state = "cancelled"
        elif not result.get("complete"):
            self.state = "partial"
        else:
            self.state = "done"
        self.update()

    def _assign_targets(self):
        """每组一个扇区，角度按该组 EXE 数量占总数的比例。
        星点位置由路径哈希决定，稳定不跳（V2.0 §4.4）。

        重点：把每颗星**当前在屏幕上哪儿**记进 f_ang/f_rad，
        聚合动画就从那里开始走 —— 否则星星会"啪"一下跳到新位置。
        """
        old = {}
        for st in self.stars:
            old[st.get("path", "")] = (st["ang"] + self.spin, st["rad"])

        total = max(1, len(self.files))
        acc = -math.pi / 2
        self.wedges = []
        for g in self.groups:
            span = math.tau * (g["count"] / total)
            self.wedges.append((acc + 0.006, acc + span - 0.006))
            acc += span

        new_stars = []
        for gi, g in enumerate(self.groups):
            a0, a1 = self.wedges[gi]
            for rec in g["files"]:
                u = hash01(rec["path"], 11)
                v = hash01(rec["path"], 23)
                ang = a0 + (a1 - a0) * u
                rad = 0.14 + 0.80 * math.sqrt(v)
                if rec["path"] in old:
                    f_ang, f_rad = old[rec["path"]]
                else:
                    # 扫完了还没轮到出场 —— 让它在聚合阶段从盘外飞进来
                    f_ang = math.tau * hash01(rec["path"], 31) + self.spin
                    f_rad = 1.30 + 0.55 * hash01(rec["path"], 41)
                new_stars.append({
                    "path": rec["path"],
                    "ang": ang, "rad": rad,
                    "f_ang": f_ang, "f_rad": f_rad,
                    "ph": hash01(rec["path"], 5) * 6.283,   # 呼吸相位只算一次
                    "group": gi, "color": g["color"],
                })
        self.stars = new_stars
        self.spin = 0.0

    def _center(self):
        return QPointF(self.width() * 0.5, self.height() * 0.52)

    def _radius(self):
        return min(self.width(), self.height()) * DIAMETER_RATIO * 0.5

    def _proj(self, c, r, a):
        a += self.yaw
        return (c.x() + r * math.cos(a), c.y() + r * math.sin(a) * self.flat)

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last_frame)
        self._last_frame = now
        self.t_anim += dt

        busy = False
        if self.state == "scanning" and not self.reduce_motion:
            self.spin += dt * SPIN_SPEED
            busy = True
        elif self.groups and not self.reduce_motion:
            # 完成后极慢地流动，让画面"活着"但不至于分心
            self.spin += dt * IDLE_FLOW
            busy = True

        # 队列里的星按节奏出场：一帧最多放几颗，这样画面是"长出来"的
        if self._pending and self.state == "scanning":
            now2 = time.perf_counter()
            n = len(self._pending)
            take = min(RELEASE_PER_FRAME, n)
            batch, self._pending = self._pending[:take], self._pending[take:]
            base = len(self.stars)
            for j, rec in enumerate(batch):
                idx = base + j
                self.stars.append({
                    "path": rec["path"],
                    "ang": (idx * 2.399963) % math.tau,
                    "rad": 0.26 + 0.66 * hash01(rec["path"], 7),
                    "sang": math.tau * hash01(rec["path"], 31),
                    "srad": 1.30 + 0.55 * hash01(rec["path"], 41),
                    "t0": now2 + j * 0.012,
                    "ph": hash01(rec["path"], 5) * 6.283,
                    "group": 0,
                    "color": QColor("#9fb4d4"),
                })
            busy = True

        # 拖动松手后的惯性
        if not self.dragging and (abs(self.vel_yaw) > 1e-4 or abs(self.vel_flat) > 1e-4):
            self.yaw += self.vel_yaw
            self.flat = min(1.0, max(0.18, self.flat + self.vel_flat))
            self.vel_yaw *= 0.90
            self.vel_flat *= 0.90
            busy = True

        if self.settle < 1.0:
            self.settle = min(1.0, self.settle + dt / T_SETTLE)
            busy = True

        if not self.reduce_motion and self.groups:
            for i, target in enumerate(self._targets()):
                cur = self.hi[i]
                step = dt / T_HOVER
                if cur < target:
                    self.hi[i] = min(target, cur + step)
                    busy = True
                elif cur > target:
                    self.hi[i] = max(target, cur - step)
                    busy = True

        if busy:
            self.update()

    def _targets(self):
        out = []
        for i in range(len(self.groups)):
            if self.sel >= 0:
                out.append(1.0 if i == self.sel else -1.0)
            else:
                out.append(1.0 if i == self.hover else 0.0)
        return out

    def event(self, ev):
        """失焦停动画（V2.0 §6）。扫描线程自己跑完，不受影响。"""
        if ev.type() == QEvent.WindowDeactivate:
            self.timer.stop()
        elif ev.type() == QEvent.WindowActivate:
            if not self.timer.isActive():
                self._last_frame = time.perf_counter()
                self.timer.start(16)
            self.update()
        return super().event(ev)

    # ---------------------------------------------------------- 背景（缓存）

    def _build_space(self):
        w, h = self.width(), self.height()
        pix = QPixmap(w, h)
        pix.fill(BG_TOP)
        pp = QPainter(pix)
        pp.setRenderHint(QPainter.Antialiasing, True)

        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, BG_TOP)
        g.setColorAt(1.0, BG_BOTTOM)
        pp.setPen(Qt.NoPen)
        pp.setBrush(g)
        pp.drawRect(0, 0, w, h)

        # 一条斜着淡出的银河带，让黑背景有方向感
        band = QLinearGradient(0, 0, w, h)
        band.setColorAt(0.00, QColor(90, 120, 200, 0))
        band.setColorAt(0.45, QColor(120, 150, 230, 22))
        band.setColorAt(0.55, QColor(150, 170, 240, 26))
        band.setColorAt(1.00, QColor(90, 120, 200, 0))
        pp.setBrush(band)
        pp.drawRect(0, 0, w, h)

        for cx, cy, rad, col, a_in in (
            (w * 0.26, h * 0.22, w * 0.48, QColor(80, 120, 210), 24),
            (w * 0.78, h * 0.82, w * 0.44, QColor(190, 110, 80), 16),
            (w * 0.62, h * 0.18, w * 0.30, QColor(120, 90, 210), 14),
        ):
            ng = QRadialGradient(cx, cy, rad)
            c1 = QColor(col)
            c1.setAlpha(a_in)
            c2 = QColor(col)
            c2.setAlpha(0)
            ng.setColorAt(0.0, c1)
            ng.setColorAt(1.0, c2)
            pp.setBrush(ng)
            pp.drawEllipse(QRectF(cx - rad, cy - rad, rad * 2, rad * 2))

        # 三层星：远（小暗）、中、近（大亮）
        rnd = random.Random(20261030)
        layers = ((0.55, 1.0, [16, 22, 28]), (0.30, 1.6, [36, 48, 60]),
                  (0.15, 2.3, [70, 96, 128]))
        for share, wd, alphas in layers:
            dot = {}
            for _ in range(int(STARFIELD * share)):
                x, y = rnd.uniform(0, w), rnd.uniform(0, h)
                a = rnd.choice(alphas)
                dot.setdefault(a, []).append(QPointF(x, y))
            for a, pts in dot.items():
                pen = QPen(QColor(200, 216, 240, a))
                pen.setWidthF(wd)
                pen.setCapStyle(Qt.RoundCap)
                pp.setPen(pen)
                pp.drawPoints(pts)
        pp.end()
        self._space = pix
        self._space_size = (w, h)

        # 挑一批稍亮的星，让它们在前台微微闪（背景图是死的，动的是这一层）
        rnd2 = random.Random(8811)
        self.twinkle = [(rnd2.uniform(0, w), rnd2.uniform(0, h),
                         rnd2.choice([1.0, 1.4, 1.8, 2.4]),
                         rnd2.uniform(0, 6.283), rnd2.uniform(0.4, 1.3),
                         rnd2.choice([90, 120, 150, 190]))
                        for _ in range(TWINKLE)]

    def paintEvent(self, _ev):
        self.frames = getattr(self, "frames", 0) + 1
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._space is None or self._space_size != (self.width(), self.height()):
            self._build_space()
        p.drawPixmap(0, 0, self._space)
        if not self.reduce_motion and self.state != "scanning":
            self._draw_twinkle(p)

        c, R = self._center(), self._radius()
        self._draw_rings(p, c, R)

        st = self.state
        if st in ("done", "partial", "cancelled") and self.groups:
            self._draw_depth(p, c, R)
            self._draw_nebula(p, c, R)
            self._draw_sectors(p, c, R)
            self._draw_stars(p, c, R)
            self._draw_labels(p, c, R)
        elif st == "scanning":
            self._draw_scan_arc(p, c, R)
            self._draw_stars(p, c, R)
        elif st == "failed":
            self._draw_center_text(p, c, self.error_text or TEXT["failed"])
        elif st == "empty":
            self._draw_center_text(p, c, TEXT["empty"])
        else:
            self._draw_empty_hint(p, c, R)
        p.end()

    def _draw_twinkle(self, p):
        """会闪的背景星。透明度要**分档**，不能每颗一个值——
        每颗一个透明度就等于每颗换一次画笔，90 颗就是 90 次，帧率直接砍半。"""
        groups = {}
        for x, y, sz, ph, sp, base in getattr(self, "twinkle", ()):
            a = int(base * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(self.t_anim * sp + ph))))
            a = (max(0, min(240, a)) // 60) * 60          # 分成 5 档
            key = (a, sz)
            groups.setdefault(key, []).append(QPointF(x, y))
        for (a, sz), pts in groups.items():
            pen = QPen(QColor(214, 228, 255, a))
            pen.setWidthF(sz)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints(pts)

    def _draw_rings(self, p, c, R):
        for i, rr in enumerate(RING_RATIO):
            pen = QPen(QColor(120, 150, 200, 24 - i * 6))
            pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            rx, ry = R * rr, R * rr * self.flat
            p.drawEllipse(QRectF(c.x() - rx, c.y() - ry, rx * 2, ry * 2))

    def _draw_empty_hint(self, p, c, R):
        pen = QPen(QColor(120, 160, 220, 70))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(c.x() - R * 0.14, c.y() - R * 0.14 * self.flat,
                             R * 0.28, R * 0.28 * self.flat))

    def _draw_center_text(self, p, c, text):
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QPen(QColor("#9fb0c8")))
        p.drawText(QRectF(c.x() - 260, c.y() - 12, 520, 24), Qt.AlignCenter, text)

    def _draw_scan_arc(self, p, c, R):
        """扫描时中间那团东西：一颗在转的星云核 + 一道带拖尾的扫掠。

        扫掠用锥形渐变做，尾巴自然淡出，比画一条会跳的线便宜也好看。
        """
        # 星云核：三团错开的光，整体慢慢转
        for i, (rr, alpha, hue) in enumerate(((0.55, 62, (70, 120, 220)),
                                              (0.36, 54, (110, 90, 210)),
                                              (0.18, 66, (70, 160, 210)))):
            cx, cy = self._proj(c, R * rr, self.spin * (1.0 + i * 0.35) + i * 2.1)
            rad = R * (0.55 - i * 0.06)
            grad = QRadialGradient(cx, cy, rad)
            c1 = QColor(*hue)
            c1.setAlpha(alpha)
            c2 = QColor(*hue)
            c2.setAlpha(0)
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QRectF(cx - rad, cy - rad * self.flat, rad * 2, rad * 2 * self.flat))

        # 扫掠：锥形渐变，从转角开始最亮，转一圈淡回 0
        # 锥形渐变会变成"硬边三角形"，是因为 0.0 和 1.0 两个停靠点颜色不同，
        # 接缝处直接跳变。让两头都是 0、亮的部分放里面，就成了一道带拖尾的扫掠。
        sweep = QConicalGradient(c, -math.degrees(self.spin) % 360.0)
        sweep.setColorAt(0.00, QColor(120, 180, 255, 0))
        sweep.setColorAt(0.55, QColor(120, 180, 255, 0))
        sweep.setColorAt(0.88, QColor(120, 180, 255, 64))
        sweep.setColorAt(1.00, QColor(120, 180, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(sweep)
        p.drawEllipse(QRectF(c.x() - R, c.y() - R * self.flat, R * 2, R * 2 * FLAT))

        # 最外圈那条细线，标出"星云的范围"
        pen = QPen(QColor(91, 156, 246, 50))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(c.x() - R, c.y() - R * self.flat, R * 2, R * 2 * FLAT))

    def _sector_shift(self, gi):
        """浮起 10px / 下沉 4px（V2.0 §5.1），减少动效时一律不位移。"""
        if self.reduce_motion or gi < 0 or gi >= len(self.hi):
            return 0.0
        h = self.hi[gi]
        return -LIFT_HOVER * h if h > 0 else SINK_OTHER * (-h)

    def _draw_depth(self, p, c, R):
        """盘子的侧壁。没有它，12° 和 38° 看起来都是一张纸。"""
        for gi, g in enumerate(self.groups):
            a0, a1 = self.wedges[gi]
            h = self.hi[gi] if gi < len(self.hi) else 0.0
            dy = self._sector_shift(gi) * self.settle
            base = QColor(g["color"]).darker(200)
            steps = max(6, int((a1 - a0) / 0.09))
            for i in range(steps):
                b0 = a0 + (a1 - a0) * i / steps
                b1 = a0 + (a1 - a0) * (i + 1) / steps
                s = math.sin((b0 + b1) / 2)
                if s <= 0.03:
                    continue
                col = QColor(base)
                fade = 1.0 if h >= 0 else (1 + h * (1 - DIM_ALPHA))
                col.setAlpha(int(230 * min(1.0, s * 1.6) * fade))
                x0, y0 = self._proj(c, R * self.settle, b0)
                x1, y1 = self._proj(c, R * self.settle, b1)
                path = QPainterPath()
                path.moveTo(x0, y0 + dy)
                path.lineTo(x1, y1 + dy)
                path.lineTo(x1, y1 + dy + DEPTH)
                path.lineTo(x0, y0 + dy + DEPTH)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawPath(path)

    def _draw_nebula(self, p, c, R):
        """每组背后一团星云光。立体之外，"星云"的感觉主要靠它。"""
        for gi, g in enumerate(self.groups):
            a0, a1 = self.wedges[gi]
            am = (a0 + a1) / 2
            h = self.hi[gi] if gi < len(self.hi) else 0.0
            dy = self._sector_shift(gi) * self.settle
            gx, gy = self._proj(c, R * 0.55, am)
            rad = min(R * 0.85, max(38.0, R * (a1 - a0) * 0.55 + R * 0.18))
            col = QColor(g["color"])
            a_in = NEBULA_ALPHA + int(20 * max(0.0, h))
            if h < 0:
                a_in = int(NEBULA_ALPHA * (1 + h * (1 - DIM_ALPHA)))
            grad = QRadialGradient(gx, gy + dy, rad)
            c1 = QColor(col)
            c1.setAlpha(max(0, a_in))
            c2 = QColor(col)
            c2.setAlpha(0)
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QRectF(gx - rad, gy + dy - rad * self.flat,
                                 rad * 2, rad * 2 * self.flat))

    def _draw_sectors(self, p, c, R):
        """扇区不用描边、不留硬边。

        做法：每个扇区用一圈径向渐变填（中间实、边缘化开），
        扇区之间留一条小缝，再叠一层同色的星云光晕 —— 边界就"软"了。
        """
        t = self.settle
        for gi, g in enumerate(self.groups):
            a0, a1 = self.wedges[gi]
            a0 += WEDGE_GAP / 2
            a1 -= WEDGE_GAP / 2
            if a1 <= a0:
                continue
            dy = self._sector_shift(gi) * t
            h = self.hi[gi] if gi < len(self.hi) else 0.0

            path = QPainterPath()
            path.moveTo(c.x(), c.y() + dy)
            steps = max(10, int((a1 - a0) / 0.05))
            for i in range(steps + 1):
                a = a0 + (a1 - a0) * i / steps
                x, y = self._proj(c, R * t, a)
                path.lineTo(x, y + dy)
            path.closeSubpath()

            # 径向渐变：中心略亮、边缘淡出，不要块状色片
            col = QColor(g["color"])
            if h < 0:
                base = int(26 * (1 + h * (1 - DIM_ALPHA)))
            else:
                base = int(22 + 26 * h)
            grad = QRadialGradient(c.x(), c.y() + dy, R * max(0.2, t))
            c1 = QColor(col)
            c1.setAlpha(base + 12)
            c2 = QColor(col)
            c2.setAlpha(max(0, base - 6))
            grad.setColorAt(0.0, c1)
            grad.setColorAt(0.75, c1)
            grad.setColorAt(1.0, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawPath(path)

    def _draw_stars(self, p, c, R):
        now = time.perf_counter()
        dots = {}

        if self.state == "scanning":
            for st in self.stars:
                p01 = (now - st["t0"]) / FLY_SECS
                if p01 < 0.0:
                    continue
                if p01 > 1.0:
                    p01 = 1.0
                k = 1.0 - (1.0 - p01) ** 3
                ang = st["sang"] + (st["ang"] + self.spin - st["sang"]) * k
                rad = st["srad"] + (st["rad"] - st["srad"]) * k
                x, y = self._proj(c, R * rad, ang)
                col = QColor(st["color"])
                col.setAlpha(int(50 + 200 * min(1.0, p01 * 2.2)))
                key = (col.red(), col.green(), col.blue(), col.alpha())
                dots.setdefault(key, (col, []))[1].append(QPointF(x, y))
        else:
            t = self.settle
            e = 1.0 - (1.0 - t) ** 3
            for st in self.stars:
                gi = st["group"]
                h = self.hi[gi] if gi < len(self.hi) else 0.0
                dy = self._sector_shift(gi) * t if gi < len(self.hi) else 0.0
                fa = st.get("f_ang", st["ang"])
                fr = st.get("f_rad", st["rad"])
                ang = fa + (st["ang"] - fa) * e + self.spin
                rad = fr + (st["rad"] - fr) * e
                if not self.reduce_motion:
                    # 相位已经存好了，别再每帧算哈希 —— 1010 颗星就是每帧 1010 次，
                    # 光这一项就吃掉 13ms，帧率从 80 掉到 40。
                    rad *= 1.0 + BREATH * math.sin(self.t_anim * 1.1 + st.get("ph", 0.0))
                x, y = self._proj(c, R * rad, ang)
                y += dy
                col = QColor(st["color"])
                if h < 0:
                    col.setAlpha(int(200 * (1 + h * (1 - DIM_ALPHA))))
                else:
                    col.setAlpha(min(255, int(185 + 50 * h)))
                key = (col.red(), col.green(), col.blue(), col.alpha())
                dots.setdefault(key, (col, []))[1].append(QPointF(x, y))

        # 两遍画：先一圈很淡的光晕，再点上那颗亮芯。
        # 单画一个点看起来是"色块"，有光晕才像星星。
        if self.reduce_motion:
            for col, pts in dots.values():
                pen = QPen(col)
                pen.setWidthF(STAR_R)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawPoints(pts)
            return

        for col, pts in dots.values():
            halo = QColor(col)
            halo.setAlpha(max(0, int(col.alpha() * 0.22)))
            pen = QPen(halo)
            pen.setWidthF(STAR_R * 3.1)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints(pts)
        for col, pts in dots.values():
            pen = QPen(col)
            pen.setWidthF(STAR_R * 0.92)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints(pts)

    def _draw_labels(self, p, c, R):
        f = QFont()
        f.setPixelSize(12)
        p.setFont(f)
        for gi, g in enumerate(self.groups):
            a0, a1 = self.wedges[gi]
            if (a1 - a0) < 0.26:
                continue
            am = (a0 + a1) / 2
            h = self.hi[gi] if gi < len(self.hi) else 0.0
            dy = self._sector_shift(gi)
            # 半径交替，相邻两个标签不会挤在一起
            rr = 1.09 if gi % 2 == 0 else 1.22
            x, y = self._proj(c, R * rr, am)
            name = os.path.basename(g["key"]) or g["key"]
            if len(name) > 10:
                name = name[:9] + "…"
            col = QColor(g["color"])
            col.setAlpha(int(235 if h >= 0 else 120))
            p.setPen(QPen(col))
            p.drawText(QRectF(x - 62, y - 12 + dy, 124, 14), Qt.AlignCenter, name)
            p.setPen(QPen(QColor(159, 176, 200, int(170 if h >= 0 else 90))))
            p.drawText(QRectF(x - 62, y + 2 + dy, 124, 14), Qt.AlignCenter,
                       "%d 个" % g["count"])

    # ---------------------------------------------------------- 交互

    def _hit(self, pos):
        if not self.groups or not self.wedges:
            return -1
        c, R = self._center(), self._radius()
        dx = pos.x() - c.x()
        dy = (pos.y() - c.y()) / max(0.01, self.flat)
        if math.hypot(dx, dy) > R * 1.10:
            return -1
        ang = math.atan2(dy, dx) - self.yaw
        while ang < -math.pi / 2:
            ang += math.tau
        while ang >= math.tau - math.pi / 2:
            ang -= math.tau
        for gi, (a0, a1) in enumerate(self.wedges):
            if a0 <= ang < a1:
                return gi
        return -1

    def mouseMoveEvent(self, ev):
        if self.dragging:
            x, y = ev.position().x(), ev.position().y()
            px, py = self.drag_prev
            dx, dy = x - px, y - py
            self.yaw += dx * 0.008
            self.flat = min(1.0, max(0.18, self.flat - dy * 0.0035))
            self.vel_yaw = dx * 0.0022
            self.vel_flat = -dy * 0.0010
            self.moved += abs(dx) + abs(dy)
            self.drag_prev = (x, y)
            self.update()
            return
        idx = self._hit(ev.position())
        if idx != self.hover:
            self.hover = idx
            self.update()
        self.setCursor(Qt.PointingHandCursor if idx >= 0 else Qt.OpenHandCursor)

    def leaveEvent(self, _ev):
        if self.hover != -1:
            self.hover = -1
            self.update()

    def _on_wedge(self, pos):
        return self._hit(pos)

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        idx = self._hit(ev.position())
        if idx >= 0:
            self.sel = -1 if idx == self.sel else idx
            self.update()
            return
        # 空白处按下 = 开始转视角
        self.dragging = True
        self.moved = 0.0
        self.vel_yaw = 0.0
        self.vel_flat = 0.0
        self.drag_prev = (ev.position().x(), ev.position().y())
        self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton or not self.dragging:
            return
        self.dragging = False
        if self.moved < 3:                 # 基本没动 = 点空白，取消选中
            self.sel = -1
            self.vel_yaw = 0.0
            self.vel_flat = 0.0
            self.update()
        self.setCursor(Qt.OpenHandCursor)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            self.sel, self.hover = -1, -1
            self.update()
            return
        if not self.groups:
            return
        if k in (Qt.Key_Left, Qt.Key_Up):
            base = self.sel if self.sel >= 0 else 0
            self.sel = (base - 1) % len(self.groups)
            self.update()
        elif k in (Qt.Key_Right, Qt.Key_Down):
            base = self.sel if self.sel >= 0 else -1
            self.sel = (base + 1) % len(self.groups)
            self.update()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.sel = self.hover if self.sel < 0 else -1
            self.update()

    def current_group(self):
        idx = self.sel if self.sel >= 0 else self.hover
        if 0 <= idx < len(self.groups):
            return idx, self.groups[idx]
        return -1, None


# ---------------------------------------------------------------- 主窗口

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DiskProbe · 软件星团")
        self.resize(1180, 760)
        # 以前这里用 QWidget{...} 全局选择器，会给每个子控件套一遍样式，
        # 每次重绘都可能触发样式重算。改成只设窗口自己。
        self.setStyleSheet(
            "MainWindow{background:#070b14;color:#e8ecf4;}")
        self.setAutoFillBackground(True)
        self.worker = None
        self.root = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)

        # ---- A. 顶部状态区
        top = QHBoxLayout()
        top.setSpacing(14)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel("软件星团")
        self.title.setStyleSheet("font-size:15px;font-weight:600;")
        self.status = QLabel(TEXT["S0_title"])
        self.status.setStyleSheet("font-size:13px;color:#9fb0c8;")
        self.detail = QLabel("")
        self.detail.setStyleSheet("font-size:11px;color:#5d6d85;")
        col.addWidget(self.title)
        col.addWidget(self.status)
        col.addWidget(self.detail)
        top.addLayout(col, 1)

        self.btn = QPushButton(TEXT["S0_btn"])
        self.btn.setFixedHeight(34)
        self.btn.setMinimumWidth(108)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setStyleSheet(
            "QPushButton{background:#182236;border:1px solid #2b3c58;border-radius:6px;"
            "color:#cfe0ff;font-size:13px;}"
            "QPushButton:hover{background:#20304a;border-color:#3d587f;}"
            "QPushButton:pressed{background:#121a29;}"
            "QPushButton:disabled{color:#54637a;border-color:#1e2735;}")
        self.btn.clicked.connect(self.on_button)
        top.addWidget(self.btn, 0)

        self.fps = QLabel("")
        self.fps.setStyleSheet("font-size:11px;color:#4d5c72;")
        top.addWidget(self.fps, 0)

        self.chk = QCheckBox("减少动效")
        self.chk.setStyleSheet("QCheckBox{font-size:12px;color:#8fa0b8;}")
        self.chk.stateChanged.connect(self.on_reduce_motion)
        top.addWidget(self.chk, 0)
        root.addLayout(top)

        # ---- B + C
        mid = QHBoxLayout()
        mid.setSpacing(14)
        self.canvas = StarCanvas()
        mid.addWidget(self.canvas, 1)

        self.panel = QFrame()
        self.panel.setFixedWidth(272)
        self.panel.setStyleSheet(
            "QFrame{background:#0b1120;border:1px solid #182133;border-radius:8px;}")
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(8)
        self.p_name = QLabel("")
        self.p_name.setStyleSheet("font-size:16px;font-weight:600;")
        self.p_meta = QLabel("")
        self.p_meta.setStyleSheet("font-size:12px;color:#9fb0c8;")
        self.p_meta.setWordWrap(True)
        self.p_files = QLabel("")
        self.p_files.setStyleSheet("font-size:11px;color:#71839c;line-height:150%;")
        self.p_files.setWordWrap(True)
        self.p_note = QLabel("拖动空白处转视角，上下拖动改倾角\n"
                             "悬停看分组，点一下锁定，Esc 取消")
        self.p_note.setStyleSheet("font-size:11px;color:#4d5c72;")
        self.p_note.setWordWrap(True)
        pl.addWidget(self.p_name)
        pl.addWidget(self.p_meta)
        pl.addSpacing(6)
        pl.addWidget(self.p_files)
        pl.addStretch(1)
        pl.addWidget(self.p_note)
        mid.addWidget(self.panel, 0)

        root.addLayout(mid, 1)

        self.foot = QLabel(TEXT["scale_note"])
        self.foot.setStyleSheet("font-size:11px;color:#4d5c72;")
        root.addWidget(self.foot)

        self._panel_idx = None
        self._fps_n = 0
        self._fps_t = time.perf_counter()
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._tick_fps)
        self._fps_timer.start(500)
        self.panel_timer = QTimer(self)
        self.panel_timer.timeout.connect(self.refresh_panel)
        self.panel_timer.start(120)

    # ---------------------------------------------------------- 文案与状态

    def set_status(self, line, sub=""):
        self.status.setText(line)
        self.detail.setText(sub)

    def on_reduce_motion(self):
        on = self.chk.isChecked()
        self.canvas.reduce_motion = on
        if on:
            for i in range(len(self.canvas.hi)):
                self.canvas.hi[i] = 0.0
            self.canvas.settle = 1.0
            self.canvas.update()

    def on_button(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.btn.setEnabled(False)
            self.set_status("正在取消…", "已发现 %d 个 EXE" % len(self.canvas.files))
            return
        folder = QFileDialog.getExistingDirectory(self, "选择要扫描的目录", "D:\\")
        if not folder:
            return                       # 取消选择 → 保持原状态（V2.0 §S1）
        self.start_scan(folder)

    def start_scan(self, folder):
        self.root = folder
        self.canvas.start_scan()
        self.btn.setEnabled(True)
        self.btn.setText("取消扫描")
        self.set_status(TEXT["scanning"] % folder, TEXT["found"] % 0)

        self.worker = ScanWorker(folder)
        self.worker.found.connect(self.on_batch)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_batch(self, batch):
        self.canvas.add_batch(batch)
        self.set_status(TEXT["scanning"] % self.root,
                        TEXT["found"] % len(self.canvas.files))

    def on_done(self, result):
        self.btn.setText(TEXT["S0_btn"])
        self.btn.setEnabled(True)
        self.canvas.set_result(result)
        st = self.canvas.state
        n = len(self.canvas.files)
        g = getattr(self.canvas, "total_groups", len(self.canvas.groups))
        if st == "failed":
            self.set_status(TEXT["failed"], result.get("error") or "")
        elif st == "empty":
            self.set_status(TEXT["empty"], self.root or "")
        elif st == "cancelled":
            self.set_status(TEXT["cancelled"], "已发现 %d 个 EXE" % n)
        elif st == "partial":
            self.set_status(TEXT["done"] % (n, g), TEXT["partial"])
        else:
            self.set_status(TEXT["done"] % (n, g), self.root or "")

    def on_failed(self, msg):
        self.btn.setText(TEXT["S0_btn"])
        self.btn.setEnabled(True)
        self.canvas.state = "failed"
        self.canvas.error_text = msg
        self.canvas.update()
        self.set_status(TEXT["failed"], msg)

    def _tick_fps(self):
        n = getattr(self.canvas, "frames", 0)
        self.canvas.frames = 0
        now = time.perf_counter()
        dt = now - self._fps_t
        self._fps_t = now
        if dt > 0:
            self.fps.setText("%.0f fps" % (n / dt))

    # ---------------------------------------------------------- 详情区

    def refresh_panel(self):
        idx, g = self.canvas.current_group()
        # 只有"当前看的是哪一组"变了才改文字。
        # 之前每 120ms 无条件 setText，而标签开了自动换行，
        # 于是每 120ms 触发一次整个窗口的布局重算 —— 那才是卡顿的真凶。
        if idx == self._panel_idx:
            return
        self._panel_idx = idx
        if not g:
            self.p_name.setText("")
            self.p_meta.setText("")
            self.p_files.setText("")
            self.p_note.setVisible(True)
            return
        self.p_note.setVisible(False)
        name = os.path.basename(g["key"]) or g["key"]
        pct = 100.0 * g["count"] / max(1, len(self.canvas.files))
        self.p_name.setText(name)
        self.p_meta.setText("%s" % g["key"])
        self.p_files.setText("%d 个 EXE · 占 %.1f%% · %.1f MB\n\n%s" % (
            g["count"], pct, g["size"] / 1048576,
            "\n".join(sorted(os.path.basename(r["path"])
                             for r in g["files"])[:10])
            + ("\n…" if g["count"] > 10 else "")))

    def keyPressEvent(self, ev):
        self.canvas.keyPressEvent(ev)
        self.refresh_panel()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
