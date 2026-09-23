"""
Meeting Summarizer
Uses your existing Ollama LLM (kimi-k2.5:cloud) to:
  1. Extract per-speaker key points, action items, decisions
  2. Generate a full structured meeting summary
  3. Save transcript (.txt) and summary (.md) to data/meetings/transcripts/
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from config.settings import settings


TRANSCRIPTS_DIR = Path("data/meetings/transcripts")


class MeetingSummarizer:
    """
    LLM-based meeting summarization.
    Reuses your existing Ollama/kimi setup — no new API keys needed.
    """

    def __init__(self):
        self.llm_base_url = settings.LLM_BASE_URL
        self.llm_api_key = settings.LLM_API_KEY
        self.llm_model = settings.LLM_MODEL
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    async def summarize(self, transcription: dict, duration_minutes: float = 0.0) -> dict:
        """
        Full summarization pipeline.

        Args:
            transcription: Output from MeetingTranscriber.transcribe()
            duration_minutes: Meeting duration in minutes

        Returns:
            {
                "summary": str,
                "speaker_notes": {speaker: notes_str},
                "speakers": list[str],
                "duration_minutes": float,
                "transcript_file": str,
                "summary_file": str,
            }
        """
        segments = transcription["segments"]
        speakers = transcription["speakers"]
        full_text = transcription["full_text"]
        audio_path = transcription["audio_path"]

        # ── Per-speaker notes ──────────────────────────────
        by_speaker = defaultdict(list)
        for seg in segments:
            by_speaker[seg["speaker"]].append(seg["text"])

        logger.info(f"Generating per-speaker notes for {len(speakers)} speakers...")
        speaker_notes = {}
        for speaker, texts in by_speaker.items():
            combined = " ".join(texts)
            speaker_notes[speaker] = await self._call_llm(
                f"You are analyzing a meeting transcript. "
                f"Below are all statements made by {speaker} during the meeting.\n\n"
                f"Statements:\n{combined}\n\n"
                f"Extract and list:\n"
                f"- Key points made\n"
                f"- Action items they committed to\n"
                f"- Decisions they made or agreed to\n"
                f"- Questions they raised\n\n"
                f"Format as concise bullet points. If a category has nothing, skip it."
            )
            logger.debug(f"Speaker notes generated for {speaker}")

        # ── Full meeting summary ───────────────────────────
        logger.info("Generating full meeting summary...")
        meeting_summary = await self._call_llm(
            f"You are a professional meeting assistant. "
            f"Summarize the following meeting transcript.\n\n"
            f"Transcript:\n{full_text}\n\n"
            f"Provide a structured summary with these sections:\n"
            f"1. **Main Topics Discussed**\n"
            f"2. **Key Decisions Made**\n"
            f"3. **Action Items** (with owner names if mentioned)\n"
            f"4. **Questions Raised**\n"
            f"5. **Overall Outcome**\n\n"
            f"Be concise and clear."
        )

        # ── Save files ────────────────────────────────────
        base_name = Path(audio_path).stem  # e.g. meeting_2026-03-10_15-00-00
        transcript_file, summary_file = self._save_files(
            base_name=base_name,
            transcription=transcription,
            summary=meeting_summary,
            speaker_notes=speaker_notes,
            duration_minutes=duration_minutes,
        )

        return {
            "summary": meeting_summary,
            "speaker_notes": speaker_notes,
            "speakers": speakers,
            "duration_minutes": duration_minutes,
            "transcript_file": transcript_file,
            "summary_file": summary_file,
        }

    def _save_files(
        self,
        base_name: str,
        transcription: dict,
        summary: str,
        speaker_notes: dict,
        duration_minutes: float,
    ):
        """Save raw transcript (.txt) and formatted summary (.md)."""

        # ── Raw transcript .txt ────────────────────────────
        txt_path = TRANSCRIPTS_DIR / f"{base_name}.txt"
        txt_lines = [
            f"Meeting Transcript",
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Duration: {duration_minutes:.1f} minutes",
            f"Speakers: {', '.join(transcription['speakers'])}",
            f"{'='*60}",
            "",
        ]
        current_speaker = None
        for seg in transcription["segments"]:
            from skills.meeting_assistant.meeting.transcriber import MeetingTranscriber
            ts = MeetingTranscriber._fmt_time(seg["start"])
            if seg["speaker"] != current_speaker:
                current_speaker = seg["speaker"]
                txt_lines.append(f"\n{current_speaker} [{ts}]")
            txt_lines.append(f"  {seg['text']}")

        txt_path.write_text("\n".join(txt_lines), encoding="utf-8")
        logger.info(f"Transcript saved → {txt_path}")

        # ── Summary .md ───────────────────────────────────
        md_path = TRANSCRIPTS_DIR / f"{base_name}.md"
        md_lines = [
            f"# Meeting Summary",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
            f"**Duration:** {duration_minutes:.1f} minutes  ",
            f"**Speakers:** {', '.join(transcription['speakers'])}",
            "",
            "---",
            "",
            "## 📝 Overall Summary",
            "",
            summary,
            "",
            "---",
            "",
            "## 👤 Per-Speaker Notes",
            "",
        ]
        for speaker, notes in speaker_notes.items():
            md_lines.append(f"### {speaker}")
            md_lines.append(notes)
            md_lines.append("")

        md_lines += [
            "---",
            "",
            "## 📄 Full Transcript",
            "",
        ]
        current_speaker = None
        for seg in transcription["segments"]:
            from skills.meeting_assistant.meeting.transcriber import MeetingTranscriber
            ts = MeetingTranscriber._fmt_time(seg["start"])
            if seg["speaker"] != current_speaker:
                current_speaker = seg["speaker"]
                md_lines.append(f"\n**{current_speaker}** [{ts}]")
            md_lines.append(f"  {seg['text']}")

        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        logger.info(f"Summary saved → {md_path}")

        return str(txt_path), str(md_path)

    def format_telegram_output(self, result: dict) -> str:
        """
        Format summary for Telegram message.
        Keeps it under 4096 chars (Telegram limit).
        """
        lines = [
            "📋 **Meeting Summary**",
            f"⏱ Duration: {result['duration_minutes']:.1f} minutes",
            f"👥 Speakers: {', '.join(result['speakers'])}",
            "",
            "## 📝 Overall Summary",
            result["summary"],
            "",
            "## 👤 Per-Speaker Notes",
        ]
        for speaker, notes in result["speaker_notes"].items():
            lines.append(f"\n**{speaker}**")
            lines.append(notes)

        lines += [
            "",
            f"📁 Transcript: `{result['transcript_file']}`",
            f"📁 Summary: `{result['summary_file']}`",
        ]

        output = "\n".join(lines)

        # Truncate if too long for Telegram
        if len(output) > 4000:
            output = output[:3900] + "\n\n... _(truncated — see summary file for full details)_"

        return output

    async def _call_llm(self, prompt: str) -> str:
        """Call Ollama LLM with a single prompt."""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1024,
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Summarizer LLM call failed: {e}")
            return f"_(summarization failed: {e})_"
