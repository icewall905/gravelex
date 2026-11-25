"""Private Trainer settings, persistent notes, and account-local vector retrieval."""
import json
import math
import os
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen


def defaults():
    endpoint = os.environ.get("PH_TRAINER_ROUTER_BASE", "https://ai.tdgs.org/v1").rstrip("/")
    return {"base_url": endpoint, "model": os.environ.get("PH_TRAINER_MODEL", "currentmodel"),
            "web_search": False}


def allowed_endpoints():
    configured = os.environ.get("PH_TRAINER_ALLOWED_BASES", "")
    return sorted({defaults()["base_url"], *(value.strip().rstrip("/") for value in configured.split(",") if value.strip())})


def model_settings(body):
    endpoint = body.get("base_url")
    model = body.get("model")
    if not isinstance(endpoint, str) or endpoint.rstrip("/") not in allowed_endpoints():
        raise ValueError("Select one of the configured Trainer endpoint URLs.")
    if not isinstance(model, str) or not re.fullmatch(r"[\w./:@ -]{1,120}", model) or not model.strip():
        raise ValueError("Enter a model identifier.")
    return {"base_url":endpoint.rstrip("/"), "model":model.strip(),
            "web_search":body.get("web_search") is True}


def vectors(text):
    words = re.findall(r"[^\W_]{3,}", text.casefold())
    counts = Counter(words + [a + " " + b for a, b in zip(words, words[1:])])
    norm = math.sqrt(sum(count ** 2 for count in counts.values())) or 1
    return {term:round(count / norm, 5) for term, count in counts.items()}


def archive(db, previous):
    db.execute("""CREATE TABLE IF NOT EXISTS planner_conversation (
        id INTEGER PRIMARY KEY, at TEXT, role TEXT NOT NULL, text TEXT NOT NULL, vector TEXT NOT NULL
    )""")
    if previous and not db.execute("SELECT 1 FROM planner_conversation LIMIT 1").fetchone():
        append(db, previous, None)


def append(db, messages, at):
    db.executemany("INSERT INTO planner_conversation(at,role,text,vector) VALUES(?,?,?,?)", [
        (at, item["role"], item["text"], json.dumps(vectors(item["text"]))) for item in messages
    ])


def recall(db, query):
    target = vectors(query)
    rows = list(db.execute("SELECT * FROM planner_conversation ORDER BY id DESC LIMIT 40"))
    oldest = rows[-1]["id"] if rows else 1
    recent = []
    now = datetime.now(UTC)
    for row in reversed(rows):
        current = bool(row["at"] and datetime.fromisoformat(row["at"]) >= now - timedelta(hours=1))
        recent.append({"role":row["role"], "text":row["text"][:600 if current else 260], "at":row["at"], "current":current})
    matches = []
    for row in db.execute("SELECT * FROM planner_conversation WHERE id < ?", (oldest,)):
        stored = json.loads(row["vector"])
        score = sum(weight * stored.get(term, 0) for term, weight in target.items())
        if score > 0.15:
            matches.append((score, row["id"], {"role":row["role"], "text":row["text"][:600], "at":row["at"]}))
    return {"last_40_messages":recent, "relevant_older_messages":[entry[2] for entry in sorted(matches, reverse=True)[:6]]}


def search(query):
    base = os.environ.get("PH_TRAINER_SEARCH_URL", "").rstrip("/")
    if not base or not query:
        return []
    with urlopen(base + "/search?" + urlencode({"q":query, "format":"json", "engines":"brave,duckduckgo,wikipedia"}), timeout=6) as response:
        data = json.loads(response.read(350_000))
    return [
        {"title":item.get("title", "")[:200], "url":item["url"], "excerpt":item.get("content", "")[:500]}
        for item in data.get("results", [])[:6] if urlsplit(item.get("url", "")).scheme in ("https", "http")
    ]
