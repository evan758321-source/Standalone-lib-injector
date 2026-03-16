FROM python:3.12-slim

# Install Java
RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jdk-headless curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Download tools at build time
RUN mkdir -p tools && \
    curl -fL "https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar" \
         -o tools/apktool.jar && \
    curl -fL "https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar" \
         -o tools/signer.jar

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

EXPOSE 10000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--timeout", "600", "--workers", "1"]
