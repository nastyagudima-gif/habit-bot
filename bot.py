"""
Бот для трекинга привычек
Версия: 1.3 - Webhook для Amvera
Функции: добавление, отслеживание, статистика, напоминания
"""

import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# ==================== ЗАГРУЗКА КОНФИГУРАЦИИ ====================

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN or TOKEN == 'YOUR_BOT_TOKEN_HERE':
    print("❌ Ошибка: BOT_TOKEN не настроен в переменных окружения")
    print("Добавьте переменную BOT_TOKEN в настройках Amvera")
    exit(1)

# Настройки для Amvera
PORT = int(os.environ.get("PORT", 8000))
APP_NAME = os.environ.get("APP_NAME", "habit-bot")
WEBHOOK_URL = f"https://{APP_NAME}.amvera.io/webhook"


# ==================== ХРАНИЛИЩЕ ДАННЫХ ====================

class HabitStorage:
    """Класс для работы с хранением привычек в JSON файле"""

    def __init__(self, file_path: str = "habits.json"):
        self.file_path = Path(file_path)
        self._cache: Dict[int, Dict] = {}
        self._lock = asyncio.Lock()
        self._load_data()

    def _load_data(self):
        """Загружает данные из JSON файла"""
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                    self._cache = {}
                    for user_id_str, user_data in raw_data.items():
                        user_id = int(user_id_str)
                        if user_id not in self._cache:
                            self._cache[user_id] = user_data
                logger.info(f"✅ Загружены данные для {len(self._cache)} пользователей")
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки данных: {e}")
                self._cache = {}
        else:
            logger.info("📁 Создан новый файл данных")
            self._cache = {}
            self._save_data()

    def _save_data(self):
        """Сохраняет данные в JSON файл"""
        try:
            data_to_save = {}
            for user_id, user_data in self._cache.items():
                data_to_save[str(user_id)] = user_data

            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
            logger.debug("💾 Данные сохранены")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения данных: {e}")

    async def get_user_data(self, user_id: int) -> Dict:
        """Получает данные пользователя"""
        async with self._lock:
            user_id = int(user_id)
            if user_id not in self._cache:
                self._cache[user_id] = {
                    "habits": [],
                    "timezone": "Europe/Moscow",
                    "next_habit_id": 1,
                    "reminder_time": "09:00"
                }
                self._save_data()
            return self._cache[user_id]

    async def save_user_data(self, user_id: int, data: Dict):
        """Сохраняет данные пользователя"""
        async with self._lock:
            user_id = int(user_id)
            self._cache[user_id] = data
            self._save_data()

    async def add_habit(self, user_id: int, habit_name: str) -> Dict:
        """Добавляет новую привычку"""
        user_data = await self.get_user_data(user_id)

        new_habit = {
            "id": user_data["next_habit_id"],
            "name": habit_name.strip(),
            "created": date.today().isoformat(),
            "history": [],
            "streak": 0
        }

        user_data["habits"].append(new_habit)
        user_data["next_habit_id"] += 1
        await self.save_user_data(user_id, user_data)

        logger.info(f"📝 Пользователь {user_id} добавил привычку: {habit_name}")
        return new_habit

    async def get_habits(self, user_id: int) -> List[Dict]:
        """Возвращает список привычек"""
        user_data = await self.get_user_data(user_id)
        return user_data["habits"]

    async def mark_done(self, user_id: int, habit_id: int) -> bool:
        """Отмечает привычку выполненной сегодня"""
        user_data = await self.get_user_data(user_id)
        today = date.today().isoformat()

        for habit in user_data["habits"]:
            if habit["id"] == habit_id:
                if today in habit["history"]:
                    logger.debug(f"⚠️ Привычка {habit_id} уже отмечена сегодня")
                    return False

                habit["history"].append(today)
                habit["streak"] = self._calculate_streak(habit["history"])
                await self.save_user_data(user_id, user_data)

                logger.info(f"✅ Пользователь {user_id} отметил привычку {habit['name']} (стрейк: {habit['streak']})")
                return True

        logger.warning(f"❌ Привычка {habit_id} не найдена у пользователя {user_id}")
        return False

    def _calculate_streak(self, history: List[str]) -> int:
        """Вычисляет текущий стрейк"""
        if not history:
            return 0

        history_dates = sorted([datetime.fromisoformat(d).date() for d in history])
        streak = 1
        current_date = history_dates[-1]

        for i in range(len(history_dates) - 2, -1, -1):
            expected_date = current_date - timedelta(days=1)
            if history_dates[i] == expected_date:
                streak += 1
                current_date = history_dates[i]
            else:
                break

        return streak

    async def get_stats(self, user_id: int, days: int = 7) -> Dict:
        """Получает статистику по привычкам за N дней"""
        habits = await self.get_habits(user_id)
        stats = {}

        for habit in habits:
            history = set(habit["history"])
            completed_days = 0

            for i in range(days):
                check_date = (date.today() - timedelta(days=i)).isoformat()
                if check_date in history:
                    completed_days += 1

            stats[habit["id"]] = {
                "name": habit["name"],
                "completed": completed_days,
                "total": days,
                "streak": habit["streak"],
                "total_completions": len(habit["history"])
            }

        return stats

    async def delete_habit(self, user_id: int, habit_id: int) -> bool:
        """Удаляет привычку по ID"""
        user_data = await self.get_user_data(user_id)

        for i, habit in enumerate(user_data["habits"]):
            if habit["id"] == habit_id:
                habit_name = habit["name"]
                user_data["habits"].pop(i)
                await self.save_user_data(user_id, user_data)
                logger.info(f"🗑 Пользователь {user_id} удалил привычку: {habit_name}")
                return True

        return False

    async def edit_habit_name(self, user_id: int, habit_id: int, new_name: str) -> bool:
        """Изменяет название привычки"""
        user_data = await self.get_user_data(user_id)

        for habit in user_data["habits"]:
            if habit["id"] == habit_id:
                old_name = habit["name"]
                habit["name"] = new_name.strip()
                await self.save_user_data(user_id, user_data)
                logger.info(f"✏️ Пользователь {user_id} переименовал привычку: {old_name} -> {new_name}")
                return True

        return False

    async def set_reminder_time(self, user_id: int, time_str: str) -> bool:
        """Устанавливает время напоминания"""
        user_data = await self.get_user_data(user_id)
        user_data["reminder_time"] = time_str
        await self.save_user_data(user_id, user_data)
        logger.info(f"⏰ Пользователь {user_id} установил время напоминания: {time_str}")
        return True

    async def get_reminder_time(self, user_id: int) -> str:
        """Получает время напоминания"""
        user_data = await self.get_user_data(user_id)
        return user_data.get("reminder_time", "09:00")

    async def reset_user(self, user_id: int):
        """Сбрасывает все привычки пользователя"""
        async with self._lock:
            user_id = int(user_id)
            self._cache[user_id] = {
                "habits": [],
                "timezone": "Europe/Moscow",
                "next_habit_id": 1,
                "reminder_time": "09:00"
            }
            self._save_data()
            logger.info(f"🔄 Сброшены все привычки пользователя {user_id}")


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_progress_bar(completed: int, total: int, width: int = 10) -> str:
    """Создает прогресс-бар (например: ▰▰▰▰▱▱▱▱▱▱)"""
    if total == 0:
        return "▱" * width

    filled = int(round(completed / total * width))
    empty = width - filled
    filled = min(filled, width)
    empty = max(empty, 0)

    return "▰" * filled + "▱" * empty


def get_week_calendar(history: List[str]) -> str:
    """Создает календарь выполнения за текущую неделю"""
    days_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    today = date.today()

    start_of_week = today - timedelta(days=today.weekday())
    week_dates = [(start_of_week + timedelta(days=i)).isoformat() for i in range(7)]

    history_set = set(history)
    calendar_parts = []

    for i, day in enumerate(days_ru):
        if week_dates[i] in history_set:
            calendar_parts.append(f"{day}✅")
        else:
            calendar_parts.append(f"{day}❌")

    return " ".join(calendar_parts)


def get_habits_list_text(habits: List[dict]) -> str:
    """Формирует текст для списка привычек"""
    if not habits:
        return "📋 У вас пока нет привычек. Добавьте первую через /add_habit"

    text = "📋 **Ваши привычки:**\n\n"
    for habit in habits:
        today = date.today().isoformat()
        status = "✅" if today in habit["history"] else "🔄"

        # Прогресс за последние 7 дней
        week_progress = 0
        for i in range(7):
            check_date = (date.today() - timedelta(days=i)).isoformat()
            if check_date in habit["history"]:
                week_progress += 1

        progress_bar = get_progress_bar(week_progress, 7, 7)

        text += f"{status} **`{habit['id']}`. {habit['name']}**\n"
        text += f"   🔥 Стрейк: {habit['streak']} дней\n"
        text += f"   📊 {progress_bar} {week_progress}/7 дней\n\n"

    return text


def get_stats_text(stats: dict, days: int) -> str:
    """Формирует текст со статистикой"""
    if not stats:
        return "📊 Нет привычек для статистики"

    text = f"📊 **Статистика за {days} дней**\n\n"

    for habit_id, data in stats.items():
        progress_bar = get_progress_bar(data["completed"], data["total"])
        percentage = int(data["completed"] / data["total"] * 100) if data["total"] > 0 else 0

        text += f"**{data['name']}**\n"
        text += f"{progress_bar} {percentage}% ({data['completed']}/{data['total']})\n"
        text += f"🔥 Стрейк: {data['streak']} дней\n\n"

    total_completed = sum(d["completed"] for d in stats.values())
    total_possible = len(stats) * days
    if total_possible > 0:
        overall_percentage = int(total_completed / total_possible * 100)
        overall_bar = get_progress_bar(total_completed, total_possible, 10)
        text += f"**📈 Общий прогресс:**\n{overall_bar} {overall_percentage}% ({total_completed}/{total_possible})\n"

    return text


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

storage = HabitStorage()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение"""
    user = update.effective_user

    keyboard = [
        [InlineKeyboardButton("➕ Добавить привычку", callback_data="help_add")],
        [InlineKeyboardButton("📋 Список привычек", callback_data="refresh_list")],
        [InlineKeyboardButton("📊 Статистика", callback_data="show_stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help_commands")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"🎯 **Привет, {user.first_name}!**\n\n"
        "Я бот для трекинга привычек! 📊\n\n"
        "**✨ Основные возможности:**\n"
        "• Добавление и отслеживание привычек\n"
        "• Ежедневные напоминания\n"
        "• Визуализация прогресса\n"
        "• Статистика и стрейки\n\n"
        "Нажми на кнопку ниже или используй команды:"
    )

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def add_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление новой привычки"""
    if not context.args:
        await update.message.reply_text(
            "❌ **Укажите название привычки**\n\n"
            "Пример: `/add_habit Зарядка`",
            parse_mode='Markdown'
        )
        return

    habit_name = " ".join(context.args)
    user_id = update.effective_user.id

    habit = await storage.add_habit(user_id, habit_name)

    keyboard = [
        [InlineKeyboardButton("✅ Отметить сегодня", callback_data=f"check_{habit['id']}")],
        [InlineKeyboardButton("📋 Список привычек", callback_data="refresh_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"✅ **Привычка добавлена!**\n\n"
        f"📌 **Название:** {habit['name']}\n"
        f"🆔 **ID:** {habit['id']}\n"
        f"📅 **Создана:** {habit['created']}\n\n"
        f"🎯 Отметь выполнение сегодня:"
    )

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def list_habits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список привычек с инлайн-кнопками"""
    user_id = update.effective_user.id
    habits = await storage.get_habits(user_id)

    if not habits:
        await update.message.reply_text(
            "📋 **У вас пока нет привычек**\n\n"
            "Добавьте первую через `/add_habit`",
            parse_mode='Markdown'
        )
        return

    keyboard = []
    for habit in habits:
        today_check = date.today().isoformat()
        is_done = today_check in habit["history"]
        status = "✅" if is_done else "🔄"

        button = InlineKeyboardButton(
            f"{status} {habit['name']} | 🔥{habit['streak']}",
            callback_data=f"check_{habit['id']}"
        )
        keyboard.append([button])

    keyboard.append([
        InlineKeyboardButton("🔄 Обновить", callback_data="refresh_list"),
        InlineKeyboardButton("📊 Статистика", callback_data="show_stats")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = get_habits_list_text(habits)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def check_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмечает привычку выполненной через команду"""
    if not context.args:
        await update.message.reply_text(
            "❌ **Укажите ID привычки**\n\n"
            "Пример: `/check 1`\n"
            "Посмотреть ID можно через `/list_habits`",
            parse_mode='Markdown'
        )
        return

    try:
        habit_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")
        return

    user_id = update.effective_user.id
    success = await storage.mark_done(user_id, habit_id)

    if success:
        habits = await storage.get_habits(user_id)
        habit = next((h for h in habits if h["id"] == habit_id), None)

        if habit:
            history_days = len(habit["history"])
            progress_bar = get_progress_bar(history_days, 30)

            text = (
                f"✅ **{habit['name']}** отмечена!\n\n"
                f"🔥 **Стрейк:** {habit['streak']} дней\n"
                f"📊 **Прогресс:** {progress_bar} {history_days}/30\n\n"
                f"🎯 Так держать!"
            )

            keyboard = [
                [InlineKeyboardButton("📋 Список привычек", callback_data="refresh_list")],
                [InlineKeyboardButton("📊 Статистика", callback_data="show_stats")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text("✅ Привычка отмечена!")
    else:
        await update.message.reply_text(
            "❌ **Не удалось отметить привычку**\n\n"
            "Возможные причины:\n"
            "• Вы уже отмечали её сегодня\n"
            "• ID привычки не существует",
            parse_mode='Markdown'
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику"""
    user_id = update.effective_user.id

    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
        days = min(days, 30)

    stats = await storage.get_stats(user_id, days)

    if not stats:
        await update.message.reply_text(
            "📊 **У вас пока нет привычек**\n\n"
            "Добавьте привычку через `/add_habit`",
            parse_mode='Markdown'
        )
        return

    text = get_stats_text(stats, days)

    keyboard = [
        [InlineKeyboardButton("📋 Список привычек", callback_data="refresh_list")],
        [InlineKeyboardButton("➕ Добавить привычку", callback_data="help_add")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс всех привычек с подтверждением"""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, сбросить всё", callback_data="reset_confirm"),
            InlineKeyboardButton("❌ Нет, отмена", callback_data="reset_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "⚠️ **ВНИМАНИЕ!**\n\n"
        "Вы действительно хотите сбросить ВСЕ привычки?\n"
        "Это действие нельзя отменить!\n\n"
        "Все данные о прогрессе будут потеряны.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def set_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка времени напоминания"""
    user_id = update.effective_user.id

    if not context.args:
        current_time = await storage.get_reminder_time(user_id)
        await update.message.reply_text(
            f"⏰ **Текущее время напоминания:** {current_time}\n\n"
            f"Чтобы изменить, отправьте:\n"
            f"`/set_reminder ЧЧ:ММ`\n\n"
            f"Пример: `/set_reminder 09:00`",
            parse_mode='Markdown'
        )
        return

    time_str = context.args[0]
    try:
        hour, minute = map(int, time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ **Неверный формат времени**\n\n"
            "Используйте формат ЧЧ:ММ (24-часовой)\n"
            "Пример: `/set_reminder 09:00`",
            parse_mode='Markdown'
        )
        return

    success = await storage.set_reminder_time(user_id, f"{hour:02d}:{minute:02d}")

    if success:
        await update.message.reply_text(
            f"✅ **Время напоминания установлено**\n\n"
            f"⏰ {hour:02d}:{minute:02d}\n\n"
            f"Я буду напоминать о привычках каждый день!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Ошибка при установке времени.")


async def delete_habit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление привычки"""
    if not context.args:
        await update.message.reply_text(
            "❌ **Укажите ID привычки**\n\n"
            "Пример: `/delete_habit 1`\n"
            "Посмотреть ID можно через `/list_habits`",
            parse_mode='Markdown'
        )
        return

    try:
        habit_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")
        return

    user_id = update.effective_user.id
    success = await storage.delete_habit(user_id, habit_id)

    if success:
        await update.message.reply_text("✅ Привычка успешно удалена!")
    else:
        await update.message.reply_text("❌ Привычка с таким ID не найдена.")


async def edit_habit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование названия привычки"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ **Укажите ID и новое название**\n\n"
            "Пример: `/edit_habit 1 Новая зарядка`",
            parse_mode='Markdown'
        )
        return

    try:
        habit_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")
        return

    new_name = " ".join(context.args[1:])
    user_id = update.effective_user.id

    success = await storage.edit_habit_name(user_id, habit_id, new_name)

    if success:
        await update.message.reply_text(f"✅ Название привычки изменено на: **{new_name}**", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Привычка с таким ID не найдена.")


async def export_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт данных в файл"""
    user_id = update.effective_user.id
    habits = await storage.get_habits(user_id)

    if not habits:
        await update.message.reply_text("📋 У вас пока нет данных для экспорта.")
        return

    report = f"📊 ОТЧЕТ ПО ПРИВЫЧКАМ\n"
    report += f"{'=' * 40}\n"
    report += f"📅 Дата: {date.today()}\n"
    report += f"👤 Пользователь: {update.effective_user.first_name}\n"
    report += f"{'=' * 40}\n\n"

    for habit in habits:
        report += f"📌 {habit['name']} (ID: {habit['id']})\n"
        report += f"   🔥 Стрейк: {habit['streak']} дней\n"
        report += f"   📅 Создана: {habit['created']}\n"
        report += f"   ✅ Всего выполнений: {len(habit['history'])}\n"
        report += f"   📆 Календарь за неделю: {get_week_calendar(habit['history'])}\n\n"

    from io import BytesIO
    file = BytesIO(report.encode('utf-8'))
    file.name = f"habits_report_{user_id}_{date.today()}.txt"

    await update.message.reply_document(
        document=file,
        filename=file.name,
        caption="📄 Ваш отчет по привычкам"
    )


# ==================== НАПОМИНАНИЯ ====================

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневное напоминание о привычках"""
    user_id = context.job.user_id

    habits = await storage.get_habits(user_id)
    if not habits:
        return

    unchecked = []
    today = date.today().isoformat()

    for habit in habits:
        if today not in habit["history"]:
            unchecked.append(f"• {habit['name']} (ID: `{habit['id']}`)")

    if unchecked:
        keyboard = []
        for habit in habits:
            if today not in habit["history"]:
                button = InlineKeyboardButton(
                    f"✅ {habit['name']}",
                    callback_data=f"check_{habit['id']}"
                )
                keyboard.append([button])

        keyboard.append([InlineKeyboardButton("📋 Все привычки", callback_data="refresh_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = (
                "🌅 **Доброе утро!**\n\n"
                "📋 **Сегодня еще не отмечены:**\n" +
                "\n".join(unchecked) +
                "\n\n🎯 Нажми на кнопку, чтобы отметить выполнение!"
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )


def setup_daily_reminder(application: Application, user_id: int, hour: int = 9, minute: int = 0):
    """Настраивает ежедневное напоминание"""
    job_queue = application.job_queue
    if not job_queue:
        return

    # Удаляем старые задания
    for job in job_queue.jobs():
        if hasattr(job, 'user_id') and job.user_id == user_id:
            job.schedule_removal()

    job_queue.run_daily(
        daily_reminder,
        time=datetime.time(hour=hour, minute=minute),
        days=tuple(range(7)),
        user_id=user_id,
        name=f"reminder_{user_id}"
    )


async def post_start(application: Application):
    """Запускает напоминания после старта бота"""
    for user_id in storage._cache.keys():
        user_data = await storage.get_user_data(user_id)
        reminder_time = user_data.get("reminder_time", "09:00")
        hour, minute = map(int, reminder_time.split(':'))
        setup_daily_reminder(application, user_id, hour, minute)
        logger.info(f"⏰ Настроено напоминание для пользователя {user_id} на {reminder_time}")


# ==================== ОБРАБОТЧИКИ ИНЛАЙН-КНОПОК ====================

async def inline_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех инлайн-кнопок"""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data.startswith("check_"):
        habit_id = int(data.split("_")[1])
        success = await storage.mark_done(user_id, habit_id)

        if success:
            habits = await storage.get_habits(user_id)
            habit = next((h for h in habits if h["id"] == habit_id), None)

            if habit:
                text = f"✅ **{habit['name']}** отмечена!\n🔥 Стрейк: {habit['streak']} дней"
            else:
                text = "✅ Привычка отмечена!"

            await query.edit_message_text(text, parse_mode='Markdown')
        else:
            await query.edit_message_text(
                "❌ **Не удалось отметить**\n\nВозможно, вы уже отмечали сегодня.",
                parse_mode='Markdown'
            )

    elif data == "refresh_list":
        habits = await storage.get_habits(user_id)
        if habits:
            text = get_habits_list_text(habits)
            keyboard = []
            for habit in habits:
                today_check = date.today().isoformat()
                is_done = today_check in habit["history"]
                status = "✅" if is_done else "🔄"
                button = InlineKeyboardButton(
                    f"{status} {habit['name']} | 🔥{habit['streak']}",
                    callback_data=f"check_{habit['id']}"
                )
                keyboard.append([button])
            keyboard.append([
                InlineKeyboardButton("🔄 Обновить", callback_data="refresh_list"),
                InlineKeyboardButton("📊 Статистика", callback_data="show_stats")
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await query.edit_message_text("📋 У вас пока нет привычек.")

    elif data == "show_stats":
        stats = await storage.get_stats(user_id, 7)
        if stats:
            text = get_stats_text(stats, 7)
            keyboard = [
                [InlineKeyboardButton("📋 Список привычек", callback_data="refresh_list")],
                [InlineKeyboardButton("➕ Добавить привычку", callback_data="help_add")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await query.edit_message_text("📊 Нет данных для статистики.")

    elif data == "help_add":
        await query.edit_message_text(
            "📝 **Как добавить привычку:**\n\n"
            "Используй команду:\n"
            "`/add_habit Название привычки`\n\n"
            "Пример:\n"
            "`/add_habit Зарядка`\n"
            "`/add_habit Чтение книги`",
            parse_mode='Markdown'
        )

    elif data == "help_commands":
        text = (
            "📚 **Доступные команды:**\n\n"
            "`/add_habit [название]` - добавить привычку\n"
            "`/list_habits` - список привычек\n"
            "`/check [ID]` - отметить выполнение\n"
            "`/delete_habit [ID]` - удалить привычку\n"
            "`/edit_habit [ID] [название]` - изменить название\n"
            "`/stats [дней]` - статистика\n"
            "`/set_reminder [время]` - время напоминания\n"
            "`/export_data` - экспорт данных\n"
            "`/reset` - сбросить всё"
        )
        await query.edit_message_text(text, parse_mode='Markdown')

    elif data == "reset_confirm":
        await storage.reset_user(user_id)
        await query.edit_message_text(
            "🔄 **Все привычки сброшены!**\n\n"
            "Вы можете начать заново с `/add_habit`",
            parse_mode='Markdown'
        )

    elif data == "reset_cancel":
        await query.edit_message_text("❌ Сброс отменен.")


# ==================== ЗАПУСК БОТА (WEBHOOK ДЛЯ AMVERA) ====================

def main():
    """Запуск бота через вебхук для Amvera"""
    print("🚀 Запуск бота для трекинга привычек на Amvera...")
    print(f"🤖 Токен: {TOKEN[:10]}...")
    print(f"🌐 Вебхук URL: {WEBHOOK_URL}")

    # Создаём приложение
    application = Application.builder().token(TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_habit", add_habit))
    application.add_handler(CommandHandler("list_habits", list_habits))
    application.add_handler(CommandHandler("check", check_habit))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("set_reminder", set_reminder_command))
    application.add_handler(CommandHandler("delete_habit", delete_habit_command))
    application.add_handler(CommandHandler("edit_habit", edit_habit_command))
    application.add_handler(CommandHandler("export_data", export_data_command))

    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(inline_button_handler))

    # Запускаем напоминания после старта
    async def on_startup():
        await post_start(application)

    # Добавляем обработчик запуска
    application.post_init = on_startup

    # Запускаем через вебхук (для Amvera)
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=WEBHOOK_URL
    )


if __name__ == "__main__":
    main()