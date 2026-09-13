@echo off
REM Double-click this file to check that everything is ready, and to get the
REM settings to paste into Claude Desktop.
setlocal enabledelayedexpansion
title LibreOffice Calc MCP - setup check

set "PF86=%ProgramFiles(x86)%"
set "PY="
set "LOFOUND="

REM The usual places first.
call :try_root "%ProgramFiles%\LibreOffice"
call :try_root "%PF86%\LibreOffice"
call :try_root "%ProgramW6432%\LibreOffice"

REM Then ask Windows itself, which finds installs on other drives or in
REM folders nobody would guess.
call :try_registry "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe" ""
call :try_registry "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe" "/reg:32"
call :try_registry "HKLM\SOFTWARE\LibreOffice\UNO\InstallPath" ""
call :try_registry "HKCU\SOFTWARE\LibreOffice\UNO\InstallPath" ""

if defined PY goto :found

echo.
if defined LOFOUND (
  echo   LibreOffice is installed here:
  echo       !LOFOUND!
  echo.
  echo   ...but it is missing the Python part this tool needs.
  echo.
  echo   To add it: open Settings ^> Apps, find LibreOffice, choose Modify,
  echo   pick "Custom" and switch on "Optional Components" ^> "Python Script
  echo   Provider". Then run this check again.
) else (
  echo   Could not find LibreOffice on this computer.
  echo.
  echo   If you have not installed it yet, get it free from:
  echo       https://www.libreoffice.org/download
  echo.
  echo   If it IS installed, open the folder it lives in, go into the folder
  echo   called "program", and check there is a file named python.exe there.
  echo   If there is, drag that file onto this window and press Enter.
)
echo.
if not defined LOCALC_NO_PAUSE pause
exit /b 1

:found
echo Using LibreOffice's Python: !PY!
echo.
"!PY!" -u "%~dp0scripts\check-setup.py"
set "CODE=%ERRORLEVEL%"
echo.
if not defined LOCALC_NO_PAUSE pause
exit /b %CODE%

:try_root
if defined PY goto :eof
if "%~1"=="" goto :eof
if exist "%~1\program\python.exe" (
  set "PY=%~1\program\python.exe"
  set "LOFOUND=%~1"
) else if exist "%~1\program\soffice.exe" (
  set "LOFOUND=%~1"
)
goto :eof

:try_registry
if defined PY goto :eof
set "REGVAL="
for /f "tokens=2,*" %%a in ('reg query "%~1" /ve %~2 2^>nul') do set "REGVAL=%%b"
if not defined REGVAL goto :eof
REM The value is either the program folder, or soffice.exe inside it.
if exist "!REGVAL!\python.exe" (
  set "PY=!REGVAL!\python.exe"
  goto :eof
)
for %%I in ("!REGVAL!") do set "REGDIR=%%~dpI"
if exist "!REGDIR!python.exe" set "PY=!REGDIR!python.exe"
if exist "!REGDIR!soffice.exe" if not defined LOFOUND set "LOFOUND=!REGDIR!"
goto :eof
