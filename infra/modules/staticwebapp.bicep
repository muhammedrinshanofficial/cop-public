@description('Short name used in all resource names')
param prefix string

@description('Environment name')
param envName string

@description('Azure region (must be a region Static Web Apps supports)')
param location string

@description('Tags applied to every resource')
param tags object

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: 'swa-${prefix}-dashboard-${envName}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {}
}

output staticWebAppId string = staticWebApp.id
output staticWebAppName string = staticWebApp.name
output defaultHostname string = staticWebApp.properties.defaultHostname
