# Starts/stops the backend (poe2craft serve --port 8000) and the frontend
# dev server (npm run dev, port 5173) as background processes, tracked by
# PID files under .make-pids/ -- the process lifecycle half of the Makefile
# (`make start`/`make stop`/`make status`), split into its own script
# because reliable Windows process management needs real cmdlets, not a
# bash one-liner.
#
# Usage: powershell -NoProfile -File scripts/dev.ps1 -Action start|stop|status
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action
)

$root = Split-Path -Parent $PSScriptRoot
$pidDir = Join-Path $root '.make-pids'
$logDir = Join-Path $root '.make-logs'
$backendPidFile = Join-Path $pidDir 'backend.pid'
$frontendPidFile = Join-Path $pidDir 'frontend.pid'

function Stop-ByPidFile {
    param([string]$Path)
    if (Test-Path $Path) {
        $savedId = Get-Content $Path -ErrorAction SilentlyContinue
        if ($savedId) {
            Stop-Process -Id $savedId -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $Path -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ByCommandLinePattern {
    param([string]$Pattern)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $Pattern } |
        ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                Write-Host "  stopped PID $($_.ProcessId): $($_.Name)"
            } catch {}
        }
}

switch ($Action) {
    'start' {
        New-Item -ItemType Directory -Force -Path $pidDir, $logDir | Out-Null

        $backend = Start-Process -FilePath 'uv' -ArgumentList 'run', 'poe2craft', 'serve', '--port', '8000' `
            -WorkingDirectory $root `
            -RedirectStandardOutput (Join-Path $logDir 'backend.log') `
            -RedirectStandardError (Join-Path $logDir 'backend.err.log') `
            -PassThru -WindowStyle Hidden
        $backend.Id | Out-File $backendPidFile -Encoding ascii

        # `npm` is a .cmd shim, not a real Win32 executable -- Start-Process
        # can't launch it directly (fails with "%1 is not a valid Win32
        # application"), so run it through cmd.exe /c instead.
        $frontend = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm', 'run', 'dev' `
            -WorkingDirectory (Join-Path $root 'frontend') `
            -RedirectStandardOutput (Join-Path $logDir 'frontend.log') `
            -RedirectStandardError (Join-Path $logDir 'frontend.err.log') `
            -PassThru -WindowStyle Hidden
        $frontend.Id | Out-File $frontendPidFile -Encoding ascii

        Write-Host "Backend:  http://127.0.0.1:8000  (PID $($backend.Id), log: .make-logs/backend.log)"
        # "localhost", not a literal 127.0.0.1 -- Vite's dev server binds
        # IPv6 loopback (::1) only by default here, so 127.0.0.1 alone
        # doesn't connect even though the server is genuinely up.
        Write-Host "Frontend: http://localhost:5173  (PID $($frontend.Id), log: .make-logs/frontend.log)"
        Write-Host "Give it a few seconds, then 'make status' to confirm both ports are listening."
    }
    'stop' {
        Stop-ByPidFile $backendPidFile
        Stop-ByPidFile $frontendPidFile
        # `uv run`/`npm run dev` are launchers, not the real worker -- killing
        # just the recorded PID can leave vite's/poe2craft's actual child
        # process running. Backstop: kill anything whose command line is
        # rooted in this project's own venv/node_modules, however it's
        # nested under the launcher. Safe because no unrelated process on
        # this machine has this project's path in its command line.
        Stop-ByCommandLinePattern ([regex]::Escape((Join-Path $root '.venv\Scripts\poe2craft')))
        Stop-ByCommandLinePattern ([regex]::Escape((Join-Path $root 'frontend\node_modules')))
        Write-Host "Stopped."
    }
    'status' {
        $conns = Get-NetTCPConnection -LocalPort 8000, 5173 -ErrorAction SilentlyContinue
        if (-not $conns) {
            Write-Host "Nothing listening on 8000 or 5173."
            return
        }
        $conns | ForEach-Object {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue
            [PSCustomObject]@{
                Port    = $_.LocalPort
                State   = $_.State
                Pid     = $_.OwningProcess
                Process = if ($proc) { $proc.Name } else { '?' }
            }
        } | Sort-Object Port | Format-Table -AutoSize
    }
}
