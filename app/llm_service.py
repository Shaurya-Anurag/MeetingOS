
import time
import requests


MODEL = "llama3.2:3b"


def call_llm(system_prompt: str, user_prompt: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": 3000,
        },
    }

    print(
        f"[LLM] Request started | "
        f"System prompt: {len(system_prompt)} chars | "
        f"User prompt: {len(user_prompt)} chars"
    )

    start = time.perf_counter()

    response = requests.post(
        "http://localhost:11434/api/chat",
        json=payload,
        timeout=600,
    )

    elapsed = time.perf_counter() - start
    response.raise_for_status()

    result = response.json()
    message = result.get("message", {}).get("content", "").strip()

    # Ollama reports these durations in nanoseconds.
    total_duration = result.get("total_duration")
    load_duration = result.get("load_duration")
    prompt_eval_duration = result.get("prompt_eval_duration")
    eval_duration = result.get("eval_duration")

    def seconds(ns):
        return f"{ns / 1_000_000_000:.2f}s" if ns is not None else "N/A"

    print(
        f"[LLM] HTTP elapsed: {elapsed:.2f}s | "
        f"Ollama total: {seconds(total_duration)} | "
        f"Model load: {seconds(load_duration)} | "
        f"Prompt eval: {seconds(prompt_eval_duration)} | "
        f"Generation: {seconds(eval_duration)} | "
        f"Prompt tokens: {result.get('prompt_eval_count', 'N/A')} | "
        f"Generated tokens: {result.get('eval_count', 'N/A')}"
    )

    return message
