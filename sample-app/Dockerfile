# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=extra_ca,required=false if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca SSL_CERT_FILE=/run/secrets/extra_ca; fi; pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN useradd -r app
USER app
EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
