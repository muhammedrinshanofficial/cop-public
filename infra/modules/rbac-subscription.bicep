targetScope = 'subscription'

@description('Object ID of the Function App managed identity')
param functionPrincipalId string

var readRoles = [
  {
    name: 'Reader'
    id: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  }
  {
    name: 'Monitoring Reader'
    id: '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
  }
  {
    name: 'Cost Management Reader'
    id: '72fafb9e-0641-4937-9268-a91bfd8191a3'
  }
]

resource assignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in readRoles: {
  name: guid(subscription().id, functionPrincipalId, role.id)
  properties: {
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.id)
  }
}]
