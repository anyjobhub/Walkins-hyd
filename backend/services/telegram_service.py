"""
services/telegram_service.py — Telegram bot integration for broadcasting jobs.

Handles:
  - Message formatting (HTML parse mode)
  - Sending individual jobs and batch jobs to channels
  - Daily digest messages
  - User subscription management
  - Rate-limited sending (respects Telegram's 30 msg/sec limit for bots)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from config import Config

logger = logging.getLogger(__name__)


class TelegramService:
    """
    Service for sending jobs to a Telegram channel or group.

    Uses the python-telegram-bot library (v21.x) with async support.
    The public methods are synchronous wrappers around async operations.
    """

    def __init__(self):
        self.token = Config.telegram.BOT_TOKEN
        self.channel_id = Config.telegram.CHANNEL_ID
        self.admin_chat_id = Config.telegram.ADMIN_CHAT_ID
        self.max_len = Config.telegram.MAX_MESSAGE_LENGTH

        if not self.token:
            logger.warning(
                "TELEGRAM_BOT_TOKEN not set — Telegram features will be disabled"
            )
        if not self.channel_id:
            logger.warning("TELEGRAM_CHANNEL_ID not set")

    @property
    def is_configured(self) -> bool:
        """Return True if both token and channel_id are set."""
        return bool(self.token and self.channel_id)

    # -------------------------------------------------------------------------
    # Message Formatting
    # -------------------------------------------------------------------------
    def format_job_message(self, job: Dict[str, Any]) -> str:
        """
        Format a job dict as an HTML Telegram message.

        Uses HTML parse mode for bold/italic/links.
        Max length: 4096 characters (Telegram limit).
        """
        is_walkin = job.get("is_walkin", False)
        is_fresher = job.get("is_fresher_friendly", False)

        # Badges
        badges = []
        if is_walkin:
            badges.append("🚶 <b>WALK-IN</b>")
        if is_fresher:
            badges.append("🌱 <b>FRESHER FRIENDLY</b>")

        badge_line = " | ".join(badges) + "\n" if badges else ""

        salary = job.get("salary") or "Not Disclosed"
        experience = job.get("experience") or "Any"
        location = job.get("location") or "India"
        company = job.get("company") or "Unknown Company"
        title = job.get("title") or "Job Opening"
        source = (job.get("source") or "").capitalize()

        # Walk-in section
        walkin_section = ""
        if is_walkin:
            dates = job.get("walkin_dates") or "See description"
            time_ = job.get("walkin_time") or "See description"
            address = job.get("address") or "See job link"
            walkin_section = (
                f"\n\n🗓 <b>WALK-IN DETAILS</b>\n"
                f"📅 <b>Dates:</b> {dates}\n"
                f"⏰ <b>Time:</b> {time_}\n"
                f"📍 <b>Venue:</b> {address}"
            )

        # Contact section
        contact_section = ""
        if job.get("contact_person") or job.get("contact_phone"):
            contact_section = "\n\n📞 <b>Contact</b>"
            if job.get("contact_person"):
                contact_section += f"\n👤 {job['contact_person']}"
            if job.get("contact_phone"):
                contact_section += f"\n📱 {job['contact_phone']}"

        # Skills
        skills_str = ""
        skills = job.get("skills") or []
        if skills:
            skill_list = ", ".join(str(s) for s in skills[:8])
            skills_str = f"\n🛠 <b>Skills:</b> {skill_list}"

        # Extracted date
        extracted = ""
        if job.get("extracted_at_human") or job.get("extracted_at"):
            date_str = job.get("extracted_at_human", "Today")
            extracted = date_str

        job_url = job.get("job_url", "#")

        msg = (
            f"{badge_line}"
            f"\n🔥 <b>{title}</b>\n"
            f"🏢 {company}\n"
            f"📍 {location}\n"
            f"\n"
            f"💰 <b>Salary:</b> {salary}\n"
            f"📊 <b>Experience:</b> {experience}"
            f"{skills_str}"
            f"{walkin_section}"
            f"{contact_section}\n"
            f"\n"
            f"🔗 <a href='{job_url}'>View Full Job →</a>\n"
            f"\n"
            f"📋 Source: {source}"
            + (f" | 🕐 {extracted}" if extracted else "")
            + "\n━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        # Trim if too long
        if len(msg) > self.max_len - 100:
            msg = msg[: self.max_len - 103] + "..."

        return msg

    def format_daily_digest(self, jobs: List[Dict[str, Any]]) -> str:
        """
        Format a compact daily digest message listing multiple jobs.

        Used for the scheduled 9 AM daily summary.
        """
        if not jobs:
            return "📭 No new walk-in jobs found today. Check back tomorrow!"

        lines = [
            f"🔥 <b>DAILY WALK-IN JOBS DIGEST</b>\n"
            f"📅 {time.strftime('%d %B %Y')} | {len(jobs)} new jobs\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        ]

        for i, job in enumerate(jobs[:20], 1):   # Max 20 in digest
            is_walkin = "🚶" if job.get("is_walkin") else "💼"
            is_fresher = " 🌱" if job.get("is_fresher_friendly") else ""
            title = job.get("title", "Job Opening")[:50]
            company = job.get("company", "")[:30]
            location = job.get("location", "")[:20]
            url = job.get("job_url", "#")

            lines.append(
                f"{i}. {is_walkin}{is_fresher} <a href='{url}'><b>{title}</b></a>\n"
                f"   🏢 {company} | 📍 {location}\n"
            )

        if len(jobs) > 20:
            lines.append(f"\n... and {len(jobs) - 20} more jobs. Visit our website!")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Sending  (synchronous wrappers over async)
    # -------------------------------------------------------------------------
    def send_job(self, job: Dict[str, Any]) -> bool:
        """
        Send a single job to the configured Telegram channel.

        Returns True on success, False on failure.
        """
        if not self.is_configured:
            logger.warning("Telegram not configured — skipping send_job")
            return False

        message = self.format_job_message(job)
        return self._send_message(self.channel_id, message)

    def send_batch_jobs(
        self, jobs: List[Dict[str, Any]], delay_seconds: float = 1.5
    ) -> Dict[str, int]:
        """
        Send multiple jobs to Telegram with a delay between each.

        Args:
            jobs: List of job dicts to send.
            delay_seconds: Delay between messages (respects Telegram rate limits).

        Returns:
            {"sent": int, "failed": int}
        """
        sent = 0
        failed = 0

        for job in jobs:
            success = self.send_job(job)
            if success:
                sent += 1
                # Mark as posted in DB
                if job.get("id"):
                    from services.database_service import JobRepository
                    JobRepository().mark_as_posted_to_telegram(job["id"])
            else:
                failed += 1
            time.sleep(delay_seconds)

        logger.info("Batch send complete: %d sent, %d failed", sent, failed)
        return {"sent": sent, "failed": failed}

    def send_daily_digest(self, jobs: List[Dict[str, Any]]) -> bool:
        """Send the daily digest message to the Telegram channel."""
        if not self.is_configured:
            return False
        message = self.format_daily_digest(jobs)
        return self._send_message(self.channel_id, message)

    def send_admin_alert(self, message: str) -> bool:
        """Send an alert message to the admin chat."""
        if not self.admin_chat_id or not self.token:
            return False
        return self._send_message(self.admin_chat_id, f"⚠️ <b>Admin Alert</b>\n\n{message}")

    # -------------------------------------------------------------------------
    # Low-level HTTP send
    # -------------------------------------------------------------------------
    def _send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> bool:
        """
        Send a message to Telegram via the Bot API.

        Uses the requests library directly (simpler than async bot for scheduled tasks).
        """
        import requests

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }

        try:
            response = requests.post(url, json=payload, timeout=15)
            data = response.json()
            if data.get("ok"):
                logger.debug("Telegram message sent to %s", chat_id)
                return True
            else:
                logger.error(
                    "Telegram API error: %s (description: %s)",
                    data.get("error_code"),
                    data.get("description"),
                )
                return False
        except Exception as exc:
            logger.error("Failed to send Telegram message: %s", exc, exc_info=True)
            return False
