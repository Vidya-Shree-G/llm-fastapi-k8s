# LLM FastAPI Kubernetes

This project is an end-to-end FastAPI application that sends prompts to a local vLLM inference server. The app exposes a health check and a generate endpoint, and the Kubernetes manifests show how to deploy both services together.

## What this project does

- Runs a FastAPI API on port 8080
- Exposes a GET /health endpoint
- Accepts prompt requests through POST /generate
- Sends the request to a vLLM OpenAI-compatible endpoint
- Includes Kubernetes deployment files

## Project structure

```text
.
├── app/
│   └── main.py
├── k8s/
│   ├── fastapi-deployment.yaml
│   ├── fastapi-service.yaml
│   ├── vllm-deployment.yaml
│   └── vllm-service.yaml
├── Dockerfile
└── requirements.txt
```

- app/main.py — FastAPI app that calls the LLM backend
- Dockerfile — container definition for the API service
- requirements.txt — Python dependencies
- k8s/ — Kubernetes deployment manifests

## Prerequisites

Before you begin, install and start Docker Desktop, then install:

- [Minikube](https://minikube.sigs.k8s.io/docs/start/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)

Python 3.12 or newer is only needed if you also want to run the API locally.

## Deploy to Minikube

### Step 1: Start the Minikube cluster

Start a local cluster with enough CPU and memory for the vLLM container:

```bash
minikube start --driver=docker --cpus=8 --memory=8192
```

Confirm that the cluster is running and kubectl is using it:

```bash
minikube status
kubectl config current-context
kubectl get nodes
```

The current context should be `minikube`.

### Step 2: Build and load the FastAPI image

Build the image from the project root, then load it into Minikube so the deployment can use it:

```bash
docker build -t llm-fastapi:latest .
minikube image load llm-fastapi:latest
```

### Step 3: Deploy the application and model

Apply the Kubernetes manifests:

```bash
kubectl apply -f k8s/
```

Wait for both deployments to become ready. The first vLLM startup can take a while because it downloads the model:

```bash
kubectl rollout status deployment/vllm --timeout=10m
kubectl rollout status deployment/fastapi --timeout=5m
kubectl get pods,services
```

### Step 4: Access and test the API

Forward the FastAPI service to your machine:

```bash
kubectl port-forward service/fastapi 8080:8080
```

In another terminal, check the health endpoint:

```bash
curl http://localhost:8080/health
```

Then send a prompt:

```bash
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Explain Kubernetes in one short paragraph.","max_tokens":80}'
```

The API forwards the prompt to the in-cluster vLLM service at `http://vllm:8000`.

### Stop or remove the cluster

When finished, stop Minikube while keeping the cluster state:

```bash
minikube stop
```

To delete the cluster and its state instead:

```bash
minikube delete
```

## Run the API locally

To run the API outside Kubernetes, first make sure a vLLM server is reachable at `http://localhost:8000`. Then create a virtual environment, install the dependencies, and start the API:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export VLLM_URL=http://localhost:8000
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Check the local health endpoint:

```bash
curl http://localhost:8080/health
```

## Notes on the setup

- The FastAPI container listens on port 8080
- The vLLM container runs a CPU-based model with the OpenAI-compatible API
- The FastAPI app calls `http://vllm:8000/v1/chat/completions`
- The cluster service names make the service-to-service communication easy

## Troubleshooting

### API returns connection errors

Check that the vLLM service is running:

```bash
kubectl get pods
kubectl logs deployment/vllm
```

### Health check keeps failing

Make sure the app container is listening on port 8080 and that the FastAPI service is selected correctly.

```bash
kubectl get svc
kubectl logs deployment/fastapi
```

### Local dev cannot reach the model

Verify that your `VLLM_URL` points to a reachable host:

```bash
export VLLM_URL=http://localhost:8000
```
