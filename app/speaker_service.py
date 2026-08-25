import os

from dotenv import load_dotenv
from pyannote.audio import Pipeline

load_dotenv()

_pipeline = None


def get_diarization_pipeline():
    global _pipeline

    if _pipeline is None:
        token = os.getenv("HUGGINGFACE_TOKEN")

        if not token:
            raise ValueError(
                "HUGGINGFACE_TOKEN is missing from .env"
            )

        print("Loading speaker diarization model...")

        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=token
        )

        print("Speaker diarization model loaded.")

    return _pipeline


def diarize_audio(audio_path: str):
    """
    Return speaker-labeled time segments for an audio file.
    """

    pipeline = get_diarization_pipeline()

    diarization = pipeline(audio_path)

    segments = []

    for turn, _, speaker in diarization.speaker_diarization.itertracks(
        yield_label=True
    ):
        segments.append(
            {
                "start": round(turn.start, 2),
                "end": round(turn.end, 2),
                "speaker": speaker
            }
        )

    return segments