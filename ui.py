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

from PySide6.QtCore import (QEasingCurve, QEvent, QPointF, QRectF, Qt, QThread,
                            QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter,
                           QImage, QPainterPath, QPen, QPixmap, QTransform, QConicalGradient,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import classify
import scanner

# ---------------------------------------------------------------- 规范参数
# 数值全部来自 V2.0。改这里就等于改规范。

TILT_DEG = 38.0                 # V2.0 §2.2 写的是 8–15°，但老大要"立体"，改成 38°
DEPTH = 20                      # 盘的厚度（像素），立体感靠它
FLAT = math.cos(math.radians(TILT_DEG))
RING_RATIO = (1.00, 1.22, 1.46)
DIAMETER_RATIO = 0.92           # 星图直径 = 短边 92%（之前 0.66 只占 45%，主视图没撑起来）

LIFT_HOVER = 10.0               # §5.1 浮起 6–12px
SINK_OTHER = 4.0                # §5.1 其他下沉 3–6px
DIM_ALPHA = 0.55                # §5.1 其他降到 45%–65%
# ---- 动效 token（交互叙事闭环.md）------------------------------------
# 全项目只许用这几个时长与曲线，别再出现 0.45 / 0.08 这种散装数字。
MS_PRESS = 90
MS_FAST = 140
MS_BASE = 220
MS_SLOW = 420
MS_SCENE = 700


def ease_std(t):
    """标准曲线，近似 Material 的 cubic-bezier(0.2, 0, 0, 1)。"""
    return t * t * (3.0 - 2.0 * t)


def ease_decel(t):
    """入场：先快后慢，落定感。"""
    return 1.0 - (1.0 - t) ** 3


def ease_accel(t):
    """退场：先慢后快，干脆。"""
    return t ** 3


def approach(cur, target, dt, ms):
    """按 token 时长做指数逼近，帧率无关。"""
    if ms <= 0:
        return target
    k = 1.0 - math.exp(-dt * 1000.0 / (ms * 0.42))
    return cur + (target - cur) * k


T_HOVER = MS_BASE / 1000.0
T_SETTLE = 0.45                 # §7 扇区重排 250–450ms
BATCH_MS = 150                  # §8.2 每 100–200ms 合批

STAR_R = 2.15
FLY_SECS = 0.62                 # 一颗星从外面飞进星云用的时间
SPIN_SPEED = 0.85               # 扫描时星云的旋转角速度（弧度/秒）
IDLE_FLOW = 0.045               # 完成后极慢的整体流动（弧度/秒，约 2.6°/s）
BREATH = 0.014                  # 呼吸：星点半径起伏幅度
RELEASE_PER_FRAME = 3           # 每帧最多放几颗星出来（视觉节奏，数据不受影响）
TWINKLE = 90                    # 会闪的背景星数量
STARFIELD = 2600                # 背景星点数量（臂间的小暗星也算在这里）
WEDGE_GAP = 0.014               # 相邻分组之间的缝
TWIST = 2.35                    # 每条臂向外卷多少弧度
TURNS = 1.0                     # 兼容旧代码（多臂布局后不再使用）
ARM_MIN = 0.30                  # 最短的臂卷到哪里（占半径比例）
ARM_SCATTER = 0.16              # 星点垂直于臂的散布（占半径比例）
ARM_ANGLE_SPREAD = 0.30         # 垂直于臂的角度散布（弧度）
FADE_SECS = 0.45                # 状态切换的淡入时间
CORE_R = 0.30                   # 核球半径（占盘半径比例）
FLAT_EMPTY = 0.17               # 什么都没扫到时，相机几乎贴平
FLAT_FULL = 0.86                # 星团成形后抬起来
BLOOM = 0.62                    # 辉光强度
SPIKES = 30                     # 有几颗亮星带十字星芒
GROUP_CAP = 9                  # §4.3 主星团只展示主要分组，其余归「其他」

BG_TOP = QColor("#070b14")
BG_BOTTOM = QColor("#0a0e1a")
INK = QColor("#e8ecf4")
INK_DIM = QColor("#9fb0c8")
INK_FAINT = QColor("#4d5c72")
ACCENT = QColor("#5b9cf6")

# 全部压到蓝紫区间，靠明度和微色相区分。真实银河的臂就是这个色系，
# 之前那套彩虹色一眼是"图表"，不是"天体"。
PALETTE = ["#a9c2ff", "#7f95f5", "#b0a2f8", "#6a8ce0", "#c2b4ff",
           "#5f7fd8", "#93a8f0", "#8b7fd8", "#a6b6f2"]

NEBULA_ALPHA = 46               # 每组背后那团星云的中心亮度
STARFIELD = 420                 # 背景星点数量

TEXT = {
    "S0_title": "你的软件星团还未被探索",
    "S0_desc": "点右下角「扫描目录」，选一个文件夹开始。",
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


def gauss01(h, salt=0):
    """把字符串变成 -1..1 的准高斯值（三个均匀相加再归一）。
    星云是中间密、边上稀，均匀分布看起来是"撒了一把盐"。"""
    v = hash01(h, salt) + hash01(h, salt + 101) + hash01(h, salt + 202) - 1.5
    return v / 1.5


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
        self.setStyleSheet("background:#05080f;")
        self.setAutoFillBackground(True)
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
        self.match = None            # 搜索命中集合（None = 不过滤）
        self.live_keys = []          # 扫描期间按目录先归堆，让星星一开始就在旋臂上
        self.live_counts = {}
        self.t_anim = 0.0            # 呼吸用的连续时间
        self.fade = 0.0              # 状态切换的淡入量
        self.total_t = math.tau * TURNS   # 螺旋总参数长度
        self.yaw = 0.0               # 视角的水平旋转（拖动改它）
        self.flat = FLAT_EMPTY       # 一开就贴平：先看到一片空域
        self.zoom = 1.0              # 滚轮缩放
        self.yaw_target = None       # 选中某条臂时，相机朝它转过去
        self.focus_gi = -1           # 当前聚焦的臂
        self.vel_yaw = 0.0
        self.vel_flat = 0.0
        self.dragging = False
        self.drag_prev = (0.0, 0.0)
        self._pending = []           # 扫描到但还没轮到出场的星
        self.moved = 0.0

        self.reduce_motion = False

        self._space = None
        self._space_size = None
        self._gcache = None
        self._gcache_key = None
        self._gcache_pad = 0
        self._last_frame = time.perf_counter()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ---------------------------------------------------------- 数据接口

    def set_filter(self, text):
        """搜索：命中的星变亮，其余压暗。星系本身就是搜索结果。"""
        text = (text or "").strip().lower()
        if not text:
            self.match = None
        else:
            self.match = {r["path"] for r in self.files
                          if text in r["path"].lower()}
        self.update()

    def reset(self):
        self.state = "S0"
        self.files = []
        self.groups = []
        self.wedges = []
        self.stars = []
        self.live_keys = []
        self.live_counts = {}
        self.hi = []
        self.hover = -1
        self.sel = -1
        self.settle = 1.0
        self.spin = 0.0
        self.update()

    def start_scan(self):
        self.reset()
        self.state = "scanning"
        self.fade = 0.0
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
            self.fade = 0.0
            self.error_text = err
            self.update()
            return
        if not self.files:
            self.state = "cancelled" if cancelled else "empty"
            self.fade = 0.0
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
        """每个分组 = 一条独立的旋臂。

        以前是一条螺旋线切成 N 段：既看不清界限，也撑不满画面。
        现在每组从核心各伸出一条臂，向外卷，组与组天然分开。
        """
        old = {}
        for st in self.stars:
            old[st.get("path", "")] = (st.get("rp", 0.5), st.get("ang", 0.0))

        self.wedges = []
        for gi in range(len(self.groups)):
            self.wedges.append((0.0, self.arm_span(gi)))

        new_stars = []
        for gi, g in enumerate(self.groups):
            span = self.arm_span(gi)
            for rec in g["files"]:
                s = hash01(rec["path"], 11)              # 沿臂的位置
                r, a = self.arm_point(gi, s)

                # 垂直臂方向散开：越靠臂梢越宽，臂才有厚度
                w = 0.55 + 1.5 * s
                rad_p = r + gauss01(rec["path"], 41) * ARM_SCATTER * 0.55 * w
                ang = a + gauss01(rec["path"], 53) * ARM_ANGLE_SPREAD * 0.55 * w
                # 臂根留白：免得所有臂在中心糊成一团
                rad_p = max(0.10, rad_p)

                star = {
                    "path": rec["path"],
                    "t": s,
                    "gi": gi,
                    "rp": rad_p,
                    "ang": ang,
                    "group": gi,
                    "color": g["color"],
                    "ph": hash01(rec["path"], 5) * 6.283,
                }
                if rec["path"] in old:
                    star["f_rp"], star["f_ang"] = old[rec["path"]]
                else:
                    star["f_rp"] = rad_p
                    star["f_ang"] = ang
                new_stars.append(star)
        self.stars = new_stars
        self.spin = 0.0

    def prov_arm_point(self, gi, s):
        """扫描期间用的"临时臂位"。

        这时还不知道最终每个分组多大，但已经知道每个文件属于哪个目录。
        所以先按目录把它们摆到 9 条臂上 —— 画面从一开始就是螺旋，
        扫完之后只是"归位"，不是"从饼变成螺旋"，两段动画因此接得上。
        """
        n = max(1, min(9, len(self.live_keys) or 1))
        phase = -math.pi / 2 + math.tau * (gi % 9) / 9
        r = 0.10 + 0.80 * (s ** 1.15)
        a = phase + TWIST * s * 0.78
        return r, a

    def arm_phase(self, gi):
        """第 gi 条臂的起始角。均匀铺开，所以每条臂互不重叠。"""
        n = max(1, len(self.groups))
        return -math.pi / 2 + math.tau * gi / n

    def arm_span(self, gi):
        """这条臂卷到多大半径。用数量的开方做映射：
        数量多的臂更长更粗，但不会把别的臂挤没。"""
        counts = [g["count"] for g in self.groups] or [1]
        mx = max(counts) or 1
        # 指数越大差距越明显：大组甩出很长的臂，小组只探出一点点，
        # 这才有"主臂 + 副臂"的层次，而不是九根一样长的风车。
        k = (self.groups[gi]["count"] / mx) ** 1.15
        return ARM_MIN + (1.0 - ARM_MIN) * k

    def arm_point(self, gi, s):
        """s 在 0..1（臂根到臂梢）-> (半径比例, 角度)。"""
        span = self.arm_span(gi)
        r = 0.10 + 0.90 * (span * s) ** 1.15
        a = self.arm_phase(gi) + TWIST * s * span
        return r, a

    def _spiral(self, t):
        """螺旋参数 t（弧度，0 = 臂根）-> (半径比例, 角度)。

        半径随 t 线性增长，角度也随 t 增长，合起来就是一条阿基米德螺旋。
        分组 = 这条螺旋上的一段，所以"某组占多少角度"仍然等于"它占多少数量"。
        """
        frac = max(0.0, min(1.0, t / max(1e-6, self.total_t)))
        # 指数型：内圈密、外圈舒展，这是银河看起来"卷"的原因。
        # 线性会让它读成同心环。
        return 0.09 + 0.91 * (frac ** 1.55), -math.pi / 2 + t

    def frac_hint(self, t):
        return max(0.0, min(1.0, t / max(1e-6, self.total_t)))

    def _t_of_radius(self, r):
        """反算：半径比例 -> 螺旋参数。命中检测用。"""
        frac = max(0.0, min(1.0, (r - 0.09) / 0.91))
        return (frac ** (1.0 / 1.55)) * self.total_t

    def _center(self):
        return QPointF(self.width() * 0.5, self.height() * 0.52)

    def _radius(self):
        return min(self.width(), self.height()) * DIAMETER_RATIO * 0.5 * self.zoom

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
                # 扫描时还不知道最终分组，先按"等分螺旋"占个位置，
                # 扫描结束 _assign_targets 会重算（那时才知道每个组多大）
                # 扫描期就按目录归臂：星星一开始就沿着螺旋往里飞，
                # 而不是先在饼里摊平、扫完再突然变成螺旋。
                key = classify.dir_key(rec["path"])
                if key not in self.live_counts:
                    if len(self.live_keys) < 9:
                        self.live_keys.append(key)
                    self.live_counts[key] = 0
                self.live_counts[key] += 1
                gi = self.live_keys.index(key) if key in self.live_keys else 8

                s = hash01(rec["path"], 11)
                r, a = self.prov_arm_point(gi, s)
                w = 0.55 + 1.5 * s
                r += gauss01(rec["path"], 41) * ARM_SCATTER * 0.5 * w
                a += gauss01(rec["path"], 53) * ARM_ANGLE_SPREAD * 0.5 * w

                self.stars.append({
                    "path": rec["path"],
                    "prp": max(0.08, r),
                    "pang": a,
                    "sang": math.tau * hash01(rec["path"], 31),
                    "srad": 1.25 + 0.55 * hash01(rec["path"], 41),
                    "t0": now2 + j * 0.012,
                    "ph": hash01(rec["path"], 5) * 6.283,
                    "group": gi,
                    "color": QColor("#8fb8e8"),
                })
            busy = True

        # 相机朝向目标（选中某条臂时）。转过去，用户就不用自己在脑子里转。
        if self.yaw_target is not None and not self.dragging:
            self.yaw = approach(self.yaw, self.yaw_target, dt, MS_SLOW)
            if abs(self.yaw - self.yaw_target) < 0.004:
                self.yaw = self.yaw_target
                self.yaw_target = None
            busy = True

        # 拖动松手后的惯性
        if not self.dragging and (abs(self.vel_yaw) > 1e-4 or abs(self.vel_flat) > 1e-4):
            self.yaw += self.vel_yaw
            self.flat = min(1.0, max(0.18, self.flat + self.vel_flat))
            self.vel_yaw *= 0.90
            self.vel_flat *= 0.90
            busy = True

        # 相机：什么都没扫到时几乎贴平（像在观测一片空域），
        # 星星聚起来之后才慢慢抬起来看这张盘。
        if not self.dragging and self.state in ("S0", "scanning", "empty"):
            tgt = FLAT_EMPTY + (FLAT_FULL - FLAT_EMPTY) * min(1.0, len(self.stars) / 240.0)
            self.flat += (tgt - self.flat) * (1.0 - math.exp(-1.5 * dt))
            busy = True

        if self.fade < 1.0:
            self.fade = min(1.0, self.fade + dt / FADE_SECS)
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
        """深空背景：更深的黑 + 大范围星云 + 1700 颗星 + 暗角。

        之前那张背景的问题是"平"——整幅一个亮度，没有纵深。
        加暗角（四角压黑）之后，视线会被收到中间，像照片而不是画布。
        """
        w, h = self.width(), self.height()
        pix = QPixmap(w, h)
        pix.fill(QColor("#04050a"))
        pp = QPainter(pix)
        pp.setRenderHint(QPainter.Antialiasing, True)

        g = QLinearGradient(0, 0, w * 0.35, h)
        g.setColorAt(0.0, QColor("#05070f"))
        g.setColorAt(0.5, QColor("#070912"))
        g.setColorAt(1.0, QColor("#08060e"))
        pp.setPen(Qt.NoPen)
        pp.setBrush(g)
        pp.drawRect(0, 0, w, h)

        # 大范围星云：紫、蓝、一点暖
        for cx, cy, rad, col, a_in in (
            (w * 0.30, h * 0.28, w * 0.62, QColor(96, 88, 200), 22),
            (w * 0.74, h * 0.70, w * 0.55, QColor(70, 110, 200), 18),
            (w * 0.58, h * 0.18, w * 0.40, QColor(150, 110, 190), 13),
            (w * 0.20, h * 0.82, w * 0.34, QColor(190, 120, 90), 8),
        ):
            ng = QRadialGradient(cx, cy, rad)
            c1 = QColor(col)
            c1.setAlpha(a_in)
            c2 = QColor(col)
            c2.setAlpha(0)
            ng.setColorAt(0.0, c1)
            ng.setColorAt(0.55, c1)
            ng.setColorAt(1.0, c2)
            pp.setBrush(ng)
            pp.drawEllipse(QRectF(cx - rad, cy - rad, rad * 2, rad * 2))

        # 银河带：斜着的一条更密的星流
        band = QLinearGradient(0, 0, w, h)
        band.setColorAt(0.00, QColor(120, 140, 230, 0))
        band.setColorAt(0.42, QColor(130, 150, 235, 14))
        band.setColorAt(0.52, QColor(165, 175, 245, 18))
        band.setColorAt(1.00, QColor(120, 140, 230, 0))
        pp.setBrush(band)
        pp.drawRect(0, 0, w, h)

        rnd = random.Random(20261030)
        layers = ((0.55, 1.0, [12, 18, 24, 32]),
                  (0.30, 1.7, [34, 46, 60, 78]),
                  (0.15, 2.4, [70, 96, 130, 170]))
        for share, wd, alphas in layers:
            dot = {}
            for _ in range(int(STARFIELD * share)):
                x, y = rnd.uniform(0, w), rnd.uniform(0, h)
                a = rnd.choice(alphas)
                # 少量偏暖的星，整片才不死
                warm = rnd.random() < 0.12
                dot.setdefault((a, warm), []).append(QPointF(x, y))
            for (a, warm), pts in dot.items():
                col = QColor(255, 226, 198, a) if warm else QColor(206, 220, 255, a)
                pen = QPen(col)
                pen.setWidthF(wd)
                pen.setCapStyle(Qt.RoundCap)
                pp.setPen(pen)
                pp.drawPoints(pts)

        # 噪声：一层极低透明度的随机点，星空和星云才不会像纯渐变
        rnd_n = random.Random(4411)
        noise = QImage(max(1, w // 2), max(1, h // 2), QImage.Format_ARGB32_Premultiplied)
        noise.fill(QColor(0, 0, 0, 0))
        np_ = QPainter(noise)
        for _ in range((w * h) // 260):
            x = rnd_n.uniform(0, noise.width())
            y = rnd_n.uniform(0, noise.height())
            a = rnd_n.choice([6, 10, 14, 20])
            np_.setPen(Qt.NoPen)
            np_.setBrush(QColor(180, 196, 255, a))
            r = rnd_n.uniform(0.6, 1.8)
            np_.drawEllipse(QRectF(x, y, r, r))
        np_.end()
        pp.setOpacity(0.85)
        pp.drawImage(QRectF(0, 0, w, h), noise)
        pp.setOpacity(1.0)

        # 暗角：四角压黑，视线收到中间
        vig = QRadialGradient(w * 0.5, h * 0.5, max(w, h) * 0.72)
        vig.setColorAt(0.00, QColor(0, 0, 0, 0))
        vig.setColorAt(0.62, QColor(0, 0, 0, 0))
        vig.setColorAt(1.00, QColor(0, 0, 0, 165))
        pp.setBrush(vig)
        pp.drawRect(0, 0, w, h)
        pp.end()

        self._space = pix
        self._space_size = (w, h)

        rnd2 = random.Random(8811)
        self.twinkle = [(rnd2.uniform(0, w), rnd2.uniform(0, h),
                         rnd2.choice([1.0, 1.4, 1.8, 2.4]),
                         rnd2.uniform(0, 6.283), rnd2.uniform(0.4, 1.3),
                         rnd2.choice([90, 120, 150, 190]))
                        for _ in range(TWINKLE)]

    def paintEvent(self, _ev):
        self.frames = getattr(self, "frames", 0) + 1
        w, h = self.width(), self.height()
        if w < 8 or h < 8:
            return

        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        # 底色必须是不透明的。之前填全透明，只要背景 pixmap 差 1px 没盖满，
        # 边缘就会透出控件默认色，在画布四周形成一条浅灰亮线。
        img.fill(QColor("#05080f"))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)

        if self._space is None or self._space_size != (w, h):
            self._build_space()
        p.drawPixmap(0, 0, self._space)
        if not self.reduce_motion and self.state != "scanning":
            self._draw_twinkle(p)

        c, R = self._center(), self._radius()
        p.setOpacity(max(0.15, self.fade))
        self._draw_rings(p, c, R)

        st = self.state
        if st in ("done", "partial", "cancelled") and self.groups:
            cache = self._galaxy_cache()
            if cache is not None:
                # 旋转 + 压扁用一个变换做完，然后一次贴图
                tr = QTransform()
                tr.translate(c.x(), c.y())
                tr.scale(1.0, self.flat)
                tr.rotateRadians(self.yaw + self.spin)
                p.save()
                p.setTransform(tr, True)
                pad = self._gcache_pad
                p.drawImage(-pad, -pad, cache)
                p.restore()
            self._draw_stars(p, c, R)
            self._draw_spikes(p, c, R)
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
        p.setOpacity(1.0)
        p.end()

        qp = QPainter(self)
        # 先把整块铺成底色：150% DPI 下，逻辑坐标画的整幅图在边缘会差半个像素，
        # 那条缝会露出窗口底色，看起来就是"画布四周一圈浅灰线"。
        qp.fillRect(self.rect(), QColor("#05080f"))
        qp.drawImage(0, 0, img)
        if not self.reduce_motion and BLOOM > 0:
            sw, sh = max(1, w // 8), max(1, h // 8)
            small = img.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            glow = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            qp.setOpacity(BLOOM)
            # 往里裁 1px：辉光是放大叠回来的，边缘会被插值补亮，
            # 那 1px 亮边就是评审 B 量到的"画布四周浅灰线"。
            qp.setClipRect(1, 1, max(1, w - 2), max(1, h - 2))
            qp.drawImage(0, 0, glow)
            qp.setClipping(False)
            qp.setOpacity(1.0)
        qp.end()

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
        # 空状态必须有一句话。之前这句话写在 TEXT 里从没上屏，用户打开只看到一片黑。
        f = QFont()
        f.setPixelSize(17)
        p.setFont(f)
        p.setPen(QPen(QColor(198, 214, 236, 210)))
        p.drawText(QRectF(c.x() - 320, c.y() + R * 0.22, 640, 26),
                   Qt.AlignCenter, TEXT["S0_title"])
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QPen(QColor(140, 160, 186, 190)))
        p.drawText(QRectF(c.x() - 320, c.y() + R * 0.22 + 28, 640, 22),
                   Qt.AlignCenter, TEXT["S0_desc"])

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
        # 星云核：三团错开的光，整体慢慢转。
        # 透明度跟着"已发现多少"走 —— 一开始要真的像什么都没有。
        fade_in = min(1.0, len(self.stars) / 160.0)
        for i, (rr, alpha, hue) in enumerate(((0.55, 62, (70, 120, 220)),
                                              (0.36, 54, (110, 90, 210)),
                                              (0.18, 66, (70, 160, 210)))):
            alpha = max(0, int(alpha * fade_in))
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
        sweep.setColorAt(0.88, QColor(120, 180, 255, int(64 * fade_in)))
        sweep.setColorAt(1.00, QColor(120, 180, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(sweep)
        p.drawEllipse(QRectF(c.x() - R, c.y() - R * self.flat, R * 2, R * 2 * self.flat))

        # 不再画那圈硬边椭圆 —— 那是一条明显的几何线，一眼就出戏。

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
        """整片底雾。银河的"云"是连续的，不跟着分组走。"""
        g = QRadialGradient(c.x(), c.y(), R * self.settle)
        g.setColorAt(0.00, QColor(150, 160, 235, 26))
        g.setColorAt(0.45, QColor(120, 110, 200, 16))
        g.setColorAt(1.00, QColor(90, 90, 160, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QRectF(c.x() - R * self.settle, c.y() - R * self.settle * self.flat,
                             R * 2 * self.settle, R * 2 * self.settle * self.flat))

    def _galaxy_cache(self):
        """把星云、旋臂、尘埃、核球烘成一张正视图（flat=1、无旋转）。

        每帧再用一个变换把它贴回来（旋转 + 压扁）。
        这四样加起来是 300 多次径向渐变，每帧现画要 15ms；烘一次之后每帧只剩一次贴图。
        """
        R = self._radius() * self.settle
        if R < 4 or not self.groups:
            return None
        pad = int(R * 1.35) + 4
        size = pad * 2
        key = (size, len(self.groups), tuple(round(g["count"], 0) for g in self.groups))
        if getattr(self, "_gcache_key", None) == key and getattr(self, "_gcache", None):
            return self._gcache

        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        pp = QPainter(img)
        pp.setRenderHint(QPainter.Antialiasing, True)
        pp.translate(pad, pad)
        fake = QPointF(0.0, 0.0)

        self._draw_nebula_c(pp, fake, R)
        self._draw_arms_c(pp, fake, R)
        self._draw_dust_c(pp, fake, R)
        self._draw_core_c(pp, fake, R)
        pp.end()
        self._gcache = img
        self._gcache_key = key
        self._gcache_pad = pad
        return img

    def _draw_nebula_c(self, p, c, R):
        g = QRadialGradient(0, 0, R)
        g.setColorAt(0.00, QColor(150, 160, 235, 26))
        g.setColorAt(0.45, QColor(120, 110, 200, 16))
        g.setColorAt(1.00, QColor(90, 90, 160, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QRectF(-R, -R, R * 2, R * 2))

    def _draw_arms_c(self, p, c, R):
        """每条臂画成一串柔和光斑，再加噪声斑点 —— 臂是丝缕状的云，不是均匀的光带。"""
        for gi, g in enumerate(self.groups):
            h = self.hi[gi] if gi < len(self.hi) else 0.0
            base = QColor(g["color"])
            if h < 0:
                base.setAlpha(int(34 * (1 + h * (1 - DIM_ALPHA))))
            else:
                base.setAlpha(int(40 + 40 * h))
            n = 48
            for i in range(n + 1):
                s = i / n
                rad_p, ang = self.arm_point(gi, s)
                for k in range(4):
                    jr = gauss01("%d-%.3f-%d" % (gi, s, k), 71) * 0.05 * (0.6 + s)
                    ja = gauss01("%d-%.3f-%d" % (gi, s, k), 83) * 0.10 * (0.6 + s)
                    rr = R * (0.055 + 0.075 * s) * (0.7 + 0.6 * hash01("%d%d" % (gi, i), k))
                    x = R * (rad_p + jr) * math.cos(ang + ja)
                    y = R * (rad_p + jr) * math.sin(ang + ja)
                    col = QColor(base)
                    col.setAlpha(max(0, int(base.alpha() * (1.25 - 0.6 * s) * (0.35 + 0.5 * hash01("%d%d" % (gi, i), k + 9)))))
                    grd = QRadialGradient(x, y, rr)
                    c1 = QColor(col)
                    c2 = QColor(col)
                    c2.setAlpha(0)
                    grd.setColorAt(0.0, c1)
                    grd.setColorAt(1.0, c2)
                    p.setPen(Qt.NoPen)
                    p.setBrush(grd)
                    p.drawEllipse(QRectF(x - rr, y - rr, rr * 2, rr * 2))

            # 臂间的小暗星：让空隙不是纯黑，密起来才像真实星空
            dim = QColor(g["color"])
            dim.setAlpha(46 if h >= 0 else 18)
            pts = []
            n_d = max(8, g["count"] // 3)
            for i in range(n_d):
                s = hash01("%d-%d" % (gi, i), 91)
                rad_p, ang = self.arm_point(gi, s)
                rad_p += gauss01("%d-%d" % (gi, i), 97) * 0.16
                ang += gauss01("%d-%d" % (gi, i), 99) * 0.45
                if 0.03 < rad_p < 1.02:
                    pts.append(QPointF(R * rad_p * math.cos(ang), R * rad_p * math.sin(ang)))
            if pts:
                pen = QPen(dim)
                pen.setWidthF(1.1)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawPoints(pts)

    def _draw_dust_c(self, p, c, R):
        """尘埃带：压在每条臂的里侧，把臂"切"出来。"""
        for gi in range(len(self.groups)):
            n = 26
            for i in range(n + 1):
                s = i / n
                rad_p, ang = self.arm_point(gi, s)
                ang += 0.20
                rad_p *= 0.95
                x, y = R * rad_p * math.cos(ang), R * rad_p * math.sin(ang)
                rr = R * (0.045 + 0.06 * s)
                grd = QRadialGradient(x, y, rr)
                grd.setColorAt(0.0, QColor(5, 7, 14, 105))
                grd.setColorAt(1.0, QColor(5, 7, 14, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(grd)
                p.drawEllipse(QRectF(x - rr, y - rr, rr * 2, rr * 2))

    def _draw_core_c(self, p, c, R):
        r_core = R * CORE_R
        for mult, alpha, hue in ((2.6, 26, (150, 150, 220)),
                                 (1.5, 55, (255, 226, 186)),
                                 (0.75, 120, (255, 240, 214))):
            rad = r_core * mult
            g = QRadialGradient(0, 0, rad)
            c1 = QColor(*hue)
            c1.setAlpha(alpha)
            c2 = QColor(*hue)
            c2.setAlpha(0)
            g.setColorAt(0.0, c1)
            g.setColorAt(0.45, c1)
            g.setColorAt(1.0, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QRectF(-rad, -rad, rad * 2, rad * 2))

    def _sector_shift(self, gi):
        """悬停的那组浮起 10px，其他下沉 4px（V2.0 §5.1）；减少动效时一律不位移。"""
        if self.reduce_motion or gi < 0 or gi >= len(self.hi):
            return 0.0
        h = self.hi[gi]
        return -LIFT_HOVER * h if h > 0 else SINK_OTHER * (-h)
    def _draw_core(self, p, c, R):
        """核球：银河中心那团暖白的光。整张图的视觉重心靠它。"""
        r_core = R * CORE_R * self.settle
        if r_core <= 1:
            return
        for mult, alpha, hue in ((2.6, 26, (150, 150, 220)),
                                 (1.5, 55, (255, 226, 186)),
                                 (0.75, 120, (255, 240, 214))):
            rad = r_core * mult
            g = QRadialGradient(c.x(), c.y(), rad)
            c1 = QColor(*hue)
            c1.setAlpha(alpha)
            c2 = QColor(*hue)
            c2.setAlpha(0)
            g.setColorAt(0.0, c1)
            g.setColorAt(0.45, c1)
            g.setColorAt(1.0, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QRectF(c.x() - rad, c.y() - rad * self.flat,
                                 rad * 2, rad * 2 * self.flat))

    def _draw_arms(self, p, c, R):
        """旋臂：沿螺旋撒一串柔和的光斑，越靠外越淡。

        不用"填充扇形"——填充会把旋臂画成色块，银河的臂是光，不是面。
        """
        # 两条极淡的装饰臂（相位各偏 120°）。它们不承载数据，
        # 只负责让画面读成"多臂星系"而不是"一条彩带"。
        for phase in (2.094, 4.189):
            for i in range(70):
                tt = self.total_t * i / 70.0
                rad_p, ang = self._spiral(tt)
                ang += self.yaw + self.spin + phase
                x = c.x() + R * rad_p * self.settle * math.cos(ang)
                y = c.y() + R * rad_p * self.settle * math.sin(ang) * self.flat
                rr = R * (0.055 + 0.05 * (tt / max(1e-6, self.total_t))) * self.settle
                grd = QRadialGradient(x, y, rr)
                c1 = QColor(120, 130, 210, 11)
                c2 = QColor(120, 130, 210, 0)
                grd.setColorAt(0.0, c1)
                grd.setColorAt(1.0, c2)
                p.setPen(Qt.NoPen)
                p.setBrush(grd)
                p.drawEllipse(QRectF(x - rr, y - rr * self.flat, rr * 2, rr * 2 * self.flat))

        steps = 132
        for gi, g in enumerate(self.groups):
            a0, a1 = self.wedges[gi]
            h = self.hi[gi] if gi < len(self.hi) else 0.0
            base = QColor(g["color"])
            if h < 0:
                base.setAlpha(int(30 * (1 + h * (1 - DIM_ALPHA))))
            else:
                base.setAlpha(int(34 + 34 * h))
            n = max(2, int(steps * (a1 - a0) / max(1e-6, self.total_t)))
            for i in range(n + 1):
                t = a0 + (a1 - a0) * i / n
                frac = t / max(1e-6, self.total_t)
                rad_p, ang = self._spiral(t)
                if rad_p > 1.0:
                    continue
                ang += self.yaw + self.spin
                x = c.x() + R * rad_p * self.settle * math.cos(ang)
                y = c.y() + R * rad_p * self.settle * math.sin(ang) * self.flat
                rr = R * (0.062 + 0.10 * frac) * self.settle
                col = QColor(base)
                col.setAlpha(max(0, int(base.alpha() * (1.15 - 0.55 * frac))))
                grd = QRadialGradient(x, y, rr)
                c1 = QColor(col)
                c2 = QColor(col)
                c2.setAlpha(0)
                grd.setColorAt(0.0, c1)
                grd.setColorAt(1.0, c2)
                p.setPen(Qt.NoPen)
                p.setBrush(grd)
                p.drawEllipse(QRectF(x - rr, y - rr * self.flat, rr * 2, rr * 2 * self.flat))

    def _draw_stars(self, p, c, R):
        now = time.perf_counter()
        hit_b = [[] for _ in range(len(self.groups) or 1)]
        miss_b = [[] for _ in range(len(self.groups) or 1)]
        arcs = []

        if self.state == "scanning":
            for st in self.stars:
                p01 = (now - st["t0"]) / FLY_SECS
                if p01 < 0.0:
                    continue
                if p01 > 1.0:
                    p01 = 1.0
                k = 1.0 - (1.0 - p01) ** 3
                rad_t = st.get("prp", 0.5)
                ang_t = st.get("pang", 0.0)
                ang = st["sang"] + (ang_t - st["sang"]) * k + self.yaw + self.spin
                rad = st["srad"] + (rad_t - st["srad"]) * k
                x = c.x() + R * rad * math.cos(ang)
                y = c.y() + R * rad * math.sin(ang) * self.flat
                if 0.30 < p01 < 0.995 and hash01(st.get("path", ""), 7) < 0.22:
                    q = max(0.0, p01 - 0.10)
                    kq = 1.0 - (1.0 - q) ** 3
                    qang = st["sang"] + (ang_t - st["sang"]) * kq + self.yaw + self.spin
                    qrad = st["srad"] + (rad_t - st["srad"]) * kq
                    arcs.append((c.x() + R * qrad * math.cos(qang),
                                 c.y() + R * qrad * math.sin(qang) * self.flat, x, y,
                                 int(70 * (1.0 - p01))))
                hit_b[0].append(QPointF(x, y))
            col = QColor("#8fb8e8")
            self._blit_bucket(p, hit_b[0], col)
            for x0, y0, x1, y1, a in arcs:
                if a > 0:
                    pen = QPen(QColor(140, 195, 255, a))
                    pen.setWidthF(1.1)
                    pen.setCapStyle(Qt.RoundCap)
                    p.setPen(pen)
                    mx = (x0 + x1) / 2 + (y1 - y0) * 0.35
                    my = (y0 + y1) / 2 - (x1 - x0) * 0.35
                    path = QPainterPath(QPointF(x0, y0))
                    path.quadTo(mx, my, x1, y1)
                    p.setBrush(Qt.NoBrush)
                    p.drawPath(path)
            return

        t_all = self.settle
        e = 1.0 - (1.0 - t_all) ** 3
        for st in self.stars:
            gi = st["group"]
            fr = st.get("f_rp", st.get("prp", 0.5))
            fa = st.get("f_ang", st.get("pang", 0.0))
            if e < 1.0:
                rad_p = fr + (st.get("rp", fr) - fr) * e
                ang = fa + (st.get("ang", fa) - fa) * e
                if gi == getattr(self, "focus_gi", -1):
                    rad_p *= 1.06          # 聚焦的臂放大 6%
            else:
                rad_p, ang = st.get("rp", 0.0), st.get("ang", 0.0)
            ang += self.yaw + self.spin
            if not self.reduce_motion:
                rad_p *= 1.0 + BREATH * math.sin(self.t_anim * 1.1 + st.get("ph", 0.0))
            x = c.x() + R * rad_p * math.cos(ang)
            y = c.y() + R * rad_p * math.sin(ang) * self.flat
            if gi < len(self.hi) and self.hi[gi] != 0.0:
                y += self._sector_shift(gi) * t_all
            if self.match is not None and st.get("path") not in self.match:
                miss_b[gi].append(QPointF(x, y))
            else:
                hit_b[gi].append(QPointF(x, y))

        for gi in range(len(self.groups)):
            pts = miss_b[gi]
            if pts:
                c0 = QColor(self.groups[gi]["color"])
                c0.setAlpha(26)
                self._blit_bucket(p, pts, c0)
            pts = hit_b[gi]
            if pts:
                h = self.hi[gi] if gi < len(self.hi) else 0.0
                col = QColor(self.groups[gi]["color"])
                if h < 0:
                    col.setAlpha(int(200 * (1 + h * (1 - DIM_ALPHA))))
                else:
                    col.setAlpha(min(255, int(190 + 45 * h)))
                self._blit_bucket(p, pts, col)

    def _blit_bucket(self, p, pts, col):
        """一组星一次画完：先光晕再亮芯。"""
        if self.reduce_motion:
            pen = QPen(col)
            pen.setWidthF(STAR_R)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints(pts)
            return
        halo = QColor(col)
        halo.setAlpha(max(0, int(col.alpha() * 0.26)))
        pen = QPen(halo)
        pen.setWidthF(STAR_R * 3.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawPoints(pts)
        pen = QPen(col)
        pen.setWidthF(STAR_R * 0.92)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawPoints(pts)

    def _draw_spikes(self, p, c, R):
        if not self.stars:
            return
        step = max(1, len(self.stars) // SPIKES)
        for i in range(0, len(self.stars), step):
            st = self.stars[i]
            gi = st["group"]
            h = self.hi[gi] if gi < len(self.hi) else 0.0
            ang = st.get("ang", 0.0) + self.yaw + self.spin
            rad_p = st.get("rp", 0.0)
            x = c.x() + R * rad_p * math.cos(ang)
            y = c.y() + R * rad_p * math.sin(ang) * self.flat
            ln = (R * 0.030) * (1.0 + 0.5 * hash01(st.get("path", ""), 3))
            fade = 1.0 if h >= 0 else (1 + h * (1 - DIM_ALPHA))
            pen = QPen(QColor(200, 225, 255, int(70 * fade)))
            pen.setWidthF(0.9)
            p.setPen(pen)
            p.drawLine(QPointF(x - ln, y), QPointF(x + ln, y))
            p.drawLine(QPointF(x, y - ln * self.flat), QPointF(x, y + ln * self.flat))

    def _draw_dust(self, p, c, R):
        """尘埃带：沿旋臂内侧压一条暗色，把臂"切"出来。
        没有它，臂和臂之间是糊在一起的。"""
        n = 90
        for i in range(n):
            t = self.total_t * i / n
            rad_p, ang = self._spiral(t)
            ang += self.yaw + self.spin + 0.16      # 稍微偏到臂的里侧
            rad_p *= 0.94
            x = c.x() + R * rad_p * self.settle * math.cos(ang)
            y = c.y() + R * rad_p * self.settle * math.sin(ang) * self.flat
            rr = R * (0.035 + 0.05 * (t / max(1e-6, self.total_t))) * self.settle
            grd = QRadialGradient(x, y, rr)
            grd.setColorAt(0.0, QColor(6, 8, 16, 90))
            grd.setColorAt(1.0, QColor(6, 8, 16, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(grd)
            p.drawEllipse(QRectF(x - rr, y - rr * self.flat, rr * 2, rr * 2 * self.flat))

    def _draw_labels(self, p, c, R):
        if not self.groups:
            return
        f = QFont()
        f.setPixelSize(12)
        p.setFont(f)
        for gi, g in enumerate(self.groups):
            h = self.hi[gi] if gi < len(self.hi) else 0.0
            rad_p, ang = self.arm_point(gi, 1.0)
            ang += self.yaw + self.spin
            dy = self._sector_shift(gi)
            # 短的臂梢都在靠中心的位置，标签会挤成一坨。
            # 所以不管臂多长，标签都推到盘外一圈，围着星系排开。
            rr = max(rad_p * 1.06, 0.94)
            x = c.x() + R * rr * math.cos(ang)
            y = c.y() + R * rr * math.sin(ang) * self.flat + dy
            name = os.path.basename(g["key"]) or g["key"]
            if len(name) > 9:
                name = name[:8] + "…"
            col = QColor(g["color"])
            col.setAlpha(int(235 if h >= 0 else 110))
            p.setPen(QPen(col))
            p.drawText(QRectF(x - 58, y - 12, 116, 14), Qt.AlignCenter, name)
            p.setPen(QPen(QColor(159, 176, 200, int(170 if h >= 0 else 80))))
            p.drawText(QRectF(x - 58, y + 2, 116, 14), Qt.AlignCenter, "%d 个" % g["count"])

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        win = self.window()
        if hasattr(win, "layout_results"):
            win.layout_results()

    def wheelEvent(self, ev):
        step = 1.08 if ev.angleDelta().y() > 0 else (1 / 1.08)
        self.zoom = min(1.6, max(0.65, self.zoom * step))
        self.update()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._hit(ev.position()) < 0:
            self.zoom = 1.0
            self.yaw = 0.0
            self.flat = FLAT_END
            self.update()
    def focus_group(self, gi):
        """把相机转到这条臂的中角。选中一条臂=我要看这个方向，
        相机不动，用户就得自己在脑子里把那条臂转到正面——那一步是白费的。"""
        if gi is None or gi < 0 or gi >= len(self.groups):
            self.yaw_target = 0.0
            self.focus_gi = -1
            return
        span = self.arm_span(gi)
        mid = self.arm_phase(gi) + TWIST * 0.32 * span
        self.yaw_target = -math.pi / 2 - mid
        self.focus_gi = gi
    def _hit(self, pos):
        if not self.groups:
            return -1
        c, R = self._center(), self._radius()
        dx = pos.x() - c.x()
        dy = (pos.y() - c.y()) / max(0.01, self.flat)
        dist = math.hypot(dx, dy)
        if dist > R * 1.20:      # 标签画在 1.06R 外，上限 1.05 会让点标签打空
            return -1
        r = dist / max(1e-6, R)
        got = math.atan2(dy, dx) - self.yaw - self.spin

        best, best_d = -1, 1e9
        for gi in range(len(self.groups)):
            span = max(0.01, self.arm_span(gi))
            # 半径 -> 该臂上的 s
            frac = ((r - 0.10) / 0.90) ** (1.0 / 1.15)
            s = min(1.0, max(0.0, frac / span))
            _, expect = self.arm_point(gi, s)
            d = abs((got - expect + math.pi) % math.tau - math.pi)
            tol = ARM_ANGLE_SPREAD * (0.8 + 1.2 * s) + 0.06
            if d < tol and d < best_d:
                best, best_d = gi, d
        return best

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
            span = self.arm_span(self.sel) if self.sel >= 0 else 1.0
            mid = self.arm_phase(self.sel) + TWIST * 0.32 * span if self.sel >= 0 else 0.0
            self.yaw_target = (-math.pi / 2 - mid) if self.sel >= 0 else 0.0
            self.focus_gi = self.sel
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
            self.focus_gi = -1
            self.yaw_target = 0.0
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

class GlowButton(QPushButton):
    """自己画的按钮。

    为什么不用样式表：Qt 的 QSS 没有 transition，:hover 只能硬切，
    这就是"按钮没有动效"的原因。自己画一个 0..1 的悬停量，才有过渡。
    """

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._idle_text = text
        self.progress = None        # None=普通按钮；0..1=进度；-1=不确定
        self._hover = False
        self._down = False
        self._h = 0.0
        self._p = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)
        self.setMinimumWidth(112)
        self.setStyleSheet("background:transparent;border:none;")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._anim)
        self._timer.start(16)

    def enterEvent(self, ev):
        self._hover = True
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        self._down = True
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._down = False
        super().mouseReleaseEvent(ev)

    def _anim(self):
        th = 1.0 if self._hover else 0.0
        tp = 1.0 if self._down else 0.0
        moved = False
        if abs(self._h - th) > 0.005:
            self._h += (th - self._h) * 0.22
            moved = True
        else:
            self._h = th
        if abs(self._p - tp) > 0.005:
            self._p += (tp - self._p) * 0.35
            moved = True
        else:
            self._p = tp
        if moved:
            self.update()

    def set_progress(self, p, text=None):
        """把按钮变成进度条形状（container transform：同一个矩形变形，不是换一个控件）。"""
        self.progress = p
        if text is not None:
            self.setText(text)
        self.update()

    def reset_button(self):
        self.progress = None
        self.setText(self._idle_text)
        self.update()

    def _mix(self, a, b, k):
        return QColor(int(a.red() + (b.red() - a.red()) * k),
                      int(a.green() + (b.green() - a.green()) * k),
                      int(a.blue() + (b.blue() - a.blue()) * k),
                      int(a.alpha() + (b.alpha() - a.alpha()) * k))

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        lift = 1.0 * self._p

        if self._h > 0.01:                     # 悬停光晕
            glow = QColor(91, 156, 246, int(46 * self._h))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(r.adjusted(-2 + lift, -2 + lift, 2 - lift, 2 - lift), 9, 9)

        bg = self._mix(QColor(24, 34, 54), QColor(34, 48, 78), self._h)
        bg = self._mix(bg, QColor(18, 26, 41), self._p)
        border = self._mix(QColor(43, 60, 88), QColor(66, 100, 148), self._h)
        p.setBrush(bg)
        pen = QPen(border)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawRoundedRect(r.adjusted(lift, lift, -lift, -lift), 7, 7)

        if self.progress is not None:
            # 变形后的样子：底部一条进度轨，文字变小靠左
            track = QRectF(r.left() + 12, r.bottom() - 7, r.width() - 24, 3)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(40, 56, 82, 200))
            p.drawRoundedRect(track, 2, 2)
            if self.progress >= 0:
                fill = QRectF(track.left(), track.top(),
                              track.width() * min(1.0, self.progress), track.height())
                p.setBrush(QColor(58, 122, 220))
                p.drawRoundedRect(fill, 2, 2)
            else:
                p.setBrush(QColor(58, 122, 220, 120))
                p.drawRoundedRect(track, 2, 2)

        col = self._mix(QColor(207, 224, 255), QColor(235, 245, 255), self._h)
        if not self.isEnabled():
            col = QColor(84, 99, 122)
        p.setPen(col)
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        txt_rect = self.rect()
        if self.progress is not None:
            txt_rect = QRectF(r.left(), r.top() - 2, r.width(), r.height() - 5)
        p.drawText(txt_rect, Qt.AlignCenter, self.text())
        p.end()


class Sidebar(QFrame):
    """左侧导航。先只做「扫描」是真能用的，其余按钮点了给出说明。"""

    NAV = [("扫描", "◎"), ("软件库", "▤"), ("历史记录", "◷"),
           ("分类管理", "◈"), ("插件中心", "▧"), ("设置", "⚙")]

    def __init__(self, on_pick, parent=None):
        super().__init__(parent)
        self.setFixedWidth(196)
        self.setStyleSheet("QFrame{background:#080d17;border:none;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 20, 16, 16)
        v.setSpacing(4)

        logo = QLabel("◍  DiskProbe")
        logo.setStyleSheet("font-size:17px;font-weight:600;color:#eaf2ff;"
                           "padding-bottom:18px;")
        v.addWidget(logo)

        self.buttons = []
        for name, glyph in self.NAV:
            b = QPushButton("%s   %s" % (glyph, name))
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(38)
            b.setCheckable(True)
            b.setStyleSheet(
                "QPushButton{text-align:left;padding-left:14px;border:none;"
                "border-radius:8px;color:#8ea2bd;font-size:13px;background:transparent;}"
                "QPushButton:hover{background:#0f1725;color:#cfe0ff;}"
                "QPushButton:checked{background:#132038;color:#eaf2ff;}")
            b.clicked.connect(lambda _=False, n=name: on_pick(n))
            v.addWidget(b)
            self.buttons.append(b)
        self.buttons[0].setChecked(True)

        v.addStretch(1)
        tip = QLabel("探索你的数字宇宙")
        tip.setStyleSheet("font-size:11px;color:#6d7f97;")
        v.addWidget(tip)
        ver = QLabel("Explore Your Digital Universe")
        ver.setStyleSheet("font-size:10px;color:#6a7d95;")
        v.addWidget(ver)


class StatCard(QFrame):
    """顶部那张小数据卡：图标 + 标签 + 数值。

    数字不跳变，是滚过去的——跳变会让眼睛重新对位，滚动让注意力跟着数字走。
    """

    def __init__(self, glyph, label, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame{background:#0a1120;border:1px solid #26354f;"
                           "border-radius:10px;}")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 16, 10)
        h.setSpacing(10)
        ic = QLabel(glyph)
        ic.setStyleSheet("font-size:16px;color:#4f7fd0;")
        h.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(1)
        lab = QLabel(label)
        lab.setStyleSheet("font-size:10px;color:#8296ae;")
        self.value = QLabel("-")
        self.value.setStyleSheet("font-size:18px;font-weight:600;color:#eaf2ff;")
        col.addWidget(lab)
        col.addWidget(self.value)
        h.addLayout(col)

    def set(self, text):
        text = str(text)
        if not hasattr(self, "_shown"):
            self._shown = 0.0
            self._target = 0.0
            self._suffix = ""
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(16)
        if text.endswith(" GB"):
            self._target = float(text[:-3] or 0)
            self._suffix = " GB"
            self._dec = 1
        elif text.replace(",", "").isdigit():
            self._target = float(text.replace(",", ""))
            self._suffix = ""
            self._dec = 0
        else:
            self._timer.stop() if hasattr(self, "_timer") else None
            self.value.setText(text)
            self._shown = -1
            return
        if getattr(self, "_dec", 0) == 0:
            self._shown = float(int(self._shown)) if self._shown >= 0 else 0.0

    def _tick(self):
        if getattr(self, "_shown", -1) < 0:
            return
        self._shown = approach(self._shown, self._target, 0.016, MS_SLOW)
        if abs(self._shown - self._target) < 0.05:
            self._shown = float(self._target)
        if getattr(self, "_dec", 0):
            self.value.setText("%.*f%s" % (self._dec, self._shown, self._suffix))
        else:
            self.value.setText("{:,}".format(int(self._shown)) + self._suffix)


class ResultsPanel(QFrame):
    """结果浮层。挂在星图上，不占布局——搜索时星图不变小，位置记忆不失效。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("rp")
        self.setStyleSheet(
            "QFrame#rp{background:rgba(9,15,26,238);border:1px solid #1d2b42;"
            "border-radius:10px;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 9, 12, 10)
        v.setSpacing(6)

        head = QHBoxLayout()
        self.title = QLabel("")
        self.title.setStyleSheet("font-size:11px;color:#9fb0c8;")
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#7f93ae;font-size:12px;}"
            "QPushButton:hover{color:#eaf2ff;}")
        head.addWidget(self.title, 1)
        head.addWidget(self.close_btn, 0)
        v.addLayout(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["文件", "目录", "大小", "修改时间"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setStyleSheet(
            "QTableWidget{background:transparent;border:none;color:#c6d3e8;"
            "font-size:11px;gridline-color:#22304a;}"
            "QHeaderView::section{background:#0d1626;color:#7f90a8;border:none;"
            "padding:4px;font-size:10px;}"
            "QTableWidget::item:selected{background:#1b2b45;}")
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        v.addWidget(self.table)
        self.hide()

    def show_rows(self, title, files, cap=300):
        rows = sorted(files, key=lambda r: r["path"].lower())[:cap]
        self.title.setText(title + ("" if len(files) <= cap
                                    else "  （显示前 %d 条）" % cap))
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            path = r["path"]
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(path)))
            d = os.path.dirname(path)
            parts = d.split("\\")
            short = "\\".join(parts[-2:]) if len(parts) > 2 else d
            it = QTableWidgetItem(short)
            it.setToolTip(d)
            self.table.setItem(i, 1, it)
            mb = (r.get("size") or 0) / 1048576.0
            s = QTableWidgetItem("%.1f MB" % mb if mb >= 1
                                 else "%.0f KB" % (mb * 1024))
            s.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 2, s)
            t = r.get("mtime") or 0
            self.table.setItem(i, 3, QTableWidgetItem(
                time.strftime("%Y-%m-%d", time.localtime(t)) if t else "-"))
        self.show()
        self.raise_()
        if self.parentWidget() is not None:
            g = self.geometry()
            from PySide6.QtCore import QPropertyAnimation
            anim = QPropertyAnimation(self, b"geometry", self)
            anim.setDuration(260)
            anim.setStartValue(g.adjusted(0, 16, 0, 16))
            anim.setEndValue(g)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
            self._rise = anim


class LegendRow(QWidget):
    """图例的一行。可点：点谁就选中谁。之前是纯 QLabel，看着能点其实点不动。"""

    def __init__(self, name, full, count, pct, color, on_click, parent=None):
        super().__init__(parent)
        self._cb = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(20)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(7)
        bar = QLabel()
        bar.setFixedSize(3, 12)
        bar.setStyleSheet("background:%s;border-radius:1px;" % color)
        lab = QLabel(name)
        lab.setStyleSheet("font-size:11px;color:#a9bad0;")
        pct_l = QLabel("%.1f%%" % pct)
        pct_l.setStyleSheet("font-size:10px;color:#8496ad;")
        h.addWidget(bar, 0)
        h.addWidget(lab, 1)
        h.addWidget(pct_l, 0)
        self.setToolTip("%s\n%d 个 EXE · %.1f%%" % (full, count, pct))
        self.setStyleSheet("LegendRow:hover{background:#101a2b;border-radius:4px;}")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._cb:
            self._cb()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DiskProbe · 软件星团")
        self.resize(1340, 880)
        self.setStyleSheet(
            "MainWindow{background:#05080f;color:#e8ecf4;"
            "font-family:'Microsoft YaHei UI','Segoe UI';}")
        self.setAutoFillBackground(True)
        self.worker = None
        self.root = None
        self.t0 = None
        self._dirset = set()
        self._total_size = 0

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = Sidebar(self.on_nav)
        outer.addWidget(self.sidebar)

        body = QWidget()
        main = QVBoxLayout(body)
        main.setContentsMargins(22, 18, 22, 16)
        main.setSpacing(12)
        outer.addWidget(body, 1)

        # ---------------- 顶部：标题 + 面包屑 + 三张数据卡
        head = QHBoxLayout()
        head.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.title = QLabel("扫描")
        self.title.setStyleSheet("font-size:22px;font-weight:600;color:#eaf2ff;")
        self.crumb = QLabel("还没有选择目录")
        self.crumb.setStyleSheet("font-size:11px;color:#8296ae;")
        left.addWidget(self.title)
        left.addWidget(self.crumb)
        head.addLayout(left, 1)

        self.card_exe = StatCard("▤", "EXE 总数")
        self.card_size = StatCard("◫", "总大小")
        self.card_time = StatCard("◷", "用时")
        for c in (self.card_exe, self.card_size, self.card_time):
            head.addWidget(c, 0)
        main.addLayout(head)

        # ---------------- 扫描进度卡
        self.prog_card = QFrame()
        self.prog_card.setStyleSheet(
            "QFrame{background:#0a1120;border:1px solid #26354f;border-radius:10px;}")
        pc = QVBoxLayout(self.prog_card)
        pc.setContentsMargins(16, 10, 16, 10)
        pc.setSpacing(6)
        row = QHBoxLayout()
        self.prog_left = QLabel("准备扫描…")
        self.prog_left.setStyleSheet("font-size:12px;color:#9fb0c8;")
        self.prog_right = QLabel("")
        self.prog_right.setStyleSheet("font-size:12px;color:#7f93ae;")
        row.addWidget(self.prog_left, 1)
        row.addWidget(self.prog_right, 0)
        pc.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setStyleSheet(
            "QProgressBar{background:#111c2e;border:none;border-radius:2px;}"
            "QProgressBar::chunk{background:#2f7ae0;border-radius:2px;}")
        pc.addWidget(self.bar)
        self.prog_card.setVisible(False)
        main.addWidget(self.prog_card)

        # ---------------- 中间：图例 + 星系 + 右侧详情
        mid = QHBoxLayout()
        mid.setSpacing(12)

        leg = QFrame()
        leg.setFixedWidth(152)
        leg.setStyleSheet("QFrame{background:transparent;border:none;}")
        lv = QVBoxLayout(leg)
        lv.setContentsMargins(4, 6, 4, 6)
        lv.setSpacing(6)
        self.legend = QVBoxLayout()
        self.legend.setSpacing(5)
        lv.addLayout(self.legend)
        lv.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文件名…")
        self.search.setStyleSheet(
            "QLineEdit{background:#0d1524;border:1px solid #2c3d59;border-radius:7px;"
            "padding:6px 9px;color:#cfe0ff;font-size:11px;}"
            "QLineEdit:focus{border-color:#3d6ea8;}")
        self.search.textChanged.connect(self.on_search)
        lv.addWidget(self.search)
        mid.addWidget(leg, 0)

        self.canvas = StarCanvas()
        self.results = ResultsPanel(self.canvas)
        self.results.close_btn.clicked.connect(self.close_results)
        mid.addWidget(self.canvas, 1)

        # 右侧详情
        self.panel = QFrame()
        self.panel.setFixedWidth(300)
        self.panel.setStyleSheet(
            "QFrame#p{background:#0a1120;border:1px solid #26354f;border-radius:12px;}")
        self.panel.setObjectName("p")
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(8)

        self.p_name = QLabel("")
        self.p_name.setStyleSheet("font-size:17px;font-weight:600;color:#eaf2ff;")
        self.p_meta = QLabel("")
        self.p_meta.setStyleSheet("font-size:11px;color:#7f93ae;")
        self.p_meta.setWordWrap(True)
        pl.addWidget(self.p_name)
        pl.addWidget(self.p_meta)

        self.p_sub = QLabel("代表程序")
        self.p_sub.setStyleSheet("font-size:11px;color:#8296ae;padding-top:8px;")
        pl.addWidget(self.p_sub)
        self.p_list = QVBoxLayout()
        self.p_list.setSpacing(4)
        pl.addLayout(self.p_list)

        pl.addStretch(1)
        self.p_all = GlowButton("查看全部 →")
        self.p_all.setFixedHeight(30)
        self.p_all.clicked.connect(self.show_group_list)
        self.p_all.setVisible(False)
        pl.addWidget(self.p_all)

        self.p_btn = GlowButton("在资源管理器中打开")
        self.p_btn.setFixedHeight(30)
        self.p_btn.clicked.connect(self.open_in_explorer)
        self.p_btn.setVisible(False)
        pl.addWidget(self.p_btn)

        self.p_note = QLabel("把鼠标移到星系上；点一下锁定，Esc 取消")
        self.p_note.setStyleSheet("font-size:11px;color:#8296ae;")
        self.p_note.setWordWrap(True)
        pl.addWidget(self.p_note)
        mid.addWidget(self.panel, 0)

        main.addLayout(mid, 1)

        # ---------------- 底部：目录 + 开始扫描
        bottom = QFrame()
        bottom.setStyleSheet(
            "QFrame#b{background:#0a1120;border:1px solid #26354f;border-radius:12px;}")
        bottom.setObjectName("b")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(10)

        self.btn_dir = GlowButton("选择目录")
        self.btn_dir.setFixedHeight(34)
        self.btn_dir.clicked.connect(self.pick_dir)
        bl.addWidget(self.btn_dir, 0)

        self.path_label = QLabel("还没有选择目录")
        self.path_label.setStyleSheet(
            "font-size:12px;color:#8ea2bd;background:#0d1524;border:1px solid #1a2436;"
            "border-radius:7px;padding:8px 12px;")
        bl.addWidget(self.path_label, 1)

        self.btn = GlowButton(TEXT["S0_btn"])
        self.btn.setFixedHeight(34)
        self.btn.setMinimumWidth(126)
        self.btn.clicked.connect(self.on_button)
        bl.addWidget(self.btn, 0)

        self.chk = QCheckBox("节能模式")
        self.chk.setStyleSheet("QCheckBox{font-size:11px;color:#7f93ae;}")
        self.chk.stateChanged.connect(self.on_reduce_motion)
        bl.addWidget(self.chk, 0)

        main.addWidget(bottom, 0)

        # ---------------- 底部展开的列表
        self.table_box = QFrame()
        self.table_box.setStyleSheet(
            "QFrame{background:#0a1120;border:1px solid #26354f;border-radius:12px;}")
        tl = QVBoxLayout(self.table_box)
        tl.setContentsMargins(12, 8, 12, 10)
        self.table_title = QLabel("")
        self.table_title.setStyleSheet("font-size:11px;color:#9fb0c8;")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件", "大小", "修改时间"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMaximumHeight(190)
        self.table.setStyleSheet(
            "QTableWidget{background:transparent;border:none;color:#c6d3e8;"
            "font-size:11px;gridline-color:#151d2c;}"
            "QHeaderView::section{background:#0e1626;color:#7f90a8;border:none;"
            "padding:4px;font-size:10px;}"
            "QTableWidget::item:selected{background:#1b2b45;}")
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        tl.addWidget(self.table_title)
        tl.addWidget(self.table)
        self.table_box.setVisible(False)
        main.addWidget(self.table_box, 0)

        self.foot = QLabel(TEXT["scale_note"])
        self.foot.setStyleSheet("font-size:10px;color:#7c8ba3;")   # 原来 #3f4e64 对比度 2.37:1，不达标
        main.addWidget(self.foot)

        # ---------------- 定时器
        self._panel_idx = None
        self._prod_cache = {}
        self.panel_timer = QTimer(self)
        self.panel_timer.timeout.connect(self.refresh_panel)
        self.panel_timer.start(120)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(250)

        self._fps_t = time.perf_counter()
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._tick_fps)
        self._fps_timer.start(500)

    # ---------------------------------------------------------- 通用

    def on_nav(self, name):
        self.title.setText(name)
        if name != "扫描":
            self.set_status("「%s」还没做" % name, "现在只有「扫描」是能用的")
        else:
            self.set_status(self.status_hint, self.status_sub)

    def set_status(self, line, sub=""):
        self.status_hint = line
        self.status_sub = sub
        self.crumb.setText(line if not sub else "%s · %s" % (line, sub))

    status_hint = "还没有选择目录"
    status_sub = ""

    def _tick_clock(self):
        if self.t0 and self.worker is not None and self.worker.isRunning():
            el = time.time() - self.t0
            self.card_time.set("%02d:%02d:%02d" % (el // 3600, (el % 3600) // 60, el % 60))

    def _tick_fps(self):
        n = getattr(self.canvas, "frames", 0)
        now = time.perf_counter()
        dt = now - self._fps_t
        self._fps_t = now
        self.canvas.frames = 0

    # ---------------------------------------------------------- 交互

    def on_reduce_motion(self):
        on = self.chk.isChecked()
        self.canvas.reduce_motion = on
        if on:
            for i in range(len(self.canvas.hi)):
                self.canvas.hi[i] = 0.0
            self.canvas.settle = 1.0
            self.canvas.update()

    def pick_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择要扫描的目录", "D:\\")
        if folder:
            self.path_label.setText(folder)
            self.root = folder
            self.set_status("已选择目录", folder)

    def on_button(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.btn.setEnabled(False)
            self.set_status("正在取消…", "已发现 %d 个 EXE" % len(self.canvas.files))
            return
        folder = self.root
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "选择要扫描的目录", "D:\\")
            if not folder:
                return
            self.root = folder
            self.path_label.setText(folder)
        self.start_scan(folder)

    def start_scan(self, folder):
        self.root = folder
        self.path_label.setText(folder)
        self.t0 = time.time()
        self._dirset = set()
        self._total_size = 0
        self.card_exe.set("0")
        self.card_size.set("0 GB")
        self.card_time.set("00:00:00")
        self.canvas.start_scan()
        self.rebuild_legend()                 # 清掉上一轮的百分比，否则同一屏两套数
        self.table_box.setVisible(False)      # 上一轮的表格也不能留着
        self._panel_idx = None
        self.p_name.setText("")
        self.p_meta.setText("扫描中…")
        self.btn.setEnabled(True)
        self.btn.set_progress(-1, "扫描中 0")     # 按钮就地变成进度条
        self.prog_card.setVisible(True)
        self.prog_left.setText("正在扫描：%s" % folder)
        self.prog_right.setText("已发现 0 个 EXE")
        self.set_status("扫描中", folder)

        self.worker = ScanWorker(folder)
        self.worker.found.connect(self.on_batch)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_batch(self, batch):
        self.canvas.add_batch(batch)
        n = len(self.canvas.files)
        for rec in batch:
            self._dirset.add(os.path.dirname(rec["path"]))
            self._total_size += rec.get("size") or 0
        self.card_exe.set("{:,}".format(n))
        self.card_size.set("%.1f GB" % (self._total_size / 1073741824))
        self.prog_right.setText("已发现 {:,} 个 EXE".format(n))
        self.btn.set_progress(-1, "扫描中 %d" % n)
        tail = batch[-1]["path"]
        parts = tail.split("\\")
        short = "\\".join(parts[-3:]) if len(parts) > 3 else tail
        self.prog_left.setText("正在扫描：…\\%s" % short)

    def on_done(self, result):
        self.btn.reset_button()
        self.btn.setEnabled(True)
        self.prog_card.setVisible(False)
        self.canvas.set_result(result)
        st = self.canvas.state
        n = len(self.canvas.files)
        g = getattr(self.canvas, "total_groups", len(self.canvas.groups))
        # 兜底：这两个数不能只依赖 on_batch 累计。
        # 目录小、或者一次性返回时，on_batch 可能没被充分调用，卡片就会显示 0。
        total = sum(r.get("size") or 0 for r in self.canvas.files)
        self.card_exe.set("{:,}".format(n))
        self.card_size.set("%.1f GB" % (total / 1073741824))
        el = None
        if self.t0:
            el = time.time() - self.t0
        elif result.get("started_at") and result.get("finished_at"):
            el = result["finished_at"] - result["started_at"]
        if el is not None:
            self.card_time.set("%02d:%02d:%02d" % (el // 3600, (el % 3600) // 60, el % 60))
        if self.root:
            self.path_label.setText(self.root)
        self.rebuild_legend()
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
        self.prog_card.setVisible(False)
        self.canvas.state = "failed"
        self.canvas.error_text = msg
        self.canvas.update()
        self.set_status(TEXT["failed"], msg)

    # ---------------------------------------------------------- 图例

    def rebuild_legend(self):
        while self.legend.count():
            item = self.legend.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self.canvas.groups:
            return
        total = max(1, len(self.canvas.files))
        for gi, g in enumerate(self.canvas.groups):
            full = g["key"]
            name = os.path.basename(full) or full
            if len(name) > 12:
                name = name[:11] + "…"
            row = LegendRow(name, full, g["count"],
                            100.0 * g["count"] / total,
                            g["color"].name(),
                            lambda i=gi: self.pick_group(i))
            self.legend.addWidget(row)

    def focus_group(self, gi):
        """把相机转到这条臂的中角，并标记聚焦。"""
        if gi < 0 or gi >= len(self.groups):
            self.yaw_target = 0.0
            self.focus_gi = -1
            return
        span = self.arm_span(gi)
        mid = self.arm_phase(gi) + TWIST * 0.32 * span
        self.yaw_target = -math.pi / 2 - mid
        self.focus_gi = gi

    def pick_group(self, gi):
        self.canvas.sel = -1 if self.canvas.sel == gi else gi
        self.canvas.focus_group(self.canvas.sel)
        self._panel_idx = None
        self.refresh_panel()
        self.fade_panel_in()
        self.canvas.update()

    def on_search(self, text):
        text = (text or "").strip()
        self.canvas.set_filter(text)
        if not text:
            self.close_results()
            return
        hits = [r for r in self.canvas.files if text.lower() in r["path"].lower()]
        self.show_results(hits, "搜索「%s」· 命中 %d 个" % (text, len(hits)))

    def show_results(self, files, title):
        self.results.show_rows(title, files)
        self.layout_results()

    def close_results(self):
        self.results.hide()

    def layout_results(self):
        """浮层贴在星图左下角，跟着画布大小走。"""
        if not self.results.isVisible():
            return
        cw, ch = self.canvas.width(), self.canvas.height()
        w = max(420, int(cw * 0.72))
        h = min(330, int(ch * 0.62))
        self.results.setGeometry(14, ch - h - 14, w, h)

    def show_group_list(self):
        idx, g = self.canvas.current_group()
        if not g:
            return
        self.show_results(g["files"], "%s · %d 个 EXE" % (g["key"], g["count"]))

    def fill_table(self, files, title, cap=400):
        """旧版底部表格，现在只在极端情况下兜底；搜索结果一律走浮层。"""
        self.show_results(files, title)

    def open_in_explorer(self):
        idx, g = self.canvas.current_group()
        if not g:
            return
        try:
            os.startfile(g["key"])
        except OSError:
            pass

    # ---------------------------------------------------------- 右侧详情

    def _product_of(self, path):
        """读 EXE 自己的 ProductName / CompanyName。结果缓存，别重复读盘。"""
        if path in self._prod_cache:
            return self._prod_cache[path]
        try:
            company, product, _desc = classify.read_version(path)
        except Exception:                      # noqa: BLE001
            company, product = "", ""
        name = product or os.path.splitext(os.path.basename(path))[0]
        out = (name.strip(), company.strip())
        self._prod_cache[path] = out
        return out

    def fade_panel_in(self):
        """右侧面板入场：淡入 + 从右滑 12px。"""
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        from PySide6.QtCore import QPropertyAnimation
        eff = QGraphicsOpacityEffect(self.panel)
        self.panel.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(MS_BASE)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self.panel.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._panel_anim = anim

    def refresh_panel(self):
        idx, g = self.canvas.current_group()
        if idx == self._panel_idx and idx >= 0:
            return
        self._panel_idx = idx
        while self.p_list.count():
            item = self.p_list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not g:
            self.p_name.setText("")
            self.p_meta.setText("")
            self.p_note.setVisible(True)
            self.p_btn.setVisible(False)
            self.p_all.setVisible(False)
            self.p_sub.setVisible(False)
            return
        self.p_note.setVisible(False)
        self.p_btn.setVisible(True)
        self.p_all.setVisible(True)
        self.p_all.setText("查看全部 %d 个 →" % g["count"])
        self.p_sub.setVisible(True)

        name = os.path.basename(g["key"]) or g["key"]
        pct = 100.0 * g["count"] / max(1, len(self.canvas.files))
        self.p_name.setText(name)
        self.p_meta.setText("%d 个 EXE · 占 %.1f%% · %.1f MB\n%s" % (
            g["count"], pct, g["size"] / 1048576, g["key"]))

        # 代表程序：按 EXE 自己的产品名聚合（最多读 60 个，避免卡）
        agg = {}
        for rec in g["files"][:60]:
            prod, company = self._product_of(rec["path"])
            key = (prod, company)
            agg[key] = agg.get(key, 0) + 1
        rows = sorted(agg.items(), key=lambda kv: -kv[1])[:5]
        for (prod, company), n in rows:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 2, 0, 2)
            h.setSpacing(8)
            nm = QLabel(prod[:18])
            nm.setStyleSheet("font-size:12px;color:#cfe0ff;")
            cnt = QLabel("%d 个" % n)
            cnt.setStyleSheet("font-size:11px;color:#8296ae;")
            h.addWidget(nm, 1)
            h.addWidget(cnt, 0)
            self.p_list.addWidget(row)



def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
