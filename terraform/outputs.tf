output "backend_url" {
  description = "Cloud Run backend URL (set as NEXT_PUBLIC_API_URL in frontend)"
  value       = google_cloud_run_v2_service.backend.uri
}

output "worker_ip" {
  description = "GCE worker public IP (set as WORKER_STREAM_URL in backend: http://<ip>:8090)"
  value       = google_compute_instance.worker.network_interface[0].access_config[0].nat_ip
}

output "gcs_bucket" {
  description = "GCS bucket name for event snapshots and clips"
  value       = google_storage_bucket.events.name
}

output "artifact_registry" {
  description = "Artifact Registry host for Docker images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.nightwatch.repository_id}"
}

output "backend_service_account" {
  description = "Backend service account email (for Cloud Run identity)"
  value       = google_service_account.backend.email
}

output "worker_service_account" {
  description = "Worker service account email (for GCE identity + GCS writes)"
  value       = google_service_account.worker.email
}

output "next_steps" {
  description = "What to do after terraform apply"
  value       = <<-EOT
    1. Update frontend env:
         NEXT_PUBLIC_API_URL=${google_cloud_run_v2_service.backend.uri}
       Then redeploy frontend (Vercel: push to main or run `vercel --prod`)

    2. Update backend env (already in Secret Manager, but set locally too):
         WORKER_STREAM_URL=http://${google_compute_instance.worker.network_interface[0].access_config[0].nat_ip}:8090

    3. Run alembic migrations against your production DB:
         DATABASE_URL=<prod-url> alembic upgrade head

    4. SSH to worker and verify the container started:
         gcloud compute ssh nightwatch-worker --zone=${var.worker_zone}
         docker ps
         docker logs nightwatch-worker
  EOT
}
