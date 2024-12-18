#!/usr/bin/env bash
set -eux

echo 'APT::Get::Assume-Yes "true";' > /etc/apt/apt.conf.d/90aptyes
apt update
apt dist-upgrade
