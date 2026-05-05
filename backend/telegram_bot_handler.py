"""
telegram_bot_handler.py — Interactive Telegram bot with slash commands.

Commands:
  /start     — Subscribe to job notifications
  /stop      — Unsubscribe from notifications
  /jobs      — Get 5 recent jobs
  /walkin    — Get walk-in jobs only
  /fresher   — Get fresher-friendly jobs
  /filter    — Filter by location
  /stats     — System statistics

Run this script separately to start the bot's polling loop:
  python telegram_bot_handler.py

Or run it via the APScheduler by calling start_bot() in a thread.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

# Ensure backend/ is on the path when running directly
sys.path.insert(0, os.path.dirname(__file__))

logger = logging.getLogger(__name__)


def start_bot(app=None):
    """
    Start the Telegram bot in polling mode.

    If app is provided (Flask app), runs inside app context.
    Otherwise, creates a standalone context.
    """
    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError:
        logger.error(
            "python-telegram-bot not installed. Run: pip install python-telegram-bot"
        )
        return

    from config import Config

    if not Config.telegram.BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot will not start")
        return

    # -------------------------------------------------------------------------
    # Command handlers
    # -------------------------------------------------------------------------
    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Subscribe user and send welcome message."""
        user = update.effective_user
        _register_user(user)
        await update.message.reply_html(
            f"👋 Welcome, <b>{user.first_name}</b>!\n\n"
            "✅ You're now subscribed to <b>Walk-in Jobs India</b> updates.\n\n"
            "Available commands:\n"
            "🔹 /jobs — Recent job listings\n"
            "🔹 /walkin — Walk-in interviews only\n"
            "🔹 /fresher — Fresher-friendly jobs\n"
            "🔹 /filter — Filter by location\n"
            "🔹 /stats — System statistics\n"
            "🔹 /stop — Unsubscribe\n\n"
            "📢 We post new jobs automatically. Stay tuned!"
        )

    async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unsubscribe user."""
        user_id = update.effective_user.id
        _unsubscribe_user(user_id)
        await update.message.reply_text(
            "😔 You've been unsubscribed from job notifications.\n"
            "Type /start anytime to re-subscribe."
        )

    async def cmd_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send 5 recent jobs."""
        jobs = _get_recent_jobs(limit=5)
        if not jobs:
            await update.message.reply_text("📭 No recent jobs found. Try again later!")
            return

        from services.telegram_service import TelegramService
        svc = TelegramService()
        await update.message.reply_text(f"📋 Found {len(jobs)} recent jobs:")
        for job in jobs:
            msg = svc.format_job_message(job)
            await update.message.reply_html(msg, disable_web_page_preview=True)

    async def cmd_walkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send walk-in jobs."""
        jobs = _get_walkin_jobs(limit=5)
        if not jobs:
            await update.message.reply_text("📭 No walk-in jobs found right now!")
            return

        from services.telegram_service import TelegramService
        svc = TelegramService()
        await update.message.reply_text(f"🚶 Found {len(jobs)} walk-in opportunities:")
        for job in jobs:
            msg = svc.format_job_message(job)
            await update.message.reply_html(msg, disable_web_page_preview=True)

    async def cmd_fresher(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send fresher-friendly jobs."""
        jobs = _get_fresher_jobs(limit=5)
        if not jobs:
            await update.message.reply_text("📭 No fresher jobs found right now!")
            return

        from services.telegram_service import TelegramService
        svc = TelegramService()
        await update.message.reply_text(f"🌱 Found {len(jobs)} fresher-friendly jobs:")
        for job in jobs:
            msg = svc.format_job_message(job)
            await update.message.reply_html(msg, disable_web_page_preview=True)

    async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Filter jobs by location: /filter Mumbai"""
        if not context.args:
            await update.message.reply_text(
                "📍 Usage: /filter <city>\n"
                "Example: /filter Mumbai\n\n"
                "Popular cities: Delhi, Mumbai, Bangalore, Chennai, Hyderabad, Pune"
            )
            return

        location = " ".join(context.args)
        jobs = _get_walkin_jobs(location=location, limit=5)

        if not jobs:
            await update.message.reply_text(
                f"📭 No walk-in jobs found in <b>{location}</b>.\n"
                "Try a different city or use /jobs for all locations.",
                parse_mode="HTML",
            )
            return

        from services.telegram_service import TelegramService
        svc = TelegramService()
        await update.message.reply_text(
            f"📍 Walk-in jobs in <b>{location}</b>: {len(jobs)} found",
            parse_mode="HTML",
        )
        for job in jobs:
            msg = svc.format_job_message(job)
            await update.message.reply_html(msg, disable_web_page_preview=True)

    async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show system statistics."""
        stats = _get_stats()
        msg = (
            "📊 <b>System Statistics</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Total Jobs: <b>{stats.get('total_jobs', 0):,}</b>\n"
            f"🚶 Walk-in Jobs: <b>{stats.get('total_walkin_jobs', 0):,}</b>\n"
            f"🌱 Fresher Jobs: <b>{stats.get('total_fresher_jobs', 0):,}</b>\n"
            f"📅 This Week: <b>{stats.get('jobs_this_week', 0):,}</b>\n"
            f"📆 This Month: <b>{stats.get('jobs_this_month', 0):,}</b>\n"
            f"📤 Pending Posts: <b>{stats.get('unposted_jobs', 0)}</b>\n"
        )

        sources = stats.get("sources", {})
        if sources:
            msg += "\n📡 <b>Sources</b>\n"
            for src, count in sources.items():
                msg += f"  • {src.capitalize()}: {count:,}\n"

        last_scrape = stats.get("last_scrape_time")
        if last_scrape:
            msg += f"\n🕐 Last scrape: {last_scrape[:10]}"

        await update.message.reply_html(msg)

    async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "❓ Unknown command. Type /start to see available commands."
        )

    # -------------------------------------------------------------------------
    # Build and run the Application
    # -------------------------------------------------------------------------
    application = (
        Application.builder()
        .token(Config.telegram.BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("jobs", cmd_jobs))
    application.add_handler(CommandHandler("walkin", cmd_walkin))
    application.add_handler(CommandHandler("fresher", cmd_fresher))
    application.add_handler(CommandHandler("filter", cmd_filter))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(
        MessageHandler(filters.COMMAND, unknown_command)
    )

    logger.info("Starting Telegram bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


# =============================================================================
# DB helper functions (wrapped to work with/without Flask app context)
# =============================================================================
def _with_app_context(func):
    """Decorator to run DB queries inside Flask app context."""
    def wrapper(*args, **kwargs):
        try:
            from flask import current_app
            with current_app.app_context():
                return func(*args, **kwargs)
        except RuntimeError:
            # No app context — run directly
            return func(*args, **kwargs)
    return wrapper


def _register_user(user):
    try:
        from services.database_service import TelegramUserRepository
        TelegramUserRepository().add_or_update_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
    except Exception as exc:
        logger.error("Failed to register telegram user: %s", exc)


def _unsubscribe_user(user_id: int):
    try:
        from services.database_service import TelegramUserRepository
        TelegramUserRepository().unsubscribe_user(user_id)
    except Exception as exc:
        logger.error("Failed to unsubscribe user %d: %s", user_id, exc)


def _get_recent_jobs(limit: int = 5):
    try:
        from services.database_service import JobRepository
        return JobRepository().get_recent_jobs(days=7, limit=limit)
    except Exception as exc:
        logger.error("Failed to get recent jobs: %s", exc)
        return []


def _get_walkin_jobs(location: str = "", limit: int = 5):
    try:
        from services.database_service import JobRepository
        return JobRepository().get_walkin_jobs(location=location, limit=limit)
    except Exception as exc:
        logger.error("Failed to get walk-in jobs: %s", exc)
        return []


def _get_fresher_jobs(limit: int = 5):
    try:
        from services.database_service import JobRepository
        result = JobRepository().get_jobs_by_filter(
            fresher_friendly=True, page=1, limit=limit
        )
        return result.get("jobs", [])
    except Exception as exc:
        logger.error("Failed to get fresher jobs: %s", exc)
        return []


def _get_stats():
    try:
        from services.database_service import JobRepository
        return JobRepository().get_stats()
    except Exception as exc:
        logger.error("Failed to get stats: %s", exc)
        return {}


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    start_bot()
