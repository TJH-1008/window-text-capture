@echo off
rem 源码方式启动（需要 Python 3.10+ 与 pillow）
setlocal
cd /d "%~dp0"
python app.py %*
