/****************************************************
*                       VNET                        *
*****************************************************/
# resource "azurerm_network_security_group" "main" {
#   name                = "${var.name_prefix}_${var.project_name}-sg"
#   location            = var.default_location
#   resource_group_name = azurerm_resource_group.main.name
# }

# resource "azurerm_virtual_network" "main" {
#   name                = "${var.name_prefix}_${var.project_name}-vnet"
#   location            = var.default_location
#   resource_group_name = azurerm_resource_group.main.name
#   address_space       = [ "10.2.0.0/16" ]
#   //Using Azure's Default DNS IP.
#   dns_servers         = []

#   tags = {
#     environment = var.env
#   }
# }

/*
Mapping to the already existing vnet and OZ zone
*/
data "azurerm_virtual_network" "subscription-vnet" {
  name    = "ScScCNR-CIO_ECT-vnet"
  resource_group_name = "ScSc-CIO_ECT_SSCPlusData-rg"
}

data "azurerm_subnet" "subscription-vnet-sub" {
  name                  = "ScScCNR-CIO_ECT_OZ-snet"
  virtual_network_name  = "ScScCNR-CIO_ECT-vnet"
  resource_group_name   = "ScSc-CIO_ECT_SSCPlusData-rg"
}

# add nic, and private endpoint yada yada