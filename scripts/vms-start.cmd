@echo off
echo Starting both VMs (auto-shutdown is 23:30 India time)...
for %%v in (vm-cop-app-dev vm-cop-idle-dev) do call az vm start --resource-group rg-cop-workload-dev --name %%v --no-wait
echo Start requested. Check with scripts\status.cmd in a minute or two.