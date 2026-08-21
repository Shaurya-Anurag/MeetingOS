from faster_whisper import WhisperModel


print("Loading transcription model...")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("Transcription model loaded.")


def transcribe_audio(audio_path: str) -> str:
    segments, info = model.transcribe(
        audio_path,
        beam_size=5
    )

    transcript = []

    for segment in segments:
        transcript.append(
            f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}"
        )

    return "\n".join(transcript)
if __name__ == "__main__":
    transcript = transcribe_audio("test.mp3")
    print("\n===== TRANSCRIPT =====\n")
    print(transcript)