# DiskProbe · 软件星团

扫一个目录，把它里面所有 `.exe` 找出来，按**所在目录**分组，用一个星系图显示。

![开场](assets/海报_产品介绍.png)

---

## 这是什么

一个 Windows 桌面小工具。你盘里装了些什么、散在哪、各占多少——它用一张图回答。

写它的动机很朴素：**想看看自己盘里到底有什么东西**。资源管理器能按大小排序，但它不会告诉你「这 1010 个 exe 分成了 29 堆，最大的一堆是 Visual Studio 拖来的」。

- 平台：Windows 10 / 11
- 技术栈：Python 3.10+ / PySide6 / QPainter 自绘 / SQLite
- 版本：v0.1

---

## 直接运行（需要 Python）

```powershell
py -3 -m pip install PySide6-Essentials
py -3 ui.py
```

## 直接运行（打包好的 exe）

去 [Releases](https://github.com/kAZANEEEE/DiskProbe/releases) 下 `DiskProbe.exe`，双击。

> 未签名的 exe，Windows SmartScreen 会拦一次：点「更多信息」→「仍要运行」。

---

## 怎么用

1. 打开，等开场动画播完
2. 点右下角 **选择目录以开始扫描**，选一个文件夹（别选 `C:\`，慢）
3. 看着星星一颗颗飞进来——**一颗星 = 一个 exe**，不是装饰
4. 扫完之后，星图按目录分成若干条旋臂

| 操作 | 效果 |
|---|---|
| 滚轮 | 缩放（0.65×–1.6×） |
| 双击空白 | 复位视角 |
| 拖动空白 | 旋转 / 上下拖改倾角 |
| 悬停一条臂 | 该组浮起，其余压暗 |
| 点击一条臂 | 锁定，**相机转向它** |
| `Esc` | 取消选中 |
| `←` `→` | 在分组之间切换 |
| 查看全部 N 个 → | 弹出该组完整文件列表 |
| 搜索框 | 按路径过滤，命中的星亮、其余压暗 |

点侧栏没做的项（软件库 / 历史记录 / 分类管理 / 设置），**那个按钮会当场碎掉**，然后飘一句「老子还没做」。这是故意的。

点「插件中心」有一个彩蛋。

---

## 口径（重要）

- **一条旋臂 = 一个目录**。臂的长度和粗细按该组 EXE 数量决定。
- **一颗星 = 一个 EXE 文件**。扫描时逐颗出现，数量是真的。
- **总大小**只统计 EXE 本身，不含同目录下的其他文件。
- **分组依据是目录，不是软件类别**。判断「这是游戏还是开发工具」需要读 EXE 内部信息，那属于推断——宁可先说不知道。
- 扫描不完整时（回收站、`System Volume Information` 这类普通权限进不去的目录），界面上会明确写出数量，不会假装扫全了。

---

## 数据存哪

```
%LOCALAPPDATA%\DiskProbe\diskprobe.db
```

一个 SQLite 文件。删掉不影响任何原始文件，只是下次要重扫。

---

## 打包

```powershell
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --noconfirm --windowed --onefile ^
    --name DiskProbe ^
    --icon assets/logo.ico ^
    --add-data "assets;assets" ^
    --add-data "彩蛋.md;." ^
    ui.py
```

产物在 `dist\DiskProbe.exe`。

> **`--windowed` 的坑**：打包后 `sys.stdout` 是 `None`，任何 `print()` 都会崩。
> 这个项目的运行路径里一行 `print` 都没有，所以安全；以后加调试输出要记得。

---

## 项目结构

```
查盘工具/
├─ ui.py            界面（主窗口 / 星图画布 / 各种面板）
├─ scanner.py       扫描器：os.scandir 递归，带 on_file 回调
├─ storage.py       SQLite 存取
├─ classify.py      分组：按目录；读 EXE 自带厂商信息
├─ assets/          logo、海报、设置说明
├─ tests/           验收测试（纯脚本，不需要 pytest）
├─ 踩坑记录.md      21+ 条真实踩过的坑
├─ 术语对照.md      所有英文标识符的中文对照
├─ 交互叙事闭环.md  动效系统规格
└─ 彩蛋.md
```

## 跑测试

```powershell
py -3 tests\test_scan_acceptance.py
py -3 tests\test_storage.py
```

两个都是普通脚本，看到「总结： 全过」就是好的。**不需要 pytest。**

---

## 它的来历

这个东西是从一个更小的问题长出来的：**怎么在 Python 里把一棵目录树走完，还不被权限错误打断。**

`scanner.py` 里留着大量第一人称的批注，记录的是当时为什么这么写、错在哪。那些注释不打算删——它们是这个项目的一部分。

---

## 已知限制

- 只认 `.exe`，不认 `.dll` / `.msi` / 快捷方式
- 分组只按目录，不判断软件类别
- 不做扫描历史、不做变化比较（留给后续版本）
- 星图对读屏软件不可见；键盘可以用 `←` `→` `Esc`，但图形本身没有可访问名称
- 没有代码签名

## 许可

还没定。暂时：自己用、给朋友用，随便。
