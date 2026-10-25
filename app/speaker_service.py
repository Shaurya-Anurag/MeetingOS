import os
import time

from dotenv import load_dotenv
from pyannote.audio import Pipeline

load_dotenv()

_pipeline = None


def get_diarization_pipeline():
    global _pipeline

    if _pipeline is None:
        token = os.getenv("HUGGINGFACE_TOKEN")
        if not token:
            raise ValueError("HUGGINGFACE_TOKEN is missing from .env")

        print("[DIARIZATION] Loading model...", flush=True)
        started = time.perf_counter()

        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=token,
        )

        print(
            f"[DIARIZATION] Model loaded in "
            f"{time.perf_counter() - started:.2f}s",
            flush=True,
        )

        try:
            import torch

            print(
                f"[DIARIZATION] Device: {_pipeline.device} | "
                f"CUDA available: {torch.cuda.is_available()}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[DIARIZATION] Device check unavailable: {exc}",
                flush=True,
            )
    else:
        print("[DIARIZATION] Reusing cached pipeline", flush=True)

    return _pipeline


def diarize_audio(audio_path: str):
    """Return speaker-labeled time segments for an audio file."""
    pipeline = get_diarization_pipeline()

    print(f"[DIARIZATION] Inference started: {audio_path}", flush=True)
    started = time.perf_counter()

    # Keep the standard call: experimental hooks and forced thread/batch
    # settings previously caused hangs or slower runs on this machine.
    diarization = pipeline(audio_path)

    print(
        f"[DIARIZATION] Inference finished in "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )

    segments = []
    for turn, _, speaker in diarization.speaker_diarization.itertracks(
        yield_label=True
    ):
        segments.append(
            {
                "start": round(turn.start, 2),
                "end": round(turn.end, 2),
                "speaker": speaker,
            }
        )

    print(
        f"[DIARIZATION] Extracted {len(segments)} speaker segments",
        flush=True,
    )
    return segments