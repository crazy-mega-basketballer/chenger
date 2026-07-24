"""
Обработчики команд для обычных пользователей.
"""

import asyncio
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import storage


def build_moderation_callback_data(prefix: str, user_id: int, video_id: int) -> str:
    """Создаёт callback-data для отдельной модерации видео."""
    return f"{prefix}_{user_id}_{video_id}"

logger = logging.getLogger(__name__)

# Роутер для пользовательских команд
user_router = Router()

_pending_media_batches = {}
_pending_media_tasks = {}


def get_runtime_bot():
    """Возвращает инициализированный экземпляр бота из основного модуля запуска."""
    try:
        import importlib
        import sys

        main_module = sys.modules.get("__main__")
        if main_module and hasattr(main_module, "get_bot"):
            bot = main_module.get_bot()
            if bot is not None:
                return bot

        bot_module = importlib.import_module("bot")
        return bot_module.get_bot()
    except Exception as exc:
        logger.debug("Не удалось получить экземпляр бота: %s", exc)
        return None


async def safe_answer_callback(event) -> None:
    """Безопасно отвечает на callback, игнорируя устаревшие query ID."""
    try:
        if hasattr(event, "answer"):
            await event.answer()
    except Exception as exc:
        if "query is too old" in str(exc).lower() or "query id is invalid" in str(exc).lower():
            logger.info("Игнорируем устаревший callback-query: %s", exc)
        else:
            logger.warning("Не удалось ответить на callback: %s", exc)


def is_admin_message(message: Message, admin_id: int) -> bool:
    """Проверяет, что сообщение пришло от администратора."""
    return bool(message.from_user and message.from_user.id == admin_id)


def get_remaining_videos(progress: dict) -> int:
    """Возвращает количество видео, которое осталось пользователю."""
    return max(0, progress['limit'] - progress['last_video_id'])


def get_media_duration_seconds(message: Message) -> int | None:
    """Возвращает длительность видео или video_note в секундах, если она доступна."""
    media = getattr(message, 'video', None)
    if media is not None:
        return getattr(media, 'duration', None)

    media = getattr(message, 'video_note', None)
    if media is not None:
        return getattr(media, 'duration', None)

    return None

# Текст приветствия и инструкций
WELCOME_TEXT = """
🎥 <b>Добро пожаловать в Video Bot!</b>

Этот бот позволяет смотреть видео по очереди. У каждого пользователя есть лимит просмотров.

<b>📋 Основные команды:</b>

▪️ <b>Получить видео</b> — смотреть следующее видео
▪️ <b>Мой профиль</b> — показать текущий лимит и прогресс
▪️ <b>Реферальная ссылка</b> — пригласить друга (+15 к лимиту)
▪️ <b>Ежедневный бонус +10</b> — получить бонус раз в сутки

<b>💡 Как увеличить лимит:</b>

1️⃣ <b>Загрузить своё видео или кружок</b> — просто отправьте видео/кружок боту (вы сразу получите бонус, но если видео будет некачественным, вас могут забанить)
2️⃣ <b>Пригласить друга</b> — за каждого приглашённого +15 к лимиту
3️⃣ <b>Ежедневный бонус</b> — получайте +10 раз в сутки (обновляется в полночь)

<b>🎬 Начальный лимит:</b> 5 видео

Нажмите кнопку ниже, чтобы начать! 👇
"""


def get_main_keyboard():
    """Создаёт главную клавиатуру с кнопками"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎥 Получить видео", callback_data="get_video")
    builder.button(text="👤 Мой профиль", callback_data="profile")
    builder.button(text="🔗 Реферальная ссылка", callback_data="referral")
    builder.button(text="🎁 Ежедневный бонус +10", callback_data="daily_bonus")
    builder.button(text="❓ Помощь", callback_data="help")
    builder.adjust(1)  # По одной кнопке в ряд
    return builder.as_markup()


@user_router.message(CommandStart())
async def cmd_start(message: Message, bot_username: str, admin_id: int):
    """
    Обработчик команды /start.
    Проверяет реферальный код, показывает приветствие.
    """
    user_id = message.from_user.id

    # Проверка на администратора
    if user_id == admin_id:
        await message.answer(
            f"👨‍💼 <b>Панель администратора</b>\n\n"
            f"Доступные команды:\n\n"
            f"📊 /stats — общая статистика бота\n"
            f"👤 /user <code>user_id</code> — статистика пользователя\n"
            f"🏆 /top — топ-10 активных пользователей\n"
            f"📋 /list — список всех видео\n"
            f"📤 /broadcast <code>текст</code> — рассылка всем пользователям\n\n"
            f"<b>Управление пользователями:</b>\n"
            f"🚫 /ban <code>user_id</code> — забанить пользователя (временно)\n"
            f"🔒 /permaban <code>user_id</code> — забанить пользователя навсегда\n"
            f"✅ /unban <code>user_id</code> — разбанить пользователя\n"
            f"🎯 /setlimit <code>user_id</code> <code>limit</code> — изменить лимит пользователя\n"
            f"🔄 /reset <code>user_id</code> — сбросить прогресс пользователя\n"
            f"🔄 /reset_all — сбросить прогресс всех пользователей\n\n"
            f"<b>Управление видео:</b>\n"
            f"🗑 /delvideo <code>video_id</code> — удалить видео по ID\n"
            f"🗑 /delrange <code>start-end</code> — удалить диапазон видео (например: 750-754)\n"
            f"🗑 /deluservideos <code>user_id</code> — удалить все видео пользователя\n"
            f"🗑 /delafter <code>количество</code> <code>начиная_с_ID</code> — удалить N видео после указанного\n"
            f"ℹ️ <b>Ответ /info на видео</b> — получить информацию о видео\n"
            f"🗑 <b>Ответ любым текстом на видео</b> — удалить видео\n"
            f"🧹 /clear — очистить весь архив\n\n"
            f"📹 <b>Загрузка видео:</b>\n"
            f"Просто отправьте видео или кружок боту — оно автоматически добавится в архив.\n\n"
            f"📤 <b>Модерация:</b>\n"
            f"Когда пользователи отправляют видео/кружки, они сразу добавляются в архив.\n"
            f"Видео приходит с подписью (от кого и номер видео).\n"
            f"Ответьте /info на видео для получения информации.\n"
            f"Ответьте любым текстом на видео для его удаления.",
            parse_mode="HTML"
        )
        return

    # Проверка на бан
    ban_timestamp = storage.check_ban(user_id)
    if ban_timestamp:
        unban_date = datetime.fromtimestamp(ban_timestamp).strftime("%d.%m.%Y %H:%M")
        await message.answer(
            f"❌ <b>Вы заблокированы до {unban_date}</b>\n\n"
            f"Обратитесь к администратору, если считаете это ошибкой.",
            parse_mode="HTML"
        )
        return

    # Проверяем, существует ли пользователь ДО обработки реферальной ссылки
    existing_user = storage.load_user_progress(user_id, create_if_missing=False)
    user_existed_before = existing_user is not None

    # Обработка реферальной ссылки
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))

            # Проверяем, что это не сам пользователь
            if referrer_id != user_id:
                # Проверяем, что реферер существует и не забанен
                referrer_ban = storage.check_ban(referrer_id)
                if not referrer_ban:
                    # Бонус начисляется только если пользователь абсолютно новый
                    # (его запись еще не существовала в базе до этого момента)
                    if not user_existed_before:
                        # Создаем пользователя и сразу привязываем реферера
                        progress = storage.load_user_progress(user_id, create_if_missing=True)

                        if storage.add_referral(referrer_id, user_id):
                            # Уведомляем реферера
                            try:
                                referrer_progress = storage.load_user_progress(referrer_id)
                                remaining = get_remaining_videos(referrer_progress)
                                current_bot = get_runtime_bot()
                                if current_bot is None:
                                    raise RuntimeError("Bot instance is not initialized")
                                await current_bot.send_message(
                                    referrer_id,
                                    f"🎉 <b>Отличные новости!</b>\n\n"
                                    f"По вашей реферальной ссылке зарегистрировался новый пользователь!\n"
                                    f"Осталось видео: <b>{remaining}</b>\n"
                                    f"Всего приглашено: <b>{referrer_progress['referrals_count']}</b>",
                                    parse_mode="HTML"
                                )
                            except Exception as e:
                                logger.error(f"Не удалось уведомить реферера {referrer_id}: {e}")

                        logger.info(
                            f"Реферал: новый пользователь {user_id} зарегистрирован по ссылке {referrer_id}"
                        )
                    else:
                        logger.info(
                            f"Реферал не засчитан: пользователь {user_id} уже существовал в системе"
                        )
        except ValueError:
            pass

    # Убеждаемся, что пользователь создан (если еще не был создан выше)
    if not user_existed_before and not (len(args) > 1 and args[1].startswith("ref_")):
        storage.load_user_progress(user_id, create_if_missing=True)

    # Отправляем приветственное сообщение
    await message.answer(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


@user_router.message(Command("help"))
@user_router.callback_query(F.data == "help")
async def cmd_help(event, admin_id: int):
    """Показывает справку (те же инструкции, что и при /start)"""
    if isinstance(event, CallbackQuery):
        await safe_answer_callback(event)
        await event.message.edit_text(
            WELCOME_TEXT,
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    else:
        user_id = event.from_user.id
        ban_timestamp = storage.check_ban(user_id)
        if ban_timestamp:
            unban_date = datetime.fromtimestamp(ban_timestamp).strftime("%d.%m.%Y %H:%M")
            await event.answer(
                f"❌ <b>Вы заблокированы до {unban_date}</b>",
                parse_mode="HTML"
            )
            return

        await event.answer(
            WELCOME_TEXT,
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )


@user_router.message(Command("next"))
@user_router.callback_query(F.data == "get_video")
async def get_next_video(event, admin_id: int):
    """
    Выдаёт пользователю следующее видео.
    Проверяет бан, лимит, прогресс.
    """
    # Определяем тип события (сообщение или callback)
    if isinstance(event, CallbackQuery):
        await safe_answer_callback(event)
        message = event.message
        user_id = event.from_user.id
    else:
        message = event
        user_id = event.from_user.id

    # Проверка на бан
    ban_timestamp = storage.check_ban(user_id)
    if ban_timestamp:
        unban_date = datetime.fromtimestamp(ban_timestamp).strftime("%d.%m.%Y %H:%M")
        await message.answer(
            f"❌ <b>Вы заблокированы до {unban_date}</b>",
            parse_mode="HTML"
        )
        return

    # Загружаем прогресс пользователя
    progress = storage.load_user_progress(user_id)
    last_video_id = progress['last_video_id']
    limit = progress['limit']

    available_videos = max(0, limit - last_video_id)

    if available_videos <= 0:
        await message.answer(
            f"⛔ <b>Больше доступных видео нет</b>\n\n"
            f"Осталось видео: <b>0</b>\n\n"
            f"<b>💡 Как увеличить количество доступных видео:</b>\n\n"
            f"1️⃣ <b>Загрузите своё видео или кружок</b> — отправьте видео/кружок боту (вы сразу получите бонус, но если видео будет некачественным, вас могут забанить)\n"
            f"2️⃣ <b>Пригласите друга</b> — нажмите 'Реферальная ссылка' (+15 за друга)\n"
            f"3️⃣ <b>Ежедневный бонус</b> — нажмите 'Ежедневный бонус +10' (+10 раз в сутки)",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    # Ищем следующее видео
    videos = storage.load_videos()
    next_video = None

    for video in videos:
        if video['id'] > last_video_id:
            next_video = video
            break

    if not next_video:
        await message.answer(
            f"🎬 <b>Поздравляем!</b>\n\n"
            f"Вы посмотрели все доступные видео в архиве.\n"
            f"Ожидайте новые видео или пригласите друзей!",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    # Отправляем видео пользователю (без подписи, без пересылки)
    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")

        # Получаем оригинальное сообщение для извлечения file_id
        original_message = await current_bot.forward_message(
            chat_id=admin_id,  # Временно пересылаем админу (самому себе)
            from_chat_id=next_video['chat_id'],
            message_id=next_video['message_id']
        )

        # Удаляем временное пересланное сообщение
        await current_bot.delete_message(chat_id=admin_id, message_id=original_message.message_id)

        # Определяем тип медиа и получаем file_id
        file_id = None
        media_type = None

        if original_message.video:
            file_id = original_message.video.file_id
            media_type = "video"
        elif original_message.video_note:
            file_id = original_message.video_note.file_id
            media_type = "video_note"

        if not file_id:
            raise RuntimeError("Не удалось получить file_id видео")

        # Отправляем видео пользователю БЕЗ подписи
        if media_type == "video":
            await current_bot.send_video(
                chat_id=user_id,
                video=file_id,
                protect_content=True
            )
        elif media_type == "video_note":
            await current_bot.send_video_note(
                chat_id=user_id,
                video_note=file_id,
                protect_content=True
            )

        # Обновляем прогресс ТОЛЬКО после успешной отправки
        progress['last_video_id'] = next_video['id']
        storage.save_user_progress(progress)

        remaining = max(0, limit - next_video['id'])
        await message.answer(
            f"Осталось видео: <b>{remaining}</b>",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )

        logger.info(f"Пользователь {user_id} получил видео #{next_video['id']}")

    except Exception as e:
        logger.error(f"Ошибка при отправке видео #{next_video['id']} пользователю {user_id}: {e}")

        # Если видео удалено из чата админа - удаляем его из списка и НЕ уменьшаем лимит
        if "message to copy not found" in str(e).lower() or "message_id_invalid" in str(e).lower():
            logger.warning(f"Видео #{next_video['id']} удалено из чата админа, удаляем из списка")
            storage.delete_video(next_video['id'])

            # Пропускаем видео - сообщаем пользователю без номера
            await message.answer(
                f"⚠️ <b>Видео недоступно</b>\n\n"
                f"Попробуйте получить следующее видео.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        else:
            # При любой другой ошибке тоже не уменьшаем лимит
            await message.answer(
                f"❌ <b>Ошибка при отправке видео</b>\n\n"
                f"Попробуйте позже или обратитесь к администратору.",
                parse_mode="HTML"
            )


@user_router.message(Command("profile"))
@user_router.callback_query(F.data == "profile")
async def show_profile(event, admin_id: int):
    """Показывает профиль пользователя"""
    if isinstance(event, CallbackQuery):
        await safe_answer_callback(event)
        message = event.message
        user_id = event.from_user.id
    else:
        message = event
        user_id = event.from_user.id

    # Проверка на бан
    ban_timestamp = storage.check_ban(user_id)
    if ban_timestamp:
        unban_date = datetime.fromtimestamp(ban_timestamp).strftime("%d.%m.%Y %H:%M")
        await message.answer(
            f"❌ <b>Вы заблокированы до {unban_date}</b>",
            parse_mode="HTML"
        )
        return

    # Загружаем прогресс
    progress = storage.load_user_progress(user_id)

    # Проверяем доступность ежедневного бонуса
    today = datetime.now().strftime("%Y-%m-%d")
    bonus_available = progress['daily_bonus_date'] != today

    bonus_text = "✅ <b>Доступен</b>" if bonus_available else "❌ Уже получен сегодня (доступен после полуночи)"

    available_videos = max(0, progress['limit'] - progress['last_video_id'])

    profile_text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"� <b>Просмотрено:</b> {progress['last_video_id']} видео\n"
        f"📦 <b>Осталось:</b> {available_videos} видео\n"
        f"👥 <b>Приглашено друзей:</b> {progress['referrals_count']}\n"
        f"🎁 <b>Ежедневный бонус:</b> {bonus_text}\n\n"
        f"💡 <i>Приглашайте друзей и получайте бонусы для увеличения доступного количества видео!</i>"
    )

    await message.answer(
        profile_text,
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


@user_router.message(Command("referral"))
@user_router.callback_query(F.data == "referral")
async def show_referral(event, bot_username: str, admin_id: int):
    """Показывает реферальную ссылку"""
    if isinstance(event, CallbackQuery):
        await safe_answer_callback(event)
        message = event.message
        user_id = event.from_user.id
    else:
        message = event
        user_id = event.from_user.id

    # Проверка на бан
    ban_timestamp = storage.check_ban(user_id)
    if ban_timestamp:
        unban_date = datetime.fromtimestamp(ban_timestamp).strftime("%d.%m.%Y %H:%M")
        await message.answer(
            f"❌ <b>Вы заблокированы до {unban_date}</b>",
            parse_mode="HTML"
        )
        return

    # Генерируем реферальную ссылку
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    # Загружаем прогресс для показа статистики
    progress = storage.load_user_progress(user_id)

    referral_text = (
        f"🔗 <b>Ваша реферальная ссылка:</b>\n\n"
        f"<code>{referral_link}</code>\n\n"
        f"👥 <b>Приглашено друзей:</b> {progress['referrals_count']}\n\n"
        f"💰 <b>За каждого приглашённого друга вы получаете +15 к лимиту!</b>\n\n"
        f"Просто отправьте эту ссылку друзьям, и когда они запустят бота — "
        f"ваш лимит автоматически увеличится."
    )

    await message.answer(
        referral_text,
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


@user_router.message(Command("daily_bonus"))
@user_router.callback_query(F.data == "daily_bonus")
async def daily_bonus(event, admin_id: int):
    """Выдаёт ежедневный бонус +10 к лимиту"""
    if isinstance(event, CallbackQuery):
        await safe_answer_callback(event)
        message = event.message
        user_id = event.from_user.id
    else:
        message = event
        user_id = event.from_user.id

    # Проверка на бан
    ban_timestamp = storage.check_ban(user_id)
    if ban_timestamp:
        unban_date = datetime.fromtimestamp(ban_timestamp).strftime("%d.%m.%Y %H:%M")
        await message.answer(
            f"❌ <b>Вы заблокированы до {unban_date}</b>",
            parse_mode="HTML"
        )
        return

    # Загружаем прогресс
    progress = storage.load_user_progress(user_id)

    # Проверяем, получал ли пользователь бонус сегодня
    today = datetime.now().strftime("%Y-%m-%d")

    if progress['daily_bonus_date'] == today:
        await message.answer(
            f"⏰ <b>Ежедневный бонус уже получен сегодня</b>\n\n"
            f"Следующий бонус будет доступен <b>завтра после полуночи</b>.\n\n"
            f"Ваш текущий лимит: <b>{progress['limit']}</b>",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    # Выдаём бонус
    progress['limit'] += 10
    progress['daily_bonus_date'] = today
    storage.save_user_progress(progress)

    remaining = get_remaining_videos(progress)
    await message.answer(
        f"🎁 <b>Поздравляем!</b>\n\n"
        f"Вы получили ежедневный бонус <b>+10</b> к доступному количеству видео!\n\n"
        f"Осталось видео: <b>{remaining}</b>\n\n"
        f"Следующий бонус будет доступен <b>завтра после полуночи</b>.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

    logger.info(f"Пользователь {user_id} получил ежедневный бонус, осталось видео: {remaining}")


async def _process_user_media_batch(messages: list[Message], admin_id: int):
    """Обрабатывает пакет видео/видеозаметок и добавляет их в архив сразу."""
    if not messages:
        return

    first_message = messages[0]
    user_id = first_message.from_user.id

    if user_id == admin_id:
        logger.info("Пропускаем пересылку видео администратора в админский чат")
        return

    ban_timestamp = storage.check_ban(user_id)
    if ban_timestamp:
        unban_date = datetime.fromtimestamp(ban_timestamp).strftime("%d.%m.%Y %H:%M")
        await first_message.answer(
            f"❌ <b>Вы заблокированы до {unban_date}</b>\n\n"
            f"Вы не можете отправлять видео.",
            parse_mode="HTML"
        )
        return

    username = first_message.from_user.username
    user_mention = f"@{username}" if username else f"ID: {user_id}"

    current_bot = get_runtime_bot()
    if current_bot is None:
        logger.error("Bot instance is not initialized")
        await first_message.answer(
            f"❌ <b>Ошибка при обработке видео</b>\n\n"
            f"Попробуйте позже.",
            parse_mode="HTML"
        )
        return

    video_ids = []
    rejected_short_count = 0
    duplicate_count = 0
    known_hashes = storage.load_duplicate_hashes()

    for message in messages:
        duration = get_media_duration_seconds(message)
        if duration is not None and duration < 10:
            rejected_short_count += 1
            continue

        # Получаем file_id (уникальный идентификатор файла в Telegram)
        file_id = None
        media = getattr(message, 'video', None)
        if media is not None:
            file_id = getattr(media, 'file_id', None)

        if file_id is None:
            media = getattr(message, 'video_note', None)
            if media is not None:
                file_id = getattr(media, 'file_id', None)

        # Если file_id не найден - пропускаем видео
        if not file_id:
            logger.warning(f"Не удалось получить file_id для видео от {user_id}")
            duplicate_count += 1
            continue

        # Проверяем на дубликат ДО копирования (используем file_id)
        duplicate_hash = storage.compute_file_hash(file_id.encode('utf-8'))
        if storage.is_duplicate_video_hash(duplicate_hash, known_hashes):
            duplicate_count += 1
            logger.info(f"Отклонен дубликат видео от {user_id}, хеш: {duplicate_hash[:16]}...")
            continue

        # Сохраняем хеш ПЕРЕД добавлением видео
        storage.save_duplicate_hash(duplicate_hash)
        known_hashes.add(duplicate_hash)

        # Добавляем видео в базу (получаем video_id для подписи)
        # Временно используем message_id из оригинального сообщения, потом обновим
        temp_video_id = storage.add_video(
            message_id=message.message_id,
            chat_id=message.chat.id,
            original_user_id=user_id
        )

        # Пересылаем видео администратору с подписью
        caption_text = (
            f"📹 Новое видео от {user_mention}\n"
            f"🆔 User ID: {user_id}\n"
            f"📹 Видео #{temp_video_id}"
        )

        try:
            # Определяем тип медиа и отправляем с подписью
            if message.video:
                forwarded = await current_bot.send_video(
                    chat_id=admin_id,
                    video=message.video.file_id,
                    caption=caption_text,
                    parse_mode="HTML"
                )
            else:  # video_note
                # Видеозаметки не поддерживают caption, поэтому копируем и отправляем текст отдельно
                forwarded = await current_bot.copy_message(
                    chat_id=admin_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id
                )
                await current_bot.send_message(
                    admin_id,
                    caption_text,
                    parse_mode="HTML"
                )

            logger.info(f"Видео #{temp_video_id} от {user_id} успешно переслано админу")

            # Обновляем запись в базе с правильным message_id и chat_id админа
            try:
                videos = storage.load_videos()
                for v in videos:
                    if v['id'] == temp_video_id:
                        v['message_id'] = forwarded.message_id
                        v['chat_id'] = admin_id
                        break
                storage.save_videos(videos)
                logger.info(f"Видео #{temp_video_id} обновлено в базе данных")
            except Exception as db_error:
                logger.error(f"Ошибка при обновлении базы данных для видео #{temp_video_id}: {db_error}")
                # Даже если не удалось обновить базу, видео уже у админа, поэтому продолжаем

            video_ids.append(temp_video_id)

            # Начисляем бонус пользователю
            try:
                progress = storage.load_user_progress(user_id)
                progress['limit'] += 1
                storage.save_user_progress(progress)
                logger.info(f"Бонус +1 начислен пользователю {user_id}, новый лимит: {progress['limit']}")
            except Exception as bonus_error:
                logger.error(f"Ошибка при начислении бонуса пользователю {user_id}: {bonus_error}")
                # Продолжаем, так как видео уже добавлено

            # Задержка для гарантии строгого порядка доставки сообщений в Telegram
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Ошибка при пересылке видео #{temp_video_id} от {user_id}: {e}")
            # Если не удалось переслать видео - удаляем его из базы
            try:
                storage.delete_video(temp_video_id)
                logger.info(f"Видео #{temp_video_id} удалено из базы после ошибки пересылки")
            except Exception as del_error:
                logger.error(f"Ошибка при удалении видео #{temp_video_id} из базы: {del_error}")
            continue

    if not video_ids:
        if rejected_short_count > 0 and duplicate_count == 0:
            await first_message.answer(
                f"❌ <b>Видео отклонено</b>\n\n"
                f"Минимальная длительность — <b>10 секунд</b>.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        elif duplicate_count > 0 and rejected_short_count == 0:
            await first_message.answer(
                f"❌ <b>Видео отклонено</b>\n\n"
                f"Такое видео уже есть в базе.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        elif rejected_short_count > 0 and duplicate_count > 0:
            await first_message.answer(
                f"❌ <b>Видео отклонены</b>\n\n"
                f"⚠️ Коротких видео (< 10 сек): <b>{rejected_short_count}</b>\n"
                f"🔁 Дубликатов: <b>{duplicate_count}</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        else:
            await first_message.answer(
                f"❌ <b>Ошибка при обработке видео</b>\n\n"
                f"Попробуйте позже или обратитесь к администратору.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        return

    reply_text = f"✅ <b>Видео принято</b>\n\n📦 Получено: <b>{len(video_ids)}</b> видео"
    if rejected_short_count:
        reply_text += f"\n⚠️ Отклонено коротких видео: <b>{rejected_short_count}</b>"
    if duplicate_count:
        reply_text += f"\n🔁 Отклонено дублей: <b>{duplicate_count}</b>"
    reply_text += f"\n📌 Осталось видео: <b>{get_remaining_videos(storage.load_user_progress(user_id))}</b>"

    await first_message.answer(
        reply_text,
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

    logger.info(f"Пользователь {user_id} отправил {len(video_ids)} видео в архив")


async def _flush_media_batch(media_group_id: str, admin_id: int):
    """Финализирует пакет видео после короткой паузы."""
    messages = _pending_media_batches.pop(media_group_id, [])
    _pending_media_tasks.pop(media_group_id, None)
    if messages:
        await _process_user_media_batch(messages, admin_id)


@user_router.message(F.video | F.video_note)
async def handle_user_video(message: Message, admin_id: int):
    """Обрабатывает видео пользователя, собирая альбомы в один пакет."""
    user_id = message.from_user.id

    if user_id == admin_id:
        logger.info("Видео администратора обрабатывается отдельным админским обработчиком")
        return

    media_group_id = getattr(message, "media_group_id", None)
    if media_group_id:
        batch = _pending_media_batches.setdefault(media_group_id, [])
        batch.append(message)
        if media_group_id not in _pending_media_tasks:
            task = asyncio.create_task(_flush_media_batch(media_group_id, admin_id))
            _pending_media_tasks[media_group_id] = task
            await asyncio.sleep(0.6)
        return

    await _process_user_media_batch([message], admin_id)
