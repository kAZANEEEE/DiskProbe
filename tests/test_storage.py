# -*- coding: utf-8 -*-
r"""storage.py 验收：两条用例。

一次扫描 = 一次 save_scan。同一批文件扫两次，只能有一行。

用法：
    py -3 tests/test_storage.py
退出码：0 = 全过；1 = 有不过

注意：用临时目录里的库，绝不碰 %LOCALAPPDATA%\DiskProbe\diskprobe.db
"""
import os
import shutil
import sys
import tempfile
import time
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import storage  # noqa: E402


def fake_scan(root, files, started):
    """造一个和 scanner.scan() 同形状的结果字典，不真的去扫盘。"""
    return {
        "schema": 2,
        "root": root,
        "started_at": started,
        "finished_at": started + 1.0,
        "files": [{"path": p, "size": s, "mtime": m} for (p, s, m) in files],
        "skipped": [],
        "complete": True,
        "error": None,
    }


def main():
    tmp = tempfile.mkdtemp(prefix="diskprobe_storage_")
    db = os.path.join(tmp, "test.db")
    failures = 0

    def report(label, problems, ok_note):
        nonlocal failures
        if problems:
            failures += 1
            print(f"  [FAIL] {label}")
            for p in problems:
                print("         !!", p)
        else:
            print(f"  [ OK ] {label} —— {ok_note}")

    print("=" * 64)

    # ① 扫两次同一批文件：不产生重复记录
    try:
        conn = storage.init_db(db)
        t0 = time.time()
        batch = [
            (r"D:\a\main.exe", 4096, t0 - 500),
            (r"D:\a\setup.exe", 8192, t0 - 400),
            (r"D:\a\sub\tool.exe", 2048, t0 - 300),
        ]
        n1 = storage.save_scan(conn, fake_scan(r"D:\a", batch, t0))
        c1 = storage.count_files(conn)

        # 第二次：同样的三个文件，但其中一个大小变、mtime 变
        t1 = t0 + 60
        batch2 = [
            (r"D:\a\main.exe", 4096, t0 - 500),
            (r"D:\a\setup.exe", 9999, t1 - 10),     # 变大了
            (r"D:\a\sub\tool.exe", 2048, t0 - 300),
        ]
        n2 = storage.save_scan(conn, fake_scan(r"D:\a", batch2, t1))
        c2 = storage.count_files(conn)

        problems = []
        if c1 != 3:
            problems.append(f"第一次扫完应有 3 行，实际 {c1}")
        if c2 != 3:
            problems.append(f"第二次扫完仍应有 3 行（不许重复），实际 {c2}")
        if n2 != 3:
            problems.append(f"save_scan 应返回处理的行数 3，实际 {n2}")
        report("① 扫两次同一目录，不产生重复记录", problems,
               f"两次都是 {c2} 行，save_scan 返回 {n2}")
    except Exception:
        failures += 1
        print("  [FAIL] ① 扫两次同一目录 —— 抛异常了")
        traceback.print_exc()
        conn = None

    # ② first_seen 不许被改写，last_scan 必须刷新
    if conn is not None:
        try:
            rows = storage.list_files(conn)
            by_name = {os.path.basename(r["path"]): r for r in rows}
            problems = []
            for row in rows:
                for key in ("path", "name", "size", "mtime", "first_seen", "last_scan"):
                    if key not in row:
                        problems.append(f"list_files 的条目缺 {key}：{row}")
                        break
            setup = by_name.get("setup.exe")
            if setup is None:
                problems.append("setup.exe 没查到")
            else:
                if abs(setup["first_seen"] - t0) > 1.0:
                    problems.append(f"first_seen 被改写了：期望≈{t0:.1f}，实际 {setup['first_seen']}")
                if abs(setup["last_scan"] - t1) > 1.0:
                    problems.append(f"last_scan 没刷新：期望≈{t1:.1f}，实际 {setup['last_scan']}")
                if setup["size"] != 9999:
                    problems.append(f"size 没更新：期望 9999，实际 {setup['size']}")
            report("② first_seen 不变 / last_scan 与 size 更新", problems,
                   "第一次的时间被保留，新数据覆盖了旧的")
        except Exception:
            failures += 1
            print("  [FAIL] ② first_seen / last_scan —— 抛异常了")
            traceback.print_exc()
    else:
        print("  [SKIP] ② 因为 ① 没过，跳过")

    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 64)
    if failures:
        print(f"总结： {failures} 条没过")
        return 1
    print("总结： 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
