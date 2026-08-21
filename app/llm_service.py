import requests


def call_llm(system_prompt: str, user_prompt: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen3:4b",
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            "stream": False
        }
    )

    response.raise_for_status()

    return response.json()["message"]["content"]