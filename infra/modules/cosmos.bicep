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

@description('Shared database throughput in RU/s (1000 is the free tier allowance)')
param databaseThroughput int = 1000

var databaseName = 'cop'

var containerDefinitions = [
  {
    name: 'snapshots'
    partitionKey: '/type'
  }
  {
    name: 'events'
    partitionKey: '/day'
  }
  {
    name: 'alerts'
    partitionKey: '/day'
  }
  {
    name: 'briefings'
    partitionKey: '/day'
  }
  {
    name: 'conversations'
    partitionKey: '/userId'
  }
]

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-${prefix}-${envName}-${take(uniqueString(resourceGroup().id), 6)}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: true
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    publicNetworkAccess: 'Enabled'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    options: {
      throughput: databaseThroughput
    }
  }
}

@batchSize(1)
resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [for c in containerDefinitions: {
  parent: database
  name: c.name
  properties: {
    resource: {
      id: c.name
      partitionKey: {
        paths: [
          c.partitionKey
        ]
        kind: 'Hash'
        version: 2
      }
    }
  }
}]

resource cosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-to-log-analytics'
  scope: account
  properties: {
    workspaceId: workspaceId
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        category: 'DataPlaneRequests'
        enabled: true
      }
      {
        category: 'ControlPlaneRequests'
        enabled: true
      }
    ]
  }
}

output cosmosAccountId string = account.id
output cosmosAccountName string = account.name
output cosmosEndpoint string = account.properties.documentEndpoint
output cosmosDatabaseName string = database.name
