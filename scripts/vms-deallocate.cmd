@echo off
echo Deallocating both VMs (stops compute billing)...
for %%v in (vm-cop-app-dev vm-cop-idle-dev) do call az vm deallocate --resource-group rg-cop-workload-dev --name %%v --no-wait
echo Deallocate requested.