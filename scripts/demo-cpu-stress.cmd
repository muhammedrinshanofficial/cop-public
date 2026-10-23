@echo off
echo Starting a 10 minute CPU load on vm-cop-app-dev (VM must be running)...
call az vm run-command invoke --resource-group rg-cop-workload-dev --name vm-cop-app-dev --command-id RunShellScript --scripts "timeout 600 yes > /dev/null & timeout 600 yes > /dev/null & wait" --no-wait
echo Load started. Alert email (Fired) in about 6 minutes, Resolved after the load ends.
echo Then run: scripts\collect.cmd metrics