from fastapi import FastAPI
from pydantic import BaseModel
import httpx

app = FastAPI(title="LLM API")

VLLM_URL = "http://vllm:8000"


class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 100


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/generate")
async def generate(request: GenerateRequest):
    payload = {
        "model": "Qwen/Qwen2.5-0.5B-Instruct",
        "messages": [
            {
                "role": "user",
                "content": request.prompt,
            }
        ],
        "max_tokens": request.max_tokens,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json=payload,
            timeout=120.0,
        )

    response.raise_for_status()

    data = response.json()

    return {
        "response": data["choices"][0]["message"]["content"]
    }
