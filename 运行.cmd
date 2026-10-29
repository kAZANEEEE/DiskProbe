@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title DiskProbe 启动器

rem 找 Python：优先 py -3，其次 python
set "PY=py -3"
%PY% -c "import sys" >nul 2>nul
if errorlevel 1 (
    set "PY=python"
    %PY% -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo   [错误] 这台机器上找不到 Python。
        echo   请把 Python 加进 PATH，或手动改这个文件里的 PY 变量。
        pause
        exit /b 1
    )
)

:menu
cls
echo ============================================================
echo    DiskProbe  -  查盘工具
echo ============================================================
echo.
echo    1. 看真实分组数据     扫描 D:\ ，按目录分组，约 3 秒
echo    2. 扫描指定目录       自己输入一个路径
echo    3. 打开星团界面       注意：目前还是写死的假数据
echo    4. 跑验收测试         scanner 四条 + storage 两条
echo    5. 打开项目文件夹
echo.
echo    0. 退出
echo.
set "choice="
set /p "choice=请输入序号后回车: "
if errorlevel 1 exit /b 0

if "%choice%"=="1" goto do_real
if "%choice%"=="2" goto do_custom
if "%choice%"=="3" goto do_gui
if "%choice%"=="4" goto do_test
if "%choice%"=="5" goto do_open
if "%choice%"=="0" exit /b 0
goto menu


:do_real
cls
echo [扫描 D:\ 并按目录分组]
echo ------------------------------------------------------------
%PY% classify.py D:\
echo ------------------------------------------------------------
echo.
pause
goto menu


:do_custom
cls
echo 直接回车 = 扫描 D:\
set "target="
set /p "target=请输入要扫描的目录: "
if "%target%"=="" set "target=D:\"
echo.
echo [扫描 %target% 并按目录分组]
echo ------------------------------------------------------------
%PY% classify.py "%target%"
echo ------------------------------------------------------------
echo.
pause
goto menu


:do_gui
cls
echo [打开星团界面]  关掉窗口就会回到这个菜单
echo.
%PY% prototype.py
if errorlevel 1 (
    echo.
    echo   [如果报 No module named PySide6]
    echo   PySide6 装在系统 Python 3.14 里，不在项目的 .venv 里。
    echo   用 py -3 跑就对了，别用 .venv\Scripts\python.exe。
    echo.
    pause
)
goto menu


:do_test
cls
echo [验收测试]
echo ------------------------------------------------------------
%PY% tests\test_scan_acceptance.py
echo.
%PY% tests\test_storage.py
echo ------------------------------------------------------------
echo.
pause
goto menu


:do_open
start "" "%~dp0"
goto menu
