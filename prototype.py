# -*- coding: utf-8 -*-
"""DiskProbe · 粒子盘面原型 —— 入口与交互状态

拆成三个文件了：
    dp_data.py    分桶数据、常量、缓动/弹簧数学、Particle
    dp_view.py    绘制（只画，不改状态）
    prototype.py  这个文件：状态 + 鼠标键盘 + 入口

跑法：py -3 prototype.py

操作：
    空格 重放 / F 快进 / Tab 切口径 / 左拖 旋转(带惯性)
    右键上下拖 改倾角 / 滚轮 缩放 / 双击 复位 / 点击 锁定
"""
import math
import random
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
                           QLinearGradient, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from dp_data import *
from dp_view import StarChartView


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

        self.view = StarChartView(self)

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

    def paintEvent(self, _ev):
        """画面全交给绘制层；这里只管触发。"""
        self.view.draw_all()


def main():
    app = QApplication(sys.argv)
    w = Canvas()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
