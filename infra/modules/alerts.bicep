@description('Short name used in all resource names')
param prefix string

@description('Environment name')
param envName string

@description('Azure region of the monitored workload')
param location string

@description('Tags applied to every resource')
param tags object

@description('Email address that receives alerts')
param alertEmail string

@description('Resource ID of the workload resource group to monitor')
param workloadResourceGroupId string

@description('Resource ID of the Application Insights component that receives the Function App telemetry')
param appInsightsId string

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-${prefix}-ops-${envName}'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'cop-ops'
    enabled: true
    emailReceivers: [
      {
        name: 'ops-email-2'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

resource cpuAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${prefix}-vm-high-cpu-${envName}'
  location: 'global'
  tags: tags
  properties: {
    description: 'Average CPU above 80 percent on any VM in the workload resource group'
    severity: 2
    enabled: true
    scopes: [
      workloadResourceGroupId
    ]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    targetResourceType: 'Microsoft.Compute/virtualMachines'
    targetResourceRegion: location
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'HighCpu'
          metricName: 'Percentage CPU'
          metricNamespace: 'Microsoft.Compute/virtualMachines'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
        }
      ]
    }
    autoMitigate: true
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

resource deploymentFailedAlert 'Microsoft.Insights/activityLogAlerts@2020-10-01' = {
  name: 'alert-${prefix}-deployment-failed-${envName}'
  location: 'global'
  tags: tags
  properties: {
    description: 'A deployment failed in the subscription'
    enabled: true
    scopes: [
      subscription().id
    ]
    condition: {
      allOf: [
        {
          field: 'category'
          equals: 'Administrative'
        }
        {
          field: 'operationName'
          equals: 'Microsoft.Resources/deployments/write'
        }
        {
          field: 'status'
          equals: 'Failed'
        }
      ]
    }
    actions: {
      actionGroups: [
        {
          actionGroupId: actionGroup.id
        }
      ]
    }
  }
}

resource functionFailureAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${prefix}-function-failures-${envName}'
  location: 'global'
  tags: tags
  properties: {
    description: 'The Function App logged one or more exceptions in the last 5 minutes'
    severity: 2
    enabled: true
    scopes: [
      appInsightsId
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'FunctionExceptions'
          metricName: 'exceptions/count'
          metricNamespace: 'microsoft.insights/components'
          operator: 'GreaterThan'
          threshold: 0
          timeAggregation: 'Count'
        }
      ]
    }
    autoMitigate: true
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

output actionGroupId string = actionGroup.id
output actionGroupName string = actionGroup.name
