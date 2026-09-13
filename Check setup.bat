@echo off
REM Double-click this file to check that everything is ready, and to get the
REM settings to paste into Claude Desktop.
setlocal
title LibreOffice Calc MCP - setup check

set "PF86=%ProgramFiles(x86)%"
set "PY="
if exist "%ProgramFiles%\LibreOffice\program\python.exe" set "PY=%ProgramFiles%\LibreOffice\program\python.exe"
if not defined PY if exist "%PF86%\LibreOffice\program\python.exe" set "PY=%PF86%\LibreOffice\program\python.exe"
if not defined PY if exist "%ProgramW6432%\LibreOffice\program\python.exe" set "PY=%ProgramW6432%\LibreOffice\program\python.exe"

if not defined PY (
  echo.
  echo   Could not find LibreOffice on this computer.
  echo.
  echo   This tool needs LibreOffice installed. Get it free from:
  echo      https://www.libreoffice.org/download
  echo.
  echo   If LibreOffice IS installed but in an unusual place, open its folder,
  echo   find the file called python.exe, and drag it onto this window.
  echo.
  pause
  exit /b 1
)

echo Using LibreOffice's Python: %PY%
echo.
"%PY%" -u "%~dp0scripts\check-setup.py"
echo.
pause
