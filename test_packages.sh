#!/bin/bash
PACKAGES=(
  "libpcre2-8-0"
  "libasn1-8-heimdal"
  "libicu"
  "libpng16-16"
  "libpsl5"
  "libzip5"
  "libsodium23"
  "libaio1"
  "libicu[0-9]*"
  "libzip[0-9]*"
  "gcc-[0-9]*"
)
for pkg in "${PACKAGES[@]}"; do
  echo "Checking $pkg:"
  apt-cache search "^${pkg}$" | head -n 3
  echo "---"
done
