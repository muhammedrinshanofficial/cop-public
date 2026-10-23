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

@description('Admin username for the VMs')
param adminUsername string

@description('SSH public key, passed at deploy time and not stored in the repo')
param sshPublicKey string

@description('Size of the app VM (CPU stress target)')
param vmSize string = 'Standard_B2ts_v2'

@description('Size of the idle VM (deliberately larger than it needs: 4 GiB RAM, no workload)')
param idleVmSize string = 'Standard_B2ls_v2'

@description('Daily auto-shutdown time, 24h HHmm, India Standard Time')
param autoShutdownTime string = '2330'

var vms = [
  {
    name: 'vm-${prefix}-app-${envName}'
    role: 'app'
    size: vmSize
  }
  {
    name: 'vm-${prefix}-idle-${envName}'
    role: 'idle'
    size: idleVmSize
  }
]

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-${prefix}-workload-${envName}'
  location: location
  tags: tags
  properties: {
    securityRules: []
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${prefix}-workload-${envName}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.20.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'snet-workload'
        properties: {
          addressPrefix: '10.20.1.0/24'
          networkSecurityGroup: {
            id: nsg.id
          }
        }
      }
    ]
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${prefix}wl${uniqueString(resourceGroup().id)}'
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource nics 'Microsoft.Network/networkInterfaces@2024-05-01' = [for vm in vms: {
  name: 'nic-${vm.name}'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: vnet.properties.subnets[0].id
          }
        }
      }
    ]
  }
}]

resource virtualMachines 'Microsoft.Compute/virtualMachines@2024-07-01' = [for (vm, i) in vms: {
  name: vm.name
  location: location
  tags: union(tags, {
    role: vm.role
  })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: vm.size
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        deleteOption: 'Delete'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
    osProfile: {
      computerName: vm.name
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nics[i].id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}]

resource shutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = [for (vm, i) in vms: {
  name: 'shutdown-computevm-${vm.name}'
  location: location
  tags: tags
  properties: {
    status: 'Enabled'
    taskType: 'ComputeVmShutdownTask'
    dailyRecurrence: {
      time: autoShutdownTime
    }
    timeZoneId: 'India Standard Time'
    notificationSettings: {
      status: 'Disabled'
    }
    targetResourceId: virtualMachines[i].id
  }
}]

resource perfDcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: 'dcr-${prefix}-vm-perf-${envName}'
  location: location
  tags: tags
  kind: 'Linux'
  properties: {
    dataSources: {
      performanceCounters: [
        {
          name: 'vm-perf-counters'
          streams: [
            'Microsoft-Perf'
          ]
          samplingFrequencyInSeconds: 60
          counterSpecifiers: [
            'Processor(*)\\% Processor Time'
            'Memory(*)\\% Used Memory'
            'Memory(*)\\% Available Memory'
            'Memory(*)\\Available MBytes Memory'
          ]
        }
      ]
    }
    destinations: {
      logAnalytics: [
        {
          name: 'law-platform'
          workspaceResourceId: workspaceId
        }
      ]
    }
    dataFlows: [
      {
        streams: [
          'Microsoft-Perf'
        ]
        destinations: [
          'law-platform'
        ]
      }
    ]
  }
}

resource monitorAgent 'Microsoft.Compute/virtualMachines/extensions@2024-07-01' = [for (vm, i) in vms: {
  parent: virtualMachines[i]
  name: 'AzureMonitorLinuxAgent'
  location: location
  tags: tags
  properties: {
    publisher: 'Microsoft.Azure.Monitor'
    type: 'AzureMonitorLinuxAgent'
    typeHandlerVersion: '1.0'
    autoUpgradeMinorVersion: true
    enableAutomaticUpgrade: true
  }
}]

resource perfAssociation 'Microsoft.Insights/dataCollectionRuleAssociations@2023-03-11' = [for (vm, i) in vms: {
  name: 'dcra-${vm.name}'
  scope: virtualMachines[i]
  dependsOn: [
    monitorAgent
  ]
  properties: {
    dataCollectionRuleId: perfDcr.id
  }
}]

resource nsgDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-to-log-analytics'
  scope: nsg
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        category: 'NetworkSecurityGroupEvent'
        enabled: true
      }
      {
        category: 'NetworkSecurityGroupRuleCounter'
        enabled: true
      }
    ]
  }
}

output vmNames array = [for vm in vms: vm.name]
output storageAccountName string = storage.name
output nsgName string = nsg.name
