# switch-llm.ps1 - flip Atria's chat LLM provider between Qwen (DashScope) and OpenAI.
#
# Usage:
#   .\switch-llm.ps1 qwen      # use Qwen via DashScope (qwen3.5-plus-2026-02-15)
#   .\switch-llm.ps1 openai    # use OpenAI (gpt-5.5)  [needs OpenAI quota]
#   .\switch-llm.ps1 status    # print the currently active provider
#
# How it works: Atria reads OPENAI_API_KEY / ATRIA_MODEL / ATRIA_FALLBACK_MODEL /
# ATRIA_API_BASE_URL from .env (loaded by run-backend.ps1 on every start). This
# script rewrites those four active lines in place, pulling each provider's API
# key from the commented "key vault" (LLM_KEY_QWEN / LLM_KEY_OPENAI) in .env, so
# secrets live only in .env. After switching, RESTART the backend terminal.
#
# NOTE: keep this file pure ASCII - Windows PowerShell reads non-BOM files as
# ANSI, and characters like an em-dash can corrupt string parsing.

param(
  [Parameter(Position = 0)]
  [ValidateSet('qwen', 'openai', 'status')]
  [string]$Provider = 'status'
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
  Write-Host "ERROR: .env not found at $envPath" -ForegroundColor Red
  exit 1
}

# Read .env as an array of lines (preserve everything we don't touch).
# Force -Encoding UTF8 on READ: Windows PowerShell 5.1's Get-Content defaults to
# ANSI, which would misread (and on write-back, corrupt) any non-ASCII content.
$lines = Get-Content -LiteralPath $envPath -Encoding UTF8

# Pull a value out of the commented key vault, e.g. "# LLM_KEY_QWEN=sk-...".
function Get-VaultKey([string]$name) {
  foreach ($line in $lines) {
    if ($line -match "^\s*#\s*$name\s*=\s*(.+?)\s*$") {
      return $Matches[1]
    }
  }
  return $null
}

# Read the current value of an active (uncommented) KEY=VALUE line.
function Get-ActiveValue([string]$name) {
  foreach ($line in $lines) {
    if ($line -match "^\s*$name\s*=\s*(.*?)\s*$") {
      return $Matches[1]
    }
  }
  return $null
}

if ($Provider -eq 'status') {
  $model = Get-ActiveValue 'ATRIA_MODEL'
  $url = Get-ActiveValue 'ATRIA_API_BASE_URL'
  $name = if ($url -match 'dashscope') { 'QWEN (DashScope)' }
          elseif ($url -match 'openai') { 'OPENAI' }
          else { 'UNKNOWN' }
  Write-Host "Active LLM provider : $name" -ForegroundColor Cyan
  Write-Host "  ATRIA_MODEL          = $model"
  Write-Host "  ATRIA_FALLBACK_MODEL = $(Get-ActiveValue 'ATRIA_FALLBACK_MODEL')"
  Write-Host "  ATRIA_API_BASE_URL   = $url"
  exit 0
}

# Provider profiles. The API key is resolved from the .env key vault.
if ($Provider -eq 'qwen') {
  $key = Get-VaultKey 'LLM_KEY_QWEN'
  $model = 'qwen3.5-plus-2026-02-15'
  $fallback = 'qwen3.5-flash'
  $baseUrl = 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions'
  $label = 'QWEN (DashScope)'
}
else {
  $key = Get-VaultKey 'LLM_KEY_OPENAI'
  $model = 'gpt-5.5'
  $fallback = 'gpt-5.4'
  $baseUrl = 'https://api.openai.com/v1/chat/completions'
  $label = 'OPENAI'
}

if ([string]::IsNullOrWhiteSpace($key)) {
  Write-Host "ERROR: could not find the API key for '$Provider' in the .env key vault." -ForegroundColor Red
  Write-Host "Expected a commented line like: # LLM_KEY_$($Provider.ToUpper())=sk-..." -ForegroundColor Red
  exit 1
}

# Rewrite the four active lines in place. Each replacement only touches a line
# that starts (no leading #) with KEY=, leaving comments and other vars intact.
$replacements = @{
  'OPENAI_API_KEY'       = $key
  'ATRIA_MODEL'          = $model
  'ATRIA_FALLBACK_MODEL' = $fallback
  'ATRIA_API_BASE_URL'   = $baseUrl
}

$newLines = foreach ($line in $lines) {
  $matched = $false
  foreach ($name in $replacements.Keys) {
    if ($line -match "^\s*$name\s*=") {
      "$name=$($replacements[$name])"
      $matched = $true
      break
    }
  }
  if (-not $matched) { $line }
}

# Write back as UTF-8 WITHOUT BOM. The active KEY=VALUE lines are pure ASCII
# (read fine by run-backend.ps1's Get-Content), and UTF-8-no-BOM also preserves
# any non-ASCII characters elsewhere in .env (comments, future Vietnamese values)
# instead of mangling them to '?', which -Encoding ascii would do.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, $newLines, $utf8NoBom)

Write-Host "Switched LLM provider -> $label" -ForegroundColor Green
Write-Host "  ATRIA_MODEL          = $model"
Write-Host "  ATRIA_FALLBACK_MODEL = $fallback"
Write-Host "  ATRIA_API_BASE_URL   = $baseUrl"
Write-Host ""
Write-Host "RESTART the backend terminal for this to take effect:" -ForegroundColor Yellow
Write-Host "  Ctrl+C in the run-backend.ps1 window, then re-run  .\run-backend.ps1" -ForegroundColor Yellow
if ($Provider -eq 'openai') {
  Write-Host "NOTE: OpenAI quota was exhausted (429). Top up the account or chat will fail." -ForegroundColor Yellow
}
