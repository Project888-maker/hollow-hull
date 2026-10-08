<#
Collect everything Claude needs to diagnose Unreal closing or crashing.
Double-click COLLECT_LOGS.bat, then send Claude the red/yellow lines it prints,
or the files it copies into reports\phase1\logs.
#>
param([string]$Project = "C:\Projects\HollowHull")

$HH = $PSScriptRoot
. (Join-Path $HH "tools\find_project.ps1")
$found = Find-UnrealProject $Project
if ($found.Dir) { $Project = $found.Dir }
$Out = Join-Path $HH "reports\phase1\logs"
New-Item -ItemType Directory -Force $Out | Out-Null

function Say([string]$Text, [string]$Color = "Cyan") { Write-Host $Text -ForegroundColor $Color }

Say "=== Graphics card and memory ==="
try {
    Get-CimInstance Win32_VideoController | ForEach-Object {
        Say ("GPU: {0} | driver {1} ({2})" -f $_.Name, $_.DriverVersion, $_.DriverDate) "White"
    }
    $ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    Say "RAM: $ram GB" "White"
} catch {
    Say "could not read GPU info: $_" "Yellow"
}

Say "`n=== Project ==="
Say "Project: $(if ($found.Uproject) { $found.Uproject } else { 'none found' })" "White"
$ia = @(Get-ChildItem (Join-Path $Project "Content") -Recurse -Filter "IA_*.uasset" -ErrorAction SilentlyContinue)
Say "Input action assets: $($ia.Count)  $(($ia | Select-Object -First 6 | ForEach-Object { $_.Name }) -join ', ')" "White"
$gm = @(Get-ChildItem (Join-Path $Project "Content") -Recurse -Filter "*GameMode*.uasset" -ErrorAction SilentlyContinue)
Say "Game modes: $(($gm | ForEach-Object { $_.FullName.Substring((Join-Path $Project 'Content').Length) }) -join ', ')" "White"

Say "`n=== Unreal crash reports (newest first) ==="
$crashes = Get-ChildItem (Join-Path $Project "Saved\Crashes") -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 3
if (-not $crashes) { Say "none found (Unreal may have closed without a crash report)" "Yellow" }
$i = 0
foreach ($c in $crashes) {
    $i++
    $ctx = Join-Path $c.FullName "CrashContext.runtime-xml"
    if (Test-Path $ctx) {
        Copy-Item $ctx (Join-Path $Out "crash_$i.xml") -Force
        $m = Select-String -Path $ctx -Pattern '<ErrorMessage>(.*?)</ErrorMessage>' | Select-Object -First 1
        $msg = "(no message)"
        if ($m) { $msg = $m.Matches[0].Groups[1].Value }
        Say "$($c.LastWriteTime): $msg" "Red"
    }
}

Say "`n=== Unreal logs (newest first) ==="
$logs = Get-ChildItem (Join-Path $Project "Saved\Logs") -Filter "*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 3
if (-not $logs) { Say "no logs in $Project\Saved\Logs" "Yellow" }
$i = 0
foreach ($l in $logs) {
    $i++
    $copy = Join-Path $Out ("unreal_log_$i.txt")
    Copy-Item $l.FullName $copy -Force
    Say "`n--- $($l.Name) ($($l.LastWriteTime)) ---" "Yellow"
    $lines = Get-Content $copy
    $lines | Select-String -Pattern 'Fatal|Assertion failed|Unhandled Exception|GPU crash|D3D|out of memory|\[HH\] (WARNING|FAILED)|RHI|Shader Model' |
        Select-Object -Last 25 | ForEach-Object { Write-Host $_.Line }
    $bp = $lines | Select-String -Pattern 'LogBlueprint: Error' | ForEach-Object {
        # drop the timestamp so repeated errors collapse to one line
        ($_.Line -replace '^\[[^\]]*\]\[[^\]]*\]', '')
    } | Select-Object -Unique | Select-Object -First 15
    if ($bp) {
        Say "  Blueprint errors:" "Red"
        $bp | ForEach-Object { Write-Host "   $_" }
    }
    Say "  (last line: $($lines | Select-Object -Last 1))" "DarkGray"
}

Say "`nCopied to $Out" "Green"
Say "Send Claude a screenshot of this window, or attach the files in that folder." "Green"
