#!/usr/bin/env bash
set -e

echo "==> Installing Python deps..."
pip install -r requirements.txt

echo "==> Creating tools dir inside project..."
mkdir -p tools

echo "==> Downloading apktool..."
APKTOOL_VERSION="2.9.3"
curl -fL "https://github.com/iBotPeaches/Apktool/releases/download/v${APKTOOL_VERSION}/apktool_${APKTOOL_VERSION}.jar" \
     -o tools/apktool.jar
echo "    apktool: $(du -sh tools/apktool.jar)"

echo "==> Downloading uber-apk-signer..."
SIGNER_VERSION="1.3.0"
curl -fL "https://github.com/patrickfav/uber-apk-signer/releases/download/v${SIGNER_VERSION}/uber-apk-signer-${SIGNER_VERSION}.jar" \
     -o tools/signer.jar
echo "    signer: $(du -sh tools/signer.jar)"

echo "==> Build complete."
