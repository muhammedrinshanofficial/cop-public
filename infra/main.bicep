targetScope = 'subscription'

@description('Short name used in all resource names')
param prefix string = 'cop'

@description('Environment name')
param envName string = 'dev'

@description('Azure region for all resources')
param location string = 'swedencentral'

@description('Owner tag value')
param owner string = 'rinshan'

@description('Admin username for the sample VMs')
param adminUsername string

@description('SSH public key for the sample VMs (passed at deploy time)')
param sshPublicKey string

@description('VM size for the sample workload')
param vmSize string = 'Standard_B2ts_v2'

@description('Email address that receives alerts (passed at deploy time)')
param alertEmail string

@description('Object ID of the admin user who gets a Cosmos DB data role (passed at deploy time, optional)')
param adminPrincipalId string = ''

@description('Monthly budget amount in the subscription billing currency')
param budgetAmount int

@description('Budget start date, first day of a month (YYYY-MM-DD)')
param budgetStartDate string

var tags = {
  project: 'azure-cloud-operations-center'
  environment: envName
  owner: owner
  managedBy: 'bicep'
}

resource rgPlatform 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${prefix}-platform-${envName}'
  location: location
  tags: tags
}

resource rgWorkload 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${prefix}-workload-${envName}'
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rgPlatform
  params: {
    prefix: prefix
    envName: envName
    location: location
    tags: tags
  }
}

module workload 'modules/workload.bicep' = {
  name: 'workload'
  scope: rgWorkload
  params: {
    prefix: prefix
    envName: envName
    location: location
    tags: tags
    workspaceId: monitoring.outputs.workspaceId
    adminUsername: adminUsername
    sshPublicKey: sshPublicKey
    vmSize: vmSize
  }
}

module alerts 'modules/alerts.bicep' = {
  name: 'alerts'
  scope: rgPlatform
  params: {
    prefix: prefix
    envName: envName
    location: location
    tags: tags
    alertEmail: alertEmail
    workloadResourceGroupId: rgWorkload.id
    appInsightsId: monitoring.outputs.appInsightsId
  }
}

module subscriptionSettings 'modules/subscription-settings.bicep' = {
  name: 'subscription-settings'
  params: {
    prefix: prefix
    envName: envName
    workspaceId: monitoring.outputs.workspaceId
    actionGroupId: alerts.outputs.actionGroupId
    alertEmail: alertEmail
    budgetAmount: budgetAmount
    budgetStartDate: budgetStartDate
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  scope: rgPlatform
  params: {
    prefix: prefix
    envName: envName
    location: location
    tags: tags
    workspaceId: monitoring.outputs.workspaceId
  }
}

module platformStorage 'modules/storage.bicep' = {
  name: 'platform-storage'
  scope: rgPlatform
  params: {
    prefix: prefix
    location: location
    tags: tags
    workspaceId: monitoring.outputs.workspaceId
  }
}

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  scope: rgPlatform
  params: {
    prefix: prefix
    envName: envName
    location: location
    tags: tags
    workspaceId: monitoring.outputs.workspaceId
  }
}

module staticWebApp 'modules/staticwebapp.bicep' = {
  name: 'staticwebapp'
  scope: rgPlatform
  params: {
    prefix: prefix
    envName: envName
    // Static Web Apps is not available in Sweden Central, and westeurope is closed to new customers on this subscription
    location: 'eastus2'
    tags: tags
  }
}

module openAi 'modules/openai.bicep' = {
  name: 'openai'
  scope: rgPlatform
  params: {
    prefix: prefix
    envName: envName
    location: location
    tags: tags
    workspaceId: monitoring.outputs.workspaceId
  }
}

module functionApp 'modules/functionapp.bicep' = {
  name: 'functionapp'
  scope: rgPlatform
  params: {
    prefix: prefix
    envName: envName
    location: location
    tags: tags
    workspaceId: monitoring.outputs.workspaceId
    workspaceName: monitoring.outputs.workspaceName
    appInsightsName: monitoring.outputs.appInsightsName
    storageAccountName: platformStorage.outputs.storageAccountName
    cosmosEndpoint: cosmos.outputs.cosmosEndpoint
    cosmosDatabaseName: cosmos.outputs.cosmosDatabaseName
    keyVaultUri: keyVault.outputs.keyVaultUri
    openAiEndpoint: openAi.outputs.openAiEndpoint
    openAiDeploymentName: openAi.outputs.openAiDeploymentName
    dashboardOrigin: 'https://${staticWebApp.outputs.defaultHostname}'
  }
}

module staticWebAppLink 'modules/staticwebapp-link.bicep' = {
  name: 'staticwebapp-link'
  scope: rgPlatform
  params: {
    staticWebAppName: staticWebApp.outputs.staticWebAppName
    functionAppName: functionApp.outputs.functionAppName
    location: location
  }
}

module rbacSubscription 'modules/rbac-subscription.bicep' = {
  name: 'rbac-subscription'
  params: {
    functionPrincipalId: functionApp.outputs.functionAppPrincipalId
  }
}

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  scope: rgPlatform
  params: {
    functionPrincipalId: functionApp.outputs.functionAppPrincipalId
    adminPrincipalId: adminPrincipalId
    workspaceName: monitoring.outputs.workspaceName
    openAiAccountName: openAi.outputs.openAiAccountName
    cosmosAccountName: cosmos.outputs.cosmosAccountName
    cosmosDatabaseName: cosmos.outputs.cosmosDatabaseName
    storageAccountName: platformStorage.outputs.storageAccountName
  }
}

output platformResourceGroup string = rgPlatform.name
output workloadResourceGroup string = rgWorkload.name
output logAnalyticsWorkspace string = monitoring.outputs.workspaceName
output sampleVmNames array = workload.outputs.vmNames
output actionGroupName string = alerts.outputs.actionGroupName
output keyVaultName string = keyVault.outputs.keyVaultName
output platformStorageName string = platformStorage.outputs.storageAccountName
output cosmosAccountName string = cosmos.outputs.cosmosAccountName
output functionAppName string = functionApp.outputs.functionAppName
output staticWebAppHostname string = staticWebApp.outputs.defaultHostname
output openAiAccountName string = openAi.outputs.openAiAccountName
