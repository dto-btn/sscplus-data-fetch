variable "default_location" {
    type    = string
    default = "canadacentral"
}

variable "personal_token" {
    type        = string
    sensitive   = true
    description = "used for direct github connection to repository for ci/cd (bad trying to get rid of this...)"
}

variable "project_name" {
    type = string
    description = "the name of the project example ProjectA"
}

variable "project_name_short" {
    type = string
    description = "short name of the project"
}

variable "name_prefix" {
    type = string
    description = "this is to properly identify resources in Azure, starts with the 4 letters with sub type, dept and location. ex: ScSc-CIO_ECT"
}

variable "env" {
    type = string
    description = "typically the env like Sandbox, Dev or Production"
}

variable "zip_deploy_file" {
    type = string
    description = "the location of the package.zip that contains the file to deploy to an Azure Function App"
}

variable "openai_rg" {
    type = string
}

variable "openai_name" {
    type = string
}

variable "fileshare_name" {
    type = string
    description = "the fileshare name that will be used to copy the files over. this is the fileshare that is used by the chatbot"
}

variable "fileshare_connection_string" {
    type = string
    description = "connection string for fs above"
    sensitive   = true
}