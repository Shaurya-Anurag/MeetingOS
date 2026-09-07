import requests


def call_llm(system_prompt: str, user_prompt: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "llama3.2:3b",
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
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_predict": 1200
            }
        },
        timeout=600
    )

    response.raise_for_status()

    return response.json()["message"]["content"].strip()