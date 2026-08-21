def validate_brief_input(topic: str, source_notes: str) -> tuple[bool, str]:

    if not topic or not topic.strip():
        return False, "Please enter a topic."

    if not source_notes or not source_notes.strip():
        return False, "Please paste meeting notes or source text."

    if len(source_notes.strip()) < 20:
        return False, "Source notes are too short. Add more detail."

    return True, "Input allowed."