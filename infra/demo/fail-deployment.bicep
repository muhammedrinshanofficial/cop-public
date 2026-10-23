resource failing 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, 'cop-demo-fail')
  properties: {
    principalId: '00000000-0000-0000-0000-000000000001'
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00000000-0000-0000-0000-0000000000ff')
  }
}
