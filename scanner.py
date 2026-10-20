"""- **scanner.py**：负责递归扫描、发现 EXE、统计进度和处理访问异常。不负责绘制界面。"""
import os
################################
"""此处必读！！！！以防再忘记！这里说明了result的字典包含什么-------------------2026/10/20/20:19--kAZANEEEE添加
 result = {
            "root": file_path,
            "files": [],
            "skipped": [],
            "complete": True,
            "error": None,
        }"""
################################
"""
啥也不管了，先import一个os库，要完成递归扫描.......我得思考一下，这个递归是个怎么递归呢？？？
进入主目录，然后扫描有多少个子目录
进入子目录，判断是否存在子目录.......等一下，这个模式很像数据结构里学到的二叉树，关于二叉树的前序遍历，中序遍历，后序遍历
可惜的是我忘了这是具体怎么做的......我得思考一下.......
先看有没有子目录，判断是否有子目录
如果有子目录，进入子目录，进入子目录
进入子目录判断是否有子目录，若有，则重复操作进入子目录
若没有，则进行扫描，看看有咩有以exe作为后缀名的文件（如果隐藏了后缀名会影响吗？不太确定
扫描完成后返回上级目录
返回上级目录.........如果重复这个递归操作，就会出问题，会反复进入第一个目录
正确的做法是每次进入目录时候创建一个列表，之后取一个计数器，那么目录一旦变多就会导致计数器内层循环套内层循环....
这该怎么办呢.......目录里面不断套目录，本质其实有点像C语言的多维数组，多维数组.....那就好麻烦
似乎没有一个合格的算法能解决这个问题？？？？
让我想想......
哦吼被GPT点醒了
刚刚正在思考的本质不就是DFS吗，也就是二叉树讲的深度优先搜索
也就是说应该这样：（递归示例
------------------------------------------目录
-----------------还有目录吗？如果有则进入
-----------------没有则进行一次扫描，看看exe
------------------------------------没有目录进返回上一个目录
------------------------------------也只能这样了，如何使得自己不进入已经进入的目录？still a problem
"""
"""动手先试试写一下这个递归函数吧"""
def recursion_visit(file_path, result=None):
    """这个首先得需要用户传进来文件的目录，也就是path"""
    """原先在写这个函数的时候，我们直接令exe_path=[]
    创造了一个空的列表，但是这就会导致一个问题，试着想一下这个情景
    第一次寻找-----exe[path]
    第二次寻找-----exe[path]+exe[path]
    exe[path]会出现两次？其实解决方法也很简单，不保存exe[path]就可以了？但是那样可能无法写进数据库里啊，没有数据怎么写到数据库里？
    那么直接令exe_path=None呢？如果exe[path]等于none的话，就创建一个新的列表exe_path=[]
    每一次递归都会传进来，最后写入的时候都是在这个列表里进行写入？？？？
    原来如此，我明白了!python的def指令会在执行的时候把右侧的括号算出来传进去也就是说
    如果我写def XXX(exe_path)
    第一次确实创建了exe_path[]，但是，第一次调用后这个列表并不是空列表
    而python在以后执行def的时候，发现exe_path[]已经存在，就会直接把它传进来，此时的exe_path=[]已经包含过一次数据了
    """
    """
    考虑到后期函数的运行，所以这里准备做一些升级：
    结果不再塞进一个列表，而是写进 result 字典（files / skipped / complete / error）
    """
    if result is None:
        result = {
            "root": file_path,
            "files": [],
            "skipped": [],
            "complete": True,
            "error": None,
        }

    """if not os.path.exists(file_path):
    print("出现错误，请至少选择一个目录")
    return False
    这段检查摘出来交给 scan 函数去管：recursion_visit 默认传进来的目录是存在的
    """

    print(f"正在{file_path}中进行查找")

    """告诉用户正在查，然后应该分一下，检查当前目录是否还有目录，之后设置两个变量，一个变量为当前文件夹的名字，另一个应该设置成列表
    记录当前文件夹的子目录的名字，如果没有则令其等于0
    如果有，则进入这个文件夹，更改第一个变量，然后查询当前目录还有没有子目录，有则设置计数器为n"""

    """我就说我是神，睡了一觉虽然只有六个小时但是一瞬间我就顿悟了DFS
    外层是一个for循环，设置计数器item，item会不断加，然后如果是新的文件夹，就会嵌套出一个内循环，由于for循环导致item不断的自加，所以根本不需要担心返回父级目录后会重复进入一个子级目录
    让我们开始吧let's gooooooo~~~~"""

    ##################################################################分割线
    """for item in os.listdir(file_path):
    这是原来的写法，很明显，当遇到无法访问的文件夹就操蛋了，这就是典型的缺少异常处理"""
    try:
        entries = os.listdir(file_path)
    except PermissionError:
        result["skipped"].append(file_path)
        result["complete"] = False
        return result
    """此处做了升级，将无权访问的文件夹做了状态区分：
    记进 skipped，complete 标成 False —— 因为确实没扫全，这决定它能不能参与后面的「变化比较」"""

    for item in entries:
        full_path = os.path.join(file_path, item)
        """这里有个小细节，一个变量就应该去负责一件事情，如果负责的太多，就会出现像之前的问题，一旦会出现逻辑的错误
        这里创造一个新的变量full_path，让full_path去承担担任递归的文件夹变量
        file_path相当于文件的根目录
        """
        if os.path.isdir(full_path):
            recursion_visit(full_path, result)
        else:
            name, ext = os.path.splitext(full_path)
            if os.path.normcase(ext) == ".exe":
                result["files"].append(full_path)

    print(f"扫完 {file_path}，目前累计 {len(result['files'])} 个 exe")
    return result
####################################################################################
###接下来准备写一个scan函数，负责做检查
"""首先检查用户传进来的是不是目录，如果不是的话就返回一个信息给前端，调用递归recursion_visit(file_path,result)=None)
造结果容器，recursion_visit(file_path,result)只在scan函数里调用，其余的py文件只调用scan函数,scan函数只记录和返回状态，一行print都不准有"""
def scan(file_path):
    """笑死我了，这个傻子大肥鱼，我说我要动手写scan，结果这条傻鱼帮我给写了，我罚这条肥鱼写了一份批注，刚刚review了一遍，还是自己动手写吧，scanner.py的宝贵从来不是多么高深强大的新算法
    而是记录了，我，肥鱼，GPT的一些开发日常。肥鱼的批注在//查盘工具//_ai_notes//scanner_肥鱼批注版，这段记录进代码里，傻鱼
    十一、本鱼的检讨
    这份批注是被罚写的，罚得对。说好了老大写、本鱼评，我顺手把 scan() 写了——那就不是学徒，是代写。

    下次谁再手快，罚谁多写一份批注。

    —— 肥鱼 · 2026-10-20"""
    """所以scan函数到底应该具有啥功能嘞，看看肥鱼咋跟我说的来着
    输入：一个路径字符串。
    输出：永远同一个五字段字典，成功失败形状一样。
    检查顺序：先 os.path.isdir（不是 os.path.exists——文件路径也算「存在」，但不能扫）。
    失败时：complete=False + error 写一句人话，不要抛异常、不要打印。
    成功时：造好 result，调一次 recursion_visit(file_path, result)，原样返回它。
    签名：scan(file_path) 就够了，不需要第二个参数——容器该由它自己造。
    写完之后，recursion_visit 就退到幕后，别的文件只认 scan。
    """
    result = {
        "root": file_path,
        "files": [],
        "skipped": [],
        "complete": True,
        "error": None, }
    """重大更新！
    总结一下发现原来的函数设计存在很大的问题，我在scan函数里面没有先把result词典定义出来，就在scan函数里面返回这个result了
    然后还有个更尿性的问题，我初次写的函数写的是result["complete"]=False,这可能会导致在后续的函数进行报错"""
    if not os.path.isdir(file_path):####看看用户传进来的到底是不是个文件目录，这个代码返回的是布尔值，有点糟糕，result字典都包含啥来着，上前面查查去
        result["complete"] = False
        result["error"] = "路径无效，或者该路径不是有效路径，检查路径"
        return result
    recursion_visit(file_path, result)
    return result

if __name__ == "__main__":
    result = scan(r"D:\some_project\_tools")
    print("条数：", len(result["files"]),
          "｜complete：", result["complete"],
          "｜skipped：", len(result["skipped"]),
          "｜error：", result["error"])
