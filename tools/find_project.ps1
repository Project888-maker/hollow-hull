<#
Shared by run_phase1.ps1 and collect_logs.ps1 (dot-sourced).
Finds the HollowHull Unreal project. Only a project file named HollowHull.uproject
is ever used, so other projects (tutorials, samples) are never touched.
#>

$HHProjectFile = "HollowHull.uproject"

function Get-ProjectSearchRoots([string]$Preferred) {
    # Every entry is optional: skip any base folder Windows doesn't report.
    $pairs = @(
        @((Split-Path $Preferred -Parent), ""),
        @("C:\Projects", ""),
        @([Environment]::GetFolderPath("MyDocuments"), "Unreal Projects"),
        @($env:USERPROFILE, "Documents\Unreal Projects"),
        @($env:USERPROFILE, "OneDrive\Documents\Unreal Projects"),
        @($env:OneDrive, "Documents\Unreal Projects"),
        @([Environment]::GetFolderPath("Desktop"), "")
    )
    $roots = foreach ($p in $pairs) {
        if (-not $p[0]) { continue }
        if ($p[1]) { Join-Path $p[0] $p[1] } else { $p[0] }
    }
    return $roots | Where-Object { Test-Path $_ } | Select-Object -Unique
}

function Find-UnrealProject([string]$Preferred) {
    # Returns @{ Uproject; Dir; Name; Others } - Uproject is $null when no HollowHull project was found.
    # Others lists other .uproject files seen, only so the message can mention them.
    $result = @{ Uproject = $null; Dir = $null; Name = $null; Others = @() }
    $direct = Join-Path $Preferred $HHProjectFile
    if (Test-Path $direct) {
        $pick = Get-Item $direct
    } else {
        $roots = Get-ProjectSearchRoots $Preferred
        # a few levels deep, in case the folder was pasted inside another HollowHull folder
        $hits = foreach ($root in $roots) {
            Get-ChildItem $root -Recurse -Depth 3 -Filter $HHProjectFile -ErrorAction SilentlyContinue
        }
        # prefer a copy outside OneDrive, then the newest
        $pick = @($hits) | Sort-Object @{ Expression = { $_.FullName -match "OneDrive" } }, @{ Expression = { $_.LastWriteTime }; Descending = $true } |
            Select-Object -First 1
        $others = foreach ($root in $roots) {
            Get-ChildItem $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                Get-ChildItem $_.FullName -Filter "*.uproject" -ErrorAction SilentlyContinue
            }
        }
        $result.Others = @($others | Where-Object { $_.Name -ne $HHProjectFile })
    }
    if ($pick) {
        $result.Uproject = $pick.FullName
        $result.Dir = $pick.DirectoryName
        $result.Name = [IO.Path]::GetFileNameWithoutExtension($pick.Name)
    }
    return $result
}
