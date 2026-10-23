@echo off
call "%~dp0deploy-infra.cmd"
if errorlevel 1 exit /b 1
call "%~dp0deploy-api.cmd"
call "%~dp0deploy-dashboard.cmd"
call "%~dp0check.cmd"