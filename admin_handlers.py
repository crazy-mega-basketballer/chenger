"""
Обработчики административных команд.
Доступны только для администратора в личном чате с ботом.
"""

import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import storage


def is_admin_message(message, admin_id: int) -> bool:
    """Проверяет, что сообщение пришло от администратора."""
    return bool(message.from_user and message.from_user.id == admin_id)

logger = logging.getLogger(__name__)

# Роутер для административных команд
admin_router = Router()
ADMIN_ID: int | None = None


def set_admin_id(admin_id: int) -> None:
    """Сохраняет ID администратора для фильтрации видео."""
    global ADMIN_ID
    ADMIN_ID = admin_id


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


class IsAdminVideoFilter(BaseFilter):
    """Проверяет, что видео пришло от администратора."""

    async def __call__(self, event, **kwargs) -> bool:
        message = event
        admin_id = kwargs.get('admin_id') or ADMIN_ID
        if not message or admin_id is None:
            return False
        return is_admin_message(message, admin_id)


def is_admin(user_id: int, admin_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id == admin_id


def build_moderation_callback_data(prefix: str, user_id: int, video_id: int) -> str:
    """Создаёт callback-data для отдельной модерации видео."""
    return f"{prefix}_{user_id}_{video_id}"


# ==================== МОДЕРАЦИЯ ВИДЕО ====================

@admin_router.callback_query(F.data.startswith("approve_batch_"))
async def approve_batch_video(callback: CallbackQuery, admin_id: int):
    """Подтверждает пакет пользовательских видео."""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    parts = callback.data.split("_")
    user_id = int(parts[2])
    video_ids = [int(item) for item in parts[3].split(",") if item]

    if not video_ids:
        await callback.answer("❌ Нет видео для подтверждения", show_alert=True)
        return

    progress = storage.load_user_progress(user_id)
    progress['limit'] += len(video_ids)
    storage.save_user_progress(progress)

    await callback.message.edit_text(
        f"✅ <b>Пакет видео подтверждён</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"📦 Количество: <b>{len(video_ids)}</b> видео\n"
        f"🎯 Новый лимит пользователя: <b>{progress['limit']}</b>",
        parse_mode="HTML"
    )

    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")
        await current_bot.send_message(
            user_id,
            f"🎉 <b>Ваши видео подтверждены!</b>\n\n"
            f"📦 Подтверждено: <b>{len(video_ids)}</b> видео\n"
            f"Ваш лимит увеличен на <b>{len(video_ids)}</b>\n\n"
            f"Новый лимит: <b>{progress['limit']}</b> видео",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await callback.answer("✅ Пакет подтверждён")


@admin_router.callback_query(F.data.startswith("reject_batch_"))
async def reject_batch_video(callback: CallbackQuery, admin_id: int):
    """Отклоняет пакет пользовательских видео и удаляет их из архива."""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    parts = callback.data.split("_")
    user_id = int(parts[2])
    video_ids = [int(item) for item in parts[3].split(",") if item]

    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")

        for video_id in video_ids:
            video = storage.get_video_by_id(video_id)
            if video is None:
                continue
            try:
                await current_bot.delete_message(chat_id=video['chat_id'], message_id=video['message_id'])
            except Exception:
                pass
            storage.delete_video(video_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить пакет видео: {e}")

    await callback.message.edit_text(
        f"❌ <b>Видео не прошло модерацию</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"Будьте аккуратнее.",
        parse_mode="HTML"
    )

    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")
        await current_bot.send_message(
            user_id,
            f"❌ <b>Видео не прошло модерацию</b>\n\n"
            f"Будьте аккуратнее.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await callback.answer("❌ Пакет отклонён")


@admin_router.callback_query(F.data.startswith("approve_"))
async def approve_video(callback: CallbackQuery, admin_id: int):
    """Одобряет видео от пользователя"""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    parts = callback.data.split("_")
    user_id = int(parts[1])
    video_id = int(parts[2])

    video = storage.get_video_by_id(video_id)
    if video is None:
        await callback.answer("❌ Видео уже не найдено", show_alert=True)
        return

    await callback.message.edit_text(
        f"✅ <b>Видео одобрено</b>\n\n"
        f"📹 Видео #{video_id} добавлено в архив\n"
        f"👤 User ID: <code>{user_id}</code>",
        parse_mode="HTML"
    )

    await callback.answer("✅ Видео одобрено")
    logger.info(f"Администратор одобрил видео #{video_id} от пользователя {user_id}")


@admin_router.callback_query(F.data.startswith("reject_"))
async def reject_video(callback: CallbackQuery, admin_id: int):
    """Отклоняет видео от пользователя и удаляет его из базы/чата администратора."""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    parts = callback.data.split("_")
    user_id = int(parts[1])

    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")

        video_id = int(parts[2])
        video = storage.get_video_by_id(video_id)
        if video is None:
            raise ValueError("video_not_found")

        await current_bot.delete_message(chat_id=video['chat_id'], message_id=video['message_id'])
        storage.delete_video(video_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить отклонённое видео #{parts[2] if len(parts) > 2 else 'unknown'}: {e}")

    await callback.message.edit_text(
        f"❌ <b>Видео отклонено</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>",
        parse_mode="HTML"
    )

    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")
        await current_bot.send_message(
            user_id,
            f"❌ <b>Ваше видео отклонено</b>\n\n"
            f"Видео не прошло модерацию.\n\n"
            f"Пожалуйста, отправляйте только качественные и уместные видео.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await callback.answer("❌ Видео отклонено")
    logger.info(f"Администратор отклонил видео от пользователя {user_id}")


# ==================== ЗАГРУЗКА ВИДЕО АДМИНИСТРАТОРОМ ====================

@admin_router.message(F.video | F.video_note, IsAdminVideoFilter())
async def admin_video_handler(message: Message, admin_id: int):
    """Обработка видео от администратора. Видео сразу добавляется в архив без модерации."""
    effective_admin_id = admin_id or ADMIN_ID
    if effective_admin_id is None or message.from_user.id != effective_admin_id:
        return

    # Получаем file_id (уникальный идентификатор файла в Telegram)
    file_id = None
    media = getattr(message, 'video', None)
    if media is not None:
        file_id = getattr(media, 'file_id', None)

    if file_id is None:
        media = getattr(message, 'video_note', None)
        if media is not None:
            file_id = getattr(media, 'file_id', None)

    # Если file_id не найден - отклоняем видео
    if not file_id:
        await message.answer(
            "❌ <b>Ошибка</b>\n\n"
            "Не удалось получить идентификатор файла.",
            parse_mode="HTML"
        )
        logger.warning(f"Не удалось получить file_id для видео от администратора")
        return

    # Проверяем на дубликат ДО добавления (используем file_id)
    duplicate_hash = storage.compute_file_hash(file_id.encode('utf-8'))
    known_hashes = storage.load_duplicate_hashes()

    if storage.is_duplicate_video_hash(duplicate_hash, known_hashes):
        await message.answer(
            "❌ <b>Видео отклонено</b>\n\n"
            "Такое видео уже есть в базе.",
            parse_mode="HTML"
        )
        logger.info(f"Администратор попытался добавить дубликат видео, хеш: {duplicate_hash[:16]}...")
        return

    # Сохраняем хеш ПЕРЕД добавлением видео
    storage.save_duplicate_hash(duplicate_hash)

    # Добавляем видео в базу
    video_id = storage.add_video(
        message_id=message.message_id,
        chat_id=message.chat.id,
        original_user_id=admin_id
    )

    logger.info(f"Администратор добавил видео #{video_id}, хеш: {duplicate_hash[:16]}...")


# ==================== СТАТИСТИКА ====================

@admin_router.message(Command("stats"))
async def cmd_stats(message: Message, admin_id: int):
    """Показывает общую статистику бота"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Собираем статистику
    videos_count = storage.get_videos_count()
    users = storage.get_all_users()
    users_count = len(users)
    banned_count = storage.get_banned_count()

    # Подсчитываем общее количество рефералов
    total_referrals = sum(u['referrals_count'] for u in users)

    stats_text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"🎬 <b>Всего видео:</b> {videos_count}\n"
        f"👥 <b>Всего пользователей:</b> {users_count}\n"
        f"🚫 <b>Забаненных:</b> {banned_count}\n"
        f"🔗 <b>Всего рефералов:</b> {total_referrals}"
    )

    await message.answer(stats_text, parse_mode="HTML")
    logger.info("Администратор запросил статистику")


# ==================== СПИСОК ВИДЕО ====================

@admin_router.message(Command("list"))
async def cmd_list(message: Message, admin_id: int):
    """Показывает список всех видео (с пагинацией)"""
    if not is_admin(message.from_user.id, admin_id):
        return

    videos = storage.load_videos()

    if not videos:
        await message.answer("📭 <b>Архив пуст</b>", parse_mode="HTML")
        return

    # Показываем первые 20 видео
    page_size = 20
    videos_to_show = videos[:page_size]

    list_text = f"📋 <b>Список видео (всего {len(videos)})</b>\n\n"

    for video in videos_to_show:
        date = datetime.fromtimestamp(video['timestamp']).strftime("%d.%m.%Y %H:%M")
        list_text += f"#{video['id']} — от User ID {video['original_user_id']} ({date})\n"

    if len(videos) > page_size:
        list_text += f"\n<i>... и ещё {len(videos) - page_size} видео</i>"

    await message.answer(list_text, parse_mode="HTML")
    logger.info("Администратор запросил список видео")


# ==================== БАН/РАЗБАН ====================

@admin_router.message(Command("ban"))
async def cmd_ban(message: Message, admin_id: int):
    """Начинает процесс бана пользователя"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Парсим user_id из команды
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ <b>Использование:</b> /ban <code>user_id</code>\n\n"
            "Пример: /ban 123456789",
            parse_mode="HTML"
        )
        return

    try:
        user_id_to_ban = int(args[1])
    except ValueError:
        await message.answer("❌ <b>Ошибка:</b> некорректный ID пользователя", parse_mode="HTML")
        return

    # Проверяем, что это не сам администратор
    if user_id_to_ban == admin_id:
        await message.answer("❌ <b>Вы не можете забанить себя</b>", parse_mode="HTML")
        return

    # Показываем кнопки выбора длительности бана
    builder = InlineKeyboardBuilder()
    builder.button(text="1 час", callback_data=f"ban_{user_id_to_ban}_1h")
    builder.button(text="5 часов", callback_data=f"ban_{user_id_to_ban}_5h")
    builder.button(text="10 часов", callback_data=f"ban_{user_id_to_ban}_10h")
    builder.button(text="24 часа", callback_data=f"ban_{user_id_to_ban}_24h")
    builder.button(text="3 дня", callback_data=f"ban_{user_id_to_ban}_3d")
    builder.button(text="7 дней", callback_data=f"ban_{user_id_to_ban}_7d")
    builder.adjust(2)

    await message.answer(
        f"⏰ <b>Выберите длительность бана для пользователя {user_id_to_ban}:</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


@admin_router.callback_query(F.data.startswith("ban_"))
async def process_ban(callback: CallbackQuery, admin_id: int):
    """Обрабатывает выбор длительности бана"""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    # Парсим данные: ban_user_id_duration
    parts = callback.data.split("_")
    user_id_to_ban = int(parts[1])
    duration = parts[2]

    # Определяем длительность
    duration_map = {
        "1h": timedelta(hours=1),
        "5h": timedelta(hours=5),
        "10h": timedelta(hours=10),
        "24h": timedelta(hours=24),
        "3d": timedelta(days=3),
        "7d": timedelta(days=7)
    }

    duration_text_map = {
        "1h": "1 час",
        "5h": "5 часов",
        "10h": "10 часов",
        "24h": "24 часа",
        "3d": "3 дня",
        "7d": "7 дней"
    }

    delta = duration_map.get(duration)
    if not delta:
        await callback.answer("❌ Неверная длительность", show_alert=True)
        return

    # Вычисляем timestamp разбана
    unban_timestamp = int((datetime.now() + delta).timestamp())

    # Баним пользователя
    storage.add_ban(user_id_to_ban, unban_timestamp)

    unban_date = datetime.fromtimestamp(unban_timestamp).strftime("%d.%m.%Y %H:%M")

    await callback.message.edit_text(
        f"✅ <b>Пользователь забанен</b>\n\n"
        f"👤 User ID: <code>{user_id_to_ban}</code>\n"
        f"⏰ Длительность: <b>{duration_text_map[duration]}</b>\n"
        f"🔓 Разбан: <b>{unban_date}</b>",
        parse_mode="HTML"
    )

    # Уведомляем пользователя
    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")
        await current_bot.send_message(
            user_id_to_ban,
            f"🚫 <b>Вы заблокированы</b>\n\n"
            f"⏰ Длительность: <b>{duration_text_map[duration]}</b>\n"
            f"🔓 Разбан: <b>{unban_date}</b>\n\n"
            f"Обратитесь к администратору для уточнения причины.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id_to_ban} о бане: {e}")

    await callback.answer("✅ Пользователь забанен")
    logger.info(f"Администратор забанил пользователя {user_id_to_ban} на {duration_text_map[duration]}")


@admin_router.message(Command("unban"))
async def cmd_unban(message: Message, admin_id: int):
    """Разбанивает пользователя"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Парсим user_id из команды
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ <b>Использование:</b> /unban <code>user_id</code>\n\n"
            "Пример: /unban 123456789",
            parse_mode="HTML"
        )
        return

    try:
        user_id_to_unban = int(args[1])
    except ValueError:
        await message.answer("❌ <b>Ошибка:</b> некорректный ID пользователя", parse_mode="HTML")
        return

    # Проверяем, забанен ли пользователь
    ban_timestamp = storage.check_ban(user_id_to_unban)
    if not ban_timestamp:
        await message.answer(
            f"ℹ️ <b>Пользователь {user_id_to_unban} не забанен</b>",
            parse_mode="HTML"
        )
        return

    # Снимаем бан
    storage.remove_ban(user_id_to_unban)

    await message.answer(
        f"✅ <b>Бан снят</b>\n\n"
        f"👤 User ID: <code>{user_id_to_unban}</code>",
        parse_mode="HTML"
    )

    # Уведомляем пользователя
    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")
        await current_bot.send_message(
            user_id_to_unban,
            f"🎉 <b>Ваша блокировка снята!</b>\n\n"
            f"Теперь вы снова можете пользоваться ботом.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id_to_unban} о разбане: {e}")

    logger.info(f"Администратор разбанил пользователя {user_id_to_unban}")


# ==================== УДАЛЕНИЕ ВИДЕО ====================

@admin_router.message(Command("delvideo"))
async def cmd_delvideo(message: Message, admin_id: int):
    """Удаляет видео по ID"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Парсим video_id из команды
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ <b>Использование:</b> /delvideo <code>video_id</code>\n\n"
            "Пример: /delvideo 5",
            parse_mode="HTML"
        )
        return

    try:
        video_id = int(args[1])
    except ValueError:
        await message.answer("❌ <b>Ошибка:</b> некорректный ID видео", parse_mode="HTML")
        return

    # Удаляем видео
    success = storage.delete_video(video_id)

    if success:
        await message.answer(
            f"✅ <b>Видео #{video_id} удалено</b>\n\n"
            f"Оставшиеся видео перенумерованы.\n"
            f"Прогресс пользователей скорректирован.",
            parse_mode="HTML"
        )
        logger.info(f"Администратор удалил видео #{video_id}")
    else:
        await message.answer(
            f"❌ <b>Видео #{video_id} не найдено</b>",
            parse_mode="HTML"
        )


@admin_router.message(F.reply_to_message)
async def delete_video_by_reply(message: Message, admin_id: int):
    """Удаляет видео при ответе администратора на сообщение с видео"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Проверяем, что это ответ на сообщение с видео
    replied_message = message.reply_to_message
    if not replied_message:
        return

    # Ищем видео по message_id и chat_id
    videos = storage.load_videos()
    video_to_delete = None

    for video in videos:
        if video['message_id'] == replied_message.message_id and video['chat_id'] == replied_message.chat.id:
            video_to_delete = video
            break

    if not video_to_delete:
        await message.answer(
            "❌ <b>Видео не найдено в базе</b>\n\n"
            "Возможно, оно уже было удалено.",
            parse_mode="HTML"
        )
        return

    # Удаляем видео из базы
    video_id = video_to_delete['id']
    original_user_id = video_to_delete['original_user_id']
    success = storage.delete_video(video_id)

    if success:
        # Удаляем само сообщение с видео
        try:
            current_bot = get_runtime_bot()
            if current_bot is None:
                raise RuntimeError("Bot instance is not initialized")
            await current_bot.delete_message(
                chat_id=replied_message.chat.id,
                message_id=replied_message.message_id
            )
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение с видео: {e}")

        # Уведомляем пользователя об отклонении видео
        try:
            current_bot = get_runtime_bot()
            if current_bot is None:
                raise RuntimeError("Bot instance is not initialized")
            await current_bot.send_message(
                original_user_id,
                f"❌ <b>Ваше видео отклонено</b>\n\n"
                f"Видео #{video_id} не прошло модерацию и было удалено из архива.\n\n"
                f"Пожалуйста, отправляйте только качественные и уместные видео.",
                parse_mode="HTML"
            )
            logger.info(f"Пользователь {original_user_id} уведомлен об удалении видео #{video_id}")
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {original_user_id}: {e}")

        await message.answer(
            f"✅ <b>Видео #{video_id} удалено</b>\n\n"
            f"Оставшиеся видео перенумерованы.\n"
            f"Прогресс пользователей скорректирован.",
            parse_mode="HTML"
        )
        logger.info(f"Администратор удалил видео #{video_id} через ответ на сообщение")
    else:
        await message.answer(
            f"❌ <b>Ошибка при удалении видео</b>",
            parse_mode="HTML"
        )


# ==================== СБРОС ПРОГРЕССА ====================

@admin_router.message(Command("reset"))
async def cmd_reset(message: Message, admin_id: int):
    """Сбрасывает прогресс пользователя"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Парсим user_id из команды
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ <b>Использование:</b> /reset <code>user_id</code>\n\n"
            "Пример: /reset 123456789",
            parse_mode="HTML"
        )
        return

    try:
        user_id_to_reset = int(args[1])
    except ValueError:
        await message.answer("❌ <b>Ошибка:</b> некорректный ID пользователя", parse_mode="HTML")
        return

    # Сбрасываем прогресс
    storage.reset_user_progress(user_id_to_reset)

    await message.answer(
        f"✅ <b>Прогресс сброшен</b>\n\n"
        f"👤 User ID: <code>{user_id_to_reset}</code>\n"
        f"🔄 Просмотренных видео: <b>0</b>\n\n"
        f"<i>Лимит и рефералы не изменены</i>",
        parse_mode="HTML"
    )

    logger.info(f"Администратор сбросил прогресс пользователя {user_id_to_reset}")


@admin_router.message(Command("reset_all"))
async def cmd_reset_all(message: Message, admin_id: int):
    """Сбрасывает прогресс всех пользователей (с подтверждением)"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Запрашиваем подтверждение
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, сбросить всё", callback_data="confirm_reset_all")
    builder.button(text="❌ Отмена", callback_data="cancel_reset_all")
    builder.adjust(1)

    await message.answer(
        "⚠️ <b>ВНИМАНИЕ!</b>\n\n"
        "Вы уверены, что хотите <b>сбросить прогресс всех пользователей</b>?\n\n"
        "Это действие установит last_video_id = 0 для всех.\n"
        "Лимиты и рефералы не изменятся.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


@admin_router.callback_query(F.data == "confirm_reset_all")
async def confirm_reset_all(callback: CallbackQuery, admin_id: int):
    """Подтверждение сброса прогресса всех пользователей"""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    storage.reset_all_progress()

    await callback.message.edit_text(
        "✅ <b>Прогресс всех пользователей сброшен</b>\n\n"
        "Все пользователи начнут просмотр с первого видео.",
        parse_mode="HTML"
    )

    await callback.answer("✅ Прогресс сброшен")
    logger.info("Администратор сбросил прогресс всех пользователей")


@admin_router.callback_query(F.data == "cancel_reset_all")
async def cancel_reset_all(callback: CallbackQuery, admin_id: int):
    """Отмена сброса прогресса"""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    await callback.message.edit_text("❌ <b>Сброс прогресса отменён</b>", parse_mode="HTML")
    await callback.answer("Отменено")


# ==================== ОЧИСТКА АРХИВА ====================

@admin_router.message(Command("clear"))
async def cmd_clear(message: Message, admin_id: int):
    """Удаляет все видео и обнуляет прогресс (с подтверждением)"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Запрашиваем подтверждение
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить всё", callback_data="confirm_clear")
    builder.button(text="❌ Отмена", callback_data="cancel_clear")
    builder.adjust(1)

    videos_count = storage.get_videos_count()

    await message.answer(
        "⚠️ <b>ВНИМАНИЕ!</b>\n\n"
        f"Вы уверены, что хотите <b>удалить все {videos_count} видео</b> "
        "и <b>обнулить прогресс всех пользователей</b>?\n\n"
        "<b>Это действие необратимо!</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


@admin_router.callback_query(F.data == "confirm_clear")
async def confirm_clear(callback: CallbackQuery, admin_id: int):
    """Подтверждение очистки архива"""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    storage.clear_all_videos()
    storage.reset_all_progress()

    await callback.message.edit_text(
        "✅ <b>Архив полностью очищен</b>\n\n"
        "Все видео удалены.\n"
        "Прогресс всех пользователей обнулён.",
        parse_mode="HTML"
    )

    await callback.answer("✅ Архив очищен")
    logger.info("Администратор очистил весь архив")


@admin_router.callback_query(F.data == "cancel_clear")
async def cancel_clear(callback: CallbackQuery, admin_id: int):
    """Отмена очистки архива"""
    if not is_admin(callback.from_user.id, admin_id):
        await callback.answer("❌ Доступно только администратору", show_alert=True)
        return

    await callback.message.edit_text("❌ <b>Очистка архива отменена</b>", parse_mode="HTML")
    await callback.answer("Отменено")


# ==================== РУЧНОЕ ИЗМЕНЕНИЕ ЛИМИТА ====================

@admin_router.message(Command("setlimit"))
async def cmd_setlimit(message: Message, admin_id: int):
    """Устанавливает лимит пользователя вручную"""
    if not is_admin(message.from_user.id, admin_id):
        return

    # Парсим аргументы
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "❌ <b>Использование:</b> /setlimit <code>user_id</code> <code>new_limit</code>\n\n"
            "Пример: /setlimit 123456789 50",
            parse_mode="HTML"
        )
        return

    try:
        user_id = int(args[1])
        new_limit = int(args[2])
    except ValueError:
        await message.answer("❌ <b>Ошибка:</b> некорректные параметры", parse_mode="HTML")
        return

    if new_limit < 0:
        await message.answer("❌ <b>Ошибка:</b> лимит не может быть отрицательным", parse_mode="HTML")
        return

    # Устанавливаем новый лимит
    storage.update_user_limit(user_id, new_limit)

    await message.answer(
        f"✅ <b>Лимит изменён</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"🎯 Новый лимит: <b>{new_limit}</b> видео",
        parse_mode="HTML"
    )

    # Уведомляем пользователя
    try:
        current_bot = get_runtime_bot()
        if current_bot is None:
            raise RuntimeError("Bot instance is not initialized")
        await current_bot.send_message(
            user_id,
            f"🎯 <b>Ваш лимит изменён администратором</b>\n\n"
            f"Новый лимит: <b>{new_limit}</b> видео",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id} об изменении лимита: {e}")

    logger.info(f"Администратор изменил лимит пользователя {user_id} на {new_limit}")
