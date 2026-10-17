###########这里是后端程序###########
#首先这个程序需要有至少四个功能
"""
1.生成一个指定大小的随机数据，确保每次写入的数据不一样，防止操作系统与U盘主控进行重复数据的压缩
2.写入测试数据(在目标盘符)，记录写入耗时，计算写入速度MB/S，同步计算写入数据的MD5哈希值
3.读取测试数据，记录读取耗时，计算读取速度，检验哈希是否正确
4.清理缓存，进行错误处理，并且无论测试成功还是失败，都要能自动清理文件
"""
import os
from os import write
from random import random

"""
我的本意是想使用random模块来进行随机数据的写入，但是了解到random是伪随机，也就是有规律可循的随机？？这里我不太确定
os库里有一个函数，是专门来解决这个问题的，也就是os.urandom(xxx),x为要写入的大小，也可以是数字变量，我猜？
单位应该是字节,1MB也就是1024*1024????因为1kB等于1024B
B是什么单位来着？字节？是Byte吗？？？
"""
"""
先写一个函数让获取用户想要生成的指定文件的大小
"""
def get_size():
    file_size = int(input("请输入生成的指定数据的大小,最小单位可取0.1MB，精确度为0.1MB"))
    file_path= input("文件的测试位置")
    return file_size,file_path
def generate_data(base_file):
    get_size()#获取要生成的指定数据的大小
    minimun_data=1024*1024/10
    file_size,file_path = get_size()
    print(f"正在准备{file_size}MB的测试文件,即将写入{file_path}")
    try:
        with open(base_file+"/test.bin","wb") as file:
            for i  in range(file_size):
                random_data=os.urandom(minimun_data)
                file.write(random_data)
                if i % 10 == 0:
                    print(f"已写入{i+1}MB")
                file.flush()
                """这一句的意思。我猜是刷新文件状态，确保已经写入"""
                print("已完成写入")
        os.fsync(file)
        """
         s.fsync(file)会让内核把数据真正的从物理层写入盘中，并且等待它完成
         file.flush()则是把python自己的缓冲区推给生态区？生态区是什么？
         不管怎么说，我认为os.fsync(file)才是衡量盘性能标准的，而且确实应该写入完成后再一次执行这个代码
        """

    except Exception as e:
        print(f"写入失败，出现错误,错误码为:{e}")
        raise"""这句话的意思说是抛给UI层去处理？？？不太理解"""
    finally:
        if os.path.exists(base_file):
            os.remove(base_file)
            """直接自动补全，美滋滋"""



