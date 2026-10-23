@echo off
setlocal
set PLATFORM_RG=rg-cop-platform-dev
set WORKLOAD_RG=rg-cop-workload-dev
set FUNC_APP=func-cop-api-dev-rkhmrb
set KV_NAME=kv-cop-dev-rkhmrb
set OAI_NAME=oai-cop-dev-rkhmrb
set OAI_LOCATION=swedencentral
set BUDGET=budget-cop-dev
set DIAG=activity-log-to-log-analytics
set TAG=azure-cloud-operations-center

for /f %%i in ('az account show --query id --output tsv') do set SUB=%%i
set FUNC_PID=
for /f %%i in ('az resource show --resource-group %PLATFORM_RG% --name %FUNC_APP% --resource-type Microsoft.Web/sites --query identity.principalId --output tsv 2^>nul') do set FUNC_PID=%%i
set GH_APP=
for /f %%i in ('az ad app list --display-name sp-cop-github --query "[0].appId" --output tsv 2^>nul') do set GH_APP=%%i

call :check %PLATFORM_RG%
set PLATFORM_STATE=%RESULT%
call :check %WORKLOAD_RG%
set WORKLOAD_STATE=%RESULT%
if "%PLATFORM_STATE%"=="foreign" goto foreign
if "%WORKLOAD_STATE%"=="foreign" goto foreign

echo.
echo ===== TEARDOWN PLAN =====
echo Resource groups: %PLATFORM_RG% is %PLATFORM_STATE%, %WORKLOAD_RG% is %WORKLOAD_STATE%
echo Also deleted: budget %BUDGET%, Activity Log export %DIAG%, the Function identity roles on the subscription
echo Also deleted: the GitHub Actions identity sp-cop-github and its subscription roles
echo Also purged: Key Vault %KV_NAME%, OpenAI account %OAI_NAME%
echo Nothing else is touched.
if "%PLATFORM_STATE%"=="ok" (echo. & echo --- in %PLATFORM_RG% --- & call az resource list --resource-group %PLATFORM_RG% --query "[].{name:name,type:type}" --output table)
if "%WORKLOAD_STATE%"=="ok" (echo. & echo --- in %WORKLOAD_RG% --- & call az resource list --resource-group %WORKLOAD_RG% --query "[].{name:name,type:type}" --output table)
echo.
if /i "%1"=="preview" (echo Preview only. Nothing was deleted. & exit /b 0)

set ANS=
set /p ANS=Type DELETE in capital letters to continue: 
if not "%ANS%"=="DELETE" (echo Cancelled. & exit /b 1)

echo.
echo [1/5] Role assignments of the Function identity on the subscription
if "%FUNC_PID%"=="" (echo No Function identity found, skipping.) else call :roles
if not "%GH_APP%"=="" call :ghidentity

echo [2/5] Budget and Activity Log export
call az consumption budget delete --budget-name %BUDGET%
call az monitor diagnostic-settings subscription delete --name %DIAG% --yes

echo [3/5] Deleting resource groups (takes several minutes)
if "%WORKLOAD_STATE%"=="ok" call az group delete --name %WORKLOAD_RG% --yes --no-wait
if "%PLATFORM_STATE%"=="ok" call az group delete --name %PLATFORM_RG% --yes --no-wait
if "%WORKLOAD_STATE%"=="ok" call az group wait --deleted --name %WORKLOAD_RG%
if "%PLATFORM_STATE%"=="ok" call az group wait --deleted --name %PLATFORM_RG%

echo [4/5] Purging soft-deleted Key Vault and OpenAI so the names are free
call az keyvault purge --name %KV_NAME%
call az cognitiveservices account purge --location %OAI_LOCATION% --resource-group %PLATFORM_RG% --name %OAI_NAME%

echo [5/5] Done. Check what is left:
echo   az group list --query "[].name" --output table
echo   az consumption budget list --output table
exit /b 0

:foreign
echo STOP: a project resource group exists but does not carry the project tag. Nothing was deleted.
exit /b 1

:check
set RESULT=missing
set T=
for /f %%t in ('az group show --name %1 --query tags.project --output tsv 2^>nul') do set T=%%t
if "%T%"=="%TAG%" set RESULT=ok
if defined T if not "%T%"=="%TAG%" set RESULT=foreign
exit /b 0

:roles
for /f "usebackq delims=" %%r in (`az role assignment list --assignee %FUNC_PID% --all --query "[?scope=='/subscriptions/%SUB%'].id" --output tsv`) do call az role assignment delete --ids %%r
exit /b 0

:ghidentity
for /f "usebackq delims=" %%r in (`az role assignment list --assignee %GH_APP% --all --query "[?scope=='/subscriptions/%SUB%'].id" --output tsv`) do call az role assignment delete --ids %%r
call az ad app delete --id %GH_APP%
exit /b 0