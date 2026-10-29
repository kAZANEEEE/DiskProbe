# -*- coding: utf-8 -*-
"""DiskProbe · 数据与数学（拆自 prototype.py）

这一层不认识 Qt 的窗口，只提供：分桶数据、常量、缓动与弹簧函数、Particle。
改数值（颜色、时长、错峰比例）只改这个文件。
"""
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


