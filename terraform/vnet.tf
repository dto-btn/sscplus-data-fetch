/****************************************************
*                       VNET                        *
*****************************************************/
/*
  Mapping to the already existing vnet and PAZ zone
  TODO: this needs to be converted to variables idealy so 
  this code can be re-usable
*/
data "azurerm_virtual_network" "subscription-vnet" {
  name    = "ScScCNR-CIO_ECT-vnet"
  resource_group_name = "ScSc-CIO_ECT_Network-rg"
}

data "azurerm_subnet" "subscription-vnet-sub" {
  name                  = "ScScCNR-CIO_ECT_PAZ-snet"
  virtual_network_name  = "ScScCNR-CIO_ECT-vnet"
  resource_group_name   = "ScSc-CIO_ECT_Network-rg"
}