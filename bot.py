import asyncio
import sqlite3
import logging
import os
from datetime import datetime, timedelta
from contextlib import contextmanager
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from typing import Optional
from dotenv import load_dotenv

# ============================================
# ===== НАСТРОЙКА =====
# ============================================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "8737854157:AAGWl9bHKkRGNmvseyKwcXhH-1ei2pCcyZE")
OWNER_USERNAME = int(os.getenv("OWNER_USERNAME", "8985475819"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "19102012")

logging.basicConfig(level=logging.ERROR)

# ============================================
# ===== БАЗА ДАННЫХ =====
# ============================================
class Database:
    def __init__(self, db_path="bot_database.db"):
        self.db_path = db_path
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    username TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    balance INTEGER DEFAULT 0,
                    frozen_until TEXT,
                    frozen_reason TEXT
                )
            ''')
            
            # Таблица истории
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    time TEXT,
                    amount INTEGER,
                    description TEXT
                )
            ''')
            
            # Таблица логов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actions_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    user_id INTEGER,
                    username TEXT,
                    user_fullname TEXT,
                    action TEXT
                )
            ''')
            
            # Таблица лотов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS lots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    cups TEXT,
                    gems INTEGER,
                    fighters INTEGER,
                    price INTEGER
                )
            ''')
            
            # Таблица ролей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_roles (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT
                )
            ''')
            
            # Таблица заданий работников
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    user_id INTEGER PRIMARY KEY,
                    comments INTEGER,
                    submitted INTEGER DEFAULT 0,
                    start_time TEXT,
                    reward INTEGER
                )
            ''')
            
            # Индексы для скорости
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users (username)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_user_id ON history (user_id)')
            
            # Начальные лоты
            cursor.execute('SELECT COUNT(*) FROM lots')
            if cursor.fetchone()[0] == 0:
                initial_lots = [
                    ("Лот 1", "86к", 23, 104, 1600),
                    ("Лот 2", "45к", 6, 104, 800),
                    ("Лот 3", "9к", 73, 40, 270),
                    ("Лот 4", "57772", 38, 104, 2100),
                    ("Лот 5", "42753", 37, 97, 1000),
                    ("Лот 6", "19840", 75, 59, 1100),
                    ("Лот 7", "43164", 27, 75, 5000),
                ]
                cursor.executemany(
                    'INSERT INTO lots (name, cups, gems, fighters, price) VALUES (?, ?, ?, ?, ?)',
                    initial_lots
                )
    
    def get_user(self, user_id: int) -> Optional[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_user_by_username(self, username: str) -> Optional[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            username = username.lstrip('@').lower()
            cursor.execute('SELECT * FROM users WHERE LOWER(username) = ?', (f"@{username}",))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def create_or_update_user(self, user_id: int, name: str, username: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = get_moscow_time()
            existing = self.get_user(user_id)
            if existing:
                cursor.execute(
                    'UPDATE users SET name = ?, username = ?, last_seen = ? WHERE id = ?',
                    (name, username, now, user_id)
                )
            else:
                cursor.execute(
                    'INSERT INTO users (id, name, username, first_seen, last_seen, balance) VALUES (?, ?, ?, ?, ?, ?)',
                    (user_id, name, username, now, now, 0)
                )
    
    def update_balance(self, user_id: int, amount: int) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT balance FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            if not row:
                return 0
            new_balance = row[0] + amount
            cursor.execute('UPDATE users SET balance = ? WHERE id = ?', (new_balance, user_id))
            return new_balance
    
    def add_history(self, user_id: int, amount: int, description: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = get_moscow_time()
            cursor.execute(
                'INSERT INTO history (user_id, time, amount, description) VALUES (?, ?, ?, ?)',
                (user_id, now, amount, description)
            )
            # Ограничиваем историю 100 записями
            cursor.execute(
                'DELETE FROM history WHERE id IN (SELECT id FROM history WHERE user_id = ? ORDER BY time DESC LIMIT -1 OFFSET 100)',
                (user_id,)
            )
    
    def get_history(self, user_id: int, limit: int = 20) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT time, amount, description FROM history WHERE user_id = ? ORDER BY time DESC LIMIT ?',
                (user_id, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def add_action_log(self, user_id: int, username: str, fullname: str, action: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = get_moscow_time()
            cursor.execute(
                'INSERT INTO actions_log (time, user_id, username, user_fullname, action) VALUES (?, ?, ?, ?, ?)',
                (now, user_id, username, fullname, action)
            )
            # Ограничиваем лог 1000 записями
            cursor.execute(
                'DELETE FROM actions_log WHERE id IN (SELECT id FROM actions_log ORDER BY time DESC LIMIT -1 OFFSET 1000)'
            )
    
    def get_actions_log(self, limit: int = 20) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT time, username, user_fullname, action FROM actions_log ORDER BY time DESC LIMIT ?',
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_users(self, limit: int = 20) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users ORDER BY id LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_user_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users')
            return cursor.fetchone()[0]
    
    def set_frozen(self, user_id: int, frozen_until: str, reason: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET frozen_until = ?, frozen_reason = ? WHERE id = ?',
                (frozen_until, reason, user_id)
            )
    
    def clear_frozen(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET frozen_until = NULL, frozen_reason = NULL WHERE id = ?',
                (user_id,)
            )
    
    def set_user_role(self, user_id: int, role: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO user_roles (user_id, role) VALUES (?, ?)',
                (user_id, role)
            )
    
    def get_user_role(self, user_id: int) -> Optional[str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT role FROM user_roles WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return row[0] if row else None
    
    def get_users_by_role(self, role: str) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM user_roles WHERE role = ?', (role,))
            return [row[0] for row in cursor.fetchall()]
    
    def get_lots(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM lots ORDER BY id')
            return [dict(row) for row in cursor.fetchall()]
    
    def create_or_update_lot(self, lot_id: Optional[int], name: str, cups: str, gems: int, fighters: int, price: int) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if lot_id:
                cursor.execute(
                    'UPDATE lots SET name = ?, cups = ?, gems = ?, fighters = ?, price = ? WHERE id = ?',
                    (name, cups, gems, fighters, price, lot_id)
                )
                return lot_id
            else:
                cursor.execute(
                    'INSERT INTO lots (name, cups, gems, fighters, price) VALUES (?, ?, ?, ?, ?)',
                    (name, cups, gems, fighters, price)
                )
                return cursor.lastrowid
    
    def create_task(self, user_id: int, comments: int, reward: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = get_moscow_time()
            cursor.execute(
                'INSERT OR REPLACE INTO tasks (user_id, comments, submitted, start_time, reward) VALUES (?, ?, 0, ?, ?)',
                (user_id, comments, now, reward)
            )
    
    def get_task(self, user_id: int) -> Optional[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM tasks WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_task_submitted(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE tasks SET submitted = submitted + 1 WHERE user_id = ?',
                (user_id,)
            )
    
    def delete_task(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tasks WHERE user_id = ?', (user_id,))

db = Database()

# ============================================
# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
# ============================================
def get_moscow_datetime():
    return datetime.now() + timedelta(hours=3)

def get_moscow_time():
    return get_moscow_datetime().strftime("%Y-%m-%d %H:%M:%S")

def parse_datetime(dt_str: str):
    return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")

def get_user_role_from_db(user_id: int) -> tuple:
    role = db.get_user_role(user_id)
    if user_id == OWNER_USERNAME:
        return "Владелец", "👑"
    if role == "admin":
        return "Админ", "🛡️"
    if role == "moderator":
        return "Модератор", "🛠️"
    if role == "support":
        return "Поддержка", "🎧"
    if role == "tester":
        return "Тестер", "🧪"
    if role == "vip":
        return "VIP", "💎"
    if role == "worker":
        return "Работник", "👷"
    return "Пользователь", "👤"

def is_admin(user_id: int) -> bool:
    if user_id == OWNER_USERNAME:
        return True
    return db.get_user_role(user_id) == "admin"

def is_moderator(user_id: int) -> bool:
    return db.get_user_role(user_id) == "moderator"

def is_support(user_id: int) -> bool:
    return db.get_user_role(user_id) == "support"

def is_tester(user_id: int) -> bool:
    return db.get_user_role(user_id) == "tester"

def is_vip(user_id: int) -> bool:
    return db.get_user_role(user_id) == "vip"

def is_worker(user_id: int) -> bool:
    return db.get_user_role(user_id) == "worker"

def get_vip_discount(user_id: int) -> float:
    return 0.9 if is_vip(user_id) else 1.0

def get_infinite_balance(user_id: int) -> bool:
    return user_id == OWNER_USERNAME or is_admin(user_id)

def is_user_frozen(user_id: int) -> tuple:
    user_data = db.get_user(user_id)
    if not user_data:
        return False, None, None
    frozen_until = user_data.get("frozen_until")
    frozen_reason = user_data.get("frozen_reason")
    if not frozen_until:
        return False, None, None
    if frozen_until == "forever":
        return True, "навсегда", frozen_reason
    try:
        until_dt = parse_datetime(frozen_until)
        if get_moscow_datetime() < until_dt:
            return True, until_dt, frozen_reason
        else:
            db.clear_frozen(user_id)
            return False, None, None
    except:
        db.clear_frozen(user_id)
        return False, None, None

def get_photo_hash(photo) -> str:
    import hashlib
    return hashlib.md5(photo.file_id.encode()).hexdigest()

def find_user(identifier: str) -> Optional[int]:
    identifier = identifier.strip()
    if identifier.startswith('@'):
        user_data = db.get_user_by_username(identifier)
        return user_data["id"] if user_data else None
    else:
        try:
            user_id = int(identifier)
            user_data = db.get_user(user_id)
            return user_data["id"] if user_data else None
        except ValueError:
            return None

def log_action(user: types.User, action: str):
    db.add_action_log(
        user.id,
        f"@{user.username}" if user.username else "без юзернейма",
        user.full_name or "без имени",
        action
    )

def track_user(user: types.User):
    db.create_or_update_user(
        user.id,
        user.full_name or "без имени",
        f"@{user.username}" if user.username else "без юзернейма"
    )

async def notify_owner(user: types.User, action: str, send_to_dm: bool = False):
    log_action(user, action)
    if send_to_dm:
        try:
            await bot.send_message(OWNER_USERNAME, f"🔔 <b>Действие пользователя</b>\n\n{action}", parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка отправки уведомления: {e}")

# ============================================
# ===== ТЕХНИЧЕСКИЙ ПЕРЕРЫВ =====
# ============================================
tech_break_enabled = False
tech_break_end = None
tech_break_reason = ""

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
# ===== МИДЛВАРЫ (ДЛЯ AIOGRAM 3.x) =====
# ============================================
class RegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = event.from_user
        if user and not db.get_user(user.id):
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

# ===== ДЕКОРАТОРЫ =====
def admin_required(func):
    async def wrapper(message, *args, **kwargs):
        if not is_admin(message.from_user.id):
            await message.answer("⛔ Доступ запрещён.")
            return
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
        return await func(message, *args, **kwargs)
    return wrapper

def owner_required(func):
    async def wrapper(message, *args, **kwargs):
        if message.from_user.id != OWNER_USERNAME:
            await message.answer("⛔ Только для владельца.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

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

back_to_main_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

DONATE_ITEMS = [
    {"name": "БП+", "price": 550},
    {"name": "БП", "price": 400},
]

# Глобальный словарь для хешей скринов работников
worker_photo_hashes = {}

# ============================================
# ===== ИНИЦИАЛИЗАЦИЯ =====
# ============================================
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

dp.message.outer_middleware(RegistrationMiddleware())
dp.message.outer_middleware(TechBreakMiddleware())
dp.callback_query.outer_middleware(TechBreakMiddleware())

# ============================================
# ===== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ МЕНЮ =====
# ============================================
async def show_main_menu(message: Message):
    user_id = message.from_user.id
    role = db.get_user_role(user_id)
    
    if user_id == OWNER_USERNAME:
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=owner_menu_kb, parse_mode="HTML")
    elif role == "admin":
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
    elif role == "moderator":
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=moderator_menu_kb, parse_mode="HTML")
    elif role == "worker":
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=worker_menu_kb, parse_mode="HTML")
    else:
        await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=main_menu_kb, parse_mode="HTML")

# ============================================
# ===== ХЕНДЛЕР START =====
# ============================================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    track_user(message.from_user)
    await notify_owner(message.from_user, "ЗАПУСТИЛ БОТА (/start)")
    await state.clear()
    await state.set_state(ScamStates.main_menu)
    await show_main_menu(message)

# ============================================
# ===== ПРОФИЛЬ =====
# ============================================
@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message, state: FSMContext):
    user_data = db.get_user(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        return
    
    balance = user_data.get("balance", 0)
    username = user_data.get("username", "без юзернейма")
    name = user_data.get("name", "без имени")
    role, emoji = get_user_role_from_db(message.from_user.id)
    
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
    history = db.get_history(message.from_user.id)
    if not history:
        await message.answer("📜 <b>История операций пуста</b>", reply_markup=profile_kb, parse_mode="HTML")
        return
    
    text = "📜 <b>История операций (последние 20):</b>\n\n"
    for entry in history:
        sign = "+" if entry["amount"] >= 0 else ""
        text += f"🕒 {entry['time']}\n   {sign}{entry['amount']} ⭐ — {entry['description']}\n\n"
    await message.answer(text, reply_markup=profile_kb, parse_mode="HTML")

@dp.message(F.text == "💰 Пополнить баланс")
async def handle_balance_topup(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if is_admin(message.from_user.id) and current_state == ScamStates.admin_panel:
        await admin_balance_start(message, state)
        return
    if message.from_user.id == OWNER_USERNAME:
        await message.answer("👑 Вы владелец. Используйте админ-панель.", reply_markup=profile_kb, parse_mode="HTML")
    else:
        await message.answer(
            "💳 <b>Пополнение баланса</b>\n\n"
            "Обратитесь в поддержку: @suport_skup_bs_bot",
            reply_markup=profile_kb, parse_mode="HTML"
        )

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
        await message.answer(
            f"❄️ <b>Ваш профиль заморожен!</b>\n\n"
            f"⏰ До: {until_str}\n"
            f"📌 Причина: {reason}\n\n"
            f"Данная функция вам недоступна.",
            reply_markup=profile_kb, parse_mode="HTML"
        )
        return
    
    user_data = db.get_user(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        return
    
    await message.answer(
        f"💰 <b>Вывод средств</b>\n\n"
        f"Ваш текущий баланс: <b>{user_data['balance']} ⭐</b>\n\n"
        f"Введите сумму, которую хотите вывести (целое число):\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
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
        await message.answer(
            "❌ Введите положительное целое число (например, 100).\n\n"
            "Попробуйте ещё раз или нажмите 'Назад'.",
            reply_markup=back_to_main_kb, parse_mode="HTML"
        )
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(
            f"❄️ <b>Ваш профиль заморожен!</b>\n\n"
            f"⏰ До: {until_str}\n"
            f"📌 Причина: {reason}\n\n"
            f"Данная функция вам недоступна.",
            reply_markup=profile_kb, parse_mode="HTML"
        )
        await state.clear()
        return
    
    user_data = db.get_user(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        await state.clear()
        return
    
    balance = user_data.get("balance", 0)
    if amount > balance:
        await message.answer(
            f"❌ <b>Недостаточно средств!</b>\n\n"
            f"Ваш баланс: <b>{balance} ⭐</b>\n"
            f"Запрошено: <b>{amount} ⭐</b>\n\n"
            f"Пожалуйста, введите сумму, не превышающую баланс.\n"
            f"Или нажмите 'Назад' для отмены.",
            reply_markup=back_to_main_kb, parse_mode="HTML"
        )
        return
    
    await state.update_data(withdraw_amount=amount)
    await message.answer(
        f"✅ Сумма <b>{amount} ⭐</b> принята.\n\n"
        f"Теперь введите <b>номер карты</b> для вывода.\n"
        f"Допустимые длины: <b>13</b>, <b>15</b>, <b>16</b>, <b>18</b> или <b>19</b> цифр.\n\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_withdraw_card)

@dp.message(ScamStates.waiting_withdraw_card)
async def process_withdraw_card(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await show_profile(message, state)
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(
            f"❄️ <b>Ваш профиль заморожен!</b>\n\n"
            f"⏰ До: {until_str}\n"
            f"📌 Причина: {reason}\n\n"
            f"Данная функция вам недоступна.",
            reply_markup=profile_kb, parse_mode="HTML"
        )
        await state.clear()
        return
    
    card_number = message.text.replace(" ", "").replace("-", "")
    if not card_number.isdigit():
        await message.answer(
            "❌ Номер карты должен содержать <b>только цифры</b>.\n\n"
            "Попробуйте ещё раз или нажмите 'Назад'.",
            reply_markup=back_to_main_kb, parse_mode="HTML"
        )
        return
    
    valid_lengths = [13, 15, 16, 18, 19]
    if len(card_number) not in valid_lengths:
        await message.answer(
            f"❌ Номер карты должен содержать <b>13, 15, 16, 18 или 19</b> цифр.\n"
            f"Вы ввели <b>{len(card_number)}</b> цифр.\n\n"
            f"Попробуйте ещё раз или нажмите 'Назад'.",
            reply_markup=back_to_main_kb, parse_mode="HTML"
        )
        return
    
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    if amount is None:
        await message.answer("❌ Ошибка: сумма не найдена. Начните заново.", reply_markup=profile_kb)
        await state.clear()
        return
    
    user_id = message.from_user.id
    user_data = db.get_user(user_id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        await state.clear()
        return
    
    if amount > user_data["balance"]:
        await message.answer(
            f"❌ Недостаточно средств! Баланс изменился.\n"
            f"Текущий баланс: <b>{user_data['balance']} ⭐</b>\n\n"
            f"Начните процесс вывода заново через профиль.",
            reply_markup=profile_kb, parse_mode="HTML"
        )
        await state.clear()
        return
    
    new_balance = db.update_balance(user_id, -amount)
    db.add_history(user_id, -amount, "Вывод средств")
    log_action(message.from_user, f"ВЫВЕЛ {amount} ⭐ на карту {card_number[:4]}...{card_number[-4:]}")
    await notify_owner(message.from_user, f"💸 <b>ВЫВОД СРЕДСТВ</b>\n👤 {user_data['username']} (ID: {user_id})\n💰 {amount} ⭐\n💳 {card_number[:4]}...{card_number[-4:]}", send_to_dm=True)
    
    commission = amount * 0.05
    await message.answer(
        f"✅ <b>Отлично!</b>\n\n"
        f"Средства в размере <b>{amount} ⭐</b> будут зачислены в течение <b>2-3 недель</b>.\n"
        f"Комиссия: <b>{commission:.2f} ⭐</b>\n\n"
        f"Ваш новый баланс: <b>{new_balance} ⭐</b>",
        reply_markup=profile_kb, parse_mode="HTML"
    )
    await state.clear()

# ============================================
# ===== КУПИТЬ =====
# ============================================
@dp.message(F.text == "🛒 Купить")
async def handle_buy_choice(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>", reply_markup=main_menu_kb, parse_mode="HTML")
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(
            f"❄️ <b>Ваш профиль заморожен!</b>\n\n"
            f"⏰ До: {until_str}\n"
            f"📌 Причина: {reason}\n\n"
            f"Данная функция вам недоступна.",
            reply_markup=main_menu_kb, parse_mode="HTML"
        )
        return
    
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'КУПИТЬ'")
    await message.answer("🛒 <b>Что вас интересует?</b>", reply_markup=buy_choice_kb, parse_mode="HTML")
  # ============================================
# ===== ДОНАТ =====
# ============================================
@dp.message(F.text == "⭐ Донат")
async def handle_donate(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить БП+ за 0 ⭐", callback_data="donate_buy_бпп")],
            [InlineKeyboardButton(text="🛒 Купить БП за 0 ⭐", callback_data="donate_buy_бп")],
            [InlineKeyboardButton(text="💎 Купить гемы", callback_data="donate_gems")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="donate_back")]
        ])
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>", reply_markup=keyboard, parse_mode="HTML")
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(
            f"❄️ <b>Ваш профиль заморожен!</b>\n\n"
            f"⏰ До: {until_str}\n"
            f"📌 Причина: {reason}",
            reply_markup=buy_choice_kb, parse_mode="HTML"
        )
        return
    
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'ДОНАТ'")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for item in DONATE_ITEMS:
        price = item['price']
        if is_vip(message.from_user.id):
            price = int(price * 0.9)
            label = f"🛒 Купить {item['name']} за {price} ⭐ (VIP скидка 10%)"
        else:
            label = f"🛒 Купить {item['name']} за {price} ⭐"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"donate_buy_{item['name'].lower().replace('+', 'p')}")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="💎 Купить гемы", callback_data="donate_gems")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="donate_back")])
    await message.answer("⭐ <b>Выберите товар:</b>", reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("donate_buy_"))
async def process_donate_buy(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    
    if get_infinite_balance(user.id):
        await callback.answer("♾️ Бесконечный баланс", show_alert=True)
        item_key = callback.data.split("_")[2]
        target_item = next((item for item in DONATE_ITEMS if item['name'].lower().replace('+', 'p').replace(' ', '') == item_key), None)
        if target_item:
            db.add_history(user.id, 0, f"Покупка {target_item['name']} (бесконечный баланс)")
            await callback.message.answer(f"✅ Вы приобрели <b>{target_item['name']}</b> (бесконечный баланс). 🎉", parse_mode="HTML")
        await callback.answer()
        return
    
    frozen, until, reason = is_user_frozen(user.id)
    if frozen:
        await callback.answer("❄️ Профиль заморожен", show_alert=True)
        return
    
    item_key = callback.data.split("_")[2]
    target_item = next((item for item in DONATE_ITEMS if item['name'].lower().replace('+', 'p').replace(' ', '') == item_key), None)
    if not target_item:
        await callback.answer("❌ Товар не найден.", show_alert=True)
        return
    
    user_data = db.get_user(user.id)
    if not user_data:
        await callback.answer("❌ Вы не зарегистрированы.", show_alert=True)
        return
    
    price = target_item['price']
    discount = get_vip_discount(user.id)
    final_price = int(price * discount)
    balance = user_data.get('balance', 0)
    
    if balance < final_price:
        await callback.answer("❌ Недостаточно средств!", show_alert=True)
        return
    
    new_balance = db.update_balance(user.id, -final_price)
    db.add_history(user.id, -final_price, f"Покупка {target_item['name']}")
    await notify_owner(user, f"⭐ ПОКУПКА ДОНАТА\n👤 {user_data['username']}\n🎯 {target_item['name']}\n💰 {final_price} ⭐", send_to_dm=True)
    
    await callback.message.answer(
        f"✅ Вы приобрели <b>{target_item['name']}</b> за {final_price} ⭐.\n"
        f"📊 Новый баланс: {new_balance} ⭐ 🎉",
        parse_mode="HTML"
    )
    await callback.answer("✅ Покупка успешна!")

@dp.callback_query(F.data == "donate_gems")
async def process_donate_gems(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    
    if get_infinite_balance(user.id):
        await callback.answer("♾️ Бесконечный баланс", show_alert=True)
        await callback.message.answer(
            "💎 <b>Покупка гемов (бесконечный баланс)</b>\n\n"
            "Введите количество гемов.\n"
            "Цена: <b>1 гем = 0 ⭐</b>\n\n"
            "🔙 Для отмены нажмите 'Назад'.",
            reply_markup=back_to_main_kb, parse_mode="HTML"
        )
        await state.set_state(ScamStates.waiting_gems_amount)
        return
    
    frozen, until, reason = is_user_frozen(user.id)
    if frozen:
        await callback.answer("❄️ Профиль заморожен", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.answer(
        "💎 <b>Покупка гемов</b>\n\n"
        "Введите количество гемов.\n"
        "Цена: <b>1 гем = 4.5 ⭐</b>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
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
            await message.answer("❌ Введите положительное число.", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
        db.add_history(message.from_user.id, 0, f"Покупка {gems_count} гемов (бесконечный баланс)")
        await message.answer(f"✅ Вы приобрели <b>{gems_count} гемов</b> (бесконечный баланс). 🎉", reply_markup=back_to_main_kb, parse_mode="HTML")
        await state.clear()
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        await message.answer("❄️ Профиль заморожен.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    try:
        gems_count = float(message.text.replace(",", "."))
        if gems_count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    stars = round(gems_count * 4.5)
    user_id = message.from_user.id
    user_data = db.get_user(user_id)
    if not user_data:
        await message.answer("⚠️ Ошибка.", reply_markup=back_to_main_kb)
        await state.clear()
        return
    
    discount = get_vip_discount(user_id)
    final_price = int(stars * discount)
    balance = user_data.get('balance', 0)
    
    if balance < final_price:
        await message.answer(
            f"❌ Недостаточно средств! Нужно: {final_price} ⭐, у вас: {balance} ⭐",
            reply_markup=back_to_main_kb, parse_mode="HTML"
        )
        return
    
    new_balance = db.update_balance(user_id, -final_price)
    db.add_history(user_id, -final_price, f"Покупка гемов {gems_count}шт")
    await notify_owner(message.from_user, f"💎 ПОКУПКА ГЕМОВ\n👤 {user_data['username']}\n💎 {gems_count} гемов\n💰 {final_price} ⭐", send_to_dm=True)
    
    await message.answer(
        f"✅ Вы приобрели <b>{gems_count} гемов</b> за {final_price} ⭐.\n"
        f"📊 Новый баланс: {new_balance} ⭐ 🎉",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.clear()

@dp.callback_query(F.data == "donate_back")
async def donate_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    await handle_buy_choice(callback.message, state)

# ============================================
# ===== АККАУНТ (ЛОТЫ) =====
# ============================================
@dp.message(F.text == "📱 Аккаунт")
async def handle_account_buy(message: Message, state: FSMContext):
    if get_infinite_balance(message.from_user.id):
        await message.answer("♾️ <b>У вас бесконечный баланс.</b>", reply_markup=buy_choice_kb, parse_mode="HTML")
        return
    
    frozen, until, reason = is_user_frozen(message.from_user.id)
    if frozen:
        until_str = "НАВСЕГДА" if until == "навсегда" else until.strftime("%d.%m.%Y %H:%M") + " (МСК)"
        await message.answer(
            f"❄️ <b>Ваш профиль заморожен!</b>\n\n"
            f"⏰ До: {until_str}\n"
            f"📌 Причина: {reason}",
            reply_markup=buy_choice_kb, parse_mode="HTML"
        )
        return
    
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'АККАУНТ'")
    lots = db.get_lots()
    text = "🛒 <b>Выберите лот:</b>\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for lot in lots:
        price = lot['price']
        if is_vip(message.from_user.id):
            price = int(price * 0.9)
            text += f"━━━━━━━━━━━━━━━━━━━━━\n🎯 <b>{lot['name']}</b>\n🏆 {lot['cups']} кубков\n💎 {lot['gems']} гемов\n⚔️ {lot['fighters']} бойцов\n💰 <b>Цена: {price} ⭐ (VIP скидка 10%)</b>\n"
        else:
            text += f"━━━━━━━━━━━━━━━━━━━━━\n🎯 <b>{lot['name']}</b>\n🏆 {lot['cups']} кубков\n💎 {lot['gems']} гемов\n⚔️ {lot['fighters']} бойцов\n💰 <b>Цена: {price} ⭐</b>\n"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"🛒 Купить {lot['name']}", callback_data=f"buy_lot_{lot['id']}")])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_lot_"))
async def process_buy_lot(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    lot_id = int(callback.data.split("_")[2])
    lots = db.get_lots()
    lot = next((l for l in lots if l['id'] == lot_id), None)
    
    if not lot:
        await callback.answer("❌ Лот не найден.", show_alert=True)
        return
    
    if get_infinite_balance(user.id):
        await callback.answer("♾️ Бесконечный баланс", show_alert=True)
        db.add_history(user.id, 0, f"Покупка {lot['name']} (бесконечный баланс)")
        await callback.message.answer(f"✅ Вы купили <b>{lot['name']}</b> (бесконечный баланс). 🎉", parse_mode="HTML")
        await callback.answer()
        return
    
    frozen, until, reason = is_user_frozen(user.id)
    if frozen:
        await callback.answer("❄️ Профиль заморожен", show_alert=True)
        return
    
    price = lot["price"]
    discount = get_vip_discount(user.id)
    final_price = int(price * discount)
    user_data = db.get_user(user.id)
    
    if not user_data:
        await callback.answer("❌ Вы не зарегистрированы.", show_alert=True)
        return
    
    balance = user_data.get("balance", 0)
    if balance < final_price:
        await callback.answer("❌ Недостаточно средств!", show_alert=True)
        return
    
    new_balance = db.update_balance(user.id, -final_price)
    db.add_history(user.id, -final_price, f"Покупка {lot['name']}")
    await notify_owner(user, f"🛒 ПОКУПКА ЛОТА\n👤 {user_data['username']}\n🎯 {lot['name']}\n💰 {final_price} ⭐", send_to_dm=True)
    
    await callback.message.answer(
        f"✅ Вы купили <b>{lot['name']}</b> за {final_price} ⭐.\n"
        f"📊 Новый баланс: {new_balance} ⭐ 🎉",
        parse_mode="HTML"
    )
    await callback.answer("✅ Покупка успешна!")

# ============================================
# ===== ПРОДАЖА =====
# ============================================
@dp.message(F.text == "💰 Продать")
async def handle_sell(message: Message, state: FSMContext):
    await message.answer(
        "💰 <b>Продажа аккаунта</b>\n\n"
        "Если вы хотите продать свой аккаунт Brawl Stars, свяжитесь с нами:\n"
        "👤 <b>@suport_skup_bs_bot</b>\n\n"
        "Мы предложим лучшую цену! 🤝",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )

# ============================================
# ===== ЗАРАБОТОК =====
# ============================================
@dp.message(F.text == "💸 Заработать деньги")
async def handle_earn_money(message: Message, state: FSMContext):
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'ЗАРАБОТАТЬ ДЕНЬГИ'")
    await message.answer(
        "💰 <b>Зарабатывайте деньги с нами!</b>\n\n"
        "В нашем боте вы можете заработать <b>до 1000 рублей в день</b>!\n\n"
        "🔥 Для этого вам всего лишь надо зайти в <b>TikTok</b> и писать "
        "такой текст в комментариях:\n\n"
        "📌 <b>Текст для копирования:</b>\n"
        "<code>@skup_bs_bot лучший бот для продажи своего аккаунта Brawl Stars</code>\n\n"
        "📊 <b>Условия оплаты:</b>\n"
        "✅ <b>1 комментарий = 5 рублей</b>\n"
        "✅ <b>200 комментариев = 1000 рублей</b>\n\n"
        "⚠️ <b>ВАЖНО!</b>\n"
        "Для выплаты предоставьте <b>скриншоты комментариев</b>.\n\n"
        "💬 Для выплаты обращайтесь: @suport_skup_bs_bot",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )

# ============================================
# ===== РАБОТНИК =====
# ============================================
@dp.message(F.text == "👷 Работа")
async def handle_work_start(message: Message, state: FSMContext):
    if not is_worker(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой функции.")
        return
    
    task = db.get_task(message.from_user.id)
    if task:
        time_left = 24 - (get_moscow_datetime() - parse_datetime(task["start_time"])).seconds // 3600
        await message.answer(
            f"⏳ У вас уже есть активное задание!\n"
            f"Осталось отправить: {task['comments'] - task['submitted']} скринов.\n"
            f"Осталось времени: {time_left} ч.",
            reply_markup=back_to_main_kb, parse_mode="HTML"
        )
        await state.set_state(ScamStates.worker_task_working)
        return
    
    await message.answer(
        "👷 <b>Готовы начать новый слот?</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data="worker_start_yes")]
            ]
        ),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "worker_start_yes")
async def worker_start_yes(callback: CallbackQuery, state: FSMContext):
    if not is_worker(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа.", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(
        "✍️ <b>Сколько комментариев вы готовы написать?</b>\n\n"
        "📊 Курс: <b>1 комментарий = 5 ⭐</b>\n"
        "⚠️ Максимум: <b>500</b>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.worker_task_comments)

@dp.message(ScamStates.worker_task_comments)
async def worker_comments_input(message: Message, state: FSMContext):
    if not is_worker(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
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
        await message.answer(
            "❌ Введите число от 1 до 500.",
            reply_markup=back_to_main_kb, parse_mode="HTML"
        )
        return
    
    reward = comments * 5
    await state.update_data(worker_comments=comments, worker_reward=reward)
    await message.answer(
        f"✅ <b>Отлично!</b>\n\n"
        f"💬 Комментариев: <b>{comments}</b>\n"
        f"💰 Вы получите: <b>{reward} ⭐</b>\n\n"
        f"❓ Вы согласны?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data="worker_confirm_yes")]
            ]
        ),
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.worker_task_confirm)

@dp.callback_query(F.data == "worker_confirm_yes")
async def worker_confirm_yes(callback: CallbackQuery, state: FSMContext):
    if not is_worker(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа.", show_alert=True)
        return
    
    data = await state.get_data()
    comments = data.get("worker_comments")
    reward = data.get("worker_reward")
    
    if not comments:
        await callback.answer("❌ Ошибка!", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.delete()
    db.create_task(callback.from_user.id, comments, reward)
    
    await callback.message.answer(
        f"✅ <b>Отлично! Принимайтесь за работу!</b>\n\n"
        f"📌 <b>Текст для копирования:</b>\n"
        f"<code>skup_bs_ лучший бот для покупки доната или продажи аккаунта Brawl Stars</code>\n\n"
        f"📊 Ждем от вас <b>{comments} скринов</b>.\n"
        f"⏳ У вас есть <b>24 часа</b>.\n\n"
        f"⚠️ При невыполнении будет списано <b>{reward} ⭐</b>\n\n"
        f"🔄 Отправляйте скрины в этот чат.",
        parse_mode="HTML"
    )
    await state.clear()
    await state.set_state(ScamStates.worker_task_working)

@dp.message(ScamStates.worker_task_working, F.photo)
async def worker_photo_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    task = db.get_task(user_id)
    
    if not task:
        await message.answer("⚠️ У вас нет активного задания.")
        await state.clear()
        return
    
    elapsed = (get_moscow_datetime() - parse_datetime(task["start_time"])).total_seconds()
    if elapsed > 24 * 3600:
        reward = task["reward"]
        new_balance = db.update_balance(user_id, -reward)
        db.add_history(user_id, -reward, f"Штраф за невыполнение задания (-{reward} ⭐)")
        db.delete_task(user_id)
        await message.answer(
            f"❌ <b>Время вышло!</b>\n\n"
            f"Списано <b>{reward} ⭐</b> (штраф).\n"
            f"Баланс: {new_balance} ⭐",
            parse_mode="HTML"
        )
        await state.clear()
        return
    
    photo_hash = get_photo_hash(message.photo[-1])
    if user_id not in worker_photo_hashes:
        worker_photo_hashes[user_id] = []
    
    if photo_hash in worker_photo_hashes[user_id]:
        await message.answer("⚠️ Этот скрин уже был отправлен!", parse_mode="HTML")
        return
    
    worker_photo_hashes[user_id].append(photo_hash)
    db.update_task_submitted(user_id)
    task = db.get_task(user_id)
    
    remaining = task["comments"] - task["submitted"]
    time_left = 24 - (elapsed // 3600)
    
    if remaining > 0:
        await message.answer(
            f"✅ Отправлено: {task['submitted']} скринов.\n"
            f"📊 Осталось: <b>{remaining}</b>\n"
            f"⏳ Времени: <b>{int(time_left)} ч.</b>",
            parse_mode="HTML"
        )
    else:
        reward = task["reward"]
        new_balance = db.update_balance(user_id, reward)
        db.add_history(user_id, reward, f"Заработок за комментарии (+{reward} ⭐)")
        db.delete_task(user_id)
        await message.answer(
            f"✅ <b>Задание выполнено!</b>\n\n"
            f"💰 Начислено <b>{reward} ⭐</b>\n"
            f"📊 Баланс: {new_balance} ⭐\n\n"
            f"🎉 Спасибо за работу!",
            parse_mode="HTML"
        )
        await state.clear()

# ============================================
# ===== ПОДДЕРЖКА =====
# ============================================
@dp.message(F.text == "❓ Поддержка")
async def handle_help(message: Message, state: FSMContext):
    await notify_owner(message.from_user, "НАЖАЛ КНОПКУ 'ПОДДЕРЖКА'")
    await message.answer(
        "📩 <b>Поддержка</b>\n\n"
        "Напишите ваш вопрос одним сообщением.\n"
        "Мы ответим в ближайшее время.\n\n"
        "✍️ Введите текст:",
        reply_markup=support_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_support)

@dp.message(ScamStates.waiting_support)
async def handle_support_message(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await show_main_menu(message)
        return
    
    user = message.from_user
    admin_text = (
        f"📩 <b>Сообщение от пользователя</b>\n"
        f"👤 {user.full_name} (@{user.username})\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"<b>Текст:</b>\n{message.text}"
    )
    
    await notify_owner(user, f"ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ: {message.text[:50]}...")
    
    try:
        await bot.send_message(OWNER_USERNAME, admin_text, parse_mode="HTML")
        for sup_id in db.get_users_by_role("support"):
            try:
                await bot.send_message(sup_id, admin_text, parse_mode="HTML")
            except:
                pass
        await message.answer(
            "✅ <b>Ваше сообщение отправлено!</b>\n\n"
            "Наш оператор свяжется с вами в ближайшее время. 🙌",
            reply_markup=main_menu_kb, parse_mode="HTML"
        )
        await state.clear()
        await state.set_state(ScamStates.main_menu)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=support_kb, parse_mode="HTML")

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
        "Введите ID или @юзернейм и текст.\n"
        "Пример: <code>123456789 Здравствуйте!</code>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_msg_user)

@dp.message(ScamStates.admin_msg_user)
async def moderator_msg_user_input(message: Message, state: FSMContext):
    if not is_moderator(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    if message.text == "🔙 Назад":
        await show_main_menu(message)
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Введите ID и текст через пробел.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    target_user = find_user(parts[0])
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    msg_text = parts[1]
    try:
        await bot.send_message(target_user, f"📩 <b>Сообщение от модератора</b>\n\n{msg_text}", parse_mode="HTML")
        await message.answer(f"✅ Сообщение отправлено пользователю.", reply_markup=moderator_menu_kb, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=moderator_menu_kb, parse_mode="HTML")
    await state.clear()

@dp.message(F.text == "📋 Обращения")
async def moderator_view_appeals(message: Message, state: FSMContext):
    if not is_moderator(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    
    actions = db.get_actions_log(limit=50)
    appeals = [a for a in actions if "ОТПРАВИЛ ВОПРОС В ПОДДЕРЖКУ" in a['action']]
    
    if not appeals:
        await message.answer("📋 <b>Обращения</b>\n\n📭 Пока нет обращений.", reply_markup=moderator_menu_kb, parse_mode="HTML")
        return
    
    text = "📋 <b>Последние обращения:</b>\n\n"
    for idx, appeal in enumerate(appeals[:10], 1):
        text += f"{idx}. [{appeal['time']}]\n   👤 {appeal['username']}\n   📝 {appeal['action'][:100]}\n\n"
    
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
        "🔐 <b>Введите пароль:</b>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
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
        await message.answer("✅ <b>Доступ разрешён!</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
    else:
        await message.answer("❌ <b>Неверный пароль!</b>", reply_markup=back_to_main_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН: СТАТИСТИКА =====
# ============================================
@dp.message(F.text == "📊 Статистика")
@admin_required
async def admin_stats(message: Message, state: FSMContext):
    total_users = db.get_user_count()
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>",
        reply_markup=admin_menu_kb, parse_mode="HTML"
    )

@dp.message(F.text == "👥 Пользователи")
@admin_required
async def admin_users(message: Message, state: FSMContext):
    users = db.get_all_users(limit=20)
    if not users:
        await message.answer("👥 <b>Пользователи</b>\n\nПока ни одного пользователя.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    
    text = "👥 <b>Список пользователей:</b>\n\n"
    for idx, user_data in enumerate(users, 1):
        frozen_str = "❄️ Заморожен" if user_data.get("frozen_until") else "✅ Активен"
        text += f"{idx}. <b>ID:</b> <code>{user_data['id']}</code>\n   📛 {user_data['name']}\n   🔖 {user_data['username']}\n   💰 {user_data.get('balance', 0)} ⭐\n   ❄️ {frozen_str}\n\n"
    
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

@dp.message(F.text == "📋 Действия")
@admin_required
async def admin_actions(message: Message, state: FSMContext):
    actions = db.get_actions_log(limit=20)
    if not actions:
        await message.answer("📋 <b>Действия</b>\n\nПока нет действий.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    
    text = "📋 <b>Последние действия:</b>\n\n"
    for entry in actions:
        text += f"• [{entry['time']}] {entry['username']} → {entry['action']}\n"
    
    await message.answer(text, reply_markup=admin_menu_kb, parse_mode="HTML")

# ============================================
# ===== АДМИН: ПОПОЛНЕНИЕ БАЛАНСА =====
# ============================================
async def admin_balance_start(message: Message, state: FSMContext):
    await message.answer(
        "💰 <b>Пополнение/списание</b>\n\n"
        "Введите <b>ID или @юзернейм</b> пользователя.\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_balance_user)

@dp.message(ScamStates.admin_balance_user)
@admin_required
async def admin_balance_user_input(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(target_user=target_user)
    await message.answer(
        f"✅ Найден: {db.get_user(target_user)['name']}\n"
        f"Введите сумму (+ пополнение, - списание):",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_balance_amount)

@dp.message(ScamStates.admin_balance_amount)
@admin_required
async def admin_balance_amount_input(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        amount = int(message.text.strip())
        if amount == 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число, не равное нулю.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    data = await state.get_data()
    target_user = data.get("target_user")
    if target_user is None:
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Владелец - выполняет сразу
    if message.from_user.id == OWNER_USERNAME:
        user_data = db.get_user(target_user)
        if amount < 0 and abs(amount) > user_data["balance"]:
            await message.answer(f"❌ Недостаточно средств! Баланс: {user_data['balance']} ⭐", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
        new_balance = db.update_balance(target_user, amount)
        db.add_history(target_user, amount, "Пополнение/списание (владелец)")
        await message.answer(f"✅ Баланс изменён на {amount} ⭐. Новый: {new_balance} ⭐", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Админ - отправляет запрос
    await message.answer("⏳ Запрос отправлен владельцу.", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)
    await send_approval_request_to_owner(message.from_user.id, "balance", {"target_user": target_user, "amount": amount})

# ============================================
# ===== АДМИН: ОТПРАВКА СООБЩЕНИЯ =====
# ============================================
@dp.message(F.text == "✉️ Отправить сообщение")
@admin_required
async def admin_send_message_start(message: Message, state: FSMContext):
    await message.answer(
        "✉️ <b>Отправка сообщения</b>\n\n"
        "Введите ID или @юзернейм пользователя:\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_msg_user)

@dp.message(ScamStates.admin_msg_user)
@admin_required
async def admin_msg_user_input(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(target_user=target_user)
    await message.answer(
        f"✅ Найден: {db.get_user(target_user)['name']}\n"
        f"Введите текст сообщения:",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_msg_text)

@dp.message(ScamStates.admin_msg_text)
@admin_required
async def admin_msg_text_input(message: Message, state: FSMContext):
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
        await bot.send_message(target_user, f"📩 <b>Сообщение от администрации</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer("✅ Сообщение отправлено.", reply_markup=admin_menu_kb, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН: ЗАМОРОЗКА =====
# ============================================
@dp.message(F.text == "❄️ Заморозить профиль")
@admin_required
async def admin_freeze_start(message: Message, state: FSMContext):
    await message.answer(
        "❄️ <b>Заморозка профиля</b>\n\n"
        "Введите ID или @юзернейм пользователя:\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_freeze_user)

@dp.message(ScamStates.admin_freeze_user)
@admin_required
async def admin_freeze_user_input(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(freeze_target=target_user)
    await message.answer(
        "Введите дату окончания заморозки:\n"
        "<b>ДД.ММ.ГГГГ ЧЧ:ММ</b> или <b>0</b> для бессрочной:\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_freeze_date)

@dp.message(ScamStates.admin_freeze_date)
@admin_required
async def admin_freeze_date_input(message: Message, state: FSMContext):
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
            frozen_until = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            await message.answer("❌ Неверный формат.", reply_markup=back_to_main_kb, parse_mode="HTML")
            return
    
    await state.update_data(freeze_until=frozen_until)
    await message.answer(
        "❄️ <b>Причина заморозки:</b>\n\n"
        "Введите текст причины:\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_freeze_reason)

@dp.message(ScamStates.admin_freeze_reason)
@admin_required
async def admin_freeze_reason_input(message: Message, state: FSMContext):
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
    
    if target_user is None:
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Владелец - выполняет сразу
    if message.from_user.id == OWNER_USERNAME:
        db.set_frozen(target_user, frozen_until, reason)
        until_str = "НАВСЕГДА" if frozen_until == "forever" else datetime.strptime(frozen_until, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M") + " (МСК)"
        try:
            await bot.send_message(target_user, f"❄️ <b>Профиль заморожен!</b>\n\n⏰ До: {until_str}\n📌 Причина: {reason}", parse_mode="HTML")
        except:
            pass
        await message.answer(f"✅ Профиль заморожен до {until_str}", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Админ - отправляет запрос
    await message.answer("⏳ Запрос отправлен владельцу.", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)
    await send_approval_request_to_owner(message.from_user.id, "freeze", {"target_user": target_user, "frozen_until": frozen_until, "reason": reason})

# ============================================
# ===== АДМИН: РАЗМОРОЗКА =====
# ============================================
@dp.message(F.text == "🔄 Разморозить профиль")
@admin_required
async def admin_unfreeze_start(message: Message, state: FSMContext):
    await message.answer(
        "🔄 <b>Разморозка профиля</b>\n\n"
        "Введите ID или @юзернейм пользователя:\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_unfreeze_user)

@dp.message(ScamStates.admin_unfreeze_user)
@admin_required
async def admin_unfreeze_user_input(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    user_data = db.get_user(target_user)
    if not user_data.get("frozen_until"):
        await message.answer("ℹ️ Профиль уже активен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Владелец - выполняет сразу
    if message.from_user.id == OWNER_USERNAME:
        db.clear_frozen(target_user)
        try:
            await bot.send_message(target_user, "✅ <b>Профиль разморожен!</b>", parse_mode="HTML")
        except:
            pass
        await message.answer("✅ Профиль разморожен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Админ - отправляет запрос
    await message.answer("⏳ Запрос отправлен владельцу.", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)
    await send_approval_request_to_owner(message.from_user.id, "unfreeze", {"target_user": target_user})

# ============================================
# ===== АДМИН: НАЗНАЧЕНИЕ СТАТУСА =====
# ============================================
@dp.message(F.text == "👑 Назначить статус")
@owner_required
async def admin_assign_start(message: Message, state: FSMContext):
    await message.answer(
        "👑 <b>Назначение статуса</b>\n\n"
        "Введите ID или @юзернейм пользователя:\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_assign_user)

@dp.message(ScamStates.admin_assign_user)
@owner_required
async def admin_assign_user_input(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    target_user = find_user(message.text.strip())
    if target_user is None:
        await message.answer("❌ Пользователь не найден.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(assign_target=target_user)
    await message.answer(
        "Выберите новую роль:\n"
        "👑 Владелец (недоступен)\n"
        "🛡️ Админ\n"
        "🛠️ Модератор\n"
        "🎧 Поддержка\n"
        "🧪 Тестер\n"
        "💎 VIP\n"
        "👷 Работник\n"
        "👤 Пользователь\n\n"
        "Введите название роли:\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_assign_status)

@dp.message(ScamStates.admin_assign_status)
@owner_required
async def admin_assign_status_input(message: Message, state: FSMContext):
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
        await message.answer("❌ Неверная роль.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    data = await state.get_data()
    target_user = data.get("assign_target")
    if target_user is None:
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    db.set_user_role(target_user, role)
    
    role_name = {
        "admin": "Админ",
        "moderator": "Модератор",
        "support": "Поддержка",
        "tester": "Тестер",
        "vip": "VIP",
        "worker": "Работник",
        "user": "Пользователь"
    }.get(role, "Пользователь")
    
    await message.answer(f"✅ Роль изменена на <b>{role_name}</b>", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН: СОЗДАНИЕ ЛОТА =====
# ============================================
@dp.message(F.text == "➕ Создать новый лот")
@admin_required
async def create_new_lot_start(message: Message, state: FSMContext):
    await message.answer(
        "➕ <b>Создание лота</b>\n\n"
        "Введите <b>номер</b> лота (целое число):\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_new_lot_number)

@dp.message(ScamStates.waiting_new_lot_number)
@admin_required
async def process_new_lot_number(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        number = int(message.text.strip())
        if number <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(new_lot_number=number)
    await message.answer(
        f"✅ Номер: <b>{number}</b>\n\n"
        f"Введите <b>количество кубков</b> (например, 86к):\n\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_new_lot_cups)

@dp.message(ScamStates.waiting_new_lot_cups)
@admin_required
async def process_new_lot_cups(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    cups = message.text.strip()
    if not cups:
        await message.answer("❌ Введите количество кубков.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(new_lot_cups=cups)
    await message.answer(
        f"✅ Кубков: <b>{cups}</b>\n\n"
        f"Введите <b>количество бойцов</b> (целое число):\n\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_new_lot_fighters)

@dp.message(ScamStates.waiting_new_lot_fighters)
@admin_required
async def process_new_lot_fighters(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        fighters = int(message.text.strip())
        if fighters <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(new_lot_fighters=fighters)
    await message.answer(
        f"✅ Бойцов: <b>{fighters}</b>\n\n"
        f"Введите <b>количество гемов</b> (целое число):\n\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_new_lot_gems)

@dp.message(ScamStates.waiting_new_lot_gems)
@admin_required
async def process_new_lot_gems(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        gems = int(message.text.strip())
        if gems < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите неотрицательное целое число.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(new_lot_gems=gems)
    await message.answer(
        f"✅ Гемов: <b>{gems}</b>\n\n"
        f"Введите <b>цену</b> в звёздах (целое число):\n\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_new_lot_price)

@dp.message(ScamStates.waiting_new_lot_price)
@admin_required
async def process_new_lot_price(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    data = await state.get_data()
    number = data.get("new_lot_number")
    cups = data.get("new_lot_cups")
    fighters = data.get("new_lot_fighters")
    gems = data.get("new_lot_gems")
    
    lot_name = f"Лот {number}"
    
    lots = db.get_lots()
    existing = None
    for lot in lots:
        if lot["name"] == lot_name:
            existing = lot["id"]
            break
    
    lot_id = db.create_or_update_lot(existing, lot_name, cups, gems, fighters, price)
    
    await message.answer(
        f"✅ <b>Лот {'обновлён' if existing else 'создан'}!</b>\n\n"
        f"📌 <b>Данные лота:</b>\n"
        f"🏆 Кубков: {cups}\n"
        f"⚔️ Бойцов: {fighters}\n"
        f"💎 Гемов: {gems}\n"
        f"💰 Цена: {price} ⭐",
        reply_markup=admin_menu_kb, parse_mode="HTML"
    )
    await state.clear()
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== АДМИН: ТЕХПЕРЕРЫВ =====
# ============================================
@dp.message(F.text == "🛠 Включить перерыв")
@admin_required
async def enable_tech_break(message: Message, state: FSMContext):
    global tech_break_enabled, tech_break_end, tech_break_reason
    
    if tech_break_enabled:
        end_dt = tech_break_end
        end_str = end_dt.strftime("%d.%m.%Y %H:%M") if end_dt else "неизвестно"
        await message.answer(f"⚠️ Техперерыв уже включён до {end_str}.", parse_mode="HTML")
        return
    
    await message.answer(
        "🛠️ <b>Включение техперерыва</b>\n\n"
        "Введите дату и время окончания:\n"
        "<b>ДД.ММ.ГГГГ ЧЧ:ММ</b>\n\n"
        "Например: <code>15.08.2026 20:00</code>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_tech_break_time)

@dp.message(ScamStates.waiting_tech_break_time)
@admin_required
async def process_tech_break_time(message: Message, state: FSMContext):
    global tech_break_end, tech_break_enabled, tech_break_reason
    
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
        await message.answer("❌ Неверный формат.", reply_markup=back_to_main_kb, parse_mode="HTML")
        return
    
    await state.update_data(tech_break_end=end_dt)
    await message.answer(
        "🛠️ <b>Причина перерыва:</b>\n\n"
        "Введите текст причины:\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb, parse_mode="HTML"
    )
    await state.set_state(ScamStates.waiting_tech_break_reason)

@dp.message(ScamStates.waiting_tech_break_reason)
@admin_required
async def process_tech_break_reason(message: Message, state: FSMContext):
    global tech_break_end, tech_break_enabled, tech_break_reason
    
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
        await message.answer("❌ Ошибка.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Владелец - выполняет сразу
    if message.from_user.id == OWNER_USERNAME:
        tech_break_end = end_dt
        tech_break_reason = reason
        tech_break_enabled = True
        await message.answer(f"✅ Техперерыв включён до {end_dt.strftime('%d.%m.%Y %H:%M')}", reply_markup=admin_menu_kb, parse_mode="HTML")
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Админ - отправляет запрос
    await message.answer("⏳ Запрос отправлен владельцу.", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)
    await send_approval_request_to_owner(message.from_user.id, "tech_on", {"end_dt": end_dt, "reason": reason})

@dp.message(F.text == "⛔ Отключить перерыв")
@admin_required
async def disable_tech_break(message: Message, state: FSMContext):
    global tech_break_enabled, tech_break_end, tech_break_reason
    
    if not tech_break_enabled:
        await message.answer("ℹ️ Техперерыв не активен.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    
    # Владелец - выполняет сразу
    if message.from_user.id == OWNER_USERNAME:
        tech_break_enabled = False
        tech_break_end = None
        tech_break_reason = ""
        await message.answer("✅ Техперерыв отключён.", reply_markup=admin_menu_kb, parse_mode="HTML")
        return
    
    # Админ - отправляет запрос
    await message.answer("⏳ Запрос отправлен владельцу.", reply_markup=admin_menu_kb, parse_mode="HTML")
    await state.set_state(ScamStates.admin_panel)
    await send_approval_request_to_owner(message.from_user.id, "tech_off", {})

# ============================================
# ===== ЗАПРОСЫ К ВЛАДЕЛЬЦУ =====
# ============================================
async def send_approval_request_to_owner(admin_id: int, request_type: str, data: dict):
    admin_user_data = db.get_user(admin_id)
    admin_name = admin_user_data['name'] if admin_user_data else "Админ"
    admin_username = admin_user_data['username'] if admin_user_data else "без юзернейма"
    
    if request_type == "balance":
        target_user_id = data.get("target_user")
        amount = data.get("amount")
        target_data = db.get_user(target_user_id)
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
        target_data = db.get_user(target_user_id)
        target_name = target_data['name'] if target_data else "Пользователь"
        target_username = target_data['username'] if target_data else "без юзернейма"
        
        until_str = "НАВСЕГДА" if frozen_until == "forever" else datetime.strptime(frozen_until, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        
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
        target_data = db.get_user(target_user_id)
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
        end_str = end_dt.strftime("%d.%m.%Y %H:%M")
        
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
        print(f"Ошибка отправки запроса владельцу: {e}")
        return False

async def freeze_admin_account(admin_id: int, duration_hours: int = 1):
    frozen_until = get_moscow_datetime() + timedelta(hours=duration_hours)
    db.set_frozen(admin_id, frozen_until.strftime("%Y-%m-%d %H:%M:%S"), "Отказ от одобрения действия владельцем")
    
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
# ===== ОБРАБОТЧИКИ КНОПОК ВЛАДЕЛЬЦА =====
# ============================================
@dp.callback_query(F.data.startswith("approve_"))
async def approve_admin_request(callback: CallbackQuery):
    global tech_break_end, tech_break_enabled, tech_break_reason
    
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
        new_balance = db.update_balance(target_user_id, amount)
        db.add_history(target_user_id, amount, "Пополнение (одобрено владельцем)")
        
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
        
        db.set_frozen(target_user_id, frozen_until, reason)
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
        db.clear_frozen(target_user_id)
        
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
    admin_id = int(data[2])
    
    await callback.answer("❌ Отклонено!", show_alert=True)
    await callback.message.delete()
    
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
        elif is_moderator(message.from_user.id):
            await state.clear()
            await show_main_menu(message)
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

@dp.message()
async def catch_all(message: Message):
    await message.answer("❓ Используйте кнопки меню.", reply_markup=main_menu_kb)

# ============================================
# ===== ЗАПУСК =====
# ============================================
async def main():
    print("=" * 50)
    print("🤖 БОТ ЗАПУЩЕН (ПОЛНАЯ ВЕРСИЯ)")
    print("=" * 50)
    print("📊 База данных: SQLite (bot_database.db)")
    print("✅ Все функции активны:")
    print("   - 👤 Профиль и вывод средств")
    print("   - 🛒 Покупка (донат, гемы, лоты)")
    print("   - 👷 Система работников")
    print("   - 📩 Поддержка и модерация")
    print("   - 👑 Админ-панель с запросами")
    print("   - 🔔 Запросы к владельцу")
    print("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
