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
        await db.commit()
    await callback.answer("Канал удалён")
    await cb_my_channels(callback)


@router.callback_query(F.data == "set_tz")
async def cb_set_tz(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    offset = await get_tz_offset()
    sign = "+" if offset >= 0 else ""
    buttons = [
        [
            green_btn("Москва (UTC+3)", callback_data="tz_3"),
            green_btn("Екатеринбург (UTC+5)", callback_data="tz_5"),
        ],
        [
            green_btn("Новосибирск (UTC+7)", callback_data="tz_7"),
            green_btn("Иркутск (UTC+8)", callback_data="tz_8"),
        ],
        [
            green_btn("Владивосток (UTC+10)", callback_data="tz_10"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")],
    ]
    await callback.message.edit_text(
        f"🕒 <b>Часовой пояс</b>\n\nСейчас выбрано: <b>UTC{sign}{offset}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tz_"))
async def cb_save_tz(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    offset_val = callback.data.split("_")[-1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('tz_offset', ?)", (offset_val,))
        await db.commit()
    await callback.answer(f"Сохранено: UTC+{offset_val}")
    await cb_back_main(callback, state)


@router.callback_query(F.data == "create_post")
async def cb_create_post(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id, title FROM channels")
        rows = await cur.fetchall()

    if not rows:
        await callback.answer("Сначала добавьте хотя бы один канал!", show_alert=True)
        return

    buttons = [[green_btn(f"📢 {r['title']}", callback_data=f"sel_ch_{r['id']}")] for r in rows]
    buttons.append([red_btn("❌ Отмена", callback_data="back_main")])

    await state.set_state(PostStates.choosing_channel)
    await callback.message.edit_text(
        "1️⃣ <b>Шаг 1 из 4:</b> Выберите канал для поста:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(PostStates.choosing_channel, F.data.startswith("sel_ch_"))
async def cb_select_channel(callback: CallbackQuery, state: FSMContext):
    ch_id = int(callback.data.split("_")[-1])
    await state.update_data(channel_id=ch_id)
    await state.set_state(PostStates.waiting_content)
    await callback.message.edit_text(
        "2️⃣ <b>Шаг 2 из 4:</b> Отправьте контент поста.\n\nМожно прислать <b>текст</b>, <b>фото с подписью</b> или <b>видео с подписью</b>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[red_btn("❌ Отмена", callback_data="back_main")]])
    )
    await callback.answer()


@router.message(PostStates.waiting_content)
async def process_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if message.photo:
        content_type = "photo"
        content_data = json.dumps({"file_id": message.photo[-1].file_id, "caption": message.caption or ""})
    elif message.video:
        content_type = "video"
        content_data = json.dumps({"file_id": message.video.file_id, "caption": message.caption or ""})
    elif message.text:
        content_type = "text"
        content_data = json.dumps({"text": message.text})
    else:
        await message.answer("⚠️ Отправьте текст, фото или видео.")
        return

    await state.update_data(content_type=content_type, content_data=content_data)
    await state.set_state(PostStates.waiting_button)
    await message.answer(
        "3️⃣ <b>Шаг 3 из 4:</b> Добавить кнопку-ссылку под постом?\n\n"
        "Напишите: <code>Текст кнопки | https://ссылка</code>\n"
        "Или нажмите <b>«Пропустить»</b>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [green_btn("⏭ Пропустить", callback_data="skip_btn")],
            [red_btn("❌ Отмена", callback_data="back_main")],
        ])
    )


@router.callback_query(PostStates.waiting_button, F.data == "skip_btn")
async def cb_skip_btn(callback: CallbackQuery, state: FSMContext):
    await state.update_data(btn_text=None, btn_link=None)
    await ask_time(callback.message, state, edit=True)
    await callback.answer()


@router.message(PostStates.waiting_button)
async def process_btn(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text or "|" not in message.text:
        await message.answer("⚠️ Формат: <code>Текст кнопки | https://ссылка</code>", parse_mode="HTML")
        return

    parts = message.text.split("|", 1)
    btn_text = parts[0].strip()
    btn_link = parts[1].strip()
    if not btn_link.startswith(("http://", "https://")):
        await message.answer("⚠️ Ссылка должна начинаться с <code>https://</code> или <code>http://</code>.", parse_mode="HTML")
        return

    await state.update_data(btn_text=btn_text, btn_link=btn_link)
    await ask_time(message, state, edit=False)


async def ask_time(msg: Message, state: FSMContext, edit: bool = False):
    offset = await get_tz_offset()
    sign = "+" if offset >= 0 else ""
    example = (datetime.now(timezone(timedelta(hours=offset))) + timedelta(hours=1)).strftime("%d.%m.%Y %H:%M")

    await state.set_state(PostStates.waiting_time)
    text = (
        f"4️⃣ <b>Шаг 4 из 4:</b> Когда выпустить пост?\n\n"
        f"Нажмите <b>«🚀 Опубликовать сейчас»</b> или введите дату и время (<b>UTC{sign}{offset}</b>):\n"
        f"<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\nНапример: <code>{example}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [green_btn("🚀 Опубликовать сейчас", callback_data="pub_now")],
        [red_btn("❌ Отмена", callback_data="back_main")],
    ])
    if edit:
        await msg.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(PostStates.waiting_time, F.data == "pub_now")
async def cb_pub_now(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT chat_id, title FROM channels WHERE id = ?", (data["channel_id"],))
        ch = await cur.fetchone()

    if not ch:
        await callback.answer("Канал не найден!", show_alert=True)
        return

    try:
        await publish_post(bot, ch["chat_id"], data["content_type"], data["content_data"], data.get("btn_text"), data.get("btn_link"))
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка публикации: {e}")
        return

    await state.clear()
    await callback.message.edit_text(f"✅ Пост опубликован в <b>{ch['title']}</b>!", parse_mode="HTML", reply_markup=main_menu())
    await callback.answer()


@router.message(PostStates.waiting_time)
async def process_time(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    offset = await get_tz_offset()
    tz = timezone(timedelta(hours=offset))

    try:
        dt_local = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=tz)
        dt_utc = dt_local.astimezone(timezone.utc)
    except ValueError:
        await message.answer("⚠️ Неверный формат! Пишите так: <code>25.11.2026 18:30</code>", parse_mode="HTML")
        return

    if dt_utc <= datetime.now(timezone.utc):
        await message.answer("⚠️ Это время уже прошло! Укажите будущее время.")
        return

    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO posts (channel_id, content_type, content_data, btn_text, btn_link, publish_time, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                data["channel_id"],
                data["content_type"],
                data["content_data"],
                data.get("btn_text"),
                data.get("btn_link"),
                dt_utc.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        await db.commit()

    await state.clear()
    await message.answer(
        f"⏰ <b>Пост поставлен в очередь!</b>\nВыйдет: <b>{dt_local.strftime('%d.%m.%Y в %H:%M')}</b>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


@router.callback_query(F.data == "queue_posts")
async def cb_queue(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    offset = await get_tz_offset()
    tz_local = timezone(timedelta(hours=offset))

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT p.id, p.content_type, p.publish_time, c.title
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.status = 'pending'
            ORDER BY p.publish_time ASC
        """)
        rows = await cur.fetchall()

    buttons = []
    text = "📅 <b>Очередь запланированных постов:</b>\n\n"
    if not rows:
        text += "Очередь пока пуста."
    else:
        for r in rows:
            dt_utc = datetime.strptime(r["publish_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            dt_loc = dt_utc.astimezone(tz_local).strftime("%d.%m %H:%M")
            text += f"• <b>#{r['id']}</b> в «{r['title']}» ({r['content_type']}) — ⏰ {dt_loc}\n"
            buttons.append([
                green_btn(f"🚀 Выпустить #{r['id']}", callback_data=f"force_{r['id']}"),
                red_btn(f"🗑 Удалить #{r['id']}", callback_data=f"del_p_{r['id']}"),
            ])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("force_"))
async def cb_force(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return
    post_id = int(callback.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT p.*, c.chat_id
            FROM posts p JOIN channels c ON p.channel_id = c.id
            WHERE p.id = ?
        """, (post_id,))
        post = await cur.fetchone()
        if not post:
            await callback.answer("Пост не найден!", show_alert=True)
            return
        await publish_post(bot, post["chat_id"], post["content_type"], post["content_data"], post["btn_text"], post["btn_link"])
        await db.execute("UPDATE posts SET status = 'published' WHERE id = ?", (post_id,))
        await db.commit()

    await callback.answer("✅ Опубликовано!")
    await cb_queue(callback)


@router.callback_query(F.data.startswith("del_p_"))
async def cb_del_p(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    post_id = int(callback.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        await db.commit()
    await callback.answer("🗑 Удалено")
    await cb_queue(callback)


async def scheduler_loop(bot: Bot):
    while True:
        try:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute("""
                    SELECT p.*, c.chat_id, c.title
                    FROM posts p JOIN channels c ON p.channel_id = c.id
                    WHERE p.status = 'pending' AND p.publish_time <= ?
                """, (now_str,))
                due = await cur.fetchall()

                for post in due:
                    try:
                        await publish_post(bot, post["chat_id"], post["content_type"], post["content_data"], post["btn_text"], post["btn_link"])
                        await db.execute("UPDATE posts SET status = 'published' WHERE id = ?", (post["id"],))
                        await db.commit()
                        if ADMIN_ID:
                            await bot.send_message(
                                ADMIN_ID,
                                f"✅ Пост <b>#{post['id']}</b> опубликован в канал <b>{post['title']}</b>!",
                                parse_mode="HTML"
                            )
                    except Exception as e:
                        logging.error(f"Ошибка публикации #{post['id']}: {e}")
        except Exception as e:
            logging.error(f"Ошибка планировщика: {e}")

        await asyncio.sleep(15)


async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise ValueError("Не задан BOT_TOKEN!")

    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    asyncio.create_task(scheduler_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
