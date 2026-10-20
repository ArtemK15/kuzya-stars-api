import os
import json
import hmac
import hashlib
import time
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

app = FastAPI(title="KUZYA STARS SHOP API")

# Разрешаем запросы с нашего сайта Mini App.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://artemk15.github.io",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
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
