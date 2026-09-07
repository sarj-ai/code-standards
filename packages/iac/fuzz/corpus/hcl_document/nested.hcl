resource "service" "example" {
  enabled = true
  policy {
    retries = 3
  }
}
