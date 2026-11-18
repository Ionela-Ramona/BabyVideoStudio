# Usage: .\masoara.ps1 <blender args...>   (log: masoara.log langa script)
$blender = 'D:\Tools\Blender\blender-4.5.16-windows-x64\blender.exe'
$log = Join-Path $PSScriptRoot 'masoara.log'
$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process $blender -ArgumentList $args -PassThru -NoNewWindow -RedirectStandardOutput $log -RedirectStandardError "$log.err"
$null = $p.Handle; $ws = 0; $pv = 0
while (-not $p.HasExited) {
    $p.Refresh()
    if ($p.WorkingSet64 -gt $ws) { $ws = $p.WorkingSet64 }
    if ($p.PrivateMemorySize64 -gt $pv) { $pv = $p.PrivateMemorySize64 }
    Start-Sleep -Milliseconds 200
}
$p.WaitForExit()
"Wall: {0:N1} s | Peak WS: {1:N0} MB | Peak Private: {2:N0} MB | Exit: {3}" -f $sw.Elapsed.TotalSeconds, ($ws/1MB), ($pv/1MB), $p.ExitCode
Select-String -Path $log -Pattern 'Mem:|Peak|Time:' | ForEach-Object { $_.Line }
if ((Get-Item "$log.err").Length) { "STDERR:"; Get-Content "$log.err" -TotalCount 10 }

