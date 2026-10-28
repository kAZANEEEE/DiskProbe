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
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS files (
    path_key    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    size        INTEGER,
    mtime       REAL,
    first_scan  REAL,
    last_scan  REAL
)
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
if __name__ == "__main__":
    print(default_db_path())
    ########################
    p=os.path.join(os.environ["TEMP"], "dp_test.db")
    conn=init_db(p)
    print("库建好了吗：",os.path.exists(p))