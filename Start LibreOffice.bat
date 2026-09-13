@echo off
REM Double-click this to open LibreOffice Calc so Claude can reach it.
REM You normally do not need this: Claude starts LibreOffice by itself.
setlocal
title Starting LibreOffice Calc

set "PF86=%ProgramFiles(x86)%"
set "SOFFICE="
if exist "%ProgramFiles%\LibreOffice\program\soffice.exe" set "SOFFICE=%ProgramFiles%\LibreOffice\program\soffice.exe"
if not defined SOFFICE if exist "%PF86%\LibreOffice\program\soffice.exe" set "SOFFICE=%PF86%\LibreOffice\program\soffice.exe"
if not defined SOFFICE if exist "%ProgramW6432%\LibreOffice\program\soffice.exe" set "SOFFICE=%ProgramW6432%\LibreOffice\program\soffice.exe"

if not defined SOFFICE (
  echo   Could not find LibreOffice. Install it from https://www.libreoffice.org/download
  pause
  exit /b 1
)

start "" "%SOFFICE%" --calc "--accept=socket,host=127.0.0.1,port=2002;urp;"
echo LibreOffice Calc is opening. You can close this window.
timeout /t 4 >nul
