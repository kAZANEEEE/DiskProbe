# -*- coding: utf-8 -*-
"""DiskProbe · 粒子盘面原型（一次性验证用，不是产品代码）

只回答一个问题：**"空盘 → 粒子显现 → 分组聚合 → 交互探索"这个手感成不成立。**

它不接 scanner.py，不接数据库，数据写死。
比例取自 2026-10-29 对 D 盘的真实扫描：
    <1MB      591 个    155 MB
    1-10MB    301 个    984 MB
    10-100MB   71 个   2259 MB
    >100MB     47 个  11713 MB
    合计 1010 个 / 15110 MB

操作：
    空格      重放
    F         快进到"聚合完成"
    Tab       切换三种口径组合
    拖拽      旋转（松手有惯性）
    滚轮      缩放盘面
    双击      复位（旋转 + 缩放 + 选中）
    点击      选中扇区（再点空白取消）
    Esc       关闭

三种组合：
    1 扇区按大小 · 粒子＝文件数
    2 扇区按数量 · 粒子＝文件数
    3 扇区按大小 · 粒子按面积
"""
import math
import random
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
                              QLinearGradient, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

# ---------------------------------------------------------------- 假数据

# (名字, 文件数, 总大小MB, 颜色)
BUCKETS = [
    ("<1MB",     591,   155.3, QColor("#3f5d80")),
    ("1-10MB",   301,   984.2, QColor("#4e9cf5")),
    ("10-100MB",  71,  2258.7, QColor("#d97757")),
    (">100MB",    47, 11712.7, QColor("#f2c14e")),
]
TOTAL_N = sum(b[1] for b in BUCKETS)
TOTAL_MB = sum(b[2] for b in BUCKETS)

PROBE_SECS = 12.2
SETTLE_SECS = 2.2          # 分两段：先收拢成平面饼，再整体倾斜成 3D
CONVERGE_PART = 0.55       # 前 55% 只收拢（flat 保持 1.0），后 45% 才转立体
TAU = math.pi * 2
WEDGE_GAP = 0.016
FLAT_TOP = 1.0             # 聚合开始时：正面看（正圆）
FLAT_END = 0.46            # 聚合结束时：倾斜俯视（扁盘）
DEPTH_END = 26             # 盘的最终厚度
STAGGER = 0.32             # 粒子开始落位的错峰比例

MODES = [
    ("size",  "file", "1 扇区按大小 · 粒子＝文件数"),
    ("count", "file", "2 扇区按数量 · 粒子＝文件数"),
    ("size",  "area", "3 扇区按大小 · 粒子按面积"),
]

BG = QColor("#0d1015")
FG = QColor("#e8eaed")
DIM = QColor(232, 234, 237, 95)


def ease_out(x):
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    return 4 * x * x * x if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def back_out(x):
    """末尾轻微过冲再回位——"落定"的手感靠它。"""
    c1 = 1.18
    c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def approach(cur, target, dt, speed=14.0):
    """指数逼近：cur 每帧朝 target 走一截。与帧率无关——
    写死 0.1 这种系数会在 30fps 和 144fps 下跑出两种手感。"""
    return cur + (target - cur) * (1.0 - math.exp(-speed * dt))


def spring(x):
    """欠阻尼弹簧阶跃响应：0 -> 1，带轻微过冲后回稳。
    时间曲线是"排好的"，弹簧是"有质量的"——僵硬感的根子在这里。"""
    if x >= 1.0:
        return 1.0
    if x <= 0.0:
        return 0.0
    w, z = 9.0, 0.62
    wd = w * math.sqrt(1 - z * z)
    return 1 - math.exp(-z * w * x) * (math.cos(wd * x) + (z * w / wd) * math.sin(wd * x))


class Particle:
    __slots__ = ("bucket", "spawn", "ea", "er", "ha", "hr", "jit")

    def __init__(self, bucket, spawn, ea, er, ha, hr, jit):
        self.bucket = bucket
        self.spawn = spawn
        self.ea = ea
        self.er = er
        self.ha = ha
        self.hr = hr
        self.jit = jit


class Canvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DiskProbe · 粒子盘面原型")
        self.resize(1280, 820)
        self.setMouseTracking(True)

        self.mode_idx = 0
        self.rot = 0.0
        self.vel = 0.0               # 旋转惯性
        self.scale = 1.0             # 滚轮缩放
        self.sel = -1
        self.hover = -1
        self.press_t = 0.0           # 按下反馈的剩余时间比例
        self.press_bucket = -1
        self.dragging = False
        self.drag_prev = 0.0
        self.moved = 0.0
        self.t_anim = 0.0
        self.cur_flat = FLAT_END
        self.cur_depth = DEPTH_END
        self.spin = 0.0              # 星盘装饰层的慢速自转（与交互旋转分离）

        rnd0 = random.Random(7788)
        self.stars = []
        for _ in range(300):
            x = rnd0.uniform(0, 1) * self.width()
            y = rnd0.uniform(0, 1) * self.height()
            wdt = rnd0.choice([1.0, 1.0, 1.0, 1.6, 2.4])
            alp = rnd0.choice([40, 70, 70, 110, 150])
            spd = rnd0.uniform(0.3, 1.1)
            ph = rnd0.uniform(0, TAU)
            # (x, y, 线宽, 亮度, 闪速, 相位)
            self.stars.append((x, y, wdt, alp, spd, ph))
        self.twinklers = [s for s in self.stars if s[3] >= 110][:40]
        self.tilt = FLAT_END         # 用户可拖的倾角
        self.scale_t = 1.0           # 缩放的目标值（滚轮改它，scale 每帧追）
        self.tilt_cur = FLAT_END     # 倾角的当前值（tilt 是目标）
        self.hi = [0.0, 0.0, 0.0, 0.0]   # 每组的高亮量 0..1（悬停/选中都靠它）
        self.ray_a = 1.0             # 扫描射线的透明度（结尾要淡出，不能瞬间没）
        self.fade = 1.0              # 整场淡入量：阶段切换时归零再爬升
        self._space_pm = None        # 静态宇宙背景的缓存
        self._space_size = None
        self.tilt_drag = False
        self.tilt_prev = 0.0

        self._rebuild()
        self._reset()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._last = time.perf_counter()

    # ---------------------------------------------------------- 模式

    def _mode(self):
        return MODES[self.mode_idx]

    @property
    def measure(self):
        return self._mode()[0]

    @property
    def spread(self):
        return self._mode()[1]

    # ---------------------------------------------------------- 数据准备

    def _ratios(self):
        if self.measure == "size":
            return [b[2] / TOTAL_MB for b in BUCKETS]
        return [b[1] / TOTAL_N for b in BUCKETS]

    def _layout_wedges(self):
        ratios = self._ratios()
        self.wedges = []
        acc = -math.pi / 2
        for r in ratios:
            span = TAU * r
            self.wedges.append((acc + WEDGE_GAP / 2, acc + span - WEDGE_GAP / 2))
            acc += span

    def _particle_counts(self):
        if self.spread == "file":
            return [b[1] for b in BUCKETS]
        tot = sum(self._ratios())
        return [max(1, int(round(TOTAL_N * r / tot))) for r in self._ratios()]

    def _rebuild(self):
        self._layout_wedges()
        rnd = random.Random(20261029)
        counts = self._particle_counts()
        total = sum(counts)
        self.parts = []
        k = 0
        for bi, n in enumerate(counts):
            a0, a1 = self.wedges[bi]
            for _ in range(n):
                ha = a0 + (a1 - a0) * rnd.random()
                # 出现时刻由角度决定：射线扫到它那一格，它才亮
                ang_norm = ((ha + math.pi / 2) % TAU) / TAU
                spawn = PROBE_SECS * ang_norm + rnd.uniform(0, 0.10)
                hr = 0.10 + 0.86 * (rnd.random() ** 1.7)      # 往团心聚，成星团
                self.parts.append(Particle(
                    bi, spawn, ha, 1.02, ha, hr, rnd.uniform(0.7, 1.5)))
                k += 1
        self.parts.sort(key=lambda p: p.spawn)

    def _reset(self):
        self.phase = "idle"
        self.clock = 0.0
        self.sel = -1
        self.hover = -1

    # ---------------------------------------------------------- 时间

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last)
        self._last = now
        self.t_anim += dt
        self.spin += dt * 0.12

        # 松手后的旋转惯性
        if not self.dragging and abs(self.vel) > 0.0004:
            self.rot += self.vel
            self.vel *= 0.93
            self.update()
        else:
            if abs(self.vel) <= 0.0004:
                self.vel = 0.0

        # 按下反馈衰减
        if self.press_t > 0:
            self.press_t = max(0.0, self.press_t - dt / 0.14)

        # 所有"会突变"的量，都在这里逐帧逼近
        self.fade = approach(self.fade, 1.0, dt, 7.0)
        self.scale = approach(self.scale, self.scale_t, dt, 12.0)
        self.tilt_cur = approach(self.tilt_cur, self.tilt, dt, 10.0)
        for bi in range(len(self.hi)):
            tgt = 1.0 if (self.sel == bi or (self.sel < 0 and self.hover == bi)) else 0.0
            if self.sel >= 0 and self.sel != bi:
                tgt = -1.0
            self.hi[bi] = approach(self.hi[bi], tgt, dt, 16.0)
        # 射线在探测末尾淡出，不要"啪"一下没了
        near_end = max(0.0, (self.clock - (PROBE_SECS - 0.6)) / 0.6) if self.phase == "probe" else 1.0
        self.ray_a = approach(self.ray_a, 1.0 - min(1.0, near_end), dt, 18.0)

        if self.phase in ("idle", "done"):
            self.update()
            return
        self.clock += dt
        if self.phase == "probe" and self.clock >= PROBE_SECS:
            self.phase, self.clock = "settle", 0.0
            self.fade = 0.15
        elif self.phase == "settle" and self.clock >= SETTLE_SECS:
            self.phase, self.clock = "done", 0.0
        self.update()

    def _visible(self):
        if self.phase == "idle":
            return 0
        if self.phase in ("settle", "done"):
            return len(self.parts)
        n = 0
        for p in self.parts:
            if p.spawn <= self.clock:
                n += 1
            else:
                break
        return n

    # ---------------------------------------------------------- 几何

    def _center(self):
        return QPointF(self.width() * 0.60, self.height() * 0.52)

    def _radius(self):
        return min(self.width(), self.height()) * 0.34 * self.scale

    def _proj(self, c, r, a):
        return (c.x() + r * math.cos(a), c.y() + r * math.sin(a) * self.cur_flat)

    # ---------------------------------------------------------- 绘制

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._draw_space(p)
        c, R = self._center(), self._radius()

        self._draw_astrolabe(p, c, R)

        pen = QPen(QColor(255, 255, 255, 16))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(c.x() - R, c.y() - R, R * 2, R * 2))

        p.setOpacity(max(0.0, min(1.0, self.fade)))
        if self.phase == "idle":
            f = QFont()
            f.setPixelSize(15)
            p.setFont(f)
            p.setPen(QPen(QColor(232, 234, 237, 75)))
            p.drawText(QRectF(c.x() - R, c.y() - 12, R * 2, 24), Qt.AlignCenter, "空 盘")
        elif self.phase == "probe":
            self._draw_probe(p, c, R)
        else:
            self._draw_settled(p, c, R)

        p.setOpacity(1.0)
        self._draw_hud(p)
        self._draw_info(p)
        p.end()

    def _draw_probe(self, p, c, R):
        groups = {}
        for pt in self.parts:
            if pt.spawn > self.clock:
                break
            age = self.clock - pt.spawn
            t = ease_out(min(1.0, age / 0.6))
            rr = R * (pt.er + (pt.hr - pt.er) * t)
            a = pt.ea + (pt.ha - pt.ea) * t * 0.35 + 0.05 * math.sin(age * 2.6 + pt.jit * 7)
            groups.setdefault(pt.bucket, []).append(
                QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a)))

        for bi, pts in groups.items():
            col = QColor(BUCKETS[bi][3])
            col.setAlpha(200)
            pen = QPen(col)
            pen.setWidthF(4.6)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints(pts)

        # 扫描射线 + 拖尾扇形
        if self.ray_a < 0.02:
            return
        sweep = -math.pi / 2 + TAU * min(1.0, self.clock / PROBE_SECS)
        ra = max(0.0, min(1.0, self.ray_a))
        trail = QPainterPath()
        trail.moveTo(c.x(), c.y())
        steps = 26
        for i in range(steps + 1):
            a = sweep - 0.62 + 0.62 * i / steps
            x, y = self._proj(c, R * 1.06, a)
            trail.lineTo(x, y)
        trail.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(120, 190, 255, int(22 * ra)))
        p.drawPath(trail)

        pen = QPen(QColor(160, 214, 255, int(130 * ra)))
        pen.setWidthF(1.6)
        p.setPen(pen)
        x1, y1 = self._proj(c, R * 1.06, sweep)
        p.drawLine(QPointF(c.x(), c.y()), QPointF(x1, y1))

        # 射线头上的亮点
        for k, al in ((10.0, 26), (4.0, 90), (1.8, 235)):  # 乘以 ra
            col = QColor(190, 230, 255, int(al * ra))
            pen = QPen(col)
            pen.setWidthF(k)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints([QPointF(x1, y1)])

    def _build_space_cache(self):
        """把渐变 + 星云 + 全部静态星点烘成一张图。每帧只 drawPixmap 一次。
        之前每帧调 300 多次 drawPoints，帧率就是这么掉下去的。"""
        w, h = self.width(), self.height()
        pm = QPixmap(w, h)
        pm.fill(QColor("#04060b"))
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.Antialiasing, True)

        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, QColor("#04060b"))
        g.setColorAt(0.55, QColor("#070a12"))
        g.setColorAt(1.0, QColor("#0b0710"))
        pp.setPen(Qt.NoPen)
        pp.setBrush(g)
        pp.drawRect(0, 0, w, h)

        for cx, cy, rad, col, a_in in (
            (w * 0.30, h * 0.26, w * 0.42, QColor(90, 130, 220), 16),
            (w * 0.78, h * 0.78, w * 0.38, QColor(200, 120, 80), 12),
        ):
            ng = QRadialGradient(cx, cy, rad)
            c1 = QColor(col); c1.setAlpha(a_in)
            c2 = QColor(col); c2.setAlpha(0)
            ng.setColorAt(0.0, c1)
            ng.setColorAt(1.0, c2)
            pp.setBrush(ng)
            pp.drawEllipse(QRectF(cx - rad, cy - rad, rad * 2, rad * 2))

        # 星点按线宽分组，每组一次 drawPoints
        buckets = {}
        for s in self.stars:
            buckets.setdefault(s[2], []).append(QPointF(s[0], s[1]))
        for wdt, pts in buckets.items():
            col = QColor(206, 222, 255, 105)
            pen = QPen(col)
            pen.setWidthF(wdt)
            pen.setCapStyle(Qt.RoundCap)
            pp.setPen(pen)
            pp.drawPoints(pts)
        pp.end()
        self._space_pm = pm
        self._space_size = (w, h)

    def _draw_space(self, p):
        if self._space_pm is None or self._space_size != (self.width(), self.height()):
            self._build_space_cache()
        p.drawPixmap(0, 0, self._space_pm)

        # 只让 40 颗亮星闪，成本可以忽略
        for s in self.twinklers:
            tw = 0.45 + 0.55 * math.sin(self.t_anim * s[4] + s[5])
            col = QColor(214, 230, 255, int(s[3] * tw))
            pen = QPen(col)
            pen.setWidthF(s[2])
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints([QPointF(s[0], s[1])])

    def _unused_old_space(self, p):
        w, h = self.width(), self.height()

        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, QColor("#04060b"))
        g.setColorAt(0.55, QColor("#070a12"))
        g.setColorAt(1.0, QColor("#0b0710"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRect(self.rect())

        # 两团星云：一冷一暖，极淡
        for cx, cy, rad, col, a_in in (
            (w * 0.30, h * 0.26, w * 0.42, QColor(90, 130, 220), 16),
            (w * 0.78, h * 0.78, w * 0.38, QColor(200, 120, 80), 12),
        ):
            ng = QRadialGradient(cx, cy, rad)
            c1 = QColor(col); c1.setAlpha(a_in)
            c2 = QColor(col); c2.setAlpha(0)
            ng.setColorAt(0.0, c1)
            ng.setColorAt(1.0, c2)
            p.setBrush(ng)
            p.drawEllipse(QRectF(cx - rad, cy - rad, rad * 2, rad * 2))

        # 静态星点：分 3 档亮度，极慢闪
        p.setBrush(Qt.NoBrush)
        for s in self.stars:
            tw = 0.65 + 0.35 * math.sin(self.t_anim * s[4] + s[5])
            col = QColor(206, 222, 255, int(s[3] * tw))
            pen = QPen(col)
            pen.setWidthF(s[2])
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints([QPointF(s[0], s[1])])

    def _draw_astrolabe(self, p, c, R):
        """星盘底层：同心轨道 + 72 根刻度 + 四条极线 + 中心核。
        它有自己的慢速自转（self.spin），跟用户的交互旋转分开——
        所以盘子永远在极缓地转，你一碰它才加速。"""
        f = self.cur_flat

        # 三层轨道
        for i, rr in enumerate((1.00, 1.24, 1.52)):
            pen = QPen(QColor(126, 164, 214, 26 - i * 6))
            pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            rx, ry = R * rr, R * rr * f
            p.drawEllipse(QRectF(c.x() - rx, c.y() - ry, rx * 2, ry * 2))

        # 72 根刻度：合成一条 path，一次 drawPath（原来 72 次 drawLine 是掉帧主因之一）
        tick = QPainterPath()
        for i in range(72):
            a = self.spin + i * TAU / 72
            major = (i % 6 == 0)
            r0 = R * (1.47 if major else 1.505)
            r1 = R * (1.60 if major else 1.545)
            x0, y0 = self._proj(c, r0, a)
            x1, y1 = self._proj(c, r1, a)
            tick.moveTo(x0, y0)
            tick.lineTo(x1, y1)
        pen = QPen(QColor(126, 164, 214, 40))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(tick)

        # 四条极线
        pen = QPen(QColor(126, 164, 214, 20))
        pen.setWidth(1)
        p.setPen(pen)
        for i in range(4):
            a = self.spin * 0.5 + i * TAU / 4
            x0, y0 = self._proj(c, R * 0.10, a)
            x1, y1 = self._proj(c, R * 1.52, a)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        # 中心核：一个极小的亮点 + 一圈光
        for k, al in ((9.0, 10), (4.0, 26), (2.0, 90)):
            col = QColor(180, 210, 255, al)
            pen = QPen(col)
            pen.setWidthF(k)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints([QPointF(c.x(), c.y())])

    def _draw_sides(self, p, c, R):
        steps = 24
        for bi, (a0, a1) in enumerate(self.wedges):
            base = QColor(BUCKETS[bi][3]).darker(165)
            dim = 0.3 if (self.sel >= 0 and bi != self.sel) else 1.0
            for i in range(steps):
                aa0 = a0 + self.rot + (a1 - a0) * i / steps
                aa1 = a0 + self.rot + (a1 - a0) * (i + 1) / steps
                s = math.sin((aa0 + aa1) / 2)
                if s <= 0.02:
                    continue
                col = QColor(base)
                col.setAlpha(int(210 * min(1.0, s * 1.7) * dim))
                x0, y0 = self._proj(c, R, aa0)
                x1, y1 = self._proj(c, R, aa1)
                path = QPainterPath()
                path.moveTo(x0, y0)
                path.lineTo(x1, y1)
                path.lineTo(x1, y1 + self.cur_depth)
                path.lineTo(x0, y0 + self.cur_depth)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawPath(path)

    def _wedge_path(self, c, a0, a1, R, dy=0.0, steps=36):
        path = QPainterPath()
        path.moveTo(c.x(), c.y() + dy)
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * i / steps
            x, y = self._proj(c, R, a)
            path.lineTo(x, y + dy)
        path.closeSubpath()
        return path

    def _draw_faces(self, p, c, R):
        """每组一团星云光；悬停/锁定的那组**整块从盘面升起**（不是沿径向滑出去），
        其余各块原地不动——盘还是那个盘。"""
        p.setPen(Qt.NoPen)
        steps = 30

        for bi, (a0, a1) in enumerate(self.wedges):
            h = max(0.0, self.hi[bi])
            lift = 22.0 * h                      # 升起的高度
            aa0 = a0 + self.rot
            aa1 = a1 + self.rot
            col = QColor(BUCKETS[bi][3])
            dim = (self.sel >= 0 and self.sel != bi)

            # ① 原位留一个暗坑：告诉眼睛"这块被拿起来了"
            if lift > 0.6:
                hole = QColor(6, 8, 12, int(150 * min(1.0, lift / 12.0)))
                p.setBrush(hole)
                p.drawPath(self._wedge_path(c, aa0, aa1, R, 0.0, steps))

            # ② 整块的厚度侧壁：贴着升起后的位置
            if lift > 0.6:
                base = QColor(col).darker(175)
                band = {}
                for i in range(steps):
                    b0 = aa0 + (aa1 - aa0) * i / steps
                    b1 = aa0 + (aa1 - aa0) * (i + 1) / steps
                    s = math.sin((b0 + b1) / 2)
                    if s <= 0.02:
                        continue
                    x0, y0 = self._proj(c, R, b0)
                    x1, y1 = self._proj(c, R, b1)
                    cc = QColor(base)
                    cc.setAlpha(int(220 * min(1.0, s * 1.7)))
                    path = QPainterPath()
                    path.moveTo(x0, y0 - lift)
                    path.lineTo(x1, y1 - lift)
                    path.lineTo(x1, y1 - lift + self.cur_depth)
                    path.lineTo(x0, y0 - lift + self.cur_depth)
                    path.closeSubpath()
                    p.setBrush(cc)
                    p.drawPath(path)

            # ③ 面：抬起的那块亮一点，暗掉的组只是淡
            face = QColor(col)
            if dim:
                face.setAlpha(8)
            else:
                face.setAlpha(int(20 + 34 * h))
            p.setBrush(face)
            p.drawPath(self._wedge_path(c, aa0, aa1, R, -lift, steps))

        # ④ 星云光：跟着抬起
        for bi, (a0, a1) in enumerate(self.wedges):
            h = max(0.0, self.hi[bi])
            lift = 22.0 * h
            am = (a0 + a1) / 2 + self.rot
            rr = R * 0.52
            gx = c.x() + rr * math.cos(am)
            gy = c.y() + rr * math.sin(am) * self.cur_flat - lift
            rad = min(R * 0.95, max(34.0, R * (a1 - a0) * 0.62 + R * 0.14))
            col = QColor(BUCKETS[bi][3])
            a_in = int(52 + 20 * h) if h >= 0 else 16
            g = QRadialGradient(gx, gy, rad)
            c1 = QColor(col); c1.setAlpha(a_in)
            c2 = QColor(col); c2.setAlpha(0)
            g.setColorAt(0.0, c1)
            g.setColorAt(1.0, c2)
            p.setBrush(g)
            p.drawEllipse(QRectF(gx - rad, gy - rad * self.cur_flat,
                                 rad * 2, rad * 2 * self.cur_flat))

    def _draw_settled(self, p, c, R):
        t_all = 1.0 if self.phase == "done" else min(1.0, self.clock / SETTLE_SECS)

        # 两段：
        #   前 55%：粒子在平面上收拢成饼（flat 一直 1.0，正圆）
        #   后 45%：饼整体倾斜成 3D（这段粒子基本不再动）
        # 两个动作分开，才读得出"先聚合、再转立体"的叙事
        t_conv = min(1.0, t_all / CONVERGE_PART)
        t_tilt = max(0.0, (t_all - CONVERGE_PART) / (1.0 - CONVERGE_PART))
        k_tilt = 1.0 if self.phase == "done" else spring(t_tilt)
        self.cur_flat = FLAT_TOP + (self.tilt_cur - FLAT_TOP) * k_tilt
        self.cur_depth = DEPTH_END * k_tilt

        if t_all > 0.35:
            self._draw_sides(p, c, R)
        self._draw_faces(p, c, R)

        core = {}
        for pt in self.parts:
            # 起点：飞入结束时的位置（永远正圆，不受 flat 影响）
            sx = c.x() + R * pt.hr * math.cos(pt.ha)
            sy = c.y() + R * pt.hr * math.sin(pt.ha)

            ha = pt.ha + self.rot
            hr = R * pt.hr
            hr *= 1.0 + 0.006 * math.sin(self.t_anim * 1.15 + pt.jit * 4.1)

            ex = c.x() + hr * math.cos(ha)
            ey = c.y() + hr * math.sin(ha) * self.cur_flat

            hh = max(0.0, self.hi[pt.bucket])
            if hh > 0.001:
                ey -= 22.0 * hh          # 跟整块一起垂直升起，不沿径向散开
            if self.press_bucket == pt.bucket and self.press_t > 0:
                ey += 4 * self.press_t

            # 错峰：每颗粒子自己的开始时刻
            delay = STAGGER * ((pt.jit * 11.3) % 1.0)
            tl = min(1.0, max(0.0, (t_conv - delay) / max(0.001, 1 - STAGGER)))
            t = 1.0 if self.phase == "done" else spring(tl)

            # 弧线：控制点往盘心方向拉，走内收的曲线而不是直线
            mx = (sx + ex) / 2 + (c.x() - (sx + ex) / 2) * 0.16
            my = (sy + ey) / 2 + (c.y() - (sy + ey) / 2) * 0.16
            x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * mx + t * t * ex
            y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * my + t * t * ey

            # 上下浮沉
            z_amp = 2.0 + 7.0 * ((pt.jit * 13.7) % 1.0)
            z_ph = pt.jit * 6.3
            z_spd = 0.30 + 0.38 * ((pt.jit * 7.1) % 1.0)
            y -= z_amp * math.sin(self.t_anim * z_spd * TAU * 0.5 + z_ph) * min(1.0, t)

            b = 0.5 + 0.5 * math.sin(self.t_anim * (0.55 + 0.5 * ((pt.jit * 3.3) % 1.0)) + pt.jit * 9.1)
            lvl = 0 if b < 0.34 else (1 if b < 0.67 else 2)
            core.setdefault((pt.bucket, lvl), []).append(QPointF(x, y))

        for pass_glow in (True, False):
            for (bi, lvl), pts in core.items():
                col = QColor(BUCKETS[bi][3])
                if self.sel >= 0 and bi != self.sel:
                    col.setAlpha(int(10 + 6 * lvl) if pass_glow else int(30 + 15 * lvl))
                else:
                    boost = 12 if self.hover == bi else 0
                    col.setAlpha(int(16 + 13 * lvl + boost) if pass_glow
                                 else int(140 + 45 * lvl + boost))
                pen = QPen(col)
                pen.setWidthF(15.0 if pass_glow else 4.6)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawPoints(pts)

    def _draw_hud(self, p):
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QPen(DIM))

        if self.phase == "idle":
            state = "星盘待观测    按空格开始"
        elif self.phase == "probe":
            state = "探测中  %d / %d" % (self._visible(), len(self.parts))
        elif self.phase == "settle":
            state = "星图成形…"
        else:
            state = "聚合完成  %d 个" % TOTAL_N

        p.drawText(QRectF(28, 20, self.width() - 56, 18), Qt.AlignLeft, "DiskProbe · 粒子盘面原型")
        p.drawText(QRectF(28, 40, self.width() - 56, 18), Qt.AlignLeft, state)
        p.setPen(QPen(QColor(78, 156, 245, 200)))
        f2 = QFont()
        f2.setPixelSize(14)
        p.setFont(f2)
        p.drawText(QRectF(28, 62, self.width() - 56, 18), Qt.AlignLeft,
                   self._mode()[2] + "  (Tab 切换)")

        p.setFont(f)
        p.setPen(QPen(QColor(232, 234, 237, 48)))
        p.drawText(QRectF(28, self.height() - 40, self.width() - 56, 18), Qt.AlignLeft,
                   "空格 重放   F 快进   左拖 旋转(带惯性)   右键拖动 改倾角   滚轮 缩放 %.2fx   双击 复位   点击 选中" % self.scale)

    def _draw_info(self, p):
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        x, y = 28, 112

        target = self.sel if self.sel >= 0 else self.hover
        if target < 0:
            p.setPen(QPen(QColor(232, 234, 237, 55)))
            p.drawText(QPointF(x, y), "(把鼠标移到扇区上试试)")
            return

        name, n, mb, col = BUCKETS[target]
        p.setPen(QPen(col))
        f2 = QFont()
        f2.setPixelSize(28)
        p.setFont(f2)
        p.drawText(QPointF(x, y + 12), name)

        p.setFont(f)
        p.setPen(QPen(FG))
        y += 52
        p.drawText(QPointF(x, y), "%d 个" % n)
        y += 21
        p.drawText(QPointF(x, y), "%.1f MB" % mb)
        y += 26
        p.setPen(QPen(DIM))
        p.drawText(QPointF(x, y), "占数量 %.1f%%" % (100.0 * n / TOTAL_N))
        y += 19
        p.drawText(QPointF(x, y), "占大小 %.1f%%" % (100.0 * mb / TOTAL_MB))
        if self.sel < 0:
            y += 26
            p.setPen(QPen(QColor(232, 234, 237, 45)))
            p.drawText(QPointF(x, y), "（悬停预览，点击锁定）")

    # ---------------------------------------------------------- 交互

    def _hit(self, pos):
        c, R = self._center(), self._radius()
        dx = pos.x() - c.x()
        dy = (pos.y() - c.y()) / max(0.01, self.cur_flat)
        if math.hypot(dx, dy) > R * 1.12:
            return -1
        ang = math.atan2(dy, dx) - self.rot
        while ang < -math.pi / 2:
            ang += TAU
        while ang >= TAU - math.pi / 2:
            ang -= TAU
        for i, (a0, a1) in enumerate(self.wedges):
            if a0 <= ang < a1:
                return i
        return -1

    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton:
            self.tilt_drag = True
            self.tilt_prev = ev.position().y()
            self.setCursor(Qt.SizeVerCursor)
            return
        if ev.button() != Qt.LeftButton:
            return
        if self.phase != "done":
            self.phase, self.clock, self.rot, self.vel = "done", 0.0, 0.0, 0.0
            self.cur_flat, self.cur_depth = FLAT_END, DEPTH_END
            self.update()
            return
        self.dragging = True
        self.moved = 0.0
        self.vel = 0.0
        c = self._center()
        self.drag_prev = math.atan2(ev.position().y() - c.y(), ev.position().x() - c.x())
        self.press_bucket = self._hit(ev.position())
        self.press_t = 1.0
        self.update()

    def mouseMoveEvent(self, ev):
        if self.tilt_drag:
            dy = ev.position().y() - self.tilt_prev
            self.tilt_prev = ev.position().y()
            self.tilt = min(1.0, max(0.18, self.tilt - dy * 0.006))
            self.update()
            return
        if self.dragging:
            c = self._center()
            ang = math.atan2(ev.position().y() - c.y(), ev.position().x() - c.x())
            d = ang - self.drag_prev
            while d > math.pi:
                d -= TAU
            while d < -math.pi:
                d += TAU
            self.rot += d
            self.vel = d * 0.85
            self.moved += abs(d)
            self.drag_prev = ang
            self.update()
            return

        # 悬停：扇区微亮 + 光标变手型
        h = self._hit(ev.position()) if self.phase == "done" else -1
        if h != self.hover:
            self.hover = h
            self.update()
        self.setCursor(Qt.PointingHandCursor if h >= 0 else Qt.ArrowCursor)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.RightButton:
            self.tilt_drag = False
            self.setCursor(Qt.ArrowCursor)
            return
        if ev.button() != Qt.LeftButton or not self.dragging:
            return
        self.dragging = False
        self.press_t = 0.0
        if self.moved < 0.05:
            idx = self._hit(ev.position())
            self.sel = -1 if idx == self.sel else idx
            self.vel = 0.0
        self.update()

    def wheelEvent(self, ev):
        step = 1.10 if ev.angleDelta().y() > 0 else (1 / 1.10)
        self.scale_t = min(1.7, max(0.65, self.scale_t * step))
        self.update()

    def mouseDoubleClickEvent(self, _ev):
        self.rot = 0.0
        self.vel = 0.0
        self.scale_t = 1.0
        self.tilt = FLAT_END
        self.sel = -1
        self.update()

    def _cycle(self, step):
        self.mode_idx = (self.mode_idx + step) % len(MODES)
        self._rebuild()
        self.rot = 0.0
        self.vel = 0.0
        self.sel = -1
        self.hover = -1
        self.phase = "done"
        self.clock = 0.0
        self.cur_flat, self.cur_depth = FLAT_END, DEPTH_END

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Space:
            self._rebuild()
            self.rot = 0.0
            self.vel = 0.0
            self.sel = -1
            self.hover = -1
            self.cur_flat, self.cur_depth = FLAT_TOP, 0
            self.phase = "probe"
            self.clock = 0.0
            self.fade = 0.0
            self.ray_a = 1.0
            self._last = time.perf_counter()
        elif k == Qt.Key_F:
            self.phase, self.clock, self.rot, self.vel = "done", 0.0, 0.0, 0.0
            self.cur_flat, self.cur_depth = FLAT_END, DEPTH_END
        elif k == Qt.Key_Tab:
            self._cycle(1)
        elif k == Qt.Key_Backtab:
            self._cycle(-1)
        elif k == Qt.Key_R:
            self.mouseDoubleClickEvent(None)
        elif k == Qt.Key_Escape:
            self.close()
        self.update()


def main():
    app = QApplication(sys.argv)
    w = Canvas()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
