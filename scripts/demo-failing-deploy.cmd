@echo off
echo Deploying a template that is meant to fail...
call az deployment group create --name cop-demo-fail --resource-group rg-cop-workload-dev --template-file "%~dp0..\infra\demo\fail-deployment.bicep"
echo.
echo The deployment should have failed. The alert email arrives in a few minutes.
echo Then run: scripts\collect.cmd activity
echo Check Operations ^> Deployments for the error text.