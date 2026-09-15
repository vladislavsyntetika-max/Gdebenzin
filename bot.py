"""
Бот "АЗС СПб - топливо в реале"
Краудсорсинговый мониторинг наличия топлива на АЗС Санкт-Петербурга.
"""

import asyncio
import json
import logging
import os
import html
import re
import socket
import sqlite3
import time
from datetime import datetime
from collections import Counter

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.exceptions import TelegramBadRequest
from aiohttp import TCPConnector, ClientSession, ClientTimeout

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "data/db.sqlite3")
MAP_URL = os.getenv("MAP_URL", "")
PORT = int(os.getenv("PORT", "8080"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("azs-bot")

NETWORKS = {
    "gpn": {"label": "Газпромнефть", "dot": "🔵"},
    "lukoil": {"label": "Лукойл", "dot": "🔴"},
    "rosneft": {"label": "Роснефть", "dot": "🟠"},
    "tatneft": {"label": "Татнефть", "dot": "🟣"},
    "ptk": {"label": "ПТК", "dot": "🟤"},
    "faeton": {"label": "Фаэтон", "dot": "⚫"},
    "kirishi": {"label": "Киришиавтосервис", "dot": "🟡"},
    "teboil": {"label": "Teboil", "dot": "🔷"},
    "other": {"label": "Независимые АЗС", "dot": "⚪"},
}

FUELS = [("f92","АИ-92"),("f95","АИ-95"),("f98","АИ-98"),("dt","ДТ")]
FUEL_SHORT = {"f92": "92", "f95": "95", "f98": "98", "dt": "ДТ"}

STATUSES = [("ok","✅ Есть"),("low","🟡 Мало"),("none","❌ Нет")]
STATUS_LABEL = {k: v for k, v in STATUSES}

STATION_FLAGS = [("flag_queue","🚗 Очередь"),("flag_limit","⛔ Лимит на литры")]
STATION_FLAG_LABEL = {k: v for k, v in STATION_FLAGS}

POINTS_REPORT = 2
POINTS_SCOUT_BONUS = 5
POINTS_STREAK_3 = 10
POINTS_STREAK_7 = 30

RANKS = [
    (0, "Новичок"),
    (21, "Заправщик"),
    (101, "Разведчик"),
    (301, "Смотритель района"),
    (701, "Легенда бензоколонки"),
]


def get_rank(points):
    rank = RANKS[0][1]
    for threshold, label in RANKS:
        if points >= threshold:
            rank = label
        else:
            break
    return rank


def next_rank_info(points):
    for threshold, label in RANKS:
        if points < threshold:
            return threshold - points, label
    return None


def display_name(user):
    return user.username or user.full_name or f"id{user.id}"


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def is_real_username(name):
    return bool(name and _USERNAME_RE.match(name))


def format_display(name, user_id=None):
    if name and name.startswith("id") and name[2:].isdigit():
        name = None
    if not name:
        return f"участник {user_id}" if user_id else "аноним"
    clean = name.strip()[:40] or "аноним"
    if is_real_username(clean):
        return f"@{clean}"
    return html.escape(clean)


STATIONS = [
    ("gpn-1", "Газпромнефть", "gpn", "ул. Десантников, 21", 59.8534, 30.1992),
    ("gpn-2", "Газпромнефть", "gpn", "Кушелевская дорога, 8", 59.9886, 30.368),
    ("gpn-3", "Газпромнефть", "gpn", "Индустриальный пр., 68", 59.9696, 30.456),
    ("gpn-4", "Газпромнефть", "gpn", "Планерная ул., 30", 60.0083, 30.2352),
    ("gpn-5", "Газпромнефть", "gpn", "ул. Полевая Сабировская, 56", 59.9978, 30.2691),
    ("gpn-6", "Газпромнефть", "gpn", "Лахтинский пр., 149А", 59.9954, 30.1235),
    ("gpn-7", "Газпромнефть", "gpn", "ул. Седова, 43к2", 59.8867, 30.4223),
    ("gpn-8", "Газпромнефть", "gpn", "Софийская ул., 69", 59.8554, 30.4221),
    ("gpn-9", "Газпромнефть", "gpn", "Придорожная аллея, 28", 60.0534, 30.3736),
    ("luk-1", "Лукойл", "lukoil", "ул. Розенштейна, 37", 59.9042, 30.2869),
    ("luk-2", "Лукойл", "lukoil", "Херсонский пр., 4", 59.9289, 30.3858),
    ("luk-3", "Лукойл АЗС №95", "lukoil", "Литовская ул., 5а", 59.9776, 30.3471),
    ("luk-4", "Лукойл", "lukoil", "Кушелевская дорога, 18", 59.9905, 30.3728),
    ("luk-5", "Лукойл", "lukoil", "Благодатная ул., 10", 59.8762, 30.3066),
    ("luk-6", "Лукойл", "lukoil", "Дальневосточный пр., 40", 59.8949, 30.4624),
    ("luk-7", "Лукойл", "lukoil", "пр. Просвещения, 10", 60.0592, 30.307),
    ("luk-8", "Лукойл", "lukoil", "Выборгская наб., 18", 59.9697, 30.3368),
    ("luk-9", "Лукойл АЗС №33", "lukoil", "Московское ш., 13Д", 59.8244, 30.3551),
    ("ptk-1", "Petersburg Fuel Company", "ptk", "пр. Маршала Жукова, 10а", 59.8661, 30.244),
    ("ptk-2", "ПТК", "ptk", "Левашовский пр., 19лА", 59.967, 30.2835),
    ("ros-1", "Роснефть", "rosneft", "Театральная пл., 7лА", 59.9269, 30.2981),
    ("ros-2", "Роснефть АЗС №17", "rosneft", "пр. Наставников, 2к1", 59.9348, 30.4865),
    ("ros-3", "Роснефть АЗС №17", "rosneft", "пр. Ветеранов, 182", 59.8347, 30.1257),
    ("ros-4", "Роснефть АЗС №17", "rosneft", "Александровский парк, 8лА", 59.9532, 30.3221),
    ("ros-5", "Роснефть", "rosneft", "Коломяжский пр., 13к7", 59.9991, 30.3005),
    ("ros-6", "Роснефть АЗС №17", "rosneft", "пр. Королёва, 40", 60.0181, 30.2566),
    ("ros-7", "Роснефть АЗС №17", "rosneft", "ул. Книповича, 11лА", 59.9076, 30.394),
    ("ros-8", "Роснефть АЗС №17", "rosneft", "ул. Маршала Казакова, 25а", 59.8604, 30.2173),
    ("nes-1", "Татнефть (бывш. Neste)", "tatneft", "Средний пр. В.О., 91к2", 59.9352, 30.2502),
    ("nes-2", "Татнефть (бывш. Neste)", "tatneft", "ул. Партизана Германа, 4", 59.8429, 30.1766),
    ("nes-3", "Татнефть (бывш. Neste)", "tatneft", "Московский пр., 102", 59.8967, 30.3197),
    ("nes-4", "Татнефть (бывш. Neste)", "tatneft", "пр. Испытателей, 2а", 60.0017, 30.3041),
    ("nes-5", "Татнефть (бывш. Neste)", "tatneft", "пр. Косыгина, 20", 59.9456, 30.48),
    ("nes-6", "Татнефть (бывш. Neste)", "tatneft", "Северный пр., 32", 60.0327, 30.3627),
    ("nes-7", "Татнефть (бывш. Neste)", "tatneft", "Софийская ул., 127к1", 59.8882, 30.3809),
    ("nes-8", "Татнефть (бывш. Neste)", "tatneft", "Выборгское ш., 21", 60.0578, 30.3083),
    ("tat-1", "Татнефть", "tatneft", "Лабораторный пр., 21", 59.9808, 30.3843),
    ("tat-2", "Татнефть", "tatneft", "Планерная ул., 57к1", 60.0214, 30.2248),
    ("tat-3", "Татнефть", "tatneft", "Кузнецовская ул., 35", 59.8719, 30.345),
    ("tat-4", "Татнефть", "tatneft", "Вербная ул., 23", 60.0234, 30.2949),
    ("gpn-10", "Газпромнефть", "gpn", "Пискарёвский пр., 4Ц", 59.9606, 30.4066),
    ("gpn-11", "Газпромнефть", "gpn", "пр. Маршала Блюхера, 9/1", 59.9801, 30.3759),
    ("gpn-12", "Газпромнефть", "gpn", "Выборгская наб., 57/1", 59.97817, 30.32678),
    ("gpn-13", "Газпромнефть", "gpn", "пр. Обуховской Обороны, 303", 59.8422, 30.4839),
    ("gpn-14", "Газпромнефть", "gpn", "пер. Матюшенко, 3", 59.8785, 30.4462),
    ("gpn-15", "Газпромнефть", "gpn", "ул. Коллонтай, 8А", 59.91596, 30.45178),
    ("gpn-16", "Газпромнефть", "gpn", "Советский пр., 55к1", 59.824386, 30.553353),
    ("gpn-17", "Газпромнефть", "gpn", "Софийская ул., 17/2", 59.88254, 30.38917),
    ("gpn-18", "Газпромнефть", "gpn", "пр. Обуховской Обороны, 227к1", 59.864803, 30.468587),
    ("gpn-19", "Газпромнефть", "gpn", "ул. Фучика, 8к2", 59.880989, 30.376033),
    ("gpn-20", "Газпромнефть", "gpn", "пр. Культуры, 3А", 60.034957, 30.365914),
    ("gpn-21", "Газпромнефть", "gpn", "ул. Циолковского, 18Я", 59.909854, 30.289295),
    ("luk-10", "Лукойл АЗС №159", "lukoil", "ул. Орджоникидзе, 50А", 59.843367, 30.354434),
    ("luk-11", "Лукойл", "lukoil", "Московское ш., 35А", 59.818122, 30.366216),
    ("luk-12", "Лукойл", "lukoil", "Пулковское ш., 42к5", 59.815035, 30.324985),
    ("luk-13", "Лукойл АЗС №78060", "lukoil", "Пулковское ш., 37к1", 59.791724, 30.32353),
    ("luk-14", "Лукойл", "lukoil", "Витебский пр., 22", 59.854971, 30.362547),
    ("luk-15", "Лукойл", "lukoil", "Московское ш., 13к4", 59.826831, 30.350979),
    ("luk-16", "Лукойл", "lukoil", "Лиговский пр., 246Т", 59.899133, 30.340766),
    ("luk-17", "Лукойл", "lukoil", "Приморское ш., 45а", 59.998499, 30.098352),
    ("luk-18", "Лукойл", "lukoil", "Школьная ул., 91", 59.991559, 30.196632),
    ("luk-19", "Лукойл", "lukoil", "Богатырский пр., 17", 60.000874, 30.261883),
    ("luk-20", "Лукойл", "lukoil", "Долгоозёрная ул., 30", 60.022592, 30.266664),
    ("luk-21", "Лукойл", "lukoil", "ул. Полевая Сабировская, 48к2", 59.994265, 30.272802),
    ("luk-22", "Лукойл", "lukoil", "Комендантский пр., 43к2", 60.026694, 30.238589),
    ("luk-23", "Лукойл", "lukoil", "ул. Генерала Хрулёва, 2", 59.995767, 30.298604),
    ("luk-24", "Лукойл АЗС №78117", "lukoil", "Комендантский пр., 44к1", 60.026228, 30.236442),
    ("ros-9", "Роснефть АЗС №17", "rosneft", "Ириновский пр., 22к1", 59.957908, 30.473164),
    ("ros-10", "Роснефть АЗС №17", "rosneft", "ул. Стасовой, 13", 59.96825, 30.43969),
    ("ros-11", "Роснефть", "rosneft", "шоссе Революции, 86к3", 59.962224, 30.459003),
    ("ros-12", "Роснефть АЗС №17", "rosneft", "Партизанская ул., 17а", 59.9474, 30.43509),
    ("ros-13", "Роснефть (ТНК)", "rosneft", "ул. Коммуны, 17", 59.945882, 30.506002),
    ("ros-14", "Роснефть", "rosneft", "Малоохтинская наб., 16", 59.934444, 30.40226),
    ("ros-15", "Роснефть", "rosneft", "Шафировский пр., 18", 59.988851, 30.464935),
    ("ros-16", "Роснефть", "rosneft", "Львовская ул., 7", 59.96935, 30.418367),
    ("ros-17", "Роснефть", "rosneft", "Ириновский пр., 52", 59.962306, 30.487613),
    ("ros-18", "Роснефть АЗС №17", "rosneft", "Карпатская ул., 1", 59.844205, 30.422406),
    ("ros-19", "Роснефть", "rosneft", "Будапештская ул., 116", 59.826124, 30.411756),
    ("ptk-3", "ПТК", "ptk", "Южное ш., 45", 59.862176, 30.413997),
    ("ros-20", "Роснефть АЗС №17", "rosneft", "Днепропетровская ул., 20лА", 59.907442, 30.356098),
    ("ros-21", "Роснефть", "rosneft", "Софийская ул., 73к2", 59.852402, 30.424924),
    ("ros-22", "Роснефть", "rosneft", "ул. Фучика, 23к1", 59.883426, 30.385568),
    ("ros-23", "Роснефть", "rosneft", "Волковский пр., 61", 59.890651, 30.354622),
    ("ros-24", "Роснефть", "rosneft", "Малая Балканская ул., 13лА", 59.838389, 30.376577),
    ("ptk-4", "ПТК", "ptk", "ул. Салова, 55а", 59.888257, 30.376722),
    ("ros-25", "Роснефть", "rosneft", "Южное ш., 61", 59.856473, 30.40079),
    ("nes-9", "Татнефть (бывш. Neste)", "tatneft", "Малоохтинская наб., 59", 59.930608, 30.400265),
    ("fae-2", "Фаэтон", "faeton", "Объездное шоссе, 15", 59.954314, 30.454019),
    ("fae-3", "Фаэтон", "faeton", "Верхняя ул., 10", 60.057771, 30.363871),
    ("fae-4", "Фаэтон", "faeton", "Выборгское ш., 83-й км", 60.080831, 30.263811),
    ("ros-26", "Роснефть", "rosneft", "Всеволожск, 41К-064, 8", 60.0262007, 30.6157399),
    ("ros-27", "Роснефть АЗС №17", "rosneft", "Всеволожск, 41К-064, 1", 60.009913, 30.575332),
    ("tat-5", "Татнефть", "tatneft", "Всеволожск, Колтушское ш., 303", 59.991473, 30.659414),
    ("tat-6", "Татнефть", "tatneft", "Всеволожск, шоссе Дорога Жизни, 6е", 60.020042, 30.601892),
    ("ptk-5", "ПТК", "ptk", "Всеволожск, Колтушское ш., 302", 59.993325, 30.657223),
    ("kir-1", "Киришиавтосервис АЗК-19", "kirishi", "пр. Маршала Жукова, 23А", 59.8619, 30.2332),
    ("kir-2", "Киришиавтосервис АЗК-10", "kirishi", "ул. Рустави, 48лА", 60.0262, 30.4316),
    ("kir-3", "Киришиавтосервис", "kirishi", "Балтийская ул., 43лА", 59.8995, 30.2886),
    ("kir-4", "Киришиавтосервис", "kirishi", "Лапинский пр., 10", 59.9806, 30.4603),
    ("kir-5", "Киришиавтосервис", "kirishi", "пр. Обуховской Обороны, 138к1лА", 59.8468, 30.4849),
    ("kir-6", "Киришиавтосервис", "kirishi", "Московское ш., 11лА", 59.8117, 30.3830),
    ("kir-7", "Киришиавтосервис", "kirishi", "ул. Коммуны, 14лА", 59.9410, 30.5037),
    ("kir-8", "Киришиавтосервис", "kirishi", "Шафировский пр., 24лА", 59.9886, 30.4695),
    ("teb-1", "Teboil", "teboil", "Всеволожск, Приютинская ул., 36", 60.0136, 30.5876),
    ("tat-7", "Татнефть (бывш. Neste)", "tatneft", "пр. Маршала Блюхера, 2к7", 59.9866, 30.3622),
    ("tat-8", "Татнефть", "tatneft", "Шафировский пр., 20", 59.988896, 30.466481),
    ("luk-25", "Лукойл АЗС №78008", "lukoil", "Кушелевская дорога, 9", 59.9906, 30.3766),
    ("luk-26", "Лукойл", "lukoil", "Шафировский пр., 10к4", 59.9902, 30.4520),
    ("luk-27", "Лукойл", "lukoil", "Шафировский пр., 21", 59.9875, 30.4572),
    ("luk-28", "Лукойл", "lukoil", "ул. Коммуны, 76", 59.9662, 30.4829),
    ("ptk-6", "ПТК", "ptk", "пр. Непокорённых, 15лА", 59.9954, 30.3805),
    ("gpn-26", "Газпромнефть (NORD point)", "gpn", "Планерная ул., 22", 60.004432, 30.234572),
    ("teb-2", "Teboil", "teboil", "пр. Маршала Блюхера, 39", 59.975626, 30.406832),
    ("teb-3", "Teboil", "teboil", "пр. Маршала Блюхера, 2к1", 59.986981, 30.359011),
    ("teb-4", "Teboil", "teboil", "Ждановская ул., 2А", 59.955089, 30.284231),
    ("gpn-27", "Газпромнефть", "gpn", "5-й Предпортовый пр.", 59.834155, 30.309285),
    ("luk-53", "Лукойл", "lukoil", "5-й Предпортовый пр.", 59.834096, 30.310338),
    ("ros-28", "Роснефть", "rosneft", "5-й Предпортовый пр.", 59.833146, 30.309711),
    ("tat-12", "Татнефть", "tatneft", "Пулковское ш.", 59.819919, 30.324900),
    ("gpn-28", "Газпромнефть", "gpn", "Пулковское ш.", 59.816631, 30.324669),
    ("ros-29", "Роснефть", "rosneft", "Пулковское шоссе, 27", 59.814955, 30.321697),
    ("tat-10", "Татнефть", "tatneft", "Ириновский пр., 26", 59.958832, 30.476073),
    ("tat-11", "Татнефть", "tatneft", "пр. Непокорённых, 62", 59.995352, 30.406707),
    ("oth-1", "Газпромнефть", "gpn", "Малый пр. В.О., 79", 59.938575, 30.231829),
    ("oth-2", "АГЗС Vervex", "other", "Выборгская наб., 57", 59.978303, 30.327286),
    ("gpn-22", "Газпромнефть", "gpn", "Всеволожск, 41К-064", 60.015928, 30.591937),
    ("gpn-24", "Газпромнефть", "gpn", "ул. Потапова, 7", 59.961516, 30.470863),
    ("gpn-25", "Газпромнефть", "gpn", "пр. Культуры, 31", 60.051728, 30.382737),
    ("luk-29", "Лукойл", "lukoil", "шоссе Революции, 70", 59.960722, 30.445248),
    ("luk-30", "Лукойл", "lukoil", "Индустриальный пр., 46", 59.960091, 30.461252),
    ("luk-31", "Лукойл", "lukoil", "пр. Косыгина, 2А", 59.939932, 30.450263),
    ("luk-32", "Лукойл", "lukoil", "Пискарёвский пр., 30", 59.974562, 30.413729),
    ("luk-33", "Лукойл", "lukoil", "Свердловская наб., 58к4", 59.955530, 30.407308),
    ("luk-34", "Лукойл", "lukoil", "Свердловская наб., 9", 59.959543, 30.386134),
    ("luk-35", "Лукойл", "lukoil", "пер. Декабристов, 9", 59.955652, 30.248016),
    ("luk-36", "Лукойл", "lukoil", "Кожевенная линия, 43", 59.926177, 30.240547),
    ("luk-37", "Лукойл", "lukoil", "Железноводская ул., 1А", 59.952888, 30.261813),
    ("luk-38", "Лукойл", "lukoil", "пр. Добролюбова, 20к6", 59.949766, 30.288419),
    ("luk-39", "Лукойл", "lukoil", "пр. Стачек, 81", 59.862671, 30.258750),
    ("luk-40", "Лукойл", "lukoil", "пр. Маршала Жукова, 46", 59.847479, 30.215492),
    ("luk-41", "Лукойл", "lukoil", "Шотландская ул., 14", 59.909060, 30.239514),
    ("luk-42", "Лукойл АЗС №97", "lukoil", "пр. Маршала Жукова, 49", 59.847529, 30.213864),
    ("luk-43", "Лукойл", "lukoil", "пр. Народного Ополчения, 80", 59.825132, 30.149002),
    ("luk-44", "Лукойл", "lukoil", "пр. Маршала Жукова, 40", 59.848307, 30.221242),
    ("luk-45", "Лукойл АЗС №51", "lukoil", "наб. Обводного канала, 34", 59.913402, 30.358675),
    ("luk-46", "Лукойл", "lukoil", "Черниговская ул., 25", 59.903346, 30.336769),
    ("luk-47", "Лукойл", "lukoil", "Гусарская ул., 10А (Пушкин)", 59.699441, 30.393921),
    ("luk-48", "Лукойл", "lukoil", "Московское ш., 9Б", 59.802240, 30.399289),
    ("luk-49", "Лукойл АЗС №78131", "lukoil", "тер. Московская Славянка, 15к2 (Пушкин)", 59.747912, 30.493923),
    ("luk-50", "Лукойл", "lukoil", "Заводской пр., 3 (Колпино)", 59.730835, 30.576902),
    ("luk-51", "Лукойл", "lukoil", "М-10, 674 км (Тельмана)", 59.709537, 30.570725),
    ("luk-52", "Лукойл", "lukoil", "Малая Балканская ул., 21", 59.831281, 30.381297),
    ("tat-9", "Татнефть (бывш. Neste)", "tatneft", "Всеволожск, Дорога Жизни, 41К-064, 9Б", 60.031549, 30.626072),
    ("tat-13", "Татнефть", "tatneft", "Большая Пороховская ул., 53", 59.952774, 30.435649),
    ("teb-5", "Teboil", "teboil", "41К-079", 59.870586, 30.533967),
    ("teb-6", "Teboil", "teboil", "КАД (А-118), около Новосаратовки", 59.945373, 30.520425),
    ("teb-7", "Teboil", "teboil", "Боровая ул., 43 лит. А", 59.914263, 30.343536),
]
STATION_BY_ID = {s[0]: s for s in STATIONS}


def _load_custom_to_cache():
    try:
        for row in get_custom_stations():
            sid, name, net, addr, lat, lng = row[0], row[1], row[2], row[3], row[4], row[5]
            STATION_BY_ID[sid] = (sid, name, net, addr, lat, lng)
    except Exception as e:
        log.warning(f"Не удалось загрузить custom_stations: {e}")


def get_station(sid):
    if sid in STATION_BY_ID:
        return STATION_BY_ID[sid]
    try:
        conn = db()
        row = conn.execute(
            "SELECT id, name, net, addr, lat, lng FROM custom_stations WHERE id=?", (sid,)
        ).fetchone()
        conn.close()
        if row:
            STATION_BY_ID[sid] = row
            return row
    except Exception:
        pass
    return None


def station_exists(sid):
    return get_station(sid) is not None


DISTRICT_CENTROIDS = [
    ("Адмиралтейский", 59.9250, 30.3130),("Василеостровский", 59.9450, 30.2530),
    ("Выборгский", 60.0380, 30.3150),("Калининский", 59.9880, 30.3960),
    ("Кировский", 59.8680, 30.2460),("Колпинский", 59.7410, 30.5880),
    ("Красногвардейский", 59.9550, 30.4340),("Красносельский", 59.8360, 30.1000),
    ("Московский", 59.8600, 30.3190),("Невский", 59.8770, 30.4430),
    ("Петроградский", 59.9620, 30.3080),("Приморский", 60.0020, 30.2710),
    ("Пушкинский", 59.7160, 30.4090),("Фрунзенский", 59.8570, 30.3730),
    ("Центральный", 59.9320, 30.3600),("Всеволожский район", 60.0200, 30.6300),
]


def district_for_station(lat, lng):
    best_name, best_dist = None, None
    for name, clat, clng in DISTRICT_CENTROIDS:
        d = (lat - clat) ** 2 + (lng - clng) ** 2
        if best_dist is None or d < best_dist:
            best_dist, best_name = d, name
    return best_name


def get_user_top_district(user_id):
    conn = db()
    rows = conn.execute(
        "SELECT station_id, COUNT(*) AS c FROM feed WHERE user_id=? GROUP BY station_id", (user_id,)
    ).fetchall()
    conn.close()
    counter = Counter()
    for station_id, c in rows:
        s = get_station(station_id)
        if not s:
            continue
        counter[district_for_station(s[4], s[5])] += c
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            station_id TEXT NOT NULL, fuel TEXT NOT NULL, status TEXT NOT NULL,
            ts INTEGER NOT NULL, user_id INTEGER, username TEXT,
            PRIMARY KEY (station_id, fuel)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
            station_id TEXT NOT NULL, fuel TEXT NOT NULL, status TEXT NOT NULL,
            user_id INTEGER, username TEXT
        )
    """)
    for table in ("reports", "feed"):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN username TEXT")
        except sqlite3.OperationalError:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS issue_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
            station_id TEXT, user_id INTEGER NOT NULL, username TEXT,
            text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            user_id INTEGER PRIMARY KEY, username TEXT,
            total_points INTEGER NOT NULL DEFAULT 0, last_report_date TEXT,
            streak_days INTEGER NOT NULL DEFAULT 0, streak3_awarded INTEGER NOT NULL DEFAULT 0,
            streak7_awarded INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS points_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            ts INTEGER NOT NULL, points INTEGER NOT NULL, reason TEXT NOT NULL, station_id TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE points_log ADD COLUMN station_id TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom_stations (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, net TEXT NOT NULL, addr TEXT,
            lat REAL NOT NULL, lng REAL NOT NULL,
            created_ts INTEGER NOT NULL, created_by INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, station_id TEXT NOT NULL,
            file_path TEXT NOT NULL, user_id INTEGER, username TEXT, ts INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_station ON photos(station_id, ts DESC)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, net TEXT NOT NULL,
            lat REAL NOT NULL, lng REAL NOT NULL, fuels TEXT, user_id INTEGER NOT NULL,
            username TEXT, status TEXT NOT NULL DEFAULT 'pending', created_ts INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_ts ON reports(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feed_ts ON feed(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feed_station_fuel ON feed(station_id, fuel, ts DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_log_user_station ON points_log(user_id, station_id, ts)")
    return conn


def get_state(key):
    conn = db()
    row = conn.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def set_state(key, value):
    conn = db()
    conn.execute(
        "INSERT INTO bot_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def save_report(station_id, fuel, status, user_id, username=None):
    now = int(time.time())
    conn = db()
    conn.execute(
        "INSERT INTO reports (station_id, fuel, status, ts, user_id, username) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(station_id, fuel) DO UPDATE SET status=excluded.status, ts=excluded.ts, "
        "user_id=excluded.user_id, username=excluded.username",
        (station_id, fuel, status, now, user_id, username),
    )
    conn.execute(
        "INSERT INTO feed (ts, station_id, fuel, status, user_id, username) VALUES (?,?,?,?,?,?)",
        (now, station_id, fuel, status, user_id, username),
    )
    conn.commit()
    conn.close()


def get_station_reports(station_id):
    conn = db()
    rows = conn.execute("SELECT fuel, status, ts FROM reports WHERE station_id=?", (station_id,)).fetchall()
    conn.close()
    return {fuel: (status, ts) for fuel, status, ts in rows}


def get_recent_feed(limit=12):
    conn = db()
    rows = conn.execute(
        "SELECT ts, station_id, fuel, status, username FROM feed ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def save_issue(station_id, user_id, username, text):
    now = int(time.time())
    conn = db()
    cur = conn.execute(
        "INSERT INTO issue_reports (ts, station_id, user_id, username, text, status) VALUES (?,?,?,?,?,'open')",
        (now, station_id, user_id, username, text),
    )
    conn.commit()
    issue_id = cur.lastrowid
    conn.close()
    return issue_id


def get_issue(issue_id):
    conn = db()
    row = conn.execute(
        "SELECT id, station_id, user_id, username, text, status FROM issue_reports WHERE id=?", (issue_id,)
    ).fetchone()
    conn.close()
    return row


def mark_issue_fixed(issue_id):
    conn = db()
    conn.execute("UPDATE issue_reports SET status='fixed' WHERE id=?", (issue_id,))
    conn.commit()
    conn.close()


def user_fixed_issues_count(user_id):
    conn = db()
    row = conn.execute(
        "SELECT COUNT(*) FROM issue_reports WHERE user_id=? AND status='fixed'", (user_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_user_stats(user_id):
    conn = db()
    total = conn.execute("SELECT COUNT(*) FROM feed WHERE user_id=?", (user_id,)).fetchone()[0]
    stations = conn.execute("SELECT COUNT(DISTINCT station_id) FROM feed WHERE user_id=?", (user_id,)).fetchone()[0]
    conn.close()
    return {"total": total, "stations": stations}


def _ensure_user_row(conn, user_id, username):
    conn.execute(
        "INSERT INTO user_points (user_id, username) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
        (user_id, username),
    )


def award_points(user_id, username, points, reason, station_id=None):
    if user_id == 0 or points == 0:
        return
    now = int(time.time())
    conn = db()
    _ensure_user_row(conn, user_id, username)
    conn.execute("UPDATE user_points SET total_points = total_points + ? WHERE user_id=?", (points, user_id))
    conn.execute(
        "INSERT INTO points_log (user_id, ts, points, reason, station_id) VALUES (?,?,?,?,?)",
        (user_id, now, points, reason, station_id),
    )
    conn.commit()
    conn.close()


POINTS_COOLDOWN_SECONDS = 3600


def can_award_station_points(user_id, station_id):
    if user_id == 0:
        return True
    hour_ago = int(time.time()) - POINTS_COOLDOWN_SECONDS
    conn = db()
    row = conn.execute(
        "SELECT COUNT(*) FROM points_log WHERE user_id=? AND station_id=? "
        "AND reason IN ('report', 'scout_bonus') AND ts > ?",
        (user_id, station_id, hour_ago),
    ).fetchone()
    conn.close()
    return row[0] == 0


def record_daily_activity(user_id, username):
    if user_id == 0:
        return
    today = time.strftime("%Y-%m-%d", time.gmtime())
    yesterday = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    conn = db()
    _ensure_user_row(conn, user_id, username)
    row = conn.execute(
        "SELECT last_report_date, streak_days, streak3_awarded, streak7_awarded FROM user_points WHERE user_id=?",
        (user_id,),
    ).fetchone()
    last_date, streak_days, s3, s7 = row if row else (None, 0, 0, 0)
    if last_date == today:
        conn.close()
        return
    if last_date == yesterday:
        streak_days += 1
    else:
        streak_days = 1
        s3 = 0
        s7 = 0
    conn.execute(
        "UPDATE user_points SET last_report_date=?, streak_days=? WHERE user_id=?",
        (today, streak_days, user_id),
    )
    conn.commit()
    conn.close()
    if streak_days >= 3 and not s3:
        award_points(user_id, username, POINTS_STREAK_3, "streak_3")
        conn = db()
        conn.execute("UPDATE user_points SET streak3_awarded=1 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
    if streak_days >= 7 and not s7:
        award_points(user_id, username, POINTS_STREAK_7, "streak_7")
        conn = db()
        conn.execute("UPDATE user_points SET streak7_awarded=1 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()


def is_scouting_report(station_id):
    rep = get_station_reports(station_id)
    for key, _label in FUELS:
        if key in rep:
            _status, ts = rep[key]
            if not is_stale(ts):
                return False
    return True


def get_points_profile(user_id):
    conn = db()
    row = conn.execute("SELECT total_points, streak_days FROM user_points WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    total_points, streak_days = row if row else (0, 0)
    return {"total_points": total_points, "streak_days": streak_days, "rank": get_rank(total_points)}


def get_weekly_leaderboard(limit=10):
    week_ago = int(time.time()) - 7 * 86400
    conn = db()
    rows = conn.execute("""
        SELECT p.user_id, COALESCE(u.username, 'id' || p.user_id) AS username, SUM(p.points) AS week_points
        FROM points_log p LEFT JOIN user_points u ON u.user_id = p.user_id
        WHERE p.ts > ? GROUP BY p.user_id ORDER BY week_points DESC LIMIT ?
    """, (week_ago, limit)).fetchall()
    conn.close()
    return rows


def get_weekly_position(user_id):
    week_ago = int(time.time()) - 7 * 86400
    conn = db()
    rows = conn.execute("""
        SELECT user_id, SUM(points) AS week_points FROM points_log
        WHERE ts > ? GROUP BY user_id ORDER BY week_points DESC
    """, (week_ago,)).fetchall()
    conn.close()
    for i, (uid, pts) in enumerate(rows, start=1):
        if uid == user_id:
            return i, pts
    return None, 0


def time_ago(ts):
    diff = max(0, int(time.time()) - ts)
    minutes = diff // 60
    if minutes < 1:
        return "только что"
    if minutes < 60:
        return f"{minutes} мин назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч назад"
    days = hours // 24
    return f"{days} дн назад"


def is_stale(ts):
    return (int(time.time()) - ts) > 8 * 3600


def add_custom_station(name, net, addr, lat, lng, user_id):
    now = int(time.time())
    station_id = f"custom-{now}"
    conn = db()
    conn.execute(
        "INSERT INTO custom_stations (id, name, net, addr, lat, lng, created_ts, created_by) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (station_id, name, net, addr, lat, lng, now, user_id),
    )
    conn.commit()
    conn.close()
    STATION_BY_ID[station_id] = (station_id, name, net, addr, lat, lng)
    return station_id


def get_custom_stations():
    conn = db()
    rows = conn.execute(
        "SELECT id, name, net, addr, lat, lng, created_ts, created_by FROM custom_stations ORDER BY created_ts ASC"
    ).fetchall()
    conn.close()
    return rows


def delete_custom_station(station_id):
    if not station_id.startswith("custom-"):
        return
    conn = db()
    conn.execute("DELETE FROM custom_stations WHERE id=?", (station_id,))
    conn.execute("DELETE FROM reports WHERE station_id=?", (station_id,))
    conn.execute("DELETE FROM feed WHERE station_id=?", (station_id,))
    conn.commit()
    conn.close()
    STATION_BY_ID.pop(station_id, None)


def save_photo(station_id, file_path, user_id, username=None):
    conn = db()
    conn.execute(
        "INSERT INTO photos (station_id, file_path, user_id, username, ts) VALUES (?,?,?,?,?)",
        (station_id, file_path, user_id, username, int(time.time())),
    )
    conn.commit()
    conn.close()


def save_pending_station(name, net, lat, lng, fuels_json, user_id, username):
    conn = db()
    cur = conn.execute(
        "INSERT INTO pending_stations (name, net, lat, lng, fuels, user_id, username, created_ts) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (name, net, lat, lng, fuels_json, user_id, username, int(time.time())),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def get_pending_station(pid):
    conn = db()
    row = conn.execute(
        "SELECT id, name, net, lat, lng, fuels, user_id, username, status FROM pending_stations WHERE id=?",
        (pid,),
    ).fetchone()
    conn.close()
    return row


def approve_pending_station(pid, admin_id):
    row = get_pending_station(pid)
    if not row:
        return None
    _, name, net, lat, lng, fuels_json, user_id, username, status = row
    if status != "pending":
        return None
    station_id = add_custom_station(name, net, "Добавлено пользователем", lat, lng, admin_id)
    try:
        fuels = json.loads(fuels_json or "{}")
    except Exception:
        fuels = {}
    for fuel_key, status_val in fuels.items():
        if fuel_key in dict(FUELS) and status_val in dict(STATUSES):
            save_report(station_id, fuel_key, status_val, user_id, username)
    conn = db()
    conn.execute("UPDATE pending_stations SET status='approved' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return station_id


def reject_pending_station(pid):
    conn = db()
    conn.execute("UPDATE pending_stations SET status='rejected' WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def kb_main():
    rows = [[InlineKeyboardButton(text=f"{v['dot']} {v['label']}", callback_data=f"net:{k}")]
            for k, v in NETWORKS.items()]
    rows.append([InlineKeyboardButton(text="🕓 Последние отчёты", callback_data="feed")])
    rows.append([InlineKeyboardButton(text="⚠️ Сообщить об ошибке в боте", callback_data="err:")])
    if MAP_URL:
        rows.append([InlineKeyboardButton(text="🗺 Открыть карту", web_app=WebAppInfo(url=MAP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_stations(net_key):
    stations = [s for s in STATIONS if s[2] == net_key]
    rows = [[InlineKeyboardButton(text=s[3], callback_data=f"stn:{s[0]}")] for s in stations]
    rows.append([InlineKeyboardButton(text="⬅️ Назад к сетям", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_station_card(station_id):
    rep = get_station_reports(station_id)
    rows = [[InlineKeyboardButton(text=f"Сообщить: {label}", callback_data=f"fuel:{station_id}:{key}")]
            for key, label in FUELS]
    flag_row = []
    for fkey, flabel in STATION_FLAGS:
        is_on = fkey in rep and rep[fkey][0] == "on" and not is_stale(rep[fkey][1])
        mark = "✅ " if is_on else ""
        flag_row.append(InlineKeyboardButton(text=f"{mark}{flabel}", callback_data=f"flag:{station_id}:{fkey}"))
    rows.append(flag_row)
    s = get_station(station_id)
    net_key = s[2] if s else "gpn"
    rows.append([InlineKeyboardButton(text="⚠️ Неточность в данных станции", callback_data=f"err:{station_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ К списку станций", callback_data=f"net:{net_key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_status_pick(station_id, fuel_key):
    # В UI статуса показываем только Есть / Нет. Старые отчёты с low продолжают храниться.
    fuel_label = FUEL_SHORT.get(fuel_key, fuel_key)
    rows = [
        [InlineKeyboardButton(text=f"{fuel_label} · ✅ Есть", callback_data=f"rep:{station_id}:{fuel_key}:ok")],
        [InlineKeyboardButton(text=f"{fuel_label} · ❌ Нет",  callback_data=f"rep:{station_id}:{fuel_key}:none")],
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"stn:{station_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def station_card_text(station_id):
    s = get_station(station_id)
    if not s:
        return "Станция не найдена."
    _, name, _net_key, addr, _, _ = s
    rep = get_station_reports(station_id)
    lines = [f"⛽ <b>{name}</b>", f"📍 {addr}", ""]
    for key, label in FUELS:
        if key in rep:
            status, ts = rep[key]
            mark = STATUS_LABEL[status]
            stale = " (устарело, обновите)" if is_stale(ts) else f" · {time_ago(ts)}"
            lines.append(f"{label}: {mark}{stale}")
        else:
            lines.append(f"{label}: ⚪ нет данных")
    flag_bits = []
    for fkey, flabel in STATION_FLAGS:
        if fkey in rep and rep[fkey][0] == "on" and not is_stale(rep[fkey][1]):
            flag_bits.append(f"{flabel} · {time_ago(rep[fkey][1])}")
    if flag_bits:
        lines.append("")
        lines.append(" · ".join(flag_bits))
    lines.append("")
    lines.append("Нажмите кнопку ниже, чтобы сообщить свежий статус.")
    return "\n".join(lines)


def kb_brand_pick():
    rows = []
    line = []
    for k, v in NETWORKS.items():
        line.append(InlineKeyboardButton(text=f"{v['dot']} {v['label']}", callback_data=f"addb:{k}"))
        if len(line) == 2:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="addcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_fuel_pick(fuels_state):
    """Диалог выбора топлива для новой станции. Каждая строка — одно топливо:
    [92]  [Есть] [Нет]  — с явной меткой вида топлива в кнопках.
    """
    rows = []
    for key, label in FUELS:
        short = FUEL_SHORT.get(key, label)
        cur = fuels_state.get(key)
        ok_text = f"{short} · ✅ Есть" if cur != "ok" else f"{short} · ✅ Есть ✓"
        none_text = f"{short} · ❌ Нет" if cur != "none" else f"{short} · ❌ Нет ✓"
        rows.append([
            InlineKeyboardButton(text=ok_text, callback_data=f"addf:{key}:ok"),
            InlineKeyboardButton(text=none_text, callback_data=f"addf:{key}:none"),
        ])
    rows.append([InlineKeyboardButton(text="💾 Сохранить заявку", callback_data="addsave")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="addcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


dp = Dispatcher()
pending_issue = {}
pending_add = {}


@dp.message(CommandStart())
async def on_start(message, command: CommandObject):
    payload = command.args
    if payload:
        if payload.startswith("err_"):
            station_id = payload[len("err_"):].replace("_", "-")
            if station_exists(station_id):
                pending_issue[message.from_user.id] = station_id
                s = get_station(station_id)
                await message.answer(
                    f"Опишите, что не так на станции <b>{s[1]}</b> — одним сообщением, и я передам автору бота."
                )
                return
        elif payload.startswith("missing_"):
            parts = payload[len("missing_"):].split("_")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                lat = int(parts[0]) / 1e6
                lng = int(parts[1]) / 1e6
                pending_issue[message.from_user.id] = f"missing:{lat:.6f}:{lng:.6f}"
                await message.answer(
                    "Напишите одним сообщением адрес и сеть заправки, которой не хватает на карте "
                    "(координаты я уже приложу автоматически)."
                )
                return
        elif payload.startswith("add_"):
            parts = payload[len("add_"):].split("_")
            if len(parts) == 2 and all(p.isdigit() or (p.startswith("-") and p[1:].isdigit()) for p in parts):
                lat = int(parts[0]) / 1e6
                lng = int(parts[1]) / 1e6
                pending_add[message.from_user.id] = {"lat": lat, "lng": lng, "net": None, "fuels": {}}
                await message.answer(
                    f"📍 Добавляем АЗС по координатам <b>{lat:.5f}, {lng:.5f}</b>\n\nВыберите бренд:",
                    reply_markup=kb_brand_pick(),
                )
                return

    text = (
        "⛽ <b>АЗС СПб — топливо в реале</b>\n"
        "Данные вносят водители, это открытое сообщество, а не официальный источник.\n\n"
        "Выберите сеть, чтобы посмотреть станции или сообщить свежий статус.\n\n"
        "За отчёты начисляются баллы и звания — посмотреть свой прогресс: /профиль, "
        "топ недели: /топ."
    )
    await message.answer(text, reply_markup=kb_main())


@dp.callback_query(F.data.startswith("addb:"))
async def cb_add_brand(cq: CallbackQuery):
    user_id = cq.from_user.id
    if user_id not in pending_add:
        await cq.answer("Сессия истекла, откройте карту заново.", show_alert=True)
        return
    net_key = cq.data.split(":", 1)[1]
    if net_key not in NETWORKS:
        await cq.answer("Неизвестный бренд.")
        return
    pending_add[user_id]["net"] = net_key
    label = NETWORKS[net_key]["label"]
    try:
        await cq.message.edit_text(
            f"⛽ Бренд: <b>{label}</b>\n\nТеперь отметьте наличие топлива (можно пропустить):",
            reply_markup=kb_fuel_pick(pending_add[user_id]["fuels"]),
        )
    except TelegramBadRequest:
        pass
    await cq.answer()


@dp.callback_query(F.data.startswith("addf:"))
async def cb_add_fuel(cq: CallbackQuery):
    user_id = cq.from_user.id
    if user_id not in pending_add:
        await cq.answer("Сессия истекла.", show_alert=True)
        return
    _, fuel_key, status = cq.data.split(":")
    if fuel_key not in dict(FUELS) or status not in ("ok", "none"):
        await cq.answer("Неверные данные.")
        return
    fuels = pending_add[user_id]["fuels"]
    if fuels.get(fuel_key) == status:
        fuels.pop(fuel_key, None)
    else:
        fuels[fuel_key] = status
    try:
        await cq.message.edit_reply_markup(reply_markup=kb_fuel_pick(fuels))
    except TelegramBadRequest:
        pass
    await cq.answer("Отмечено")


@dp.callback_query(F.data == "addsave")
async def cb_add_save(cq: CallbackQuery):
    user_id = cq.from_user.id
    if user_id not in pending_add:
        await cq.answer("Сессия истекла.", show_alert=True)
        return
    data = pending_add.pop(user_id)
    if not data.get("net"):
        await cq.answer("Сначала выберите бренд.", show_alert=True)
        return
    net_key = data["net"]
    name = NETWORKS[net_key]["label"]
    username = display_name(cq.from_user)
    pid = save_pending_station(
        name=name, net=net_key, lat=data["lat"], lng=data["lng"],
        fuels_json=json.dumps(data["fuels"]), user_id=user_id, username=username,
    )
    try:
        await cq.message.edit_text(
            "✅ Заявка отправлена на модерацию. Как только автор проверит — точка появится на карте."
        )
    except TelegramBadRequest:
        pass
    await cq.answer("Отправлено")
    if ADMIN_ID:
        fuels_lines = []
        for key, label in FUELS:
            if data["fuels"].get(key):
                fuels_lines.append(f"{FUEL_SHORT.get(key, label)}: {STATUS_LABEL[data['fuels'][key]]}")
        fuels_text = "\n".join(fuels_lines) if fuels_lines else "не указано"
        admin_text = (
            f"🆕 <b>Заявка на новую АЗС #{pid}</b>\n\n"
            f"Бренд: <b>{name}</b>\n"
            f"Координаты: <code>{data['lat']:.6f}, {data['lng']:.6f}</code>\n"
            f"Топливо:\n{fuels_text}\n\n"
            f"От: {format_display(username)} (id {user_id})"
        )
        mod_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"appmod:{pid}:approve"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"appmod:{pid}:reject"),
        ]])
        try:
            await cq.bot.send_message(ADMIN_ID, admin_text, reply_markup=mod_kb)
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data == "addcancel")
async def cb_add_cancel(cq: CallbackQuery):
    pending_add.pop(cq.from_user.id, None)
    try:
        await cq.message.edit_text("Отменено.")
    except TelegramBadRequest:
        pass
    await cq.answer()


@dp.callback_query(F.data.startswith("appmod:"))
async def cb_moderate(cq: CallbackQuery):
    if not ADMIN_ID or cq.from_user.id != ADMIN_ID:
        await cq.answer("Только автор бота может модерировать.", show_alert=True)
        return
    _, pid_str, action = cq.data.split(":")
    pid = int(pid_str)
    if action == "approve":
        station_id = approve_pending_station(pid, cq.from_user.id)
        if not station_id:
            await cq.answer("Заявка уже обработана.")
            return
        await cq.answer("Одобрено")
        try:
            await cq.message.edit_text(cq.message.text + f"\n\n✅ Одобрено (id {station_id})")
        except TelegramBadRequest:
            pass
        row = get_pending_station(pid)
        if row and row[6]:
            try:
                await cq.bot.send_message(row[6], "🎉 Ваша заявка на новую АЗС одобрена и уже на карте!")
            except TelegramBadRequest:
                pass
    elif action == "reject":
        reject_pending_station(pid)
        await cq.answer("Отклонено")
        try:
            await cq.message.edit_text(cq.message.text + "\n\n❌ Отклонено")
        except TelegramBadRequest:
            pass
        row = get_pending_station(pid)
        if row and row[6]:
            try:
                await cq.bot.send_message(row[6], "Заявка на новую АЗС отклонена модератором.")
            except TelegramBadRequest:
                pass


@dp.message(Command("recent"))
async def on_recent_cmd(message: Message):
    await message.answer(feed_text(), reply_markup=kb_main())


@dp.message(Command("вклад"))
async def on_contribution_cmd(message: Message):
    fixed = user_fixed_issues_count(message.from_user.id)
    stats = get_user_stats(message.from_user.id)
    lines = ["📊 <b>Ваш вклад</b>", ""]
    if stats["total"] == 0:
        lines.append("Пока нет отчётов. Отметьте статус на любой станции — это займёт 10 секунд!")
    else:
        lines.append(f"Отчётов о топливе: <b>{stats['total']}</b>")
        lines.append(f"Станций: <b>{stats['stations']}</b>")
    if fixed:
        lines.append(f"Подтверждённых исправлений: <b>{fixed}</b> 🙌")
    lines.append("")
    lines.append("Баллы и звание — команда /профиль")
    await message.answer("\n".join(lines), reply_markup=kb_main())


@dp.message(Command("профиль"))
async def on_profile_cmd(message: Message):
    user_id = message.from_user.id
    name = display_name(message.from_user)
    conn = db()
    _ensure_user_row(conn, user_id, name)
    conn.commit()
    conn.close()
    profile = get_points_profile(user_id)
    stats = get_user_stats(user_id)
    fixed = user_fixed_issues_count(user_id)
    week_place, week_points = get_weekly_position(user_id)
    rank_display = profile["rank"]
    if profile["rank"] == "Смотритель района":
        top_district = get_user_top_district(user_id)
        if top_district:
            rank_display = f"Смотритель района «{top_district}»"
    lines = [f"🏅 <b>Профиль {format_display(name)}</b>", ""]
    lines.append(f"Баллы: <b>{profile['total_points']}</b>")
    lines.append(f"Звание: <b>{rank_display}</b>")
    nxt = next_rank_info(profile["total_points"])
    if nxt:
        need, label = nxt
        lines.append(f"До звания «{label}»: {need} баллов")
    if profile["streak_days"] >= 2:
        lines.append(f"🔥 Стрик: {profile['streak_days']} дн. подряд")
    lines.append("")
    lines.append(f"Отчётов всего: {stats['total']} (по {stats['stations']} станциям)")
    if week_place:
        lines.append(f"Место в топе за неделю: <b>#{week_place}</b> ({week_points} баллов)")
    if fixed:
        lines.append(f"Подтверждённых исправлений: {fixed} 🙌")
    await message.answer("\n".join(lines), reply_markup=kb_main())


@dp.message(Command("топ"))
async def on_top_cmd(message: Message):
    rows = get_weekly_leaderboard(10)
    if not rows:
        await message.answer("Пока нет отчётов за неделю.", reply_markup=kb_main())
        return
    text = format_leaderboard_text(rows, title="🏆 <b>Топ-10 недели</b>")
    await message.answer(text, reply_markup=kb_main())


@dp.message(Command("правила"))
async def on_rules_cmd(message: Message):
    text = (
        "📋 <b>Правила и конфиденциальность</b>\n\n"
        "Это открытый некоммерческий проект, не связанный с сетями АЗС официально.\n\n"
        "<b>Что мы храним:</b> Telegram ID, username (если задан), отметки о топливе "
        "и сообщения о неточностях. Точные координаты — только если вы сами сообщаете "
        "об отсутствующей станции.\n\n"
        "<b>Кому передаются данные:</b> никому. Нет рекламы, нет продажи третьим лицам.\n\n"
        "<b>Ответственность:</b> данные вносят сами водители, точность не гарантируется."
    )
    await message.answer(text, reply_markup=kb_main())


def feed_text():
    rows = get_recent_feed(12)
    if not rows:
        return "Пока нет отчётов. Станьте первым — выберите станцию через /start."
    fuel_label = {k: v for k, v in FUELS}
    lines = ["🕓 <b>Последние отчёты сообщества</b>", ""]
    for ts, station_id, fuel, status, username in rows:
        s = get_station(station_id)
        if not s:
            continue
        who = f" · {format_display(username)}" if username else ""
        lines.append(f"{s[1]}, {s[3]} — {fuel_label.get(fuel, fuel)} {STATUS_LABEL[status]} · {time_ago(ts)}{who}")
    return "\n".join(lines)


@dp.callback_query(F.data == "menu")
async def cb_menu(cq: CallbackQuery):
    await safe_edit(cq, "Выберите сеть:", kb_main())
    await cq.answer()


@dp.callback_query(F.data == "feed")
async def cb_feed(cq: CallbackQuery):
    await safe_edit(cq, feed_text(), kb_main())
    await cq.answer()


@dp.callback_query(F.data.startswith("net:"))
async def cb_net(cq: CallbackQuery):
    net_key = cq.data.split(":", 1)[1]
    label = NETWORKS[net_key]["label"]
    await safe_edit(cq, f"Станции сети <b>{label}</b>:", kb_stations(net_key))
    await cq.answer()


@dp.callback_query(F.data.startswith("stn:"))
async def cb_station(cq: CallbackQuery):
    station_id = cq.data.split(":", 1)[1]
    await safe_edit(cq, station_card_text(station_id), kb_station_card(station_id))
    await cq.answer()


@dp.callback_query(F.data.startswith("fuel:"))
async def cb_fuel(cq: CallbackQuery):
    _, station_id, fuel_key = cq.data.split(":")
    fuel_label = dict(FUELS)[fuel_key]
    await safe_edit(cq, f"Какой статус у <b>{fuel_label}</b>?", kb_status_pick(station_id, fuel_key))
    await cq.answer()


@dp.callback_query(F.data.startswith("flag:"))
async def cb_flag(cq: CallbackQuery):
    _, station_id, flag_key = cq.data.split(":")
    rep = get_station_reports(station_id)
    currently_on = flag_key in rep and rep[flag_key][0] == "on" and not is_stale(rep[flag_key][1])
    new_status = "off" if currently_on else "on"
    save_report(station_id, flag_key, new_status, cq.from_user.id, display_name(cq.from_user))
    await safe_edit(cq, station_card_text(station_id), kb_station_card(station_id))
    label = STATION_FLAG_LABEL[flag_key]
    await cq.answer(f"{label}: {'отмечено' if new_status == 'on' else 'снято'}")


@dp.callback_query(F.data.startswith("rep:"))
async def cb_report(cq: CallbackQuery):
    _, station_id, fuel_key, status = cq.data.split(":")
    scouting = is_scouting_report(station_id)
    allow_points = can_award_station_points(cq.from_user.id, station_id)
    name = display_name(cq.from_user)
    save_report(station_id, fuel_key, status, cq.from_user.id, name)
    points_earned = 0
    if allow_points:
        points_earned = POINTS_REPORT + (POINTS_SCOUT_BONUS if scouting else 0)
        award_points(cq.from_user.id, name, POINTS_REPORT, "report", station_id)
        if scouting:
            award_points(cq.from_user.id, name, POINTS_SCOUT_BONUS, "scout_bonus", station_id)
    record_daily_activity(cq.from_user.id, name)
    await safe_edit(cq, station_card_text(station_id), kb_station_card(station_id))
    if allow_points:
        bonus_note = " (+5 за разведку 🔭)" if scouting else ""
        await cq.answer(f"Спасибо! +{points_earned} баллов{bonus_note}. Статус: {STATUS_LABEL[status]}")
    else:
        await cq.answer(f"Статус обновлён: {STATUS_LABEL[status]}. Баллы уже начислялись в этот час.")


async def safe_edit(cq, text, markup):
    try:
        await cq.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass


@dp.callback_query(F.data.startswith("err:"))
async def cb_report_issue(cq: CallbackQuery):
    station_id = cq.data.split(":", 1)[1]
    pending_issue[cq.from_user.id] = station_id
    if station_id:
        s = get_station(station_id)
        name = s[1] if s else station_id
        prompt = f"Опишите, что не так на станции <b>{name}</b> — одним сообщением."
    else:
        prompt = "Опишите, что не так в боте или на карте — одним сообщением."
    await cq.message.answer(prompt)
    await cq.answer()


@dp.message(F.text & ~F.text.startswith("/"))
async def on_free_text(message: Message):
    user_id = message.from_user.id
    if user_id not in pending_issue:
        return
    raw = pending_issue.pop(user_id)
    username = message.from_user.username or message.from_user.full_name
    if raw.startswith("missing:"):
        coords = raw[len("missing:"):]
        station_id = None
        text_for_db = f"[Нет на карте · координаты {coords}] {message.text}"
    else:
        station_id = raw
        text_for_db = message.text
    issue_id = save_issue(station_id, user_id, username, text_for_db)
    await message.answer("Спасибо! Заявка передана, разберёмся как можно быстрее. 🙌")
    if ADMIN_ID:
        station_line = ""
        if station_id:
            s = get_station(station_id)
            if s:
                station_line = f"\nСтанция: {s[1]}, {s[3]} (id: {station_id})"
        safe_username = format_display(username)
        safe_text = html.escape(text_for_db)
        admin_text = (
            f"⚠️ Новое сообщение о неточности #{issue_id}\n"
            f"От: {safe_username} (id {user_id}){station_line}\n\n{safe_text}"
        )
        fix_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Исправлено", callback_data=f"fix:{issue_id}")
        ]])
        try:
            await message.bot.send_message(ADMIN_ID, admin_text, reply_markup=fix_kb)
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data.startswith("fix:"))
async def cb_mark_fixed(cq: CallbackQuery):
    if not ADMIN_ID or cq.from_user.id != ADMIN_ID:
        await cq.answer("Только автор бота может отмечать исправления.", show_alert=True)
        return
    issue_id = int(cq.data.split(":", 1)[1])
    issue = get_issue(issue_id)
    if not issue:
        await cq.answer("Заявка не найдена.")
        return
    mark_issue_fixed(issue_id)
    reporter_id = issue[2]
    try:
        await cq.message.bot.send_message(
            reporter_id,
            "Ваше сообщение о неточности разобрали и исправили — спасибо! 🙌"
        )
    except TelegramBadRequest:
        pass
    await cq.message.edit_text(cq.message.text + "\n\n✅ Отмечено как исправлено.", parse_mode=None)
    await cq.answer("Отмечено, автор уведомлён.")


def format_leaderboard_text(rows, title="🏆 <b>Топ разведчиков недели</b>"):
    medals = ["🥇", "🥈", "🥉"]
    lines = [title, ""]
    for i, (uid, username, pts) in enumerate(rows):
        mark = medals[i] if i < 3 else f"{i + 1}."
        display = format_display(username, uid)
        lines.append(f"{mark} {display} — {pts} баллов")
    lines.append("")
    lines.append("Спасибо всем! Присоединяйтесь: @naidibenzin_bot")
    return "\n".join(lines)


async def post_weekly_leaderboard(bot: Bot):
    if not CHANNEL_ID:
        return False
    rows = get_weekly_leaderboard(10)
    if not rows:
        log.info("Автопост топа недели пропущен: за неделю нет отчётов.")
        return False
    text = format_leaderboard_text(rows)
    await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
    log.info("Топ недели опубликован в канал %s", CHANNEL_ID)
    return True


async def weekly_leaderboard_task(bot: Bot):
    if not CHANNEL_ID:
        log.info("CHANNEL_ID не задан — автопост топа недели отключён.")
        return
    POST_HOUR_UTC = 6
    POLL_INTERVAL = 600
    while True:
        now = datetime.utcnow()
        if now.weekday() == 0 and now.hour >= POST_HOUR_UTC:
            today_str = now.strftime("%Y-%m-%d")
            if get_state("last_weekly_post_date") != today_str:
                sent = False
                try:
                    sent = await post_weekly_leaderboard(bot)
                except Exception:
                    log.exception("Ошибка при публикации топа недели")
                if sent:
                    set_state("last_weekly_post_date", today_str)
        await asyncio.sleep(POLL_INTERVAL)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN.")
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    _load_custom_to_cache()

    class IPv4OnlySession(AiohttpSession):
        async def _create_session(self):
            connector = TCPConnector(family=socket.AF_INET)
            return ClientSession(connector=connector, timeout=ClientTimeout(total=60))

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
        session=IPv4OnlySession()
    )

    await bot.delete_webhook(drop_pending_updates=True, request_timeout=15)

    import webserver
    await webserver.run_webserver(PORT)

    asyncio.create_task(weekly_leaderboard_task(bot))

    await dp.start_polling(bot, request_timeout=15)


if __name__ == "__main__":
    asyncio.run(main())