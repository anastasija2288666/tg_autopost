import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None
DB_PATH = "autopost.db"

router = Router()

class PostStates(StatesGroup):
    choosing_channel = State()
    waiting_content = State()
    waiting_button = State()
    waiting_time = State()

class ChannelStates(StatesGroup):
    waiting_channel = State()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

def green_btn(text: str, callback_data: str = None, url: str = None) -> InlineKeyboardButton:
    kwargs = {"text": text, "style": "success"}
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)

def red_btn(text: str, callback_data: str) -> InlineKeyboardButton:
    try:
        return InlineKeyboardButton(text=text, callback_data=callback_data, style="danger")
    except TypeError:
        return InlineKeyboardButton(text=text, callback_data=callback_data)

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [green_btn("➕ Создать пост", callback_data="create_post")],
        [green_btn("📅 Очередь постов", callback_data="queue_posts")],
        [
            green_btn("📢 Мои каналы", callback_data="my_channels"),
            green_btn("🕒 Часовой пояс", callback_data="set_tz"),
        ],
    ])

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE,
                title TEXT,
                username TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                content_type TEXT,
                content_data TEXT,
                btn_text TEXT,
                btn_link TEXT,
                publish_time TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('tz_offset', '8')")
        await db.commit()

async def get_tz_offset() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = 'tz_offset'")
        row = await cur.fetchone()
        return int(row[0]) if row else 8

async def publish_post(bot: Bot, chat_id: int, content_type: str, content_data: str, btn_text: str = None, btn_link: str = None):
    data = json.loads(content_data)
    kb = None
    if btn_text and btn_link:
        kb = InlineKeyboardMarkup(inline_keyboard=[[green_btn(btn_text, url=btn_link)]])

    if content_type == "text":
        await bot.send_message(chat_id=chat_id, text=data["text"], reply_markup=kb)
    elif content_type == "photo":
        await bot.send_photo(chat_id=chat_id, photo=data["file_id"], caption=data.get("caption"), reply_markup=kb)
    elif content_type == "video":
        await bot.send_video(chat_id=chat_id, video=data["file_id"], caption=data.get("caption"), reply_markup=kb)

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ закрыт.")
        return

    await message.answer(
        "👋 <b>Бот отложенного автопостинга готов!</b>\n\nВыберите нужное действие:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

@router.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text(
        "👋 <b>Главное меню автопостинга</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
    await callback.answer()

@router.callback_query(F.data == "my_channels")
async def cb_my_channels(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id, title, username FROM channels")
        rows = await cur.fetchall()

    buttons = []
    text = "📢 <b>Подключённые каналы:</b>\n\n"
    if not rows:
        text += "Пока нет добавленных каналов."
    else:
        for r in rows:
            uname = f" (@{r['username']})" if r["username"] else ""
            text += f"• <b>{r['title']}</b>{uname}\n"
            buttons.append([red_btn(f"🗑 Удалить: {r['title']}", callback_data=f"del_ch_{r['id']}")])

    buttons.append([green_btn("➕ Добавить канал", callback_data="add_channel")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data == "add_channel")
async def cb_add_channel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(ChannelStates.waiting_channel)
    await callback.message.edit_text(
        "📢 <b>Подключение канала</b>\n\n"
        "1. Добавьте бота в администраторы вашего канала (с правом публикации сообщений).\n"
        "2. Отправьте сюда <b>@username</b> канала или просто <b>перешлите любой пост</b> из него.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[red_btn("❌ Отмена", callback_data="my_channels")]])
    )
    await callback.answer()

@router.message(ChannelStates.waiting_channel)
async def process_add_channel(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    target = None
    if message.forward_from_chat and message.forward_from_chat.type == "channel":
        target = message.forward_from_chat.id
    elif message.text:
        target = message.text.strip()

    if not target:
        await message.answer("⚠️ Пришлите @username канала или перешлите пост из него.")
        return

    try:
        chat = await bot.get_chat(target)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)
        if member.status not in ("administrator", "creator"):
            await message.answer("❌ Бот не является администратором этого канала! Выдайте права и попробуйте снова.")
            return
    except Exception as e:
        await message.answer(f"❌ Не удалось подключить канал.\nОшибка: {e}")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO channels (chat_id, title, username) VALUES (?, ?, ?)",
            (chat.id, chat.title or "Канал", chat.username)
        )
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Канал <b>{chat.title}</b> подключён!", parse_mode="HTML", reply_markup=main_menu())

@router.callback_query(F.data.startswith("del_ch_"))
async def cb_del_channel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    ch_id = int(callback.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE id = ?", (ch_id,))
