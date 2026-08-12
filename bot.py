import asyncio
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

# ============================================
# ===== КОНФИГ =====
# ============================================
BOT_TOKEN = "8737854157:AAGWl9bHKkRGNmvseyKwcXhH-1ei2pCcyZE"
OWNER_USERNAME = 8985475819
ADMIN_PASSWORD = "19102012"

# ============================================
# ===== ДАННЫЕ В ПАМЯТИ =====
# ============================================
users_db = {}
actions_log = []
ADMIN_IDS = []
MODERATOR_IDS = []
SUPPORT_IDS = []
VIP_IDS = []
WORKER_IDS = []

LOTS = [
    {"name": "Лот 1", "cups": "86к", "gems": 23, "fighters": 104, "price": 1600},
    {"name": "Лот 2", "cups": "45к", "gems": 6, "fighters": 104, "price": 800},
    {"name": "Лот 3", "cups": "9к", "gems": 73, "fighters": 40, "price": 270},
    {"name": "Лот 4", "cups": "57772", "gems": 38, "fighters": 104, "price": 2100},
    {"name": "Лот 5", "cups": "42753", "gems": 37, "fighters": 97, "price": 1000},
    {"name": "Лот 6", "cups": "19840", "gems": 75, "fighters": 59, "price": 1100},
    {"name": "Лот 7", "cups": "43164", "gems": 27, "fighters": 75, "price": 5000},
]

DONATE_ITEMS = [
    {"name": "БП+", "price": 550},
    {"name": "БП", "price": 400},
]

# ============================================
# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
# ============================================
def get_moscow_time():
    return (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

def get_user_role(user_id: int):
    if user_id == OWNER_USERNAME:
        return "Владелец", "👑"
    if user_id in ADMIN_IDS:
        return "Админ", "🛡️"
    if user_id in MODERATOR_IDS:
        return "Модератор", "🛠️"
    if user_id in SUPPORT_IDS:
        return "Поддержка", "🎧"
    if user_id in VIP_IDS:
        return "VIP", "💎"
    if user_id in WORKER_IDS:
        return "Работник", "👷"
    return "Пользователь", "👤"

def is_admin(user_id: int):
    return user_id == OWNER_USERNAME or user_id in ADMIN_IDS

def is_vip(user_id: int):
    return user_id in VIP_IDS

def is_worker(user_id: int):
    return user_id in WORKER_IDS

def is_moderator(user_id: int):
    return user_id in MODERATOR_IDS

def is_support(user_id: int):
    return user_id in SUPPORT_IDS

def get_vip_discount(user_id: int):
    return 0.9 if is_vip(user_id) else 1.0

def track_user(user: types.User):
    if user.id not in users_db:
        users_db[user.id] = {
            "name": user.full_name or "без имени",
            "username": f"@{user.username}" if user.username else "без юзернейма",
            "balance": 0,
            "history": []
        }

def add_history(user_id: int, amount: int, description: str):
    if user_id not in users_db:
        return
    users_db[user_id]["history"].append({
        "time": get_moscow_time(),
        "amount": amount,
        "description": description
    })
    if len(users_db[user_id]["history"]) > 100:
        users_db[user_id]["history"] = users_db[user_id]["history"][-100:]

def log_action(user: types.User, action: str):
    user_str = f"{user.full_name or 'без имени'} (@{user.username if user.username else 'без юзернейма'}) [ID: {user.id}]"
    actions_log.append(f"[{get_moscow_time()}] {user_str} → {action}")
    if len(actions_log) > 1000:
        actions_log.pop(0)

# ============================================
# ===== СОСТОЯНИЯ =====
# ============================================
class ScamStates(StatesGroup):
    main_menu = State()
    waiting_support = State()
    waiting_gems_amount = State()
    admin_panel = State()
    admin_balance_user = State()
    admin_balance_amount = State()
    waiting_admin_password = State()
    admin_msg_user = State()
    admin_msg_text = State()
    waiting_withdraw_amount = State()
    waiting_withdraw_card = State()

# ============================================
# ===== КЛАВИАТУРЫ =====
# ============================================
main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🛒 Купить")],
        [KeyboardButton(text="💰 Продать")],
        [KeyboardButton(text="💸 Заработать деньги")],
        [KeyboardButton(text="❓ Поддержка")]
    ],
    resize_keyboard=True
)

worker_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🛒 Купить")],
        [KeyboardButton(text="💰 Продать")],
        [KeyboardButton(text="💸 Заработать деньги")],
        [KeyboardButton(text="❓ Поддержка")]
    ],
    resize_keyboard=True
)

moderator_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="📩 Написать письмо")],
        [KeyboardButton(text="📋 Обращения")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

owner_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🛒 Купить")],
        [KeyboardButton(text="💰 Продать")],
        [KeyboardButton(text="💸 Заработать деньги")],
        [KeyboardButton(text="❓ Поддержка")],
        [KeyboardButton(text="👑 Админ-панель")]
    ],
    resize_keyboard=True
)

admin_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="👥 Пользователи")],
        [KeyboardButton(text="📋 Действия")],
        [KeyboardButton(text="💰 Пополнить баланс")],
        [KeyboardButton(text="✉️ Отправить сообщение")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

profile_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💸 Вывести деньги")],
        [KeyboardButton(text="📜 История")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

buy_choice_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⭐ Донат")],
        [KeyboardButton(text="📱 Аккаунт")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

support_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

# ============================================
# ===== ИНИЦИАЛИЗАЦИЯ =====
# ============================================
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# ============================================
# ===== ХЕНДЛЕР START =====
# ============================================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    track_user(message.from_user)
    await state.clear()
    await state.set_state(ScamStates.main_menu)
    
    if message.from_user.id == OWNER_USERNAME:
        await message.answer("👋 Добро пожаловать, владелец!", reply_markup=owner_menu_kb)
    elif is_admin(message.from_user.id):
        await message.answer("👋 Добро пожаловать, администратор!", reply_markup=admin_menu_kb)
    elif is_moderator(message.from_user.id):
        await message.answer("👋 Добро пожаловать, модератор!", reply_markup=moderator_menu_kb)
    elif is_worker(message.from_user.id):
        await message.answer("👋 Добро пожаловать!", reply_markup=worker_menu_kb)
    else:
        await message.answer("👋 Добро пожаловать!", reply_markup=main_menu_kb)

# ============================================
# ===== ПРОФИЛЬ =====
# ============================================
@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message, state: FSMContext):
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка. Нажмите /start.")
        return
    
    balance = user_data.get("balance", 0)
    role, emoji = get_user_role(message.from_user.id)
    
    await message.answer(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"📛 Имя: {user_data['name']}\n"
        f"🔖 Юзернейм: {user_data['username']}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"💰 Баланс: {balance} ⭐\n"
        f"🎖️ Статус: {emoji} {role}",
        reply_markup=profile_kb,
        parse_mode="HTML"
    )

@dp.message(F.text == "📜 История")
async def show_history(message: Message, state: FSMContext):
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка.")
        return
    
    history = user_data.get("history", [])
    if not history:
        await message.answer("📜 История пуста", reply_markup=profile_kb)
        return
    
    text = "📜 <b>История операций (последние 10):</b>\n\n"
    for entry in history[-10:]:
        sign = "+" if entry["amount"] >= 0 else ""
        text += f"🕒 {entry['time']}\n   {sign}{entry['amount']} ⭐ — {entry['description']}\n\n"
    
    await message.answer(text, reply_markup=profile_kb, parse_mode="HTML")

# ============================================
# ===== ВЫВОД СРЕДСТВ =====
# ============================================
@dp.message(F.text == "💸 Вывести деньги")
async def start_withdraw(message: Message, state: FSMContext):
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка.")
        return
    
    await message.answer(
        f"💰 <b>Вывод средств</b>\n\n"
        f"Ваш баланс: <b>{user_data['balance']} ⭐</b>\n\n"
        f"Введите сумму для вывода:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_withdraw_amount)

@dp.message(ScamStates.waiting_withdraw_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await show_profile(message, state)
        return
    
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число.", reply_markup=back_kb)
        return
    
    user_data = users_db.get(message.from_user.id)
    if amount > user_data["balance"]:
        await message.answer(f"❌ Недостаточно средств! Баланс: {user_data['balance']} ⭐", reply_markup=back_kb)
        return
    
    await state.update_data(withdraw_amount=amount)
    await message.answer(
        f"✅ Сумма <b>{amount} ⭐</b> принята.\n\n"
        f"Введите номер карты (только цифры):",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_withdraw_card)

@dp.message(ScamStates.waiting_withdraw_card)
async def process_withdraw_card(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await show_profile(message, state)
        return
    
    card_number = message.text.replace(" ", "").replace("-", "")
    if not card_number.isdigit() or len(card_number) < 13:
        await message.answer("❌ Неверный номер карты. Должно быть 13-19 цифр.", reply_markup=back_kb)
        return
    
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    if not amount:
        await message.answer("❌ Ошибка.", reply_markup=profile_kb)
        await state.clear()
        return
    
    user_id = message.from_user.id
    users_db[user_id]["balance"] -= amount
    add_history(user_id, -amount, f"Вывод {amount} ⭐ на карту {card_number[:4]}...{card_number[-4:]}")
    log_action(message.from_user, f"ВЫВЕЛ {amount} ⭐")
    
    commission = amount * 0.05
    await message.answer(
        f"✅ Заявка на вывод <b>{amount} ⭐</b> отправлена!\n\n"
        f"Средства поступят в течение 2-3 недель.\n"
        f"Комиссия: <b>{commission:.2f} ⭐</b>\n"
        f"Новый баланс: <b>{users_db[user_id]['balance']} ⭐</b>",
        reply_markup=profile_kb,
        parse_mode="HTML"
    )
    await state.clear()

# ============================================
# ===== КУПИТЬ =====
# ============================================
@dp.message(F.text == "🛒 Купить")
async def handle_buy(message: Message, state: FSMContext):
    await message.answer("🛒 <b>Что вас интересует?</b>", reply_markup=buy_choice_kb, parse_mode="HTML")

@dp.message(F.text == "⭐ Донат")
async def handle_donate(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for item in DONATE_ITEMS:
        price = item['price']
        if is_vip(message.from_user.id):
            price = int(price * 0.9)
            label = f"🛒 {item['name']} за {price} ⭐ (VIP скидка 10%)"
        else:
            label = f"🛒 {item['name']} за {price} ⭐"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"donate_{item['name'].lower().replace('+', 'p')}")])
    
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="💎 Купить гемы", callback_data="donate_gems")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="donate_back")])
    
    await message.answer("⭐ <b>Выберите товар:</b>", reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("donate_"))
async def process_donate(callback: CallbackQuery, state: FSMContext):
    if callback.data == "donate_back":
        await callback.answer()
        await callback.message.delete()
        await handle_buy(callback.message, state)
        return
    
    if callback.data == "donate_gems":
        await callback.answer()
        await callback.message.answer(
            "💎 <b>Покупка гемов</b>\n\n"
            "Введите количество гемов.\n"
            "Цена: 1 гем = 4.5 ⭐\n\n"
            "🔙 Для отмены нажмите 'Назад'.",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        await state.set_state(ScamStates.waiting_gems_amount)
        return
    
    # Покупка доната
    item_key = callback.data.split("_")[1]
    target_item = None
    for item in DONATE_ITEMS:
        if item['name'].lower().replace('+', 'p') == item_key:
            target_item = item
            break
    
    if not target_item:
        await callback.answer("❌ Товар не найден.", show_alert=True)
        return
    
    user_id = callback.from_user.id
    user_data = users_db.get(user_id)
    if not user_data:
        await callback.answer("❌ Ошибка.", show_alert=True)
        return
    
    price = target_item['price']
    if is_vip(user_id):
        price = int(price * 0.9)
    
    if user_data["balance"] < price:
        await callback.answer("❌ Недостаточно средств!", show_alert=True)
        await callback.message.answer(f"❌ Нужно: {price} ⭐, у вас: {user_data['balance']} ⭐", parse_mode="HTML")
        return
    
    users_db[user_id]["balance"] -= price
    add_history(user_id, -price, f"Покупка {target_item['name']}")
    log_action(callback.from_user, f"КУПИЛ {target_item['name']}")
    
    await callback.answer("✅ Покупка успешна!", show_alert=True)
    await callback.message.answer(
        f"✅ Вы приобрели <b>{target_item['name']}</b> за {price} ⭐.\n"
        f"💰 Новый баланс: {users_db[user_id]['balance']} ⭐ 🎉",
        parse_mode="HTML"
    )

@dp.message(ScamStates.waiting_gems_amount)
async def handle_gems_amount(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await handle_donate(message, state)
        return
    
    try:
        gems = float(message.text.replace(",", "."))
        if gems <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.", reply_markup=back_kb)
        return
    
    price = int(gems * 4.5)
    if is_vip(message.from_user.id):
        price = int(price * 0.9)
    
    user_id = message.from_user.id
    user_data = users_db.get(user_id)
    
    if user_data["balance"] < price:
        await message.answer(f"❌ Недостаточно средств! Нужно: {price} ⭐, у вас: {user_data['balance']} ⭐", reply_markup=back_kb)
        return
    
    users_db[user_id]["balance"] -= price
    add_history(user_id, -price, f"Покупка {gems} гемов")
    log_action(message.from_user, f"КУПИЛ {gems} ГЕМОВ")
    
    await message.answer(
        f"✅ Вы приобрели <b>{gems} гемов</b> за {price} ⭐.\n"
        f"💰 Новый баланс: {users_db[user_id]['balance']} ⭐ 🎉",
        reply_markup=buy_choice_kb,
        parse_mode="HTML"
    )
    await state.clear()

@dp.message(F.text == "📱 Аккаунт")
async def handle_accounts(message: Message, state: FSMContext):
    text = "🛒 <b>Выберите лот:</b>\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for idx, lot in enumerate(LOTS):
        price = lot['price']
        if is_vip(message.from_user.id):
            price = int(price * 0.9)
            text += f"━━━━━━━━━━━━━━━━━━━━━\n🎯 {lot['name']}\n🏆 {lot['cups']} кубков\n💎 {lot['gems']} гемов\n⚔️ {lot['fighters']} бойцов\n💰 <b>{price} ⭐ (VIP скидка)</b>\n"
        else:
            text += f"━━━━━━━━━━━━━━━━━━━━━\n🎯 {lot['name']}\n🏆 {lot['cups']} кубков\n💎 {lot['gems']} гемов\n⚔️ {lot['fighters']} бойцов\n💰 <b>{price} ⭐</b>\n"
        
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"🛒 Купить {lot['name']}", callback_data=f"buy_lot_{idx}")])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_lot_"))
async def process_buy_lot(callback: CallbackQuery):
    lot_index = int(callback.data.split("_")[2])
    if lot_index >= len(LOTS):
        await callback.answer("❌ Лот не найден.", show_alert=True)
        return
    
    lot = LOTS[lot_index]
    user_id = callback.from_user.id
    user_data = users_db.get(user_id)
    
    if not user_data:
        await callback.answer("❌ Ошибка.", show_alert=True)
        return
    
    price = lot['price']
    if is_vip(user_id):
        price = int(price * 0.9)
    
    if user_data["balance"] < price:
        await callback.answer("❌ Недостаточно средств!", show_alert=True)
        await callback.message.answer(f"❌ Нужно: {price} ⭐, у вас: {user_data['balance']} ⭐", parse_mode="HTML")
        return
    
    users_db[user_id]["balance"] -= price
    add_history(user_id, -price, f"Покупка {lot['name']}")
    log_action(callback.from_user, f"КУПИЛ {lot['name']}")
    
    await callback.answer("✅ Покупка успешна!", show_alert=True)
    await callback.message.answer(
        f"✅ Вы купили <b>{lot['name']}</b> за {price} ⭐.\n"
        f"💰 Новый баланс: {users_db[user_id]['balance']} ⭐ 🎉",
        parse_mode="HTML"
    )

# ============================================
# ===== ПРОДАЖА =====
# ============================================
@dp.message(F.text == "💰 Продать")
async def handle_sell(message: Message, state: FSMContext):
    await message.answer(
        "💰 <b>Продажа аккаунта</b>\n\n"
        "Свяжитесь с поддержкой: @suport_skup_bs_bot",
        reply_markup=back_kb,
        parse_mode="HTML"
    )

# ============================================
# ===== ЗАРАБОТОК =====
# ============================================
@dp.message(F.text == "💸 Заработать деньги")
async def handle_earn(message: Message, state: FSMContext):
    await message.answer(
        "💰 <b>Зарабатывайте с нами!</b>\n\n"
        "🔥 Пишите комментарии в TikTok:\n"
        "<code>@skup_bs_bot лучший бот для продажи аккаунта Brawl Stars</code>\n\n"
        "📊 <b>Условия:</b>\n"
        "✅ 1 комментарий = 5 ⭐\n"
        "✅ 200 комментариев = 1000 ⭐\n\n"
        "⚠️ Для выплаты нужны скриншоты!\n"
        "💬 Обращайтесь: @suport_skup_bs_bot",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
  # ============================================
# ===== ПОДДЕРЖКА =====
# ============================================
@dp.message(F.text == "❓ Поддержка")
async def handle_support(message: Message, state: FSMContext):
    await message.answer(
        "📩 <b>Поддержка</b>\n\n"
        "Напишите ваш вопрос одним сообщением.\n"
        "Наш оператор ответит вам в ближайшее время.\n\n"
        "✍️ Введите текст сообщения:",
        reply_markup=support_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_support)

@dp.message(ScamStates.waiting_support)
async def process_support(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await state.set_state(ScamStates.main_menu)
        if message.from_user.id == OWNER_USERNAME:
            await message.answer("❓ Меню:", reply_markup=owner_menu_kb)
        elif is_admin(message.from_user.id):
            await message.answer("❓ Меню:", reply_markup=admin_menu_kb)
        elif is_moderator(message.from_user.id):
            await message.answer("❓ Меню:", reply_markup=moderator_menu_kb)
        else:
            await message.answer("❓ Меню:", reply_markup=main_menu_kb)
        return
    
    user = message.from_user
    admin_text = (
        f"📩 <b>Сообщение от пользователя</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Юзернейм: @{user.username if user.username else 'без юзернейма'}\n"
        f"📛 Имя: {user.full_name or 'без имени'}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Текст сообщения:</b>\n{message.text}"
    )
    
    log_action(user, f"ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ: {message.text[:50]}...")
    
    try:
        # Отправляем владельцу
        await bot.send_message(OWNER_USERNAME, admin_text, parse_mode="HTML")
        
        # Отправляем всем в поддержке
        for sup_id in SUPPORT_IDS:
            try:
                await bot.send_message(sup_id, admin_text, parse_mode="HTML")
            except:
                pass
        
        await message.answer(
            "✅ <b>Ваше сообщение отправлено!</b>\n\n"
            "Наш оператор свяжется с вами в ближайшее время.\n"
            "Спасибо за обращение! 🙌",
            reply_markup=main_menu_kb,
            parse_mode="HTML"
        )
        await state.clear()
        await state.set_state(ScamStates.main_menu)
    except Exception as e:
        await message.answer(
            f"❌ Ошибка: {e}\n\n"
            "Попробуйте позже или напишите напрямую @suport_skup_bs_bot",
            reply_markup=support_kb,
            parse_mode="HTML"
        )

# ============================================
# ===== МОДЕРАТОР =====
# ============================================
@dp.message(F.text == "📩 Написать письмо")
async def moderator_write_letter(message: Message, state: FSMContext):
    if not is_moderator(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    await message.answer(
        "✍️ <b>Напишите письмо пользователю</b>\n\n"
        "Введите ID или @юзернейм получателя и текст через пробел.\n"
        "Пример: <code>123456789 Здравствуйте, ваш аккаунт был разморожен.</code>\n"
        "Или: <code>@username Ваш баланс пополнен.</code>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_msg_user)

@dp.message(ScamStates.admin_msg_user)
async def moderator_msg_user_input(message: Message, state: FSMContext):
    if not is_moderator(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    if message.text == "🔙 Назад":
        await state.clear()
        if message.from_user.id == OWNER_USERNAME:
            await message.answer("❓ Меню:", reply_markup=owner_menu_kb)
        elif is_admin(message.from_user.id):
            await message.answer("❓ Меню:", reply_markup=admin_menu_kb)
        elif is_moderator(message.from_user.id):
            await message.answer("❓ Меню:", reply_markup=moderator_menu_kb)
        else:
            await message.answer("❓ Меню:", reply_markup=main_menu_kb)
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Введите ID и текст через пробел.", reply_markup=back_kb)
        return
    
    identifier = parts[0]
    msg_text = parts[1]
    
    # Поиск пользователя
    target_user = None
    if identifier.startswith('@'):
        username = identifier[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                target_user = uid
                break
    else:
        try:
            uid = int(identifier)
            if uid in users_db:
                target_user = uid
        except ValueError:
            pass
    
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_kb)
        return
    
    try:
        await bot.send_message(
            target_user,
            f"📩 <b>Сообщение от модератора</b>\n\n{msg_text}",
            parse_mode="HTML"
        )
        await message.answer(
            f"✅ Сообщение отправлено пользователю {users_db[target_user]['name']}.",
            reply_markup=moderator_menu_kb,
            parse_mode="HTML"
        )
        log_action(message.from_user, f"ОТПРАВИЛ СООБЩЕНИЕ пользователю {users_db[target_user]['username']}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=moderator_menu_kb)
    
    await state.clear()
    await state.set_state(ScamStates.main_menu)

@dp.message(F.text == "📋 Обращения")
async def moderator_view_appeals(message: Message, state: FSMContext):
    if not is_moderator(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    # Фильтруем только обращения в поддержку
    appeals = []
    for entry in actions_log:
        if "ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ" in entry:
            appeals.append(entry)
    
    if not appeals:
        await message.answer(
            "📋 <b>Обращения</b>\n\n"
            "📭 Пока нет обращений в поддержку.",
            reply_markup=moderator_menu_kb,
            parse_mode="HTML"
        )
        return
    
    text = "📋 <b>Последние обращения в поддержку:</b>\n\n"
    for idx, appeal in enumerate(appeals[-10:], 1):
        text += f"{idx}. {appeal}\n"
    
    await message.answer(text, reply_markup=moderator_menu_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН-ПАНЕЛЬ =====
# ============================================
@dp.message(F.text == "👑 Админ-панель")
async def admin_panel_request(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    await message.answer(
        "🔐 <b>Введите пароль для доступа к админ-панели:</b>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_admin_password)

@dp.message(ScamStates.waiting_admin_password)
async def admin_password_check(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    if message.text == "🔙 Назад":
        await state.clear()
        await state.set_state(ScamStates.main_menu)
        if message.from_user.id == OWNER_USERNAME:
            await message.answer("❓ Меню:", reply_markup=owner_menu_kb)
        elif is_admin(message.from_user.id):
            await message.answer("❓ Меню:", reply_markup=admin_menu_kb)
        else:
            await message.answer("❓ Меню:", reply_markup=main_menu_kb)
        return
    
    if message.text == ADMIN_PASSWORD:
        await message.answer(
            "✅ <b>Пароль верный!</b>\n\n"
            "👑 <b>Админ-панель</b>\n\n"
            "Выберите действие:",
            reply_markup=admin_menu_kb,
            parse_mode="HTML"
        )
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer(
            "❌ <b>Неверный пароль!</b>\n\n"
            "Попробуйте ещё раз или нажмите 'Назад'.",
            reply_markup=back_kb,
            parse_mode="HTML"
        )

# ============================================
# ===== АДМИН: СТАТИСТИКА =====
# ============================================
@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    total_users = len(users_db)
    total_actions = len(actions_log)
    
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"📋 Всего действий: <b>{total_actions}</b>",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )

# ============================================
# ===== АДМИН: ПОЛЬЗОВАТЕЛИ =====
# ============================================
@dp.message(F.text == "👥 Пользователи")
async def admin_users(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if not users_db:
        await message.answer(
            "👥 <b>Пользователи</b>\n\n"
            "Пока ни одного пользователя.",
            reply_markup=admin_menu_kb,
            parse_mode="HTML"
        )
        return
    
    text = "👥 <b>Список пользователей:</b>\n\n"
    for idx, (uid, data) in enumerate(users_db.items(), 1):
        text += f"{idx}. <b>ID:</b> <code>{uid}</code>\n"
        text += f"   📛 {data['name']}\n"
        text += f"   🔖 {data['username']}\n"
        text += f"   💰 Баланс: {data.get('balance', 0)} ⭐\n\n"
        if idx >= 20:
            text += f"... и ещё {len(users_db) - 20} пользователей.\n"
            break
    
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН: ДЕЙСТВИЯ =====
# ============================================
@dp.message(F.text == "📋 Действия")
async def admin_actions(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if not actions_log:
        await message.answer(
            "📋 <b>Действия</b>\n\n"
            "Пока нет действий.",
            reply_markup=admin_menu_kb,
            parse_mode="HTML"
        )
        return
    
    log_entries = actions_log[-20:]
    text = "📋 <b>Последние действия:</b>\n\n"
    for entry in log_entries:
        text += f"• {entry}\n"
    
    if len(actions_log) > 20:
        text += f"\n... и ещё {len(actions_log) - 20} действий."
    
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН: ПОПОЛНЕНИЕ БАЛАНСА =====
# ============================================
@dp.message(F.text == "💰 Пополнить баланс")
async def admin_balance_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "💰 <b>Пополнение или списание баланса</b>\n\n"
        "Введите <b>ID или @юзернейм</b> пользователя.\n"
        "Примеры: <code>123456789</code> или <code>@username</code>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_balance_user)

@dp.message(ScamStates.admin_balance_user)
async def admin_balance_user_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    identifier = message.text.strip()
    target_user = None
    
    # Поиск по @юзернейму
    if identifier.startswith('@'):
        username = identifier[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                target_user = uid
                break
    else:
        # Поиск по ID
        try:
            uid = int(identifier)
            if uid in users_db:
                target_user = uid
        except ValueError:
            pass
    
    if target_user is None:
        await message.answer(
            "❌ Пользователь не найден. Проверьте ID или юзернейм.",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    await state.update_data(target_user=target_user)
    await message.answer(
        f"✅ Найден пользователь: {users_db[target_user]['name']} ({users_db[target_user]['username']})\n"
        f"Текущий баланс: {users_db[target_user]['balance']} ⭐\n\n"
        f"Введите <b>сумму изменения</b> (целое число):\n"
        f"➕ положительное — пополнение\n"
        f"➖ отрицательное — списание\n\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_balance_amount)

@dp.message(ScamStates.admin_balance_amount)
async def admin_balance_amount_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        amount = int(message.text.strip())
        if amount == 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите целое число (положительное для пополнения, отрицательное для списания), не равное нулю.",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    data = await state.get_data()
    target_user = data.get("target_user")
    if target_user is None or target_user not in users_db:
        await message.answer("❌ Ошибка: пользователь не найден.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    current_balance = users_db[target_user]["balance"]
    if amount < 0 and abs(amount) > current_balance:
        await message.answer(
            f"❌ Недостаточно средств! Текущий баланс пользователя: {current_balance} ⭐.\n"
            f"Списание на {abs(amount)} ⭐ невозможно.",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    users_db[target_user]["balance"] += amount
    new_balance = users_db[target_user]["balance"]
    
    if amount > 0:
        add_history(target_user, amount, "Пополнение (админ)")
        desc = f"ПОПОЛНИЛ БАЛАНС на {amount} ⭐"
    else:
        add_history(target_user, amount, f"Списание ({abs(amount)} ⭐)")
        desc = f"СПИСАЛ БАЛАНС на {abs(amount)} ⭐"
    
    log_action(message.from_user, f"{desc} пользователю {users_db[target_user]['username']} (ID {target_user})")
    
    await message.answer(
        f"✅ Баланс пользователя {users_db[target_user]['name']} изменён на {amount} ⭐.\n"
        f"Новый баланс: {new_balance} ⭐.",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН: ОТПРАВКА СООБЩЕНИЯ =====
# ============================================
@dp.message(F.text == "✉️ Отправить сообщение")
async def admin_send_message_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "✉️ <b>Отправка сообщения пользователю</b>\n\n"
        "Введите <b>ID или @юзернейм</b> пользователя.\n"
        "Примеры: <code>123456789</code> или <code>@username</code>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_msg_user)

@dp.message(ScamStates.admin_msg_user)
async def admin_msg_user_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    identifier = message.text.strip()
    target_user = None
    
    # Поиск по @юзернейму
    if identifier.startswith('@'):
        username = identifier[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                target_user = uid
                break
    else:
        # Поиск по ID
        try:
            uid = int(identifier)
            if uid in users_db:
                target_user = uid
        except ValueError:
            pass
    
    if target_user is None:
        await message.answer(
            "❌ Пользователь не найден. Проверьте ID или юзернейм.",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    await state.update_data(target_user=target_user)
    await message.answer(
        f"✅ Найден пользователь: {users_db[target_user]['name']} ({users_db[target_user]['username']})\n\n"
        f"✉️ Введите <b>текст сообщения</b>:\n\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_msg_text)

@dp.message(ScamStates.admin_msg_text)
async def admin_msg_text_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    data = await state.get_data()
    target_user = data.get("target_user")
    if target_user is None or target_user not in users_db:
        await message.answer("❌ Ошибка: пользователь не найден.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    msg_text = message.text
    log_action(message.from_user, f"ОТПРАВИЛ СООБЩЕНИЕ пользователю {users_db[target_user]['username']} (ID {target_user})")
    
    try:
        await bot.send_message(
            target_user,
            f"📩 <b>Сообщение от администрации</b>\n\n{msg_text}",
            parse_mode="HTML"
        )
        await message.answer(
            f"✅ Сообщение успешно отправлено пользователю {users_db[target_user]['name']}.",
            reply_markup=admin_menu_kb,
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение: {e}", reply_markup=admin_menu_kb)
    
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== ОБРАБОТЧИК НАЗАД =====
# ============================================
@dp.message(F.text == "🔙 Назад")
async def handle_back(message: Message, state: FSMContext):
    current_state = await state.get_state()
    
    admin_states = [
        ScamStates.admin_panel,
        ScamStates.admin_balance_user,
        ScamStates.admin_balance_amount,
        ScamStates.admin_msg_user,
        ScamStates.admin_msg_text,
        ScamStates.waiting_admin_password,
    ]
    
    if current_state in admin_states:
        if is_admin(message.from_user.id):
            await admin_panel_request(message, state)
        else:
            await state.clear()
            await state.set_state(ScamStates.main_menu)
            await message.answer("❓ Меню:", reply_markup=main_menu_kb)
        return
    
    if current_state in [ScamStates.waiting_withdraw_amount, ScamStates.waiting_withdraw_card]:
        await show_profile(message, state)
        return
    
    if current_state == ScamStates.waiting_gems_amount:
        await handle_donate(message, state)
        return
    
    if current_state == ScamStates.waiting_support:
        await state.clear()
        await state.set_state(ScamStates.main_menu)
        if message.from_user.id == OWNER_USERNAME:
            await message.answer("❓ Меню:", reply_markup=owner_menu_kb)
        elif is_admin(message.from_user.id):
            await message.answer("❓ Меню:", reply_markup=admin_menu_kb)
        elif is_moderator(message.from_user.id):
            await message.answer("❓ Меню:", reply_markup=moderator_menu_kb)
        else:
            await message.answer("❓ Меню:", reply_markup=main_menu_kb)
        return
    
    await state.clear()
    await state.set_state(ScamStates.main_menu)
    if message.from_user.id == OWNER_USERNAME:
        await message.answer("❓ Меню:", reply_markup=owner_menu_kb)
    elif is_admin(message.from_user.id):
        await message.answer("❓ Меню:", reply_markup=admin_menu_kb)
    elif is_moderator(message.from_user.id):
        await message.answer("❓ Меню:", reply_markup=moderator_menu_kb)
    else:
        await message.answer("❓ Меню:", reply_markup=main_menu_kb)

# ============================================
# ===== ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ =====
# ============================================
@dp.message()
async def catch_all_messages(message: Message, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state == ScamStates.waiting_gems_amount:
        await message.answer(
            "💎 Введите количество гемов (число).\n"
            "Или нажмите 'Назад' для отмены.",
            reply_markup=back_kb
        )
    elif current_state == ScamStates.waiting_support:
        await message.answer(
            "📩 Отправьте текстовое сообщение с вашим вопросом.\n"
            "Или нажмите 'Назад' для отмены.",
            reply_markup=support_kb
        )
    elif current_state == ScamStates.waiting_withdraw_amount:
        await message.answer(
            "💰 Введите сумму вывода (целое число).\n"
            "Или нажмите 'Назад'.",
            reply_markup=back_kb
        )
    elif current_state == ScamStates.waiting_withdraw_card:
        await message.answer(
            "💳 Введите номер карты (только цифры).\n"
            "Или нажмите 'Назад'.",
            reply_markup=back_kb
        )
    else:
        await message.answer(
            "❓ Используйте кнопки меню.\n"
            "Если вы не видите кнопки, нажмите /start",
            reply_markup=main_menu_kb
        )

# ============================================
# ===== ЗАПУСК БОТА =====
# ============================================
async def main():
    print("=" * 50)
    print("🤖 БОТ ЗАПУЩЕН (ПОЛНАЯ ВЕРСИЯ)")
    print("=" * 50)
    print("✅ Все функции активны:")
    print("   - 👤 Профиль и вывод средств")
    print("   - 🛒 Покупка (донат, гемы, лоты)")
    print("   - 📩 Поддержка и модерация")
    print("   - 👑 Админ-панель")
    print("=" * 50)
    print("📌 Данные хранятся в памяти (при перезапуске сбрасываются)")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
