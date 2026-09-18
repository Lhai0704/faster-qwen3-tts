. "$PSScriptRoot\environment.ps1"
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$marker = "$PSScriptRoot\local_app.py"
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.ToLower().Contains($marker.ToLower())
}
$listening = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue
if ($existing -or $listening) {
    Write-Host 'Already running. Open http://127.0.0.1:7860 . Use stop.cmd or stop.bat to stop.'
    exit 0
}
Write-Host 'Open http://127.0.0.1:7860 in your browser.'
Write-Host 'Closing this window does not always free GPU memory. Use stop.cmd / stop.bat, or unload the model in the web page.'
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\local_app.py"
