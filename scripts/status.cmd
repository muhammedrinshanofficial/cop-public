@echo off
echo === VMs ===
call az vm list --resource-group rg-cop-workload-dev --show-details --query "[].{name:name,size:hardwareProfile.vmSize,state:powerState}" --output table
echo.
echo === Function App ===
call az resource show --resource-group rg-cop-platform-dev --name func-cop-api-dev-rkhmrb --resource-type Microsoft.Web/sites --query "properties.{state:state,httpsOnly:httpsOnly}" --output table
echo.
echo === Functions registered (expect 34) ===
call az functionapp function list --resource-group rg-cop-platform-dev --name func-cop-api-dev-rkhmrb --query "length(@)" --output tsv