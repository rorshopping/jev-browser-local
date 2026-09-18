<#
.SYNOPSIS
  Stop the warm Chrome started by start_warm_chrome.ps1.
#>
$me = $PID
$found = 0
Get-CimInstance Win32_Process |
  Where-Object { $_.ProcessId -ne $me -and $_.CommandLine -like "*.chrome-profile*" } |
  ForEach-Object { "stopping PID $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $script:found++ }
if ($found -eq 0) { "no warm chrome found (profile .chrome-profile)" }
