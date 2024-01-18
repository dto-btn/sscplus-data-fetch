/****************************************************
*                       RG                          *
*****************************************************/
resource "azurerm_resource_group" "main" {
  name     = "${var.name_prefix}_${var.project_name}-rg"
  location = var.default_location

  tags = {
    environment = var.env
  }
}

resource "azurerm_source_control_token" "sscplus-data-fetch" {
  type = "GitHub"
  token = var.personal_token
}

/****************************************************
*                STORAGE / KEYVAULT                 *
*****************************************************/
resource "azurerm_storage_account" "main" {
  name                     = "${lower(var.project_name_short)}storage"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  tags = {
    environment = var.env
  }
}

resource "azurerm_data_protection_backup_vault" "main" {
  name                = "${lower(var.project_name_short)}-backup-vault"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  datastore_type      = "VaultStore"
  redundancy          = "LocallyRedundant"

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "storage_account_role" {  
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Account Backup Contributor"
  principal_id         = azurerm_data_protection_backup_vault.main.identity[0].principal_id
}

resource "azurerm_data_protection_backup_policy_blob_storage" "main" {
  name               = "${lower(var.project_name_short)}-backup-policy"
  vault_id           = azurerm_data_protection_backup_vault.main.id
  retention_duration = "P90D"
}

resource "azurerm_data_protection_backup_instance_blob_storage" "main" {
  name               = "${lower(var.project_name_short)}-backup-instance"
  vault_id           = azurerm_data_protection_backup_vault.main.id
  location           = azurerm_resource_group.main.location
  storage_account_id = azurerm_storage_account.main.id
  backup_policy_id   = azurerm_data_protection_backup_policy_blob_storage.main.id

  depends_on = [azurerm_role_assignment.storage_account_role]
}

resource "azurerm_storage_container" "main" {
  name                  = "sscplusdata"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "indices" {
  name                  = "indices"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

data "azurerm_cognitive_account" "ai" {
  name                = var.openai_name
  resource_group_name = var.openai_rg
}

/****************************************************
*                  Function App                     *
*****************************************************/
resource "azurerm_application_insights" "main" {
  name                = "sscplus-data-fetch-app-insights"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"
}

resource "azurerm_service_plan" "main" {
  name                = "${replace(var.name_prefix, "_", "")}${var.project_name}-plan"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "P1v3"
}

resource "azurerm_linux_function_app" "main" {
  name                = "sscplus-data-fetch"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  storage_account_name       = azurerm_storage_account.main.name
  storage_account_access_key = azurerm_storage_account.main.primary_access_key
  service_plan_id            = azurerm_service_plan.main.id

  site_config {
    always_on = false
    vnet_route_all_enabled = true
    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = {
    "AzureWebJobsFeatureFlags"       = "EnableWorkerIndexing"
    "APPINSIGHTS_INSTRUMENTATIONKEY" = azurerm_application_insights.main.instrumentation_key
    "BUILD_FLAGS"                    = "UseExpressBuild"
    "ENABLE_ORYX_BUILD"              = "true"
    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "1"
    "XDG_CACHE_HOME"                 = "/tmp/.cache"
    "StorageConnectionString"        = azurerm_storage_account.main.primary_connection_string
    "AzureOpenAIEndpoint"            = data.azurerm_cognitive_account.ai.endpoint
    "AzureOpenAIKey"                 = data.azurerm_cognitive_account.ai.primary_access_key
    "FILESHARE_CONNECTION_STRING"    = var.fileshare_connection_string
    "FILESHARE_NAME"                 = var.fileshare_name
  }

  virtual_network_subnet_id = data.azurerm_subnet.subscription-vnet-sub.id

  # just run zip package.zip function_app.py requirements.txt host.json
  zip_deploy_file = var.zip_deploy_file

}