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
  }

  virtual_network_subnet_id = data.azurerm_subnet.subscription-vnet-sub.id

  # just run zip package.zip function_app.py requirements.txt host.json
  zip_deploy_file = var.zip_deploy_file

}