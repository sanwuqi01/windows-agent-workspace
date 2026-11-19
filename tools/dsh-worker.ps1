# dsh-worker.ps1 —— 一次性 DSH agent 执行器（Codex / 脚本 / CI 调用入口）
#
# 用法：
#   dsh-worker.ps1 "任务描述"
#   "任务描述" | dsh-worker.ps1 -            # 从 stdin 读任务
#   dsh-worker.ps1 --json "任务"             # 输出机器可读事件流
#   dsh-worker.ps1 --session-id s-abc "继续" # 接续同一会话
#
# 返回：任务答案走 stdout，诊断走 stderr，退出码透传 CLI。
#
# 模型凭据：从 $DSH_HOME\.credentials.yaml 的 refs 段就地读出，注入子进程环境变量，
# 不落任何新文件、不打印。

$ErrorActionPreference = 'Stop'

$dshHome   = 'C:\Users\Administrator\.dsh'
$dshExe    = 'D:\DSH NEXT\DSH NEXT.exe'
$dshBoot   = 'D:\DSH NEXT\resources\app.asar\lib\desktop-cli.js'
$patchFile = 'F:\agent\tools\worker.patch.yml'

# --- 凭据：优先环境变量，否则从 credentials.yaml 的 refs 段读 ---
if (-not $env:DEEPSEEK_API_KEY) {
  $cred = Join-Path $dshHome '.credentials.yaml'
  if (Test-Path -LiteralPath $cred) {
    foreach ($line in (Get-Content -LiteralPath $cred)) {
      if ($line -match '^\s*DEEPSEEK_API_KEY\s*:\s*(\S+)\s*$') {
        $env:DEEPSEEK_API_KEY = $Matches[1]
        break
      }
    }
  }
}
if (-not $env:DEEPSEEK_API_KEY) {
  [Console]::Error.WriteLine('dsh-worker: 未找到模型凭据（环境变量 DEEPSEEK_API_KEY，或 credentials.yaml 的 refs 段）')
  exit 2
}

$env:ELECTRON_RUN_AS_NODE = '1'
$env:DSH_HOME = $dshHome

# $args 原样收集全部参数，避免 --json / --session-id 被 PowerShell 当自己的参数吞掉
# 注意：PowerShell 不接受裸 "-"（会报 name 参数非法），所以包装层用 --stdin 代替，
# 到这里再翻回 CLI 认识的 "-"（含义：任务文本从 stdin 读）。
$taskArgs = foreach ($a in $args) { if ($a -in '-', '--stdin') { '-' } else { $a } }

$cliArgs = @('--expose-internals', $dshBoot, '--profile', 'headless', '--patch', $patchFile, '--approval-policy', 'never') + @($taskArgs)

& $dshExe @cliArgs
exit $LASTEXITCODE
