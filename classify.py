# -*- coding: utf-8 -*-
"""DiskProbe 分组：从 EXE 自己身上读身份，读不到就用目录兜底。

为什么要有这个文件（肥鱼 2026-10-29 写）——
    星团要把 1010 个 EXE 分成几团，就必须先回答"按什么分"。
    猜用途（这是游戏？是开发工具？）会错，所以不猜。

    但有两样东西不是猜，是读出来的事实：
      L1 厂商 —— EXE 文件里自带一个版本资源，里面有 CompanyName（厂商名）。
                 这是文件自己声明的，不是我们推断的。D 盘实测 22.9% 有。
      L2 目录 —— 文件路径的前两级。100% 有，而且目录名是用户自己起的。

    所以默认按 L2 分组（覆盖全），悬停时显示 L1（有就显示）。
    用途分类属于第三层"推断"，V1.1 再说，而且要明确标注是推断。

读厂商靠的是 Windows 自带的 version.dll，用 ctypes 调，不装任何第三方库。
"""
import ctypes
import ctypes.wintypes as wt
import os

# ---------------------------------------------------------------- Win32 版本资源

_ver = ctypes.WinDLL("version", use_last_error=True)

_ver.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.DWORD)]
_ver.GetFileVersionInfoSizeW.restype = wt.DWORD
_ver.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
_ver.GetFileVersionInfoW.restype = wt.BOOL
_ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR,
                                ctypes.POINTER(ctypes.c_void_p),
                                ctypes.POINTER(wt.UINT)]
_ver.VerQueryValueW.restype = wt.BOOL

# 要取的三个字段。查的是英文语言块 040904b0（美式英语 + Unicode）
_WANTED = ("CompanyName", "ProductName", "FileDescription")


def read_version(path):
    """读一个 EXE 的 (厂商, 产品名, 描述)。读不到就返回三个空串，绝不抛异常。

    慢的话不是这里的错：冷缓存 + 杀软实时扫描会让第一次跑得很慢，
    同一批文件第二次跑，D 盘 1010 个只要 0.3 秒。
    """
    try:
        size = _ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return "", "", ""
        buf = ctypes.create_string_buffer(size)
        if not _ver.GetFileVersionInfoW(path, 0, size, buf):
            return "", "", ""
        out = []
        for key in _WANTED:
            val = ""
            ptr = ctypes.c_void_p()
            length = wt.UINT()
            sub = "\\StringFileInfo\\040904b0\\" + key
            if _ver.VerQueryValueW(buf, sub, ctypes.byref(ptr),
                                   ctypes.byref(length)) and length.value:
                val = ctypes.wstring_at(ptr.value, length.value).rstrip("\x00")
            out.append(val)
        return tuple(out)
    except OSError:
        return "", "", ""


# ---------------------------------------------------------------- 分组

def dir_key(path):
    """取"盘符 + 第一级目录"当分组名。

        D:\\STEAM\\steamapps\\common\\x.exe   ->  D:\\STEAM
        D:\\some_project\\_tools\\y.exe       ->  D:\\some_project
        D:\\z.exe                             ->  D:\\（根目录）
    """
    drive, rest = os.path.splitdrive(path)
    rest = rest.lstrip("\\/")
    if not rest:
        return drive + "\\（根目录）"
    first = rest.split("\\", 1)[0]
    if "\\" not in rest:
        return drive + "\\（根目录）"
    return drive + "\\" + first


def build_groups(files, key_func=dir_key):
    """把 scan() 的 files 列表按 key_func 分堆，按文件数从多到少排。

    返回：[{"key": 分组名, "count": 个数, "size": 总字节, "files": [记录...]}, ...]
    """
    buckets = {}
    for rec in files:
        k = key_func(rec["path"])
        g = buckets.setdefault(k, {"key": k, "count": 0, "size": 0, "files": []})
        g["count"] += 1
        g["size"] += rec.get("size") or 0
        g["files"].append(rec)
    groups = list(buckets.values())
    groups.sort(key=lambda g: -g["count"])
    return groups


# ---------------------------------------------------------------- 命令行自检

if __name__ == "__main__":
    import sys
    import time

    # 控制台默认是 GBK，直接打印「百度网盘」这类路径会报 UnicodeEncodeError。
    # 这两行让输出强制走 UTF-8，不管在哪个终端里跑都不炸。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = sys.argv[1] if len(sys.argv) > 1 else "D:\\"
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import scanner

    print("扫描 %s ..." % root)
    result = scanner.scan(root)
    total = len(result["files"])
    print("扫到 %d 个 EXE，耗时 %.1f 秒，complete=%s，跳过 %d 项" % (
        total, result["finished_at"] - result["started_at"],
        result["complete"], len(result["skipped"])))

    groups = build_groups(result["files"])
    print()
    print("按目录分组：%d 组" % len(groups))
    print("%6s  %10s  %s" % ("个数", "大小MB", "分组"))
    for g in groups[:20]:
        print("%6d  %10.1f  %s" % (g["count"], g["size"] / 1048576, g["key"]))

    print()
    print("抽 6 个读厂商（这一步慢，只抽样）...")
    t0 = time.perf_counter()
    for g in groups[:3]:
        for rec in g["files"][:2]:
            company, product, desc = read_version(rec["path"])
            print("  %-26s | %-22s | %s" % (
                os.path.basename(rec["path"])[:26], company[:22] or "(无)", product[:24]))
    print("  6 个文件用了 %.2f 秒" % (time.perf_counter() - t0))
