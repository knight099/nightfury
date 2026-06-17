terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Store state in GCS — create the bucket manually before first `terraform init`
  # backend "gcs" {
  #   bucket = "nightwatch-terraform-state"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ── Enable required APIs ───────────────────────────────────────────────────────

resource "google_project_service" "run" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam_credentials" {
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "secret_manager" {
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "compute" {
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

# ── Artifact Registry (Docker images) ─────────────────────────────────────────

resource "google_artifact_registry_repository" "nightwatch" {
  location      = var.region
  repository_id = "nightwatch"
  description   = "Nightwatch Docker images"
  format        = "DOCKER"
  depends_on    = [google_project_service.artifact_registry]
}

# ── GCS Bucket ────────────────────────────────────────────────────────────────

resource "google_storage_bucket" "events" {
  name                        = var.gcs_bucket
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition { age = 90 }
    action { type = "Delete" }
  }

  cors {
    origin          = ["*"]
    method          = ["GET"]
    response_header = ["*"]
    max_age_seconds = 3600
  }
}

# ── Service Account: Backend ───────────────────────────────────────────────────
# Needs storage.objectViewer to read blobs and iam.serviceAccountTokenCreator
# on itself to sign V4 URLs.

resource "google_service_account" "backend" {
  account_id   = "nightwatch-backend"
  display_name = "Nightwatch Backend (Cloud Run)"
}

resource "google_storage_bucket_iam_member" "backend_gcs_viewer" {
  bucket = google_storage_bucket.events.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_storage_bucket_iam_member" "backend_gcs_creator" {
  bucket = google_storage_bucket.events.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.backend.email}"
}

# Allow the service account to sign its own tokens (needed for V4 signed URLs)
resource "google_service_account_iam_member" "backend_token_creator" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.backend.email}"
}

# ── Service Account: Worker ────────────────────────────────────────────────────

resource "google_service_account" "worker" {
  account_id   = "nightwatch-worker"
  display_name = "Nightwatch Worker (GCE)"
}

resource "google_storage_bucket_iam_member" "worker_gcs_admin" {
  bucket = google_storage_bucket.events.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.worker.email}"
}

# Pull images from Artifact Registry
resource "google_artifact_registry_repository_iam_member" "worker_reader" {
  location   = google_artifact_registry_repository.nightwatch.location
  repository = google_artifact_registry_repository.nightwatch.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.worker.email}"
}

# ── Cloud Run: Backend ─────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "backend" {
  name     = "nightwatch-backend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  depends_on = [google_project_service.run]

  template {
    service_account = google_service_account.backend.email

    scaling {
      min_instance_count = var.backend_min_instances
      max_instance_count = var.backend_max_instances
    }

    containers {
      image = var.backend_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        startup_cpu_boost = true
      }

      ports {
        container_port = 8080
      }

      # Application config
      env { name = "DEBUG";              value = "false" }
      env { name = "GCS_BUCKET";         value = var.gcs_bucket }
      env { name = "GCS_PROJECT";        value = var.project_id }
      env { name = "GEMINI_MODEL";       value = "gemini-2.0-flash" }
      env { name = "RATE_LIMIT_ENABLED"; value = "true" }

      # Secrets injected from Secret Manager
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "REDIS_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.redis_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secret_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "WORKER_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.worker_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "STREAM_TOKEN_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.stream_token_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SUPER_ADMIN_USERNAME"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.super_admin_username.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SUPER_ADMIN_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.super_admin_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SENDGRID_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.sendgrid_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GUPSHUP_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gupshup_api_key.secret_id
            version = "latest"
          }
        }
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 15
        period_seconds        = 30
        failure_threshold     = 3
      }

      startup_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 10
      }
    }
  }

  lifecycle {
    ignore_changes = [
      # Image is updated by CI/CD, not Terraform
      template[0].containers[0].image,
    ]
  }
}

# Allow unauthenticated (public) access to the backend API
resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  name     = google_cloud_run_v2_service.backend.name
  location = google_cloud_run_v2_service.backend.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Grant backend service account access to Secret Manager secrets
resource "google_project_iam_member" "backend_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# ── GCE Worker Instance ────────────────────────────────────────────────────────

resource "google_compute_instance" "worker" {
  name         = "nightwatch-worker"
  machine_type = var.worker_machine_type
  zone         = var.worker_zone

  depends_on = [google_project_service.compute]

  tags = ["nightwatch-worker"]

  boot_disk {
    initialize_params {
      image = "projects/cos-cloud/global/images/family/cos-stable"
      size  = var.worker_disk_size_gb
      type  = "pd-ssd"
    }
  }

  # Persistent disk for SQLite offline queue and GCS credentials
  attached_disk {
    source      = google_compute_disk.worker_data.self_link
    device_name = "data"
    mode        = "READ_WRITE"
  }

  network_interface {
    network = "default"
    access_config {
      # Ephemeral public IP — attach a static IP in production
    }
  }

  service_account {
    email  = google_service_account.worker.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    user-data = templatefile("${path.module}/worker-cloud-init.yaml", {
      worker_image        = var.worker_image
      backend_url         = google_cloud_run_v2_service.backend.uri
      worker_api_key      = var.worker_api_key
      stream_token_secret = var.stream_token_secret
      gcs_bucket          = var.gcs_bucket
      gcs_project         = var.project_id
      gemini_api_key      = var.gemini_api_key
    })
  }

  metadata_startup_script = null
  allow_stopping_for_update = true
}

resource "google_compute_disk" "worker_data" {
  name  = "nightwatch-worker-data"
  type  = "pd-ssd"
  zone  = var.worker_zone
  size  = 20

  lifecycle {
    prevent_destroy = true
  }
}

# Firewall: allow RTMP ingest from NVR cameras
resource "google_compute_firewall" "worker_rtmp" {
  name    = "nightwatch-worker-rtmp"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["1935"]
  }

  target_tags   = ["nightwatch-worker"]
  source_ranges = ["0.0.0.0/0"]
  description   = "RTMP push from NVR cameras to worker"
}

# Firewall: allow MJPEG stream from worker (accessed by frontend via signed URL)
resource "google_compute_firewall" "worker_mjpeg" {
  name    = "nightwatch-worker-mjpeg"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["8090"]
  }

  target_tags   = ["nightwatch-worker"]
  source_ranges = ["0.0.0.0/0"]
  description   = "MJPEG live stream (signed token required)"
}

# ── Secret Manager ─────────────────────────────────────────────────────────────

locals {
  secrets = {
    database_url         = var.database_url
    redis_url            = var.redis_url
    secret_key           = var.secret_key
    worker_api_key       = var.worker_api_key
    stream_token_secret  = var.stream_token_secret
    super_admin_username = var.super_admin_username
    super_admin_password = var.super_admin_password
    gemini_api_key       = var.gemini_api_key
    sendgrid_api_key     = var.sendgrid_api_key
    gupshup_api_key      = var.gupshup_api_key
  }
}

resource "google_secret_manager_secret" "database_url" {
  secret_id  = "nightwatch-database-url"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = var.database_url
}

resource "google_secret_manager_secret" "redis_url" {
  secret_id  = "nightwatch-redis-url"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "redis_url" {
  secret      = google_secret_manager_secret.redis_url.id
  secret_data = var.redis_url
}

resource "google_secret_manager_secret" "secret_key" {
  secret_id  = "nightwatch-secret-key"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "secret_key" {
  secret      = google_secret_manager_secret.secret_key.id
  secret_data = var.secret_key
}

resource "google_secret_manager_secret" "worker_api_key" {
  secret_id  = "nightwatch-worker-api-key"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "worker_api_key" {
  secret      = google_secret_manager_secret.worker_api_key.id
  secret_data = var.worker_api_key
}

resource "google_secret_manager_secret" "stream_token_secret" {
  secret_id  = "nightwatch-stream-token-secret"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "stream_token_secret" {
  secret      = google_secret_manager_secret.stream_token_secret.id
  secret_data = var.stream_token_secret
}

resource "google_secret_manager_secret" "super_admin_username" {
  secret_id  = "nightwatch-super-admin-username"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "super_admin_username" {
  secret      = google_secret_manager_secret.super_admin_username.id
  secret_data = var.super_admin_username
}

resource "google_secret_manager_secret" "super_admin_password" {
  secret_id  = "nightwatch-super-admin-password"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "super_admin_password" {
  secret      = google_secret_manager_secret.super_admin_password.id
  secret_data = var.super_admin_password
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id  = "nightwatch-gemini-api-key"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "gemini_api_key" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = var.gemini_api_key
}

resource "google_secret_manager_secret" "sendgrid_api_key" {
  secret_id  = "nightwatch-sendgrid-api-key"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "sendgrid_api_key" {
  secret      = google_secret_manager_secret.sendgrid_api_key.id
  secret_data = var.sendgrid_api_key
}

resource "google_secret_manager_secret" "gupshup_api_key" {
  secret_id  = "nightwatch-gupshup-api-key"
  depends_on = [google_project_service.secret_manager]
  replication { auto {} }
}
resource "google_secret_manager_secret_version" "gupshup_api_key" {
  secret      = google_secret_manager_secret.gupshup_api_key.id
  secret_data = var.gupshup_api_key
}
