variable "project_name" {
  description = "Name prefix used for all resources in this sandbox"
  type        = string
  default     = "tf-ai-reviewer"
}

variable "environment" {
  description = "Environment label used for tagging sandbox resources"
  type        = string
  default     = "sandbox"
}