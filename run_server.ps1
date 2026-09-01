$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$work = "C:\Users\shrey_itz95ac\Projects\samadhan-ai"
$out = "C:\Users\SHREY_~1\AppData\Local\Temp\opencode\uvicorn_out.txt"
$err = "C:\Users\SHREY_~1\AppData\Local\Temp\opencode\uvicorn_err.txt"
$py = Join-Path $work "venv\Scripts\python.exe"

# Kill anything already bound to port 8000 (leftover stale servers)
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory $work -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden
Write-Output "Server launching in background on http://127.0.0.1:8000"
