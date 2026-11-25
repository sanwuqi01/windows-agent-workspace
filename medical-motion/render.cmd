@echo off
setlocal
set "NODE=%USERPROFILE%\.dsh\dsh-runtimes\dsh-next-primary-runtime\dependencies\node\bin\node.exe"
if exist "%NODE%" goto run
set "NODE=node"
:run
"%NODE%" --experimental-strip-types "%~dp0render.mjs" %*
exit /b %errorlevel%
