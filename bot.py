import random
import asyncio
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from typing import Callable, Dict, Any, Awaitable
import hashlib

# ===== КОНФИГ =====
BOT_TOKEN = "8737854157:AAGWl9bHKkRGNmvseyKwcXhH-1ei2pCcyZE"
OWNER_USERNAME = 8985475819
ADMIN_PASSWORD = "19102012"
SUPPORT_PASSWORD = "148867"

# ===== СПИСКИ РОЛЕЙ =====
ADMIN_IDS = []           # ID админов
MODERATOR_IDS = []       # ID модераторов
SUPPORT_IDS = []         # ID поддержки
TESTER_IDS = []          # ID тестеров
VIP_IDS = []             # ID VIP-пользователей
WORKER_IDS = []          # ID работников

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====
tech_break_enabled = False
tech_break_end = None
tech_break_reason = ""
pending_actions = {}
user_tasks = {}

def get_moscow_datetime():
    return datetime.now() + timedelta(hours=3)

def get_moscow_time():
    return get_moscow_datetime().strftime("%Y-%m-%d %H:%M:%S")

def is_tech_break_active():
    global tech_break_enabled, tech_break_end
    if not tech_break_enabled or tech_break_end is None:
        return False
    now = get_moscow_datetime()
    if now < tech_break_end:
        return True
    else:
        tech_break_enabled = False
        tech_break_end = None
        tech_break_reason = ""
        return False

def get_user_role(user_id: int):
    if user_id == OWNER_USERNAME:
        return "Владелец", "👑"
    if user_id in ADMIN_IDS:
        return "Админ", "🛡️"
    if user_id in MODERATOR_IDS:
        return "Модератор", "🛠️"
    if user_id in SUPPORT_IDS:
        return "Поддержка", "🎧"
    if user_id in TESTER_IDS:
        return "Тестер", "🧪"
    if user_id in VIP_IDS:
        return "VIP", "💎"
    if user_id in WORKER_IDS:
        return "Работник", "👷"
    return "Пользователь", "👤"

def get_vip_discount(user_id: int) -> float:
    if user_id in VIP_IDS:
        return 0.9
    return 1.0

def get_vip_bonus(user_id: int) -> float:
    if user_id in VIP_IDS:
        return 1.05
    return 1.0

def get_infinite_balance(user_id: int) -> bool:
    if user_id == OWNER_USERNAME or user_id in ADMIN_IDS:
        return True
    return False

# ===== СПИСОК ЛОТОВ =====
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

users_db = {}
actions_log = []

def add_history_entry(user_id: int, amount: int, description: str):
    if user_id not in users_db:
        return
    now = get_moscow_time()
    users_db[user_id].setdefault("history", []).append({
        "time": now,
        "amount": amount,
        "description": description
    })
    if len(users_db[user_id]["history"]) > 100:
        users_db[user_id]["history"] = users_db[user_id]["history"][-100:]

def log_action(user: types.User, action: str):
    now = get_moscow_time()
    user_str = f"{user.full_name or 'без имени'} (@{user.username if user.username else 'без юзернейма'}) [ID: {user.id}]"
    actions_log.append(f"[{now}] {user_str} → {action}")
    if len(actions_log) > 1000:
        actions_log.pop(0)

def track_user(user: types.User):
    now = get_moscow_time()
    if user.id not in users_db:
        users_db[user.id] = {
            "name": user.full_name or "без имени",
            "username": f"@{user.username}" if user.username else "без юзернейма",
            "first_seen": now,
            "last_seen": now,
            "balance": 0,
            "history": [],
            "frozen_until": None,
            "frozen_reason": None
        }
    else:
        users_db[user.id]["last_seen"] = now
        users_db[user.id]["name"] = user.full_name or "без имени"
        users_db[user.id]["username"] = f"@{user.username}" if user.username else "без юзернейма"

def is_user_frozen(user_id: int):
    user_data = users_db.get(user_id)
    if not user_data:
        return False, None, None
    frozen_until = user_data.get("frozen_until")
    frozen_reason = user_data.get("frozen_reason")
    if frozen_until is None:
        return False, None, None
    now = get_moscow_datetime()
    if isinstance(frozen_until, datetime) and now < frozen_until:
        return True, frozen_until, frozen_reason
    elif frozen_until == "forever":
        return True, "навсегда", frozen_reason
    else:
        user_data["frozen_until"] = None
        user_data["frozen_reason"] = None
        return False, None, None

def get_photo_hash(photo: types.PhotoSize) -> str:
    file_id = photo.file_id
    return hashlib.md5(file_id.encode()).hexdigest()

class RegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = event.from_user
        if user.id not in users_db and (not event.text or event.text != "/start"):
            await event.answer("⚠️ Пожалуйста, нажмите /start для начала работы.")
            return
        return await handler(event, data)

class TechBreakMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if is_tech_break_active():
            user = event.from_user
            if user.id == OWNER_USERNAME or user.id in TESTER_IDS:
                return await handler(event, data)
            end_dt = tech_break_end
            end_str = end_dt.strftime("%d.%m.%Y %H:%M")
            reason = tech_break_reason if tech_break_reason else "не указана"
            msg = (
                f"🛠️ <b>Технический перерыв!</b>\n\n"
                f"⏰ Бот временно недоступен до <b>{end_str}</b> (по московскому времени).\n"
                f"📌 <b>Причина:</b> {reason}\n\n"
                f"📩 По всем вопросам обращайтесь в поддержку: @suport_skup_bs_bot\n"
                f"или воспользуйтесь кнопкой «Поддержка» в главном меню бота."
            )
            if isinstance(event, types.Message):
                await event.answer(msg, parse_mode="HTML")
            elif isinstance(event, types.CallbackQuery):
                await event.answer("🛠️ Технический перерыв", show_alert=True)
                await event.message.answer(msg, parse_mode="HTML")
            return
        return await handler(event, data)

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
    waiting_tech_break_time = State()
    waiting_tech_break_reason = State()
    waiting_new_lot_number = State()
    waiting_new_lot_cups = State()
    waiting_new_lot_fighters = State()
    waiting_new_lot_gems = State()
    waiting_new_lot_price = State()
    admin_freeze_user = State()
    admin_freeze_date = State()
    admin_freeze_reason = State()
    admin_unfreeze_user = State()
    admin_assign_user = State()
    admin_assign_status = State()
    worker_task_comments = State()
    worker_task_confirm = State()
    worker_task_working = State()

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

dp.message.middleware(RegistrationMiddleware())
dp.message.middleware(TechBreakMiddleware())
dp.callback_query.middleware(TechBreakMiddleware())

def generate_donate_code(prefix="BB"):
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(random.choices(chars, k=6))
    return f"{prefix}{random_part}"

async def notify_owner(user: types.User, action: str, send_to_dm: bool = False):
    log_action(user, action)
    if send_to_dm:
        try:
            await bot.send_message(OWNER_USERNAME, f"🔔 <b>Действие пользователя</b>\n\n{action}", parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка отправки уведомления в личку: {e}")

# ===== КЛАВИАТУРЫ =====
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
        [KeyboardButton(text="👷 Работа")],
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
        [KeyboardButton(text="➕ Создать новый лот")],
        [KeyboardButton(text="👥 Пользователи")],
        [KeyboardButton(text="📋 Действия")],
        [KeyboardButton(text="💰 Пополнить баланс")],
        [KeyboardButton(text="✉️ Отправить сообщение")],
        [KeyboardButton(text="❄️ Заморозить профиль")],
        [KeyboardButton(text="🔄 Разморозить профиль")],
        [KeyboardButton(text="👑 Назначить статус")],
        [KeyboardButton(text="🛠 Включить перерыв")],
        [KeyboardButton(text="⛔ Отключить перерыв")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

profile_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Пополнить баланс")],
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

gems_back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

sell_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📦 Выставить товар")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

support_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

back_to_main_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

# ============================================
# ===== ОСНОВНЫЕ ХЕНДЛЕРЫ =====
# ============================================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    track_user(message.from_user)
    await notify_owner(message.from_user, "ЗАПУСТИЛ БОТА (/start)")
    await state.clear()
    await state.set_state(ScamStates.main_menu)
    user_id = message.from_user.id
    if user_id == OWNER_USERNAME:
        await message.answer(
            "👋 <b>Добро пожаловать, владелец!</b>\n\n"
            "❓ <b>Что вы хотите сделать?</b>\n\n"
            "🔹 У вас есть доступ к админ-панели (кнопка ниже).",
            reply_markup=owner_menu_kb, parse_mode="HTML"
        )
    elif user_id in ADMIN_IDS:
        await message.answer(
            "👋 <b>Добро пожаловать, администратор!</b>\n\n"
            "❓ <b>Что вы хотите сделать?</b>\n\n"
            "🔹 У вас есть доступ к админ-панели (кнопка ниже).",
            reply_markup=admin_menu_kb, parse_mode="HTML"
        )
    elif user_id in MODERATOR_IDS:
        await message.answer(
            "👋 <b>Добро пожаловать, модератор!</b>\n\n"
            "❓ <b>Что вы хотите сделать?</b>",
            reply_markup=moderator_menu_kb, parse_mode="HTML"
        )
    elif user_id in WORKER_IDS:
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "❓ <b>Что вы хотите сделать?</b>",
            reply_markup=worker_menu_kb, parse_mode="HTML"
        )
    else:
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "❓ <b>Что вы хотите сделать?</b>",
            reply_markup=main_menu_kb, parse_mode="HTML"
        )

# ============================================
# ===== ПРОФИЛЬ С ОТОБРАЖЕНИЕМ РОЛИ =====
# ============================================
@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message, state: FSMContext):
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        return
    balance = user_data.get("balance", 0)
    username = user_data.get("username", "без юзернейма")
    name = user_data.get("name", "без имени")
    role, emoji = get_user_role(message.from_user.id)
    
    # Показываем бесконечный баланс для владельца и админа
    balance_display = "♾️ Бесконечный" if get_infinite_balance(message.from_user.id) else f"{balance} ⭐"
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    frozen_text = ""
    if frozen:
        if until == "навсегда":
            frozen_text = "❄️ Профиль заморожен НАВСЕГДА."
        else:
            frozen_text = f"❄️ Профиль заморожен до {until.strftime('%d.%m.%Y %H:%M')} (МСК)."
        frozen_text += f"\n📌 Причина: {reason}"
        frozen_text += "\n⚠️ <b>Вывод средств и покупка лотов недоступны!</b>"
    else:
        frozen_text = "✅ Профиль активен."
    
    await message.answer(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"📛 <b>Имя:</b> {name}\n"
        f"🔖 <b>Юзернейм:</b> {username}\n"
        f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n"
        f"💰 <b>Баланс:</b> {balance_display}\n"
        f"🎖️ <b>Статус:</b> {emoji} {role}\n\n"
        f"{frozen_text}\n\n"
        "👇 Выберите действие:",
        reply_markup=profile_kb, parse_mode="HTML"
    )

@dp.message(F.text == "📜 История")
async def show_history(message: Message, state: FSMContext):
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        return
    history = user_data.get("history", [])
    if not history:
        await message.answer("📜 <b>История операций пуста</b>\n\nЗдесь будут отображаться все пополнения и траты.", reply_markup=profile_kb, parse_mode="HTML")
        return
    entries = history[-20:][::-1]
    text = "📜 <b>История операций (последние 20):</b>\n\n"
    for entry in entries:
        sign = "+" if entry["amount"] >= 0 else ""
        text += f"🕒 {entry['time']}\n   {sign}{entry['amount']} ⭐ — {entry['description']}\n\n"
    await message.answer(text, reply_markup=profile_kb, parse_mode="HTML")

@dp.message(F.text == "💰 Пополнить баланс")
async def handle_balance_topup(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if message.from_user.id == OWNER_USERNAME and current_state == ScamStates.admin_panel:
        await admin_balance_start(message, state)
        return
    if message.from_user.id == OWNER_USERNAME:
        await message.answer("👑 Вы владелец. Используйте админ-панель для пополнения баланса пользователей.", reply_markup=profile_kb, parse_mode="HTML")
    else:
        await message.answer("💳 <b>Пополнение баланса</b>\n\nДля пополнения баланса обратитесь в нашу поддержку:\n👤 <b>@suport_skup_bs_bot</b>\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.\n\nУкажите свой ID и сумму пополнения.\nСпасибо! 😊", reply_markup=profile_kb, parse_mode="HTML")

# ============================================
# ===== ВЫВОД =====
# ============================================
@dp.message(F.text == "💸 Вывести деньги")
async def start_withdraw(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>\n\nВы не можете вывести средства, так как ваш баланс не ограничен.", reply_markup=profile_kb, parse_mode="HTML")
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.\nЕсли вы не согласны с решением, обратитесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", reply_markup=profile_kb, parse_mode="HTML")
        return
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        return
    await message.answer(f"💰 <b>Вывод средств</b>\n\nВаш текущий баланс: <b>{user_data['balance']} ⭐</b>\n\nВведите сумму, которую хотите вывести (целое число):\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
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
        await message.answer("❌ Введите положительное целое число (например, 100).\n\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", reply_markup=profile_kb, parse_mode="HTML")
        await state.clear()
        return
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        await state.clear()
        return
    balance = user_data.get("balance", 0)
    if amount > balance:
        await message.answer(f"❌ <b>Недостаточно средств!</b>\n\nВаш баланс: <b>{balance} ⭐</b>\nЗапрошено: <b>{amount} ⭐</b>\n\nПожалуйста, введите сумму, не превышающую баланс.\nИли нажмите 'Назад' для отмены.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(withdraw_amount=amount)
    await message.answer(f"✅ Сумма <b>{amount} ⭐</b> принята.\n\nТеперь введите <b>номер карты</b> для вывода.\nДопустимые длины: <b>13</b>, <b>15</b>, <b>16</b>, <b>18</b> или <b>19</b> цифр.\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_withdraw_card)

@dp.message(ScamStates.waiting_withdraw_card)
async def process_withdraw_card(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await show_profile(message, state)
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", reply_markup=profile_kb, parse_mode="HTML")
        await state.clear()
        return
    card_number = message.text.replace(" ", "").replace("-", "")
    if not card_number.isdigit():
        await message.answer("❌ Номер карты должен содержать <b>только цифры</b>.\n\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    valid_lengths = [13, 15, 16, 18, 19]
    if len(card_number) not in valid_lengths:
        await message.answer(f"❌ Номер карты должен содержать <b>13, 15, 16, 18 или 19</b> цифр.\nВы ввели <b>{len(card_number)}</b> цифр.\n\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    if amount is None:
        await message.answer("❌ Ошибка: сумма не найдена. Начните заново.", reply_markup=profile_kb)
        await state.clear()
        return
    user_id = message.from_user.id
    user_data = users_db.get(user_id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        await state.clear()
        return
    if amount > user_data["balance"]:
        await message.answer(f"❌ Недостаточно средств! Баланс изменился.\nТекущий баланс: <b>{user_data['balance']} ⭐</b>\n\nНачните процесс вывода заново через профиль.", reply_markup=profile_kb, parse_mode="HTML")
        await state.clear()
        return
    users_db[user_id]["balance"] -= amount
    new_balance = users_db[user_id]["balance"]
    add_history_entry(user_id, -amount, "Вывод средств")
    log_action(message.from_user, f"ВЫВЕЛ {amount} ⭐ на карту {card_number[:4]}...{card_number[-4:]} (остаток {new_balance})")
    await notify_owner(message.from_user, f"💸 <b>ВЫВОД СРЕДСТВ</b>\n👤 Пользователь: {user_data['username']} (ID: {user_id})\n💰 Сумма: {amount} ⭐\n💳 Карта: {card_number[:4]}...{card_number[-4:]}\n📊 Остаток: {new_balance} ⭐", send_to_dm=True)
    commission = amount * 0.05
    await message.answer(f"✅ <b>Отлично!</b>\n\nСредства в размере <b>{amount} ⭐</b> будут зачислены на указанную карту в течение <b>2-3 недель</b>.\nКомиссия за вывод составит <b>5%</b> (это <b>{commission:.2f} ⭐</b>).\n\nВаш новый баланс: <b>{new_balance} ⭐</b>\n\nПо всем вопросам обращайтесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", reply_markup=profile_kb, parse_mode="HTML")
    await state.clear()

# ============================================
# ===== КУПИТЬ С УЧЁТОМ VIP-СКИДКИ =====
# ============================================
@dp.message(F.text == "🛒 Купить")
async def handle_buy_choice(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>\n\nВы можете приобрести любой товар без ограничений.", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.\nЕсли вы не согласны с решением, обратитесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'КУПИТЬ' → ВЫБОР")
    await message.answer("🛒 <b>Что вас интересует?</b>\n\nВыберите вариант:", reply_markup=buy_choice_kb, parse_mode="HTML")

@dp.message(F.text == "⭐ Донат")
async def handle_donate(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>\n\nВыберите товар для покупки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить БП+ за 0 ⭐ (бесконечный)", callback_data="donate_buy_бпп")],
            [InlineKeyboardButton(text="🛒 Купить БП за 0 ⭐ (бесконечный)", callback_data="donate_buy_бп")],
            [InlineKeyboardButton(text="💎 Купить гемы", callback_data="donate_gems")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="donate_back")]
        ]), parse_mode="HTML")
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", reply_markup=buy_choice_kb, parse_mode="HTML")
        return
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'ДОНАТ'")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for item in DONATE_ITEMS:
        price = item['price']
        if message.from_user.id in VIP_IDS:
            price = int(price * 0.9)
            label = f"🛒 Купить {item['name']} за {price} ⭐ (VIP скидка 10%)"
        else:
            label = f"🛒 Купить {item['name']} за {price} ⭐"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"donate_buy_{item['name'].lower().replace('+', 'p')}")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="💎 Купить гемы", callback_data="donate_gems")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="donate_back")])
    await message.answer("⭐ <b>Выберите товар для покупки:</b>\n\n💰 Покупка происходит мгновенно с вашего баланса.\nЕсли средств недостаточно, вы можете пополнить баланс через поддержку @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("donate_buy_"))
async def process_donate_buy(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    if get_infinite_balance(user.id):
        # Бесконечный баланс — покупка бесплатно
        await callback.answer("♾️ Бесконечный баланс", show_alert=True)
        item_key = callback.data.split("_")[2]
        target_item = None
        for item in DONATE_ITEMS:
            norm = item['name'].lower().replace('+', 'p').replace(' ', '')
            if norm == item_key:
                target_item = item
                break
        if target_item:
            add_history_entry(user.id, 0, f"Покупка {target_item['name']} (бесконечный баланс)")
            await callback.message.answer(f"✅ <b>Отлично!</b>\n\nВы приобрели <b>{target_item['name']}</b> (бесконечный баланс).\nСпасибо за покупку! 🎉", parse_mode="HTML")
        await callback.answer()
        return
    frozen, until, reason = is_user_frozen(user.id)
    if frozen:
        await callback.answer("❄️ Профиль заморожен", show_alert=True)
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await callback.message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", parse_mode="HTML")
        return
    item_key = callback.data.split("_")[2]
    target_item = None
    for item in DONATE_ITEMS:
        norm = item['name'].lower().replace('+', 'p').replace(' ', '')
        if norm == item_key:
            target_item = item
            break
    if not target_item:
        await callback.answer("❌ Товар не найден.", show_alert=True)
        return
    user_data = users_db.get(user.id)
    if not user_data:
        await callback.answer("❌ Вы не зарегистрированы. Нажмите /start.", show_alert=True)
        return
    price = target_item['price']
    discount = get_vip_discount(user.id)
    final_price = int(price * discount)
    balance = user_data.get('balance', 0)
    if balance < final_price:
        await callback.answer("❌ Недостаточно средств! Пополните баланс через поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", show_alert=True)
        await callback.message.answer(f"❌ <b>Недостаточно средств!</b>\n\nДля покупки <b>{target_item['name']}</b> требуется <b>{final_price} ⭐</b>, а у вас <b>{balance} ⭐</b>.\nПополните баланс через поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", parse_mode="HTML")
        await callback.answer()
        return
    users_db[user.id]["balance"] -= final_price
    new_balance = users_db[user.id]["balance"]
    add_history_entry(user.id, -final_price, f"Покупка {target_item['name']}")
    admin_text = f"⭐ <b>ПОКУПКА ДОНАТА</b>\n👤 Пользователь: {user_data['username']} (ID: {user.id})\n📛 Имя: {user_data['name']}\n🎯 Купил: {target_item['name']}\n💰 Сумма: {final_price} ⭐\n📊 Остаток: {new_balance} ⭐"
    await notify_owner(user, admin_text, send_to_dm=True)
    await callback.message.answer(f"✅ <b>Отлично!</b>\n\nВы успешно приобрели <b>{target_item['name']}</b> за {final_price} ⭐.\n📊 Новый баланс: {new_balance} ⭐\n\nСкоро с вами свяжется наш оператор.\nСпасибо за покупку! 🎉\nПо всем вопросам обращайтесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", parse_mode="HTML")
    await callback.answer("✅ Покупка успешна!")

@dp.callback_query(F.data == "donate_gems")
async def process_donate_gems(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    if get_infinite_balance(user.id):
        await callback.answer("♾️ Бесконечный баланс", show_alert=True)
        await callback.message.answer("💎 <b>Покупка гемов (бесконечный баланс)</b>\n\nВведите количество гемов, которое вы хотите купить.\nЦена: <b>1 гем = 0 ⭐</b> (бесконечный баланс)\nНапример, введите <b>10</b> для покупки 10 гемов.\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        await state.set_state(ScamStates.waiting_gems_amount)
        return
    frozen, until, reason = is_user_frozen(user.id)
    if frozen:
        await callback.answer("❄️ Профиль заморожен", show_alert=True)
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await callback.message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", parse_mode="HTML")
        return
    await callback.answer()
    await callback.message.answer("💎 <b>Покупка гемов</b>\n\nВведите количество гемов, которое вы хотите купить.\nЦена: <b>1 гем = 4.5 ⭐</b>\nНапример, введите <b>10</b> для покупки 10 гемов.\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_gems_amount)

@dp.message(ScamStates.waiting_gems_amount)
async def handle_gems_amount(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await handle_donate(message, state)
        return
    if get_infinite_balance(message.from_user.id):
        try:
            gems_count = float(message.text.replace(",", "."))
            if gems_count <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ <b>Ошибка!</b>\n\nПожалуйста, введите <b>положительное число</b> (например, 10, 50).", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
        add_history_entry(message.from_user.id, 0, f"Покупка {gems_count} гемов (бесконечный баланс)")
        await message.answer(f"✅ <b>Отлично!</b>\n\nВы успешно приобрели <b>{gems_count} гемов</b> (бесконечный баланс).\nСпасибо за покупку! 🎉", reply_markup=back_to_main_kb, parse_mode="HTML")
        await state.clear()
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    try:
        gems_count = float(message.text.replace(",", "."))
        if gems_count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ <b>Ошибка!</b>\n\nПожалуйста, введите <b>положительное число</b> (например, 10, 50).", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    stars = round(gems_count * 4.5)
    user_id = message.from_user.id
    user_data = users_db.get(user_id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        await state.clear()
        return
    discount = get_vip_discount(user_id)
    final_price = int(stars * discount)
    balance = user_data.get('balance', 0)
    if balance < final_price:
        await message.answer(f"❌ <b>Недостаточно средств!</b>\n\nДля покупки <b>{gems_count} гемов</b> требуется <b>{final_price} ⭐</b>, а у вас <b>{balance} ⭐</b>.\nПополните баланс через поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    users_db[user_id]["balance"] -= final_price
    new_balance = users_db[user_id]["balance"]
    add_history_entry(user_id, -final_price, f"Покупка гемов {gems_count}шт")
    admin_text = f"💎 <b>ПОКУПКА ГЕМОВ</b>\n👤 Пользователь: {user_data['username']} (ID: {user_id})\n📛 Имя: {user_data['name']}\n💎 Купил: {gems_count} гемов\n💰 Сумма: {final_price} ⭐\n📊 Остаток: {new_balance} ⭐"
    await notify_owner(message.from_user, admin_text, send_to_dm=True)
    await message.answer(f"✅ <b>Отлично!</b>\n\nВы успешно приобрели <b>{gems_count} гемов</b> за {final_price} ⭐.\n📊 Новый баланс: {new_balance} ⭐\n\nСкоро с вами свяжется наш оператор.\nСпасибо за покупку! 🎉\nПо всем вопросам обращайтесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "donate_back")
async def donate_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    await handle_buy_choice(callback.message, state)

@dp.message(F.text == "📱 Аккаунт")
async def handle_account_buy(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>\n\nВы можете выбрать любой лот без ограничений.", reply_markup=buy_choice_kb, parse_mode="HTML")
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", reply_markup=buy_choice_kb, parse_mode="HTML")
        return
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'АККАУНТ' → ВЫБОР ЛОТА")
    text = "🛒 <b>Выберите лот:</b>\n\n⚠️ <b>Обязательно прочтите информацию в разделе \"Как проходит сделка?\"</b>\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for idx, lot in enumerate(LOTS, start=1):
        price = lot['price']
        if message.from_user.id in VIP_IDS:
            price = int(price * 0.9)
            text += f"━━━━━━━━━━━━━━━━━━━━━\n🎯 <b>{lot['name']}</b>\n🏆 <b>{lot['cups']} кубков</b>\n💎 <b>{lot['gems']} гемов</b>\n⚔️ <b>{lot['fighters']} бойцов</b>\n💰 <b>Цена: {price} ⭐ (VIP скидка 10%)</b>\n📩 <i>по всем вопросам обращайтесь в поддержку @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.</i>\n"
        else:
            text += f"━━━━━━━━━━━━━━━━━━━━━\n🎯 <b>{lot['name']}</b>\n🏆 <b>{lot['cups']} кубков</b>\n💎 <b>{lot['gems']} гемов</b>\n⚔️ <b>{lot['fighters']} бойцов</b>\n💰 <b>Цена: {price} ⭐</b>\n📩 <i>по всем вопросам обращайтесь в поддержку @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.</i>\n"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"🛒 Купить {lot['name']}", callback_data=f"buy_lot_{idx}")])
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_lot_"))
async def process_buy_lot(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    if get_infinite_balance(user.id):
        await callback.answer("♾️ Бесконечный баланс", show_alert=True)
        lot_index = int(callback.data.split("_")[2]) - 1
        if lot_index < 0 or lot_index >= len(LOTS):
            await callback.answer("❌ Лот не найден.", show_alert=True)
            return
        lot = LOTS[lot_index]
        add_history_entry(user.id, 0, f"Покупка {lot['name']} (бесконечный баланс)")
        await callback.message.answer(f"✅ <b>Отлично!</b>\n\nВы успешно купили <b>{lot['name']}</b> (бесконечный баланс).\nПродавец напишет вам в кратчайшее время.\n\nПо всем вопросам обращайтесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", parse_mode="HTML")
        await callback.answer()
        return
    frozen, until, reason = is_user_frozen(user.id)
    if frozen:
        await callback.answer("❄️ Профиль заморожен", show_alert=True)
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await callback.message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", parse_mode="HTML")
        return
    lot_index = int(callback.data.split("_")[2]) - 1
    if lot_index < 0 or lot_index >= len(LOTS):
        await callback.answer("❌ Лот не найден.", show_alert=True)
        return
    lot = LOTS[lot_index]
    price = lot["price"]
    discount = get_vip_discount(user.id)
    final_price = int(price * discount)
    user_data = users_db.get(user.id)
    if not user_data:
        await callback.answer("❌ Вы не зарегистрированы. Нажмите /start.", show_alert=True)
        return
    balance = user_data.get("balance", 0)
    if balance < final_price:
        await callback.answer("❌ Недостаточно средств! Чтобы пополнить баланс, обратитесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", show_alert=True)
        await callback.message.answer(f"❌ <b>Недостаточно средств!</b>\n\nДля покупки лота требуется <b>{final_price} ⭐</b>, а у вас на балансе <b>{balance} ⭐</b>.\nПополните баланс через поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", parse_mode="HTML")
        await callback.answer()
        return
    users_db[user.id]["balance"] -= final_price
    new_balance = users_db[user.id]["balance"]
    add_history_entry(user.id, -final_price, f"Покупка {lot['name']}")
    admin_text = f"🛒 <b>ПОКУПКА ЛОТА</b>\n👤 Пользователь: {user_data['username']} (ID: {user.id})\n📛 Имя: {user_data['name']}\n🎯 Купил лот: {lot['name']}\n💰 Сумма: {final_price} ⭐\n📊 Остаток: {new_balance} ⭐"
    await notify_owner(user, admin_text, send_to_dm=True)
    await callback.message.answer(f"✅ <b>Отлично!</b>\n\nВы успешно купили <b>{lot['name']}</b> за {final_price} ⭐.\nПродавец напишет вам в кратчайшее время.\n\n📊 Новый баланс: {new_balance} ⭐\nПо всем вопросам обращайтесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", parse_mode="HTML")
    await callback.answer("✅ Покупка успешна!")

# ============================================
# ===== ЗАРАБОТОК =====
# ============================================
@dp.message(F.text == "💸 Заработать деньги")
async def handle_earn_money(message: Message, state: FSMContext):
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'ЗАРАБОТАТЬ ДЕНЬГИ'")
    await message.answer("💰 <b>Зарабатывайте деньги с нами!</b>\n\nВ нашем боте вы можете заработать <b>до 1000 рублей в день</b>!\n\n🔥 Для этого вам всего лишь надо зайти в <b>TikTok</b> и писать такой текст в комментариях под разными видео:\n\n📌 <b>Текст для копирования:</b>\n<code>@skup_bs_bot лучший бот для продажи своего аккаунта Brawl Stars</code>\n\n📊 <b>Условия оплаты:</b>\n✅ <b>1 комментарий = 5 рублей</b>\n✅ <b>200 комментариев = 1000 рублей</b>\n\n⚠️ <b>ВАЖНО!</b>\nДля выплаты предоставьте <b>скриншоты комментариев</b>.\nБез них выплата <b>НЕ БУДЕТ</b> произведена!\n\n💬 Для выплаты обращайтесь сюда:\n👤 <b>@suport_skup_bs_bot</b>\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.\n\n🎯 Желаем удачи! 💪", reply_markup=back_to_main_kb, parse_mode="HTML")

# ============================================
# ===== РАБОТА =====
# ============================================
@dp.message(F.text == "👷 Работа")
async def handle_work_start(message: Message, state: FSMContext):
    if message.from_user.id not in WORKER_IDS:
        await message.answer("⛔ У вас нет доступа к этой функции.")
        return
    if message.from_user.id in user_tasks:
        task = user_tasks[message.from_user.id]
        time_left = 24 - (get_moscow_datetime() - task["start_time"]).seconds // 3600
        await message.answer(f"⏳ У вас уже есть активное задание!\nОсталось отправить: {task['comments'] - task['submitted']} скринов.\nОсталось времени: {time_left} ч.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await message.answer("👷 <b>Готовы начать новый слот?</b>\n\n💬 Вы готовы начать сегодня новый слот?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Да", callback_data="worker_start_yes")]]), parse_mode="HTML")

@dp.callback_query(F.data == "worker_start_yes")
async def worker_start_yes(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in WORKER_IDS:
        await callback.answer("⛔ У вас нет доступа к этой функции.", show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer("✍️ <b>Сколько комментариев вы готовы сегодня написать?</b>\n\n📊 Курс: <b>1 комментарий = 5 рублей</b>\n⚠️ Максимальное количество: <b>500</b>\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.worker_task_comments)

@dp.message(ScamStates.worker_task_comments)
async def worker_comments_input(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await state.set_state(ScamStates.main_menu)
        if message.from_user.id == OWNER_USERNAME:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=owner_menu_kb, parse_mode="HTML")
        elif message.from_user.id in ADMIN_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
        elif message.from_user.id in MODERATOR_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=moderator_menu_kb, parse_mode="HTML")
        elif message.from_user.id in WORKER_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=worker_menu_kb, parse_mode="HTML")
        else:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    try:
        comments = int(message.text.strip())
        if comments <= 0:
            raise ValueError
        if comments > 500:
            await message.answer("❌ <b>Ошибка!</b>\n\nМаксимальное количество комментариев — <b>500</b>.\nПожалуйста, введите меньшее число.", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
    except ValueError:
        await message.answer("❌ <b>Ошибка!</b>\n\nПожалуйста, введите <b>целое число</b> (например, 50, 100).", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    reward = comments * 5
    await state.update_data(worker_comments=comments, worker_reward=reward)
    await message.answer(f"✅ <b>Отлично!</b>\n\n💬 Комментариев: <b>{comments}</b>\n💰 Вы получите: <b>{reward} ⭐</b>\n\n❓ Вы согласны?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Да", callback_data="worker_confirm_yes")]]), parse_mode="HTML")
    await state.set_state(ScamStates.worker_task_confirm)

@dp.callback_query(F.data == "worker_confirm_yes")
async def worker_confirm_yes(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in WORKER_IDS:
        await callback.answer("⛔ У вас нет доступа к этой функции.", show_alert=True)
        return
    data = await state.get_data()
    comments = data.get("worker_comments")
    reward = data.get("worker_reward")
    if not comments:
        await callback.answer("❌ Ошибка! Попробуйте начать заново.", show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()
    user_tasks[callback.from_user.id] = {"comments": comments, "submitted": 0, "start_time": get_moscow_datetime(), "screens": [], "reward": reward, "file_hashes": []}
    await callback.message.answer(f"✅ <b>Отлично! Принимайтесь за работу!</b>\n\n📌 <b>Текст для копирования:</b>\n<code>skup_bs_ лучший бот для покупки доната или продажи аккаунта Brawl Stars</code>\n\n📊 <b>Ждем от вас {comments} скринов</b> отправленных комментариев.\n\n⏳ <b>У вас есть 24 часа</b> на выполнение задания.\nВы можете отправлять скрины частями.\n\n⚠️ <b>Предупреждение!</b>\nПри отправке одинаковых скринов или невыполнении за 24 часа — \nс вашего баланса будет списано <b>{reward} ⭐</b>\n\n🔄 Для отправки скринов просто пришлите их в этот чат.\nНачинаем! 🚀", parse_mode="HTML")
    await state.clear()
    await state.set_state(ScamStates.worker_task_working)

@dp.message(ScamStates.worker_task_working, F.photo)
async def worker_photo_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    task = user_tasks.get(user_id)
    if not task:
        await message.answer("⚠️ У вас нет активного задания. Напишите /start для начала.")
        await state.clear()
        return
    elapsed = (get_moscow_datetime() - task["start_time"]).total_seconds()
    if elapsed > 24 * 3600:
        reward = task["reward"]
        users_db[user_id]["balance"] -= reward
        add_history_entry(user_id, -reward, f"Штраф за невыполнение задания (-{reward} ⭐)")
        await message.answer(f"❌ <b>Время вышло!</b>\n\nВы не успели отправить все {task['comments']} скринов.\nС вашего баланса списано <b>{reward} ⭐</b> (штраф).\nТекущий баланс: {users_db[user_id]['balance']} ⭐", parse_mode="HTML")
        del user_tasks[user_id]
        await state.clear()
        return
    photo_hash = get_photo_hash(message.photo[-1])
    if photo_hash in task["file_hashes"]:
        await message.answer("⚠️ <b>Этот скрин уже был отправлен!</b>\n\nПожалуйста, отправляйте только уникальные скрины.", parse_mode="HTML")
        return
    task["file_hashes"].append(photo_hash)
    task["submitted"] += 1
    remaining = task["comments"] - task["submitted"]
    time_left = 24 - (elapsed // 3600)
    if remaining > 0:
        await message.answer(f"✅ <b>Отлично! Вы отправили {task['submitted']} скринов.</b>\n\n📊 Осталось: <b>{remaining}</b> скринов.\n⏳ Оставшееся время: <b>{int(time_left)} ч.</b>", parse_mode="HTML")
    else:
        reward = task["reward"]
        users_db[user_id]["balance"] += reward
        add_history_entry(user_id, reward, f"Заработок за комментарии (+{reward} ⭐)")
        await message.answer(f"✅ <b>Отлично! Вы выполнили задание!</b>\n\n💰 Вам начислено <b>{reward} ⭐</b>\n📊 Текущий баланс: {users_db[user_id]['balance']} ⭐\n\n🎉 Спасибо за работу!", parse_mode="HTML")
        del user_tasks[user_id]
        await state.clear()

# ============================================
# ===== ПОДДЕРЖКА =====
# ============================================
@dp.message(F.text == "❓ Поддержка")
async def handle_help(message: Message, state: FSMContext):
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'ПОДДЕРЖКА'")
    await message.answer("📩 <b>Поддержка</b>\n\nНапишите ваш вопрос или проблему одним сообщением.\nНаш оператор обязательно ответит вам в ближайшее время.\n\nВы также можете написать нам вручную: @suport_skup_bs_bot\n\n✍️ Введите текст сообщения:", reply_markup=support_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_support)

@dp.message(ScamStates.waiting_support)
async def handle_support_message(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await state.set_state(ScamStates.main_menu)
        if message.from_user.id == OWNER_USERNAME:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=owner_menu_kb, parse_mode="HTML")
        elif message.from_user.id in ADMIN_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
        elif message.from_user.id in MODERATOR_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=moderator_menu_kb, parse_mode="HTML")
        elif message.from_user.id in WORKER_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=worker_menu_kb, parse_mode="HTML")
        else:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    user = message.from_user
    user_username = f"@{user.username}" if user.username else "без юзернейма"
    user_fullname = user.full_name or "без имени"
    user_id = user.id
    admin_text = f"📩 <b>Сообщение от пользователя</b>\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Юзернейм:</b> {user_username}\n📛 <b>Имя:</b> {user_fullname}\n🆔 <b>ID:</b> <code>{user_id}</code>\n━━━━━━━━━━━━━━━━━━━\n\n<b>Текст сообщения:</b>\n{message.text}"
    await notify_owner(user, f"ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ: {message.text[:50]}...")
    try:
        await bot.send_message(OWNER_USERNAME, admin_text, parse_mode="HTML")
        if OWNER_USERNAME in SUPPORT_IDS or message.from_user.id in SUPPORT_IDS:
            for sup_id in SUPPORT_IDS:
                try:
                    await bot.send_message(sup_id, admin_text, parse_mode="HTML")
                except:
                    pass
        await message.answer("✅ <b>Ваше сообщение отправлено!</b>\n\nНаш оператор свяжется с вами в ближайшее время.\nСпасибо за обращение! 🙌", reply_markup=main_menu_kb, parse_mode="HTML")
        await state.clear()
        await state.set_state(ScamStates.main_menu)
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при отправке сообщения. Попробуйте позже или напишите напрямую @suport_skup_bs_bot.\n\nОшибка: {e}", reply_markup=support_kb, parse_mode="HTML")

# ============================================
# ===== МОДЕРАТОР: НАПИСАТЬ ПИСЬМО =====
# ============================================
@dp.message(F.text == "📩 Написать письмо")
async def moderator_write_letter(message: Message, state: FSMContext):
    if message.from_user.id not in MODERATOR_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("✍️ <b>Напишите текст письма</b>, которое будет отправлено пользователю.\n\nВведите ID или @юзернейм получателя и текст через пробел.\nПример: <code>123456789 Здравствуйте, ваш аккаунт был разморожен.</code>\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_msg_user)

@dp.message(F.text == "📋 Обращения")
async def moderator_view_appeals(message: Message, state: FSMContext):
    if message.from_user.id not in MODERATOR_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if not actions_log:
        await message.answer("📋 <b>Обращения</b>\n\nПока нет обращений в поддержку.", reply_markup=moderator_menu_kb, parse_mode="HTML")
        return
    text = "📋 <b>Последние обращения в поддержку:</b>\n\n"
    for entry in actions_log[-10:]:
        if "ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ" in entry:
            text += f"• {entry}\n"
    await message.answer(text, reply_markup=moderator_menu_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН-ПАНЕЛЬ =====
# ============================================
@dp.message(F.text == "👑 Админ-панель")
async def admin_panel_request(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("🔐 <b>Введите пароль для доступа к админ-панели:</b>\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_admin_password)

@dp.message(ScamStates.waiting_admin_password)
async def admin_password_check(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await state.clear()
        await state.set_state(ScamStates.main_menu)
        if message.from_user.id == OWNER_USERNAME:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=owner_menu_kb, parse_mode="HTML")
        elif message.from_user.id in ADMIN_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
        elif message.from_user.id in MODERATOR_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=moderator_menu_kb, parse_mode="HTML")
        else:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    if message.text == ADMIN_PASSWORD:
        await message.answer("✅ <b>Пароль верный!</b>\n\n👑 <b>Админ-панель</b>\n\nВыберите действие:", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer("❌ <b>Неверный пароль!</b>\n\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    total_users = len(users_db)
    total_actions = len(actions_log)
    await message.answer(f"📊 <b>Статистика</b>\n\n👥 Всего пользователей: <b>{total_users}</b>\n📋 Всего действий: <b>{total_actions}</b>\n\n🔄 Функция в разработке.", reply_markup=admin_menu_kb, parse_mode="HTML")

@dp.message(F.text == "👥 Пользователи")
async def admin_users(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if not users_db:
        await message.answer("👥 <b>Пользователи</b>\n\nПока ни одного пользователя.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    text = "👥 <b>Список пользователей:</b>\n\n"
    for idx, (uid, data) in enumerate(users_db.items(), 1):
        frozen_str = "❄️ Заморожен" if data.get("frozen_until") is not None else "✅ Активен"
        if data.get("frozen_until") == "forever":
            frozen_until_str = "навсегда"
        elif isinstance(data.get("frozen_until"), datetime):
            frozen_until_str = data["frozen_until"].strftime("%d.%m.%Y %H:%M")
        else:
            frozen_until_str = "нет"
        text += f"{idx}. <b>ID:</b> <code>{uid}</code>\n   📛 {data['name']}\n   🔖 {data['username']}\n   💰 Баланс: {data.get('balance', 0)} ⭐\n   ❄️ Статус: {frozen_str}\n   ⏰ До: {frozen_until_str}\n   🕒 Первый визит: {data['first_seen']}\n   🕒 Последний визит: {data['last_seen']}\n\n"
        if idx >= 20:
            text += f"... и ещё {len(users_db) - 20} пользователей.\n"
            break
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

@dp.message(F.text == "📋 Действия")
async def admin_actions(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if not actions_log:
        await message.answer("📋 <b>Действия</b>\n\nПока нет действий.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    log_entries = actions_log[-20:]
    text = "📋 <b>Последние действия:</b>\n\n"
    for entry in log_entries:
        text += f"• {entry}\n"
    if len(actions_log) > 20:
        text += f"\n... и ещё {len(actions_log) - 20} действий."
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН-ПОПОЛНЕНИЕ =====
# ============================================
async def admin_balance_start(message: Message, state: FSMContext):
    await message.answer("💰 <b>Пополнение или списание баланса</b>\n\nВведите <b>ID или @юзернейм</b> пользователя.\nПримеры: `123456789` или `@username`\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_balance_user)

@dp.message(ScamStates.admin_balance_user)
async def admin_balance_user_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    target_user = None
    text = message.text.strip()
    if text.startswith('@'):
        username = text[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                target_user = uid
                break
    else:
        try:
            uid = int(text)
            if uid in users_db:
                target_user = uid
        except ValueError:
            pass
    if target_user is None:
        await message.answer("❌ Пользователь не найден. Проверьте ID или юзернейм.\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(target_user=target_user)
    await message.answer(f"✅ Найден пользователь: {users_db[target_user]['name']} ({users_db[target_user]['username']})\nТекущий баланс: {users_db[target_user]['balance']} ⭐\n\nВведите <b>сумму изменения</b> (целое число):\n➕ положительное — пополнение\n➖ отрицательное — списание\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_balance_amount)

@dp.message(ScamStates.admin_balance_amount)
async def admin_balance_amount_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    try:
        amount = int(message.text.strip())
        if amount == 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число (положительное для пополнения, отрицательное для списания), не равное нулю.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    data = await state.get_data()
    target_user = data.get("target_user")
    if target_user is None or target_user not in users_db:
        await message.answer("❌ Ошибка: пользователь не найден. Начните заново.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    if message.from_user.id == OWNER_USERNAME:
        current_balance = users_db[target_user]["balance"]
        if amount < 0 and abs(amount) > current_balance:
            await message.answer(f"❌ Недостаточно средств! Текущий баланс пользователя: {current_balance} ⭐.\nСписание на {abs(amount)} ⭐ невозможно.", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
        users_db[target_user]["balance"] += amount
        new_balance = users_db[target_user]["balance"]
        if amount > 0:
            add_history_entry(target_user, amount, "Пополнение")
        else:
            add_history_entry(target_user, amount, f"Списание ({abs(amount)} ⭐)")
        log_action(message.from_user, f"ПОПОЛНИЛ/СПИСАЛ БАЛАНС пользователя {users_db[target_user]['username']} (ID {target_user}) на {amount} ⭐")
        await notify_owner(message.from_user, f"💰 Баланс изменён на {amount} ⭐", send_to_dm=True)
        await message.answer(f"✅ Баланс пользователя {users_db[target_user]['name']} изменён на {amount} ⭐.\nНовый баланс: {new_balance} ⭐.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer("⏳ <b>Ожидайте разрешения от владельца!</b>\n\nЗапрос на пополнение баланса отправлен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-ЗАМОРОЗКА =====
# ============================================
@dp.message(F.text == "❄️ Заморозить профиль")
async def admin_freeze_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("❄️ <b>Заморозка профиля</b>\n\nВведите <b>ID или @юзернейм</b> пользователя.\nПримеры: `123456789` или `@username`\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_freeze_user)

@dp.message(ScamStates.admin_freeze_user)
async def admin_freeze_user_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    target_user = None
    text = message.text.strip()
    if text.startswith('@'):
        username = text[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                target_user = uid
                break
    else:
        try:
            uid = int(text)
            if uid in users_db:
                target_user = uid
        except ValueError:
            pass
    if target_user is None:
        await message.answer("❌ Пользователь не найден. Проверьте ID или юзернейм.\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(freeze_target=target_user)
    await message.answer(f"✅ Найден пользователь: {users_db[target_user]['name']} ({users_db[target_user]['username']})\n\nВведите <b>дату окончания заморозки</b> в формате:\n<b>ДД.ММ.ГГГГ ЧЧ:ММ</b> (по московскому времени)\nили <b>0</b> для бессрочной заморозки.\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_freeze_date)

@dp.message(ScamStates.admin_freeze_date)
async def admin_freeze_date_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    text = message.text.strip()
    if text == "0":
        frozen_until = "forever"
    else:
        try:
            parts = text.split()
            if len(parts) != 2:
                raise ValueError
            date_part, time_part = parts
            day, month, year = map(int, date_part.split('.'))
            hour, minute = map(int, time_part.split(':'))
            end_dt = get_moscow_datetime().replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
            if end_dt < get_moscow_datetime():
                await message.answer("❌ Указанная дата уже прошла! Введите будущую дату или 0 для бессрочной.", reply_markup=back_to_main_kb, parse_mode="HTML")
                return
            frozen_until = end_dt
        except:
            await message.answer("❌ Неверный формат! Введите дату в формате <b>ДД.ММ.ГГГГ ЧЧ:ММ</b> или <b>0</b> для бессрочной.", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
    await state.update_data(freeze_until=frozen_until)
    await message.answer("❄️ <b>Шаг 3: Причина заморозки</b>\n\nВведите <b>причину</b> заморозки (текст).\nПользователь увидит эту причину в уведомлении.\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_freeze_reason)

@dp.message(ScamStates.admin_freeze_reason)
async def admin_freeze_reason_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    reason = message.text.strip()
    if not reason:
        await message.answer("❌ Причина не может быть пустой.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    data = await state.get_data()
    target_user = data.get("freeze_target")
    frozen_until = data.get("freeze_until")
    if target_user is None or target_user not in users_db:
        await message.answer("❌ Ошибка: пользователь не найден. Начните заново.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    user_data = users_db[target_user]
    if message.from_user.id == OWNER_USERNAME:
        user_data["frozen_until"] = frozen_until
        user_data["frozen_reason"] = reason
        if frozen_until == "forever":
            until_str = "НАВСЕГДА"
            msg_user = f"❄️ <b>Ваш профиль заморожен НАВСЕГДА!</b>"
        else:
            until_str = frozen_until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
            msg_user = f"❄️ <b>Ваш профиль заморожен до {until_str}</b>"
        user_msg = f"{msg_user}\n\n📌 <b>Причина:</b> {reason}\n\nЕсли вы не согласны с решением, обратитесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота."
        try:
            await bot.send_message(target_user, user_msg, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"⚠️ Не удалось отправить уведомление пользователю: {e}")
        log_action(message.from_user, f"ЗАМОРОЗИЛ ПРОФИЛЬ пользователя {user_data['username']} (ID {target_user}) до {until_str} по причине: {reason}")
        await notify_owner(message.from_user, f"❄️ Заморожен профиль {user_data['username']} до {until_str}", send_to_dm=True)
        await message.answer(f"✅ <b>Профиль пользователя {user_data['name']} заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nУведомление отправлено пользователю.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.clear()
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer("⏳ <b>Ожидайте разрешения от владельца!</b>\n\nЗапрос на заморозку отправлен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-РАЗМОРОЗКА =====
# ============================================
@dp.message(F.text == "🔄 Разморозить профиль")
async def admin_unfreeze_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("🔄 <b>Разморозка профиля</b>\n\nВведите <b>ID или @юзернейм</b> пользователя.\nПримеры: `123456789` или `@username`\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_unfreeze_user)

@dp.message(ScamStates.admin_unfreeze_user)
async def admin_unfreeze_user_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    target_user = None
    text = message.text.strip()
    if text.startswith('@'):
        username = text[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                target_user = uid
                break
    else:
        try:
            uid = int(text)
            if uid in users_db:
                target_user = uid
        except ValueError:
            pass
    if target_user is None:
        await message.answer("❌ Пользователь не найден. Проверьте ID или юзернейм.\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    user_data = users_db[target_user]
    if user_data.get("frozen_until") is None:
        await message.answer("ℹ️ Профиль пользователя уже активен (не заморожен).", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
        return
    if message.from_user.id == OWNER_USERNAME:
        user_data["frozen_until"] = None
        user_data["frozen_reason"] = None
        try:
            await bot.send_message(target_user, "✅ <b>Ваш профиль разморожен!</b>\n\nТеперь вам доступны все функции бота.\nСпасибо, что с нами! 🎉", parse_mode="HTML")
        except Exception as e:
            await message.answer(f"⚠️ Не удалось отправить уведомление пользователю: {e}")
        log_action(message.from_user, f"РАЗМОРОЗИЛ ПРОФИЛЬ пользователя {user_data['username']} (ID {target_user})")
        await notify_owner(message.from_user, f"🔄 Разморожен профиль {user_data['username']}", send_to_dm=True)
        await message.answer(f"✅ <b>Профиль пользователя {user_data['name']} разморожен!</b>\n\nУведомление отправлено пользователю.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.clear()
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer("⏳ <b>Ожидайте разрешения от владельца!</b>\n\nЗапрос на разморозку отправлен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-ОТПРАВКА СООБЩЕНИЯ =====
# ============================================
@dp.message(F.text == "✉️ Отправить сообщение")
async def admin_send_message_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("✉️ <b>Отправка сообщения пользователю</b>\n\nВведите <b>ID или @юзернейм</b> пользователя, которому хотите отправить сообщение.\nПримеры: `123456789` или `@username`\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_msg_user)

@dp.message(ScamStates.admin_msg_user)
async def admin_msg_user_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    target_user = None
    text = message.text.strip()
    if text.startswith('@'):
        username = text[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                target_user = uid
                break
    else:
        try:
            uid = int(text)
            if uid in users_db:
                target_user = uid
        except ValueError:
            pass
    if target_user is None:
        await message.answer("❌ Пользователь не найден. Проверьте ID или юзернейм.\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(target_user=target_user)
    await message.answer(f"✅ Найден пользователь: {users_db[target_user]['name']} ({users_db[target_user]['username']})\n\n✉️ Введите <b>текст сообщения</b>, которое будет отправлено пользователю:\n(Можно использовать обычный текст, смайлики и HTML-форматирование)\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_msg_text)

@dp.message(ScamStates.admin_msg_text)
async def admin_msg_text_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    data = await state.get_data()
    target_user = data.get("target_user")
    if target_user is None or target_user not in users_db:
        await message.answer("❌ Ошибка: пользователь не найден. Начните заново.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    msg_text = message.text
    admin_user = message.from_user
    log_action(admin_user, f"ОТПРАВИЛ СООБЩЕНИЕ пользователю {users_db[target_user]['username']} (ID {target_user}): {msg_text[:50]}...")
    try:
        await bot.send_message(target_user, f"📩 <b>Сообщение от поддержки</b>\n\n{msg_text}", parse_mode="HTML")
        await message.answer(f"✅ Сообщение успешно отправлено пользователю {users_db[target_user]['name']}.", reply_markup=admin_menu_kb, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение пользователю: {e}", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-НАЗНАЧЕНИЕ СТАТУСА =====
# ============================================
@dp.message(F.text == "👑 Назначить статус")
async def admin_assign_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME:
        await message.answer("⛔ Только для владельца.")
        return
    await message.answer("👑 <b>Назначение статуса</b>\n\nВведите <b>ID или @юзернейм</b> пользователя:\nПримеры: `123456789` или `@username`\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_assign_user)

@dp.message(ScamStates.admin_assign_user)
async def admin_assign_user_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME:
        await message.answer("⛔ Только для владельца.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    target_user = None
    text = message.text.strip()
    if text.startswith('@'):
        username = text[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                target_user = uid
                break
    else:
        try:
            uid = int(text)
            if uid in users_db:
                target_user = uid
        except ValueError:
            pass
    if target_user is None:
        await message.answer("❌ Пользователь не найден. Проверьте ID или юзернейм.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(assign_target=target_user)
    user_data = users_db[target_user]
    role, emoji = get_user_role(target_user)
    await message.answer(f"✅ Найден пользователь: {user_data['name']} ({user_data['username']})\n🎖️ Текущая роль: {emoji} {role}\n\nВыберите новую роль:\n👑 Владелец (недоступен)\n🛡️ Админ\n🛠️ Модератор\n🎧 Поддержка\n🧪 Тестер\n💎 VIP\n👷 Работник\n👤 Пользователь\n\nВведите название роли (например, VIP, Работник):\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_assign_status)

@dp.message(ScamStates.admin_assign_status)
async def admin_assign_status_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME:
        await message.answer("⛔ Только для владельца.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    role_map = {
        "админ": "admin",
        "модератор": "moderator",
        "поддержка": "support",
        "тестер": "tester",
        "вип": "vip",
        "vip": "vip",
        "работник": "worker",
        "пользователь": "user"
    }
    role = role_map.get(message.text.strip().lower())
    if not role:
        await message.answer("❌ Неверная роль. Доступные роли: Админ, Модератор, Поддержка, Тестер, VIP, Работник, Пользователь.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    data = await state.get_data()
    target_user = data.get("assign_target")
    if target_user is None or target_user not in users_db:
        await message.answer("❌ Ошибка: пользователь не найден.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    if target_user in ADMIN_IDS:
        ADMIN_IDS.remove(target_user)
    if target_user in MODERATOR_IDS:
        MODERATOR_IDS.remove(target_user)
    if target_user in SUPPORT_IDS:
        SUPPORT_IDS.remove(target_user)
    if target_user in TESTER_IDS:
        TESTER_IDS.remove(target_user)
    if target_user in VIP_IDS:
        VIP_IDS.remove(target_user)
    if target_user in WORKER_IDS:
        WORKER_IDS.remove(target_user)
    role_name = {
        "admin": "Админ",
        "moderator": "Модератор",
        "support": "Поддержка",
        "tester": "Тестер",
        "vip": "VIP",
        "worker": "Работник",
        "user": "Пользователь"
    }.get(role, "Пользователь")
    if role == "admin":
        ADMIN_IDS.append(target_user)
    elif role == "moderator":
        MODERATOR_IDS.append(target_user)
    elif role == "support":
        SUPPORT_IDS.append(target_user)
    elif role == "tester":
        TESTER_IDS.append(target_user)
    elif role == "vip":
        VIP_IDS.append(target_user)
    elif role == "worker":
        WORKER_IDS.append(target_user)
    user_data = users_db[target_user]
    new_role, emoji = get_user_role(target_user)
    await message.answer(f"✅ <b>Роль пользователя изменена!</b>\n\n👤 Пользователь: {user_data['name']} ({user_data['username']})\n🎖️ Новая роль: {emoji} {new_role}", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-СОЗДАНИЕ НОВОГО ЛОТА =====
# ============================================
@dp.message(F.text == "➕ Создать новый лот")
async def create_new_lot_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("➕ <b>Создание нового лота</b>\n\nВведите <b>номер</b> лота (целое число).\nНапример: <code>8</code>\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_new_lot_number)

@dp.message(ScamStates.waiting_new_lot_number)
async def process_new_lot_number(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    try:
        number = int(message.text.strip())
        if number <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число (например, 8).\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(new_lot_number=number)
    await message.answer(f"✅ Номер лота: <b>{number}</b>\n\nВведите <b>количество кубков</b> (можно с буквой 'к', например, 86к).\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_new_lot_cups)

@dp.message(ScamStates.waiting_new_lot_cups)
async def process_new_lot_cups(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    cups = message.text.strip()
    if not cups:
        await message.answer("❌ Количество кубков не может быть пустым.\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(new_lot_cups=cups)
    await message.answer(f"✅ Кубков: <b>{cups}</b>\n\nВведите <b>количество бойцов</b> (целое число).\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_new_lot_fighters)

@dp.message(ScamStates.waiting_new_lot_fighters)
async def process_new_lot_fighters(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    try:
        fighters = int(message.text.strip())
        if fighters <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число (количество бойцов).\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(new_lot_fighters=fighters)
    await message.answer(f"✅ Бойцов: <b>{fighters}</b>\n\nВведите <b>количество гемов</b> (целое число).\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_new_lot_gems)

@dp.message(ScamStates.waiting_new_lot_gems)
async def process_new_lot_gems(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    try:
        gems = int(message.text.strip())
        if gems < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите неотрицательное целое число (количество гемов).\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(new_lot_gems=gems)
    await message.answer(f"✅ Гемов: <b>{gems}</b>\n\nВведите <b>цену</b> в звёздах (целое число).\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_new_lot_price)

@dp.message(ScamStates.waiting_new_lot_price)
async def process_new_lot_price(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число (цену в звёздах).\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    data = await state.get_data()
    number = data.get("new_lot_number")
    cups = data.get("new_lot_cups")
    fighters = data.get("new_lot_fighters")
    gems = data.get("new_lot_gems")
    lot_name = f"Лот {number}"
    existing = None
    for idx, lot in enumerate(LOTS):
        if lot.get("name") == lot_name:
            existing = idx
            break
    new_lot = {"name": lot_name, "cups": cups, "gems": gems, "fighters": fighters, "price": price}
    if existing is not None:
        LOTS[existing] = new_lot
        msg = f"🔄 <b>Лот {number} обновлён!</b>"
    else:
        LOTS.append(new_lot)
        msg = f"✅ <b>Лот {number} создан!</b>"
    log_action(message.from_user, f"СОЗДАЛ/ОБНОВИЛ ЛОТ {lot_name}: кубки={cups}, бойцы={fighters}, гемы={gems}, цена={price}")
    await notify_owner(message.from_user, f"➕ Создан/обновлён лот {lot_name}", send_to_dm=True)
    await message.answer(f"{msg}\n\n📌 <b>Данные лота:</b>\n🏆 Кубков: {cups}\n⚔️ Бойцов: {fighters}\n💎 Гемов: {gems}\n💰 Цена: {price} ⭐\n\nЛот добавлен в раздел «Аккаунт».", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.clear()
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-ТЕХПЕРЕРЫВ =====
# ============================================
@dp.message(F.text == "🛠 Включить перерыв")
async def enable_tech_break(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if tech_break_enabled:
        end_dt = tech_break_end
        end_str = end_dt.strftime("%d.%m.%Y %H:%M") if end_dt else "неизвестно"
        await message.answer(f"⚠️ Технический перерыв уже включён до **{end_str}**.\nЕсли хотите изменить время, сначала отключите текущий перерыв.", parse_mode="HTML")
        return
    await message.answer("🛠️ <b>Включение технического перерыва – шаг 1</b>\n\nВведите дату и время окончания перерыва в формате:\n<b>ДД.ММ.ГГГГ ЧЧ:ММ</b> (по московскому времени).\n\nНапример: <code>15.08.2026 20:00</code>\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_tech_break_time)

@dp.message(ScamStates.waiting_tech_break_time)
async def process_tech_break_time(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError
        date_part, time_part = parts
        day, month, year = map(int, date_part.split('.'))
        hour, minute = map(int, time_part.split(':'))
        if not (1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2100):
            raise ValueError
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        end_dt = get_moscow_datetime().replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except:
        await message.answer("❌ Неверный формат! Введите дату и время в формате <b>ДД.ММ.ГГГГ ЧЧ:ММ</b>.\nНапример: <code>15.08.2026 20:00</code>\n\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    now = get_moscow_datetime()
    if end_dt <= now:
        await message.answer("❌ Указанное время уже прошло! Пожалуйста, введите <b>будущую</b> дату и время.\n\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(tech_break_end=end_dt)
    await message.answer("🛠️ <b>Включение технического перерыва – шаг 2</b>\n\nВведите <b>причину</b> перерыва (текст).\nНапример: «Обновление серверов»\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_tech_break_reason)

@dp.message(ScamStates.waiting_tech_break_reason)
async def process_tech_break_reason(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    reason = message.text.strip()
    if not reason:
        await message.answer("❌ Причина не может быть пустой. Введите текст причины.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    data = await state.get_data()
    end_dt = data.get("tech_break_end")
    if end_dt is None:
        await message.answer("❌ Ошибка: время не найдено. Начните заново.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    global tech_break_end, tech_break_enabled, tech_break_reason
    if message.from_user.id == OWNER_USERNAME:
        tech_break_end = end_dt
        tech_break_reason = reason
        tech_break_enabled = True
        end_str = end_dt.strftime("%d.%m.%Y %H:%M")
        await message.answer(f"✅ <b>Технический перерыв включён!</b>\n\n🛠️ Бот будет недоступен до <b>{end_str}</b> (по московскому времени).\n📌 <b>Причина:</b> {reason}\n\nℹ️ Пользователи будут видеть это сообщение.\n\nВы можете отключить перерыв раньше через кнопку «⛔ Отключить перерыв».", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer("⏳ <b>Ожидайте разрешения от владельца!</b>\n\nЗапрос на включение техперерыва отправлен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)

@dp.message(F.text == "⛔ Отключить перерыв")
async def disable_tech_break(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    global tech_break_enabled, tech_break_end, tech_break_reason
    if not tech_break_enabled:
        await message.answer("ℹ️ Технический перерыв в данный момент не активен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    if message.from_user.id == OWNER_USERNAME:
        tech_break_enabled = False
        tech_break_end = None
        tech_break_reason = ""
        await message.answer("✅ <b>Технический перерыв отключён!</b>\n\n🔄 Бот снова работает в штатном режиме.", reply_markup=admin_menu_kb, parse_mode="HTML")
    else:
        await message.answer("⏳ <b>Ожидайте разрешения от владельца!</b>\n\nЗапрос на отключение техперерыва отправлен.", reply_markup=admin_menu_kb, parse_mode="HTML")

# ============================================
# ===== НАЗАД И ОБРАБОТКА НЕИЗВЕСТНЫХ =====
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
        ScamStates.waiting_tech_break_time,
        ScamStates.waiting_tech_break_reason,
        ScamStates.waiting_new_lot_number,
        ScamStates.waiting_new_lot_cups,
        ScamStates.waiting_new_lot_fighters,
        ScamStates.waiting_new_lot_gems,
        ScamStates.waiting_new_lot_price,
        ScamStates.admin_freeze_user,
        ScamStates.admin_freeze_date,
        ScamStates.admin_freeze_reason,
        ScamStates.admin_unfreeze_user,
        ScamStates.admin_assign_user,
        ScamStates.admin_assign_status,
    ]
    if current_state in admin_states:
        await admin_panel_request(message, state)
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
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=owner_menu_kb, parse_mode="HTML")
        elif message.from_user.id in ADMIN_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
        elif message.from_user.id in MODERATOR_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=moderator_menu_kb, parse_mode="HTML")
        elif message.from_user.id in WORKER_IDS:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=worker_menu_kb, parse_mode="HTML")
        else:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    await state.clear()
    await state.set_state(ScamStates.main_menu)
    if message.from_user.id == OWNER_USERNAME:
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=owner_menu_kb, parse_mode="HTML")
    elif message.from_user.id in ADMIN_IDS:
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
    elif message.from_user.id in MODERATOR_IDS:
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=moderator_menu_kb, parse_mode="HTML")
    elif message.from_user.id in WORKER_IDS:
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=worker_menu_kb, parse_mode="HTML")
    else:
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=main_menu_kb, parse_mode="HTML")

@dp.message()
async def catch_all_messages(message: Message, state: FSMContext):
    text_preview = message.text[:50] if message.text else "[НЕ ТЕКСТ]"
    await notify_owner(message.from_user, f"НАПИСАЛ: {text_preview}")
    current_state = await state.get_state()
    if current_state == ScamStates.waiting_gems_amount:
        await message.answer("💎 <b>Пожалуйста, введите число</b> — количество гемов.\n\nНапример: 10, 50, 100.\n\n🔙 Чтобы вернуться в меню доната — нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    elif current_state == ScamStates.waiting_support:
        await message.answer("📩 Пожалуйста, отправьте <b>текстовое сообщение</b> с вашим вопросом.\n\n🔙 Или нажмите 'Назад' для отмены.", reply_markup=support_kb, parse_mode="HTML")
    elif current_state == ScamStates.waiting_withdraw_amount:
        await message.answer("💰 Введите сумму вывода (целое число) или нажмите 'Назад'.", reply_markup=back_to_main_kb)
    elif current_state == ScamStates.waiting_withdraw_card:
        await message.answer("💳 Введите номер карты (только цифры) или нажмите 'Назад'.", reply_markup=back_to_main_kb)
    else:
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=main_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.main_menu)

async def main():
    print("🤖 Бот запущен (полная версия со статусами)")
    print("📢 Логи действий — в админ-панели (кнопка 'Действия')")
    print("💳 Добавлен профиль с балансом, пополнением и выводом")
    print("📜 Добавлена история операций")
    print("🔒 Перед началом работы нужно нажать /start")
    print("🔐 Админ-панель защищена паролем (не отображается)")
    print("👷 Добавлен статус 'Работник' с системой заданий")
    print("👑 Добавлена кнопка 'Назначить статус' в админ-панели")
    print("💎 VIP-скидка 10%, +5% пополнение, +5% вывод")
    print("🧪 Тестеры имеют доступ во время техперерыва")
    print("🎧 Поддержка видит обращения")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
