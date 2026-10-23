@echo off
if "%1"=="" (echo Usage: scripts\collect.cmd name & exit /b 1)
if "%FUNC_HOST%"=="" call "%~dp0_env.cmd"
curl -s --max-time 120 -w "\n" -X POST "https://%FUNC_HOST%/api/collect/%1" -H "x-functions-key: %FUNC_KEY%"