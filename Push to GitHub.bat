@echo off
REM Push Guardian Library to GitHub.
REM
REM This uses --force-with-lease because the local history was rewritten to
REM remove Lists.xlsx (the holdings spreadsheet) from every past commit. The
REM copy on GitHub still has the old history, so an ordinary push is refused.
REM
REM --force-with-lease is the safe form of a force push: it refuses to run if
REM anything has landed on GitHub that this machine has not seen, so it cannot
REM silently throw away someone else's work.

setlocal
cd /d "%~dp0"
title Push Guardian Library to GitHub

echo.
echo   Push Guardian Library to GitHub
echo   ===============================
echo.
echo   This replaces the history on GitHub with the history on this machine.
echo   That is deliberate: it is how Lists.xlsx stops being recoverable from
echo   old commits once the repository is public.
echo.
echo   Nothing you can see on the site changes. Only the commit history does.
echo.

git rev-parse --git-dir >nul 2>&1
if errorlevel 1 (
  echo   ERROR: this folder is not a git repository.
  echo.
  pause
  exit /b 1
)

echo   local commits to push:
git log --oneline -3
echo.

choice /c YN /n /m "   Go ahead? [Y/N] "
if errorlevel 2 (
  echo.
  echo   Cancelled. Nothing was pushed.
  echo.
  pause
  exit /b 0
)

echo.
echo   pushing...
echo.
git push --force-with-lease origin main

if errorlevel 1 (
  echo.
  echo   The push did not succeed. Copy the message above and send it over.
) else (
  echo.
  echo   Done. Next:
  echo     1. Make the repo public   - Settings, Danger Zone, Change visibility
  echo     2. Turn on Pages          - Settings, Pages, Source: GitHub Actions
  echo.
  echo   Then the site builds itself at:
  echo     https://rishabh-labs.github.io/guardian-library/
)

echo.
pause
