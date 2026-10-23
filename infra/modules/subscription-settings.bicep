targetScope = 'subscription'

@description('Short name used in all resource names')
param prefix string

@description('Environment name')
param envName string

@description('Log Analytics workspace that receives the Activity Log')
param workspaceId string

@description('Action Group notified by budget alerts')
param actionGroupId string

@description('Email address for budget alerts')
param alertEmail string

@description('Monthly budget amount in the subscription billing currency')
param budgetAmount int

@description('Budget start date, first day of a month (YYYY-MM-DD)')
param budgetStartDate string

resource activityLogExport 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'activity-log-to-log-analytics'
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        category: 'Administrative'
        enabled: true
      }
      {
        category: 'ServiceHealth'
        enabled: true
      }
      {
        category: 'ResourceHealth'
        enabled: true
      }
      {
        category: 'Alert'
        enabled: true
      }
    ]
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: 'budget-${prefix}-${envName}'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
    }
    notifications: {
      Actual_GreaterThan_50_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: [
          alertEmail
        ]
        contactGroups: [
          actionGroupId
        ]
      }
      Actual_GreaterThan_80_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [
          alertEmail
        ]
        contactGroups: [
          actionGroupId
        ]
      }
      Forecasted_GreaterThan_100_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [
          alertEmail
        ]
        contactGroups: [
          actionGroupId
        ]
      }
    }
  }
}
