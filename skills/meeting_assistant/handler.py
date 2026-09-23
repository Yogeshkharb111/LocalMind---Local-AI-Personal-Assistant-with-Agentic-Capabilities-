"""
Meeting Assistant Skill Handler
Supports:
  "start meeting recording"           → start mic recording
  "stop recording and summarize"      → stop + transcribe + summarize
  "schedule meeting 15:00 to 16:00"  → auto start/stop at given times
  "cancel meeting schedule"           → remove scheduled meeting
  "meeting status"                    → show recording/schedule status
  "summarize last meeting"            → transcribe + summarize last recorded audio
"""

import asyncio
import os
import re
from loguru import logger

from config.settings import settings
from skills.meeting_assistant.meeting.recorder import AudioRecorder
from skills.meeting_assistant.meeting.transcriber import MeetingTranscriber
from skills.meeting_assistant.meeting.summarizer import MeetingSummarizer
from skills.meeting_assistant.meeting.scheduler import MeetingScheduler

_recorder    = AudioRecorder(output_dir="data/meetings/audio")
_transcriber = MeetingTranscriber(whisper_model="base")
_summarizer  = MeetingSummarizer()
_scheduler   = MeetingScheduler(timezone="Asia/Kolkata")


async def run(message: str, user_id: int, router=None, **kwargs) -> str:
    if not _scheduler.scheduler.running:
        _scheduler.start_scheduler()

    msg = message.lower().strip()

    # ── SUMMARIZE LAST RECORDING ──────────────────────────
    if any(w in msg for w in ["summarize last", "last meeting", "process recording", "summarize meeting", "summarize my meeting"]):
        from pathlib import Path
        audio_dir = Path("data/meetings/audio")
        audio_files = sorted(audio_dir.glob("*.wav"), key=os.path.getmtime, reverse=True)

        if not audio_files:
            return "❌ No recorded meetings found in `data/meetings/audio/`"

        latest = str(audio_files[0])
        await _send_status(router, user_id, f"📁 Found recording: `{latest}`\n🔤 Transcribing with Whisper...")

        try:
            transcription = _transcriber.transcribe(latest)
            segment_count = len(transcription["segments"])
            await _send_status(
                router, user_id,
                f"✅ Transcription done — {segment_count} segments.\n📝 Generating summary..."
            )
            result = await _summarizer.summarize(transcription, duration_minutes=3.0)
            return _summarizer.format_telegram_output(result)
        except Exception as e:
            logger.error(f"Summarize last meeting failed: {e}")
            return f"❌ Failed: {str(e)}"

    # ── START recording ───────────────────────────────────
    if any(w in msg for w in ["start", "begin", "record now", "open mic"]):
        if _recorder.is_recording:
            return f"🎙 Already recording! {_recorder.get_status()}"
        try:
            file_path = _recorder.start()
            return (
                f"🎙 **Recording started!**\n"
                f"📁 Saving to: `{file_path}`\n\n"
                f"Send **'stop recording'** when your meeting is done."
            )
        except Exception as e:
            logger.error(f"Meeting recorder start failed: {e}")
            return (
                f"❌ Failed to start recording: {str(e)}\n"
                f"Make sure a microphone is connected and sounddevice is installed.\n"
                f"`pip install sounddevice soundfile`"
            )

    # ── STOP recording + transcribe + summarize ───────────
    if any(w in msg for w in ["stop", "end", "finish", "done recording"]):
        if not _recorder.is_recording:
            return "⏹ No recording in progress. Send **'start meeting recording'** to begin."

        duration = _recorder.duration_minutes
        await _send_status(router, user_id, "⏹ Recording stopped. Starting transcription...")

        try:
            audio_file = _recorder.stop()
            if not audio_file:
                return "❌ Recording failed — no audio was captured."

            await _send_status(router, user_id, "🔤 Transcribing audio with Whisper...")
            transcription = _transcriber.transcribe(audio_file)

            await _send_status(
                router, user_id,
                f"✅ Transcription done — {len(transcription['segments'])} segments.\n📝 Generating summary..."
            )
            result = await _summarizer.summarize(transcription, duration_minutes=duration)
            return _summarizer.format_telegram_output(result)

        except ImportError as e:
            return f"❌ Missing dependency: {str(e)}\n`pip install openai-whisper --break-system-packages`"
        except Exception as e:
            logger.error(f"Meeting processing failed: {e}")
            return f"❌ Processing failed: {str(e)}"

    # ── SCHEDULE meeting ──────────────────────────────────
    if any(w in msg for w in ["schedule", "set meeting", "auto record"]):
        times = _parse_times(message)
        if not times:
            return "📅 Please specify start and end times.\n\nExample: `schedule meeting 15:00 to 16:00`"

        start_h, start_m, stop_h, stop_m = times

        async def scheduled_start():
            _recorder.start()
            logger.info("Scheduled meeting recording started")

        async def scheduled_stop():
            if _recorder.is_recording:
                duration = _recorder.duration_minutes
                audio_file = _recorder.stop()
                if audio_file:
                    try:
                        transcription = _transcriber.transcribe(audio_file)
                        result = await _summarizer.summarize(transcription, duration_minutes=duration)
                        output = _summarizer.format_telegram_output(result)
                        logger.info(f"Scheduled meeting processed:\n{output[:200]}")
                    except Exception as e:
                        logger.error(f"Scheduled meeting processing failed: {e}")

        confirmation = _scheduler.schedule(
            start_hour=start_h, start_minute=start_m,
            stop_hour=stop_h, stop_minute=stop_m,
            on_start=scheduled_start, on_stop=scheduled_stop,
        )
        return (
            f"📅 **{confirmation}**\n\n"
            f"I'll automatically:\n"
            f"• Start recording at {start_h:02d}:{start_m:02d}\n"
            f"• Stop and summarize at {stop_h:02d}:{stop_m:02d}\n\n"
            f"Send **'cancel meeting schedule'** to cancel."
        )

    # ── CANCEL schedule ───────────────────────────────────
    if any(w in msg for w in ["cancel", "remove schedule", "unschedule"]):
        cancelled = _scheduler.cancel()
        return "✅ Meeting schedule cancelled." if cancelled else "No meeting schedule found to cancel."

    # ── STATUS ────────────────────────────────────────────
    if any(w in msg for w in ["status", "recording status", "what's recording"]):
        return "\n".join([
            "📊 **Meeting Assistant Status**",
            "",
            f"🎙 Recording: {_recorder.get_status()}",
            "",
            f"{_scheduler.get_status()}",
        ])

    # ── HELP / fallback ───────────────────────────────────
    return (
        "🎙 **Meeting Assistant**\n\n"
        "Available commands:\n"
        "• `start meeting recording` — begin recording\n"
        "• `stop recording` — stop and generate summary\n"
        "• `summarize last meeting` — summarize the last recorded audio\n"
        "• `schedule meeting 15:00 to 16:00` — auto record at set times\n"
        "• `cancel meeting schedule` — remove schedule\n"
        "• `meeting status` — check current state\n\n"
        "**Setup:**\n"
        "`pip install openai-whisper sounddevice soundfile apscheduler pytz --break-system-packages`"
    )


def _parse_times(message: str):
    times = re.findall(r"\b(\d{1,2}):(\d{2})\b", message)
    if len(times) >= 2:
        return int(times[0][0]), int(times[0][1]), int(times[1][0]), int(times[1][1])
    times_ampm = re.findall(r"\b(\d{1,2})\s*(am|pm)\b", message.lower())
    if len(times_ampm) >= 2:
        def to_24h(h, meridiem):
            h = int(h)
            if meridiem == "pm" and h != 12: h += 12
            elif meridiem == "am" and h == 12: h = 0
            return h
        return to_24h(*times_ampm[0]), 0, to_24h(*times_ampm[1]), 0
    return None


async def _send_status(router, user_id: int, text: str):
    try:
        if router and hasattr(router, "_send_intermediate"):
            await router._send_intermediate(user_id, text)
        else:
            logger.info(f"Status update: {text}")
    except Exception:
        pass
