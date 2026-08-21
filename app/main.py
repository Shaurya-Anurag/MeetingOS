import gradio as gr

from Services.Transcription import transcribe_audio
from app.brief_service import generate_executive_brief


def generate_brief(audio_path, topic):
    if not audio_path:
        return "Please upload a meeting audio file."

    if not topic or not topic.strip():
        topic = "Meeting Discussion"

    print("Transcribing audio...")
    transcript = transcribe_audio(audio_path)

    print("Generating executive brief...")
    brief = generate_executive_brief(
        topic=topic,
        source_notes=transcript
    )

    return brief


with gr.Blocks(title="MeetingOS") as demo:

    gr.Markdown(
        """
        # MeetingOS
        ### AI Meeting Intelligence

        Upload a meeting recording and generate an executive brief automatically.
        """
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

    generate_button = gr.Button(
        "Generate Executive Brief",
        variant="primary"
    )

    brief_output = gr.Markdown(
        label="Executive Brief"
    )

    generate_button.click(
        fn=generate_brief,
        inputs=[audio_input, topic_input],
        outputs=brief_output
    )


if __name__ == "__main__":
    demo.launch()