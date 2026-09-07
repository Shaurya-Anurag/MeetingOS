import json

from app.llm_service import call_llm
from app.prompts import (
    get_intelligence_system_prompt,
    build_intelligence_user_prompt
)


def generate_meeting_intelligence(
    topic: str,
    transcript: str
) -> dict:

    system_prompt = get_intelligence_system_prompt()

    user_prompt = build_intelligence_user_prompt(
        topic,
        transcript
    )

    raw_response = call_llm(
        system_prompt,
        user_prompt
    )
    print("\n===== RAW LLM RESPONSE =====")
    print(raw_response)
    print("===== END RAW LLM RESPONSE =====\n")

    try:
        return json.loads(raw_response)

    except json.JSONDecodeError:
        return {
            "executive_summary": "Unable to parse meeting intelligence.",
            "topics": [],
            "decisions": [],
            "action_items": [],
            "risks_and_concerns": [],
            "unresolved_questions": [],
            "contradictions": []
        }