import asyncio
import logging
from urllib.parse import urlencode
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor

# ---------- НАСТРОЙКИ ----------
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = "8663065329:AAGsTfadlYYtBviD5-RXHHJf4YUBEzoqymw"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ---------- ДАННЫЕ СТРАН ----------
COUNTRIES = {
    "pl": {"domain": "olx.pl", "name": "Польша 🇵🇱"},
    "bg": {"domain": "olx.bg", "name": "Болгария 🇧🇬"},
    "ro": {"domain": "olx.ro", "name": "Румыния 🇷🇴"},
}

# ---------- ГЛАВНЫЙ ЭКРАН С КНОПКАМИ СТРАН ----------
def main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🇵🇱 Польша", "🇧🇬 Болгария")
    kb.add("🇷🇴 Румыния")
    return kb

@dp.message_handler(commands=["start", "help"])
async def start(message: types.Message):
    await message.answer("🌍 Привет! Выбери страну для парсинга OLX.\nЯ пришлю 30 свежих объявлений.", reply_markup=main_keyboard())

# ---------- ОБРАБОТЧИК ВЫБОРА СТРАНЫ (СРАЗУ ЗАПУСКАЕТ ПОИСК) ----------
@dp.message_handler(lambda msg: msg.text in ["🇵🇱 Польша", "🇧🇬 Болгария", "🇷🇴 Румыния"])
async def parse_country(message: types.Message):
    choice = message.text
    if "Польша" in choice: code = "pl"
    elif "Болгария" in choice: code = "bg"
    else: code = "ro"
    
    country = COUNTRIES[code]
    await message.answer(f"🔍 Паршу {country['name']} (m.{country['domain']}). Жди 30 объявлений...", reply_markup=types.ReplyKeyboardRemove())
    
    # Запускаем парсинг
    results = await simple_parse(country)
    
    if not results:
        await message.answer("❌ Не нашёл объявлений. Возможно, OLX заблокировал запрос. Попробуй позже.", reply_markup=main_keyboard())
        return

    # Отправка результатов
    await message.answer(f"📊 Найдено: {len(results)} объявлений в {country['name']}")
    
    for i, item in enumerate(results, 1):
        msg_text = (
            f"🔗 {item['link']}\n"
            f"📝 {item['title']}\n"
            f"💰 Цена: {item['price']}\n"
            f"📍 {item['location']}\n"
            f"🕒 {item['date']}"
        )
        await message.answer(msg_text, disable_web_page_preview=True)
        if i % 10 == 0:
            await asyncio.sleep(1)
    
    await message.answer("✅ Готово! Можешь выбрать другую страну.", reply_markup=main_keyboard())

# ---------- САМЫЙ ПРОСТОЙ И НАДЁЖНЫЙ ПАРСЕР (БЕЗ ФИЛЬТРОВ, БЕЗ ДРОПОВ) ----------
async def simple_parse(country: dict) -> list:
    domain = country["domain"]
    all_offers = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pl,en-US;q=0.7,en;q=0.3",
    }

    for page in range(1, 4):  # 3 страницы = ~ 40-50 объявлений
        url = f"https://www.{domain}/?page={page}"
        
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Ищем все карточки товаров (универсальный поиск по data-cy)
            cards = soup.select('[data-cy="l-card"]')
            
            if not cards:
                # Фоллбэк: ищем по старым классам
                cards = soup.select('.offer-wrapper, .EIR5N, [data-testid="listing-grid"] > div')
            
            for card in cards:
                try:
                    # Ссылка и заголовок
                    link_el = card.select_one('a')
                    if not link_el or 'href' not in link_el.attrs:
                        continue
                    link = link_el['href']
                    if link.startswith('/'):
                        link = f"https://www.{domain}{link}"
                    title = link_el.get_text(strip=True) or "Без названия"
                    
                    # Цена
                    price_el = card.select_one('[data-testid="price"], .price, .price-wrapper')
                    price = price_el.get_text(strip=True) if price_el else "Цена не указана"
                    
                    # Локация и дата
                    location = "Не указана"
                    date = "Не указана"
                    loc_el = card.select_one('[data-testid="location"], .location, .date-location')
                    if loc_el:
                        loc_text = loc_el.get_text(strip=True)
                        parts = loc_text.split(' - ')
                        if len(parts) == 2:
                            location, date = parts
                        else:
                            location = loc_text
                    
                    all_offers.append({
                        "link": link,
                        "title": title[:80],
                        "price": price,
                        "location": location,
                        "date": date
                    })
                except:
                    continue
                    
        except Exception as e:
            logging.error(f"Ошибка на странице {page}: {e}")
            continue
        
        await asyncio.sleep(1)  # Пауза между страницами
    
    return all_offers[:30]  # Отдаём ровно 30

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
