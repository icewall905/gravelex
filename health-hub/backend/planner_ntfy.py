"""Deliver planner reminders through the configured ntfy publisher."""
import json
import logging
import os
import re
import secrets
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

import accounts
import fitness

log = logging.getLogger(__name__)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def server():
    value = os.environ.get("PH_NTFY_URL", "").rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme == "https" and parsed.hostname and not (
        parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
    ):
        return value
    return ""


def settings(state):
    saved = state.get("ntfy", {})
    return {"available": bool(server()), "server": server(), "enabled": saved.get("enabled", False),
            "topic": saved.get("topic", "")}


def configure(body, current):
    if not server():
        raise ValueError("ntfy is not configured on the hub.")
    topic = body.get("topic", "")
    if not isinstance(topic, str) or (topic and not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", topic)):
        raise ValueError("Use a topic of 8–64 letters, digits, underscores or dashes.")
    return {"enabled": body.get("enabled") is True,
            "topic": topic or current.get("topic") or "pebble-" + secrets.token_urlsafe(24)}


def publish(topic, title, message, workout=None):
    base = server()
    if not base or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", topic or ""):
        raise ValueError("ntfy requires a configured server and topic.")
    payload = {"topic":topic, "title":title, "message":message, "tags":["calendar"]}
    public_url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if public_url.startswith("https://"):
        query = "?" + urlencode({"workout":workout}) if workout else ""
        payload["click"] = public_url + "/planner.html" + query
    headers = {"Content-Type":"application/json", "X-Firebase":"no"}
    token = os.environ.get("PH_NTFY_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(base + "/", json.dumps(payload).encode(), headers, method="POST")
    with build_opener(NoRedirect()).open(req, timeout=8) as response:
        if response.status != 200:
            raise OSError("ntfy rejected the notification.")


def deliver(db, state, now):
    from planner import reminders

    ntfy = settings(state)
    if not (ntfy["available"] and ntfy["enabled"]):
        return
    zone = ZoneInfo(state["timezone"])
    today = now.astimezone(zone).date()
    db.execute("""CREATE TABLE IF NOT EXISTS planner_ntfy_deliveries (
        id TEXT NOT NULL, kind TEXT NOT NULL, at INTEGER NOT NULL,
        sent INTEGER NOT NULL DEFAULT 0, lease_until INTEGER NOT NULL,
        PRIMARY KEY(id, kind, at)
    )""")
    current = int(now.timestamp())
    with db:
        db.execute("DELETE FROM planner_ntfy_deliveries WHERE at < ?", (current - 7 * 86400,))
    # Include yesterday's late follow-up when the retry window crosses midnight.
    due = list(reminders(state, today - timedelta(days=1))) + list(reminders(state, today))
    for item, kind, at in due:
        due_at = int(at.timestamp())
        if not 0 <= current - due_at < 3 * 3600:
            continue
        key = (item["id"], kind, due_at)
        with db:
            changed = db.execute("""INSERT INTO planner_ntfy_deliveries(id,kind,at,lease_until)
                VALUES(?,?,?,?) ON CONFLICT(id,kind,at) DO UPDATE SET lease_until=excluded.lease_until
                WHERE sent=0 AND lease_until<=?""", (*key, current + 120, current)).rowcount
        if not changed:
            continue
        try:
            title = "You have a workout today" if kind == "morning" else "How did training go?"
            publish(ntfy["topic"], title, "Open Pebble Health to view your workout and message Trainer.", item["id"])
        except (OSError, ValueError) as error:
            log.warning("ntfy reminder delivery failed: %s", type(error).__name__)
            continue
        with db:
            db.execute("UPDATE planner_ntfy_deliveries SET sent=1 WHERE id=? AND kind=? AND at=?", key)


def tick():
    if not server():
        return
    from planner import read

    now = datetime.now(UTC)
    for user in accounts.users():
        if not user["active"]:
            continue
        try:
            with accounts.as_user(user), closing(fitness.connect()) as db:
                deliver(db, read(db), now)
        except Exception:
            log.exception("Planner ntfy check failed for an account.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            tick()
        except Exception:
            log.exception("Planner ntfy check failed.")
        time.sleep(45)
