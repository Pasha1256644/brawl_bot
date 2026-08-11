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
VIP_IDS = []             # ID VIP
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

# ===== ФУНКЦИЯ ЗАПРОСА ПОДТВЕРЖДЕНИЯ ВЛАДЕЛЬЦУ =====
async def request_owner_confirmation(admin_id: int, target_user_id: int, amount: int, action_type: str):
    admin_data = users_db.get(admin_id)
    admin_name = admin_data.get("name", "Админ") if admin_data else "Админ"
    admin_username = admin_data.get("username", "@admin") if admin_data else "@admin"
    
    target_data = users_db.get(target_user_id)
    target_name = target_data.get("name", "Пользователь") if target_data else "Пользователь"
    target_username = target_data.get("username", "@user") if target_data else "@user"
    
    action_text = {
        "topup": f"пополнить баланс на {amount} ⭐",
        "freeze": "заморозить профиль",
        "unfreeze": "разморозить профиль",
        "tech_break": "включить техперерыв",
        "tech_break_off": "выключить техперерыв"
    }.get(action_type, "выполнить действие")
    
    text = (
        f"🔔 <b>ЗАПРОС НА ПОДТВЕРЖДЕНИЕ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Админ:</b> {admin_name} ({admin_username})\n"
        f"📌 <b>Действие:</b> {action_text}\n"
        f"👥 <b>Пользователь:</b> {target_name} ({target_username})\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"Разрешаете выполнить это действие?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Разрешить", callback_data=f"confirm_allow_{admin_id}_{target_user_id}_{amount}_{action_type}"),
            InlineKeyboardButton(text="❌ Запретить", callback_data=f"confirm_deny_{admin_id}_{target_user_id}_{amount}_{action_type}")
        ]
    ])
    
    await bot.send_message(OWNER_USERNAME, text, reply_markup=keyboard, parse_mode="HTML")

# ===== ОБРАБОТЧИК ОТВЕТА ВЛАДЕЛЬЦА =====
@dp.callback_query(F.data.startswith("confirm_"))
async def handle_owner_confirmation(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_USERNAME:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    
    data_parts = callback.data.split("_")
    action = data_parts[1]  # allow или deny
    admin_id = int(data_parts[2])
    target_user_id = int(data_parts[3])
    amount = int(data_parts[4])
    action_type = data_parts[5]
    
    await callback.message.delete()
    
    if action == "allow":
        await callback.message.answer(f"✅ <b>Действие разрешено!</b>", parse_mode="HTML")
        try:
            await bot.send_message(admin_id, f"✅ <b>Владелец разрешил действие!</b>\n\nВы можете продолжить.", parse_mode="HTML")
        except Exception as e:
            print(f"Не удалось уведомить админа: {e}")
        
        # Выполняем действие
        if action_type == "topup":
            users_db[target_user_id]["balance"] += amount
            add_history_entry(target_user_id, amount, f"Пополнение админом с подтверждения владельца (+{amount} ⭐)")
            try:
                await bot.send_message(target_user_id, f"💳 <b>Ваш баланс пополнен!</b>\n\n💰 <b>Сумма:</b> +{amount} ⭐\n📊 <b>Текущий баланс:</b> {users_db[target_user_id]['balance']} ⭐\n\nСпасибо, что с нами! 🎉", parse_mode="HTML")
            except Exception as e:
                print(f"Не удалось уведомить пользователя: {e}")
        elif action_type == "freeze":
            frozen_until = users_db[target_user_id].get("frozen_until", "forever")
            frozen_reason = users_db[target_user_id].get("frozen_reason", "Не указана")
            if frozen_until == "forever":
                until_str = "НАВСЕГДА"
                msg_user = f"❄️ <b>Ваш профиль заморожен НАВСЕГДА!</b>"
            else:
                until_str = frozen_until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
                msg_user = f"❄️ <b>Ваш профиль заморожен до {until_str}</b>"
            try:
                await bot.send_message(target_user_id, f"{msg_user}\n\n📌 <b>Причина:</b> {frozen_reason}\n\nЕсли вы не согласны с решением, обратитесь в поддержку: @suport_skup_bs_bot\nили воспользуйтесь кнопкой «Поддержка» в главном меню бота.", parse_mode="HTML")
            except Exception as e:
                print(f"Не удалось уведомить пользователя: {e}")
        elif action_type == "unfreeze":
            users_db[target_user_id]["frozen_until"] = None
            users_db[target_user_id]["frozen_reason"] = None
            try:
                await bot.send_message(target_user_id, "✅ <b>Ваш профиль разморожен!</b>\n\nТеперь вам доступны все функции бота.\nСпасибо, что с нами! 🎉", parse_mode="HTML")
            except Exception as e:
                print(f"Не удалось уведомить пользователя: {e}")
        elif action_type == "tech_break":
            global tech_break_enabled, tech_break_end, tech_break_reason
            tech_break_enabled = True
            tech_break_end = pending_actions.get(f"{admin_id}_{target_user_id}_tech_break_end")
            tech_break_reason = pending_actions.get(f"{admin_id}_{target_user_id}_tech_break_reason")
            try:
                await bot.send_message(admin_id, f"✅ <b>Технический перерыв включён!</b>", parse_mode="HTML")
            except Exception as e:
                print(f"Не удалось уведомить админа: {e}")
        elif action_type == "tech_break_off":
            global tech_break_enabled, tech_break_end, tech_break_reason
            tech_break_enabled = False
            tech_break_end = None
            tech_break_reason = ""
            try:
                await bot.send_message(admin_id, f"✅ <b>Технический перерыв отключён!</b>", parse_mode="HTML")
            except Exception as e:
                print(f"Не удалось уведомить админа: {e}")
        
    elif action == "deny":
        await callback.message.answer(f"❌ <b>Действие запрещено владельцем!</b>\n\nАдмин {admin_id} заморожен на 1 час.", parse_mode="HTML")
        
        # Замораживаем админа на 1 час
        freeze_time = get_moscow_datetime() + timedelta(hours=1)
        users_db[admin_id]["frozen_until"] = freeze_time
        users_db[admin_id]["frozen_reason"] = "Отказ владельца в выполнении действия"
        
        try:
            await bot.send_message(admin_id, f"❌ <b>Действие запрещено владельцем!</b>\n\nВаш профиль заморожен на 1 час.\nПричина: Отказ владельца в выполнении действия.\n\n⏰ Разморозка в: {freeze_time.strftime('%H:%M')}", parse_mode="HTML")
        except Exception as e:
            print(f"Не удалось уведомить админа: {e}")
    
    # Удаляем из pending_actions
    pending_actions.pop(f"{admin_id}_{target_user_id}_{action_type}", None)
    await callback.answer()

# ===== MIDDLEWARE =====
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
# ===== /START =====
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
# ===== ПРОФИЛЬ =====
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
# ===== ВЫВОД СРЕДСТВ =====
# ============================================
@dp.message(F.text == "💸 Вывести деньги")
async def start_withdraw(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>\n\nВы не можете вывести средства.", reply_markup=profile_kb, parse_mode="HTML")
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", reply_markup=profile_kb, parse_mode="HTML")
        return
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        return
    await message.answer(f"💰 <b>Вывод средств</b>\n\nВаш текущий баланс: <b>{user_data['balance']} ⭐</b>\n\nВведите сумму, которую хотите вывести (целое число):\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_withdraw_amount)

# ============================================
# ===== КУПИТЬ =====
# ============================================
@dp.message(F.text == "🛒 Купить")
async def handle_buy_choice(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>\n\nВы можете приобрести любой товар.", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}\n\nДанная функция вам недоступна.", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'КУПИТЬ' → ВЫБОР")
    await message.answer("🛒 <b>Что вас интересует?</b>\n\nВыберите вариант:", reply_markup=buy_choice_kb, parse_mode="HTML")

@dp.message(F.text == "⭐ Донат")
async def handle_donate(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>Бесконечный баланс</b>\n\nВыберите товар:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 БП+ (бесплатно)", callback_data="donate_buy_бпп")],
            [InlineKeyboardButton(text="🛒 БП (бесплатно)", callback_data="donate_buy_бп")],
            [InlineKeyboardButton(text="💎 Гемы", callback_data="donate_gems")],
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
    await message.answer("⭐ <b>Выберите товар для покупки:</b>\n\n💰 Покупка происходит мгновенно с вашего баланса.", reply_markup=keyboard, parse_mode="HTML")

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
        else:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    if message.text == ADMIN_PASSWORD:
        await message.answer("✅ <b>Пароль верный!</b>\n\n👑 <b>Админ-панель</b>\n\nВыберите действие:", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer("❌ <b>Неверный пароль!</b>\n\nПопробуйте ещё раз или нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН-ПОПОЛНЕНИЕ (С ПОДТВЕРЖДЕНИЕМ) =====
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
        # Владелец выполняет сразу
        current_balance = users_db[target_user]["balance"]
        if amount < 0 and abs(amount) > current_balance:
            await message.answer(f"❌ Недостаточно средств! Текущий баланс: {current_balance} ⭐.", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
        users_db[target_user]["balance"] += amount
        new_balance = users_db[target_user]["balance"]
        add_history_entry(target_user, amount, "Пополнение" if amount > 0 else f"Списание ({abs(amount)} ⭐)")
        await message.answer(f"✅ Баланс изменён на {amount} ⭐.\nНовый баланс: {new_balance} ⭐.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        # Админ отправляет запрос владельцу
        await request_owner_confirmation(message.from_user.id, target_user, amount, "topup")
        await message.answer("⏳ <b>Запрос отправлен владельцу!</b>\n\nОжидайте подтверждения.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-ЗАМОРОЗКА (С ПОДТВЕРЖДЕНИЕМ) =====
# ============================================
@dp.message(F.text == "❄️ Заморозить профиль")
async def admin_freeze_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("❄️ <b>Заморозка профиля</b>\n\nВведите <b>ID или @юзернейм</b> пользователя.\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
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
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(freeze_target=target_user)
    await message.answer(f"✅ Найден: {users_db[target_user]['name']}\n\nВведите дату окончания (ДД.ММ.ГГГГ ЧЧ:ММ) или 0 для бессрочной:", reply_markup=back_to_main_kb, parse_mode="HTML")
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
            day, month, year = map(int, parts[0].split('.'))
            hour, minute = map(int, parts[1].split(':'))
            end_dt = get_moscow_datetime().replace(year=year, month=month, day=day, hour=hour, minute=minute)
            if end_dt < get_moscow_datetime():
                await message.answer("❌ Дата уже прошла!", reply_markup=back_to_main_kb, parse_mode="HTML")
                return
            frozen_until = end_dt
        except:
            await message.answer("❌ Неверный формат! Пример: 15.08.2026 20:00", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
    await state.update_data(freeze_until=frozen_until)
    await message.answer("📌 Введите <b>причину</b> заморозки:", reply_markup=back_to_main_kb, parse_mode="HTML")
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
        await message.answer("❌ Ошибка!", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    if message.from_user.id == OWNER_USERNAME:
        users_db[target_user]["frozen_until"] = frozen_until
        users_db[target_user]["frozen_reason"] = reason
        until_str = "НАВСЕГДА" if frozen_until == "forever" else frozen_until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        try:
            await bot.send_message(target_user, f"❄️ <b>Ваш профиль заморожен</b> до {until_str}\n📌 Причина: {reason}", parse_mode="HTML")
        except:
            pass
        await message.answer(f"✅ Профиль заморожен до {until_str}.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        users_db[target_user]["frozen_until"] = frozen_until
        users_db[target_user]["frozen_reason"] = reason
        await request_owner_confirmation(message.from_user.id, target_user, 0, "freeze")
        await message.answer("⏳ <b>Запрос отправлен владельцу!</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-РАЗМОРОЗКА (С ПОДТВЕРЖДЕНИЕМ) =====
# ============================================
@dp.message(F.text == "🔄 Разморозить профиль")
async def admin_unfreeze_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("🔄 <b>Разморозка профиля</b>\n\nВведите <b>ID или @юзернейм</b> пользователя.\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
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
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    if users_db[target_user].get("frozen_until") is None:
        await message.answer("ℹ️ Профиль уже активен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
        return
    if message.from_user.id == OWNER_USERNAME:
        users_db[target_user]["frozen_until"] = None
        users_db[target_user]["frozen_reason"] = None
        try:
            await bot.send_message(target_user, "✅ <b>Ваш профиль разморожен!</b>", parse_mode="HTML")
        except:
            pass
        await message.answer("✅ Профиль разморожен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        await request_owner_confirmation(message.from_user.id, target_user, 0, "unfreeze")
        await message.answer("⏳ <b>Запрос отправлен владельцу!</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН-ТЕХПЕРЕРЫВ (С ПОДТВЕРЖДЕНИЕМ) =====
# ============================================
@dp.message(F.text == "🛠 Включить перерыв")
async def enable_tech_break(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if tech_break_enabled:
        await message.answer("⚠️ Перерыв уже включён.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    await message.answer("🛠️ <b>Включение техперерыва – шаг 1</b>\n\nВведите дату и время окончания в формате:\n<b>ДД.ММ.ГГГГ ЧЧ:ММ</b>\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
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
        day, month, year = map(int, parts[0].split('.'))
        hour, minute = map(int, parts[1].split(':'))
        end_dt = get_moscow_datetime().replace(year=year, month=month, day=day, hour=hour, minute=minute)
        if end_dt < get_moscow_datetime():
            await message.answer("❌ Дата уже прошла!", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
    except:
        await message.answer("❌ Неверный формат! Пример: 15.08.2026 20:00", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(tech_break_end=end_dt)
    await message.answer("📌 Введите <b>причину</b> техперерыва:", reply_markup=back_to_main_kb, parse_mode="HTML")
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
        await message.answer("❌ Причина не может быть пустой.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    data = await state.get_data()
    end_dt = data.get("tech_break_end")
    if end_dt is None:
        await message.answer("❌ Ошибка!", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    if message.from_user.id == OWNER_USERNAME:
        global tech_break_enabled, tech_break_end, tech_break_reason
        tech_break_enabled = True
        tech_break_end = end_dt
        tech_break_reason = reason
        await message.answer(f"✅ Техперерыв включён до {end_dt.strftime('%d.%m.%Y %H:%M')}.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        pending_actions[f"{message.from_user.id}_0_tech_break"] = {
            "tech_break_end": end_dt,
            "tech_break_reason": reason
        }
        await request_owner_confirmation(message.from_user.id, 0, 0, "tech_break")
        await message.answer("⏳ <b>Запрос отправлен владельцу!</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)

@dp.message(F.text == "⛔ Отключить перерыв")
async def disable_tech_break(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if not tech_break_enabled:
        await message.answer("ℹ️ Перерыв не активен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    if message.from_user.id == OWNER_USERNAME:
        global tech_break_enabled, tech_break_end, tech_break_reason
        tech_break_enabled = False
        tech_break_end = None
        tech_break_reason = ""
        await message.answer("✅ Техперерыв отключён.", reply_markup=admin_menu_kb, parse_mode="HTML")
    else:
        await request_owner_confirmation(message.from_user.id, 0, 0, "tech_break_off")
        await message.answer("⏳ <b>Запрос отправлен владельцу!</b>", reply_markup=admin_menu_kb, parse_mode="HTML")

# ============================================
# ===== ОСТАЛЬНЫЕ АДМИН-КНОПКИ (БЕЗ ПОДТВЕРЖДЕНИЯ) =====
# ============================================
@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer(f"📊 <b>Статистика</b>\n\n👥 Всего пользователей: {len(users_db)}\n📋 Всего действий: {len(actions_log)}", reply_markup=admin_menu_kb, parse_mode="HTML")

@dp.message(F.text == "👥 Пользователи")
async def admin_users(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if not users_db:
        await message.answer("👥 Пока нет пользователей.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    text = "👥 <b>Список пользователей:</b>\n\n"
    for idx, (uid, data) in enumerate(users_db.items(), 1):
        frozen_str = "❄️" if data.get("frozen_until") else "✅"
        text += f"{idx}. ID: <code>{uid}</code> | {data['name']} | {frozen_str}\n"
        if idx >= 20:
            text += f"... и ещё {len(users_db) - 20} пользователей."
            break
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

@dp.message(F.text == "📋 Действия")
async def admin_actions(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if not actions_log:
        await message.answer("📋 Пока нет действий.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    text = "📋 <b>Последние действия:</b>\n\n"
    for entry in actions_log[-10:]:
        text += f"• {entry}\n"
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

@dp.message(F.text == "✉️ Отправить сообщение")
async def admin_send_message_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("✉️ <b>Отправка сообщения</b>\n\nВведите <b>ID или @юзернейм</b> получателя:\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
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
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    await state.update_data(target_user=target_user)
    await message.answer("✉️ Введите <b>текст сообщения</b>:", reply_markup=back_to_main_kb, parse_mode="HTML")
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
        await message.answer("❌ Ошибка!", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    msg_text = message.text
    try:
        await bot.send_message(target_user, f"📩 <b>Сообщение от администрации</b>\n\n{msg_text}", parse_mode="HTML")
        await message.answer(f"✅ Сообщение отправлено пользователю {users_db[target_user]['name']}.", reply_markup=admin_menu_kb, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== МОДЕРАТОР =====
# ============================================
@dp.message(F.text == "📩 Написать письмо")
async def moderator_write_letter(message: Message, state: FSMContext):
    if message.from_user.id not in MODERATOR_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("✍️ <b>Написать письмо</b>\n\nВведите <b>ID или @юзернейм</b> и текст через пробел.\nПример: <code>123456789 Здравствуйте!</code>\n\n🔙 Для отмены нажмите 'Назад'.", reply_markup=back_to_main_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_msg_user)

@dp.message(F.text == "📋 Обращения")
async def moderator_view_appeals(message: Message, state: FSMContext):
    if message.from_user.id not in MODERATOR_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if not actions_log:
        await message.answer("📋 Пока нет обращений.", reply_markup=moderator_menu_kb, parse_mode="HTML")
        return
    text = "📋 <b>Обращения в поддержку:</b>\n\n"
    for entry in actions_log[-10:]:
        if "ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ" in entry:
            text += f"• {entry}\n"
    await message.answer(text, reply_markup=moderator_menu_kb, parse_mode="HTML")

# ============================================
# ===== НАЗАД =====
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

# ============================================
# ===== ЗАПУСК =====
# ============================================
async def main():
    print("🤖 Бот запущен")
    print("👑 Полная система статусов и подтверждений")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
