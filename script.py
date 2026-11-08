import feedparser
import requests
import json
import os
import time
import re
from urllib.parse import urlparse
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
UNSPLASH_ACCESS_KEY = os.environ.get('UNSPLASH_ACCESS_KEY', '')

# Ключевые слова для фильтрации (в нижнем регистре)
KEYWORDS = ['blender', 'cycles', 'eevee', 'geometry nodes', 'bpy', 'blender foundation']

FEEDS = [
    "https://80.lv/rss/",
    "https://www.blendernation.com/feed/",
    "https://blenderartists.org/latest.rss",
    "https://devtalk.blender.org/c/news/weekly-updates/10.rss"
]

STATE_FILE = "posted.json"
translator = GoogleTranslator(source='auto', target='ru')

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

def extract_image(entry):
    if hasattr(entry, 'media_content'):
        for m in entry.media_content:
            if m.get('medium') == 'image': return m.get('url')
    if hasattr(entry, 'image'):
        return entry.image.get('href') if isinstance(entry.image, dict) else str(entry.image)
    
    content = ""
    if hasattr(entry, 'summary'): content += entry.summary
    if hasattr(entry, 'description'): content += entry.description
    if hasattr(entry, 'content') and entry.content: content += entry.content[0].value
    
    match = re.search(r'<img[^>]+src="([^"]+)"', content)
    return match.group(1) if match else None

def extract_links(content):
    links = re.findall(r'https?://[^\s<>"\')\]]+', content)
    cleaned = []
    for link in links:
        link = re.sub(r'["\'\)\]>]+$', '', link)
        domain = urlparse(link).netloc
        if not any(x in domain for x in ['facebook', 'twitter', 'instagram', 'youtube.com/watch', 'imgur']):
            if link not in cleaned: cleaned.append(link)
    return cleaned

def is_blender_news(title, description):
    text = (title + " " + description).lower()
    # Если есть ключевые слова Blender
    if any(kw in text for kw in KEYWORDS):
        return True
    return False

def translate_text(text):
    try:
        # Переводим только первые 500 символов для скорости и стабильности
        return translator.translate(text[:500])
    except:
        return text # Если переводчик заблокировал, оставляем как есть

def send_to_telegram(image_url, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    if image_url:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        try:
            resp = requests.get(image_url, timeout=10)
            if resp.status_code == 200:
                files = {'photo': ('img.jpg', resp.content, 'image/jpeg')}
                data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': text, 'parse_mode': 'HTML'}
                return requests.post(url, files=files, data=data, timeout=15).status_code == 200
        except:
            pass # Если картинка не загрузилась, отправим просто текст
    
    # Отправка текстом
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
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
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:5]:
            link = entry.get('link', '')
            if not link or link in posted:
                continue

            title = entry.get('title', 'Без заголовка')
            description = ""
            if hasattr(entry, 'summary'): description += entry.summary
            if hasattr(entry, 'description'): description += entry.description
            
            # 1. Фильтр по ключевым словам
            if not is_blender_news(title, description):
                print(f"⏭️ Пропуск (не Blender): {title[:40]}")
                continue

            print(f"✅ Найдено: {title[:50]}")

            # 2. Перевод
            ru_title = translate_text(title)
            # Берем только первый абзац или 200 символов для краткости
            short_desc = description.split('<p>')[0].replace('<br>', '').replace('<p>', '').replace('</p>', '')
            ru_desc = translate_text(short_desc)

            # 3. Формируем пост
            main_link = link
            post_text = f"<b>{ru_title}</b>\n\n{ru_desc}...\n\n🔗 Источник: {main_link}"

            # 4. Картинка
            image_url = extract_image(entry)

            # 5. Отправка
            print("📤 Отправка в Telegram...")
            if send_to_telegram(image_url, post_text):
                new_posted.append(link)
                updated = True
                save_posted(new_posted)
                print("✅ Успешно отправлено на модерацию!")
            else:
                print("❌ Ошибка отправки")
            
            time.sleep(1) # Пауза, чтобы не спамить запросами

    print("=" * 50)
    print("✅ Готово!" if updated else "ℹ️ Новых новостей про Blender нет.")

if __name__ == "__main__":
    main()
