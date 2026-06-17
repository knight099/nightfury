variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run and other regional resources"
  type        = string
  default     = "asia-south1"
}

variable "gcs_bucket" {
  description = "GCS bucket name for event snapshots and clips"
  type        = string
  default     = "nightwatch-events"
}

variable "backend_image" {
  description = "Docker image URI for the backend (Artifact Registry)"
  type        = string
}

variable "worker_image" {
  description = "Docker image URI for the worker (Artifact Registry)"
  type        = string
}

variable "database_url" {
  description = "PostgreSQL connection URL (Neon or Cloud SQL)"
  type        = string
  sensitive   = true
}

variable "redis_url" {
  description = "Redis connection URL (Upstash or Cloud Memorystore)"
  type        = string
  sensitive   = true
}

variable "secret_key" {
  description = "AES-256 session encryption key (64 hex chars)"
  type        = string
  sensitive   = true
}

variable "worker_api_key" {
  description = "Static API key for worker → backend internal endpoints"
  type        = string
  sensitive   = true
}

variable "stream_token_secret" {
  description = "HMAC secret shared between backend and worker for stream URL signing"
  type        = string
  sensitive   = true
}

variable "gemini_api_key" {
  description = "Google AI Studio API key for Gemini (fallback if Vertex auth fails)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "sendgrid_api_key" {
  description = "SendGrid API key for email alerts"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gupshup_api_key" {
  description = "Gupshup API key for WhatsApp alerts"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gupshup_app_name" {
  description = "Gupshup app name for WhatsApp"
  type        = string
  default     = ""
}

variable "whatsapp_business_number" {
  description = "WhatsApp Business number for outbound alerts"
  type        = string
  default     = ""
}

variable "super_admin_username" {
  description = "Bootstrap super admin username"
  type        = string
  sensitive   = true
}

variable "super_admin_password" {
  description = "Bootstrap super admin password"
  type        = string
  sensitive   = true
}

variable "worker_zone" {
  description = "GCP zone for the worker GCE instance"
  type        = string
  default     = "asia-south1-a"
}

variable "worker_machine_type" {
  description = "GCE machine type for worker (2 vCPU minimum for FFmpeg)"
  type        = string
  default     = "e2-standard-2"
}

variable "worker_disk_size_gb" {
  description = "Boot disk size in GB for worker instance"
  type        = number
  default     = 50
}

variable "backend_min_instances" {
  description = "Minimum Cloud Run instances (1 keeps WebSocket sessions alive)"
  type        = number
  default     = 1
}

variable "backend_max_instances" {
  description = "Maximum Cloud Run instances"
  type        = number
  default     = 10
}

variable "backend_concurrency" {
  description = "Max concurrent requests per Cloud Run instance"
  type        = number
  default     = 100
}
