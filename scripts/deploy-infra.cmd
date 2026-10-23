@echo off
call "%~dp0whatif.cmd"
if errorlevel 1 (echo what-if failed, nothing deployed. & exit /b 1)
echo.
echo Read the what-if above. Only worry about delete lines.
set ANS=
set /p ANS=Type YES to deploy: 
if not "%ANS%"=="YES" (echo Cancelled. & exit /b 1)
call az deployment sub create --name cop-main-dev --location swedencentral --parameters "%~dp0..\infra\main.dev.bicepparam"
echo.
echo Done. Check in the portal that action group ag-cop-ops-dev still shows ops-email-2 as Verified.