"""
Meeting Transcriber
Uses OpenAI Whisper for speech-to-text.
Speaker diarization disabled — single speaker mode (SPEAKER_00).
Fully free — no API keys, no HuggingFace token, no credentials required.
Runs 100% locally.

Requirements:
  pip install openai-whisper soundfile torch --break-system-packages
"""

from pathlib import Path
from typing import Optional
from loguru import logger


class MeetingTranscriber:
    """
    Transcribes audio files using Whisper.
    Models are loaded lazily on first use to avoid slow startup.
    No credentials or API keys required.
    """

    def __init__(self, whisper_model: str = "base"):
        """
        Args:
            whisper_model: Whisper model size.
                          "base"   = fast, good quality (recommended)
                          "small"  = better quality, slower
                          "medium" = best quality, much slower
        """
        self.whisper_model_name = whisper_model
        self._whisper = None
        self._diarizer = None

    def _load_models(self):
        """Lazy-load Whisper model on first transcription call."""
        if self._whisper is None:
            # Inject bundled ffmpeg from imageio-ffmpeg into PATH
            # so Whisper can find it without a system-level ffmpeg install
            import os, shutil, tempfile
            try:
                import imageio_ffmpeg
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()  # full path to ffmpeg binary
                ffmpeg_dir = os.path.dirname(ffmpeg_exe)

                # Whisper calls ffmpeg by name ("ffmpeg"), but imageio bundles it
                # with a versioned name like "ffmpeg-win64-v6.0.exe"
                # So we copy/symlink it as "ffmpeg.exe" in a temp dir
                tmp_dir = os.path.join(tempfile.gettempdir(), "localmind_ffmpeg")
                os.makedirs(tmp_dir, exist_ok=True)
                ffmpeg_target = os.path.join(tmp_dir, "ffmpeg.exe")
                if not os.path.exists(ffmpeg_target):
                    shutil.copy2(ffmpeg_exe, ffmpeg_target)
                    logger.info(f"Copied ffmpeg to: {ffmpeg_target}")

                # Prepend temp dir so "ffmpeg" resolves correctly
                os.environ["PATH"] = tmp_dir + os.pathsep + os.environ.get("PATH", "")
                logger.info(f"ffmpeg injected from imageio-ffmpeg: {ffmpeg_target}")
            except Exception as e:
                logger.warning(f"imageio-ffmpeg not available, falling back to system ffmpeg: {e}")

            import whisper
            logger.info(f"Loading Whisper '{self.whisper_model_name}' model...")
            self._whisper = whisper.load_model(self.whisper_model_name)
            logger.info("Whisper model loaded ✅")
        # diarizer disabled — single speaker mode (SPEAKER_00)
        self._diarizer = None

    def transcribe(self, audio_path: str) -> dict:
        """
        Full transcription pipeline: Whisper + single speaker labels.

        Returns:
            {
                "audio_path": str,
                "segments": [
                    {
                        "start": float,
                        "end": float,
                        "speaker": str,
                        "text": str,
                    },
                    ...
                ],
                "full_text": str,
                "speakers": list[str],
            }
        """
        self._load_models()
        audio_path = str(audio_path)
        logger.info(f"Transcribing {audio_path}...")

        # ── Step 1: Whisper transcription ─────────────────
        logger.info("Running Whisper speech-to-text...")
        result = self._whisper.transcribe(
            audio_path,
            word_timestamps=True,
            verbose=False,
            language="en",      # set to None for auto language detection
            task="transcribe",
        )
        logger.info(f"Whisper complete — {len(result['segments'])} segments")

        # ── Step 2: Speaker diarization (disabled) ────────
        logger.info("Diarization disabled — using single speaker mode")
        diarization_segments = []

        # ── Step 3: Build segments with speaker labels ────
        segments = []
        speakers_found = set()

        for seg in result["segments"]:
            speaker = self._get_dominant_speaker(
                diarization_segments, seg["start"], seg["end"]
            )
            speakers_found.add(speaker)
            segments.append({
                "start": round(seg["start"], 2),
                "end": round(seg["end"], 2),
                "speaker": speaker,
                "text": seg["text"].strip(),
            })

        logger.info(
            f"Transcription complete — "
            f"{len(segments)} segments, {len(speakers_found)} speakers: "
            f"{', '.join(sorted(speakers_found))}"
        )

        return {
            "audio_path": audio_path,
            "segments": segments,
            "full_text": result["text"].strip(),
            "speakers": sorted(list(speakers_found)),
        }

    def _get_dominant_speaker(
        self, diarization_segments: list, start: float, end: float
    ) -> str:
        """
        Find which speaker was dominant in the time window [start, end].
        With diarization disabled, always returns SPEAKER_00.
        """
        if not diarization_segments:
            return "SPEAKER_00"

        overlap = {}
        for seg in diarization_segments:
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", 0)
            label = f"SPEAKER_{seg.get('label', 0):02d}"
            o = min(seg_end, end) - max(seg_start, start)
            if o > 0:
                overlap[label] = overlap.get(label, 0) + o

        if not overlap:
            return "UNKNOWN"
        return max(overlap, key=overlap.get)

    def format_transcript(self, transcription: dict) -> str:
        """
        Format transcript as readable markdown with speaker labels and timestamps.

        Example output:
            **SPEAKER_00** [00:00]
              Let's start the meeting.
        """
        lines = []
        current_speaker = None

        for seg in transcription["segments"]:
            ts = self._fmt_time(seg["start"])
            if seg["speaker"] != current_speaker:
                current_speaker = seg["speaker"]
                lines.append(f"\n**{current_speaker}** [{ts}]")
            lines.append(f"  {seg['text']}")

        return "\n".join(lines).strip()

    def format_transcript_plain(self, transcription: dict) -> str:
        """Plain text version (no markdown) for saving to .txt file."""
        lines = []
        current_speaker = None

        for seg in transcription["segments"]:
            ts = self._fmt_time(seg["start"])
            if seg["speaker"] != current_speaker:
                current_speaker = seg["speaker"]
                lines.append(f"\n{current_speaker} [{ts}]")
            lines.append(f"  {seg['text']}")

        return "\n".join(lines).strip()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"