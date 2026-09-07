import html
import gradio as gr
import re

from Services.Transcription import transcribe_audio
from app.analytics_service import analyze_transcript
from app.intelligence_service import generate_meeting_intelligence
from app.database import (
    initialize_database,
    save_meeting,
    get_all_meetings,
    search_meetings,
    get_meeting,
    delete_meeting,
    get_tasks,
    get_task,
    update_task_status,
)

initialize_database()


# =========================================================
# BASIC HELPERS
# =========================================================

def esc(value):
    if value is None:
        return ""
    return html.escape(str(value))


def display_value(value):
    if value in (None, "", "null"):
        return "Not specified"
    return str(value)


# =========================================================
# SPEAKER DETECTION / NAME MAPPING
# =========================================================

def extract_speaker_info(transcript):
    """
    Extract detected speakers and up to two sample utterances
    from the speaker-aware transcript.
    """

    pattern = re.compile(
        r"\[(\d+(?:\.\d+)?)s\s*->\s*(\d+(?:\.\d+)?)s\]\s+"
        r"(SPEAKER_\d+):\s*(.*)"
    )

    speakers = {}

    for line in transcript.splitlines():

        match = pattern.match(line.strip())

        if not match:
            continue

        speaker = match.group(3)
        text = match.group(4).strip()

        if speaker not in speakers:
            speakers[speaker] = []

        if text and len(speakers[speaker]) < 2:
            speakers[speaker].append(text)

    return speakers


def build_speaker_setup_html(speakers):
    """
    Build the speaker confirmation panel showing sample utterances.
    """

    count = len(speakers)

    if count == 0:
        return """
        <div class="empty-state">
            No speakers could be detected.
        </div>
        """

    cards = []

    for index, (speaker, lines) in enumerate(speakers.items(), 1):

        snippets = ""

        for line in lines:
            snippets += f"""
            <div class="speaker-snippet">
                “{esc(line)}”
            </div>
            """

        cards.append(
            f"""
            <div class="topic-card">
                <div class="topic-number">
                    SPEAKER {index}
                </div>

                <h3>
                    Speaker {index}
                </h3>

                <div class="section-label">
                    SAMPLE UTTERANCES
                </div>

                {snippets}
            </div>
            """
        )

    return f"""
    <div class="summary-card">

        <div class="section-label">
            SPEAKER DETECTION
        </div>

        <p>
            MeetingOS detected
            <strong>{count}</strong>
            speaker{"s" if count != 1 else ""}.
            Is this correct?
        </p>

    </div>

    <div class="topic-grid">
        {"".join(cards)}
    </div>
    """


def prepare_meeting(audio_path):
    """
    Transcribe the recording and detect speakers.
    Meeting intelligence is generated only after speaker
    confirmation is completed.
    """

    if not audio_path:
        return (
            "",
            {},
            """
            <div class="empty-page">
                Please upload a meeting recording first.
            </div>
            """,
            gr.update(visible=False),
            gr.update(visible=False),
            *[
                gr.update(visible=False)
                for _ in range(6)
            ],
            gr.update(visible=False),
            gr.update(visible=False),
        )

    print("Transcribing audio and detecting speakers...")

    transcript = transcribe_audio(audio_path)

    speakers = extract_speaker_info(transcript)

    speaker_items = list(speakers.keys())

    name_updates = []

    for index in range(6):

        if index < len(speaker_items):

            speaker = speaker_items[index]

            name_updates.append(
                gr.update(
                    visible=True,
                    label=f"Name for Speaker {index + 1}",
                    placeholder=f"e.g. Shaurya"
                )
            )

        else:

            name_updates.append(
                gr.update(
                    visible=False,
                    value=""
                )
            )

    return (
        transcript,
        speakers,
        gr.update(
            value=build_speaker_setup_html(speakers),
            visible=True
        ),
        gr.update(
            value=None,
            visible=True,
            label=f"MeetingOS detected {len(speakers)} speakers. Is this correct?"
        ),
        gr.update(
            visible=False
        ),
        *name_updates,
        gr.update(
            visible=True,
            value="Continue"
        ),
        gr.update(
            visible=False
        ),
    )


def update_mapping_visibility(choice):
    """
    Show name fields only when the user confirms
    the detected speaker count.
    """

    if choice == "Yes":

        return (
            gr.update(
                visible=True
            ),
            gr.update(
                visible=True,
                value="Confirm Names & Continue"
            )
        )

    if choice == "No":

        return (
            gr.update(
                visible=False
            ),
            gr.update(
                visible=True,
                value="Continue Without Names"
            )
        )

    return (
        gr.update(
            visible=False
        ),
        gr.update(
            visible=False
        )
    )


def finalize_speakers(
    transcript,
    speakers,
    speaker_confirmation,
    name1,
    name2,
    name3,
    name4,
    name5,
    name6
):
    """
    Apply optional speaker names to the speaker-aware transcript.

    If the user selects No, generic speaker labels are preserved.
    """

    if not transcript:
        return (
            transcript,
            gr.update(visible=False),
            gr.update(visible=False),
        )

    if speaker_confirmation == "No":

        return (
            transcript,
            gr.update(visible=False),
            gr.update(visible=True),
        )

    names = [
        name1,
        name2,
        name3,
        name4,
        name5,
        name6
    ]

    speaker_list = list(speakers.keys())

    for index, speaker in enumerate(speaker_list):

        if index >= len(names):
            break

        name = names[index]

        if name and name.strip():

            transcript = transcript.replace(
                speaker,
                name.strip()
            )

    return (
        transcript,
        gr.update(visible=False),
        gr.update(visible=True),
    )


# =========================================================
# EVIDENCE
# =========================================================

def render_evidence(evidence):

    if not evidence:
        return ""

    blocks = []

    for item in evidence:

        timestamp = esc(
            item.get(
                "timestamp",
                ""
            )
        )

        text = esc(
            item.get(
                "text",
                ""
            )
        )

        if timestamp or text:

            blocks.append(
                f"""
                <div class="evidence">
                    <span class="evidence-label">
                        Evidence
                    </span>

                    <span class="evidence-time">
                        {timestamp}
                    </span>

                    <span class="evidence-text">
                        {text}
                    </span>
                </div>
                """
            )

    return "".join(blocks)


# =========================================================
# TOPICS
# =========================================================

def render_topics(topics):

    if not topics:

        return """
        <div class="empty-state">
            No major discussion topics identified.
        </div>
        """

    cards = []

    for index, topic in enumerate(
        topics,
        1
    ):

        name = esc(
            topic.get(
                "name",
                f"Topic {index}"
            )
        )

        summary = esc(
            topic.get(
                "summary",
                ""
            )
        )

        outcome = esc(
            topic.get(
                "outcome",
                ""
            )
        )

        key_points = topic.get(
            "key_points",
            []
        )

        evidence = topic.get(
            "evidence",
            []
        )

        points_html = ""

        if key_points:

            points_html = "<ul>"

            for point in key_points:

                points_html += (
                    f"<li>{esc(point)}</li>"
                )

            points_html += "</ul>"

        evidence_html = render_evidence(
            evidence
        )

        outcome_html = ""

        if outcome:

            outcome_html = (
                "<div class='outcome'>"
                "<strong>Outcome:</strong> "
                f"{outcome}"
                "</div>"
            )

        cards.append(
            f"""
            <div class="topic-card">

                <div class="topic-number">
                    TOPIC {index}
                </div>

                <h3>
                    {name}
                </h3>

                <p class="topic-summary">
                    {summary}
                </p>

                {points_html}

                {outcome_html}

                {evidence_html}

            </div>
            """
        )

    return "".join(cards)


# =========================================================
# DECISIONS
# =========================================================

def render_decisions(decisions):

    if not decisions:

        return """
        <div class="empty-state">
            No explicit decisions identified.
        </div>
        """

    cards = []

    for decision in decisions:

        if isinstance(
            decision,
            dict
        ):

            text = esc(
                decision.get(
                    "decision",
                    ""
                )
            )

            evidence = render_evidence(
                decision.get(
                    "evidence",
                    []
                )
            )

        else:

            text = esc(decision)
            evidence = ""

        cards.append(
            f"""
            <div class="decision-card">

                <div class="icon decision-icon">
                    ✓
                </div>

                <div>

                    <div class="card-main">
                        {text}
                    </div>

                    {evidence}

                </div>

            </div>
            """
        )

    return "".join(cards)


# =========================================================
# ACTION ITEMS
# =========================================================

def render_actions(actions):

    if not actions:

        return """
        <div class="empty-state">
            No explicit action items identified.
        </div>
        """

    cards = []

    for action in actions:

        if isinstance(
            action,
            dict
        ):

            task = esc(
                action.get(
                    "task",
                    ""
                )
            )

            owner = display_value(
                action.get(
                    "owner"
                )
            )

            deadline = display_value(
                action.get(
                    "deadline"
                )
            )

            evidence = render_evidence(
                action.get(
                    "evidence",
                    []
                )
            )

        else:

            task = esc(action)
            owner = "Not specified"
            deadline = "Not specified"
            evidence = ""

        cards.append(
            f"""
            <div class="action-card">

                <div class="icon action-icon">
                    →
                </div>

                <div class="action-body">

                    <div class="action-task">
                        {task}
                    </div>

                    <div class="action-meta">

                        <span>
                            <strong>
                                Owner
                            </strong>
                            {esc(owner)}
                        </span>

                        <span>
                            <strong>
                                Deadline
                            </strong>
                            {esc(deadline)}
                        </span>

                    </div>

                    {evidence}

                </div>

            </div>
            """
        )

    return "".join(cards)


# =========================================================
# RISKS
# =========================================================

def render_risks(risks):

    if not risks:

        return """
        <div class="empty-state">
            No explicit risks or concerns identified.
        </div>
        """

    cards = []

    for risk in risks:

        if isinstance(
            risk,
            dict
        ):

            text = esc(
                risk.get(
                    "risk",
                    ""
                )
            )

            evidence = render_evidence(
                risk.get(
                    "evidence",
                    []
                )
            )

        else:

            text = esc(risk)
            evidence = ""

        cards.append(
            f"""
            <div class="risk-card">

                <div class="icon risk-icon">
                    !
                </div>

                <div>

                    <div class="card-main">
                        {text}
                    </div>

                    {evidence}

                </div>

            </div>
            """
        )

    return "".join(cards)


# =========================================================
# UNRESOLVED QUESTIONS
# =========================================================

def render_questions(questions):

    if not questions:

        return """
        <div class="empty-state">
            No unresolved questions identified.
        </div>
        """

    cards = []

    for question in questions:

        if isinstance(
            question,
            dict
        ):

            text = esc(
                question.get(
                    "question",
                    ""
                )
            )

            evidence = render_evidence(
                question.get(
                    "evidence",
                    []
                )
            )

        else:

            text = esc(question)
            evidence = ""

        cards.append(
            f"""
            <div class="question-card">

                <div class="icon question-icon">
                    ?
                </div>

                <div>

                    <div class="card-main">
                        {text}
                    </div>

                    {evidence}

                </div>

            </div>
            """
        )

    return "".join(cards)


# =========================================================
# CONTRADICTIONS
# =========================================================

def render_contradictions(contradictions):

    if not contradictions:

        return """
        <div class="empty-state success">
            No contradictions identified.
        </div>
        """

    cards = []

    for contradiction in contradictions:

        if isinstance(
            contradiction,
            dict
        ):

            text = esc(
                contradiction.get(
                    "issue",
                    ""
                )
            )

            evidence = render_evidence(
                contradiction.get(
                    "evidence",
                    []
                )
            )

        else:

            text = esc(contradiction)
            evidence = ""

        cards.append(
            f"""
            <div class="contradiction-card">

                <div class="icon contradiction-icon">
                    ↔
                </div>

                <div>

                    <div class="card-main">
                        {text}
                    </div>

                    {evidence}

                </div>

            </div>
            """
        )

    return "".join(cards)

def _meeting_choices(meetings):
    choices = []

    for meeting in meetings:
        duration = meeting["duration_seconds"] or 0
        label = (
            f'{meeting["topic"]} '
            f'• {meeting["created_at"]} '
            f'• {duration / 60:.1f} min'
        )
        choices.append((label, meeting["id"]))

    return choices


def build_history_choices():
    return _meeting_choices(get_all_meetings())


def build_search_choices(query):
    return _meeting_choices(search_meetings(query))


def build_task_choices(meeting_id):
    if meeting_id is None:
        return []

    choices = []
    for task in get_tasks(meeting_id):
        owner = task.get("owner") or "Unassigned"
        deadline = task.get("deadline") or "No deadline"
        label = f'{task["task"]} • {owner} • {deadline} • {task["status"]}'
        choices.append((label, task["id"]))

    return choices


def task_selection_changed(task_id):
    if task_id is None:
        return gr.update(value="Pending"), ""

    task = get_task(task_id)
    if task is None:
        return gr.update(value="Pending"), "Task could not be found."

    owner = task.get("owner") or "Unassigned"
    deadline = task.get("deadline") or "No deadline"
    message = (
        f'<div class="task-meta">'
        f'<strong>{esc(task["task"])}</strong><br>'
        f'Owner: {esc(owner)} &nbsp;•&nbsp; Deadline: {esc(deadline)}'
        f'</div>'
    )
    return gr.update(value=task["status"]), message


def save_task_status(task_id, status, meeting_id):
    if task_id is None:
        return gr.update(choices=build_task_choices(meeting_id), value=None), gr.update(value="Pending"), "Select a task first."

    updated = update_task_status(task_id, status)
    if not updated:
        return gr.update(choices=build_task_choices(meeting_id), value=task_id), gr.update(value=status), "Task status could not be updated."

    return (
        gr.update(choices=build_task_choices(meeting_id), value=task_id),
        gr.update(value=status),
        f'<div class="success-message">Task marked <strong>{esc(status)}</strong>.</div>'
    )


def build_workspace_analytics_html():
    meetings = get_all_meetings()
    tasks = get_tasks()

    total_duration = sum((m["duration_seconds"] or 0) for m in meetings)
    pending = sum(1 for t in tasks if t["status"] == "Pending")
    in_progress = sum(1 for t in tasks if t["status"] == "In Progress")
    completed = sum(1 for t in tasks if t["status"] == "Completed")

    total_tasks = len(tasks)
    max_tasks = max(total_tasks, 1)

    return f"""
    <div class="workspace-analytics">
        <div class="workspace-metric">
            <div class="metric-value">{len(meetings)}</div>
            <div class="metric-label">MEETINGS</div>
        </div>
        <div class="workspace-metric">
            <div class="metric-value">{total_duration / 60:.1f}</div>
            <div class="metric-label">TOTAL MINUTES</div>
        </div>
        <div class="workspace-metric">
            <div class="metric-value">{total_tasks}</div>
            <div class="metric-label">TASKS</div>
        </div>
        <div class="workspace-metric">
            <div class="metric-value">{completed}</div>
            <div class="metric-label">COMPLETED</div>
        </div>
    </div>

    <div class="task-bars">
        <div class="bar-row"><span>Pending</span><div class="bar-track"><div class="bar-fill" style="width:{pending / max_tasks * 100:.1f}%"></div></div><strong>{pending}</strong></div>
        <div class="bar-row"><span>In Progress</span><div class="bar-track"><div class="bar-fill" style="width:{in_progress / max_tasks * 100:.1f}%"></div></div><strong>{in_progress}</strong></div>
        <div class="bar-row"><span>Completed</span><div class="bar-track"><div class="bar-fill" style="width:{completed / max_tasks * 100:.1f}%"></div></div><strong>{completed}</strong></div>
    </div>
    """


def refresh_workspace_analytics():
    return build_workspace_analytics_html()


# =========================================================
# GENERATE MEETING INTELLIGENCE
# =========================================================

def generate_brief(
    transcript,
    speakers,
    topic
):

    if not transcript:

        return (
            """
            <div class="empty-page">
                No meeting transcript available.
            </div>
            """,
            """
            <div class="empty-page">
                No meeting data available.
            </div>
            """,
            gr.update(choices=build_history_choices(), value=None),
            gr.update(choices=[], value=None),
            gr.update(value="Pending"),
            ""
        )

    if not topic or not topic.strip():

        topic = "Meeting Discussion"

    print(
        "Calculating analytics..."
    )

    analytics = analyze_transcript(
        transcript
    )

    print(
        "Generating meeting intelligence..."
    )

    intelligence = generate_meeting_intelligence(
        topic=topic,
        transcript=transcript
    )

    print("Saving meeting...")
    meeting_id = save_meeting(
        topic=topic,
        transcript=transcript,
        intelligence=intelligence,
        analytics=analytics,
        speaker_data=speakers
    )
    print(f"Meeting saved with ID: {meeting_id}")

    summary = esc(
        intelligence.get(
            "executive_summary",
            "No executive summary identified."
        )
    )

    topics_html = render_topics(
        intelligence.get(
            "topics",
            []
        )
    )

    decisions_html = render_decisions(
        intelligence.get(
            "decisions",
            []
        )
    )

    actions_html = render_actions(
        intelligence.get(
            "action_items",
            []
        )
    )

    risks_html = render_risks(
        intelligence.get(
            "risks_and_concerns",
            []
        )
    )

    questions_html = render_questions(
        intelligence.get(
            "unresolved_questions",
            []
        )
    )

    contradictions_html = render_contradictions(
        intelligence.get(
            "contradictions",
            []
        )
    )

    intelligence_html = f"""
    <div class="report">

        <div class="hero-section">

            <div class="eyebrow">
                MEETING INTELLIGENCE
            </div>

            <h1>
                {esc(topic)}
            </h1>

            <p class="hero-description">
                Structured intelligence extracted from the meeting.
            </p>

        </div>

        <div class="summary-card">

            <div class="section-label">
                EXECUTIVE SUMMARY
            </div>

            <p>
                {summary}
            </p>

        </div>

        <section>

            <div class="section-heading">
                Discussion Topics
            </div>

            <div class="topic-grid">
                {topics_html}
            </div>

        </section>

        <section>

            <div class="section-heading">
                Decisions Made
            </div>

            <div class="stack">
                {decisions_html}
            </div>

        </section>

        <section>

            <div class="section-heading">
                Action Items
            </div>

            <div class="stack">
                {actions_html}
            </div>

        </section>

        <div class="two-column">

            <section>

                <div class="section-heading">
                    Risks & Concerns
                </div>

                <div class="stack">
                    {risks_html}
                </div>

            </section>

            <section>

                <div class="section-heading">
                    Unresolved Questions
                </div>

                <div class="stack">
                    {questions_html}
                </div>

            </section>

        </div>

        <section>

            <div class="section-heading">
                Contradictions & Inconsistencies
            </div>

            <div class="stack">
                {contradictions_html}
            </div>

        </section>

    </div>
    """

    analytics_html = f"""
    <div class="analytics-panel">

        <div class="metric">

            <div class="metric-value">
                {analytics["duration_minutes"]:.2f}
            </div>

            <div class="metric-label">
                MINUTES
            </div>

        </div>

        <div class="metric">

            <div class="metric-value">
                {analytics["word_count"]:,}
            </div>

            <div class="metric-label">
                WORDS
            </div>

        </div>

        <div class="metric">

            <div class="metric-value">
                {analytics["segment_count"]}
            </div>

            <div class="metric-label">
                SEGMENTS
            </div>

        </div>

    </div>
    """

    task_choices = build_task_choices(meeting_id)
    first_task = task_choices[0][1] if task_choices else None

    return (
        intelligence_html,
        analytics_html,
        gr.update(
            choices=build_history_choices(),
            value=meeting_id,
        ),
        gr.update(
            choices=task_choices,
            value=first_task,
        ),
        gr.update(
            value=(get_task(first_task) or {}).get("status", "Pending")
            if first_task is not None
            else "Pending"
        ),
        ""
    )


# =========================================================
# CSS
# =========================================================

css = """
.gradio-container {
    max-width: 1250px !important;
    margin: 0 auto !important;
}

#header {
    text-align: center;
    margin-bottom: 30px;
}

#header h1 {
    font-size: 44px;
    margin-bottom: 6px;
}

#header p {
    opacity: 0.7;
    font-size: 17px;
}

#generate {
    height: 52px;
    font-size: 17px;
    font-weight: 700;
}

#analyze {
    height: 48px;
    font-size: 16px;
    font-weight: 700;
}

#confirm-speakers {
    height: 48px;
    font-size: 16px;
    font-weight: 700;
}

.report {
    padding: 10px 0 40px 0;
}

.hero-section {
    padding: 10px 0 25px 0;
}

.eyebrow {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.8px;
    opacity: 0.6;
    margin-bottom: 8px;
}

.hero-section h1 {
    margin: 0;
    font-size: 30px;
}

.hero-description {
    opacity: 0.65;
    margin-top: 6px;
}

.summary-card {
    border-radius: 16px;
    padding: 22px;
    margin-bottom: 32px;
    border: 1px solid rgba(255,255,255,0.10);
}

.summary-card p {
    font-size: 18px;
    line-height: 1.6;
    margin-bottom: 0;
}

.section-label {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.4px;
    opacity: 0.6;
    margin-bottom: 10px;
}

.section-heading {
    font-size: 24px;
    font-weight: 700;
    margin: 30px 0 14px 0;
}

.topic-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
}

.topic-card,
.decision-card,
.action-card,
.risk-card,
.question-card,
.contradiction-card {
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 14px;
    padding: 18px;
    margin-bottom: 12px;
}

.topic-number {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.2px;
    opacity: 0.5;
}

.topic-card h3 {
    margin: 5px 0 10px 0;
    font-size: 19px;
}

.topic-summary {
    line-height: 1.55;
}

.topic-card ul {
    margin-top: 8px;
}

.outcome {
    margin-top: 12px;
    font-size: 14px;
    opacity: 0.85;
}

.stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.decision-card,
.action-card,
.risk-card,
.question-card,
.contradiction-card {
    display: flex;
    gap: 14px;
    align-items: flex-start;
}

.icon {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    flex-shrink: 0;
}

.decision-icon {
    background: rgba(70, 200, 120, 0.16);
}

.action-icon {
    background: rgba(100, 130, 255, 0.16);
}

.risk-icon {
    background: rgba(255, 170, 70, 0.16);
}

.question-icon {
    background: rgba(170, 120, 255, 0.16);
}

.contradiction-icon {
    background: rgba(255, 100, 120, 0.16);
}

.card-main {
    font-size: 16px;
    line-height: 1.5;
}

.action-task {
    font-size: 16px;
    font-weight: 650;
    margin-bottom: 10px;
}

.action-meta {
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
    font-size: 13px;
    opacity: 0.75;
}

.action-meta span {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.evidence {
    margin-top: 12px;
    padding: 10px 12px;
    border-left: 2px solid rgba(255,255,255,0.20);
    font-size: 12px;
    opacity: 0.62;
    line-height: 1.45;
}

.evidence-label {
    font-weight: 700;
    margin-right: 8px;
}

.evidence-time {
    font-weight: 700;
    margin-right: 8px;
}

.evidence-text {
    font-style: italic;
}

.two-column {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
}

.empty-state {
    border: 1px dashed rgba(255,255,255,0.18);
    border-radius: 12px;
    padding: 18px;
    opacity: 0.65;
}

.empty-state.success {
    border-color: rgba(70, 200, 120, 0.25);
}

.analytics-panel {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
}

.metric {
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 12px;
    padding: 14px;
    text-align: center;
}

.metric-value {
    font-size: 24px;
    font-weight: 750;
}

.metric-label {
    font-size: 10px;
    letter-spacing: 1px;
    opacity: 0.55;
    margin-top: 3px;
}

.empty-page {
    padding: 30px;
    opacity: 0.6;
}

.speaker-snippet {
    padding: 9px 12px;
    margin-top: 8px;
    border-left: 2px solid rgba(255,255,255,0.20);
    font-size: 13px;
    opacity: 0.75;
    line-height: 1.45;
}

.speaker-help {
    font-size: 13px;
    opacity: 0.65;
    margin-bottom: 10px;
}

.workspace-analytics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin: 12px 0 18px 0;
}

.workspace-metric {
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 12px;
    padding: 16px;
}

.task-bars {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 20px;
}

.bar-row {
    display: grid;
    grid-template-columns: 110px 1fr 30px;
    gap: 10px;
    align-items: center;
    font-size: 13px;
}

.bar-track {
    height: 9px;
    border-radius: 999px;
    background: rgba(255,255,255,0.08);
    overflow: hidden;
}

.bar-fill {
    height: 100%;
    border-radius: 999px;
    background: currentColor;
}

.task-meta {
    margin: 6px 0 10px 0;
    padding: 10px 12px;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    font-size: 13px;
    line-height: 1.55;
}

.success-message {
    padding: 9px 12px;
    font-size: 13px;
    opacity: 0.8;
}

@media (max-width: 850px) {

    .topic-grid,
    .two-column {
        grid-template-columns: 1fr;
    }
}
"""
def delete_saved_meeting(meeting_id):

    if meeting_id is None:
        return (
            gr.update(
                choices=build_history_choices(),
                value=None
            ),
            """
            <div class="empty-page">
                Select a meeting to delete.
            </div>
            """,
            """
            <div class="empty-page">
                No meeting data available.
            </div>
            """
        )

    deleted = delete_meeting(meeting_id)

    if not deleted:
        return (
            gr.update(
                choices=build_history_choices(),
                value=None
            ),
            """
            <div class="empty-page">
                Meeting could not be found.
            </div>
            """,
            """
            <div class="empty-page">
                No meeting data available.
            </div>
            """
        )

    print(f"Meeting deleted: {meeting_id}")

    return (
        gr.update(
            choices=build_history_choices(),
            value=None
        ),
        """
        <div class="empty-page">
            Meeting deleted successfully.
        </div>
        """,
        """
        <div class="empty-page">
            No meeting data available.
        </div>
        """
    )

def close_saved_meeting():
    return (
        gr.update(value=None),
        """
        <div class="empty-page">
            Analyze a meeting recording to begin.
        </div>
        """,
        """
        <div class="empty-page">
            No meeting data available.
        </div>
        """
    )

def open_saved_meeting(meeting_id):

    if meeting_id is None:
        return (
            """
            <div class="empty-page">
                Select a meeting from history first.
            </div>
            """,
            """
            <div class="empty-page">
                No meeting data available.
            </div>
            """
        )

    meeting = get_meeting(meeting_id)

    if meeting is None:
        return (
            """
            <div class="empty-page">
                Meeting could not be found.
            </div>
            """,
            """
            <div class="empty-page">
                No meeting data available.
            </div>
            """
        )

    intelligence = meeting["intelligence"]
    analytics = meeting["analytics"]
    topic = meeting["topic"]

    summary = esc(
        intelligence.get(
            "executive_summary",
            "No executive summary identified."
        )
    )

    topics_html = render_topics(
        intelligence.get("topics", [])
    )

    decisions_html = render_decisions(
        intelligence.get("decisions", [])
    )

    actions_html = render_actions(
        intelligence.get("action_items", [])
    )

    risks_html = render_risks(
        intelligence.get("risks_and_concerns", [])
    )

    questions_html = render_questions(
        intelligence.get("unresolved_questions", [])
    )

    contradictions_html = render_contradictions(
        intelligence.get("contradictions", [])
    )

    intelligence_html = f"""
    <div class="report">

        <div class="hero-section">
            <div class="eyebrow">
                SAVED MEETING
            </div>

            <h1>
                {esc(topic)}
            </h1>

            <p class="hero-description">
                Loaded from MeetingOS history.
            </p>
        </div>

        <div class="summary-card">
            <div class="section-label">
                EXECUTIVE SUMMARY
            </div>

            <p>
                {summary}
            </p>
        </div>

        <section>
            <div class="section-heading">
                Discussion Topics
            </div>

            <div class="topic-grid">
                {topics_html}
            </div>
        </section>

        <section>
            <div class="section-heading">
                Decisions Made
            </div>

            <div class="stack">
                {decisions_html}
            </div>
        </section>

        <section>
            <div class="section-heading">
                Action Items
            </div>

            <div class="stack">
                {actions_html}
            </div>
        </section>

        <div class="two-column">

            <section>
                <div class="section-heading">
                    Risks & Concerns
                </div>

                <div class="stack">
                    {risks_html}
                </div>
            </section>

            <section>
                <div class="section-heading">
                    Unresolved Questions
                </div>

                <div class="stack">
                    {questions_html}
                </div>
            </section>

        </div>

        <section>
            <div class="section-heading">
                Contradictions & Inconsistencies
            </div>

            <div class="stack">
                {contradictions_html}
            </div>
        </section>

    </div>
    """

    analytics_html = f"""
    <div class="analytics-panel">

        <div class="metric">
            <div class="metric-value">
                {analytics.get("duration_minutes", 0):.2f}
            </div>

            <div class="metric-label">
                MINUTES
            </div>
        </div>

        <div class="metric">
            <div class="metric-value">
                {analytics.get("word_count", 0):,}
            </div>

            <div class="metric-label">
                WORDS
            </div>
        </div>

        <div class="metric">
            <div class="metric-value">
                {analytics.get("segment_count", 0)}
            </div>

            <div class="metric-label">
                SEGMENTS
            </div>
        </div>

    </div>
    """

    return intelligence_html, analytics_html
# =========================================================
# UI
# =========================================================

with gr.Blocks(
    title="MeetingOS",
    css=css
) as demo:

    gr.Markdown(
        """
        # MeetingOS
        ### AI-Powered Meeting Intelligence

        Turn raw meeting recordings into structured, actionable intelligence.
        """,
        elem_id="header"
    )

    # -----------------------------------------------------
    # INPUT + ANALYTICS
    # -----------------------------------------------------

    with gr.Row():

        with gr.Column(scale=1):

            gr.Markdown(
                "## Meeting Input"
            )

            topic_input = gr.Textbox(
                label="Meeting Topic",
                placeholder="e.g. Q2 Product Launch Planning",
                value="Meeting Discussion"
            )

            audio_input = gr.Audio(
                label="Meeting Recording",
                type="filepath"
            )

            analyze_button = gr.Button(
                "Analyze Recording & Detect Speakers",
                variant="primary",
                elem_id="analyze"
            )

        with gr.Column(scale=1):

            gr.Markdown(
                "## Meeting Analytics"
            )

            analytics_output = gr.HTML(
                """
                <div class="empty-page">
                    No meeting data available.
                </div>
                """
            )
# -----------------------------------------------------
# MEETING HISTORY
# -----------------------------------------------------

    with gr.Row():

        with gr.Column(scale=3):

            history_dropdown = gr.Dropdown(
                label="Meeting History",
                choices=build_history_choices(),
                value=None,
                interactive=True
            )

        with gr.Column(scale=1):

            open_meeting_button = gr.Button(
                "Open Meeting",
                variant="secondary",
                interactive=False
            )

        with gr.Column(scale=1):

            close_meeting_button = gr.Button(
                "Close Meeting",
                variant="secondary",
                interactive=False
            )

        with gr.Column(scale=1):

            delete_meeting_button = gr.Button(
                "Delete Meeting",
                variant="stop",
                interactive=False
            )


    # -----------------------------------------------------
    # MEETING SEARCH
    # -----------------------------------------------------

    with gr.Row():

        search_input = gr.Textbox(
            label="Search Meetings",
            placeholder="Search topic, transcript, decisions, tasks...",
            scale=4
        )

        search_button = gr.Button(
            "Search",
            variant="secondary",
            scale=1
        )

    # -----------------------------------------------------
    # TASK TRACKING
    # -----------------------------------------------------

    gr.Markdown("## Task Tracker")

    with gr.Row():

        with gr.Column(scale=3):

            task_dropdown = gr.Dropdown(
                label="Meeting Tasks",
                choices=[],
                value=None,
                interactive=True
            )

        with gr.Column(scale=1):

            task_status_dropdown = gr.Dropdown(
                label="Status",
                choices=[
                    "Pending",
                    "In Progress",
                    "Completed"
                ],
                value="Pending",
                interactive=True
            )

        with gr.Column(scale=1):

            update_task_button = gr.Button(
                "Update Status",
                variant="secondary",
                interactive=False
            )

    task_status_message = gr.HTML("")

    gr.Markdown("## Workspace Analytics")

    workspace_analytics_output = gr.HTML(
        build_workspace_analytics_html()
    )

    # -----------------------------------------------------
    # SPEAKER DETECTION
    # -----------------------------------------------------

    speaker_setup = gr.HTML(
        visible=False
    )

    speaker_confirmation = gr.Radio(
        choices=[
            "Yes",
            "No"
        ],
        label="Is the detected speaker count correct?",
        visible=False
    )

    with gr.Column(
        visible=False
    ) as speaker_mapping_group:

        gr.Markdown(
            """
            **Map the detected speakers to names.**
            
            The sample utterances above are taken directly from
            the recording. Leave any name blank to keep the
            generic speaker label.
            """,
            elem_classes=["speaker-help"]
        )

        name1 = gr.Textbox(
            label="Name for Speaker 1",
            visible=False
        )

        name2 = gr.Textbox(
            label="Name for Speaker 2",
            visible=False
        )

        name3 = gr.Textbox(
            label="Name for Speaker 3",
            visible=False
        )

        name4 = gr.Textbox(
            label="Name for Speaker 4",
            visible=False
        )

        name5 = gr.Textbox(
            label="Name for Speaker 5",
            visible=False
        )

        name6 = gr.Textbox(
            label="Name for Speaker 6",
            visible=False
        )

    continue_speakers_button = gr.Button(
        "Continue",
        variant="primary",
        elem_id="confirm-speakers",
        visible=False
    )

    # -----------------------------------------------------
    # FINAL GENERATION
    # -----------------------------------------------------

    generate_button = gr.Button(
        "Generate Meeting Intelligence",
        variant="primary",
        elem_id="generate",
        visible=False
    )

    # Hidden state
    transcript_state = gr.State("")
    speaker_state = gr.State({})

    gr.Markdown(
        "---"
    )

    intelligence_output = gr.HTML(
        """
        <div class="empty-page">
            Analyze a meeting recording to begin.
        </div>
        """
    )

    # -----------------------------------------------------
    # ANALYZE RECORDING
    # -----------------------------------------------------

    analyze_button.click(
        fn=prepare_meeting,
        inputs=[
            audio_input
        ],
        outputs=[
            transcript_state,
            speaker_state,
            speaker_setup,
            speaker_confirmation,
            speaker_mapping_group,
            name1,
            name2,
            name3,
            name4,
            name5,
            name6,
            continue_speakers_button,
            generate_button
        ]
    )

    # -----------------------------------------------------
    # YES / NO SPEAKER FLOW
    # -----------------------------------------------------

    speaker_confirmation.change(
        fn=update_mapping_visibility,
        inputs=[
            speaker_confirmation
        ],
        outputs=[
            speaker_mapping_group,
            continue_speakers_button
        ]
    )

    # -----------------------------------------------------
    # CONFIRM / CONTINUE
    # -----------------------------------------------------

    continue_speakers_button.click(
        fn=finalize_speakers,
        inputs=[
            transcript_state,
            speaker_state,
            speaker_confirmation,
            name1,
            name2,
            name3,
            name4,
            name5,
            name6
        ],
        outputs=[
            transcript_state,
            continue_speakers_button,
            generate_button
        ]
    )

    # -----------------------------------------------------
    # GENERATE INTELLIGENCE
    # -----------------------------------------------------

    generate_event = generate_button.click(
        fn=generate_brief,
        inputs=[
            transcript_state,
            speaker_state,
            topic_input
        ],
        outputs=[
            intelligence_output,
            analytics_output,
            history_dropdown,
            task_dropdown,
            task_status_dropdown,
            task_status_message
        ],
        show_progress="hidden"
    )

    generate_event.then(
        fn=refresh_workspace_analytics,
        inputs=[],
        outputs=[workspace_analytics_output]
    )

    search_button.click(
        fn=build_search_choices,
        inputs=[search_input],
        outputs=[history_dropdown]
    )

    def update_history_selection(meeting_id):
        task_choices = build_task_choices(meeting_id)
        first_task = task_choices[0][1] if task_choices else None
        current_status = (get_task(first_task) or {}).get("status", "Pending") if first_task is not None else "Pending"

        return (
            gr.update(interactive=meeting_id is not None),
            gr.update(interactive=meeting_id is not None),
            gr.update(interactive=meeting_id is not None),
            gr.update(interactive=first_task is not None),
            gr.update(choices=task_choices, value=first_task),
            gr.update(value=current_status),
            ""
        )

    history_dropdown.change(
        fn=update_history_selection,
        inputs=[history_dropdown],
        outputs=[
            open_meeting_button,
            close_meeting_button,
            delete_meeting_button,
            update_task_button,
            task_dropdown,
            task_status_dropdown,
            task_status_message
        ]
    )

    task_dropdown.change(
        fn=task_selection_changed,
        inputs=[task_dropdown],
        outputs=[task_status_dropdown, task_status_message]
    )

    update_task_event = update_task_button.click(
        fn=save_task_status,
        inputs=[task_dropdown, task_status_dropdown, history_dropdown],
        outputs=[task_dropdown, task_status_dropdown, task_status_message]
    )

    update_task_event.then(
        fn=refresh_workspace_analytics,
        inputs=[],
        outputs=[workspace_analytics_output]
    )

    open_meeting_button.click(
        fn=open_saved_meeting,
        inputs=[
            history_dropdown
        ],
        outputs=[
            intelligence_output,
            analytics_output
        ]
    )

    close_event = close_meeting_button.click(
        fn=close_saved_meeting,
        inputs=[],
        outputs=[
            history_dropdown,
            intelligence_output,
            analytics_output
        ]
    )

    close_event.then(
        fn=update_history_selection,
        inputs=[history_dropdown],
        outputs=[
            open_meeting_button,
            close_meeting_button,
            delete_meeting_button,
            update_task_button,
            task_dropdown,
            task_status_dropdown,
            task_status_message
        ]
    )

    delete_event = delete_meeting_button.click(
        fn=delete_saved_meeting,
        inputs=[
            history_dropdown
        ],
        outputs=[
            history_dropdown,
            intelligence_output,
            analytics_output
        ]
    )

    delete_event.then(
        fn=update_history_selection,
        inputs=[history_dropdown],
        outputs=[
            open_meeting_button,
            close_meeting_button,
            delete_meeting_button,
            update_task_button,
            task_dropdown,
            task_status_dropdown,
            task_status_message
        ]
    ).then(
        fn=refresh_workspace_analytics,
        inputs=[],
        outputs=[workspace_analytics_output]
    )


if __name__ == "__main__":
    demo.queue().launch()