@echo off
if not defined SWA_TOKEN call "%~dp0_env.cmd"
if not defined SWA_TOKEN (echo SWA_TOKEN missing, are you signed in with az login? & exit /b 1)
call npx --yes @azure/static-web-apps-cli deploy "%~dp0..\src\dashboard" --deployment-token %SWA_TOKEN% --env production
if errorlevel 1 (
  echo First attempt failed, trying once more...
  call npx --yes @azure/static-web-apps-cli deploy "%~dp0..\src\dashboard" --deployment-token %SWA_TOKEN% --env production
)