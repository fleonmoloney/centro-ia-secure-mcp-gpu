variable "project_id" {
  type        = string
  description = "Proyecto de GCP"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type        = string
  default     = "us-central1-a"
  description = "Zona con GPU T4 disponible (verificar cuota y disponibilidad)"
}

variable "machine_type" {
  type    = string
  default = "n1-standard-4"
}

variable "gpu_type" {
  type    = string
  default = "nvidia-tesla-t4"
}

variable "image" {
  type        = string
  description = "Imagen del servicio, por ejemplo ghcr.io/<usuario>/centro-ia-secure-mcp-gpu:latest (variante GPU)"
}

variable "model_id" {
  type    = string
  default = "Qwen/Qwen2.5-1.5B-Instruct"
}

variable "serve_api_key" {
  type        = string
  sensitive   = true
  description = "Clave de API del servicio de modelos"
}

variable "allowed_cidrs" {
  type        = list(string)
  description = "Rangos autorizados a llegar al puerto 8000. No hay valor por defecto a propósito."
}

variable "spot" {
  type        = bool
  default     = true
  description = "Instancia spot: más barata y puede ser interrumpida"
}
