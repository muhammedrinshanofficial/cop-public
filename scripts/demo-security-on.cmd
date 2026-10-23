@echo off
set RG=rg-cop-workload-dev
set NSG=nsg-cop-workload-dev
echo Creating 7 test rules and 2 untagged resources (8 findings expected)...

rem critical: SSH is covered by demo-open-ssh.cmd, these are the other critical cases
call az network nsg rule create -g %RG% --nsg-name %NSG% -n t-rdp --priority 110 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "*" --destination-port-ranges 3389 --output none
call az network nsg rule create -g %RG% --nsg-name %NSG% -n t-allports --priority 120 --direction Inbound --access Allow --protocol "*" --source-address-prefixes "*" --destination-port-ranges "*" --output none
call az network nsg rule create -g %RG% --nsg-name %NSG% -n t-range-hides-rdp --priority 130 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "*" --destination-port-ranges 3000-4000 --output none

rem warning: other ports, and the Internet tag as source
call az network nsg rule create -g %RG% --nsg-name %NSG% -n t-web-8080 --priority 140 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "*" --destination-port-ranges 8080 --output none
call az network nsg rule create -g %RG% --nsg-name %NSG% -n t-internet-tag-443 --priority 150 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes Internet --destination-port-ranges 443 --output none

rem must NOT be flagged: private source, and a Deny rule
call az network nsg rule create -g %RG% --nsg-name %NSG% -n t-safe-private-ssh --priority 160 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes 10.0.0.0/8 --destination-port-ranges 22 --output none
call az network nsg rule create -g %RG% --nsg-name %NSG% -n t-safe-deny --priority 170 --direction Inbound --access Deny --protocol Tcp --source-address-prefixes "*" --destination-port-ranges 22 --output none

rem info: a public IP and an untagged NSG (both untagged on purpose, so the tag check fires)
call az network nsg create -g %RG% -n nsg-cop-untagged-test --output none
call az network public-ip create -g %RG% -n pip-cop-test-dev --sku Standard --allocation-method Static --output none

echo.
echo Done. Wait about 3 minutes (Resource Graph lags), then press Security ^> Scan now.
echo Expected: 8 findings (3 critical, 2 warning, 3 info). The two safe rules must not appear.
echo The public IP costs a little per day. Run scripts\demo-security-off.cmd when you are done.