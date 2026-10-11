<#
.SYNOPSIS
Export a locally installed Global chibi for Chibi Studio, without the Unity Editor.
.EXAMPLE
.\tools\chibi_export\export.ps1 -ViewerPath C:\Tools\UmaViewer -CharacterId 1030 -Name 'Rice Shower'
#>
[CmdletBinding()]
param(
    [string]$ViewerPath,
    [string]$GamePath,
    [string]$ModelsPath = $env:CHIBI_MODELS_DIR,
    [ValidateRange(1000, 9999)][int]$CharacterId = 1030,
    [string]$Name,
    [ValidatePattern('^[a-zA-Z0-9_]{2,16}$')][string]$Costume = '00',
    [string]$Outfit = 'Racing outfit',
    [string[]]$Motions,
    [switch]$UseViewerKeys,
    [switch]$AllRaceOutfits,
    [switch]$InventoryOnly,
    [switch]$PhysicsOnly,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$cache = Join-Path $repo '.local'
$models = if ($ModelsPath) { [IO.Path]::GetFullPath($ModelsPath) } else { Join-Path $repo 'models' }
$player = Join-Path $cache 'chibi-player'
$downloads = Join-Path $cache 'chibi-downloads'
$build = Join-Path $cache 'chibi-export-build'
$modelId = if ($Costume -eq '00') { "$CharacterId" } else { "$CharacterId-$Costume" }
$output = Join-Path $models $modelId
if ($AllRaceOutfits -or $InventoryOnly -or $PhysicsOnly) { $output = Join-Path $cache 'chibi-import' }
if (!$Name) { $Name = if ($CharacterId -eq 1030) { 'Rice Shower' } else { "Character $CharacterId" } }
New-Item -ItemType Directory -Path $cache, $downloads, $output -Force | Out-Null
Get-Command dotnet -ErrorAction Stop | Out-Null

# Only one exporter may use this private player at a time.
$exportLock = [IO.File]::Open((Join-Path $cache 'chibi-export.lock'), 'OpenOrCreate', 'Write', 'None')
function Invoke-ChibiExport($exportRequest, [int]$timeoutSeconds = 210) {
    $runOutput = $exportRequest.output
    [IO.File]::WriteAllText((Join-Path $player 'chibi-studio-export.json'), ($exportRequest | ConvertTo-Json -Depth 30))
    foreach ($marker in @('export-complete.txt', 'export-error.txt', 'progress.json')) {
        $markerPath = Join-Path $runOutput $marker
        if (Test-Path -LiteralPath $markerPath) { Remove-Item -LiteralPath $markerPath }
    }
    $child = $null
    try {
        $child = Start-Process -FilePath (Join-Path $player 'UmaViewer.exe') -WorkingDirectory $player -WindowStyle Hidden -PassThru -ArgumentList '-batchmode', '-logFile', 'chibi-studio-player.log'
        $deadline = [DateTime]::UtcNow.AddSeconds($timeoutSeconds)
        $lastCompleted = -1
        while (!$child.WaitForExit(1000)) {
            if ([DateTime]::UtcNow -gt $deadline) { throw 'Export timed out. See .local/chibi-player/chibi-studio-player.log.' }
            $progressPath = Join-Path $runOutput 'progress.json'
            if (Test-Path -LiteralPath $progressPath) {
                try {
                    $progress = Get-Content -LiteralPath $progressPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($progress.completed -ne $lastCompleted) {
                        Write-Host "[$($progress.completed + 1)/$($progress.total)] $($progress.name) - $($progress.outfit)"
                        $lastCompleted = $progress.completed
                    }
                } catch { } # A progress file can be between writes.
            }
        }
        $failure = Join-Path $runOutput 'export-error.txt'
        if (Test-Path -LiteralPath $failure) { throw (Get-Content -LiteralPath $failure -Raw -Encoding UTF8) }
        if ($child.ExitCode -ne 0 -or !(Test-Path -LiteralPath (Join-Path $runOutput 'export-complete.txt'))) {
            throw 'UmaViewer exited without completing. See .local/chibi-player/chibi-studio-player.log. Bulk imports can be resumed with the same command.'
        }
    } finally {
        if ($null -ne $child -and !$child.HasExited) { $child.Kill() }
    }
}
try {
    $managed = Join-Path $player 'UmaViewer_Data/Managed/umamusume.dll'
    if (!(Test-Path -LiteralPath $managed)) {
        if (!$ViewerPath) { throw 'First export: supply -ViewerPath with a Windows x64 Mono UmaViewer build folder.' }
        $source = (Resolve-Path -LiteralPath $ViewerPath).Path
        if (!(Test-Path -LiteralPath (Join-Path $source 'UmaViewer_Data/Managed/umamusume.dll'))) {
            throw 'This exporter needs the Mono build with UmaViewer_Data/Managed/umamusume.dll (an IL2CPP build is not compatible).'
        }
        Write-Host 'Preparing a private copy of UmaViewer in .local/chibi-player...'
        New-Item -ItemType Directory -Path $player -Force | Out-Null
        foreach ($item in @('UmaViewer.exe', 'UnityPlayer.dll', 'UmaViewer_Data', 'MonoBleedingEdge')) {
            Copy-Item -LiteralPath (Join-Path $source $item) -Destination $player -Recurse -Force
        }
        if (Test-Path -LiteralPath (Join-Path $source 'Config.json')) {
            Copy-Item -LiteralPath (Join-Path $source 'Config.json') -Destination $player -Force
        }
    }

    if (!(Test-Path -LiteralPath (Join-Path $player 'BepInEx/core/BepInEx.dll'))) {
        $zip = Join-Path $downloads 'BepInEx_win_x64_5.4.23.5.zip'
        if (!(Test-Path -LiteralPath $zip)) {
            Write-Host 'Downloading the pinned BepInEx 5 runtime from its official release...'
            Invoke-WebRequest -Uri 'https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.5/BepInEx_win_x64_5.4.23.5.zip' -OutFile $zip
        }
        if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne '82F9878551030F54657792C0740D9D51A09500EEAE1FBA21106B0C441E6732C4') {
            throw 'BepInEx archive did not match the pinned SHA-256. The archive was not installed.'
        }
        Expand-Archive -LiteralPath $zip -DestinationPath $player -Force
    }

    $configPath = Join-Path $player 'Config.json'
    $config = if (Test-Path -LiteralPath $configPath) { Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
    if (!$GamePath) {
        $GamePath = Join-Path ${env:ProgramFiles(x86)} 'Steam/steamapps/common/UmamusumePrettyDerby/UmamusumePrettyDerby_Data/Persistent'
        if (!(Test-Path -LiteralPath (Join-Path $GamePath 'meta')) -and $config.MainPath) { $GamePath = $config.MainPath }
    }
    $GamePath = (Resolve-Path -LiteralPath $GamePath).Path
    if (!(Test-Path -LiteralPath (Join-Path $GamePath 'meta')) -or !(Test-Path -LiteralPath (Join-Path $GamePath 'dat'))) {
        throw '-GamePath must be the installed Global game cache containing meta and dat. Assets must already be downloaded in the game.'
    }
    $settings = @{
        MainPath = $GamePath; Region = 0; WorkMode = 0; Language = 1
        RegionDetectionPassed = $true; DownloadMissingResources = $false; EnableTextureStreaming = $false
    }
    if (!$UseViewerKeys) {
        # Read the public compatibility values from pinned upstream source; never bundle game keys.
        $revision = '07f82e9fa08f23c1cda3a9be3045a09372eae8bb'
        $upstream = Join-Path $downloads "Config-$revision.cs"
        if (!(Test-Path -LiteralPath $upstream)) {
            Invoke-WebRequest -Uri "https://raw.githubusercontent.com/katboi01/UmaViewer/$revision/Assets/Scripts/Config.cs" -OutFile $upstream
        }
        $sourceText = Get-Content -LiteralPath $upstream -Raw
        foreach ($field in @('DBBaseKey', 'DBKey', 'GlobalDBKey', 'ABKey')) {
            $match = [regex]::Match($sourceText, "\b$field\s*=\s*new byte\[\]\s*\{([^}]+)\}")
            $bytes = [regex]::Matches($match.Groups[1].Value, '0x([0-9a-fA-F]{2})')
            if (!$match.Success -or $bytes.Count -lt 8) { throw "Could not read $field from pinned UmaViewer configuration." }
            $settings["${field}Text"] = ($bytes | ForEach-Object { $_.Groups[1].Value }) -join ''
        }
    }
    foreach ($key in $settings.Keys) { $config | Add-Member -NotePropertyName $key -NotePropertyValue $settings[$key] -Force }
    [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 20))

    if (!$Motions) {
        $Motions = @(
            "3d/motion/mini/event/body/chara/chr${CharacterId}_00/anm_min_eve_chr${CharacterId}_00_idle01_loop",
            '3d/motion/mini/event/body/type00/anm_min_eve_type00_walk01_loop',
            '3d/motion/mini/event/body/type00/anm_min_eve_type00_run00_loop',
            '3d/motion/mini/event/body/type00/anm_min_eve_type00_joy05_loop'
        )
    }
    Write-Host 'Building the exporter...'
    & dotnet build (Join-Path $PSScriptRoot 'ChibiStudioExporter.csproj') --artifacts-path $build --nologo --verbosity quiet "-p:ViewerPath=$player"
    if ($LASTEXITCODE -ne 0) { throw 'Exporter build failed. Install .NET SDK 8 or newer and use a compatible Mono UmaViewer build.' }
    $plugins = Join-Path $player 'BepInEx/plugins/ChibiStudioExporter'
    New-Item -ItemType Directory -Path $plugins -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $build 'bin/ChibiStudioExporter/debug/ChibiStudioExporter.dll') -Destination $plugins -Force

    if ($AllRaceOutfits -or $InventoryOnly -or $PhysicsOnly) {
        Write-Host 'Checking the installed Global mini assets...'
        Invoke-ChibiExport @{mode = 'inventory'; output = $output}
        if ($AllRaceOutfits -or $PhysicsOnly) {
            $python = Join-Path $repo '.venv/Scripts/python.exe'
            if (!(Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
            $batchPath = Join-Path $output 'batch.json'
            $catalogArgs = @((Join-Path $PSScriptRoot 'catalog.py'), '--master', (Join-Path $GamePath 'master/master.mdb'),
                '--inventory', (Join-Path $output 'inventory.json'), '--output', $batchPath, '--models', $models)
            if ($Force) { $catalogArgs += '--force' }
            & $python @catalogArgs
            if ($LASTEXITCODE -ne 0) { throw 'Could not build the Global racewear catalog.' }
            $batch = Get-Content -LiteralPath $batchPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($PhysicsOnly) {
                $batch.mode = 'physics'
                if (!$AllRaceOutfits) { $batch.items = @($batch.items | Where-Object character_id -eq $CharacterId) }
            }
            if (!$batch.items.Count) { throw 'No complete local racewear assets were found. See .local/chibi-import/batch.json.' }
            Invoke-ChibiExport $batch ([Math]::Max(210, $batch.items.Count * 180 + 30))
            $report = if (!$PhysicsOnly) { Get-Content -LiteralPath (Join-Path $output 'batch-report.json') -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
            & $python (Join-Path $PSScriptRoot 'refresh_metadata.py') --models $models --catalog $batchPath
            if ($LASTEXITCODE -ne 0) { throw 'Models exported, but updating their face metadata failed. Rerun to finish the import.' }
            if ($PhysicsOnly) { Write-Host 'Physics metadata updated. Details: .local/chibi-import/physics-report.json' }
            else {
                $failed = @($report.results | Where-Object status -eq 'failed')
                Write-Host "Finished $($report.results.Count) outfits; $($failed.Count) failed; $($report.unavailable.Count) unavailable locally."
                Write-Host 'Details: .local/chibi-import/batch-report.json'
                if ($failed.Count) { throw 'Some outfits failed. The successful exports are available; rerun this command to retry only incomplete outfits.' }
            }
        } else {
            Write-Host "Inventory: $output/inventory.json"
        }
    } else {
        Write-Host "Exporting $Name from local assets..."
        Invoke-ChibiExport @{ character_id = $CharacterId; name = $Name; costume = $Costume; outfit = $Outfit; output = $output; motions = $Motions }
        Write-Host "Ready: $output/model.glb"
    }
    Write-Host 'Start python viewer.py and refresh the character list in Chibi Studio.'
}
finally {
    $exportLock.Dispose()
}
