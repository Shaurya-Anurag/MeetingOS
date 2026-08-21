from app.guardrails import validate_brief_input
from app.llm_service import call_llm
from app.prompts import build_brief_user_prompt, get_brief_system_prompt


def generate_executive_brief(topic: str, source_notes: str) -> str:

    allowed, message = validate_brief_input(topic, source_notes)

    if not allowed:
        return message

    system_prompt = get_brief_system_prompt()
    user_prompt = build_brief_user_prompt(topic, source_notes)

    brief = call_llm(system_prompt, user_prompt)

    return brief