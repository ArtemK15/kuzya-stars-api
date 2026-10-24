import os
import json
import hmac
import hashlib
import time
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")
ANALYTICS_DB = os.getenv("ANALYTICS_DB", "analytics.db")
app = FastAPI(title="KUZYA STARS SHOP API")

# Разрешаем запросы с нашего сайта Mini App.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://artemk15.github.io",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

PACKAGES = [
    {"stars": 50, "price_rub": 75},
    {"stars": 100, "price_rub": 147},
    {"stars": 150, "price_rub": 221},
    {"stars": 250, "price_rub": 370},
    {"stars": 500, "price_rub": 735},
    {"stars": 1000, "price_rub": 1423},
    {"stars": 1500, "price_rub": 2144},
    {"stars": 2000, "price_rub": 2830},
]


def verify_telegram_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="BOT_TOKEN не настроен на сервере",
        )

    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="Нет данных Telegram Mini App",
        )

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)

        if not received_hash:
            raise ValueError("Нет hash")

        auth_date = int(parsed.get("auth_date", "0"))
        now = int(time.time())

        if (
            auth_date <= 0
            or now - auth_date > 3600
            or auth_date > now + 30
        ):
            raise ValueError("Данные устарели")

        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(parsed.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            raise ValueError("Неверная подпись")

        user_json = parsed.get("user")
        if not user_json:
            raise ValueError("Нет пользователя Telegram")

        user = json.loads(user_json)

        if not isinstance(user.get("id"), int):
            raise ValueError("Нет ID пользователя")

        return user

    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=401,
            detail="Данные Telegram недействительны",
        )


@app.get("/")
async def root():
    return {
        "shop": "KUZYA STARS SHOP",
        "status": "API работает",
    }


@app.get("/api/catalog")
async def catalog():
    return {"packages": PACKAGES}


@app.get("/api/me")
async def current_user(
    x_telegram_init_data: str = Header(default=""),
):
    user = verify_telegram_init_data(x_telegram_init_data)

    return {
        "ok": True,
        "telegram_id": user["id"],
        "first_name": user.get("first_name", ""),
    }


def analytics_connection():
    conn = sqlite3.connect(ANALYTICS_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_analytics_db():
    with analytics_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics_visits (
                session_id TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                opened_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics_presence (
                telegram_id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                last_seen REAL NOT NULL
            )
        """)
        conn.commit()


init_analytics_db()


def require_admin(init_data: str) -> dict:
    user = verify_telegram_init_data(init_data)
    if not ADMIN_ID or str(user.get("id")) != str(ADMIN_ID):
        raise HTTPException(status_code=403, detail="Нет доступа к аналитике")
    return user


@app.post("/api/analytics/heartbeat")
async def analytics_heartbeat(payload: dict):
    user = verify_telegram_init_data(str(payload.get("initData", "")))
    session_id = str(payload.get("sessionId", "")).strip()
    if not session_id or len(session_id) > 100:
        raise HTTPException(status_code=400, detail="Некорректная сессия")
    now = time.time()
    opened_at = datetime.now(timezone.utc).isoformat()
    with analytics_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO analytics_visits(session_id, telegram_id, opened_at) VALUES (?, ?, ?)",
            (session_id, user["id"], opened_at),
        )
        conn.execute(
            "INSERT INTO analytics_presence(telegram_id, session_id, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET session_id=excluded.session_id, last_seen=excluded.last_seen",
            (user["id"], session_id, now),
        )
        conn.commit()
    return {"ok": True, "active_window_seconds": 60}


@app.post("/api/admin/analytics")
async def admin_analytics(payload: dict):
    require_admin(str(payload.get("initData", "")))
    now = time.time()
    today = datetime.now(timezone.utc).date().isoformat()
    with analytics_connection() as conn:
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM analytics_presence WHERE last_seen >= ?", (now - 60,)
        ).fetchone()["n"]
        visits = conn.execute("SELECT COUNT(*) AS n FROM analytics_visits").fetchone()["n"]
        unique_visitors = conn.execute(
            "SELECT COUNT(DISTINCT telegram_id) AS n FROM analytics_visits"
        ).fetchone()["n"]
        today_visits = conn.execute(
            "SELECT COUNT(*) AS n FROM analytics_visits WHERE substr(opened_at, 1, 10) = ?",
            (today,),
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT substr(opened_at,1,10) AS day, COUNT(*) AS visits, "
            "COUNT(DISTINCT telegram_id) AS visitors FROM analytics_visits "
            "GROUP BY substr(opened_at,1,10) ORDER BY day DESC LIMIT 7"
        ).fetchall()
    return {
        "active_now": active,
        "total_visits": visits,
        "unique_visitors": unique_visitors,
        "today_visits": today_visits,
        "daily": [dict(row) for row in reversed(rows)],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

