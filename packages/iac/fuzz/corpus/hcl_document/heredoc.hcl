locals {
  ordinary = <<EOT
literal { text }
EOT
  indented = <<-VALUE
    ${not_a_block}
  VALUE
}
