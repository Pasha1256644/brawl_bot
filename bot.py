import asyncio
import random
import logging
import hashlib
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

# ============================================
# ===== ЛОГИРОВАНИЕ =====
# ============================================
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_errors.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
user_tasks = {}
worker_photo_hashes = {}
pending_requests = {}  # Хранит запросы админов к владельцу

ADMIN_IDS = []
MODERATOR_IDS = []
SUPPORT_IDS = []
TESTER_IDS = []
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
# ===== ТЕХНИЧЕСКИЙ ПЕРЕРЫВ =====
# ============================================
tech_break_enabled = False
tech_break_end = None
tech_break_reason = ""

# ============================================
# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
# ============================================
def get_moscow_datetime():
    return datetime.now() + timedelta(hours=3)

def get_moscow_time():
    return get_moscow_datetime().strftime("%Y-%m-%d %H:%M:%S")

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

def is_tester(user_id: int):
    return user_id in TESTER_IDS

def get_vip_discount(user_id: int):
    return 0.9 if is_vip(user_id) else 1.0

def get_infinite_balance(user_id: int):
    return user_id == OWNER_USERNAME or is_admin(user_id)

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

def is_user_frozen(user_id: int):
    user_data = users_db.get(user_id)
    if not user_data:
        return False, None, None
    frozen_until = user_data.get("frozen_until")
    frozen_reason = user_data.get("frozen_reason")
    if frozen_until is None:
        return False, None, None
    if frozen_until == "forever":
        return True, "навсегда", frozen_reason
    if isinstance(frozen_until, datetime) and get_moscow_datetime() < frozen_until:
        return True, frozen_until, frozen_reason
    else:
        user_data["frozen_until"] = None
        user_data["frozen_reason"] = None
        return False, None, None

def get_photo_hash(photo: types.PhotoSize) -> str:
    return hashlib.md5(photo.file_id.encode()).hexdigest()

def find_user(identifier: str):
    identifier = identifier.strip()
    if identifier.startswith('@'):
        username = identifier[1:].lower()
        for uid, data in users_db.items():
            if data.get("username", "").lower() == f"@{username}":
                return uid
        return None
    else:
        try:
            uid = int(identifier)
            if uid in users_db:
                return uid
            return None
        except ValueError:
            return None

def track_user(user: types.User):
    if user.id not in users_db:
        users_db[user.id] = {
            "name": user.full_name or "без имени",
            "username": f"@{user.username}" if user.username else "без юзернейма",
            "first_seen": get_moscow_time(),
            "last_seen": get_moscow_time(),
            "balance": 0,
            "history": [],
            "frozen_until": None,
            "frozen_reason": None
        }
    else:
        users_db[user.id]["last_seen"] = get_moscow_time()
        users_db[user.id]["name"] = user.full_name or "без имени"
        users_db[user.id]["username"] = f"@{user.username}" if user.username else "без юзернейма"

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
    logger.info(f"{user.id} → {action}")

async def notify_owner(user: types.User, action: str, send_to_dm: bool = False):
    log_action(user, action)
    if send_to_dm:
        try:
            await bot.send_message(OWNER_USERNAME, f"🔔 <b>Действие пользователя</b>\n\n{action}", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")

# ============================================
# ===== СИСТЕМА ЗАПРОСОВ К ВЛАДЕЛЬЦУ =====
# ============================================
async def send_approval_request(admin_id: int, request_type: str, data: dict):
    """Отправляет запрос владельцу на одобрение действия админа"""
    admin_data = users_db.get(admin_id)
    admin_name = admin_data['name'] if admin_data else "Админ"
    admin_username = admin_data['username'] if admin_data else "без юзернейма"
    
    if request_type == "balance":
        target_user_id = data.get("target_user")
        amount = data.get("amount")
        target_data = users_db.get(target_user_id)
        target_name = target_data['name'] if target_data else "Пользователь"
        target_username = target_data['username'] if target_data else "без юзернейма"
        
        text = (
            f"🔔 <b>ЗАПРОС НА ОДОБРЕНИЕ</b>\n\n"
            f"👤 <b>Админ:</b> {admin_name} ({admin_username}) [ID: {admin_id}]\n"
            f"📌 <b>Действие:</b> Пополнение баланса\n"
            f"👤 <b>Пользователь:</b> {target_name} ({target_username}) [ID: {target_user_id}]\n"
            f"💰 <b>Сумма:</b> {amount} ⭐\n\n"
            f"⬇️ <b>Выберите действие:</b>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ РАЗРЕШИТЬ", callback_data=f"approve_balance_{admin_id}_{target_user_id}_{amount}"),
                InlineKeyboardButton(text="❌ ОТКАЗАТЬ", callback_data=f"reject_balance_{admin_id}")
            ]
        ])
        
    elif request_type == "freeze":
        target_user_id = data.get("target_user")
        frozen_until = data.get("frozen_until")
        reason = data.get("reason")
        target_data = users_db.get(target_user_id)
        target_name = target_data['name'] if target_data else "Пользователь"
        target_username = target_data['username'] if target_data else "без юзернейма"
        
        until_str = "НАВСЕГДА" if frozen_until == "forever" else frozen_until.strftime("%d.%m.%Y %H:%M") if isinstance(frozen_until, datetime) else str(frozen_until)
        
        text = (
            f"🔔 <b>ЗАПРОС НА ОДОБРЕНИЕ</b>\n\n"
            f"👤 <b>Админ:</b> {admin_name} ({admin_username}) [ID: {admin_id}]\n"
            f"📌 <b>Действие:</b> Заморозка профиля\n"
            f"👤 <b>Пользователь:</b> {target_name} ({target_username}) [ID: {target_user_id}]\n"
            f"⏰ <b>До:</b> {until_str}\n"
            f"📌 <b>Причина:</b> {reason}\n\n"
            f"⬇️ <b>Выберите действие:</b>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ РАЗРЕШИТЬ", callback_data=f"approve_freeze_{admin_id}_{target_user_id}_{frozen_until}_{reason}"),
                InlineKeyboardButton(text="❌ ОТКАЗАТЬ", callback_data=f"reject_freeze_{admin_id}")
            ]
        ])
        
    elif request_type == "unfreeze":
        target_user_id = data.get("target_user")
        target_data = users_db.get(target_user_id)
        target_name = target_data['name'] if target_data else "Пользователь"
        target_username = target_data['username'] if target_data else "без юзернейма"
        
        text = (
            f"🔔 <b>ЗАПРОС НА ОДОБРЕНИЕ</b>\n\n"
            f"👤 <b>Админ:</b> {admin_name} ({admin_username}) [ID: {admin_id}]\n"
            f"📌 <b>Действие:</b> Разморозка профиля\n"
            f"👤 <b>Пользователь:</b> {target_name} ({target_username}) [ID: {target_user_id}]\n\n"
            f"⬇️ <b>Выберите действие:</b>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ РАЗРЕШИТЬ", callback_data=f"approve_unfreeze_{admin_id}_{target_user_id}"),
                InlineKeyboardButton(text="❌ ОТКАЗАТЬ", callback_data=f"reject_unfreeze_{admin_id}")
            ]
        ])
        
    elif request_type == "tech_on":
        end_dt = data.get("end_dt")
        reason = data.get("reason")
        end_str = end_dt.strftime("%d.%m.%Y %H:%M") if isinstance(end_dt, datetime) else str(end_dt)
        
        text = (
            f"🔔 <b>ЗАПРОС НА ОДОБРЕНИЕ</b>\n\n"
            f"👤 <b>Админ:</b> {admin_name} ({admin_username}) [ID: {admin_id}]\n"
            f"📌 <b>Действие:</b> Включить техперерыв\n"
            f"⏰ <b>До:</b> {end_str}\n"
            f"📌 <b>Причина:</b> {reason}\n\n"
            f"⬇️ <b>Выберите действие:</b>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ РАЗРЕШИТЬ", callback_data=f"approve_tech_on_{admin_id}_{end_dt.strftime('%Y%m%d%H%M')}_{reason}"),
                InlineKeyboardButton(text="❌ ОТКАЗАТЬ", callback_data=f"reject_tech_on_{admin_id}")
            ]
        ])
        
    elif request_type == "tech_off":
        text = (
            f"🔔 <b>ЗАПРОС НА ОДОБРЕНИЕ</b>\n\n"
            f"👤 <b>Админ:</b> {admin_name} ({admin_username}) [ID: {admin_id}]\n"
            f"📌 <b>Действие:</b> Отключить техперерыв\n\n"
            f"⬇️ <b>Выберите действие:</b>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ РАЗРЕШИТЬ", callback_data=f"approve_tech_off_{admin_id}"),
                InlineKeyboardButton(text="❌ ОТКАЗАТЬ", callback_data=f"reject_tech_off_{admin_id}")
            ]
        ])
    
    try:
        await bot.send_message(OWNER_USERNAME, text, reply_markup=keyboard, parse_mode="HTML")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки запроса владельцу: {e}")
        return False

async def freeze_admin_account(admin_id: int, duration_hours: int = 1):
    """Заморозка аккаунта админа при отказе"""
    frozen_until = get_moscow_datetime() + timedelta(hours=duration_hours)
    if admin_id in users_db:
        users_db[admin_id]["frozen_until"] = frozen_until
        users_db[admin_id]["frozen_reason"] = "Отказ от одобрения действия владельцем"
    
    try:
        await bot.send_message(
            admin_id,
            f"❄️ <b>Ваш аккаунт заморожен на {duration_hours} час(а)!</b>\n\n"
            f"📌 <b>Причина:</b> Отказ от одобрения действия владельцем\n"
            f"⏰ <b>До:</b> {frozen_until.strftime('%d.%m.%Y %H:%M')} (МСК)\n\n"
            f"Все функции админа временно недоступны.",
            parse_mode="HTML"
        )
    except:
        pass

# ============================================
# ===== МИДЛВАРЫ =====
# ============================================
class RegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = event.from_user
        if user and user.id not in users_db:
            # Если пользователь не зарегистрирован, ПРОПУСКАЕМ только /start
            if isinstance(event, types.Message) and event.text and event.text.startswith('/start'):
                return await handler(event, data)
            await event.answer("⚠️ Пожалуйста, нажмите /start для начала работы.")
            return
        return await handler(event, data)

class TechBreakMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if is_tech_break_active():
            user = event.from_user
            if user.id == OWNER_USERNAME or is_tester(user.id):
                return await handler(event, data)
            end_dt = tech_break_end
            end_str = end_dt.strftime("%d.%m.%Y %H:%M")
            reason = tech_break_reason if tech_break_reason else "не указана"
            msg = (
                f"🛠️ <b>Технический перерыв!</b>\n\n"
                f"⏰ Бот временно недоступен до <b>{end_str}</b> (по московскому времени).\n"
                f"📌 <b>Причина:</b> {reason}\n\n"
                f"📩 По всем вопросам обращайтесь в поддержку: @suport_skup_bs_bot"
            )
            if isinstance(event, types.Message):
                await event.answer(msg, parse_mode="HTML")
            elif isinstance(event, types.CallbackQuery):
                await event.answer("🛠️ Технический перерыв", show_alert=True)
                await event.message.answer(msg, parse_mode="HTML")
            return
        return await handler(event, data)

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

# Подключаем мидлвары
dp.message.middleware(RegistrationMiddleware())
dp.message.middleware(TechBreakMiddleware())
dp.callback_query.middleware(TechBreakMiddleware())

# ============================================
# ===== ХЕНДЛЕР START (ИСПРАВЛЕННЫЙ) =====
# ============================================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # Регистрируем пользователя
    track_user(message.from_user)
    await notify_owner(message.from_user, "ЗАПУСТИЛ БОТА (/start)")
    await state.clear()
    await state.set_state(ScamStates.main_menu)
    
    # Показываем меню в зависимости от роли
    if message.from_user.id == OWNER_USERNAME:
        await message.answer(
            "👋 Добро пожаловать, владелец!\n\n"
            "❓ Что вы хотите сделать?",
            reply_markup=owner_menu_kb
        )
    elif is_admin(message.from_user.id):
        # Проверка на заморозку админа
        frozen, until, reason = is_user_frozen(message.from_user.id)
        if frozen:
            until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
            await message.answer(
                f"❄️ <b>Ваш аккаунт заморожен!</b>\n\n"
                f"⏰ До: {until_str}\n"
                f"📌 Причина: {reason}\n\n"
                f"Админ-панель недоступна до разморозки.",
                reply_markup=main_menu_kb,
                parse_mode="HTML"
            )
            return
        await message.answer(
            "👋 Добро пожаловать, администратор!\n\n"
            "❓ Что вы хотите сделать?",
            reply_markup=admin_menu_kb
        )
    elif is_moderator(message.from_user.id):
        await message.answer(
            "👋 Добро пожаловать, модератор!\n\n"
            "❓ Что вы хотите сделать?",
            reply_markup=moderator_menu_kb
        )
    elif is_worker(message.from_user.id):
        await message.answer(
            "👋 Добро пожаловать!\n\n"
            "❓ Что вы хотите сделать?",
            reply_markup=worker_menu_kb
        )
    else:
        await message.answer(
            "👋 Добро пожаловать!\n\n"
            "❓ Что вы хотите сделать?",
            reply_markup=main_menu_kb
        )

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
        f"👇 Выберите действие:",
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
        await message.answer("📜 История операций пуста", reply_markup=profile_kb)
        return
    
    text = "📜 <b>История операций (последние 10):</b>\n\n"
    for entry in history[-10:]:
        sign = "+" if entry["amount"] >= 0 else ""
        text += f"🕒 {entry['time']}\n   {sign}{entry['amount']} ⭐ — {entry['description']}\n\n"
    
    await message.answer(text, reply_markup=profile_kb, parse_mode="HTML")

@dp.message(F.text == "💰 Пополнить баланс")
async def handle_balance_topup(message: Message, state: FSMContext):
    if is_admin(message.from_user.id):
        await admin_balance_start(message, state)
        return
    else:
        await message.answer(
            "💳 <b>Пополнение баланса</b>\n\n"
            "Обратитесь в поддержку: @suport_skup_bs_bot",
            reply_markup=profile_kb,
            parse_mode="HTML"
        )

# ============================================
# ===== ВЫВОД СРЕДСТВ =====
# ============================================
@dp.message(F.text == "💸 Вывести деньги")
async def start_withdraw(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ У вас бесконечный баланс. Вывод недоступен.", reply_markup=profile_kb)
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ Профиль заморожен до {until_str}\nПричина: {reason}", reply_markup=profile_kb)
        return
    
    user_data = users_db.get(message.from_user.id)
    await message.answer(
        f"💰 <b>Вывод средств</b>\n\nВаш баланс: <b>{user_data['balance']} ⭐</b>\n\nВведите сумму:",
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
        await message.answer("❌ Введите положительное число.", reply_markup=back_kb)
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        await message.answer("❄️ Профиль заморожен. Вывод недоступен.", reply_markup=profile_kb)
        await state.clear()
        return
    
    user_data = users_db.get(message.from_user.id)
    if amount > user_data["balance"]:
        await message.answer(f"❌ Недостаточно средств! Баланс: {user_data['balance']} ⭐", reply_markup=back_kb)
        return
    
    await state.update_data(withdraw_amount=amount)
    await message.answer(
        f"✅ Сумма {amount} ⭐ принята.\n\nВведите номер карты:",
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
        await message.answer("❌ Неверный номер карты.", reply_markup=back_kb)
        return
    
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    if not amount:
        await message.answer("❌ Ошибка.", reply_markup=profile_kb)
        await state.clear()
        return
    
    user_id = message.from_user.id
    users_db[user_id]["balance"] -= amount
    new_balance = users_db[user_id]["balance"]
    add_history(user_id, -amount, f"Вывод {amount} ⭐ на карту {card_number[:4]}...{card_number[-4:]}")
    log_action(message.from_user, f"ВЫВЕЛ {amount} ⭐")
    await notify_owner(message.from_user, f"💸 ВЫВОД СРЕДСТВ\nСумма: {amount} ⭐", send_to_dm=True)
    
    commission = amount * 0.05
    await message.answer(
        f"✅ Заявка на вывод {amount} ⭐ отправлена!\n\n"
        f"Комиссия: {commission:.2f} ⭐\n"
        f"Новый баланс: {new_balance} ⭐",
        reply_markup=profile_kb,
        parse_mode="HTML"
    )
    await state.clear()

# ============================================
# ===== КУПИТЬ =====
# ============================================
@dp.message(F.text == "🛒 Купить")
async def handle_buy(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ У вас бесконечный баланс.", reply_markup=main_menu_kb)
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        await message.answer("❄️ Профиль заморожен. Покупка недоступна.", reply_markup=main_menu_kb)
        return
    
    await message.answer("🛒 Что вас интересует?", reply_markup=buy_choice_kb)

@dp.message(F.text == "⭐ Донат")
async def handle_donate(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for item in DONATE_ITEMS:
        price = item['price']
        if is_vip(message.from_user.id):
            price = int(price * 0.9)
            label = f"🛒 {item['name']} за {price} ⭐ (VIP скидка)"
        else:
            label = f"🛒 {item['name']} за {price} ⭐"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"donate_{item['name'].lower().replace('+', 'p')}")])
    
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="💎 Купить гемы", callback_data="donate_gems")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="donate_back")])
    await message.answer("⭐ Выберите товар:", reply_markup=keyboard, parse_mode="HTML")

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
            "💎 Введите количество гемов.\nЦена: 1 гем = 4.5 ⭐",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        await state.set_state(ScamStates.waiting_gems_amount)
        return
    
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
        return
    
    users_db[user_id]["balance"] -= price
    add_history(user_id, -price, f"Покупка {target_item['name']}")
    log_action(callback.from_user, f"КУПИЛ {target_item['name']}")
    
    await callback.answer("✅ Покупка успешна!", show_alert=True)
    await callback.message.answer(f"✅ Вы купили {target_item['name']} за {price} ⭐. Новый баланс: {users_db[user_id]['balance']} ⭐", parse_mode="HTML")

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
        await message.answer(f"❌ Недостаточно средств! Нужно: {price} ⭐", reply_markup=back_kb)
        return
    
    users_db[user_id]["balance"] -= price
    add_history(user_id, -price, f"Покупка {gems} гемов")
    log_action(message.from_user, f"КУПИЛ {gems} ГЕМОВ")
    
    await message.answer(f"✅ Вы купили {gems} гемов за {price} ⭐. Новый баланс: {users_db[user_id]['balance']} ⭐", reply_markup=buy_choice_kb, parse_mode="HTML")
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
        return
    
    users_db[user_id]["balance"] -= price
    add_history(user_id, -price, f"Покупка {lot['name']}")
    log_action(callback.from_user, f"КУПИЛ {lot['name']}")
    
    await callback.answer("✅ Покупка успешна!", show_alert=True)
    await callback.message.answer(f"✅ Вы купили {lot['name']} за {price} ⭐. Новый баланс: {users_db[user_id]['balance']} ⭐", parse_mode="HTML")

# ============================================
# ===== ПРОДАЖА =====
# ============================================
@dp.message(F.text == "💰 Продать")
async def handle_sell(message: Message, state: FSMContext):
    await message.answer("💰 Продажа аккаунта\n\nСвяжитесь с поддержкой: @suport_skup_bs_bot", reply_markup=back_kb)

# ============================================
# ===== ЗАРАБОТОК =====
# ============================================
@dp.message(F.text == "💸 Заработать деньги")
async def handle_earn(message: Message, state: FSMContext):
    await message.answer(
        "💰 <b>Зарабатывайте с нами!</b>\n\n"
        "Пишите комментарии в TikTok:\n"
        "<code>@skup_bs_bot лучший бот</code>\n\n"
        "1 комментарий = 5 ⭐\n\n"
        "Для выплаты обращайтесь: @suport_skup_bs_bot",
        reply_markup=back_kb,
        parse_mode="HTML"
    )

# ============================================
# ===== РАБОТНИК =====
# ============================================
@dp.message(F.text == "👷 Работа")
async def handle_work_start(message: Message, state: FSMContext):
    if not is_worker(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return
    
    if message.from_user.id in user_tasks:
        task = user_tasks[message.from_user.id]
        time_left = 24 - (get_moscow_datetime() - task["start_time"]).seconds // 3600
        await message.answer(
            f"⏳ Активное задание!\n"
            f"Осталось: {task['comments'] - task['submitted']} скринов\n"
            f"Времени: {time_left} ч.",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return
    
    await message.answer(
        "👷 Готовы начать новый слот?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="worker_start_yes")]
        ]),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "worker_start_yes")
async def worker_start_yes(callback: CallbackQuery, state: FSMContext):
    if not is_worker(callback.from_user.id):
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(
        "✍️ Сколько комментариев готовы написать?\n"
        "Максимум: 500\n"
        "1 комментарий = 5 ⭐",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.worker_task_comments)

@dp.message(ScamStates.worker_task_comments)
async def worker_comments_input(message: Message, state: FSMContext):
    if not is_worker(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return
    
    if message.text == "🔙 Назад":
        await state.clear()
        await show_main_menu(message)
        return
    
    try:
        comments = int(message.text.strip())
        if comments <= 0 or comments > 500:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 1 до 500.", reply_markup=back_kb)
        return
    
    reward = comments * 5
    await state.update_data(worker_comments=comments, worker_reward=reward)
    await message.answer(
        f"✅ Комментариев: {comments}\n💰 Награда: {reward} ⭐\n\nСогласны?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="worker_confirm_yes")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.worker_task_confirm)

@dp.callback_query(F.data == "worker_confirm_yes")
async def worker_confirm_yes(callback: CallbackQuery, state: FSMContext):
    if not is_worker(callback.from_user.id):
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return
    
    data = await state.get_data()
    comments = data.get("worker_comments")
    reward = data.get("worker_reward")
    
    if not comments:
        await callback.answer("❌ Ошибка!", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.delete()
    
    user_tasks[callback.from_user.id] = {
        "comments": comments,
        "submitted": 0,
        "start_time": get_moscow_datetime(),
        "reward": reward,
        "file_hashes": []
    }
    
    await callback.message.answer(
        f"✅ Начинайте работу!\n\n"
        f"📌 Текст:\n<code>skup_bs_ лучший бот для покупки доната или продажи аккаунта Brawl Stars</code>\n\n"
        f"Ждем {comments} скринов.\n"
        f"⏳ У вас 24 часа.\n"
        f"⚠️ Штраф: {reward} ⭐\n\n"
        f"Отправляйте скрины в этот чат.",
        parse_mode="HTML"
    )
    await state.clear()
    await state.set_state(ScamStates.worker_task_working)

@dp.message(ScamStates.worker_task_working, F.photo)
async def worker_photo_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    task = user_tasks.get(user_id)
    
    if not task:
        await message.answer("⚠️ Нет активного задания.")
        await state.clear()
        return
    
    elapsed = (get_moscow_datetime() - task["start_time"]).total_seconds()
    if elapsed > 24 * 3600:
        reward = task["reward"]
        users_db[user_id]["balance"] -= reward
        add_history(user_id, -reward, f"Штраф за невыполнение задания (-{reward} ⭐)")
        await message.answer(f"❌ Время вышло! Списано {reward} ⭐")
        del user_tasks[user_id]
        await state.clear()
        return
    
    photo_hash = get_photo_hash(message.photo[-1])
    if photo_hash in task["file_hashes"]:
        await message.answer("⚠️ Этот скрин уже был отправлен!")
        return
    
    task["file_hashes"].append(photo_hash)
    task["submitted"] += 1
    remaining = task["comments"] - task["submitted"]
    time_left = 24 - (elapsed // 3600)
    
    if remaining > 0:
        await message.answer(f"✅ Отправлено: {task['submitted']} скринов. Осталось: {remaining}. Времени: {int(time_left)} ч.")
    else:
        reward = task["reward"]
        users_db[user_id]["balance"] += reward
        add_history(user_id, reward, f"Заработок за комментарии (+{reward} ⭐)")
        await message.answer(f"✅ Задание выполнено! Начислено {reward} ⭐. Баланс: {users_db[user_id]['balance']} ⭐")
        del user_tasks[user_id]
        await state.clear()

# ============================================
# ===== ПОДДЕРЖКА =====
# ============================================
@dp.message(F.text == "❓ Поддержка")
async def handle_support(message: Message, state: FSMContext):
    await message.answer(
        "📩 Напишите ваш вопрос:",
        reply_markup=support_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_support)

@dp.message(ScamStates.waiting_support)
async def process_support(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await show_main_menu(message)
        return
    
    user = message.from_user
    admin_text = f"📩 Вопрос от {user.full_name} (@{user.username})\n\n{message.text}"
    
    log_action(user, f"ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ")
    
    try:
        await bot.send_message(OWNER_USERNAME, admin_text, parse_mode="HTML")
        for sup_id in SUPPORT_IDS:
            try:
                await bot.send_message(sup_id, admin_text, parse_mode="HTML")
            except:
                pass
        await message.answer("✅ Сообщение отправлено!", reply_markup=main_menu_kb)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=support_kb)
    
    await state.clear()

# ============================================
# ===== МОДЕРАТОР =====
# ============================================
@dp.message(F.text == "📩 Написать письмо")
async def moderator_write_letter(message: Message, state: FSMContext):
    if not is_moderator(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    await message.answer(
        "✍️ Введите ID и текст через пробел:\nПример: 123456789 Здравствуйте!",
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
        await show_main_menu(message)
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Введите ID и текст.", reply_markup=back_kb)
        return
    
    target_user = find_user(parts[0])
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_kb)
        return
    
    try:
        await bot.send_message(target_user, f"📩 Сообщение от модератора:\n\n{parts[1]}")
        await message.answer("✅ Сообщение отправлено!", reply_markup=moderator_menu_kb)
        log_action(message.from_user, f"ОТПРАВИЛ СООБЩЕНИЕ пользователю {users_db[target_user]['username']}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=moderator_menu_kb)
    
    await state.clear()

@dp.message(F.text == "📋 Обращения")
async def moderator_view_appeals(message: Message, state: FSMContext):
    if not is_moderator(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    appeals = []
    for entry in actions_log:
        if "ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ" in entry:
            appeals.append(entry)
    
    if not appeals:
        await message.answer("📋 Обращений пока нет.", reply_markup=moderator_menu_kb)
        return
    
    text = "📋 Последние обращения:\n\n"
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
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(f"❄️ Ваш аккаунт заморожен до {until_str}\nПричина: {reason}", reply_markup=main_menu_kb)
        return
    
    await message.answer("🔐 Введите пароль:", reply_markup=back_kb, parse_mode="HTML")
    await state.set_state(ScamStates.waiting_admin_password)

@dp.message(ScamStates.waiting_admin_password)
async def admin_password_check(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    if message.text == "🔙 Назад":
        await state.clear()
        await show_main_menu(message)
        return
    
    if message.text == ADMIN_PASSWORD:
        await message.answer("✅ Доступ разрешён!", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer("❌ Неверный пароль!", reply_markup=back_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН: СТАТИСТИКА =====
# ============================================
@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    total_users = len(users_db)
    total_actions = len(actions_log)
    tasks_count = len(user_tasks)
    
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"📋 Действий: {total_actions}\n"
        f"👷 Активных заданий: {tasks_count}",
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
        await message.answer("👥 Пока ни одного пользователя.", reply_markup=admin_menu_kb)
        return
    
    text = "👥 <b>Список пользователей:</b>\n\n"
    for idx, (uid, data) in enumerate(users_db.items(), 1):
        frozen_str = "❄️ Заморожен" if data.get("frozen_until") else "✅ Активен"
        text += f"{idx}. <b>ID:</b> <code>{uid}</code>\n"
        text += f"   📛 {data['name']}\n"
        text += f"   🔖 {data['username']}\n"
        text += f"   💰 Баланс: {data.get('balance', 0)} ⭐\n"
        text += f"   ❄️ Статус: {frozen_str}\n\n"
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
        await message.answer("📋 Пока нет действий.", reply_markup=admin_menu_kb)
        return
    
    text = "📋 <b>Последние действия:</b>\n\n"
    for entry in actions_log[-20:]:
        text += f"• {entry}\n"
    
    if len(actions_log) > 20:
        text += f"\n... и ещё {len(actions_log) - 20} действий."
    
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН: ПОПОЛНЕНИЕ БАЛАНСА (С ЗАПРОСОМ) =====
# ============================================
async def admin_balance_start(message: Message, state: FSMContext):
    await message.answer(
        "💰 Введите ID или @юзернейм пользователя:",
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
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_kb)
        return
    
    await state.update_data(target_user=target_user)
    await message.answer(
        f"✅ Найден: {users_db[target_user]['name']}\n"
        f"Баланс: {users_db[target_user]['balance']} ⭐\n\n"
        f"Введите сумму (+ пополнение, - списание):",
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
        await message.answer("❌ Введите число, не равное нулю.", reply_markup=back_kb)
        return
    
    data = await state.get_data()
    target_user = data.get("target_user")
    if target_user is None:
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Если владелец - выполняем сразу
    if message.from_user.id == OWNER_USERNAME:
        if amount < 0 and abs(amount) > users_db[target_user]["balance"]:
            await message.answer(f"❌ Недостаточно средств! Баланс: {users_db[target_user]['balance']} ⭐", reply_markup=back_kb)
            return
        
        users_db[target_user]["balance"] += amount
        new_balance = users_db[target_user]["balance"]
        add_history(target_user, amount, f"Админ: {'пополнение' if amount > 0 else 'списание'}")
        log_action(message.from_user, f"ИЗМЕНИЛ БАЛАНС пользователю {users_db[target_user]['username']} на {amount} ⭐")
        
        await message.answer(
            f"✅ Баланс изменён на {amount} ⭐\n"
            f"Новый баланс: {new_balance} ⭐",
            reply_markup=admin_menu_kb,
            parse_mode="HTML"
        )
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Админ - отправляем запрос владельцу
    await message.answer(
        "⏳ <b>Запрос отправлен владельцу на одобрение!</b>\n\n"
        "Ожидайте подтверждения. Владелец получит уведомление.",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_panel)
    
    await send_approval_request(
        message.from_user.id,
        "balance",
        {"target_user": target_user, "amount": amount}
    )

# ============================================
# ===== АДМИН: ОТПРАВКА СООБЩЕНИЯ =====
# ============================================
@dp.message(F.text == "✉️ Отправить сообщение")
async def admin_send_message_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "✉️ Введите ID или @юзернейм пользователя:",
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
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_kb)
        return
    
    await state.update_data(target_user=target_user)
    await message.answer(
        f"✅ Найден: {users_db[target_user]['name']}\n\n"
        f"Введите текст сообщения:",
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
    if target_user is None:
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    try:
        await bot.send_message(target_user, f"📩 Сообщение от администрации:\n\n{message.text}")
        await message.answer("✅ Сообщение отправлено!", reply_markup=admin_menu_kb)
        log_action(message.from_user, f"ОТПРАВИЛ СООБЩЕНИЕ пользователю {users_db[target_user]['username']}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=admin_menu_kb)
    
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН: ЗАМОРОЗКА (С ЗАПРОСОМ) =====
# ============================================
@dp.message(F.text == "❄️ Заморозить профиль")
async def admin_freeze_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "❄️ Введите ID или @юзернейм пользователя:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_freeze_user)

@dp.message(ScamStates.admin_freeze_user)
async def admin_freeze_user_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_kb)
        return
    
    await state.update_data(freeze_target=target_user)
    await message.answer(
        "Введите дату окончания (ДД.ММ.ГГГГ ЧЧ:ММ) или 0 для бессрочной:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_freeze_date)

@dp.message(ScamStates.admin_freeze_date)
async def admin_freeze_date_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
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
                raise ValueError
            frozen_until = end_dt
        except:
            await message.answer("❌ Неверный формат.", reply_markup=back_kb)
            return
    
    await state.update_data(freeze_until=frozen_until)
    await message.answer(
        "❄️ Введите причину заморозки:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_freeze_reason)

@dp.message(ScamStates.admin_freeze_reason)
async def admin_freeze_reason_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    reason = message.text.strip()
    if not reason:
        await message.answer("❌ Причина не может быть пустой.", reply_markup=back_kb)
        return
    
    data = await state.get_data()
    target_user = data.get("freeze_target")
    frozen_until = data.get("freeze_until")
    
    if target_user is None:
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Если владелец - выполняем сразу
    if message.from_user.id == OWNER_USERNAME:
        users_db[target_user]["frozen_until"] = frozen_until
        users_db[target_user]["frozen_reason"] = reason
        
        until_str = "НАВСЕГДА" if frozen_until == "forever" else frozen_until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        
        try:
            await bot.send_message(target_user, f"❄️ Профиль заморожен до {until_str}\nПричина: {reason}")
        except:
            pass
        
        log_action(message.from_user, f"ЗАМОРОЗИЛ ПРОФИЛЬ {users_db[target_user]['username']} до {until_str}")
        await message.answer(f"✅ Профиль заморожен до {until_str}", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.clear()
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Админ - отправляем запрос владельцу
    await message.answer(
        "⏳ <b>Запрос отправлен владельцу на одобрение!</b>\n\n"
        "Ожидайте подтверждения.",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_panel)
    
    await send_approval_request(
        message.from_user.id,
        "freeze",
        {"target_user": target_user, "frozen_until": frozen_until, "reason": reason}
    )

# ============================================
# ===== АДМИН: РАЗМОРОЗКА (С ЗАПРОСОМ) =====
# ============================================
@dp.message(F.text == "🔄 Разморозить профиль")
async def admin_unfreeze_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "🔄 Введите ID или @юзернейм пользователя:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_unfreeze_user)

@dp.message(ScamStates.admin_unfreeze_user)
async def admin_unfreeze_user_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_kb)
        return
    
    if users_db[target_user].get("frozen_until") is None:
        await message.answer("ℹ️ Профиль уже активен.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Если владелец - выполняем сразу
    if message.from_user.id == OWNER_USERNAME:
        users_db[target_user]["frozen_until"] = None
        users_db[target_user]["frozen_reason"] = None
        
        try:
            await bot.send_message(target_user, "✅ Профиль разморожен!")
        except:
            pass
        
        log_action(message.from_user, f"РАЗМОРОЗИЛ ПРОФИЛЬ {users_db[target_user]['username']}")
        await message.answer("✅ Профиль разморожен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.clear()
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Админ - отправляем запрос владельцу
    await message.answer(
        "⏳ <b>Запрос отправлен владельцу на одобрение!</b>\n\n"
        "Ожидайте подтверждения.",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_panel)
    
    await send_approval_request(
        message.from_user.id,
        "unfreeze",
        {"target_user": target_user}
    )

# ============================================
# ===== АДМИН: НАЗНАЧЕНИЕ СТАТУСА =====
# ============================================
@dp.message(F.text == "👑 Назначить статус")
async def admin_assign_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME:
        await message.answer("⛔ Только для владельца.")
        return
    
    await message.answer(
        "👑 Введите ID или @юзернейм пользователя:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_assign_user)

@dp.message(ScamStates.admin_assign_user)
async def admin_assign_user_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME:
        await message.answer("⛔ Только для владельца.")
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_kb)
        return
    
    await state.update_data(assign_target=target_user)
    await message.answer(
        "Выберите роль:\n"
        "admin - Админ\n"
        "moderator - Модератор\n"
        "support - Поддержка\n"
        "tester - Тестер\n"
        "vip - VIP\n"
        "worker - Работник\n"
        "user - Пользователь\n\n"
        "Введите название роли:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
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
        await message.answer("❌ Неверная роль.", reply_markup=back_kb)
        return
    
    data = await state.get_data()
    target_user = data.get("assign_target")
    if target_user is None:
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Удаляем из всех списков
    for lst in [ADMIN_IDS, MODERATOR_IDS, SUPPORT_IDS, TESTER_IDS, VIP_IDS, WORKER_IDS]:
        if target_user in lst:
            lst.remove(target_user)
    
    # Добавляем в нужный список
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
    
    role_name = {
        "admin": "Админ",
        "moderator": "Модератор",
        "support": "Поддержка",
        "tester": "Тестер",
        "vip": "VIP",
        "worker": "Работник",
        "user": "Пользователь"
    }.get(role, "Пользователь")
    
    log_action(message.from_user, f"НАЗНАЧИЛ СТАТУС {role_name} пользователю {users_db[target_user]['username']}")
    await notify_owner(message.from_user, f"👑 НАЗНАЧИЛ СТАТУС {role_name} пользователю {users_db[target_user]['username']}", send_to_dm=True)
    
    await message.answer(f"✅ Роль изменена на {role_name}", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН: СОЗДАНИЕ ЛОТА =====
# ============================================
@dp.message(F.text == "➕ Создать новый лот")
async def create_new_lot_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "➕ Введите номер лота:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_new_lot_number)

@dp.message(ScamStates.waiting_new_lot_number)
async def process_new_lot_number(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        number = int(message.text.strip())
        if number <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.", reply_markup=back_kb)
        return
    
    await state.update_data(new_lot_number=number)
    await message.answer("Введите количество кубков (например, 86к):", reply_markup=back_kb)
    await state.set_state(ScamStates.waiting_new_lot_cups)

@dp.message(ScamStates.waiting_new_lot_cups)
async def process_new_lot_cups(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    cups = message.text.strip()
    if not cups:
        await message.answer("❌ Введите количество кубков.", reply_markup=back_kb)
        return
    
    await state.update_data(new_lot_cups=cups)
    await message.answer("Введите количество бойцов:", reply_markup=back_kb)
    await state.set_state(ScamStates.waiting_new_lot_fighters)

@dp.message(ScamStates.waiting_new_lot_fighters)
async def process_new_lot_fighters(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        fighters = int(message.text.strip())
        if fighters <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.", reply_markup=back_kb)
        return
    
    await state.update_data(new_lot_fighters=fighters)
    await message.answer("Введите количество гемов:", reply_markup=back_kb)
    await state.set_state(ScamStates.waiting_new_lot_gems)

@dp.message(ScamStates.waiting_new_lot_gems)
async def process_new_lot_gems(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        gems = int(message.text.strip())
        if gems < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите неотрицательное число.", reply_markup=back_kb)
        return
    
    await state.update_data(new_lot_gems=gems)
    await message.answer("Введите цену в звёздах:", reply_markup=back_kb)
    await state.set_state(ScamStates.waiting_new_lot_price)

@dp.message(ScamStates.waiting_new_lot_price)
async def process_new_lot_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.", reply_markup=back_kb)
        return
    
    data = await state.get_data()
    number = data.get("new_lot_number")
    cups = data.get("new_lot_cups")
    fighters = data.get("new_lot_fighters")
    gems = data.get("new_lot_gems")
    
    lot_name = f"Лот {number}"
    
    # Проверяем, существует ли лот
    existing = None
    for idx, lot in enumerate(LOTS):
        if lot["name"] == lot_name:
            existing = idx
            break
    
    new_lot = {"name": lot_name, "cups": cups, "gems": gems, "fighters": fighters, "price": price}
    if existing is not None:
        LOTS[existing] = new_lot
        msg = f"🔄 Лот {number} обновлён!"
    else:
        LOTS.append(new_lot)
        msg = f"✅ Лот {number} создан!"
    
    log_action(message.from_user, f"СОЗДАЛ/ОБНОВИЛ ЛОТ {lot_name}")
    await notify_owner(message.from_user, f"➕ {msg} {lot_name}", send_to_dm=True)
    
    await message.answer(
        f"{msg}\n\n"
        f"📌 Данные лота:\n"
        f"🏆 Кубков: {cups}\n"
        f"⚔️ Бойцов: {fighters}\n"
        f"💎 Гемов: {gems}\n"
        f"💰 Цена: {price} ⭐",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )
    await state.clear()
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН: ТЕХПЕРЕРЫВ (С ЗАПРОСОМ) =====
# ============================================
@dp.message(F.text == "🛠 Включить перерыв")
async def enable_tech_break(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if tech_break_enabled:
        await message.answer("⚠️ Техперерыв уже включён.")
        return
    
    await message.answer(
        "🛠️ Введите дату и время окончания (ДД.ММ.ГГГГ ЧЧ:ММ):",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_tech_break_time)

@dp.message(ScamStates.waiting_tech_break_time)
async def process_tech_break_time(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
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
        end_dt = get_moscow_datetime().replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if end_dt <= get_moscow_datetime():
            raise ValueError
    except:
        await message.answer("❌ Неверный формат.", reply_markup=back_kb)
        return
    
    await state.update_data(tech_break_end=end_dt)
    await message.answer(
        "🛠️ Введите причину перерыва:",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_tech_break_reason)

@dp.message(ScamStates.waiting_tech_break_reason)
async def process_tech_break_reason(message: Message, state: FSMContext):
    global tech_break_enabled, tech_break_end, tech_break_reason
    
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    reason = message.text.strip()
    if not reason:
        await message.answer("❌ Причина не может быть пустой.", reply_markup=back_kb)
        return
    
    data = await state.get_data()
    end_dt = data.get("tech_break_end")
    if end_dt is None:
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Если владелец - выполняем сразу
    if message.from_user.id == OWNER_USERNAME:
        tech_break_end = end_dt
        tech_break_reason = reason
        tech_break_enabled = True
        
        await message.answer(
            f"✅ Техперерыв включён до {end_dt.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=admin_menu_kb,
            parse_mode="HTML"
        )
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Админ - отправляем запрос владельцу
    await message.answer(
        "⏳ <b>Запрос отправлен владельцу на одобрение!</b>\n\n"
        "Ожидайте подтверждения.",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_panel)
    
    await send_approval_request(
        message.from_user.id,
        "tech_on",
        {"end_dt": end_dt, "reason": reason}
    )

@dp.message(F.text == "⛔ Отключить перерыв")
async def disable_tech_break(message: Message, state: FSMContext):
    global tech_break_enabled, tech_break_end, tech_break_reason
    
    if not is_admin(message.from_user.id):
        return
    
    if not tech_break_enabled:
        await message.answer("ℹ️ Техперерыв не активен.", reply_markup=admin_menu_kb)
        return
    
    # Если владелец - выполняем сразу
    if message.from_user.id == OWNER_USERNAME:
        tech_break_enabled = False
        tech_break_end = None
        tech_break_reason = ""
        
        await message.answer("✅ Техперерыв отключён.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    
    # Админ - отправляем запрос владельцу
    await message.answer(
        "⏳ <b>Запрос отправлен владельцу на одобрение!</b>\n\n"
        "Ожидайте подтверждения.",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_panel)
    
    await send_approval_request(
        message.from_user.id,
        "tech_off",
        {}
    )

# ============================================
# ===== ОБРАБОТЧИКИ КНОПОК ВЛАДЕЛЬЦА =====
# ============================================
@dp.callback_query(F.data.startswith("approve_"))
async def approve_admin_request(callback: CallbackQuery):
    global tech_break_enabled, tech_break_end, tech_break_reason
    
    if callback.from_user.id != OWNER_USERNAME:
        await callback.answer("⛔ Только владелец!", show_alert=True)
        return
    
    data = callback.data.split("_")
    request_type = data[1]
    admin_id = int(data[2])
    
    await callback.answer("✅ Одобрено!", show_alert=True)
    await callback.message.delete()
    
    if request_type == "balance":
        target_user_id = int(data[3])
        amount = int(data[4])
        
        users_db[target_user_id]["balance"] += amount
        new_balance = users_db[target_user_id]["balance"]
        add_history(target_user_id, amount, "Пополнение (одобрено владельцем)")
        log_action(callback.from_user, f"ОДОБРИЛ ПОПОЛНЕНИЕ пользователю {users_db[target_user_id]['username']} на {amount} ⭐")
        
        try:
            await bot.send_message(admin_id, f"✅ Пополнение баланса пользователю [ID: {target_user_id}] на {amount} ⭐ выполнено.", parse_mode="HTML")
        except:
            pass
        
        try:
            await bot.send_message(target_user_id, f"💰 <b>Ваш баланс пополнен!</b>\n\nСумма: <b>+{amount} ⭐</b>\n📊 Новый баланс: <b>{new_balance} ⭐</b>", parse_mode="HTML")
        except:
            pass
        
        await callback.message.answer(f"✅ Пополнение выполнено! Новый баланс: {new_balance} ⭐", parse_mode="HTML")
        
    elif request_type == "freeze":
        target_user_id = int(data[3])
        frozen_until = data[4]
        reason = "_".join(data[5:]) if len(data) > 5 else "Не указана"
        
        if frozen_until == "forever":
            users_db[target_user_id]["frozen_until"] = "forever"
        else:
            try:
                frozen_dt = datetime.strptime(frozen_until, "%Y-%m-%d %H:%M:%S")
                users_db[target_user_id]["frozen_until"] = frozen_dt
            except:
                users_db[target_user_id]["frozen_until"] = frozen_until
        
        users_db[target_user_id]["frozen_reason"] = reason
        until_str = "НАВСЕГДА" if frozen_until == "forever" else datetime.strptime(frozen_until, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M") + " (МСК)"
        
        try:
            await bot.send_message(admin_id, f"✅ Заморозка профиля [ID: {target_user_id}] выполнена до {until_str}", parse_mode="HTML")
        except:
            pass
        
        try:
            await bot.send_message(target_user_id, f"❄️ <b>Ваш профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}", parse_mode="HTML")
        except:
            pass
        
        await callback.message.answer(f"✅ Заморозка выполнена до {until_str}", parse_mode="HTML")
        
    elif request_type == "unfreeze":
        target_user_id = int(data[3])
        users_db[target_user_id]["frozen_until"] = None
        users_db[target_user_id]["frozen_reason"] = None
        
        try:
            await bot.send_message(admin_id, f"✅ Разморозка профиля [ID: {target_user_id}] выполнена.", parse_mode="HTML")
        except:
            pass
        
        try:
            await bot.send_message(target_user_id, f"✅ <b>Ваш профиль разморожен!</b>\n\nТеперь вам доступны все функции бота.", parse_mode="HTML")
        except:
            pass
        
        await callback.message.answer(f"✅ Разморозка выполнена.", parse_mode="HTML")
        
    elif request_type == "tech_on":
        end_dt_str = data[3]
        reason = "_".join(data[4:]) if len(data) > 4 else "Не указана"
        end_dt = datetime.strptime(end_dt_str, "%Y%m%d%H%M")
        
        tech_break_end = end_dt
        tech_break_reason = reason
        tech_break_enabled = True
        
        try:
            await bot.send_message(admin_id, f"✅ Техперерыв включён до {end_dt.strftime('%d.%m.%Y %H:%M')}", parse_mode="HTML")
        except:
            pass
        
        await callback.message.answer(f"✅ Техперерыв включён до {end_dt.strftime('%d.%m.%Y %H:%M')}", parse_mode="HTML")
        
    elif request_type == "tech_off":
        tech_break_enabled = False
        tech_break_end = None
        tech_break_reason = ""
        
        try:
            await bot.send_message(admin_id, f"✅ Техперерыв отключён.", parse_mode="HTML")
        except:
            pass
        
        await callback.message.answer(f"✅ Техперерыв отключён.", parse_mode="HTML")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_admin_request(callback: CallbackQuery):
    if callback.from_user.id != OWNER_USERNAME:
        await callback.answer("⛔ Только владелец!", show_alert=True)
        return
    
    data = callback.data.split("_")
    request_type = data[1]
    admin_id = int(data[2])
    
    await callback.answer("❌ Отклонено!", show_alert=True)
    await callback.message.delete()
    
    # Замораживаем админа на 1 час
    await freeze_admin_account(admin_id, 1)
    
    try:
        await bot.send_message(
            admin_id,
            f"❌ <b>Действие отклонено владельцем!</b>\n\n"
            f"❄️ <b>Ваш аккаунт заморожен на 1 час!</b>\n\n"
            f"📌 Причина: Отказ в одобрении действия.",
            parse_mode="HTML"
        )
    except:
        pass
    
    await callback.message.answer(f"❌ Действие отклонено. Админ заморожен на 1 час.", parse_mode="HTML")

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
        if is_admin(message.from_user.id):
            await admin_panel_request(message, state)
        else:
            await state.clear()
            await show_main_menu(message)
        return
    
    if current_state in [ScamStates.waiting_withdraw_amount, ScamStates.waiting_withdraw_card]:
        await show_profile(message, state)
        return
    
    if current_state == ScamStates.waiting_gems_amount:
        await handle_donate(message, state)
        return
    
    if current_state == ScamStates.waiting_support:
        await state.clear()
        await show_main_menu(message)
        return
    
    if current_state == ScamStates.worker_task_comments:
        await state.clear()
        await show_main_menu(message)
        return
    
    await state.clear()
    await show_main_menu(message)

# ============================================
# ===== ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ =====
# ============================================
@dp.message()
async def catch_all_messages(message: Message, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state == ScamStates.waiting_gems_amount:
        await message.answer("💎 Введите количество гемов (число).", reply_markup=back_kb)
    elif current_state == ScamStates.waiting_support:
        await message.answer("📩 Отправьте текстовое сообщение.", reply_markup=support_kb)
    elif current_state == ScamStates.waiting_withdraw_amount:
        await message.answer("💰 Введите сумму вывода.", reply_markup=back_kb)
    elif current_state == ScamStates.waiting_withdraw_card:
        await message.answer("💳 Введите номер карты.", reply_markup=back_kb)
    elif current_state == ScamStates.worker_task_comments:
        await message.answer("👷 Введите количество комментариев.", reply_markup=back_kb)
    else:
        await message.answer("❓ Используйте кнопки меню.", reply_markup=main_menu_kb)

# ============================================
# ===== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ МЕНЮ =====
# ============================================
async def show_main_menu(message: Message):
    user_id = message.from_user.id
    
    if user_id == OWNER_USERNAME:
        await message.answer("❓ Меню:", reply_markup=owner_menu_kb)
    elif is_admin(user_id):
        await message.answer("❓ Меню:", reply_markup=admin_menu_kb)
    elif is_moderator(user_id):
        await message.answer("❓ Меню:", reply_markup=moderator_menu_kb)
    elif is_worker(user_id):
        await message.answer("❓ Меню:", reply_markup=worker_menu_kb)
    else:
        await message.answer("❓ Меню:", reply_markup=main_menu_kb)

# ============================================
# ===== ЗАПУСК БОТА =====
# ============================================
async def main():
    print("=" * 60)
    print("🤖 БОТ ЗАПУЩЕН (ПОЛНАЯ ВЕРСИЯ С ЗАПРОСАМИ)")
    print("=" * 60)
    print("✅ Все функции активны:")
    print("   - 👤 Профиль и вывод средств")
    print("   - 🛒 Покупка (донат, гемы, лоты)")
    print("   - 👷 Система работников")
    print("   - 📩 Поддержка и модерация")
    print("   - 👑 Полная админ-панель")
    print("   - ❄️ Заморозка/разморозка профилей")
    print("   - 👑 Назначение статусов")
    print("   - ➕ Создание лотов")
    print("   - 🛠 Технический перерыв")
    print("   - 📝 Логирование в файл")
    print("   - 🔔 Запросы к владельцу (approve/reject)")
    print("=" * 60)
    print("📌 Данные хранятся в памяти (при перезапуске сбрасываются)")
    print("📁 Логи ошибок: bot_errors.log")
    print("=" * 60)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
  
