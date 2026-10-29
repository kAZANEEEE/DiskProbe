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
    Tab       切换三种组合（这是本原型最想看的东西）
    Shift+Tab 反向切换
    拖拽      旋转
    点击      选中扇区（再点空白取消）

三种组合：
    1 扇区按大小 · 粒子＝文件数     <- 会打架：面积大的没点，点多的面积小
    2 扇区按数量 · 粒子＝文件数     <- 自洽，但"占地方"这件事看不出来
    3 扇区按大小 · 粒子按面积       <- 好看，但"一个点＝一个文件"不成立了

跑法：
    py -3 prototype.py
"""
import math
import random
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
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
SETTLE_SECS = 1.2
TAU = math.pi * 2
WEDGE_GAP = 0.016          # 扇区之间的缝（弧度）

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


class Particle:
    __slots__ = ("bucket", "spawn", "ea", "er", "ha", "hr", "jit")

    def __init__(self, bucket, spawn, ea, er, ha, hr, jit):
        self.bucket = bucket
        self.spawn = spawn      # 出现时刻
        self.ea = ea            # 入场角
        self.er = er            # 入场半径（相对 R）
        self.ha = ha            # 落位角
        self.hr = hr            # 落位半径（相对 R）
        self.jit = jit


class Canvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DiskProbe · 粒子盘面原型")
        self.resize(1280, 820)

        self.mode_idx = 0
        self.rot = 0.0
        self.sel = -1
        self.dragging = False
        self.drag_prev = 0.0
        self.moved = 0.0

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
                u = k / max(1, total - 1)
                spawn = PROBE_SECS * (u ** 1.35)      # 前密后疏，像真扫盘
                ea = rnd.uniform(0, TAU)
                er = rnd.uniform(0.92, 1.36)
                ha = a0 + (a1 - a0) * rnd.random()
                hr = math.sqrt(rnd.random())           # 按面积均匀撒
                self.parts.append(Particle(bi, spawn, ea, er, ha, hr, rnd.uniform(0.7, 1.5)))
                k += 1
        self.parts.sort(key=lambda p: p.spawn)

    def _reset(self):
        self.phase = "idle"
        self.clock = 0.0
        self.sel = -1

    # ---------------------------------------------------------- 时间

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last)
        self._last = now
        if self.phase in ("idle", "done"):
            self.update()
            return
        self.clock += dt
        if self.phase == "probe" and self.clock >= PROBE_SECS:
            self.phase, self.clock = "settle", 0.0
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
        return min(self.width(), self.height()) * 0.34

    # ---------------------------------------------------------- 绘制

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), BG)
        c, R = self._center(), self._radius()

        pen = QPen(QColor(255, 255, 255, 16))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(c.x() - R, c.y() - R, R * 2, R * 2))

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

        frac = min(1.0, self.clock / PROBE_SECS)
        pen = QPen(QColor(78, 156, 245, 45))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawArc(QRectF(c.x() - R * 1.4, c.y() - R * 1.4, R * 2.8, R * 2.8),
                  90 * 16, int(-360 * 16 * frac))

    def _draw_settled(self, p, c, R):
        t = 1.0 if self.phase == "done" else ease_in_out(min(1.0, self.clock / SETTLE_SECS))
        groups = {}
        for pt in self.parts:
            start_r = R * pt.hr
            start_a = pt.ha
            ha = pt.ha + self.rot
            hr = R * (0.14 + 0.84 * pt.hr)
            sx, sy = start_r * math.cos(start_a), start_r * math.sin(start_a)
            ex, ey = hr * math.cos(ha), hr * math.sin(ha)
            x = sx + (ex - sx) * t
            y = sy + (ey - sy) * t
            if self.sel == pt.bucket:
                x += math.cos(ha) * 14 * t      # 选中扇区整体向外移 14px
                y += math.sin(ha) * 14 * t
            groups.setdefault(pt.bucket, []).append(QPointF(c.x() + x, c.y() + y))

        for bi, pts in groups.items():
            col = QColor(BUCKETS[bi][3])
            if self.sel >= 0 and bi != self.sel:
                col.setAlpha(55)
            else:
                col.setAlpha(215)
            pen = QPen(col)
            pen.setWidthF(4.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints(pts)

    def _draw_hud(self, p):
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QPen(DIM))

        if self.phase == "idle":
            state = "空盘    按空格开始"
        elif self.phase == "probe":
            state = "探测中  %d / %d" % (self._visible(), len(self.parts))
        elif self.phase == "settle":
            state = "聚合中…"
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
                   "空格 重放   F 快进   拖拽 旋转   点击 选中")

    def _draw_info(self, p):
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        x, y = 28, 112

        if self.sel < 0:
            p.setPen(QPen(QColor(232, 234, 237, 55)))
            p.drawText(QPointF(x, y), "(点一个扇区试试)")
            return

        name, n, mb, col = BUCKETS[self.sel]
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

    # ---------------------------------------------------------- 交互

    def _hit(self, pos):
        c, R = self._center(), self._radius()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
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
        if ev.button() != Qt.LeftButton:
            return
        if self.phase != "done":
            self.phase, self.clock, self.rot = "done", 0.0, 0.0
            self.update()
            return
        self.dragging = True
        self.moved = 0.0
        c = self._center()
        self.drag_prev = math.atan2(ev.position().y() - c.y(), ev.position().x() - c.x())

    def mouseMoveEvent(self, ev):
        if not self.dragging:
            return
        c = self._center()
        ang = math.atan2(ev.position().y() - c.y(), ev.position().x() - c.x())
        d = ang - self.drag_prev
        while d > math.pi:
            d -= TAU
        while d < -math.pi:
            d += TAU
        self.rot += d
        self.moved += abs(d)
        self.drag_prev = ang
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton or not self.dragging:
            return
        self.dragging = False
        if self.moved < 0.05:
            idx = self._hit(ev.position())
            self.sel = -1 if idx == self.sel else idx
        self.update()

    def _cycle(self, step):
        self.mode_idx = (self.mode_idx + step) % len(MODES)
        self._rebuild()
        self.rot = 0.0
        self.sel = -1
        self.phase = "done"
        self.clock = 0.0

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Space:
            self._rebuild()
            self.rot = 0.0
            self.sel = -1
            self.phase = "probe"
            self.clock = 0.0
            self._last = time.perf_counter()
        elif k == Qt.Key_F:
            self.phase, self.clock, self.rot = "done", 0.0, 0.0
        elif k == Qt.Key_Tab:
            self._cycle(1)
        elif k == Qt.Key_Backtab:
            self._cycle(-1)
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
