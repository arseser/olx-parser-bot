import asyncio
import logging
import re
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

# ---------- ЛОГИ ----------
logging.basicConfig(level=logging.INFO)

# ---------- ТОКЕН ----------
BOT_TOKEN = "8663065329:AAGsTfadlYYtBviD5-RXHHJf4YUBEzoqymw"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ---------- ХРАНИЛИЩЕ НАСТРОЕК ----------
saved_filters = {}

# ---------- ДОМЕНЫ OLX ----------
OLX_DOMAINS = {
    "pl": {"domain": "olx.pl", "name": "Польша 🇵🇱"},
    "bg": {"domain": "olx.bg", "name": "Болгария 🇧🇬"},
    "ro": {"domain": "olx.ro", "name": "Румыния 🇷🇴"},
}

# ---------- FSM СОСТОЯНИЯ ----------
class ParserStates(StatesGroup):
    choosing_country = State()
    typing_category = State()
    typing_price_from = State()
    typing_price_to = State()

# ---------- ГЛАВНОЕ МЕНЮ ----------
def main_keyboard(has_saved: bool = False):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if has_saved:
        kb.add("⚡ Быстрый поиск (сохранённые фильтры)")
    kb.add("🔄 Новый поиск")
    return kb

# ---------- СТАРТ ----------
@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    has = uid in saved_filters
    await message.answer(
        "👋 Привет! Я парсер OLX (Польша/Болгария/Румыния).\n"
        "Выдаю до 30 объявлений с инфой о продавце.\n\n"
        + ("✅ Есть сохранённые фильтры — жми Быстрый поиск." if has else "⚠ Сначала настрой поиск."),
        reply_markup=main_keyboard(has)
    )

# ---------- БЫСТРЫЙ ПОИСК ----------
@dp.message_handler(lambda msg: msg.text == "⚡ Быстрый поиск (сохранённые фильтры)")
async def quick_search(message: types.Message):
    uid = message.from_user.id
    if uid not in saved_filters:
        await message.answer("❌ Нет сохранённых фильтров.", reply_markup=main_keyboard(False))
        return
    data = saved_filters[uid]
    country_name = OLX_DOMAINS[data['country']]['name']
    await message.answer(f"⏳ Ищу по сохранённым фильтрам ({country_name})...", reply_markup=types.ReplyKeyboardRemove())
    results = await parse_olx(data)
    await send_results(message, results, country_name)

# ---------- НОВЫЙ ПОИСК (ШАГ 1) ----------
@dp.message_handler(lambda msg: msg.text == "🔄 Новый поиск")
async def new_search(message: types.Message, state: FSMContext):
    await state.finish()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add("🇵🇱 Польша", "🇧🇬 Болгария", "🇷🇴 Румыния")
    await message.answer("1️⃣ Выбери страну:", reply_markup=kb)
    await ParserStates.choosing_country.set()

# ---------- ШАГИ ----------
@dp.message_handler(state=ParserStates.choosing_country)
async def got_country(message: types.Message, state: FSMContext):
    choice = message.text
    code = ""
    if "Польша" in choice: code = "pl"
    elif "Болгария" in choice: code = "bg"
    elif "Румыния" in choice: code = "ro"
    else:
        await message.answer("Пожалуйста, выбери страну кнопкой.")
        return

    await state.update_data(country=code)
    await message.answer(
        "2️⃣ Введи категорию (часть URL после домена).\n"
        "Пример: elektronika/telefony-komorkowe\n"
        "Или 'пропустить' — все категории.",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await ParserStates.typing_category.set()

@dp.message_handler(state=ParserStates.typing_category)
async def got_category(message: types.Message, state: FSMContext):
    cat = message.text.strip().lower()
    if cat == "пропустить":
        cat = ""
    await state.update_data(category=cat)
    await message.answer("3️⃣ Цена ОТ (число или 'пропустить'):")
    await ParserStates.typing_price_from.set()

@dp.message_handler(state=ParserStates.typing_price_from)
async def got_price_from(message: types.Message, state: FSMContext):
    val = message.text.strip().lower()
    await state.update_data(price_from=val if val != "пропустить" else "")
    await message.answer("4️⃣ Цена ДО (число или 'пропустить'):")
    await ParserStates.typing_price_to.set()

@dp.message_handler(state=ParserStates.typing_price_to)
async def got_price_to(message: types.Message, state: FSMContext):
    val = message.text.strip().lower()
    await state.update_data(price_to=val if val != "пропустить" else "")
    
    data = await state.get_data()
    await state.finish()
    
    # Сохраняем фильтры
    uid = message.from_user.id
    saved_filters[uid] = data
    
    country_name = OLX_DOMAINS[data['country']]['name']
    await message.answer(f"⏳ Ищу объявления ({country_name})...")
    
    results = await parse_olx(data)
    await send_results(message, results, country_name)

# ---------- ОТПРАВКА РЕЗУЛЬТАТОВ ----------
async def send_results(message: types.Message, results: list, country_name: str):
    if not results:
        kb = main_keyboard(message.from_user.id in saved_filters)
        await message.answer("😔 Вообще ничего не нашлось. Попробуй другую категорию или страну.", reply_markup=kb)
        return
    
    await message.answer(f"📊 Найдено объявлений: {len(results)} ({country_name})")
    
    for i, item in enumerate(results, 1):
        msg_text = (
            f"🔗 {item['link']}\n"
            f"👤 Продавец: {item['seller']}\n"
            f"📅 На OLX с: {item['reg_date']}\n"
            f"⭐ Отзывы: {item['reviews']}\n"
            f"📦 Продано: {item['sold']}\n"
            f"📋 Активных: {item['active_ads']}\n"
            f"💰 Цена: {item['price']}\n"
            f"📝 {item['title'][:80]}"
        )
        await message.answer(msg_text, disable_web_page_preview=False)
        if i % 10 == 0:
            await asyncio.sleep(1.5)
    
    kb = main_keyboard(message.from_user.id in saved_filters)
    await message.answer(f"✅ Готово! {country_name} — показано {len(results)} объявлений.", reply_markup=kb)

# ---------- ПАРСЕР ----------
async def parse_olx(data: dict) -> list:
    country = data.get("country", "pl")
    domain = OLX_DOMAINS[country]["domain"]
    category = data.get("category", "")
    price_from = data.get("price_from", "")
    price_to = data.get("price_to", "")

    results = []
    for page in range(1, 4):  # 3 страницы = ~30+ объявлений
        url = f"https://m.{domain}/"
        if category:
            url += f"{category}/"
        
        params = {}
        if price_from:
            params["search[filter_float_price:from]"] = price_from
        if price_to:
            params["search[filter_float_price:to]"] = price_to
        if page > 1:
            params["page"] = page
        
        if params:
            url += "?" + urlencode(params)

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
            "Accept-Language": "pl,en;q=0.9",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            offers = soup.select(".offer, [data-cy='listing-item']")
            
            for offer in offers:
                link_el = offer.select_one("a")
                if not link_el:
                    continue
                link = "https://" + domain + link_el.get("href", "")
                title = link_el.get_text(strip=True)

                price_el = offer.select_one(".price, [data-testid='listing-price']")
                price = price_el.get_text(strip=True) if price_el else "N/A"

                # Парсим продавца БЕЗ фильтрации (всегда добавляем)
                seller_info = await get_seller_info(link)
                if seller_info:
                    results.append({
                        "title": title,
                        "price": price,
                        "link": link,
                        **seller_info
                    })
                else:
                    # Даже если продавец не распарсился — добавляем хоть что-то
                    results.append({
                        "title": title,
                        "price": price,
                        "link": link,
                        "seller": "Неизвестно",
                        "reg_date": "???",
                        "reviews": "???",
                        "sold": "???",
                        "active_ads": "???"
                    })

                await asyncio.sleep(0.3)
        except Exception as e:
            logging.error(f"Ошибка на странице {url}: {e}")
            continue

    return results

# ---------- ИНФА О ПРОДАВЦЕ (БЕЗ ФИЛЬТРОВ, ПРОСТО СОБИРАЕМ) ----------
async def get_seller_info(offer_url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "Accept-Language": "pl,en;q=0.9",
    }
    try:
        resp = requests.get(offer_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Продавец
        seller_name = "Неизвестно"
        seller_el = soup.select_one(".user-image__name, [data-testid='seller-name'], .css-12hdxwj")
        if seller_el:
            seller_name = seller_el.get_text(strip=True)

        # Год регистрации
        reg_date = "???"
        reg_text = soup.get_text()
        reg_match = re.search(r"(?:на сервисе с|registered since|od|на сайта от)\s*(\d{4})", reg_text, re.IGNORECASE)
        if reg_match:
            reg_date = reg_match.group(1) + " г."

        # Отзывы
        reviews_text = ""
        review_el = soup.select_one(".user-stats__reviews, [data-testid='rating']")
        if review_el:
            reviews_text = review_el.get_text(strip=True)
        
        neg_count = "0"
        neg_match = re.search(r"(\d+)\s*(?:негативн|negative|negatywn)", reviews_text, re.IGNORECASE)
        if neg_match:
            neg_count = neg_match.group(1)

        # Продано / Активные
        sold_count = "0"
        active_count = "0"
        stats_el = soup.select_one(".user-stats, [data-testid='seller-stats']")
        if stats_el:
            stats_text = stats_el.get_text()
            sold_match = re.search(r"(\d+)\s*(?:продано|sold|sprzedane)", stats_text, re.IGNORECASE)
            active_match = re.search(r"(\d+)\s*(?:активн|active|aktywn)", stats_text, re.IGNORECASE)
            if sold_match: sold_count = sold_match.group(1)
            if active_match: active_count = active_match.group(1)

        return {
            "seller": seller_name,
            "reg_date": reg_date,
            "reviews": f"{neg_count} негативных",
            "sold": sold_count,
            "active_ads": active_count
        }

    except:
        return None

# ---------- ЗАПУСК ----------
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
