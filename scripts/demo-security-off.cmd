@echo off
set RG=rg-cop-workload-dev
set NSG=nsg-cop-workload-dev
echo Removing all security test items (missing ones are skipped)...

for %%r in (t-rdp t-allports t-range-hides-rdp t-web-8080 t-internet-tag-443 t-safe-private-ssh t-safe-deny) do call az network nsg rule delete -g %RG% --nsg-name %NSG% -n %%r 2>nul
call az network nsg delete -g %RG% -n nsg-cop-untagged-test 2>nul
call az network public-ip delete -g %RG% -n pip-cop-test-dev 2>nul

echo.
echo Done. Wait about 3 minutes, then press Security ^> Scan now. Expected: 0 findings.
echo The timeline events stay as history. Press Regenerate on the briefing to clear its Critical light.