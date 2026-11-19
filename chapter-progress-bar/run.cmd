@echo off
rem 一条命令入口（Windows）。参数与 python chapter_bar.py 完全一致。
rem 解释器优先级：CHAPTERBAR_PYTHON 环境变量 > DSH 内置 Python（含 Pillow）> PATH 里的 python
setlocal
set "PY=%CHAPTERBAR_PYTHON%"
if not defined PY set "PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-next-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0chapter_bar.py" %*
exit /b %ERRORLEVEL%
