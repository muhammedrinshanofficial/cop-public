@echo off
rem Sets every variable a window needs. Run it as: call scripts\_env.cmd
rem collect.cmd calls it by itself when FUNC_HOST is empty.
rem There is no setlocal on purpose, so the variables stay in your window.

for /f %%i in ('az resource show --resource-group rg-cop-platform-dev --name func-cop-api-dev-rkhmrb --resource-type Microsoft.Web/sites --query properties.defaultHostName --output tsv') do set FUNC_HOST=%%i
for /f %%i in ('az functionapp keys list --resource-group rg-cop-platform-dev --name func-cop-api-dev-rkhmrb --query functionKeys.default --output tsv') do set FUNC_KEY=%%i
for /f %%i in ('az ad signed-in-user show --query id --output tsv') do set ADMIN_PRINCIPAL_ID=%%i
for /f %%i in ('az staticwebapp secrets list --name swa-cop-dashboard-dev --resource-group rg-cop-platform-dev --query properties.apiKey --output tsv') do set SWA_TOKEN=%%i

if exist "%USERPROFILE%\.ssh\cop_vm_key.pub" (set /p SSH_PUBLIC_KEY=<"%USERPROFILE%\.ssh\cop_vm_key.pub") else (echo WARNING: SSH public key not found.)
if exist "%~dp0email.local" (set /p ALERT_EMAIL=<"%~dp0email.local") else (echo WARNING: scripts\email.local is missing, so ALERT_EMAIL is not set. Bicep what-if will fail without it.)

if "%FUNC_KEY%"=="" echo WARNING: FUNC_KEY is empty. Are you signed in with az login?
if "%SWA_TOKEN%"=="" echo WARNING: SWA_TOKEN is empty. Are you signed in with az login?
echo Ready: FUNC_HOST, FUNC_KEY, ADMIN_PRINCIPAL_ID, SWA_TOKEN, SSH_PUBLIC_KEY, ALERT_EMAIL