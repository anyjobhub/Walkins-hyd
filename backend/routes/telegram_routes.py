"""
routes/telegram_routes.py — Telegram subscription management endpoints.
"""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request

from services.database_service import TelegramUserRepository

logger = logging.getLogger(__name__)
telegram_bp = Blueprint("telegram", __name__)
user_repo = TelegramUserRepository()


@telegram_bp.route("/telegram/subscribe", methods=["POST"])
def subscribe():
    """
    Subscribe a user to Telegram job notifications.

    Body (JSON):
      user_id   (int, required)
      username  (str, optional)
      first_name (str, optional)
    """
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({"error": "'user_id' is required"}), 400

    success = user_repo.add_or_update_user(
        user_id=int(user_id),
        username=data.get("username"),
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
    )

    if success:
        return jsonify({"success": True, "message": "Subscribed successfully"}), 200
    return jsonify({"success": False, "message": "Failed to subscribe"}), 500


@telegram_bp.route("/telegram/unsubscribe", methods=["POST"])
def unsubscribe():
    """
    Unsubscribe a user from Telegram notifications.

    Body (JSON):
      user_id (int, required)
    """
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({"error": "'user_id' is required"}), 400

    success = user_repo.unsubscribe_user(int(user_id))
    if success:
        return jsonify({"success": True, "message": "Unsubscribed successfully"}), 200
    return jsonify({"success": False, "message": "User not found"}), 404


@telegram_bp.route("/telegram/subscribers", methods=["GET"])
def get_subscribers():
    """Get subscriber count (public) — no user details exposed."""
    count = user_repo.get_subscriber_count()
    return jsonify({"subscriber_count": count}), 200
