@description('Name of the Static Web App')
param staticWebAppName string

@description('Name of the Function App that becomes the dashboard backend')
param functionAppName string

@description('Region of the Function App')
param location string

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' existing = {
  name: staticWebAppName
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: functionAppName
}

resource backend 'Microsoft.Web/staticSites/linkedBackends@2023-12-01' = {
  parent: staticWebApp
  name: 'backend'
  properties: {
    backendResourceId: functionApp.id
    region: location
  }
}

// Linking switches on Easy Auth for the Function App. These settings keep the dashboard login
// for the API and give the health check and the collector endpoints back their own protection
// (the collectors keep the function key).
resource auth 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: functionApp
  name: 'authsettingsV2'
  dependsOn: [
    backend
  ]
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'
      excludedPaths: [
        '/api/health'
        '/api/collect/inventory'
        '/api/collect/cost'
        '/api/collect/metrics'
        '/api/collect/activity'
        '/api/collect/alerts'
        '/api/collect/utilization'
        '/api/collect/waste'
        '/api/collect/security'
        '/api/collect/forecast'
      ]
    }
    identityProviders: {
      azureStaticWebApps: {
        enabled: true
        registration: {
          clientId: staticWebApp.properties.defaultHostname
        }
      }
    }
    httpSettings: {
      requireHttps: true
    }
  }
}
