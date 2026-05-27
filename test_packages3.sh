#!/bin/bash
PACKAGES=(
  "libhcrypto[0-9]*.*heimdal"
  "libroken[0-9]*.*heimdal"
)
for pkg in "${PACKAGES[@]}"; do
  echo "Checking $pkg:"
  apt-cache search "^${pkg}$" | head -n 3
  echo "---"
done
