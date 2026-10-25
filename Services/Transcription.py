import os
import subprocess
import tempfile
import time

from app.pipeline_diagnostics import emit_event, new_run_id, stage_event
from faster_whisper import WhisperModel
from app.speaker_service import diarize_audio


print("Loading transcription model...", flush=True)

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8",
)

print("Transcription model loaded.", flush=True)


def prepare_diarization_audio(audio_path: str) -> str:
    """Convert input audio to 16 kHz mono PCM WAV for diarization."""
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = temp_file.name
    temp_file.close()

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-i",
                audio_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                wav_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        try:
            os.remove(wav_path)
        except OSError:
            pass
        raise RuntimeError(
            "FFmpeg was not found. Make sure FFmpeg is available on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        try:
            os.remove(wav_path)
        except OSError:
            pass
        raise RuntimeError(
            "FFmpeg failed while preparing audio for diarization."
        ) from exc

    return wav_path


def find_speaker(start: float, end: float, speaker_segments: list) -> str:
    """Assign the speaker with the greatest temporal overlap."""
    best_speaker = "UNKNOWN"
    best_overlap = 0.0

    for speaker_segment in speaker_segments:
        overlap = max(
            0.0,
            min(end, speaker_segment["end"])
            - max(start, speaker_segment["start"]),
        )
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker_segment["speaker"]

    return best_speaker


def transcribe_audio(
    audio_path: str,
    *,
    run_id: str | None = None,
) -> str:
    run_id = run_id or new_run_id()
    total_start = time.perf_counter()
    diarization_audio = None

    try:
        # 1. Whisper transcription
        print("[TIMING] Whisper transcription started...", flush=True)
        whisper_start = time.perf_counter()

        with stage_event(run_id, "whisper_transcription") as stage:
            print("[TIMING] Calling model.transcribe()...", flush=True)

            segments, info = model.transcribe(
                audio_path,
                beam_size=1,
                vad_filter=True,
            )

            print(
                "[TIMING] model.transcribe() returned in "
                f"{time.perf_counter() - whisper_start:.2f}s; consuming segments...",
                flush=True,
            )

            # faster-whisper is lazy: consume the generator to run inference.
            whisper_segments = list(segments)
            whisper_duration = time.perf_counter() - whisper_start

            print(
                f"[TIMING] Whisper finished: {len(whisper_segments)} segments "
                f"in {whisper_duration:.2f}s",
                flush=True,
            )

            stage["metadata"]["segment_count"] = len(whisper_segments)
            stage["metadata"]["model"] = "base"
            stage["metadata"]["language"] = getattr(info, "language", None)
            stage["metadata"]["duration_ms"] = round(whisper_duration * 1000, 2)

        # 2. Audio conversion
        print("[TIMING] Preparing diarization audio...", flush=True)
        conversion_start = time.perf_counter()

        with stage_event(run_id, "audio_conversion") as stage:
            diarization_audio = prepare_diarization_audio(audio_path)
            conversion_duration = time.perf_counter() - conversion_start
            stage["metadata"]["status"] = "converted"
            stage["metadata"]["format"] = "wav"
            stage["metadata"]["sample_rate_hz"] = 16000
            stage["metadata"]["channels"] = 1
            stage["metadata"]["duration_ms"] = round(conversion_duration * 1000, 2)

        print(
            f"[TIMING] Audio conversion finished in {conversion_duration:.2f}s",
            flush=True,
        )

        # 3. Speaker diarization
        print("[TIMING] Speaker diarization started...", flush=True)
        diarization_start = time.perf_counter()

        try:
            with stage_event(run_id, "speaker_diarization") as stage:
                speaker_segments = diarize_audio(diarization_audio)
                diarization_duration = time.perf_counter() - diarization_start
                stage["metadata"]["segment_count"] = len(speaker_segments)
                stage["metadata"]["speaker_count"] = len({
                    segment.get("speaker")
                    for segment in speaker_segments
                    if segment.get("speaker")
                })
                stage["metadata"]["duration_ms"] = round(
                    diarization_duration * 1000, 2
                )
        finally:
            if diarization_audio and os.path.exists(diarization_audio):
                try:
                    os.remove(diarization_audio)
                except OSError:
                    pass
                diarization_audio = None

        print(
            f"[TIMING] Speaker diarization finished in "
            f"{diarization_duration:.2f}s ({len(speaker_segments)} segments)",
            flush=True,
        )

        # 4. Match Whisper segments to speakers
        print("[TIMING] Matching speakers...", flush=True)
        matching_start = time.perf_counter()

        with stage_event(run_id, "speaker_matching") as stage:
            transcript = []
            unknown_count = 0

            for segment in whisper_segments:
                speaker = find_speaker(
                    segment.start,
                    segment.end,
                    speaker_segments,
                )

                if speaker == "UNKNOWN":
                    unknown_count += 1

                transcript.append(
                    f"[{segment.start:.2f}s -> {segment.end:.2f}s] "
                    f"{speaker}: {segment.text.strip()}"
                )

            result = "\n".join(transcript)
            matching_duration = time.perf_counter() - matching_start

            stage["metadata"]["transcript_segment_count"] = len(whisper_segments)
            stage["metadata"]["unknown_speaker_count"] = unknown_count
            stage["metadata"]["matched_segment_count"] = (
                len(whisper_segments) - unknown_count
            )
            stage["metadata"]["duration_ms"] = round(matching_duration * 1000, 2)

        print(
            f"[TIMING] Speaker matching finished in {matching_duration:.2f}s",
            flush=True,
        )

        total_duration = time.perf_counter() - total_start
        emit_event(
            run_id,
            "transcription_pipeline",
            "success",
            duration_ms=total_duration * 1000,
            metadata={
                "whisper_segment_count": len(whisper_segments),
                "diarization_segment_count": len(speaker_segments),
                "unknown_speaker_count": unknown_count,
            },
        )

        print(
            f"[TIMING] TOTAL transcription pipeline: {total_duration:.2f}s",
            flush=True,
        )
        return result

    except Exception as exc:
        emit_event(
            run_id,
            "transcription_pipeline",
            "failed",
            duration_ms=(time.perf_counter() - total_start) * 1000,
            error_type=type(exc).__name__,
        )
        raise

    finally:
        if diarization_audio and os.path.exists(diarization_audio):
            try:
                os.remove(diarization_audio)
            except OSError:
                emit_event(
                    run_id,
                    "audio_cleanup",
                    "failed",
                    error_type="OSError",
                )
