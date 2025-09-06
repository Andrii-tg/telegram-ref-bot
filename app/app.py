import os
import asyncio
import aiosqlite
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update
import uvicorn

from database import init_db
from handlers import router

# --- Настройки ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
WEBHOOK_PATH = "/webhook/telegram"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", f"https://your-app.onrender.com{WEBHOOK_PATH}")

# --- Создаём объекты ---
app = FastAPI()
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
dp.include_router(router)


# --- Telegram Webhook ---
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return {"status": "ok"}


# --- CryptoCloud Webhook ---
@app.post("/webhook/cryptocloud")
async def cryptocloud_webhook(request: Request):
    data = await request.json()
    order_id = data.get("order_id")
    status = data.get("status")

    if order_id and status == "success":
        async with aiosqlite.connect("bot.db") as db:
            await db.execute("UPDATE payments SET status = 'paid' WHERE order_id = ?", (order_id,))
            cursor = await db.execute("SELECT user_id FROM payments WHERE order_id = ?", (order_id,))
            row = await cursor.fetchone()
            if row:
                user_id = row[0]
                await db.execute("UPDATE users SET paid = 1 WHERE user_id = ?", (user_id,))
            await db.commit()

    return {"status": "ok"}


# --- Startup & Shutdown ---
@app.on_event("startup")
async def on_startup():
    await init_db()
    await bot.set_webhook(WEBHOOK_URL)
    print("Бот запущен ✅, вебхук установлен:", WEBHOOK_URL)


@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
    print("Вебхук удалён ❌")


# --- Запуск ---
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
