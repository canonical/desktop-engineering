#!/usr/bin/env bash
set -eux

# Disable installing of manpages and docs
cat <<"EOF" | tee /etc/dpkg/dpkg.cfg.d/01_nodoc
# Delete man pages
path-exclude=/usr/share/man/*

# Delete docs
path-exclude=/usr/share/doc/*
path-include=/usr/share/doc/*/copyright
EOF

echo 'APT::Get::Assume-Yes "true";' > /etc/apt/apt.conf.d/90aptyes
apt update

# Install ca-certificates to ensure that APT can access HTTPS repos
apt install ca-certificates
# Update package lists again, to ensure that we also have lists from HTTPS repos
apt update

locales_required_check=$(dirname "$0")/.locales-required
if ! [ -e "${locales_required_check}" ] && [ -f ./debian/control ]; then
  apt install dctrl-tools
  build_deps=$(grep-dctrl -s Build-Depends -n - ./debian/control)

  locales_needed=false
  if echo "${build_deps}" | grep -Fqs language-pack ||
      echo "${build_deps}" | grep -Fqs locales; then
      locales_needed=true
  fi

  # We can't use ${GITHUB_ENV} here, because the github ${{ env.XXX }} variables
  # arent't visible here, and we don't want to expose each one at call time.
  echo "${locales_needed}" > "${locales_required_check}"
fi

if [ "$(cat "${locales_required_check}" || true)" != "true" ]; then
  # Disable installing of locale files
  cat <<"EOF" | tee /etc/dpkg/dpkg.cfg.d/01_nolocales
# Delete locales
path-exclude=/usr/share/locale/*
EOF
fi

apt dist-upgrade

eatmydata_check=$(dirname "$0")/.use-eatmydata
if [ "$(cat "${eatmydata_check}" || true)" == "true" ]; then
  # Install and use eatmydata
  apt install eatmydata

  mkdir -p "/usr/local/libexec/dt-deb-action"
  ln -s /usr/bin/eatmydata /usr/local/libexec/dt-deb-action/dpkg
  echo 'Dir::Bin::dpkg /usr/local/libexec/dt-deb-action/dpkg;' > \
    /etc/apt/apt.conf.d/00dt-deb-action-eatmydata
fi
