import os
import subprocess
import tempfile
import time

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
    total_start = time.perf_counter()

    # 1. Whisper transcription
    stage_start = time.perf_counter()
    print("[TIMING] Whisper transcription started...")

    segments, info = model.transcribe(
        audio_path,
        beam_size=1,
        vad_filter=True
    )
    whisper_segments = list(segments)

    print(
        f"[TIMING] Whisper: "
        f"{time.perf_counter() - stage_start:.2f}s "
        f"({len(whisper_segments)} segments)"
    )

    # 2. Audio conversion
    stage_start = time.perf_counter()
    print("[TIMING] Preparing diarization audio...")

    diarization_audio = prepare_diarization_audio(audio_path)

    print(
        f"[TIMING] Audio conversion: "
        f"{time.perf_counter() - stage_start:.2f}s"
    )

    # 3. Speaker diarization
    stage_start = time.perf_counter()
    print("[TIMING] Speaker diarization started...")

    try:
        speaker_segments = diarize_audio(diarization_audio)
    finally:
        if os.path.exists(diarization_audio):
            os.remove(diarization_audio)

    print(
        f"[TIMING] Diarization: "
        f"{time.perf_counter() - stage_start:.2f}s "
        f"({len(speaker_segments)} speaker segments)"
    )

    # 4. Merge Whisper and diarization
    stage_start = time.perf_counter()
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

    result = "\n".join(transcript)

    print(
        f"[TIMING] Speaker matching and formatting: "
        f"{time.perf_counter() - stage_start:.2f}s"
    )
    print(
        f"[TIMING] TOTAL transcription pipeline: "
        f"{time.perf_counter() - total_start:.2f}s"
    )

    return result
