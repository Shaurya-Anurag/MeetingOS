import os
import subprocess
import tempfile

from faster_whisper import WhisperModel

from app.speaker_service import diarize_audio


print("Loading transcription model...")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("Transcription model loaded.")


def prepare_diarization_audio(audio_path: str) -> str:
    """
    Convert input audio to 16 kHz mono PCM WAV for diarization.
    """

    temp_file = tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False
    )

    wav_path = temp_file.name
    temp_file.close()

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                audio_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                wav_path
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise RuntimeError(
            "FFmpeg was not found. Make sure FFmpeg is available on PATH."
        )
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "FFmpeg failed while preparing audio for diarization."
        )

    return wav_path


def find_speaker(start: float, end: float, speaker_segments: list) -> str:
    """
    Assign the speaker whose diarization segment has the greatest
    temporal overlap with the Whisper segment.
    """

    best_speaker = "UNKNOWN"
    best_overlap = 0.0

    for speaker_segment in speaker_segments:

        speaker_start = speaker_segment["start"]
        speaker_end = speaker_segment["end"]

        overlap_start = max(start, speaker_start)
        overlap_end = min(end, speaker_end)

        overlap = max(
            0.0,
            overlap_end - overlap_start
        )

        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker_segment["speaker"]

    return best_speaker


def transcribe_audio(audio_path: str) -> str:

    # -------------------------
    # 1. Whisper transcription
    # -------------------------

    segments, info = model.transcribe(
        audio_path,
        beam_size=1,
        vad_filter=True
    )

    whisper_segments = list(segments)

    # -------------------------
    # 2. Speaker diarization
    # -------------------------

    print("Running speaker diarization...")

    diarization_audio = prepare_diarization_audio(
        audio_path
    )

    try:
        speaker_segments = diarize_audio(
            diarization_audio
        )
    finally:
        if os.path.exists(diarization_audio):
            os.remove(diarization_audio)

    # -------------------------
    # 3. Merge Whisper + speakers
    # -------------------------

    transcript = []

    for segment in whisper_segments:

        speaker = find_speaker(
            segment.start,
            segment.end,
            speaker_segments
        )

        transcript.append(
            f"[{segment.start:.2f}s -> {segment.end:.2f}s] "
            f"{speaker}: {segment.text.strip()}"
        )

    return "\n".join(transcript)


if __name__ == "__main__":

    transcript = transcribe_audio(
        "test_diarization.wav"
    )

    print(
        "\n===== SPEAKER-AWARE TRANSCRIPT =====\n"
    )

    print(transcript)