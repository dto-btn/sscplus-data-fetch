variable "default_location" {
    type    = string
    default = "canadacentral"
}

variable "personal_token" {
    type        = string
    sensitive   = true
    description = "used for direct github connection to repository for ci/cd"
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