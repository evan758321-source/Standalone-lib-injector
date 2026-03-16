#!/usr/bin/env bash
set -e

echo "==> Installing Java..."
apt-get update -qq && apt-get install -y -qq default-jre-headless

echo "==> Creating tool dirs..."
mkdir -p /opt/apktool /opt/uber-apk-signer

echo "==> Downloading apktool..."
APKTOOL_VERSION="2.9.3"
curl -sL "https://github.com/iBotPeaches/Apktool/releases/download/v${APKTOOL_VERSION}/apktool_${APKTOOL_VERSION}.jar" \
     -o /opt/apktool/apktool.jar

echo "==> Downloading uber-apk-signer..."
SIGNER_VERSION="1.3.0"
curl -sL "https://github.com/patrickfav/uber-apk-signer/releases/download/v${SIGNER_VERSION}/uber-apk-signer-${SIGNER_VERSION}.jar" \
     -o /opt/uber-apk-signer/uber-apk-signer.jar

echo "==> Installing Python deps..."
pip install -r requirements.txt

echo "==> Build complete."
