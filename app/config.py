import os
from dotenv import load_dotenv

load_dotenv()


def get_model_provider() -> str:
    return os.getenv("MODEL_PROVIDER", "openai").lower()


def get_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError("OPENAI_API_KEY is missing in .env file.")

    return api_key


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")