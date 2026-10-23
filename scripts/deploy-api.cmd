@echo off
python -m compileall -q "%~dp0..\src\api"
if errorlevel 1 (echo Syntax error, not publishing. & exit /b 1)
pushd "%~dp0..\src\api"
call func azure functionapp publish func-cop-api-dev-rkhmrb --python
popd
echo.
echo Published. Function count check:
call "%~dp0status.cmd"