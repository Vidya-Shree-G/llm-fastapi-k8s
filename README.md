# LLM FastAPI Kubernetes

A secure FastAPI service for serving LLM requests behind a Kubernetes deployment, with JWT-based authentication, Prometheus metrics, Grafana dashboards, and CPU-based autoscaling.

## Overview

This project provides a production-oriented pattern for exposing an LLM through an API layer:

- FastAPI app with authenticated request handling
- JWT/OIDC validation and scope enforcement
- request size and rate limiting
- upstream forwarding to a vLLM inference service
- Kubernetes deployment manifests
- Prometheus metrics collection
- Grafana dashboard for observability
- Horizontal Pod Autoscaler for CPU-based scaling

## Architecture

```text
Client
  |
  v
FastAPI API
  - validates JWT
  - checks scopes
  - enforces rate limits
  - forwards prompt to vLLM
  |
  v
vLLM service
```

The API exposes a `/generate` endpoint that validates access and forwards requests to the configured model backend. Metrics are exported from the FastAPI app and can be scraped by Prometheus.

## Features

- Secure API layer with OIDC-style JWT validation
- Required scope checks for protected routes
- Rate limiting per client
- Request body size restrictions
- `/health` and `/ready` endpoints for health checks
- `/metrics` endpoint for Prometheus scraping
- `/whoami` endpoint for inspecting token claims
- Kubernetes manifests for deployment and scaling
- Grafana and Prometheus monitoring setup

## Repository structure

```text
.
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   └── security.py
├── k8s/
│   ├── fastapi-deployment.yaml
│   ├── fastapi-hpa.yaml
│   ├── fastapi-service.yaml
│   ├── metrics-server-apiservice.yaml
│   ├── metrics-server-deployment.yaml
│   ├── metrics-server-service.yaml
│   ├── metrics-server-serviceaccount.yaml
│   ├── vllm-deployment.yaml
│   ├── vllm-service.yaml
│   └── monitoring/
│       ├── grafana-config.yaml
│       ├── grafana-dashboard-configmap.yaml
│       ├── grafana-dashboard-provider-configmap.yaml
│       ├── grafana-deployment.yaml
│       ├── grafana-service.yaml
│       ├── grafana-dashboard.json
│       ├── prometheus-config.yaml
│       ├── prometheus-deployment.yaml
│       ├── prometheus-service-monitor.yaml
│       └── prometheus-service.yaml
├── Dockerfile
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
└── .venv/
```

## Requirements

- Python 3.11+
- pip
- Docker
- Kubernetes cluster or local cluster such as `kind` or `minikube`
- `kubectl`

## Local setup

### 1. Create and activate a virtual environment

```bash
cd llm-fastapi-k8s
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Typical local settings:

```bash
export VLLM_URL=http://localhost:8000
export AUTH_MODE=disabled
```

For OIDC mode, set:

```bash
export AUTH_MODE=oidc
export OIDC_ISSUER="https://issuer.example.com"
export OIDC_AUDIENCE="api://llm-fastapi"
export OIDC_JWKS_URL="https://issuer.example.com/.well-known/jwks.json"
```

### 4. Start the backend model service

Make sure a vLLM inference service is running and reachable at `http://localhost:8000` or the URL configured in `VLLM_URL`.

### 5. Run the API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

The app is available at:

- http://localhost:8080
- http://localhost:8080/docs

## API endpoints

- `GET /health` — application health status
- `GET /ready` — readiness status for probes
- `POST /generate` — protected generation endpoint
- `GET /whoami` — returns token subject and scope information
- `GET /metrics` — Prometheus metrics

Example request:

```bash
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Explain Kubernetes in one short paragraph.","max_tokens":80}'
```

When auth is enabled, include a bearer token:

```bash
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"prompt":"Explain Kubernetes in one short paragraph.","max_tokens":80}'
```

## Security model

The API enforces the following protections:

- JWT/OIDC validation with JWKS-based key verification
- issuer and audience validation
- required scope checks for protected routes
- request size limits
- per-client rate limiting

The security logic lives in `app/security.py` and the runtime settings live in `app/config.py`.

## Kubernetes deployment

Build the image:

```bash
docker build -t llm-fastapi:latest .
```

Apply the manifests:

```bash
kubectl apply -f k8s/
```

Verify the deployment:

```bash
kubectl get pods
kubectl get svc
kubectl logs deployment/fastapi
```

Optional local access:

```bash
kubectl port-forward svc/fastapi 8080:8080
```

## Monitoring

### Prometheus

Deploy the metrics server and Prometheus stack:

```bash
kubectl apply -f k8s/metrics-server-serviceaccount.yaml
kubectl apply -f k8s/metrics-server-deployment.yaml
kubectl apply -f k8s/metrics-server-service.yaml
kubectl apply -f k8s/metrics-server-apiservice.yaml
kubectl apply -f k8s/monitoring/prometheus-config.yaml
kubectl apply -f k8s/monitoring/prometheus-deployment.yaml
kubectl apply -f k8s/monitoring/prometheus-service.yaml
kubectl apply -f k8s/monitoring/prometheus-service-monitor.yaml
```

Then verify the target in Prometheus:

```bash
kubectl port-forward svc/prometheus 9090:9090
```

Open http://localhost:9090 and inspect the targets page.

### Grafana

```bash
kubectl apply -f k8s/monitoring/grafana-config.yaml
kubectl apply -f k8s/monitoring/grafana-dashboard-provider-configmap.yaml
```

Access Grafana:

```bash
kubectl port-forward svc/grafana 3000:3000
```

Then open http://localhost:3000 with:

- username: `admin`
- password: `admin`

## Autoscaling

A CPU-based Horizontal Pod Autoscaler is included at `k8s/fastapi-hpa.yaml`.

Apply it:

```bash
kubectl apply -f k8s/fastapi-hpa.yaml
```

Check status:

```bash
kubectl get hpa
kubectl describe hpa fastapi
```

## Notes

This project is intended as a practical foundation for deploying an LLM API in Kubernetes. It is suitable for local development and cluster-based demos, and it is structured to be extended with additional security, tracing, or custom autoscaling strategies.

## Quick command summary

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

docker build -t llm-fastapi:latest .
kubectl apply -f k8s/
kubectl get pods
kubectl get svc
kubectl port-forward svc/fastapi 8080:8080

kubectl apply -f k8s/metrics-server-serviceaccount.yaml
kubectl apply -f k8s/metrics-server-deployment.yaml
kubectl apply -f k8s/metrics-server-service.yaml
kubectl apply -f k8s/metrics-server-apiservice.yaml
kubectl apply -f k8s/monitoring/prometheus-config.yaml
kubectl apply -f k8s/monitoring/prometheus-deployment.yaml
kubectl apply -f k8s/monitoring/prometheus-service.yaml
kubectl apply -f k8s/monitoring/prometheus-service-monitor.yaml
kubectl apply -f k8s/monitoring/grafana-config.yaml
kubectl apply -f k8s/monitoring/grafana-dashboard-provider-configmap.yaml
kubectl apply -f k8s/monitoring/grafana-dashboard-configmap.yaml
kubectl apply -f k8s/monitoring/grafana-deployment.yaml
kubectl apply -f k8s/monitoring/grafana-service.yaml
```
