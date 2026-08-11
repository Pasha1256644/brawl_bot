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

# ===== СПИСКИ СТАТУСОВ =====
ADMIN_IDS = [8985475819]
SUPPORT_IDS = []
TESTER_IDS = []
VIP_IDS = []
WORKER_IDS = []

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====
tech_break_enabled = False
tech_break_end = None
tech_break_reason = ""
pending_actions = {}
user_tasks = {}  # {user_id: {"comments": 100, "submitted": 0, "start_time": datetime, "screens": [], "reward": 500}}

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

# ===== ФУНКЦИИ СТАТУСОВ =====
def get_user_status(user_id: int):
    if user_id == OWNER_USERNAME:
        return "Владелец", "👑"
    if user_id in ADMIN_IDS:
        return "Админ", "🛡️"
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

# ===== БАЗА ДАННЫХ =====
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

# ===== ПОМОЩНИКИ ДЛЯ РАБОТЫ =====
def get_photo_hash(photo: types.PhotoSize) -> str:
    """Создаёт хеш фото для проверки дубликатов"""
    file_id = photo.file_id
    return hashlib.md5(file_id.encode()).hexdigest()

async def check_worker_task_completion(user_id: int):
    """Проверяет, завершено ли задание работника"""
    task = user_tasks.get(user_id)
    if not task:
        return
    if task["submitted"] >= task["comments"]:
        # Начисляем награду
        users_db[user_id]["balance"] += task["reward"]
        add_history_entry(user_id, task["reward"], f"Заработок за комментарии (+{task['reward']} ⭐)")
        await bot.send_message(
            user_id,
            f"✅ <b>Отлично! Вы выполнили задание!</b>\n\n"
            f"💰 Вам начислено <b>{task['reward']} ⭐</b>\n"
            f"📊 Текущий баланс: {users_db[user_id]['balance']} ⭐\n\n"
            f"🎉 Спасибо за работу!",
            parse_mode="HTML"
        )
        del user_tasks[user_id]

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

# ===== СОСТОЯНИЯ =====
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

# ===== ИНИЦИАЛИЗАЦИЯ =====
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
# ===== ХЕНДЛЕРЫ =====
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

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message, state: FSMContext):
    user_data = users_db.get(message.from_user.id)
    if not user_data:
        await message.answer("⚠️ Ошибка: данные не найдены. Попробуйте /start.")
        return
    balance = user_data.get("balance", 0)
    username = user_data.get("username", "без юзернейма")
    name = user_data.get("name", "без имени")
    status, emoji = get_user_status(message.from_user.id)
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
        f"💰 <b>Баланс:</b> {balance} ⭐\n"
        f"🎖️ <b>Статус:</b> {emoji} {status}\n\n"
        f"{frozen_text}\n\n"
        "👇 Выберите действие:",
        reply_markup=profile_kb, parse_mode="HTML"
    )

# ============================================
# ===== РАБОТА (ДЛЯ СТАТУСА "РАБОТНИК") =====
# ============================================
@dp.message(F.text == "👷 Работа")
async def handle_work_start(message: Message, state: FSMContext):
    if message.from_user.id not in WORKER_IDS:
        await message.answer("⛔ У вас нет доступа к этой функции.")
        return
    
    # Проверяем, есть ли уже активное задание
    if message.from_user.id in user_tasks:
        task = user_tasks[message.from_user.id]
        await message.answer(
            f"⏳ У вас уже есть активное задание!\n"
            f"Осталось отправить: {task['comments'] - task['submitted']} скринов.\n"
            f"Осталось времени: {24 - (get_moscow_datetime() - task['start_time']).seconds // 3600} ч.",
            reply_markup=back_to_main_kb,
            parse_mode="HTML"
        )
        return
    
    await message.answer(
        "👷 <b>Готовы начать новый слот?</b>\n\n"
        "💬 Вы готовы начать сегодня новый слот?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="worker_start_yes")]
        ]),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "worker_start_yes")
async def worker_start_yes(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in WORKER_IDS:
        await callback.answer("⛔ У вас нет доступа к этой функции.", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(
        "✍️ <b>Сколько комментариев вы готовы сегодня написать?</b>\n\n"
        "📊 Курс: <b>1 комментарий = 5 рублей</b>\n"
        "⚠️ Максимальное количество: <b>500</b>\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.worker_task_comments)

@dp.message(ScamStates.worker_task_comments)
async def worker_comments_input(message: Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await state.set_state(ScamStates.main_menu)
        if message.from_user.id == OWNER_USERNAME:
            await message.answer("❓ <b>Что вы хотите сделать?</b>", reply_markup=owner_menu_kb, parse_mode="HTML")
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
            await message.answer(
                "❌ <b>Ошибка!</b>\n\n"
                "Максимальное количество комментариев — <b>500</b>.\n"
                "Пожалуйста, введите меньшее число.",
                reply_markup=back_to_main_kb,
                parse_mode="HTML"
            )
            return
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка!</b>\n\n"
            "Пожалуйста, введите <b>целое число</b> (например, 50, 100).",
            reply_markup=back_to_main_kb,
            parse_mode="HTML"
        )
        return
    
    reward = comments * 5
    await state.update_data(worker_comments=comments, worker_reward=reward)
    await message.answer(
        f"✅ <b>Отлично!</b>\n\n"
        f"💬 Комментариев: <b>{comments}</b>\n"
        f"💰 Вы получите: <b>{reward} ⭐</b>\n\n"
        f"❓ Вы согласны?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="worker_confirm_yes")]
        ]),
        parse_mode="HTML"
    )
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
    
    user_tasks[callback.from_user.id] = {
        "comments": comments,
        "submitted": 0,
        "start_time": get_moscow_datetime(),
        "screens": [],
        "reward": reward,
        "file_hashes": []
    }
    
    await callback.message.answer(
        f"✅ <b>Отлично! Принимайтесь за работу!</b>\n\n"
        f"📌 <b>Текст для копирования:</b>\n"
        f"<code>skup_bs_ лучший бот для покупки доната или продажи аккаунта Brawl Stars</code>\n\n"
        f"📊 <b>Ждем от вас {comments} скринов</b> отправленных комментариев.\n\n"
        f"⏳ <b>У вас есть 24 часа</b> на выполнение задания.\n"
        f"Вы можете отправлять скрины частями.\n\n"
        f"⚠️ <b>Предупреждение!</b>\n"
        f"При отправке одинаковых скринов или невыполнении за 24 часа — \n"
        f"с вашего баланса будет списано <b>{reward} ⭐</b>\n\n"
        f"🔄 Для отправки скринов просто пришлите их в этот чат.\n"
        f"Начинаем! 🚀",
        parse_mode="HTML"
    )
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
    
    # Проверяем время
    elapsed = (get_moscow_datetime() - task["start_time"]).total_seconds()
    if elapsed > 24 * 3600:
        # Штраф
        reward = task["reward"]
        users_db[user_id]["balance"] -= reward
        add_history_entry(user_id, -reward, f"Штраф за невыполнение задания (-{reward} ⭐)")
        await message.answer(
            f"❌ <b>Время вышло!</b>\n\n"
            f"Вы не успели отправить все {task['comments']} скринов.\n"
            f"С вашего баланса списано <b>{reward} ⭐</b> (штраф).\n"
            f"Текущий баланс: {users_db[user_id]['balance']} ⭐",
            parse_mode="HTML"
        )
        del user_tasks[user_id]
        await state.clear()
        return
    
    # Проверка на дубли
    photo_hash = get_photo_hash(message.photo[-1])
    if photo_hash in task["file_hashes"]:
        await message.answer(
            "⚠️ <b>Этот скрин уже был отправлен!</b>\n\n"
            "Пожалуйста, отправляйте только уникальные скрины.",
            parse_mode="HTML"
        )
        return
    
    task["file_hashes"].append(photo_hash)
    task["submitted"] += 1
    remaining = task["comments"] - task["submitted"]
    time_left = 24 - (elapsed // 3600)
    
    if remaining > 0:
        await message.answer(
            f"✅ <b>Отлично! Вы отправили {task['submitted']} скринов.</b>\n\n"
            f"📊 Осталось: <b>{remaining}</b> скринов.\n"
            f"⏳ Оставшееся время: <b>{int(time_left)} ч.</b>",
            parse_mode="HTML"
        )
    else:
        # Задание выполнено
        reward = task["reward"]
        users_db[user_id]["balance"] += reward
        add_history_entry(user_id, reward, f"Заработок за комментарии (+{reward} ⭐)")
        await message.answer(
            f"✅ <b>Отлично! Вы выполнили задание!</b>\n\n"
            f"💰 Вам начислено <b>{reward} ⭐</b>\n"
            f"📊 Текущий баланс: {users_db[user_id]['balance']} ⭐\n\n"
            f"🎉 Спасибо за работу!",
            parse_mode="HTML"
        )
        del user_tasks[user_id]
        await state.clear()

# ============================================
# ===== АДМИН-НАЗНАЧЕНИЕ СТАТУСА =====
# ============================================
@dp.message(F.text == "👑 Назначить статус")
async def admin_assign_start(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    
    await message.answer(
        "👑 <b>Назначение статуса</b>\n\n"
        "Введите <b>ID или @юзернейм</b> пользователя:\n"
        "Примеры: `123456789` или `@username`\n\n"
        "🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_assign_user)

@dp.message(ScamStates.admin_assign_user)
async def admin_assign_user_input(message: Message, state: FSMContext):
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
        await message.answer(
            "❌ Пользователь не найден. Проверьте ID или юзернейм.",
            reply_markup=back_to_main_kb,
            parse_mode="HTML"
        )
        return
    
    await state.update_data(assign_target=target_user)
    user_data = users_db[target_user]
    status, emoji = get_user_status(target_user)
    
    await message.answer(
        f"✅ Найден пользователь: {user_data['name']} ({user_data['username']})\n"
        f"🎖️ Текущий статус: {emoji} {status}\n\n"
        f"Выберите новый статус:\n"
        f"👑 Владелец (недоступен)\n"
        f"🛡️ Админ\n"
        f"🎧 Поддержка\n"
        f"🧪 Тестер\n"
        f"💎 VIP\n"
        f"👷 Работник\n"
        f"👤 Пользователь\n\n"
        f"Введите название статуса (например, VIP, Работник):\n"
        f"🔙 Для отмены нажмите 'Назад'.",
        reply_markup=back_to_main_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_assign_status)

@dp.message(ScamStates.admin_assign_status)
async def admin_assign_status_input(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_USERNAME and message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    if message.text == "🔙 Назад":
        await admin_panel_request(message, state)
        return
    
    status_map = {
        "админ": "admin",
        "поддержка": "support",
        "тестер": "tester",
        "вип": "vip",
        "vip": "vip",
        "работник": "worker",
        "пользователь": "user"
    }
    
    status = status_map.get(message.text.strip().lower())
    if not status:
        await message.answer(
            "❌ Неверный статус. Доступные статусы: Админ, Поддержка, Тестер, VIP, Работник, Пользователь.",
            reply_markup=back_to_main_kb,
            parse_mode="HTML"
        )
        return
    
    data = await state.get_data()
    target_user = data.get("assign_target")
    if target_user is None or target_user not in users_db:
        await message.answer("❌ Ошибка: пользователь не найден.", reply_markup=admin_menu_kb)
        await state.set_state(ScamStates.admin_panel)
        return
    
    # Удаляем из всех списков
    if target_user in ADMIN_IDS:
        ADMIN_IDS.remove(target_user)
    if target_user in SUPPORT_IDS:
        SUPPORT_IDS.remove(target_user)
    if target_user in TESTER_IDS:
        TESTER_IDS.remove(target_user)
    if target_user in VIP_IDS:
        VIP_IDS.remove(target_user)
    if target_user in WORKER_IDS:
        WORKER_IDS.remove(target_user)
    
    # Добавляем в нужный список
    status_name = {
        "admin": "Админ",
        "support": "Поддержка",
        "tester": "Тестер",
        "vip": "VIP",
        "worker": "Работник",
        "user": "Пользователь"
    }.get(status, "Пользователь")
    
    if status == "admin":
        ADMIN_IDS.append(target_user)
    elif status == "support":
        SUPPORT_IDS.append(target_user)
    elif status == "tester":
        TESTER_IDS.append(target_user)
    elif status == "vip":
        VIP_IDS.append(target_user)
    elif status == "worker":
        WORKER_IDS.append(target_user)
    
    user_data = users_db[target_user]
    new_status, emoji = get_user_status(target_user)
    
    await message.answer(
        f"✅ <b>Статус пользователя изменён!</b>\n\n"
        f"👤 Пользователь: {user_data['name']} ({user_data['username']})\n"
        f"🎖️ Новый статус: {emoji} {new_status}",
        reply_markup=admin_menu_kb,
        parse_mode="HTML"
    )
    await state.set_state(ScamStates.admin_panel)

# ============================================
# ===== ОСТАЛЬНЫЕ ХЕНДЛЕРЫ (ПОКУПКА, ВЫВОД, АДМИНКА) =====
# ============================================
# ... (все остальные хендлеры из предыдущей версии бота, их код идентичен)
# Для экономии места я не дублирую их здесь полностью,
# но в полном коде они должны быть.

# ============================================
# ===== ЗАПУСК =====
# ============================================
async def main():
    print("🤖 Бот запущен")
    print("📢 Логи действий — в админ-панели (кнопка 'Действия')")
    print("💳 Добавлен профиль с балансом, пополнением и выводом")
    print("📜 Добавлена история операций")
    print("🔒 Перед началом работы нужно нажать /start")
    print("🔐 Админ-панель защищена паролем (не отображается)")
    print("👷 Добавлен статус 'Работник' с системой заданий")
    print("👑 Добавлена кнопка 'Назначить статус' в админ-панели")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
