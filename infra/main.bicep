// ShopperMind AI — Azure infrastructure
//
// One resource group holds the whole platform. Container Apps runs the API and the web
// front end, Postgres Flexible Server holds tenant data, and the AI services are
// referenced by the API at runtime. Every AI service is optional: the API degrades to
// local implementations when a key is absent, so an evaluation deployment can skip them.
//
//   az group create -n rg-shoppermind-prod -l centralindia
//   az deployment group create -g rg-shoppermind-prod -f infra/main.bicep \
//      -p environmentName=prod postgresAdminPassword=<secret>

targetScope = 'resourceGroup'

@description('Short environment name, used in every resource name.')
@allowed(['dev', 'staging', 'prod'])
param environmentName string = 'dev'

@description('Region for all resources. Central India keeps data resident for the launch market.')
param location string = resourceGroup().location

@description('Region for the Azure OpenAI account. Not every model is available in every region.')
param openAiLocation string = 'swedencentral'

@description('Administrator login for Postgres.')
param postgresAdminUser string = 'shoppermind'

@secure()
@description('Administrator password for Postgres. Supply at deployment; never commit it.')
param postgresAdminPassword string

@description('Deploy the Azure AI services. Set false for a cheap evaluation deployment — the platform still runs on its local fallbacks.')
param deployAiServices bool = true

@description('Chat model for the copilot. Azure retires model versions on a schedule, so this is a parameter — pin it to whatever `az cognitiveservices model list` reports as GenerallyAvailable in your region.')
param chatModel string = 'gpt-5.4-mini'

@description('Version of the chat model.')
param chatModelVersion string = '2026-03-17'

@description('Public app name. The web app is reachable at https://<appName>.<region>.azurecontainerapps.io and the API at https://<appName>-api...')
param appName string = 'shoppermind'

@description('Container image for the API.')
param apiImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Container image for the web front end.')
param webImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

var prefix = 'shoppermind-${environmentName}'
var uniqueSuffix = uniqueString(resourceGroup().id)
var tags = {
  application: 'ShopperMind AI'
  environment: environmentName
  managedBy: 'bicep'
}

// ── observability ───────────────────────────────────────────────────────────
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${prefix}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${prefix}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ── secrets ─────────────────────────────────────────────────────────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-sm-${environmentName}-${take(uniqueSuffix, 8)}'
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

// ── data ────────────────────────────────────────────────────────────────────
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'psql-${prefix}-${take(uniqueSuffix, 6)}'
  location: location
  tags: tags
  sku: {
    // Burstable is deliberate for dev/staging: the analytical work is bursty and short.
    // Production moves to GeneralPurpose, where the module runs are not competing for
    // CPU credits at exactly the moment a dashboard is loading.
    name: environmentName == 'prod' ? 'Standard_D4ds_v5' : 'Standard_B2ms'
    tier: environmentName == 'prod' ? 'GeneralPurpose' : 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: environmentName == 'prod' ? 256 : 64
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: environmentName == 'prod' ? 35 : 7
      geoRedundantBackup: environmentName == 'prod' ? 'Enabled' : 'Disabled'
    }
    highAvailability: {
      mode: environmentName == 'prod' ? 'ZoneRedundant' : 'Disabled'
    }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'shoppermind'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Container Apps egresses from shared Azure IPs; lock this down to a VNet before
// production traffic. Left open here so an evaluation deployment works out of the box.
resource postgresAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAllAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stsm${environmentName}${take(uniqueSuffix, 10)}'
  location: location
  tags: tags
  sku: { name: environmentName == 'prod' ? 'Standard_ZRS' : 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    // Camera frames, where a tenant opts into retaining them at all, are short-lived by
    // policy. The lifecycle rule below enforces it rather than trusting the application.
    deleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource mediaContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'shoppermind-media'
  properties: { publicAccess: 'None' }
}

resource frameRetention 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-camera-frames'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['shoppermind-media/frames/']
            }
            actions: {
              baseBlob: {
                // Frames are an operational artefact, never a dataset. One day, then gone.
                delete: { daysAfterModificationGreaterThan: 1 }
              }
            }
          }
        }
      ]
    }
  }
}

// ── AI services ─────────────────────────────────────────────────────────────
resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (deployAiServices) {
  name: 'oai-${prefix}-${take(uniqueSuffix, 6)}'
  location: openAiLocation
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'oai-${prefix}-${take(uniqueSuffix, 6)}'
    publicNetworkAccess: 'Enabled'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (deployAiServices) {
  parent: openAi
  name: chatModel
  sku: {
    name: 'GlobalStandard'
    // The copilot is bursty — a quiet estate makes few calls, then a Monday morning
    // makes many. Capacity is set for the peak, not the average.
    capacity: environmentName == 'prod' ? 60 : 10
  }
  properties: {
    model: { format: 'OpenAI', name: chatModel, version: chatModelVersion }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (deployAiServices) {
  parent: openAi
  name: 'text-embedding-3-large'
  sku: { name: 'Standard', capacity: environmentName == 'prod' ? 60 : 10 }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-large', version: '1' }
  }
  dependsOn: [chatDeployment]
}

// Speech, Vision and Language in one multi-service account: the API only needs a key
// and an endpoint per capability, and one account is cheaper and simpler to rotate.
resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (deployAiServices) {
  name: 'cog-${prefix}-${take(uniqueSuffix, 6)}'
  location: location
  tags: tags
  kind: 'CognitiveServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'cog-${prefix}-${take(uniqueSuffix, 6)}'
    publicNetworkAccess: 'Enabled'
  }
}

// ── container platform ──────────────────────────────────────────────────────
resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: 'crsm${environmentName}${take(uniqueSuffix, 10)}'
  location: location
  tags: tags
  sku: { name: environmentName == 'prod' ? 'Premium' : 'Basic' }
  properties: { adminUserEnabled: false }
}

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${prefix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    zoneRedundant: environmentName == 'prod'
  }
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-api'
  location: location
  tags: tags
}

// The API pulls images and reads secrets as itself — no admin credentials anywhere.
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, apiIdentity.id, 'AcrPull')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull
    )
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, apiIdentity.id, 'KeyVaultSecretsUser')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User
    )
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

var postgresConnection = 'postgresql+psycopg://${postgresAdminUser}:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/shoppermind?sslmode=require'

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${appName}-api'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${apiIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        corsPolicy: {
          allowedOrigins: ['https://${appName}.${containerEnv.properties.defaultDomain}']
          allowedMethods: ['*']
          allowedHeaders: ['*']
          allowCredentials: true
        }
      }
      registries: [
        { server: registry.properties.loginServer, identity: apiIdentity.id }
      ]
      secrets: [
        { name: 'database-url', value: postgresConnection }
        { name: 'api-secret-key', value: uniqueString(resourceGroup().id, 'jwt', environmentName) }
        { name: 'openai-key', value: deployAiServices ? openAi.listKeys().key1 : '' }
        { name: 'cognitive-key', value: deployAiServices ? aiServices.listKeys().key1 : '' }
        { name: 'storage-connection', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: {
            cpu: json(environmentName == 'prod' ? '2.0' : '1.0')
            memory: environmentName == 'prod' ? '4Gi' : '2Gi'
          }
          env: [
            { name: 'SHOPPERMIND_ENV', value: environmentName }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'API_SECRET_KEY', secretRef: 'api-secret-key' }
            { name: 'CORS_ORIGINS', value: 'https://${appName}.${containerEnv.properties.defaultDomain}' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection' }
            { name: 'AZURE_STORAGE_CONTAINER', value: 'shoppermind-media' }
            { name: 'AZURE_OPENAI_ENDPOINT', value: deployAiServices ? openAi.properties.endpoint : '' }
            { name: 'AZURE_OPENAI_API_KEY', secretRef: 'openai-key' }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatModel }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: 'text-embedding-3-large' }
            { name: 'AZURE_SPEECH_KEY', secretRef: 'cognitive-key' }
            { name: 'AZURE_SPEECH_REGION', value: location }
            { name: 'AZURE_VISION_ENDPOINT', value: deployAiServices ? aiServices.properties.endpoint : '' }
            { name: 'AZURE_VISION_KEY', secretRef: 'cognitive-key' }
            { name: 'AZURE_LANGUAGE_ENDPOINT', value: deployAiServices ? aiServices.properties.endpoint : '' }
            { name: 'AZURE_LANGUAGE_KEY', secretRef: 'cognitive-key' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 20
              periodSeconds: 30
            }
            {
              // Readiness checks the database, so a replica with no DB never takes traffic.
              type: 'Readiness'
              httpGet: { path: '/ready', port: 8000 }
              initialDelaySeconds: 10
              periodSeconds: 15
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: environmentName == 'prod' ? 2 : 1
        maxReplicas: environmentName == 'prod' ? 10 : 3
        rules: [
          {
            name: 'http-concurrency'
            http: { metadata: { concurrentRequests: '40' } }
          }
        ]
      }
    }
  }
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${apiIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: { external: true, targetPort: 3000, transport: 'auto' }
      registries: [
        { server: registry.properties.loginServer, identity: apiIdentity.id }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'NEXT_PUBLIC_API_URL', value: 'https://${appName}-api.${containerEnv.properties.defaultDomain}' }
            { name: 'NODE_ENV', value: 'production' }
          ]
        }
      ]
      scale: {
        minReplicas: environmentName == 'prod' ? 2 : 1
        maxReplicas: environmentName == 'prod' ? 6 : 2
      }
    }
  }
}

// ── outputs ─────────────────────────────────────────────────────────────────
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output webUrl string = 'https://${web.properties.configuration.ingress.fqdn}'
output registryLoginServer string = registry.properties.loginServer
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output keyVaultName string = keyVault.name
output aiServicesDeployed bool = deployAiServices
