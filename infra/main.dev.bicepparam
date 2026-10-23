using 'main.bicep'

param prefix = 'cop'
param envName = 'dev'
param location = 'swedencentral'
param owner = 'rinshan'
param adminUsername = 'azureops'
param sshPublicKey = readEnvironmentVariable('SSH_PUBLIC_KEY')
param alertEmail = readEnvironmentVariable('ALERT_EMAIL')
param adminPrincipalId = readEnvironmentVariable('ADMIN_PRINCIPAL_ID', '')
param budgetAmount = 10000
param budgetStartDate = '2026-10-01'
