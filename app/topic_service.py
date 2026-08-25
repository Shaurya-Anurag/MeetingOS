from app.llm_service import call_llm


def extract_topics(transcript: str) -> str:
    system_prompt = """
You are a meeting intelligence system.

Analyze the meeting transcript and identify the major discussion topics.

For each topic provide:

## Topic 1: <short topic name>
- Summary: <1-2 sentence summary>
- Key discussion: <important points discussed>
- Outcome: <decision, unresolved, or informational>

## Topic 2: <short topic name>
...

Rules:
- Identify 3-7 meaningful topics.
- Do not invent information.
- Keep each topic concise.
- Preserve the meaning of the transcript.
- If no clear outcome exists, write "No clear outcome identified."
"""

    user_prompt = f"""
Analyze this meeting transcript:

{transcript}

Identify and structure the major discussion topics.
"""

    return call_llm(system_prompt, user_prompt)