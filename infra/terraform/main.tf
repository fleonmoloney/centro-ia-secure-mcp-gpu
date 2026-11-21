resource "google_service_account" "serving" {
  account_id   = "secmcp-serving"
  display_name = "Servicio de modelos (mínimo privilegio)"
}

resource "google_compute_firewall" "serving" {
  name          = "secmcp-serving-8000"
  network       = "default"
  source_ranges = var.allowed_cidrs
  target_tags   = ["secmcp-serving"]

  allow {
    protocol = "tcp"
    ports    = ["8000"]
  }
}

resource "google_compute_instance" "serving" {
  name         = "secmcp-serving"
  machine_type = var.machine_type
  tags         = ["secmcp-serving"]

  boot_disk {
    initialize_params {
      # Imagen de Deep Learning VM con controladores NVIDIA y Docker. Verificar la familia vigente.
      image = "projects/deeplearning-platform-release/global/images/family/common-cu124-ubuntu-2204"
      size  = 100
    }
  }

  guest_accelerator {
    type  = var.gpu_type
    count = 1
  }

  scheduling {
    on_host_maintenance = "TERMINATE"
    automatic_restart   = !var.spot
    preemptible         = var.spot
    provisioning_model  = var.spot ? "SPOT" : "STANDARD"
  }

  network_interface {
    network = "default"
    access_config {}
  }

  service_account {
    email  = google_service_account.serving.email
    scopes = ["logging-write", "monitoring-write"]
  }

  shielded_instance_config {
    enable_secure_boot          = false # los controladores NVIDIA de la imagen no están firmados para Secure Boot
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  metadata = {
    serve-api-key = var.serve_api_key
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    set -euo pipefail
    KEY=$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/serve-api-key)
    docker rm -f secmcp 2>/dev/null || true
    docker run -d --name secmcp --restart unless-stopped --gpus all -p 8000:8000 \
      -e SERVE_API_KEY="$KEY" -e MODEL_ID="${var.model_id}" -v /opt/models:/models \
      ${var.image}
  EOT
}
