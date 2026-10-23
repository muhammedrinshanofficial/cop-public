@description('Object ID of the Function App managed identity')
param functionPrincipalId string

@description('Object ID of the signed-in admin user (empty skips the Cosmos role for the user)')
param adminPrincipalId string = ''

@description('Log Analytics workspace name')
param workspaceName string

@description('Azure OpenAI account name')
param openAiAccountName string

@description('Cosmos DB account name')
param cosmosAccountName string

@description('Cosmos DB database name')
param cosmosDatabaseName string

@description('Platform storage account name')
param storageAccountName string

var logAnalyticsReaderRoleId = '73c42c96-874c-492b-b04d-ab87d138a893'
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAiAccountName
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosAccountName
}

resource platformStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource workspaceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workspace.id, functionPrincipalId, logAnalyticsReaderRoleId)
  scope: workspace
  properties: {
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', logAnalyticsReaderRoleId)
  }
}

resource openAiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAi.id, functionPrincipalId, openAiUserRoleId)
  scope: openAi
  properties: {
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
  }
}

// Cosmos DB data-plane roles are a separate system from Azure RBAC.
// Scope is the single database "cop", not the whole account.
resource functionCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, functionPrincipalId, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: functionPrincipalId
    scope: '${cosmosAccount.id}/dbs/${cosmosDatabaseName}'
  }
}

resource adminCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (!empty(adminPrincipalId)) {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, adminPrincipalId, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: adminPrincipalId
    scope: '${cosmosAccount.id}/dbs/${cosmosDatabaseName}'
  }
}

// Lets the admin user upload the Function package now that shared-key access is being turned off.
resource adminStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminPrincipalId)) {
  name: guid(platformStorage.id, adminPrincipalId, storageBlobDataContributorRoleId)
  scope: platformStorage
  properties: {
    principalId: adminPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
  }
}
