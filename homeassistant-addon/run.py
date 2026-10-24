#!/usr/bin/env python3
"""Supervisor add-on entrypoint with persistent, quiet bootstrap secrets."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import time
import socket
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

DATA = Path("/data")


def password_hash(password):
    salt = secrets.token_hex(8)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=32768, r=8, p=1, maxmem=132 * 1024 * 1024).hex()
    return f"scrypt:32768:8:1${salt}${digest}"


def persistent(name, length=48):
    path = DATA / name
    if path.exists():
        return path.read_text().strip()
    value = secrets.token_urlsafe(length)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value + "\n")
    return value


def options():
    try:
        return json.loads((DATA / "options.json").read_text())
    except FileNotFoundError:
        return {}


def main():
    opts = options()
    username = opts.get("admin_username", "admin")
    if not isinstance(username, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,39}", username):
        raise SystemExit("admin_username must be 3-40 lowercase letters, numbers, dots, underscores or hyphens")
    initial = opts.get("initial_password", "")
    if initial and (not isinstance(initial, str) or not 12 <= len(initial) <= 1024):
        raise SystemExit("initial_password must be 12-1024 characters")
    DATA.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    hash_path=DATA/'bootstrap-password-hash'
    if not (DATA/'household.sqlite3').exists() and not hash_path.exists():
        if not initial:
            raise SystemExit('Set initial_password (at least 12 characters) in add-on Configuration before first start')
        fd=os.open(hash_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream: stream.write(password_hash(initial)+'\n')
    env['PH_ADMIN_USERNAME']=username
    if hash_path.exists(): env['PH_PASSWORD_HASH']=hash_path.read_text().strip()
    timezone = opts.get("timezone", "UTC")
    ZoneInfo(timezone)
    public_url=opts.get('public_url','').rstrip('/')
    if public_url:
        parsed=urlsplit(public_url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise SystemExit('public_url must be a base HTTP(S) URL without credentials or query parameters')
    configured_hosts=opts.get('allowed_hosts','homeassistant.local,localhost,127.0.0.1')
    hosts={part.strip().lower() for part in configured_hosts.split(',') if part.strip()}
    hosts.update(('localhost','127.0.0.1',socket.gethostname().lower()))
    if public_url: hosts.add(urlsplit(public_url).hostname.lower())
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,252}',host) for host in hosts):
        raise SystemExit('allowed_hosts must contain hostnames or IPv4 addresses, without ports or schemes')
    env.update({"FITNESS_DB": str(DATA/"fitness.sqlite3"), "WEB_DIR": "/app/web", "DOWNLOAD_DIR": str(DATA/"downloads"),
                "AUTH_TOKEN": persistent("service-token"), "PH_SESSION_SECRET": persistent("session-secret"),
                "PEBBLE_TZ": timezone, "PUBLIC_URL": public_url,
                "WEARER_NAME": opts.get("wearer_name", ""), "ALLOWED_HOSTS": ",".join(sorted(hosts))})
    (DATA / "downloads").mkdir(parents=True, exist_ok=True)
    env.update({'LLM_BASE_URL':opts.get('llm_base_url',''),'LLM_MODEL':opts.get('llm_model',''),
                'LLM_API_KEY':opts.get('llm_api_key',''),'MQTT_ENABLED':'false',
                'HA_WS_URL':'','HA_TOKEN':'','HA_REPORT_SERVICE':''})
    subprocess.run(['python','-c','import accounts; assert accounts.initialize()'],env=env,check=True)
    children = [subprocess.Popen(["gunicorn", "-w", "2", "-b", "0.0.0.0:8790", "--access-logfile", "-", "dashboard:app"], env=env),
                subprocess.Popen(["gunicorn", "-w", "1", "-b", "0.0.0.0:9998", "--access-logfile", "-", "app:app"], env=env)]
    if opts.get("enable_briefing"):
        env.update({"LLM_BASE_URL": opts.get("llm_base_url", ""), "LLM_MODEL": opts.get("llm_model", ""), "LLM_API_KEY": opts.get("llm_api_key", "")})
        children.append(subprocess.Popen(["python", "/app/backend/briefing.py", "--daemon"], env=env))
    stopping=False
    def terminate_children():
        for child in children:
            if child.poll() is None: child.terminate()
    def stop(*_):
        nonlocal stopping
        stopping=True
        terminate_children()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        for child in children:
            if child.poll() is not None:
                terminate_children()
                for process in children:
                    try: process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                return 0 if stopping else (child.returncode or 1)
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
