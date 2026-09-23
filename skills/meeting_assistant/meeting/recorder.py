"""
Meeting Audio Recorder
Captures microphone audio using sounddevice.
Saves WAV files to data/meetings/audio/
Runs recording in a background thread — bot stays responsive during recording.
"""

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from loguru import logger

SAMPLE_RATE = 16000   # 16kHz — optimal for Whisper
CHANNELS = 1          # mono — sufficient for speech


class AudioRecorder:
    """
    Records microphone audio to WAV file.
    Thread-safe — recording runs in background via sounddevice callback.
    """

    def __init__(self, output_dir: str = "data/meetings/audio"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._recording = False
        self._frames = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self.current_file: Optional[str] = None
        self._start_time: Optional[datetime] = None

    def start(self) -> str:
        """Start recording. Returns path to output WAV file."""
        if self._recording:
            logger.warning("AudioRecorder: already recording")
            return self.current_file

        with self._lock:
            self._frames = []
            self._recording = True
            self._start_time = datetime.now()

        timestamp = self._start_time.strftime("%Y-%m-%d_%H-%M-%S")
        self.current_file = str(self.output_dir / f"meeting_{timestamp}.wav")

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._callback,
            blocksize=1024,
        )
        self._stream.start()
        logger.info(f"🎙 Recording started → {self.current_file}")
        return self.current_file

    def _callback(self, indata, frames, time, status):
        """Called by sounddevice on each audio chunk."""
        if status:
            logger.warning(f"AudioRecorder status: {status}")
        if self._recording:
            with self._lock:
                self._frames.append(indata.copy())

    def stop(self) -> Optional[str]:
        """Stop recording and save WAV file. Returns path to saved file."""
        if not self._recording:
            logger.warning("AudioRecorder: not currently recording")
            return None

        self._recording = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._lock:
            if not self._frames:
                logger.warning("AudioRecorder: no audio captured")
                return None
            audio = np.concatenate(self._frames, axis=0)

        sf.write(self.current_file, audio, SAMPLE_RATE)
        duration = (datetime.now() - self._start_time).total_seconds() / 60
        logger.info(
            f"⏹ Recording saved → {self.current_file} "
            f"({duration:.1f} min, {len(audio)/SAMPLE_RATE:.0f}s)"
        )
        return self.current_file

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration_minutes(self) -> float:
        """How long we have been recording so far."""
        if not self._recording or not self._start_time:
            return 0.0
        return (datetime.now() - self._start_time).total_seconds() / 60

    def get_status(self) -> str:
        if self._recording:
            return f"🎙 Recording in progress ({self.duration_minutes:.1f} min elapsed)"
        return "⏹ Not recording"
