import asyncio
import logging
import os
from typing import Any, Dict, List
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

logging.basicConfig(level=logging.INFO)

# ==================== НАЛАШТУВАННЯ ====================
BOT_TOKEN = "8979591910:AAHL-MhsL81G7IxKrLBkUOOhQVeD1lQXSXg"
ADMIN_ID = 6765881520  # Твій числовий ID
REKVIZITY = "4441114409323761" # Тільки голі цифри картки!
# ======================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ОБХІД ТАЙМАУТУ RENDER (МІКРО-ВЕБСЕРВЕР) ---
async def handle_root(request):
    return web.Response(text="Bot is running live!")

async def start_webserver():
    app = web.Application()
    app.router.add_get('/', handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render сам передає порт у змінну оточення PORT, якщо її немає — беремо 8080
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Micro-webserver started on port {port}")

# --- МІДЛВАР ДЛЯ МЕДІАГРУП ---
class MediaGroupMiddleware(BaseMiddleware):
    def __init__(self, latency: float = 0.6):
        self.latency = latency
        self.album_cache: Dict[str, List[types.Message]] = {}
        super().__init__()

    async def __call__(self, handler, event: types.Message, data: Dict[str, Any]) -> Any:
        if not event.media_group_id:
            return await handler(event, data)
        self.album_cache.setdefault(event.media_group_id, []).append(event)
        if len(self.album_cache[event.media_group_id]) == 1:
            await asyncio.sleep(self.latency)
            data["album"] = self.album_cache.pop(event.media_group_id)
            return await handler(event, data)
        return

dp.message.middleware(MediaGroupMiddleware())

class PrintingForm(StatesGroup):
    waiting_for_color = State()
    waiting_for_type = State()
    waiting_for_files = State()

class AdminForm(StatesGroup):
    waiting_for_price = State()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🖨 Замовити друк", callback_data="start_order")
    await message.answer(
        f"Привіт! 👋\nТут можна швидко замовити друк у гуртожитку.",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "start_order")
async def start_order(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="⬛️ Чорно-білий", callback_data="color_bw")
    builder.button(text="🟥 Кольоровий", callback_data="color_cl")
    await callback.message.answer("🎨 Вибери колір друку:", reply_markup=builder.as_markup())
    await state.set_state(PrintingForm.waiting_for_color)

@dp.callback_query(PrintingForm.waiting_for_color)
async def process_color(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    color_text = "Чорно-білий" if callback.data == "color_bw" else "Кольоровий"
    await state.update_data(color=color_text)
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Односторонній", callback_data="type_single")
    builder.button(text="📖 Двосторонній", callback_data="type_double")
    await callback.message.answer("📐 Вибери тип друку:", reply_markup=builder.as_markup())
    await state.set_state(PrintingForm.waiting_for_type)

@dp.callback_query(PrintingForm.waiting_for_type)
async def process_type(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    type_text = "Односторонній" if callback.data == "type_single" else "Двосторонній"
    await state.update_data(print_type=type_text, files=[])
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Надіслати замовлення", callback_data="send_all_files")
    
    await callback.message.answer(
        "📎 <b>Надсилай файли для друку</b> (документи, photo, презентації).\n\n"
        "Коли завантажиш усе — тисни кнопку👇",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.set_state(PrintingForm.waiting_for_files)

@dp.message(PrintingForm.waiting_for_files)
async def process_incoming_files(message: types.Message, state: FSMContext, album: List[types.Message] = None):
    user_data = await state.get_data()
    file_list = user_data.get("files", [])
    last_msg_id = user_data.get("last_msg_id")
    
    messages_to_process = album if album else [message]
    added_count = 0
    
    for msg in messages_to_process:
        file_id, file_type = None, None
        if msg.document:
            file_id, file_type = msg.document.file_id, "document"
        elif msg.photo:
            file_id, file_type = msg.photo[-1].file_id, "photo"
        elif msg.video:
            file_id, file_type = msg.video.file_id, "video"
            
        if file_id:
            file_list.append({"file_id": file_id, "type": file_type})
            added_count += 1

    if added_count > 0:
        await state.update_data(files=file_list)
        if last_msg_id:
            try: await bot.delete_message(chat_id=message.chat.id, message_id=last_msg_id)
            except Exception: pass
                
        builder = InlineKeyboardBuilder()
        builder.button(text="📥 Надіслати замовлення", callback_data="send_all_files")
        
        sent_msg = await message.answer(
            f"✅ Успішно додано файлів: <b>{added_count}</b>\n📊 Всього у списку: <b>{len(file_list)}</b> ф.\n\n"
            f"Можеш кинути ще файли або підтвердити відправку👇",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        await state.set_state(PrintingForm.waiting_for_files)
        await state.update_data(last_msg_id=sent_msg.message_id)
    else:
        await message.answer("⚠️ Надішли документ, фото або відео.")

@dp.callback_query(F.data == "send_all_files", PrintingForm.waiting_for_files)
async def send_order_to_admin(callback: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    file_list = user_data.get("files", [])
    last_msg_id = user_data.get("last_msg_id")
    
    if not file_list:
        await callback.answer("❌ Список файлів порожній!", show_alert=True)
        return
        
    await callback.answer()
    if last_msg_id:
        try: await bot.delete_message(chat_id=callback.message.chat.id, message_id=last_msg_id)
        except Exception: pass
            
    await state.clear()
    
    username = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
    await callback.message.answer("🚀 Замовлення прийнято! Очікуй на сповіщення про готовність та суму.")
    
    admin_msg = (
        f"🖨 <b>Нове замовлення!</b>\n\n"
        f"👤 Замовник: {username}\n"
        f"🎨 Колір: {user_data['color']}\n"
        f"📄 Тип: {user_data['print_type']}\n"
        f"📦 Всього файлів: {len(file_list)}\n"
    )
    
    await bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
    
    for index, file_info in enumerate(file_list, start=1):
        builder = InlineKeyboardBuilder()
        if index == len(file_list):
            builder.button(text="💰 Виконано (Ввести суму)", callback_data=f"orderdone_{callback.from_user.id}")
            
        caption_text = f"Файл {index} із {len(file_list)}"
        fid = file_info["file_id"]
        
        if file_info["type"] == "document":
            await bot.send_document(chat_id=ADMIN_ID, document=fid, caption=caption_text, reply_markup=builder.as_markup())
        elif file_info["type"] == "photo":
            await bot.send_photo(chat_id=ADMIN_ID, photo=fid, caption=caption_text, reply_markup=builder.as_markup())
        elif file_info["type"] == "video":
            await bot.send_video(chat_id=ADMIN_ID, video=fid, caption=caption_text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("orderdone_"))
async def admin_click_done(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    student_id = callback.data.split("_")[1]
    await state.set_state(AdminForm.waiting_for_price)
    await state.update_data(target_student_id=student_id, admin_msg_to_edit=callback.message)
    await bot.send_message(chat_id=ADMIN_ID, text="💰 Введіть загальну суму до оплати (просто цифрами):")

@dp.message(AdminForm.waiting_for_price)
async def process_admin_price(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
        
    admin_data = await state.get_data()
    student_id = int(admin_data["target_student_id"])
    msg_to_edit = admin_data["admin_msg_to_edit"]
    price = message.text.strip()
    
    await state.clear()
    
    try:
        await bot.send_message(
            chat_id=student_id, 
            text=f"🎉 <b>Твоє замовлення готове!</b>\nМожеш підходити й забирати роздруківки.\n\n"
                 f"💰 <b>До оплати:</b> {price} грн\n"
                 f"📌 <b>Реквізити:</b> Картка: <code>{REKVIZITY}</code>",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Студенту надіслано рахунок на {price} грн, замовлення закрито!")
        await msg_to_edit.edit_caption(
            caption=msg_to_edit.caption + f"\n\n✅ <b>ВИКОНАНО (Рахунок: {price} грн)</b>", 
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Не вдалося надіслати сповіщення.")

async def set_main_menu(bot: Bot):
    main_menu_commands = [
        types.BotCommand(command="/start", description="🤖 Запустити бота / Створити замовлення")
    ]
    await bot.set_my_commands(main_menu_commands)

async def main():
    await set_main_menu(bot)
    # Запускаємо вебсервер паралельно з ботом
    await start_webserver()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
