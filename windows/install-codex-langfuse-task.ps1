# Customize these values before running the script.
$TaskName = "codex-langfuse-exporter"
$PythonPath = "C:\Python314\python.exe"
$ProjectDir = "C:\path\to\codex-langfuse-exporter"
$ScriptPath = Join-Path $ProjectDir "codex_langfuse_sync.py"
$StateFilePath = Join-Path $ProjectDir "state\state.json"
$LogFilePath = Join-Path $ProjectDir "state\scheduled-task.log"
$ExporterArgs = @(
  "--days", "1",
  "--limit", "50",
  "--state-file", $StateFilePath,
  "--log-file", $LogFilePath,
  "--no-prompt",
  "--no-output"
)
$StartTime = "09:00"
$RepeatMinutes = 60
$ReplaceExistingTask = $true

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Quote-TaskArgument {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Value
  )

  if ($Value -match '[\s"]') {
    return '"' + $Value.Replace('"', '\"') + '"'
  }

  return $Value
}

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
  throw "Register-ScheduledTask is unavailable. Run this on Windows PowerShell 5.1 or newer."
}

$TaskPythonPath = $PythonPath
if ([System.IO.Path]::GetFileName($PythonPath) -ieq "python.exe") {
  $pythonwPath = Join-Path (Split-Path -Path $PythonPath -Parent) "pythonw.exe"
  if (Test-Path -LiteralPath $pythonwPath -PathType Leaf) {
    $TaskPythonPath = $pythonwPath
  }
}

if (-not (Test-Path -LiteralPath $TaskPythonPath -PathType Leaf)) {
  throw "Python executable not found: $TaskPythonPath"
}

if (-not (Test-Path -LiteralPath $ProjectDir -PathType Container)) {
  throw "Project directory not found: $ProjectDir"
}

if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
  throw "Exporter entry script not found: $ScriptPath"
}

if ($RepeatMinutes -lt 1) {
  throw "RepeatMinutes must be >= 1"
}

if ($StartTime -notmatch '^\d{2}:\d{2}$') {
  throw "StartTime must use HH:mm, for example 09:00"
}

$stateDir = Split-Path -Path $StateFilePath -Parent
if ($stateDir) {
  New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
}

$hour, $minute = $StartTime.Split(":") | ForEach-Object { [int]$_ }
$startAt = Get-Date -Hour $hour -Minute $minute -Second 0
if ($startAt -le (Get-Date)) {
  $startAt = $startAt.AddDays(1)
}

$argumentList = @((Quote-TaskArgument -Value $ScriptPath))
foreach ($arg in $ExporterArgs) {
  $argumentList += Quote-TaskArgument -Value ([string]$arg)
}

$action = New-ScheduledTaskAction `
  -Execute $TaskPythonPath `
  -Argument ($argumentList -join " ") `
  -WorkingDirectory $ProjectDir

$trigger = New-ScheduledTaskTrigger `
  -Once `
  -At $startAt `
  -RepetitionInterval (New-TimeSpan -Minutes $RepeatMinutes) `
  -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal `
  -UserId $currentUser `
  -LogonType Interactive `
  -RunLevel Limited

if ($ReplaceExistingTask) {
  $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($null -ne $existingTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  }
}

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description "Sync Codex local sessions into Langfuse on a schedule." `
  | Out-Null

Write-Host "Registered scheduled task successfully."
Write-Host "Task name: $TaskName"
Write-Host "Runs as: $currentUser (interactive logon; task runs while this user is logged in)"
Write-Host "Program: $TaskPythonPath"
Write-Host "Arguments: $($argumentList -join ' ')"
Write-Host "Log file: $LogFilePath"
Write-Host "Working directory: $ProjectDir"
Write-Host "First run: $($startAt.ToString('yyyy-MM-dd HH:mm'))"
Write-Host "Repeat interval: every $RepeatMinutes minute(s)"
