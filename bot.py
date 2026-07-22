"""
Telegram Video Bot - главный файл запуска.

Бот работает как посредник между администратором и пользователями.
Все видео хранятся в админ-чате и пересылаются пользователям без скачивания на сервер.
"""

import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import storage
import admin_handlers
from handlers import user_router
from admin_handlers import admin_router

# Отключаем все логи
logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

# Глобальные переменные
bot: Bot = None
bot_username: str = None
admin_id: int = None


def get_bot() -> Bot:
    """Возвращает инициализированный экземпляр бота."""
    return bot


def prompt_for_credentials() -> tuple[str, int]:
    """Запрашивает у пользователя токен бота и ID администратора вручную."""
    print("\n" + "=" * 50)
    print("НАСТРОЙКА БОТА")
    print("=" * 50)

    while True:
        token = input("Введите токен бота Telegram: ").strip()
        if token:
            break
        print("Токен не может быть пустым.")

    while True:
        admin_id_input = input("Введите ID администратора Telegram: ").strip()
        if not admin_id_input:
            print("ID администратора не может быть пустым.")
            continue
        try:
            admin_id = int(admin_id_input)
            break
        except ValueError:
            print("Ошибка: введите целое число.")

    return token, admin_id


async def main():
    """Главная функция запуска бота"""
    global bot, bot_username, admin_id

    token, admin_id_from_input = prompt_for_credentials()
    if not token:
        print("\nОШИБКА: Токен не может быть пустым.")
        sys.exit(1)

    # Инициализация бота
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Получаем username бота для реферальных ссылок
    me = await bot.get_me()
    bot_username = me.username

    # Инициализация хранилища
    storage.ensure_files_exist()
    admin_id = admin_id_from_input
    admin_handlers.set_admin_id(admin_id)

    # Создаём диспетчер
    dp = Dispatcher()

    # Middleware для передачи bot_username и admin_id в хендлеры
    # ВАЖНО: middleware должен быть ДО регистрации роутеров
    @dp.message.middleware()
    @dp.callback_query.middleware()
    async def inject_dependencies(handler, event, data):
        data['bot_username'] = bot_username
        data['admin_id'] = admin_id
        try:
            return await handler(event, data)
        except Exception as exc:
            message = str(exc).lower()
            if "query is too old" in message or "query id is invalid" in message:
                return None
            raise

    # Регистрируем роутеры
    # Важно: admin_router должен быть ПЕРЕД user_router,
    # чтобы видео от администратора обрабатывались первыми
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Запуск polling
    print("\n" + "="*50)
    print(f"Bot @{bot_username} started successfully!")
    print(f"Admin ID: {admin_id}")
    print("="*50 + "\n")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Критическая ошибка: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n✓ Бот остановлен")
