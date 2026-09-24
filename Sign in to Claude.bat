@echo off
REM Sign the Claude Code CLI in to your Claude subscription.
REM
REM This is what lets the portal's Summarise button work without paying for
REM API credit - it uses the subscription you already have.
REM
REM Double-click this file. A browser window opens; approve with the same
REM account your Claude subscription is on. Nothing else to do.

title Sign in to Claude

echo.
echo   Guardian Library - Claude sign-in
echo   =================================
echo.

REM Find the newest installed CLI rather than hard-coding a version that
REM changes every few weeks.
set "CLAUDE="
for /f "delims=" %%d in ('dir /b /ad /o-n "%APPDATA%\Claude\claude-code" 2^>nul') do (
  if not defined CLAUDE if exist "%APPDATA%\Claude\claude-code\%%d\claude.exe" (
    set "CLAUDE=%APPDATA%\Claude\claude-code\%%d\claude.exe"
  )
)

if not defined CLAUDE (
  echo   Could not find claude.exe under %APPDATA%\Claude\claude-code
  echo   Is Claude Code installed?
  echo.
  pause
  exit /b 1
)

echo   using: %CLAUDE%
echo.
echo   A browser window should open. If it does not, copy the link this
echo   window prints and paste it into your browser yourself.
echo.

"%CLAUDE%" setup-token

echo.
echo   ---------------------------------
echo   Checking whether it worked...
echo.
"%CLAUDE%" auth status
echo.
echo   You want   "loggedIn": true
echo.
pause
