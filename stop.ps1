$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$pidFile = Join-Path $root 'server.pid'

function Stop-ByHttp {
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:7860/shutdown' -Method POST -TimeoutSec 25 -ContentType 'application/json' -Body '{}' | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-RelatedPids {
    $ids = New-Object 'System.Collections.Generic.HashSet[int]'
    $markers = @(
        (Join-Path $root 'local_app.py'),
        (Join-Path $root 'start.ps1'),
        (Join-Path $root 'start.cmd'),
        (Join-Path $root 'start.bat')
    )
    Get-CimInstance Win32_Process | ForEach-Object {
        if ($_.ProcessId -eq $PID) { return }
        $cmd = $_.CommandLine
        if (-not $cmd) { return }
        foreach ($marker in $markers) {
            if ($cmd.ToLower().Contains($marker.ToLower())) {
                [void]$ids.Add([int]$_.ProcessId)
                break
            }
        }
    }
    Get-NetTCPConnection -LocalPort 7860 -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.OwningProcess -and $_.OwningProcess -ne $PID) {
            [void]$ids.Add([int]$_.OwningProcess)
        }
    }
    if (Test-Path $pidFile) {
        $saved = ((Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1) + '').Trim()
        if ($saved -match '^\d+$') { [void]$ids.Add([int]$saved) }
    }
    return @($ids)
}

Write-Host 'Stopping local voice cloning server...'
if (Stop-ByHttp) {
    Write-Host 'Asked the server to unload the model and exit.'
    Start-Sleep -Seconds 2
}

$targets = Get-RelatedPids
foreach ($id in $targets) {
    if ($id -eq $PID) { continue }
    if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
        Write-Host "Killing process tree $id"
        & taskkill.exe /F /T /PID $id 2>$null | Out-Null
    }
}

Start-Sleep -Seconds 1
$still = @(Get-RelatedPids | Where-Object { $_ -ne $PID -and (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
$port = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue
if ($still -or $port) {
    $portPids = @($port | ForEach-Object { $_.OwningProcess })
    Write-Host ('Still running: ' + (($still + $portPids) -join ', '))
} else {
    Write-Host 'Server processes have exited.'
}

$gpuPython = @()
try {
    $gpuPython = @(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>$null | Where-Object { $_ -match 'python' })
} catch {}
if ($gpuPython.Count -gt 0) {
    Write-Host 'Python is still using GPU memory:'
    $gpuPython | ForEach-Object { Write-Host ('  ' + $_) }
} else {
    Write-Host 'No Python GPU process found.'
}

if (Test-Path $pidFile) {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
