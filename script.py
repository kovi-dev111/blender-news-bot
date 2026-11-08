import feedparser
import requests
import json
import os
import time
import re
from urllib.parse import urlparse
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator, MyMemoryTranslator

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

KEYWORDS = [
    'blender', 'cycles', 'eevee', 'geometry nodes', 'bpy',
    'blender foundation', '3d modeling', '3d render', 'vfx',
    'procedural', 'shader', 'addon', 'plug-in'
]

FEEDS = [
    "https://80.lv/rss/",
    "https://www.blendernation.com/feed/",
    "https://blenderartists.org/latest.rss",
    "https://devtalk.blender.org/c/news/weekly-updates/10.rss",
    "https://www.blender.org/rss.xml"
]

STATE_FILE = "posted.json"


def is_working_hours():
    now_utc = datetime.utcnow()
    return 3 <= now_utc.hour < 19


def get_time_info():
    now_utc = datetime.utcnow()
    now_utc5 = now_utc + timedelta(hours=5)
    return now_utc, now_utc5


def load_posted():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_posted(posted):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(posted, f, ensure_ascii=False, indent=2)


def clean_html(text):
    clean = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', clean).strip()


def translate_text(text):
    clean = clean_html(text)
    if not clean or len(clean) < 10:
        return clean
    try:
        return GoogleTranslator(source='auto', target='ru').translate(clean)
    except Exception:
        try:
            return MyMemoryTranslator(source='auto', target='ru').translate(clean)
        except Exception:
            return clean


def extract_image(entry):
    if hasattr(entry, 'media_content'):
        for m in entry.media_content:
            if m.get('medium') == 'image':
                return m.get('url')
    if hasattr(entry, 'image'):
        return entry.image.get('href') if isinstance(entry.image, dict) else str(entry.image)
    content = ""
    if hasattr(entry, 'summary'):
        content += entry.summary
    if hasattr(entry, 'description'):
        content += entry.description
    if hasattr(entry, 'content') and entry.content:
        content += entry.content[0].value
    match = re.search(r'<img[^>]+src="([^"]+)"', content)
    return match.group(1) if match else None


def is_blender_news(title, description):
    text = (title + " " + description).lower()
    return any(kw in text for kw in KEYWORDS)


def send_to_telegram(image_url, text):
    if image_url:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        try:
            resp = requests.get(image_url, timeout=10)
            if resp.status_code == 200:
                files = {'photo': ('img.jpg', resp.content, 'image/jpeg')}
                data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': text, 'parse_mode': 'HTML'}
                if requests.post(url, files=files, data=data, timeout=15).status_code == 200:
                    return True
        except Exception:
            pass
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": 'HTML'}
    return requests.post(url, json=payload, timeout=10).status_code == 200


def main():
    if not os.path.exists(STATE_FILE):
        save_posted([])

    now_utc, now_utc5 = get_time_info()
    print("=" * 50)
    print(f"🕐 Время: UTC {now_utc.strftime('%H:%M')} / UTC+5 {now_utc5.strftime('%H:%M')}")

    if not is_working_hours():
        print("⏰ НЕ рабочее время. Сплю.")
        return

    print("✅ Рабочее время. Ищем новости...")
    posted = load_posted()
    new_posted = posted.copy()
    updated = False

    for feed_url in FEEDS:
        print(f"\n📡 Проверяю ленту: {feed_url}")
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]:
            link = entry.get('link', '')
            if not link or link in posted:
                continue

            published_time = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    published_time = datetime(*entry.published_parsed[:6])
                except Exception:
                    pass
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    published_time = datetime(*entry.updated_parsed[:6])
                except Exception:
                    pass

            if published_time:
                age = datetime.utcnow() - published_time
                if age.total_seconds() > 86400:
                    print(f"⏭️ Пропуск (старше 1 дня): {entry.get('title', '')[:40]}")
                    continue
            else:
                print(f"⚠️ Дата не найдена, считаем свежей: {entry.get('title', '')[:40]}")

            title = entry.get('title', 'Без заголовка')
            description = ""
            if hasattr(entry, 'summary'):
                description += entry.summary
            if hasattr(entry, 'description'):
                description += entry.description

            if not is_blender_news(title, description):
                print(f"⏭️ Пропуск (нет ключевых слов): {title[:50]}")
                continue

            print(f"✅ Найдено свежее: {title[:50]}")

            ru_title = translate_text(title)
            short_desc = description.split('<p>')[0].split('<br>')[0]
            ru_desc = translate_text(short_desc)

            post_text = f"<b>{ru_title}</b>\n\n{ru_desc}\n\n🔗 Источник: {link}"
            image_url = extract_image(entry)

            print("📤 Отправка в Telegram...")
            if send_to_telegram(image_url, post_text):
                new_posted.append(link)
                updated = True
                save_posted(new_posted)
                print("✅ Успешно отправлено на модерацию!")
            else:
                print("❌ Ошибка отправки")

            time.sleep(1.5)

    print("\n" + "=" * 50)
    print("✅ Готово!" if updated else "ℹ️ Новых свежих новостей про Blender нет.")


if __name__ == "__main__":
    main()
