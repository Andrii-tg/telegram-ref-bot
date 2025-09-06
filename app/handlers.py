import os
import random
import aiosqlite

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from utils import create_payment, validate_address, need_memo

router = Router()

# --- Константы/настройки ---
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ID админа
PRICE_USDT = 1.00  # цена доступа

WITHDRAW_NETWORKS = [
    ("USDT • TRC20", "usdt_trc20"),
    ("USDT • ERC20", "usdt_erc20"),
    ("TON", "ton"),
]

# --- FSM для вывода ---
class WithdrawState(StatesGroup):
    choose_network = State()
    enter_address = State()
    enter_memo = State()
    confirm = State()


# ===================== ВХОД И ОПЛАТА =====================
@router.message(Command("start"))
async def start_handler(message: Message):
    user_id = message.from_user.id
    referrer_id = None

    if message.text and " " in message.text:
        try:
            referrer_id = int(message.text.split()[1])
            if referrer_id == user_id:
                referrer_id = None
        except ValueError:
            pass

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT paid FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()

        if not row:
            await db.execute(
                "INSERT INTO users (user_id, referrer_id) VALUES (?, ?)",
                (user_id, referrer_id)
            )
            await db.commit()
            row = (0,)

    if not row[0]:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Продолжить", callback_data="continue")]
        ])
        await message.answer("👋 Добро пожаловать!\nНажмите «Продолжить», чтобы начать.", reply_markup=kb)
    else:
        await show_main_menu(message)


@router.callback_query(F.data == "continue")
async def continue_handler(callback: CallbackQuery):
    await callback.message.answer("✅ Отлично, теперь переходим к оплате!")
    await show_payment_step(callback.message)


async def show_payment_step(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💸 Оплатить {PRICE_USDT:.2f} USDT", callback_data="pay")]
    ])
    await message.answer("💳 Чтобы получить доступ, подтвердите оплату:", reply_markup=kb)


@router.callback_query(F.data == "pay")
async def pay_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    amount = PRICE_USDT
    order_id = f"{user_id}_{random.randint(1000, 9999)}"

    payment = await create_payment(amount, order_id)

    if payment.get("status") == "success":
        pay_url = payment["result"].get("link")
        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                "INSERT INTO payments (order_id, user_id, status) VALUES (?, ?, ?)",
                (order_id, user_id, "pending")
            )
            await db.commit()

        await callback.message.answer(f"✅ Оплата создана на {amount} USDT:\n{pay_url}")
    else:
        await callback.message.answer("❌ Ошибка при создании оплаты.")


# ===================== Webhook от CryptoCloud =====================
async def process_payment_webhook(order_id: str, amount: float):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT user_id FROM payments WHERE order_id = ?", (order_id,))
        row = await cursor.fetchone()
        if not row:
            return
        user_id = row[0]

        await db.execute("UPDATE payments SET status = 'paid' WHERE order_id = ?", (order_id,))
        await db.execute("UPDATE users SET paid = 1 WHERE user_id = ?", (user_id,))

        cursor = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        referrer_id = row[0] if row else None

        if referrer_id:
            bonus = amount * 0.5
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, referrer_id))
        await db.commit()


# ===================== МЕНЮ =====================
async def show_main_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="🔗 Реф. ссылка", callback_data="ref_link")],
        [InlineKeyboardButton(text="💸 Вывод средств", callback_data="withdraw")],
        [InlineKeyboardButton(text="📖 Гайд", url="https://telegra.ph/your-guide-post")]
    ])
    await message.answer("🎉 Добро пожаловать! Вот ваше меню:", reply_markup=kb)


@router.callback_query(F.data == "balance")
async def balance_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        balance = row[0] if row else 0.0
    await callback.message.answer(f"💰 Ваш баланс: {balance:.2f} USDT")


@router.callback_query(F.data == "ref_link")
async def ref_link_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT paid FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()

    if not row or row[0] == 0:
        await callback.message.answer("❌ Реферальная ссылка доступна только после оплаты.")
        return

    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username
    await callback.message.answer(f"🔗 Ваша реферальная ссылка:\nhttps://t.me/{bot_username}?start={user_id}")


# ===================== ВЫВОД =====================
@router.callback_query(F.data == "withdraw")
async def withdraw_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        balance = row[0] if row else 0.0

    if balance <= 0:
        await callback.message.answer("😕 На вашем балансе нет средств для вывода.")
        return

    buttons = [[InlineKeyboardButton(text=title, callback_data=f"wd_net:{code}")]
               for title, code in WITHDRAW_NETWORKS]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons + [[InlineKeyboardButton(text="↩️ Отмена", callback_data="wd_cancel")]])
    await state.set_state(WithdrawState.choose_network)
    await callback.message.answer("💸 Вывод средств.\nВыберите сеть:", reply_markup=kb)


@router.callback_query(F.data == "wd_cancel")
async def wd_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Вывод отменён.")


@router.callback_query(F.data.startswith("wd_net:"))
async def wd_choose_network(callback: CallbackQuery, state: FSMContext):
    network = callback.data.split(":", 1)[1]
    await state.update_data(network=network)
    await state.set_state(WithdrawState.enter_address)
    await callback.message.answer("✍️ Укажите адрес для вывода.")


@router.message(WithdrawState.enter_address)
async def wd_enter_address(message: Message, state: FSMContext):
    data = await state.get_data()
    network = data.get("network")
    address = message.text.strip()

    if not validate_address(network, address):
        await message.answer("⚠️ Неверный адрес для этой сети.")
        return

    await state.update_data(address=address)

    if need_memo(network):
        await state.set_state(WithdrawState.enter_memo)
        await message.answer("ℹ️ Укажите MEMO/Tag (или «-», если не нужно).")
    else:
        await state.update_data(memo="")
        await wd_confirm(message, state)


@router.message(WithdrawState.enter_memo)
async def wd_enter_memo(message: Message, state: FSMContext):
    memo = message.text.strip()
    if memo == "-":
        memo = ""
    await state.update_data(memo=memo)
    await wd_confirm(message, state)


async def wd_confirm(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    network = data["network"]
    address = data["address"]
    memo = data.get("memo", "")

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        balance = row[0] if row else 0.0

    if balance <= 0:
        await state.clear()
        await message.answer("😕 Баланс пуст.")
        return

    text = (
        "🔁 Подтвердите вывод:\n"
        f"• Сеть: {network.upper()}\n"
        f"• Адрес: {address}\n"
        + (f"• MEMO: {memo}\n" if memo else "")
        + f"• Сумма: {balance:.2f} USDT"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="wd_ok")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data="wd_cancel")]
    ])
    await state.set_state(WithdrawState.confirm)
    await state.update_data(amount=balance)
    await message.answer(text, reply_markup=kb)


@router.callback_query(WithdrawState.confirm, F.data == "wd_ok")
async def wd_create(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    network = data["network"]
    address = data["address"]
    memo = data.get("memo", "")
    amount = data["amount"]

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        current_balance = row[0] if row else 0.0

        if current_balance < amount - 1e-9:
            await state.clear()
            await callback.message.answer("⚠️ Баланс изменился. Попробуйте снова.")
            return

        await db.execute("""
            INSERT INTO withdrawals (user_id, amount, network, address, memo, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (user_id, amount, network, address, memo))

        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

    await state.clear()
    await callback.message.answer("✅ Заявка на вывод создана. Статус: pending.")

    if ADMIN_ID:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Approve", callback_data=f"admin_approve:{user_id}")],
            [InlineKeyboardButton(text="❌ Reject", callback_data=f"admin_reject:{user_id}")]
        ])
        try:
            await callback.bot.send_message(
                ADMIN_ID,
                f"🧾 Новая заявка:\nUser: {user_id}\nAmount: {amount:.2f}\nNetwork: {network}\nAddress: {address}\n{('Memo: '+memo if memo else '')}",
                reply_markup=kb
            )
        except Exception as e:
            print(f"Ошибка уведомления админа: {e}")


# ===================== Админ =====================
@router.message(Command("withdrawals"))
async def admin_withdrawals(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT id, user_id, amount, network, address, status FROM withdrawals WHERE status = 'pending'")
        rows = await cursor.fetchall()
    if not rows:
        await message.answer("❌ Нет заявок на вывод.")
        return
    text = "📋 Заявки:\n"
    for r in rows:
        text += f"#{r[0]} | User {r[1]} | {r[2]} USDT | {r[3]} | {r[4]} | {r[5]}\n"
    await message.answer(text)


@router.callback_query(F.data.startswith("admin_approve:"))
async def admin_approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE withdrawals SET status = 'approved' WHERE user_id = ? AND status = 'pending'", (user_id,))
        await db.commit()
    await callback.message.answer(f"✅ Вывод для {user_id} одобрен.")
    try:
        await callback.bot.send_message(user_id, "✅ Ваш вывод был успешно обработан.")
    except:
        pass


@router.callback_query(F.data.startswith("admin_reject:"))
async def admin_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split(":")[1])
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT amount FROM withdrawals WHERE user_id = ? AND status = 'pending'", (user_id,))
        row = await cursor.fetchone()
        if row:
            amount = row[0]
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.execute("UPDATE withdrawals SET status = 'rejected' WHERE user_id = ? AND status = 'pending'", (user_id,))
        await db.commit()
    await callback.message.answer(f"❌ Вывод для {user_id} отклонён.")
    try:
        await callback.bot.send_message(user_id, "❌ Ваш вывод был отклонён, средства возвращены на баланс.")
    except:
        pass
