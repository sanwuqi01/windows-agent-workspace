@echo off
rem ============================================================
rem  dsh-worker.cmd -- run one one-shot DSH agent task and exit.
rem
rem  Usage (local Windows, or over SSH from another machine):
rem    dsh-worker.cmd "rename the 12 shots to jing01..jing12"
rem    echo TASK TEXT | dsh-worker.cmd -
rem    dsh-worker.cmd --json "TASK"            machine-readable event stream
rem    dsh-worker.cmd --session-id s-abc "continue the previous task"
rem
rem  Implementation (credentials, profile, patch overlay) lives in
rem  dsh-worker.ps1 next to this file. Keep THIS file ASCII-only:
rem  cmd.exe decodes .cmd in the OEM codepage, so UTF-8 Chinese here
rem  would be mangled into broken commands.
rem ============================================================
setlocal DisableDelayedExpansion
set "SCRIPT=%~dp0dsh-worker.ps1"
powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %errorlevel%
