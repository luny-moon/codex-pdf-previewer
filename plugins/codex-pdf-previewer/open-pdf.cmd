@echo off
setlocal DisableDelayedExpansion
if "%~1"=="" goto usage
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0scripts\preview.py" open "%~1"
exit /b %errorlevel%
:use_python
python "%~dp0scripts\preview.py" open "%~1"
exit /b %errorlevel%
:usage
echo Usage: open-pdf.cmd "C:\Documents\sample.pdf"
exit /b 2
