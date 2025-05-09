import os
import logging
import sqlite3
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup, ChatInviteLink
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, PreCheckoutQueryHandler
from pathlib import Path
from datetime import datetime, timedelta, time

# Настройки бота
TOKEN = os.getenv('TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
PROVIDER_TOKEN = os.getenv('PROVIDER_TOKEN')

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
DATABASE_NAME = DATA_DIR / "subscriber.db"

# Создаем Flask приложение
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is running"

def init_db():
    """Инициализация базы данных"""
    try:
        conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriber (
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
        ON subscriber(subscription_end)
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
    
    day = TARIFFS[tariff]['days']
    subscription_end = (datetime.now() + timedelta(days=day)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("""
    INSERT OR REPLACE INTO subscriber (user_id, username, full_name, subscription_end, tariff, invite_link)
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
    SELECT subscription_end FROM subscriber 
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
    SELECT username, full_name, subscription_end, tariff, invite_link FROM subscriber 
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

# Инициализируем базу данных при запуске
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

def get_tariff_keyboard():
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
            reply_markup=get_tariff_keyboard()
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
        
        message = await update.message.reply_text(
            f"🎉 Оплата принята! Ваша ссылка для вступления в канал:\n"
            f"{invite_link.invite_link}\n\n"
            f"⚠️ Внимание:\n"
            f"1. Ссылка одноразовая\n"
            f"2. Срок действия: {days} дней\n"
            f"3. Не передавайте ссылку другим\n"
            f"4. Не выходите из канала, иначе придется покупать доступ заново!\n"
            f"5. Не обновляйте меню, пока не перейдете по ссылке!",
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при создании ссылки: {e}")
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, обратитесь в поддержку.",
            reply_markup=get_main_keyboard()
        )

async def track_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

async def check_expired_subscription(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет истекшие подписки"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""
    SELECT user_id FROM subscriber 
    WHERE subscription_end <= ?
    """, (current_time,))
    
    expired_user = cursor.fetchall()
    
    for user in expired_user:
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
                
            cursor.execute("DELETE FROM subscriber WHERE user_id = ?", (user_id,))
            
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя {user_id} из канала: {e}")
    
    conn.commit()
    conn.close()

async def check_upcoming_expiration(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет подписки, которые истекают через 1 день"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT user_id, subscription_end FROM subscriber 
    WHERE subscription_end BETWEEN datetime('now') AND datetime('now', '+1 day')
    """)
    
    expiring_user = cursor.fetchall()
    
    for user in expiring_user:
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

def run_flask():
    """Запуск Flask сервера"""
    port = int(os.getenv('PORT', 5000))
    flask_app.run(host='0.0.0.0', port=port)

def main() -> None:
    """Основная функция запуска"""
    # Инициализируем бота с JobQueue
    app = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.StatusUpdate.NEW_CHAT_MEMBERS, track_new_member))
    
    # Настраиваем JobQueue
    if hasattr(app, 'job_queue'):
        app.job_queue.run_repeating(check_expired_subscription, interval=21600, first=10)
        app.job_queue.run_daily(check_upcoming_expiration, time=time(hour=12, minute=0))
    else:
        logger.warning("JobQueue не доступен. Периодические задачи не будут выполняться.")
    
    # Запускаем Flask в основном потоке
    from threading import Thread
    Thread(target=run_flask).start()
    
    # Запускаем бота в текущем потоке
    app.run_polling()

if __name__ == '__main__':
    main()
