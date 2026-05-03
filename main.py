import asyncio
import logging
import re
from datetime import datetime
from urllib.parse import urlencode, quote_plus

import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

# ---------- ЛОГИ ----------
logging.basicConfig(level=logging.INFO)

# ---------- ТОКЕН (вставлен) ----------
BOT_TOKEN = "8663065329:AAGsTfadlYYtBviD5-RXHHJf4YUBEzoqymw"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ---------- ДАННЫЕ ПОЛЬЗОВАТЕЛЯ В ОПЕРАТИВКЕ ----------
user_data = {}

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
    typing_max_reviews = State()
    typing_min_sold = State()
    typing_min_active = State()
    typing_min_reg_year = State()

# ---------- КНОПКИ СТАРТА ----------
@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔄 Начать новый поиск")
    await message.answer(
        "👋 Привет! Я парсер OLX (PL/BG/RO).\n"
        "Я буду спрашивать фильтры по шагам.\n"
        "Жми кнопку ниже, чтобы начать.",
        reply_markup=kb
    )

@dp.message_handler(lambda msg: msg.text == "🔄 Начать новый поиск")
async def start_search(message: types.Message, state: FSMContext):
    await state.finish()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add("🇵🇱 Польша", "🇧🇬 Болгария")
    kb.add("🇷🇴 Румыния")
    await message.answer("1️⃣ Выбери страну:", reply_markup=kb)
    await ParserStates.choosing_country.set()

# ---------- ШАГИ ЗАПОЛНЕНИЯ ФИЛЬТРОВ ----------
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
        f"2️⃣ Введи категорию (часть URL после домена).\n"
        f"Пример: elektronika/telefony-komorkowe\n"
        f"Или напиши 'пропустить', чтобы искать по всем.",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await ParserStates.typing_category.set()

@dp.message_handler(state=ParserStates.typing_category)
async def got_category(message: types.Message, state: FSMContext):
    cat = message.text.strip().lower()
    if cat == "пропустить":
        cat = ""
    await state.update_data(category=cat)
    await message.answer("3️⃣ Цена ОТ (в злотых/левах/леях). Напиши число или 'пропустить':")
    await ParserStates.typing_price_from.set()

@dp.message_handler(state=ParserStates.typing_price_from)
async def got_price_from(message: types.Message, state: FSMContext):
    val = message.text.strip().lower()
    await state.update_data(price_from=val if val != "пропустить" else "")
    await message.answer("4️⃣ Цена ДО. Число или 'пропустить':")
    await ParserStates.typing_price_to.set()

@dp.message_handler(state=ParserStates.typing_price_to)
async def got_price_to(message: types.Message, state: FSMContext):
    val = message.text.strip().lower()
    await state.update_data(price_to=val if val != "пропустить" else "")
    await message.answer("5️⃣ Максимум отрицательных отзывов у продавца (допустим, 0, 3, 5):")
    await ParserStates.typing_max_reviews.set()

@dp.message_handler(state=ParserStates.typing_max_reviews)
async def got_max_reviews(message: types.Message, state: FSMContext):
    try:
        rev = int(message.text.strip())
        await state.update_data(max_neg_reviews=rev)
    except:
        await state.update_data(max_neg_reviews=999)
    await message.answer("6️⃣ Минимальное КОЛИЧЕСТВО ПРОДАННЫХ товаров у продавца (введи число, например 10):")
    await ParserStates.typing_min_sold.set()

@dp.message_handler(state=ParserStates.typing_min_sold)
async def got_min_sold(message: types.Message, state: FSMContext):
    try:
        sold = int(message.text.strip())
        await state.update_data(min_sold=sold)
    except:
        await state.update_data(min_sold=0)
    await message.answer("7️⃣ Минимальное количество АКТИВНЫХ объявлений у продавца (число, например 5):")
    await ParserStates.typing_min_active.set()

@dp.message_handler(state=ParserStates.typing_min_active)
async def got_min_active(message: types.Message, state: FSMContext):
    try:
        act = int(message.text.strip())
        await state.update_data(min_active=act)
    except:
        await state.update_data(min_active=0)
    await message.answer("8️⃣ Минимальный ГОД регистрации продавца на OLX (например 2018):")
    await ParserStates.typing_min_reg_year.set()

# ---------- ФИНАЛЬНЫЙ ШАГ: ЗАПУСК ПАРСИНГА ----------
@dp.message_handler(state=ParserStates.typing_min_reg_year)
async def got_reg_year(message: types.Message, state: FSMContext):
    try:
        year = int(message.text.strip())
        await state.update_data(min_reg_year=year)
    except:
        await state.update_data(min_reg_year=0)
    
    data = await state.get_data()
    await message.answer("⏳ Ищу объявления, это может занять до минуты...")
    await state.finish()

    results = await parse_olx(data)

    if not results:
        await message.answer("😔 Ничего не нашлось под такие фильтры. Попробуй ослабить параметры.", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("🔄 Начать новый поиск"))
        return

    for i, item in enumerate(results[:30], 1):
        msg_text = (
            f"🔗 {item['link']}\n"
            f"👤 {item['seller']}\n"
            f"📅 На OLX с {item['reg_date'] or 'неизвестно'}\n"
            f"⭐ Отзывы: {item['reviews']}\n"
            f"📦 Продано: {item['sold']}\n"
            f"📋 Объявлений: {item['active_ads']}\n"
            f"💰 Цена: {item['price']}\n"
            f"📝 {item['title'][:80]}"
        )
        await message.answer(msg_text, disable_web_page_preview=False)
        if i % 10 == 0:
            await asyncio.sleep(1.5)

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔄 Начать новый поиск")
    await message.answer(f"✅ Готово! Показано до 30 объявлений.", reply_markup=kb)

# ---------- ЯДРО ПАРСЕРА ----------
async def parse_olx(data: dict) -> list:
    country = data.get("country", "pl")
    domain = OLX_DOMAINS[country]["domain"]
    category = data.get("category", "")
    price_from = data.get("price_from", "")
    price_to = data.get("price_to", "")
    max_neg_reviews = data.get("max_neg_reviews", 999)
    min_sold = data.get("min_sold", 0)
    min_active = data.get("min_active", 0)
    min_reg_year = data.get("min_reg_year", 0)

    results = []
    for page in range(1, 4):
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

                seller_info = await get_seller_info(link, min_reg_year, max_neg_reviews, min_sold, min_active)
                if seller_info:
                    results.append({
                        "title": title,
                        "price": price,
                        "link": link,
                        **seller_info
                    })

                await asyncio.sleep(0.3)
        except Exception as e:
            logging.error(f"Ошибка на странице {url}: {e}")
            continue

    return results

# ---------- ПОЛУЧЕНИЕ ИНФОРМАЦИИ О ПРОДАВЦЕ ----------
async def get_seller_info(offer_url: str, min_reg_year: int, max_neg_reviews: int, min_sold: int, min_active: int) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "Accept-Language": "pl,en;q=0.9",
    }
    try:
        resp = requests.get(offer_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        seller_name = "Неизвестно"
        seller_el = soup.select_one(".user-image__name, [data-testid='seller-name'], .css-12hdxwj")
        if seller_el:
            seller_name = seller_el.get_text(strip=True)

        reg_date = None
        reg_text = soup.get_text()
        reg_match = re.search(r"(?:на сервисе с|registered since|od)\s*(\d{4})", reg_text, re.IGNORECASE)
        if reg_match:
            reg_year = int(reg_match.group(1))
            if reg_year < min_reg_year:
                return None
            reg_date = reg_match.group(1)

        reviews_text = ""
        review_el = soup.select_one(".user-stats__reviews, [data-testid='rating']")
        if review_el:
            reviews_text = review_el.get_text(strip=True)
        
        neg_count = 0
        neg_match = re.search(r"(\d+)\s*(?:негативн|negative|negatywn)", reviews_text, re.IGNORECASE)
        if neg_match:
            neg_count = int(neg_match.group(1))
        if neg_count > max_neg_reviews:
            return None

        sold_count = 0
        active_count = 0
        stats_el = soup.select_one(".user-stats, [data-testid='seller-stats']")
        if stats_el:
            stats_text = stats_el.get_text()
            sold_match = re.search(r"(\d+)\s*(?:продано|sold|sprzedane)", stats_text, re.IGNORECASE)
            active_match = re.search(r"(\d+)\s*(?:активн|active|aktywn)", stats_text, re.IGNORECASE)
            if sold_match: sold_count = int(sold_match.group(1))
            if active_match: active_count = int(active_match.group(1))
        
        if sold_count < min_sold or active_count < min_active:
            return None

        return {
            "seller": seller_name,
            "reg_date": f"{reg_date} г." if reg_date else "???",
            "reviews": f"{neg_count} негативных",
            "sold": sold_count,
            "active_ads": active_count
        }

    except Exception as e:
        logging.warning(f"Не смог распарсить продавца {offer_url}: {e}")
        return None

# ---------- ЗАПУСК БОТА ----------
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
