# -*- coding: utf-8 -*-
"""scanner.scan() 验收：四条用例。

自带临时测试目录，不依赖任何本地草稿，clone 下来就能跑。

用法：
    python tests/test_scan_acceptance.py
退出码：0 = 全过；1 = 有不过（可直接接 CI）
"""
import os
import shutil
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import scanner  # noqa: E402

KEYS = {"schema", "root", "started_at", "finished_at",
        "files", "skipped", "complete", "error"}
FILE_KEYS = {"path", "size", "mtime"}
SKIP_KEYS = {"path", "kind", "reason"}
NO_PERM = r"C:\Windows\System32\config"  # 普通用户读不进去的目录（验收第 4 条用）


def build_fixture():
    """造一棵答案已知的小目录树。

        根/            a.exe  b.txt  BIG.EXE
        根/sub1/       c.exe
        根/sub1/sub2/  d.exe  e.txt

    期望扫到 4 个 exe：a.exe、BIG.EXE（大小写混写）、sub1/c.exe、sub1/sub2/d.exe
    """
    root = tempfile.mkdtemp(prefix="diskprobe_fixture_")
    sub1 = os.path.join(root, "sub1")
    sub2 = os.path.join(sub1, "sub2")
    os.makedirs(sub2)
    for rel in ("a.exe", "b.txt", "BIG.EXE",
                os.path.join("sub1", "c.exe"),
                os.path.join("sub1", "sub2", "d.exe"),
                os.path.join("sub1", "sub2", "e.txt")):
        with open(os.path.join(root, rel), "w", encoding="utf-8"):
            pass
    return root


def check_shape(label, result):
    """所有返回都必须是同一个八字段字典，且 files / skipped 的条目形状固定。"""
    problems = []
    if not isinstance(result, dict):
        problems.append(f"返回的不是 dict，而是 {type(result).__name__}: {result!r}")
        return problems
    if set(result) != KEYS:
        problems.append(f"字段不对：缺/多 -> {sorted(set(result) ^ KEYS)}")
    if not isinstance(result.get("complete"), bool):
        problems.append(f"complete 必须是布尔，实际 {result.get('complete')!r}（{type(result.get('complete')).__name__}）")
    for f in result.get("files") or []:
        if not isinstance(f, dict) or set(f) != FILE_KEYS:
            problems.append(f"files 的条目必须是 {sorted(FILE_KEYS)} 的字典，实际 {f!r}")
            break
        if not isinstance(f["size"], int):
            problems.append(f"size 必须是 int，实际 {f['size']!r}")
            break
    for s in result.get("skipped") or []:
        if not isinstance(s, dict) or set(s) != SKIP_KEYS:
            problems.append(f"skipped 的条目必须是 {sorted(SKIP_KEYS)} 的字典，实际 {s!r}")
            break
    return problems


def main():
    fixture = build_fixture()
    expect = {"a.exe", "BIG.EXE", "c.exe", "d.exe"}
    failures = 0

    def report(label, problems, passed_note):
        nonlocal failures
        if problems:
            failures += 1
            print(f"  [FAIL] {label}")
            for p in problems:
                print("         !!", p)
        else:
            print(f"  [ OK ] {label} —— {passed_note}")

    print("=" * 64)

    # ① 正常目录
    try:
        r = scanner.scan(fixture)
        problems = check_shape("①", r)
        if not problems:
            got = {os.path.basename(f["path"]).lower() for f in r["files"]}
            if got != {e.lower() for e in expect}:
                problems.append(f"扫到的 exe 不对：期望 {sorted(expect)}，实际 {sorted(got)}")
            if r["complete"] is not True:
                problems.append("complete 应为 True")
            if r["error"] is not None:
                problems.append(f"error 应为 None，实际 {r['error']!r}")
        report("① 正常目录（4 条 exe，含大小写混写）", problems, f"{len(expect)} 条 exe 全抓到")
    except Exception:
        failures += 1
        print("  [FAIL] ① 正常目录 —— 抛异常了")
        traceback.print_exc()

    # ② 不存在的路径
    try:
        bad = os.path.join(tempfile.gettempdir(), "diskprobe_definitely_not_here_98765")
        r = scanner.scan(bad)
        problems = check_shape("②", r)
        if not problems:
            if r["complete"] is not False:
                problems.append("complete 应为 False")
            if not r["error"]:
                problems.append("error 应写一句人话，现在是空的")
            if r["files"]:
                problems.append(f"files 应为空，实际 {r['files']}")
        report("② 不存在的路径（不崩、返回 error 字典）", problems, "返回字典，complete=False")
    except Exception:
        failures += 1
        print("  [FAIL] ② 不存在的路径 —— 抛异常了")
        traceback.print_exc()

    # ③ 传的是文件，不是目录
    try:
        r = scanner.scan(os.path.join(fixture, "a.exe"))
        problems = check_shape("③", r)
        if not problems:
            if r["complete"] is not False:
                problems.append("complete 应为 False")
            if not r["error"]:
                problems.append("error 应写一句人话，现在是空的")
        report("③ 传的是文件（isdir 为 False）", problems, "返回字典，complete=False")
    except Exception:
        failures += 1
        print("  [FAIL] ③ 传的是文件 —— 抛异常了")
        traceback.print_exc()

    # ④ 无权限目录
    if not os.path.isdir(NO_PERM):
        print("  [SKIP] ④ 无权限目录 —— 本机没有这个目录，跳过")
    else:
        try:
            r = scanner.scan(NO_PERM)
            problems = check_shape("④", r)
            if not problems:
                if r["skipped"]:
                    if r["complete"] is not False:
                        problems.append("记了 skipped，complete 就该是 False")
                else:
                    print("  [SKIP] ④ 无权限目录 —— 本机居然读得进去（管理员？），跳过")
                    problems = None
            if problems is not None:
                note = "权限异常已记进 skipped，complete=False" if not problems else ""
                report("④ 无权限目录", problems, note)
        except Exception:
            failures += 1
            print("  [FAIL] ④ 无权限目录 —— 抛异常了（PermissionError 该被吃掉）")
            traceback.print_exc()

    shutil.rmtree(fixture, ignore_errors=True)

    print("=" * 64)
    if failures:
        print(f"总结： {failures} 条没过")
        return 1
    print("总结： 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
