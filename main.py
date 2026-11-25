M channels WHERE id = ?", (ch_id,))
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
    await cb_back_main(callback, state) FRO
M channels WHERE id = ?", (ch_id,))
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
    await cb_back_main(callback, state) FRO