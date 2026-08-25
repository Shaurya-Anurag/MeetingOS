import html
import gradio as gr
import re

from Services.Transcription import transcribe_audio
from app.analytics_service import analyze_transcript
from app.intelligence_service import generate_meeting_intelligence


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
        build_speaker_setup_html(speakers),
        gr.update(
            value=None,
            visible=True
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


# =========================================================
# GENERATE MEETING INTELLIGENCE
# =========================================================

def generate_brief(
    transcript,
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
            """
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

    return (
        intelligence_html,
        analytics_html
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

@media (max-width: 850px) {

    .topic-grid,
    .two-column {
        grid-template-columns: 1fr;
    }
}
"""


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

    generate_button.click(
        fn=generate_brief,
        inputs=[
            transcript_state,
            topic_input
        ],
        outputs=[
            intelligence_output,
            analytics_output
        ],
        show_progress="hidden"
    )


if __name__ == "__main__":
    demo.queue().launch()