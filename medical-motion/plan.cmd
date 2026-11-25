@echo off
setlocal
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if exist "%PYTHON%" goto run
set "PYTHON=python"
:run
"%PYTHON%" "%~dp0plan.py" %*
exit /b %errorlevel%
