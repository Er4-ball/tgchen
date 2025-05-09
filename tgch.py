import logging
import sqlite3
import asyncio
from datetime import datetime, timedelta
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup, ChatInviteLink
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, PreCheckoutQueryHandler
from pathlib import Path
from datetime import datetime, timedelta, time
from flask import Flask
from threading import Thread
import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Проверка и загрузка обязательных переменных
def get_env_var(name: str, required: bool = True, default=None):
    value = os.getenv(name, default)
    if required and value is None:
        raise ValueError(f"Необходимо указать переменную окружения: {name}")
    return value

TOKEN = get_env_var('BOT_TOKEN')
ADMIN_ID = int(get_env_var('AD_ID'))
CHANNEL_ID = int(get_env_var('CHEN_ID'))
PROVIDER_TOKEN = get_env_var('PROVIDE_TOKEN')
PORT = int(get_env_var('PORT', required=False, default=8080))

# Тарифы (в копейках)
TARIFFS = {
    '1_month': {'price': 29900, 'days': 30, 'label': '1 месяц - 299₽'},
    '3_months': {'price': 79900, 'days': 90, 'label': '3 месяца - 799₽'},
    '6_months': {'price': 149900, 'days': 180, 'label': '6 месяцев - 1499₽'},
    '1_year': {'price': 299900, 'days': 365, 'label': '1 год - 2999₽'}
}

# Логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Путь к базе данных
DATA_DIR = Path(__file__).parent
DATABASE_NAME = DATA_DIR / "subscribers.db"

def init_db():
    """Инициализация базы данных"""
    try:
        conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            subscription_end TEXT,
            payment_date TEXT DEFAULT CURRENT_TIMESTAMP,
            tariff TEXT,
            invite_link TEXT
        )
        """)
        
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscription_end 
        ON subscribers(subscription_end)
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"База данных создана: {DATABASE_NAME}")
    except Exception as e:
        logger.error(f"Ошибка при создании базы: {e}")
        raise

def add_subscriber(user_id: int, username: str, full_name: str, tariff: str, invite_link: str = None):
    """Добавляет подписчика в базу данных"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    days = TARIFFS[tariff]['days']
    subscription_end = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("""
    INSERT OR REPLACE INTO subscribers (user_id, username, full_name, subscription_end, tariff, invite_link)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, username, full_name, subscription_end, tariff, invite_link))
    
    conn.commit()
    conn.close()

def check_subscription(user_id: int) -> bool:
    """Проверяет наличие активной подписки"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""
    SELECT subscription_end FROM subscribers 
    WHERE user_id = ? AND subscription_end > ?
    """, (user_id, current_time))
    
    result = cursor.fetchone()
    conn.close()
    
    return result is not None

def get_subscriber_info(user_id: int) -> dict:
    """Возвращает информацию о подписчике"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT username, full_name, subscription_end, tariff, invite_link FROM subscribers 
    WHERE user_id = ?
    """, (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            "username": result[0],
            "full_name": result[1],
            "subscription_end": result[2],
            "tariff": result[3],
            "invite_link": result[4]
        }
    return None

# Инициализация базы данных
init_db()

def get_main_keyboard():
    """Создает основную клавиатуру"""
    keyboard = [
        [InlineKeyboardButton("💰 Купить подписку", callback_data='choose_tariff')],
        [InlineKeyboardButton("🔐 Проверить доступ", callback_data='check')],
        [InlineKeyboardButton("🆘 Поддержка", url="https://t.me/mitsuki1221")],
        [InlineKeyboardButton("🔄 Обновить меню", callback_data='refresh')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_tariffs_keyboard():
    """Клавиатура с выбором тарифа"""
    keyboard = [
        [InlineKeyboardButton(TARIFFS['1_month']['label'], callback_data='tariff_1_month')],
        [InlineKeyboardButton(TARIFFS['3_months']['label'], callback_data='tariff_3_months')],
        [InlineKeyboardButton(TARIFFS['6_months']['label'], callback_data='tariff_6_months')],
        [InlineKeyboardButton(TARIFFS['1_year']['label'], callback_data='tariff_1_year')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start"""
    await update.message.reply_text(
        "🔮 Доступ к эксклюзивным прогнозам:",
        reply_markup=get_main_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'choose_tariff':
        await query.edit_message_text(
            "Выберите тариф подписки:",
            reply_markup=get_tariffs_keyboard()
        )
    elif query.data == 'back':
        await query.edit_message_text(
            "🔮 Доступ к эксклюзивным прогнозам:",
            reply_markup=get_main_keyboard()
        )
    elif query.data.startswith('tariff_'):
        tariff = query.data.replace('tariff_', '')
        await send_invoice(update, context, tariff)
    elif query.data == 'check':
        if check_subscription(query.from_user.id):
            user_info = get_subscriber_info(query.from_user.id)
            end_date = user_info['subscription_end'][:10]
            tariff_label = TARIFFS.get(user_info['tariff'], {}).get('label', 'Неизвестный тариф')
            await query.edit_message_text(
                f"✅ Доступ активен до {end_date}\n"
                f"Тариф: {tariff_label}\n"
                f"Канал: CryptoSignals HQ\n\n"
                f"⚠️ Внимание: если вы выйдете из канала до окончания подписки, "
                f"вам придется покупать доступ заново!",
                reply_markup=get_main_keyboard()
            )
        else:
            await query.edit_message_text(
                "❌ Подписка не оформлена или истекла",
                reply_markup=get_main_keyboard()
            )
    elif query.data == 'refresh':
        await query.edit_message_text(
            "🔮 Доступ к эксклюзивным прогнозам:",
            reply_markup=get_main_keyboard()
        )

async def send_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, tariff: str):
    """Отправка платежной формы"""
    query = update.callback_query
    tariff_info = TARIFFS[tariff]
    
    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title=f"Подписка на {tariff_info['label'].split(' - ')[0]}",
        description=f"Доступ к каналу на {tariff_info['label']}",
        payload=f"subscription_{tariff}",
        provider_token=PROVIDER_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(tariff_info['label'], tariff_info['price'])],
        need_email=True
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка платежа"""
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("subscription_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Ошибка оплаты")

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка успешной оплаты"""
    user = update.effective_user
    tariff = update.message.successful_payment.invoice_payload.replace('subscription_', '')
    days = TARIFFS[tariff]['days']
    
    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            name=f"sub_{user.id}"
        )
        
        add_subscriber(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            tariff=tariff,
            invite_link=invite_link.invite_link
        )
        
        await update.message.reply_text(
            f"🎉 Оплата принята! Ваша ссылка для вступления в канал:\n"
            f"{invite_link.invite_link}\n\n"
            f"⚠️ Внимание:\n"
            f"1. Ссылка одноразовая\n"
            f"2. Срок действия: {days} дней\n"
            f"3. Не передавайте ссылку другим\n"
            f"4. Не выходите из канала, тогда придется покупать доступ заново!\n"
            f"5. Не обновляйте меню пока не перейдете, ссылка пропадет!",
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при создании ссылки: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, обратитесь в поддержку.",
            reply_markup=get_main_keyboard()
        )

async def track_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отслеживает новых участников канала"""
    if update.message.chat.id == CHANNEL_ID:
        for user in update.message.new_chat_members:
            if user.id != context.bot.id:
                if check_subscription(user.id):
                    try:
                        await context.bot.send_message(
                            chat_id=user.id,
                            text="✅ Вы успешно вступили в канал!",
                            reply_markup=get_main_keyboard()
                        )
                    except Exception as e:
                        logger.error(f"Ошибка отправки подтверждения: {e}")

async def check_expired_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет истекшие подписки"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""
    SELECT user_id FROM subscribers 
    WHERE subscription_end <= ?
    """, (current_time,))
    
    expired_users = cursor.fetchall()
    
    for user in expired_users:
        user_id = user[0]
        try:
            await context.bot.ban_chat_member(
                chat_id=CHANNEL_ID,
                user_id=user_id,
                until_date=int((datetime.now() + timedelta(days=365)).timestamp())
            )
            
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Ваша подписка истекла. Доступ к каналу закрыт.\n"
                         "Чтобы возобновить доступ, приобретите новую подписку.",
                    reply_markup=get_main_keyboard()
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")
                
            cursor.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
            
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя {user_id} из канала: {e}")
    
    conn.commit()
    conn.close()

async def check_upcoming_expirations(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет подписки, которые истекают через 1 день"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT user_id, subscription_end FROM subscribers 
    WHERE subscription_end BETWEEN datetime('now') AND datetime('now', '+1 day')
    """)
    
    expiring_users = cursor.fetchall()
    
    for user in expiring_users:
        user_id = user[0]
        expiration_date = datetime.fromisoformat(user[1]).strftime('%Y-%m-%d')
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ Ваша подписка истекает {expiration_date}!\n"
                     f"Продлите подписку, чтобы сохранить доступ к каналу.",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Не удалось отправить предупреждение пользователю {user_id}: {e}")
    
    conn.close()

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get('PORT', 8080)) 
    app.run(host='0.0.0.0', port=port)

async def run_bot():
    """Асинхронный запуск бота"""
    bot_app = Application.builder().token(TOKEN).build()
    
    # Регистрация обработчиков
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(PreCheckoutQueryHandler(precheckout))
    bot_app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    bot_app.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.StatusUpdate.NEW_CHAT_MEMBERS, track_new_members))
    
    # Планировщик задач
    job_queue = bot_app.job_queue
    if job_queue:
        job_queue.run_repeating(check_expired_subscriptions, interval=21600, first=10)
        job_queue.run_daily(check_upcoming_expirations, time=time(hour=12, minute=0))
    
    await bot_app.run_polling()

def main():
    """Главная функция запуска"""
    try:
        # Запускаем Flask в отдельном потоке
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Запускаем бота в основном потоке
        asyncio.run(run_bot())
        
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
        raise

if __name__ == '__main__':
    main()
