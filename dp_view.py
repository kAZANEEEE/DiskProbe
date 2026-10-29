# -*- coding: utf-8 -*-
"""DiskProbe · 绘制层（拆自 prototype.py）

**只画，不改状态。** 所有需要的东西都从 canvas 上读。
好处：改视觉碰不到事件与状态；改交互也不会把画面改崩。
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
                           QLinearGradient, QRadialGradient)

from dp_data import *


class StarChartView:
    """所有绘制集中在这一个类里。canvas 只负责状态和事件。"""

    def __init__(self, canvas):
        self.c = canvas

    def draw_all(self):
        p = QPainter(self.c)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._draw_space(p)
        c, R = self.c._center(), self.c._radius()

        self._draw_astrolabe(p, c, R)

        pen = QPen(QColor(255, 255, 255, 16))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(c.x() - R, c.y() - R, R * 2, R * 2))

        p.setOpacity(max(0.0, min(1.0, self.c.fade)))
        if self.c.phase == "idle":
            f = QFont()
            f.setPixelSize(15)
            p.setFont(f)
            p.setPen(QPen(QColor(232, 234, 237, 75)))
            p.drawText(QRectF(c.x() - R, c.y() - 12, R * 2, 24), Qt.AlignCenter, "空 盘")
        elif self.c.phase == "probe":
            self._draw_probe(p, c, R)
        else:
            self._draw_settled(p, c, R)

        p.setOpacity(1.0)
        self._draw_hud(p)
        self._draw_info(p)
        p.end()

    def _draw_probe(self, p, c, R):
        groups = {}
        for pt in self.c.parts:
            if pt.spawn > self.c.clock:
                break
            age = self.c.clock - pt.spawn
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
        if self.c.ray_a < 0.02:
            return
        sweep = -math.pi / 2 + TAU * min(1.0, self.c.clock / PROBE_SECS)
        ra = max(0.0, min(1.0, self.c.ray_a))
        trail = QPainterPath()
        trail.moveTo(c.x(), c.y())
        steps = 26
        for i in range(steps + 1):
            a = sweep - 0.62 + 0.62 * i / steps
            x, y = self.c._proj(c, R * 1.06, a)
            trail.lineTo(x, y)
        trail.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(120, 190, 255, int(22 * ra)))
        p.drawPath(trail)

        pen = QPen(QColor(160, 214, 255, int(130 * ra)))
        pen.setWidthF(1.6)
        p.setPen(pen)
        x1, y1 = self.c._proj(c, R * 1.06, sweep)
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
        w, h = self.c.width(), self.c.height()
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
        for s in self.c.stars:
            buckets.setdefault(s[2], []).append(QPointF(s[0], s[1]))
        for wdt, pts in buckets.items():
            col = QColor(206, 222, 255, 105)
            pen = QPen(col)
            pen.setWidthF(wdt)
            pen.setCapStyle(Qt.RoundCap)
            pp.setPen(pen)
            pp.drawPoints(pts)
        pp.end()
        self.c._space_pm = pm
        self.c._space_size = (w, h)

    def _draw_space(self, p):
        if self.c._space_pm is None or self.c._space_size != (self.c.width(), self.c.height()):
            self._build_space_cache()
        p.drawPixmap(0, 0, self.c._space_pm)

        # 只让 40 颗亮星闪，成本可以忽略
        for s in self.c.twinklers:
            tw = 0.45 + 0.55 * math.sin(self.c.t_anim * s[4] + s[5])
            col = QColor(214, 230, 255, int(s[3] * tw))
            pen = QPen(col)
            pen.setWidthF(s[2])
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPoints([QPointF(s[0], s[1])])

    def _draw_astrolabe(self, p, c, R):
        """星盘底层：同心轨道 + 72 根刻度 + 四条极线 + 中心核。
        它有自己的慢速自转（self.c.spin），跟用户的交互旋转分开——
        所以盘子永远在极缓地转，你一碰它才加速。"""
        f = self.c.cur_flat

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
            a = self.c.spin + i * TAU / 72
            major = (i % 6 == 0)
            r0 = R * (1.47 if major else 1.505)
            r1 = R * (1.60 if major else 1.545)
            x0, y0 = self.c._proj(c, r0, a)
            x1, y1 = self.c._proj(c, r1, a)
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
            a = self.c.spin * 0.5 + i * TAU / 4
            x0, y0 = self.c._proj(c, R * 0.10, a)
            x1, y1 = self.c._proj(c, R * 1.52, a)
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
        for bi, (a0, a1) in enumerate(self.c.wedges):
            base = QColor(BUCKETS[bi][3]).darker(165)
            dim = 0.3 if (self.c.sel >= 0 and bi != self.c.sel) else 1.0
            for i in range(steps):
                aa0 = a0 + self.c.rot + (a1 - a0) * i / steps
                aa1 = a0 + self.c.rot + (a1 - a0) * (i + 1) / steps
                s = math.sin((aa0 + aa1) / 2)
                if s <= 0.02:
                    continue
                col = QColor(base)
                col.setAlpha(int(210 * min(1.0, s * 1.7) * dim))
                x0, y0 = self.c._proj(c, R, aa0)
                x1, y1 = self.c._proj(c, R, aa1)
                path = QPainterPath()
                path.moveTo(x0, y0)
                path.lineTo(x1, y1)
                path.lineTo(x1, y1 + self.c.cur_depth)
                path.lineTo(x0, y0 + self.c.cur_depth)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawPath(path)

    def _wedge_path(self, c, a0, a1, R, dy=0.0, steps=36):
        path = QPainterPath()
        path.moveTo(c.x(), c.y() + dy)
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * i / steps
            x, y = self.c._proj(c, R, a)
            path.lineTo(x, y + dy)
        path.closeSubpath()
        return path

    def _draw_faces(self, p, c, R):
        """每组一团星云光；悬停/锁定的那组**整块从盘面升起**（不是沿径向滑出去），
        其余各块原地不动——盘还是那个盘。"""
        p.setPen(Qt.NoPen)
        steps = 30

        for bi, (a0, a1) in enumerate(self.c.wedges):
            h = max(0.0, self.c.hi[bi])
            lift = 22.0 * h                      # 升起的高度
            aa0 = a0 + self.c.rot
            aa1 = a1 + self.c.rot
            col = QColor(BUCKETS[bi][3])
            dim = (self.c.sel >= 0 and self.c.sel != bi)

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
                    x0, y0 = self.c._proj(c, R, b0)
                    x1, y1 = self.c._proj(c, R, b1)
                    cc = QColor(base)
                    cc.setAlpha(int(220 * min(1.0, s * 1.7)))
                    path = QPainterPath()
                    path.moveTo(x0, y0 - lift)
                    path.lineTo(x1, y1 - lift)
                    path.lineTo(x1, y1 - lift + self.c.cur_depth)
                    path.lineTo(x0, y0 - lift + self.c.cur_depth)
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
        for bi, (a0, a1) in enumerate(self.c.wedges):
            h = max(0.0, self.c.hi[bi])
            lift = 22.0 * h
            am = (a0 + a1) / 2 + self.c.rot
            rr = R * 0.52
            gx = c.x() + rr * math.cos(am)
            gy = c.y() + rr * math.sin(am) * self.c.cur_flat - lift
            rad = min(R * 0.95, max(34.0, R * (a1 - a0) * 0.62 + R * 0.14))
            col = QColor(BUCKETS[bi][3])
            a_in = int(52 + 20 * h) if h >= 0 else 16
            g = QRadialGradient(gx, gy, rad)
            c1 = QColor(col); c1.setAlpha(a_in)
            c2 = QColor(col); c2.setAlpha(0)
            g.setColorAt(0.0, c1)
            g.setColorAt(1.0, c2)
            p.setBrush(g)
            p.drawEllipse(QRectF(gx - rad, gy - rad * self.c.cur_flat,
                                 rad * 2, rad * 2 * self.c.cur_flat))

    def _draw_settled(self, p, c, R):
        t_all = 1.0 if self.c.phase == "done" else min(1.0, self.c.clock / SETTLE_SECS)

        # 两段：
        #   前 55%：粒子在平面上收拢成饼（flat 一直 1.0，正圆）
        #   后 45%：饼整体倾斜成 3D（这段粒子基本不再动）
        # 两个动作分开，才读得出"先聚合、再转立体"的叙事
        t_conv = min(1.0, t_all / CONVERGE_PART)
        t_tilt = max(0.0, (t_all - CONVERGE_PART) / (1.0 - CONVERGE_PART))
        k_tilt = 1.0 if self.c.phase == "done" else spring(t_tilt)
        self.c.cur_flat = FLAT_TOP + (self.c.tilt_cur - FLAT_TOP) * k_tilt
        self.c.cur_depth = DEPTH_END * k_tilt

        if t_all > 0.35:
            self._draw_sides(p, c, R)
        self._draw_faces(p, c, R)

        core = {}
        for pt in self.c.parts:
            # 起点：飞入结束时的位置（永远正圆，不受 flat 影响）
            sx = c.x() + R * pt.hr * math.cos(pt.ha)
            sy = c.y() + R * pt.hr * math.sin(pt.ha)

            ha = pt.ha + self.c.rot
            hr = R * pt.hr
            hr *= 1.0 + 0.006 * math.sin(self.c.t_anim * 1.15 + pt.jit * 4.1)

            ex = c.x() + hr * math.cos(ha)
            ey = c.y() + hr * math.sin(ha) * self.c.cur_flat

            hh = max(0.0, self.c.hi[pt.bucket])
            if hh > 0.001:
                ey -= 22.0 * hh          # 跟整块一起垂直升起，不沿径向散开
            if self.c.press_bucket == pt.bucket and self.c.press_t > 0:
                ey += 4 * self.c.press_t

            # 错峰：每颗粒子自己的开始时刻
            delay = STAGGER * ((pt.jit * 11.3) % 1.0)
            tl = min(1.0, max(0.0, (t_conv - delay) / max(0.001, 1 - STAGGER)))
            t = 1.0 if self.c.phase == "done" else spring(tl)

            # 弧线：控制点往盘心方向拉，走内收的曲线而不是直线
            mx = (sx + ex) / 2 + (c.x() - (sx + ex) / 2) * 0.16
            my = (sy + ey) / 2 + (c.y() - (sy + ey) / 2) * 0.16
            x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * mx + t * t * ex
            y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * my + t * t * ey

            # 上下浮沉
            z_amp = 2.0 + 7.0 * ((pt.jit * 13.7) % 1.0)
            z_ph = pt.jit * 6.3
            z_spd = 0.30 + 0.38 * ((pt.jit * 7.1) % 1.0)
            y -= z_amp * math.sin(self.c.t_anim * z_spd * TAU * 0.5 + z_ph) * min(1.0, t)

            b = 0.5 + 0.5 * math.sin(self.c.t_anim * (0.55 + 0.5 * ((pt.jit * 3.3) % 1.0)) + pt.jit * 9.1)
            lvl = 0 if b < 0.34 else (1 if b < 0.67 else 2)
            core.setdefault((pt.bucket, lvl), []).append(QPointF(x, y))

        for pass_glow in (True, False):
            for (bi, lvl), pts in core.items():
                col = QColor(BUCKETS[bi][3])
                if self.c.sel >= 0 and bi != self.c.sel:
                    col.setAlpha(int(10 + 6 * lvl) if pass_glow else int(30 + 15 * lvl))
                else:
                    boost = 12 if self.c.hover == bi else 0
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

        if self.c.phase == "idle":
            state = "星盘待观测    按空格开始"
        elif self.c.phase == "probe":
            state = "探测中  %d / %d" % (self.c._visible(), len(self.c.parts))
        elif self.c.phase == "settle":
            state = "星图成形…"
        else:
            state = "聚合完成  %d 个" % TOTAL_N

        p.drawText(QRectF(28, 20, self.c.width() - 56, 18), Qt.AlignLeft, "DiskProbe · 粒子盘面原型")
        p.drawText(QRectF(28, 40, self.c.width() - 56, 18), Qt.AlignLeft, state)
        p.setPen(QPen(QColor(78, 156, 245, 200)))
        f2 = QFont()
        f2.setPixelSize(14)
        p.setFont(f2)
        p.drawText(QRectF(28, 62, self.c.width() - 56, 18), Qt.AlignLeft,
                   self.c._mode()[2] + "  (Tab 切换)")

        p.setFont(f)
        p.setPen(QPen(QColor(232, 234, 237, 48)))
        p.drawText(QRectF(28, self.c.height() - 40, self.c.width() - 56, 18), Qt.AlignLeft,
                   "空格 重放   F 快进   左拖 旋转(带惯性)   右键拖动 改倾角   滚轮 缩放 %.2fx   双击 复位   点击 选中" % self.c.scale)

    def _draw_info(self, p):
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        x, y = 28, 112

        target = self.c.sel if self.c.sel >= 0 else self.c.hover
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
        if self.c.sel < 0:
            y += 26
            p.setPen(QPen(QColor(232, 234, 237, 45)))
            p.drawText(QPointF(x, y), "（悬停预览，点击锁定）")

    # ---------------------------------------------------------- 交互

