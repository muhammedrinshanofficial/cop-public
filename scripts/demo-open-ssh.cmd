@echo off
if /i "%1"=="on" goto on
if /i "%1"=="scan" goto scan
if /i "%1"=="off" goto off
echo Usage: scripts\demo-open-ssh.cmd on ^| scan ^| off
exit /b 1

:on
call az network nsg rule create --resource-group rg-cop-workload-dev --nsg-name nsg-cop-workload-dev --name allow-ssh-internet --priority 100 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "*" --destination-port-ranges 22
echo Rule added. Wait about 3 minutes (Resource Graph lags), then run: scripts\demo-open-ssh.cmd scan
exit /b 0

:scan
call "%~dp0collect.cmd" security
exit /b 0

:off
call az network nsg rule delete --resource-group rg-cop-workload-dev --nsg-name nsg-cop-workload-dev --name allow-ssh-internet
echo Rule deleted. Wait about 3 minutes, then run scan again. The finding goes, the timeline event stays.
exit /b 0