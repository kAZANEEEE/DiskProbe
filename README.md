# DiskProbe · 软件星团

扫一个目录，把里面的 exe 全找出来，按它们在哪个文件夹里分组，画成一张星系图。

![预览](assets/海报_产品介绍.png)

---

## 为什么写这个

我 D 盘里有一千多个 exe。

想搞清楚都是些什么东西，资源管理器只能按大小排，排完还是不知道那一堆是哪来的。后来想想，其实我想知道的不多：这些东西分成了几堆、哪堆最占地方、散在哪些文件夹里。

所以就写了这个。扫完之后它告诉我：1010 个 exe，29 堆，最大的一堆是 Visual Studio 拖来的 153 个。

- 平台：Windows 10 / 11
- Python 3.10+ / PySide6 / QPainter 自绘 / SQLite
- 版本：v0.1

---

## 怎么跑

**装了 Python：**

```powershell
py -3 -m pip install PySide6-Essentials
py -3 ui.py
```

**没装：**

去 [Releases](https://github.com/kAZANEEEE/DiskProbe/releases) 下 `DiskProbe.exe`，双击就行。

第一次会被 SmartScreen 拦一下，点「更多信息」→「仍要运行」。没签名，正常。

---

## 怎么用

1. 打开，等开场动画播完
2. 点右下角「选择目录以开始扫描」，选个文件夹
3. 星星会一颗颗飞进来，一颗就是一个 exe
4. 扫完，星系按文件夹分成几条旋臂

| 操作 | 效果 |
|---|---|
| 滚轮 | 缩放 |
| 双击空白 | 复位视角 |
| 拖动空白 | 旋转、上下拖改倾角 |
| 悬停一条臂 | 这组浮起来，其他压暗 |
| 点一条臂 | 锁定，相机会转过去 |
| `Esc` | 取消锁定 |
| `←` `→` | 一组一组切 |
| 查看全部 N 个 → | 完整清单，带目录列 |
| 搜索框 | 按路径过滤 |

侧栏那几个页面还没做。点它们，按钮会当场碎掉，然后飘一句「老子还没做」。第一版是给朋友看的，这个尺度我觉得还行。

「插件中心」里藏了个东西。

---

## 几点说明

- **一条旋臂 = 一个文件夹**，不是「一类软件」。要判断这是游戏还是开发工具，得去读 exe 内部的信息，那是猜，我先不猜。
- **总大小只算 exe 本身**，不算同一个文件夹里的其他东西。
- **扫不全就说扫不全。**回收站、System Volume Information 这些进不去的目录，界面上会写清有几个没读到。

---

## 数据在哪

```
%LOCALAPPDATA%\DiskProbe\diskprobe.db
```

一个 SQLite 文件。删了不影响你任何原始文件，只是下次要重扫。

---

## 自己打包

```powershell
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --noconfirm --windowed --onefile ^
    --name DiskProbe --icon assets/logo.ico ^
    --add-data "assets;assets" --add-data "彩蛋.md;." ui.py
```

出来在 `dist\DiskProbe.exe`，43 MB。

有个坑记一下：`--windowed` 打包之后 `sys.stdout` 是 `None`，代码里任何一句 `print()` 都会让程序直接死掉，而且什么错误都不显示。这个项目运行路径里没有 print，所以是安全的。以后要加调试输出记得先想想这事。

---

## 目录

```
查盘工具/
├─ ui.py            界面（星图、面板、动效都在这里）
├─ scanner.py       扫描器
├─ storage.py       SQLite 读写
├─ classify.py      分组
├─ assets/          logo、海报、设置说明
├─ tests/           验收测试，纯脚本
├─ 踩坑记录.md      二十多条真踩过的坑
├─ 术语对照.md      英文标识符的中文对照
├─ 交互叙事闭环.md  动效规格
└─ 彩蛋.md
```

## 测试

```powershell
py -3 tests\test_scan_acceptance.py
py -3 tests\test_storage.py
```

看到「总结： 全过」就是正常的。不用装 pytest，就是两个普通脚本。

---

## 怎么来的

最开始只有一个问题：**怎么用 Python 把一棵目录树走完，还不被权限错误打断。**

`scanner.py` 里留着很多第一人称的注释，写的是当时为什么这么写、哪里错了、后来怎么发现的。那些不删，本来就是这个项目的一部分。

---

## 现在还不行的

- 只认 exe，不认 dll、msi、快捷方式
- 分组只看文件夹，不猜软件类别
- 没有扫描历史，不做前后对比（留给 v1.1）
- 星图对读屏软件不友好，键盘能用但图形本身没有可访问名称
- 没签名

## 许可

还没定。自己用、给朋友用，随便。
