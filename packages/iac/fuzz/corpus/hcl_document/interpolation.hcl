output "quoted" {
  value = "prefix ${var.value == \"quoted\"} suffix"
}
