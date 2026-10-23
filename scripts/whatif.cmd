@echo off
if not defined ALERT_EMAIL call "%~dp0_env.cmd"
if not defined ALERT_EMAIL (echo ALERT_EMAIL missing, stopping. & exit /b 1)
call az deployment sub what-if --location swedencentral --parameters "%~dp0..\infra\main.dev.bicepparam"