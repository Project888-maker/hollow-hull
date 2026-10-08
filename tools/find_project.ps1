<#
Shared by run_phase1.ps1 and collect_logs.ps1 (dot-sourced).
Finds the Unreal project to build into: a .uproject directly inside the
preferred folder, otherwise the newest .uproject in the usual project folders.
#>

function Get-ProjectSearchRoots([string]$Preferred) {
    # Every entry is optional: skip any base folder Windows doesn't report.
    $pairs = @(
        @((Split-Path $Preferred -Parent), ""),
        @("C:\Projects", ""),
        @([Environment]::GetFolderPath("MyDocuments"), "Unreal Projects"),
        @($env:USERPROFILE, "Documents\Unreal Projects"),
        @($env:USERPROFILE, "OneDrive\Documents\Unreal Projects"),
        @($env:OneDrive, "Documents\Unreal Projects")
    )
    $roots = foreach ($p in $pairs) {
        if (-not $p[0]) { continue }
        if ($p[1]) { Join-Path $p[0] $p[1] } else { $p[0] }
    }
    return $roots | Where-Object { Test-Path $_ } | Select-Object -Unique
}

function Find-UnrealProject([string]$Preferred) {
    # Returns @{ Uproject; Dir; Name; Candidates } - Uproject is $null when nothing was found.
    $result = @{ Uproject = $null; Dir = $null; Name = $null; Candidates = @() }
    $direct = Get-ChildItem $Preferred -Filter "*.uproject" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($direct) {
        $pick = $direct
    } else {
        $found = foreach ($root in (Get-ProjectSearchRoots $Preferred)) {
            Get-ChildItem $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                Get-ChildItem $_.FullName -Filter "*.uproject" -ErrorAction SilentlyContinue
            }
        }
        $result.Candidates = @($found | Sort-Object LastWriteTime -Descending)
        $pick = $result.Candidates | Select-Object -First 1
    }
    if ($pick) {
        $result.Uproject = $pick.FullName
        $result.Dir = $pick.DirectoryName
        $result.Name = [IO.Path]::GetFileNameWithoutExtension($pick.Name)
    }
    return $result
}
