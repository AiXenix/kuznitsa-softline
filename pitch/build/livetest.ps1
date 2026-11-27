# Проверка живого режима: локальный сервер + пересылка запросов на стенд, снимки нужных слайдов
param([string]$Steps = '3.0,3.1,3.2,3.3,5.2,6.0,6.1', [string]$Out = 'shots-live', [string]$Acts = '')
$B = Split-Path -Parent $MyInvocation.MyCommand.Path
node "$B\build.js"
if (-not $?) { exit 1 }
$srv = Start-Process node -ArgumentList "`"$B\serve.js`"", '47631' -PassThru -WindowStyle Hidden -RedirectStandardOutput "$B\serve.log" -RedirectStandardError "$B\serve.err"
Start-Sleep -Seconds 2
try {
  $h = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:47631/health' -TimeoutSec 20
  "health через пересылку: $($h.StatusCode)"
  $a = @("$B\shot.js", '--url', 'http://127.0.0.1:47631/web/pitch/index.html', '--out', "$B\$Out", '--steps', $Steps, '--wait', '2600')
  if ($Acts) { $a += @('--acts', "$B\$Acts") }
  node @a
} finally {
  Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue
  Get-Content "$B\serve.err" -ErrorAction SilentlyContinue | Select-Object -First 10
}
