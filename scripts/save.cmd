@echo off
if "%~1"=="" (echo Usage: scripts\save.cmd "commit message" & exit /b 1)
git add .
git status --short
git commit -m "%~1"
git push