@description('Short name used in all resource names')
param prefix string

@description('Environment name')
param envName string

@description('Azure region')
param location string

@description('Tags applied to every resource')
param tags object

@description('Log Analytics workspace ID for diagnostics')
param workspaceId string

@description('Name of the model deployment used by the application')
param deploymentName string = 'gpt-41-mini'

@description('Deployment SKU. DataZoneStandard keeps processing inside the EU (Standard has no quota on this subscription)')
param deploymentSkuName string = 'DataZoneStandard'

@description('Capacity in thousands of tokens per minute')
param deploymentCapacity int = 10

var accountName = 'oai-${prefix}-${envName}-${take(uniqueString(resourceGroup().id), 6)}'

resource account 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: account
  name: deploymentName
  sku: {
    name: deploymentSkuName
    capacity: deploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-mini'
      version: '2025-04-14'
    }
  }
}

resource openAiDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-to-log-analytics'
  scope: account
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        category: 'Audit'
        enabled: true
      }
      {
        category: 'RequestResponse'
        enabled: true
      }
    ]
  }
}

output openAiAccountId string = account.id
output openAiAccountName string = account.name
output openAiEndpoint string = account.properties.endpoint
output openAiDeploymentName string = modelDeployment.name
