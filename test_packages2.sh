#!/bin/bash
PACKAGES=(
  "libaio1.*"
  "libgssapi3-heimdal"
  "libhcrypto4-heimdal"
  "libheimbase1-heimdal"
  "libheimntlm0-heimdal"
  "libhx509-5-heimdal"
  "libkrb5-26-heimdal"
  "libroken18-heimdal"
  "libwind0-heimdal"
)
for pkg in "${PACKAGES[@]}"; do
  echo "Checking $pkg:"
  apt-cache search "^${pkg}$" | head -n 3
  echo "---"
done
