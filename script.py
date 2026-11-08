import feedparser
import requests
import json
import os
import time
import re
from urllib.parse import urlparse
from datetime import datetime, timedelta
from huggingface_hub import InferenceClient

HF_API_KEY = os.environ.get('HF_API_KEY')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
UNSPLASH_ACCESS_KEY = os.environ.get('UNSPLASH_ACCESS_KEY', '')

# Инициализируем клиент Hugging Face с лучшей моделью для русского языка
client = InferenceClient(token=HF_API_KEY)
MODEL_NAME = "HuggingFaceH4/zephyr-7b-beta"
FEEDS = [
    "https://80.lv/rss/",
    "https://www.blendernation.com/feed/",
    "https://blenderartists.org/latest.rss",
    "https://devtalk.blender.org/c/news/weekly-updates/10.rss"
]

STATE_FILE = "posted.json"

# ===== ВРЕМЯ =====
def is_working_hours():
    """8:00 - 0:00 UTC+5 = 03:00 - 19:00 UTC"""
    now_utc = datetime.utcnow()
    return 3 <= now_utc.hour < 19

def get_time_info():
    now_utc = datetime.utcnow()
    now_utc5 = now_utc + timedelta(hours=5)
    return now_utc, now_utc5

# ===== ХРАНИЛИЩЕ =====
def load_posted():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_posted(posted):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(posted, f, ensure_ascii=False, indent=2)

# ===== КАРТИНКИ =====
def extract_image_from_entry(entry):
    image_url = None
    
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            if media.get('medium') == 'image' or media.get('type', '').startswith('image'):
                image_url = media.get('url')
                break
    
    if not image_url and hasattr(entry, 'image'):
        image_url = entry.image.get('href') if isinstance(entry.image, dict) else str(entry.image)
    
    if not image_url:
        content = ""
        if hasattr(entry, 'summary'): content += entry.summary
        if hasattr(entry, 'description'): content += entry.description
        if hasattr(entry, 'content') and entry.content: content += entry.content[0].value
        img_match = re.search(r'<img[^>]+src="([^"]+)"', content)
        if img_match: image_url = img_match.group(1)
    
    if not image_url and hasattr(entry, 'enclosures'):
        for enclosure in entry.enclosures:
            if hasattr(enclosure, 'type') and enclosure.type.startswith('image'):
                image_url = enclosure.href
                break
    
    return image_url

def search_unsplash_image(query):
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        response = requests.get("https://api.unsplash.com/search/photos", 
            params={'query': query, 'per_page': 1, 'orientation': 'landscape', 'client_id': UNSPLASH_ACCESS_KEY}, timeout=10)
        if response.status_code == 200 and response.json()['results']:
            return response.json()['results'][0]['urls']['regular']
    except:
        pass
    return None

def get_image_search_keywords(title, description):
    keywords = []
    text = (title + " " + description).lower()
    if any(x in text for x in ['blender', 'cycles', 'eevee', '3d']): keywords.append('blender 3d')
    if any(x in text for x in ['material', 'texture', 'pbr', 'shader']): keywords.append('3d materials textures')
    if any(x in text for x in ['render', 'animation']): keywords.append('3d rendering')
    if any(x in text for x in ['addon', 'plugin']): keywords.append('blender interface')
    if any(x in text for x in ['model', 'sculpt']): keywords.append('3d modeling')
    if len(keywords) < 2: keywords.append('blender 3d art')
    return ' '.join(keywords[:3])

# ===== ССЫЛКИ =====
def extract_links_from_content(content):
    links = re.findall(r'https?://[^\s<>"\')\]]+', content)
    cleaned = []
    for link in links:
        link = re.sub(r'["\'\)\]>]+$', '', link)
        domain = urlparse(link).netloc
        if not any(x in domain for x in ['facebook', 'twitter', 'instagram', 'youtube.com/watch', 'imgur', 'i.imgur']):
            if link not in cleaned: cleaned.append(link)
    return cleaned

# ===== AI (HUGGING FACE) =====
def check_with_ai(title, description, all_links, has_image):
    links_text = "\n".join(all_links[:3]) if all_links else "Нет"
    image_instruction = "\nВАЖНО: У новости НЕТ изображения. В самом конце поста добавь отдельной строкой: NO_IMAGE_FOUND" if not has_image else ""
    
    # Промпт специально под формат Zephyr
    prompt = f"""<|system|>
Ты редактор Telegram-канала о Blender. Отвечай ТОЛЬКО на русском языке.
Если новость НЕ про Blender (3D, рендер, аддоны), ответь ровно одним словом: IGNORE
<|user|>
Заголовок: {title}
Текст: {description[:1000]}
Ссылки: {links_text}
{image_instruction}

Создай пост СТРОГО по этому шаблону:
[Краткий заголовок на русском]

[Суть новости: 2-3 предложения, без воды]

🔗 [Название ресурса] — [ссылка]
🔗 [Название ресурса 2] — [ссылка]

Правила: макс. 800 символов, без жирного шрифта (*), ссылки полные.
<|assistant|>
"""
    
    for attempt in range(2):
        try:
            # Используем chat_completion, он стабильнее для Zephyr
            response = client.chat_completion(
                model="HuggingFaceH4/zephyr-7b-beta",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.3
            )
            text = response.choices[0].message.content.strip()
            
            # Чистим ответ от возможных кавычек
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            return text
            
        except Exception as e:
            print(f"  HF Attempt {attempt+1} error: {e}")
            if attempt == 0:
                print("  Жду 5 секунд (сервер HF просыпается)...")
                time.sleep(5)
    return "IGNORE"
    # Попытка запроса с защитой от "холодного старта" серверов HF
    for attempt in range(2):
        try:
            response = client.chat_completion(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.4
            )
            text = response.choices[0].message.content.strip()
            
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            return text
        except Exception as e:
            print(f"  HF Attempt {attempt+1} error: {e}")
            if attempt == 0:
                print("  Жду 5 секунд (сервер HF просыпается)...")
                time.sleep(5)
    return "IGNORE"

# ===== TELEGRAM =====
def send_photo_to_telegram(photo_url, caption):
    try:
        photo_response = requests.get(photo_url, timeout=15)
        if photo_response.status_code != 200: return False
        files = {'photo': ('image.jpg', photo_response.content, 'image/jpeg')}
        data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", files=files, data=data, timeout=20)
        return resp.status_code == 200
    except:
        return send_text_to_telegram(caption)

def send_text_to_telegram(text):
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        return resp.status_code == 200
    except:
        return False

# ===== ГЛАВНОЕ =====
def main():
    
    if not os.path.exists(STATE_FILE):
        save_posted([])
    
    now_utc, now_utc5 = get_time_info()
    print("=" * 50)
    print(f"🕐 Время: UTC {now_utc.strftime('%H:%M')} / UTC+5 {now_utc5.strftime('%H:%M')}")
    print("=" * 50)
    
    if not is_working_hours():
        print("⏰ НЕ рабочее время (08:00-00:00 UTC+5). Сплю.")
        return
    
    print("✅ Рабочее время. Начинаю...")
    posted = load_posted()
    new_posted = posted.copy()
    updated = False
    print(f"📦 Уже было: {len(posted)}\n")

    for feed_url in FEEDS:
        print(f"📡 {feed_url}")
        feed = feedparser.parse(feed_url)
        
        for entry in feed.entries[:5]:
            link = entry.get('link', '')
            if not link or link in posted: continue

            title = entry.get('title', 'Без заголовка')
            description = ""
            if hasattr(entry, 'summary'): description += entry.summary + "\n\n"
            if hasattr(entry, 'description'): description += entry.description + "\n\n"
            if hasattr(entry, 'content') and entry.content: description += entry.content[0].value + "\n\n"
            
            image_url = extract_image_from_entry(entry)
            print(f"  🔍 {title[:50]}... 📷 {'✅' if image_url else '❌'}")
            
            all_links = extract_links_from_content(description)
            if link and link not in all_links: all_links.insert(0, link)
            
            result = check_with_ai(title, description, all_links, image_url is not None)
            time.sleep(2)

            if result and "IGNORE" not in result:
                needs_image_search = "NO_IMAGE_FOUND" in result
                result = result.replace("NO_IMAGE_FOUND", "").strip()
                
                if not image_url and needs_image_search and UNSPLASH_ACCESS_KEY:
                    keywords = get_image_search_keywords(title, description)
                    image_url = search_unsplash_image(keywords)
                    print(f"     🔎 Unsplash: {'✅' if image_url else '❌'}")
                
                print(f"     📤 Отправка на модерацию...")
                success = send_photo_to_telegram(image_url, result) if image_url else send_text_to_telegram(result)
                
                if success:
                    new_posted.append(link)
                    updated = True
                    save_posted(new_posted)
                    print(f"     ✅ Отправлено!")
                else:
                    print(f"     ❌ Ошибка отправки")
            else:
                print(f"     ⏭️ Пропуск (не Blender или ошибка AI)")

    print("\n" + "=" * 50)
    print("✅ Готово!" if updated else "ℹ️ Новых нет.")
    print("=" * 50)

if __name__ == "__main__":
    main()
