output "serving_ip" {
  value       = google_compute_instance.serving.network_interface[0].access_config[0].nat_ip
  description = "IP pública del servicio (restringida por allowed_cidrs)"
}
