r"""
现在是2026.10.27.23:13分
我确信我已经提前完成了第九周的任务，接下来就提前进入第十周(11/2----11/8)吧
scanner.py人如其名是个扫描器，storage.py也人如其名，用来保存scanner.py那些产出的字典
这就是数据库，将那些字典变成数据库里能查的行，不做扫描，不做界面
作为一个数据库，他应该具有以下功能
1.返回 %LOCALAPPDATA%\DiskProbe\diskprobe.db
翻译成人话就是返回一个路径指向当前用户的应用数据目录
2.建立数据库
3.将字典保存进入数据库
4.列出数据库里的文件
5.返回数据库里有多少行
"""
import os
import sqlite3
import time

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS files (
    path_key    TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    name        TEXT NOT NULL,
    size        INTEGER,
    mtime       REAL,
    first_seen  REAL,
    last_scan   REAL
)
"""
#################
UPSERT_SQL = """
INSERT INTO files (path_key, path, name, size, mtime, first_seen, last_scan)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (path_key) DO UPDATE SET
    size       = excluded.size,
    mtime      = excluded.mtime,
    last_scan  = excluded.last_scan
"""
r"""default_db_path()      返回 %LOCALAPPDATA%\DiskProbe\diskprobe.db
init_db(path)          建目录、连库、建表、返回连接
save_scan(conn, res)   写库，返回行数
list_files(conn)       查询，每条要带 path/name/size/mtime/first_seen/last_scan 六个键
count_files(conn)      返回行数
我尼玛......早知道好好听听数据库了，我现在狗叼不会啊，FUCKKKK"""
def default_db_path():
    """os.environ.get("LOCALAPPDATA")#####获取环境变量，并且返回字符串
    os.path.expanduser("~")得到的是用户主目录"""
    base=os.environ.get("LOCALAPPDATA")
    return os.path.join(base, "DiskProbe", "diskprobe.db")
def init_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(TABLE_SQL)
    conn.row_factory=sqlite3.Row
    return conn
def save_scan(conn, result):
    # 时间不另取时钟，直接用 scan() 记下的 finished_at：
    # 这样数据库里的时间和扫描日志对得上，也才测得出来（另取 time.time() 会盖掉测试喂进来的时间）
    now_time = result.get("finished_at") or time.time()
    files = result["files"]
    with conn:                      # 事务：要么全进，要么全不进
        for f in files:
            path_key = os.path.normcase(os.path.abspath(f["path"]))
            name = os.path.basename(f["path"])
            conn.execute(UPSERT_SQL, (
                path_key,
                f["path"],          # 原始大小写，给界面显示用
                name,
                f["size"],
                f["mtime"],
                now_time,           # first_seen：只有第一次插入时才写进去
                now_time,           # last_scan：每次都会被刷新
            ))
    return len(files)

def list_files(conn, keyword=None):
    """查出来给界面用。不传 keyword 就列全部，传了按文件名模糊搜。"""
    cur = conn.cursor()
    if keyword:
        cur.execute(
            "SELECT path, name, size, mtime, first_seen, last_scan FROM files "
            "WHERE name LIKE ? ORDER BY name",
            (f"%{keyword}%",),
        )
    else:
        cur.execute(
            "SELECT path, name, size, mtime, first_seen, last_scan FROM files ORDER BY name"
        )
    return [dict(row) for row in cur.fetchall()]


def count_files(conn):
    """表里现在有多少行。验收就靠它：扫两次前后各数一遍。"""
    return conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
if __name__ == "__main__":
    print(default_db_path())
    ########################
    p=os.path.join(os.environ["TEMP"], "dp_test.db")
    conn=init_db(p)
    print("库建好了吗：",os.path.exists(p))