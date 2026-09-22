@echo off
REM Start Guardian Library and put it on a public URL.
REM
REM Double-click this. It prints a link to send the office. The link works from
REM any phone or laptop, anywhere, for as long as this window stays open and
REM this PC stays awake.
REM
REM The link CHANGES every time you run this - that is how free Cloudflare quick
REM tunnels work. For a permanent address, see DEPLOY.md.

setlocal
cd /d "%~dp0"
title Guardian Library - sharing

echo.
echo   Guardian Library
echo   ================
echo.

REM --- start the portal if it is not already up ---------------------------
curl -s -o nul -m 5 http://127.0.0.1:5055/login
if errorlevel 1 (
  echo   starting the portal...
  start "" /b ".venv\Scripts\pythonw.exe" app.py
  timeout /t 6 /nobreak >nul
) else (
  echo   portal already running
)

REM --- find cloudflared ----------------------------------------------------
set CF=C:\Program Files (x86)\cloudflared\cloudflared.exe
if not exist "%CF%" set CF=C:\Program Files\cloudflared\cloudflared.exe
if not exist "%CF%" (
  echo.
  echo   Cloudflare tunnel not found. Install it with:
  echo       winget install --id Cloudflare.cloudflared
  echo.
  pause
  exit /b 1
)

REM --- open the tunnel and pull the URL out of its log ---------------------
set LOG=%TEMP%\guardian-tunnel.log
if exist "%LOG%" del "%LOG%"
echo   opening the public link...
REM --protocol http2: this network blocks the default QUIC transport, which
REM shows up as the tunnel starting but never becoming reachable.
start "" /b "%CF%" tunnel --protocol http2 --url http://localhost:5055 --logfile "%LOG%"

set URL=
for /l %%i in (1,1,30) do (
  timeout /t 2 /nobreak >nul
  for /f "tokens=*" %%u in ('findstr /r /c:"https://[a-z0-9-]*\.trycloudflare\.com" "%LOG%" 2^>nul') do (
    for /f "tokens=2 delims= " %%v in ("%%u") do set URL=%%v
  )
  if defined URL goto :found
)

echo   the tunnel did not come up. Check %LOG%
pause
exit /b 1

:found
powershell -NoProfile -Command "$t = Get-Content '%LOG%' -Raw; if ($t -match 'https://[a-z0-9-]+\.trycloudflare\.com') { $u = $Matches[0]; Set-Clipboard $u; Write-Host ''; Write-Host '   SEND THIS LINK:' -ForegroundColor Green; Write-Host ('   ' + $u) -ForegroundColor White; Write-Host ''; Write-Host '   password: see VIEWER_PASSWORD in .env'; Write-Host ''; Write-Host '   (link copied to clipboard)' -ForegroundColor DarkGray }"

echo   Keep this window open. Closing it takes the link down.
echo.
pause
