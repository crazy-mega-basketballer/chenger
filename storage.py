"""
Модуль для работы с файловым хранилищем данных бота.
Все данные хранятся в текстовых файлах для минимального потребления ресурсов.
"""

import os
import logging
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

# Имена файлов
VIDEOS_FILE = "videos.txt"
PROGRESS_FILE = "progress.txt"
BANNED_FILE = "banned.txt"
DUPLICATES_FILE = "duplicates.txt"


def ensure_files_exist():
    """Создаёт необходимые файлы, если они отсутствуют"""
    for file in [VIDEOS_FILE, PROGRESS_FILE, BANNED_FILE, DUPLICATES_FILE]:
        if not os.path.exists(file):
            open(file, 'w').close()
            logger.info(f"Создан файл: {file}")


def get_admin_id() -> int:
    """Запрашивает ID администратора вручную при запуске бота."""
    print("\n" + "="*50)
    print("ВВОД ID АДМИНИСТРАТОРА")
    print("="*50)

    while True:
        admin_id_input = input("Введите ID администратора Telegram: ").strip()
        if not admin_id_input:
            print("ID администратора не может быть пустым.")
            continue
        try:
            admin_id = int(admin_id_input)
            logger.info(f"ID администратора получен вручную: {admin_id}")
            return admin_id
        except ValueError:
            print("Ошибка: введите целое число.")


# ==================== РАБОТА С ВИДЕО ====================

def load_duplicate_hashes() -> set[str]:
    """Возвращает набор хешей уже сохранённых видео для быстрой проверки дубликатов."""
    if not os.path.exists(DUPLICATES_FILE):
        return set()

    with open(DUPLICATES_FILE, 'r', encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip()}


def save_duplicate_hash(hash_value: str) -> None:
    """Сохраняет новый хеш видео в лёгкий файл."""
    with open(DUPLICATES_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{hash_value}\n")


def compute_file_hash(file_bytes: bytes) -> str:
    """Вычисляет быстрый хеш содержимого файла."""
    return hashlib.sha256(file_bytes).hexdigest()


def is_duplicate_video_hash(hash_value: str, known_hashes: Optional[set[str]] = None) -> bool:
    """Проверяет, был ли уже такой хеш сохранён."""
    if known_hashes is None:
        known_hashes = load_duplicate_hashes()
    return hash_value in known_hashes


def add_video(message_id: int, chat_id: int, original_user_id: int) -> int:
    """
    Добавляет видео в архив.
    Возвращает ID нового видео (порядковый номер).
    Формат: id|message_id|chat_id|original_user_id|timestamp
    """
    videos = load_videos()
    new_id = len(videos) + 1
    timestamp = int(datetime.now().timestamp())

    with open(VIDEOS_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{new_id}|{message_id}|{chat_id}|{original_user_id}|{timestamp}\n")

    logger.info(f"Добавлено видео #{new_id} от пользователя {original_user_id}")
    return new_id


def load_videos() -> List[Dict]:
    """
    Загружает список всех видео.
    Возвращает список словарей с ключами: id, message_id, chat_id, original_user_id, timestamp
    """
    videos = []
    if not os.path.exists(VIDEOS_FILE):
        return videos

    with open(VIDEOS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            videos.append({
                'id': int(parts[0]),
                'message_id': int(parts[1]),
                'chat_id': int(parts[2]),
                'original_user_id': int(parts[3]),
                'timestamp': int(parts[4])
            })

    return videos


def get_video_by_id(video_id: int) -> Optional[Dict]:
    """Получает видео по его ID"""
    videos = load_videos()
    for video in videos:
        if video['id'] == video_id:
            return video
    return None


def save_videos(videos: List[Dict]):
    """
    Сохраняет список видео в файл.
    Формат: id|message_id|chat_id|original_user_id|timestamp
    """
    with open(VIDEOS_FILE, 'w', encoding='utf-8') as f:
        for video in videos:
            f.write(f"{video['id']}|{video['message_id']}|{video['chat_id']}|"
                   f"{video['original_user_id']}|{video['timestamp']}\n")
    logger.info(f"Сохранено {len(videos)} видео в базу")


def delete_video(video_id: int) -> bool:
    """
    Удаляет видео по ID и перенумеровывает оставшиеся.
    Также корректирует прогресс всех пользователей.
    Возвращает True, если видео было удалено.
    """
    videos = load_videos()

    # Проверяем существование видео
    video_exists = any(v['id'] == video_id for v in videos)
    if not video_exists:
        return False

    # Удаляем и перенумеровываем
    new_videos = []
    for video in videos:
        if video['id'] == video_id:
            continue  # Пропускаем удаляемое видео

        # Перенумеровываем: если id больше удалённого - уменьшаем на 1
        if video['id'] > video_id:
            video['id'] -= 1

        new_videos.append(video)

    # Сохраняем обновлённый список
    with open(VIDEOS_FILE, 'w', encoding='utf-8') as f:
        for video in new_videos:
            f.write(f"{video['id']}|{video['message_id']}|{video['chat_id']}|"
                   f"{video['original_user_id']}|{video['timestamp']}\n")

    # Корректируем прогресс пользователей
    adjust_progress_after_deletion(video_id)

    logger.info(f"Удалено видео #{video_id}, оставшиеся перенумерованы")
    return True


def clear_all_videos():
    """Удаляет все видео из архива"""
    with open(VIDEOS_FILE, 'w') as f:
        f.write('')
    logger.info("Все видео удалены из архива")


def get_videos_count() -> int:
    """Возвращает общее количество видео"""
    return len(load_videos())


# ==================== РАБОТА С ПРОГРЕССОМ ПОЛЬЗОВАТЕЛЕЙ ====================

def load_user_progress(user_id: int, create_if_missing: bool = True) -> Dict:
    """
    Загружает прогресс пользователя.
    Формат: user_id|last_video_id|limit|referrer_id|referrals_count|daily_bonus_date
    Если пользователя нет и create_if_missing=True - создаёт запись с начальными значениями.
    """
    if not os.path.exists(PROGRESS_FILE):
        open(PROGRESS_FILE, 'w').close()

    with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            if int(parts[0]) == user_id:
                return {
                    'user_id': int(parts[0]),
                    'last_video_id': int(parts[1]),
                    'limit': int(parts[2]),
                    'referrer_id': int(parts[3]),
                    'referrals_count': int(parts[4]),
                    'daily_bonus_date': parts[5] if len(parts) > 5 else ''
                }

    # Если пользователя нет
    if not create_if_missing:
        return None

    # Создаём запись с начальными значениями
    default_progress = {
        'user_id': user_id,
        'last_video_id': 0,
        'limit': 5,
        'referrer_id': 0,
        'referrals_count': 0,
        'daily_bonus_date': ''
    }
    save_user_progress(default_progress)
    logger.info(f"Создан новый пользователь: {user_id}")
    return default_progress


def save_user_progress(progress: Dict):
    """Сохраняет прогресс пользователя"""
    lines = []
    user_found = False

    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('|')
                if int(parts[0]) == progress['user_id']:
                    # Обновляем существующую запись
                    lines.append(
                        f"{progress['user_id']}|{progress['last_video_id']}|"
                        f"{progress['limit']}|{progress['referrer_id']}|"
                        f"{progress['referrals_count']}|{progress['daily_bonus_date']}\n"
                    )
                    user_found = True
                else:
                    lines.append(line + '\n')

    # Если пользователь не найден - добавляем новую запись
    if not user_found:
        lines.append(
            f"{progress['user_id']}|{progress['last_video_id']}|"
            f"{progress['limit']}|{progress['referrer_id']}|"
            f"{progress['referrals_count']}|{progress['daily_bonus_date']}\n"
        )

    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def adjust_progress_after_deletion(deleted_video_id: int):
    """
    Корректирует прогресс всех пользователей после удаления видео.
    - Если last_video_id == deleted_video_id → уменьшить на 1 (но не ниже 0)
    - Если last_video_id > deleted_video_id → уменьшить на 1
    - Если last_video_id < deleted_video_id → без изменений
    """
    if not os.path.exists(PROGRESS_FILE):
        return

    lines = []
    with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split('|')
            user_id = int(parts[0])
            last_video_id = int(parts[1])
            limit = int(parts[2])
            referrer_id = int(parts[3])
            referrals_count = int(parts[4])
            daily_bonus_date = parts[5] if len(parts) > 5 else ''

            # Корректируем last_video_id
            if last_video_id >= deleted_video_id:
                last_video_id = max(0, last_video_id - 1)

            lines.append(
                f"{user_id}|{last_video_id}|{limit}|{referrer_id}|"
                f"{referrals_count}|{daily_bonus_date}\n"
            )

    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    logger.info(f"Прогресс пользователей скорректирован после удаления видео #{deleted_video_id}")


def reset_user_progress(user_id: int):
    """Сбрасывает прогресс пользователя (last_video_id = 0)"""
    progress = load_user_progress(user_id)
    progress['last_video_id'] = 0
    save_user_progress(progress)
    logger.info(f"Сброшен прогресс пользователя {user_id}")


def reset_all_progress():
    """Сбрасывает прогресс всех пользователей"""
    if not os.path.exists(PROGRESS_FILE):
        return

    lines = []
    with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split('|')
            user_id = parts[0]
            limit = parts[2]
            referrer_id = parts[3]
            referrals_count = parts[4]
            daily_bonus_date = parts[5] if len(parts) > 5 else ''

            # Сбрасываем только last_video_id
            lines.append(f"{user_id}|0|{limit}|{referrer_id}|{referrals_count}|{daily_bonus_date}\n")

    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    logger.info("Сброшен прогресс всех пользователей")


def get_all_users() -> List[Dict]:
    """Возвращает список всех пользователей"""
    users = []
    if not os.path.exists(PROGRESS_FILE):
        return users

    with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            users.append({
                'user_id': int(parts[0]),
                'last_video_id': int(parts[1]),
                'limit': int(parts[2]),
                'referrer_id': int(parts[3]),
                'referrals_count': int(parts[4]),
                'daily_bonus_date': parts[5] if len(parts) > 5 else ''
            })

    return users


def update_user_limit(user_id: int, new_limit: int):
    """Устанавливает новый лимит пользователя"""
    progress = load_user_progress(user_id)
    progress['limit'] = max(0, new_limit)  # Не может быть меньше 0
    save_user_progress(progress)
    logger.info(f"Лимит пользователя {user_id} изменён на {new_limit}")


def add_referral(referrer_id: int, new_user_id: int) -> bool:
    """
    Добавляет реферала: увеличивает лимит реферера на 15 и счётчик рефералов на 1.
    Устанавливает referrer_id новому пользователю.
    Возвращает True, если бонус был начислен, и False, если пользователь уже имел реферера.
    """
    new_user_progress = load_user_progress(new_user_id)
    if new_user_progress['referrer_id'] != 0:
        logger.info(f"Реферал не добавлен: {new_user_id} уже имеет реферера {new_user_progress['referrer_id']}")
        return False

    # Обновляем реферера
    referrer_progress = load_user_progress(referrer_id)
    referrer_progress['limit'] += 15
    referrer_progress['referrals_count'] += 1
    save_user_progress(referrer_progress)

    # Обновляем нового пользователя
    new_user_progress['referrer_id'] = referrer_id
    save_user_progress(new_user_progress)

    logger.info(f"Реферал добавлен: пользователь {new_user_id} привязан к рефереру {referrer_id}")
    return True


# ==================== РАБОТА С БАНАМИ ====================

def add_ban(user_id: int, unban_timestamp: int):
    """
    Добавляет пользователя в список забаненных.
    Формат: user_id|unban_timestamp
    """
    # Сначала удаляем старый бан, если есть
    remove_ban(user_id)

    with open(BANNED_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{user_id}|{unban_timestamp}\n")

    logger.info(f"Пользователь {user_id} забанен до {datetime.fromtimestamp(unban_timestamp)}")


def remove_ban(user_id: int):
    """Удаляет пользователя из списка забаненных"""
    if not os.path.exists(BANNED_FILE):
        return

    lines = []
    with open(BANNED_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            if int(parts[0]) != user_id:
                lines.append(line + '\n')

    with open(BANNED_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    logger.info(f"Бан пользователя {user_id} снят")


def check_ban(user_id: int) -> Optional[int]:
    """
    Проверяет, забанен ли пользователь.
    Возвращает timestamp разбана, если забанен, иначе None.
    Автоматически удаляет истёкшие баны.
    """
    if not os.path.exists(BANNED_FILE):
        return None

    current_time = int(datetime.now().timestamp())
    lines = []
    ban_timestamp = None

    with open(BANNED_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            banned_user_id = int(parts[0])
            unban_time = int(parts[1])

            if banned_user_id == user_id:
                if unban_time > current_time:
                    ban_timestamp = unban_time
                    lines.append(line + '\n')
                else:
                    logger.info(f"Истёк бан пользователя {user_id}")
            else:
                # Очищаем истёкшие баны других пользователей
                if unban_time > current_time:
                    lines.append(line + '\n')

    # Сохраняем очищенный список
    with open(BANNED_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    return ban_timestamp


def get_banned_count() -> int:
    """Возвращает количество активных банов"""
    if not os.path.exists(BANNED_FILE):
        return 0

    current_time = int(datetime.now().timestamp())
    count = 0

    with open(BANNED_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            unban_time = int(parts[1])
            if unban_time > current_time:
                count += 1

    return count
