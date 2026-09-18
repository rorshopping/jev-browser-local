<#
.SYNOPSIS
  Start the local JEV decision bridge that jev-browser talks to.

.DESCRIPTION
  Serves the TypeSafe /v1/systemone contract (and an OpenAI-compatible typing
  endpoint) from the local parallel-decisions engine. Blocks while serving, so
  run it in a background terminal or as a background process.

  Uses the gpu worktree venv with the engine fixes (chunked prefill + trie
  collision scoring). Loads the 1.5B decision model by default; the 0.5B typing
  model is loaded only when VRAM headroom allows (see --typing).

.EXAMPLE
  .\start_bridge.ps1                 # 1.5B decisions + typing when VRAM allows
  .\start_bridge.ps1 -NoTyping       # decisions only, ~1 GB less VRAM
  .\start_bridge.ps1 -Model Qwen/Qwen2.5-0.5B-Instruct
#>
param(
  [string]$Model = "Qwen/Qwen2.5-1.5B-Instruct",
  [int]$Port = 8768,
  [switch]$NoTyping,
  [switch]$Typing
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = "C:\Users\Richard\Documents\Projects\parallel-decisions_wt\gpu\.venv\Scripts\python.exe"
$engineSrc = "C:\Users\Richard\Documents\Projects\parallel-decisions_wt\chunked-prefill\src"
$env:PYTHONPATH = $engineSrc

$serverArgs = @((Join-Path $project "local_jev_server.py"), "--port", $Port, "--model", $Model)
if ($NoTyping) { $serverArgs += "--no-typing" }
if ($Typing) { $serverArgs += "--typing" }

& $venv @serverArgs
