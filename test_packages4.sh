#!/bin/bash
PACKAGES=(
  "libldap-[0-9].*"
  "libnghttp2-[0-9]*"
  "librtmp[0-9]*"
  "libonig[0-9]*"
  "libsasl2-[0-9]*"
)
for pkg in "${PACKAGES[@]}"; do
  echo "Checking $pkg:"
  apt-cache search "^${pkg}$" | head -n 3
  echo "---"
done
