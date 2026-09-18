<#
.SYNOPSIS
  Start a long-lived Chrome for jev-browser warm-browser mode (CDP).

.DESCRIPTION
  jev-browser normally launches a fresh Chromium for every run (~1 s). With a
  warm browser, runs connect over CDP in ~100 ms and reuse the same profile
  (so site logins survive between runs).

  Idempotent: if the CDP port already answers, it exits without starting
  anything. Uses a dedicated profile directory (.chrome-profile in this
  project) so it never touches the user's normal Chrome profile.

.EXAMPLE
  .\start_warm_chrome.ps1                 # headless (default)
  .\start_warm_chrome.ps1 -Headed         # visible window, for debugging
  .\start_warm_chrome.ps1 -Port 9333      # non-default port
#>
param(
  [int]$Port = 9333,
  [switch]$Headed
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$profileDir = Join-Path $project ".chrome-profile"

function Test-Cdp {
  try {
    $null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/json/version" -TimeoutSec 2
    return $true
  } catch {
    return $false
  }
}

if (Test-Cdp) {
  Write-Output "warm chrome already running on port $Port"
  exit 0
}

$full = Get-ChildItem "$env:LOCALAPPDATA\ms-playwright\chromium-*\chrome-win64\chrome.exe" -ErrorAction SilentlyContinue |
  Sort-Object FullName -Descending | Select-Object -First 1
$shell = Get-ChildItem "$env:LOCALAPPDATA\ms-playwright\chromium_headless_shell-*\chrome-headless-shell-win64\chrome-headless-shell.exe" -ErrorAction SilentlyContinue |
  Sort-Object FullName -Descending | Select-Object -First 1

if ($Headed -and -not $full) { throw "headed mode needs the full Chromium build under ms-playwright" }
$exe = if ($Headed -or $full) { $full.FullName } else { $shell.FullName }
if (-not $exe) { throw "no Chrome/Chromium found under $env:LOCALAPPDATA\ms-playwright" }

$chromeArgs = @(
  "--remote-debugging-port=$Port",
  "--user-data-dir=$profileDir",
  "--no-first-run",
  "--no-default-browser-check",
  "--disable-sync",
  "about:blank"
)
if (-not $Headed) {
  if ($exe -like "*headless-shell*") {
    # The shell binary is headless by design; no extra flag needed.
  } else {
    $chromeArgs += "--headless=new"
  }
}

Start-Process -FilePath $exe -ArgumentList $chromeArgs -WindowStyle Hidden

for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Milliseconds 250
  if (Test-Cdp) {
    Write-Output "warm chrome ready on port $Port"
    Write-Output "profile: $profileDir"
    Write-Output "use:     `$env:JEV_BROWSER_CDP_URL = `"http://127.0.0.1:$Port`""
    exit 0
  }
}
throw "warm chrome did not become ready on port $Port"
