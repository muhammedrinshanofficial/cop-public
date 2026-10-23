@echo off
echo Removing the open SSH rule if it exists...
call az network nsg rule delete --resource-group rg-cop-workload-dev --nsg-name nsg-cop-workload-dev --name allow-ssh-internet 2>nul
call "%~dp0vms-start.cmd"
echo Wait about 3 minutes, then run: scripts\collect.cmd security