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

STATION_FLAGS = [("flag_queue_1","🚗"),("flag_queue_2","🚗🚗"),("flag_queue_3","🚗🚗🚗"),("flag_delivery","🚛 Бензовоз на АЗС"),("flag_limit","⛔ Лимит на литры")]
STATION_FLAG_LABEL = {k: v for k, v in STATION_FLAGS}

POINTS_REPORT = 2
POINTS_SCOUT_BONUS = 5
POINTS_STREAK_3 = 10
POINTS_STREAK_7 = 30
POINTS_SHARE = 10        # за первый репост в сутки
POINTS_ADD_STATION = 50  # за одобренную новую АЗС
POINTS_FIX_ISSUE = 20    # за исправленную неточность

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
    ("nes-1", "Татнефть", "tatneft", "Средний пр. В.О., 91к2", 59.9352, 30.2502),
    ("nes-2", "Татнефть", "tatneft", "ул. Партизана Германа, 4", 59.8429, 30.1766),
    ("nes-3", "Татнефть", "tatneft", "Московский пр., 102", 59.8967, 30.3197),
    ("nes-4", "Татнефть", "tatneft", "пр. Испытателей, 2а", 60.0017, 30.3041),
    ("nes-5", "Татнефть", "tatneft", "пр. Косыгина, 20", 59.9456, 30.48),
    ("nes-6", "Татнефть", "tatneft", "Северный пр., 32", 60.0327, 30.3627),
    ("nes-7", "Татнефть", "tatneft", "Софийская ул., 127к1", 59.8882, 30.3809),
    ("nes-8", "Татнефть", "tatneft", "Выборгское ш., 21", 60.0578, 30.3083),
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
    ("nes-9", "Татнефть", "tatneft", "Малоохтинская наб., 59", 59.930608, 30.400265),
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
    ("tat-7", "Татнефть", "tatneft", "пр. Маршала Блюхера, 2к7", 59.9866, 30.3622),
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
    ("tat-9", "Татнефть", "tatneft", "Всеволожск, Дорога Жизни, 41К-064, 9Б", 60.031549, 30.626072),
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


# ==== Точные границы районов (GeoJSON) ====
_GEO_DISTRICTS = []  # [(name, [(ring, [lng,lat]...)...]), ...]

def _point_in_ring(x, y, ring):
    """Ray casting. ring — список [lng,lat]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside

def _point_in_multipolygon(x, y, coords):
    """coords: MultiPolygon -> [[[ring],[hole]...],...]"""
    for poly in coords:
        if not poly: continue
        outer = poly[0]
        if not _point_in_ring(x, y, outer):
            continue
        # проверяем дырки
        in_hole = False
        for hole in poly[1:]:
            if _point_in_ring(x, y, hole):
                in_hole = True; break
        if not in_hole:
            return True
    return False

def _load_geo_districts():
    global _GEO_DISTRICTS
    if _GEO_DISTRICTS:
        return
    import os as _os
    base = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "webapp", "geo")
    for fname in ("spb_districts.geojson", "lo_districts.geojson"):
        fp = _os.path.join(base, fname)
        if not _os.path.exists(fp):
            log.warning("geo file missing: %s", fp)
            continue
        try:
            import json as _json
            with io.open(fp, encoding="utf-8") as f:
                gj = _json.load(f)
            for ft in gj.get("features", []):
                name = (ft.get("properties") or {}).get("name")
                geom = ft.get("geometry") or {}
                if not name or geom.get("type") != "MultiPolygon":
                    continue
                _GEO_DISTRICTS.append((name, geom["coordinates"]))
            log.info("geo districts loaded: %d", len(_GEO_DISTRICTS))
        except Exception:
            log.exception("Failed to load %s", fp)


def district_for_station(lat, lng):
    """Точный район по полигонам, fallback — ближайший центроид."""
    try:
        _load_geo_districts()
    except Exception:
        pass
    if _GEO_DISTRICTS:
        for name, coords in _GEO_DISTRICTS:
            try:
                if _point_in_multipolygon(lng, lat, coords):
                    return name
            except Exception:
                continue
    # Fallback: старый способ
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


def init_db():
    """Один раз при старте процесса: создаёт схему, настраивает WAL.
    Не вызывать после старта — каждая операция на сетевом диске дорогая."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA mmap_size = 134217728")
        conn.execute("PRAGMA cache_size = -8000")
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
            CREATE TABLE IF NOT EXISTS user_fraud_state (
                user_id INTEGER PRIMARY KEY,
                minute_window_start INTEGER NOT NULL DEFAULT 0,
                minute_count INTEGER NOT NULL DEFAULT 0,
                hour_window_start INTEGER NOT NULL DEFAULT 0,
                hour_count INTEGER NOT NULL DEFAULT 0,
                violations_count INTEGER NOT NULL DEFAULT 0,
                flagged_until INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics_counters (
                day TEXT NOT NULL, key TEXT NOT NULL, value INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (day, key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics_users_daily (
                day TEXT NOT NULL, user_id INTEGER NOT NULL,
                PRIMARY KEY (day, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_stations (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, net TEXT NOT NULL, addr TEXT,
                lat REAL NOT NULL, lng REAL NOT NULL,
                created_ts INTEGER NOT NULL, created_by INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS station_overrides (
                id TEXT PRIMARY KEY,
                name TEXT, net TEXT, addr TEXT, lat REAL, lng REAL,
                deleted INTEGER NOT NULL DEFAULT 0,
                updated_ts INTEGER NOT NULL
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dps_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lat REAL NOT NULL, lng REAL NOT NULL,
                user_id INTEGER, username TEXT,
                ts INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dps_ts ON dps_reports(ts)")
        try:
            conn.execute("ALTER TABLE dps_reports ADD COLUMN kind TEXT NOT NULL DEFAULT 'dps'")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        log.info("init_db: схема БД готова, WAL активен")
    finally:
        conn.close()


def db():
    """Быстрое соединение — только PRAGMA, без DDL. Схема создаётся init_db() при старте."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -8000")
    conn.execute("PRAGMA mmap_size = 134217728")
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

def check_user_rate(user_id):
    """Проверяет лимиты отчётов для user_id.
    Возвращает (allowed: bool, reason: str|None)."""
    if not user_id:
        return True, None
    now = int(time.time())
    conn = db()
    try:
        row = conn.execute(
            "SELECT minute_window_start, minute_count, hour_window_start, hour_count, violations_count, flagged_until FROM user_fraud_state WHERE user_id=?",
            (user_id,)
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO user_fraud_state (user_id, minute_window_start, minute_count, hour_window_start, hour_count) VALUES (?,?,?,?,?)",
                (user_id, now, 1, now, 1)
            )
            conn.commit()
            return True, None

        mws, mc, hws, hc, vc, fu = row

        # Теневой бан — игнорируем
        if fu and fu > now:
            return False, "flagged"

        if now - mws >= 60:
            mws = now
            mc = 1
        else:
            mc += 1

        if now - hws >= 3600:
            hws = now
            hc = 1
        else:
            hc += 1

        violation = None
        if mc > 30:
            violation = "too_many_per_minute"
        elif hc > 150:
            violation = "too_many_per_hour"

        if violation:
            vc += 1
            flagged_until = now + 86400 if vc >= 3 else fu
            conn.execute(
                "UPDATE user_fraud_state SET minute_window_start=?, minute_count=?, hour_window_start=?, hour_count=?, violations_count=?, flagged_until=? WHERE user_id=?",
                (mws, mc, hws, hc, vc, flagged_until, user_id)
            )
            conn.commit()
            try:
                log.warning("rate-limit: user=%s reason=%s mc=%s hc=%s vc=%s", user_id, violation, mc, hc, vc)
            except Exception:
                pass
            return False, violation

        conn.execute(
            "UPDATE user_fraud_state SET minute_window_start=?, minute_count=?, hour_window_start=?, hour_count=? WHERE user_id=?",
            (mws, mc, hws, hc, user_id)
        )
        conn.commit()
        return True, None
    finally:
        conn.close()


def check_user_consensus(user_id, lookback_min=60, min_conflicts=5):
    """Проверяет, не идёт ли user_id против большинства.
    Возвращает (suspicious: bool, conflicts: int).

    Логика: за последние lookback_min минут собрать отчёты пользователя
    по топливным парам. Для каждой пары посмотреть, что ставили другие
    за последние 24 часа. Если у пользователя 'none', а большинство
    (>=60%) 'ok' — это конфликт. Если конфликтов >= min_conflicts —
    подозрительно."""
    if not user_id:
        return False, 0
    now = int(time.time())
    since = now - lookback_min * 60
    day_ago = now - 86400
    conn = db()
    try:
        mine = conn.execute(
            "SELECT station_id, fuel, status FROM feed "
            "WHERE ts > ? AND user_id = ? AND fuel IN ('f92','f95','f98','dt')",
            (since, user_id)
        ).fetchall()
        if len(mine) < min_conflicts:
            return False, 0

        conflicts = 0
        for sid, fuel, my_status in mine:
            if my_status != 'none':
                continue
            others = conn.execute(
                "SELECT status, COUNT(*) FROM feed "
                "WHERE ts > ? AND station_id = ? AND fuel = ? AND user_id != ? AND user_id > 0 "
                "GROUP BY status",
                (day_ago, sid, fuel, user_id)
            ).fetchall()
            total = sum(c for _, c in others)
            if total < 3:
                continue
            ok_cnt = sum(c for st, c in others if st in ('ok', 'low'))
            if ok_cnt / total >= 0.6:
                conflicts += 1
        return (conflicts >= min_conflicts), conflicts
    except Exception:
        try:
            log.exception("check_user_consensus failed")
        except Exception:
            pass
        return False, 0
    finally:
        conn.close()


def save_report(station_id, fuel, status, user_id, username=None, shadow=False):
    now = int(time.time())
    conn = db()
    if not shadow:
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
    try:
        if fuel in dict(FUELS):
            inc_metric("reports")
        if user_id:
            track_user_today(user_id)
    except Exception:
        log.exception("metrics failed in save_report")


def get_station_reports(station_id):
    conn = db()
    rows = conn.execute("SELECT fuel, status, ts FROM reports WHERE station_id=?", (station_id,)).fetchall()
    conn.close()
    return {fuel: (status, ts) for fuel, status, ts in rows}


def get_delivery_history(station_id, days=14):
    """Возвращает историю завоза топлива: список {ts, fuel} и агрегат.
    Завоз = переход 'none' → 'ok' или 'low' в feed для топлива."""
    if not station_id:
        return {"events": [], "typical_hour": None, "avg_interval_days": None}
    since = int(time.time()) - days * 86400
    conn = db()
    try:
        rows = conn.execute(
            "SELECT ts, fuel, status FROM feed "
            "WHERE station_id = ? AND ts > ? AND fuel IN ('f92','f95','f98','dt') "
            "ORDER BY fuel, ts ASC",
            (station_id, since)
        ).fetchall()
    finally:
        conn.close()

    # Идём по каждому топливу отдельно: prev_status → current
    prev = {}  # fuel -> status
    events = []
    for ts, fuel, status in rows:
        p_status = prev.get(fuel)
        if p_status == 'none' and status in ('ok', 'low'):
            events.append({"ts": int(ts), "fuel": fuel})
        prev[fuel] = status

    events.sort(key=lambda e: e["ts"])
    # Отфильтровываем близкие (в пределах 30 минут) — одно событие
    filtered = []
    for e in events:
        if filtered and e["ts"] - filtered[-1]["ts"] < 1800:
            continue
        filtered.append(e)

    # Средний час завоза (в МСК = UTC+3)
    typical_hour = None
    if filtered:
        hours = []
        for e in filtered:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            h = (_dt.fromtimestamp(e["ts"], _tz.utc) + _td(hours=3)).hour
            hours.append(h)
        typical_hour = round(sum(hours) / len(hours))

    # Средний интервал (в днях)
    avg_interval = None
    if len(filtered) >= 2:
        deltas = [(filtered[i+1]["ts"] - filtered[i]["ts"]) for i in range(len(filtered)-1)]
        avg_days = (sum(deltas) / len(deltas)) / 86400
        avg_interval = round(avg_days, 1)

    return {
        "events": filtered[-10:],  # последние 10 для фронта
        "typical_hour": typical_hour,
        "avg_interval_days": avg_interval,
    }


def get_recent_feed(limit=12):
    conn = db()
    rows = conn.execute(
        "SELECT ts, station_id, fuel, status, username FROM feed ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def save_dps_report(lat, lng, user_id, username=None, kind="dps"):
    if kind not in ("dps", "camera"):
        kind = "dps"
    now = int(time.time())
    conn = db()
    cur = conn.execute(
        "INSERT INTO dps_reports (lat, lng, user_id, username, ts, kind) VALUES (?,?,?,?,?,?)",
        (float(lat), float(lng), user_id or 0, username, now, kind),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_active_dps_reports(dps_ttl=3600, camera_ttl=10800):
    """ДПС — 1 час, камеры — 3 часа. Возвращает id, lat, lng, ts, kind, user_id."""
    now = int(time.time())
    dps_cutoff = now - dps_ttl
    cam_cutoff = now - camera_ttl
    conn = db()
    rows = conn.execute(
        "SELECT id, lat, lng, ts, kind, COALESCE(user_id, 0) FROM dps_reports "
        "WHERE ts > (CASE WHEN kind='camera' THEN ? ELSE ? END) "
        "ORDER BY ts DESC LIMIT 200",
        (cam_cutoff, dps_cutoff),
    ).fetchall()
    conn.close()
    return rows


def delete_dps_report(report_id, user_id, is_admin=False):
    """Удаляет метку. Автор — всегда, чужой — только админ.
    Возвращает True если удалено."""
    conn = db()
    row = conn.execute("SELECT user_id FROM dps_reports WHERE id=?", (int(report_id),)).fetchone()
    if not row:
        conn.close()
        return False
    owner = row[0] or 0
    if not is_admin and owner != int(user_id):
        conn.close()
        return False
    conn.execute("DELETE FROM dps_reports WHERE id=?", (int(report_id),))
    conn.commit()
    conn.close()
    return True


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


def get_my_stations(user_id, limit=5, min_reports=3):
    """Возвращает список станций, где user_id чаще всего отмечался.
    Только станции с минимум min_reports отчётами от этого пользователя."""
    if not user_id:
        return []
    conn = db()
    try:
        rows = conn.execute(
            "SELECT station_id, COUNT(*) AS cnt, MAX(ts) AS last_ts FROM feed "
            "WHERE user_id = ? AND fuel IN ('f92','f95','f98','dt') "
            "GROUP BY station_id HAVING cnt >= ? "
            "ORDER BY cnt DESC LIMIT ?",
            (user_id, min_reports, limit)
        ).fetchall()
    finally:
        conn.close()
    result = []
    for sid, cnt, last_ts in rows:
        st = STATION_BY_ID.get(sid)
        if not st:
            continue
        result.append({
            "id": sid,
            "name": st[1],
            "net": st[2],
            "addr": st[3] or "—",
            "cnt": cnt,
            "last_ts": int(last_ts or 0),
        })
    return result


def is_my_station(user_id, station_id):
    """True, если station_id в списке 'моих' для этого пользователя.
    Используется для x2 бонуса."""
    if not user_id or not station_id:
        return False
    conn = db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM feed WHERE user_id = ? AND station_id = ? AND fuel IN ('f92','f95','f98','dt')",
            (user_id, station_id)
        ).fetchone()
        cnt = row[0] if row else 0
    finally:
        conn.close()
    return cnt >= 3


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

def can_award_share_today(user_id):
    """True, если юзер ещё не получал баллы за репост сегодня."""
    if not user_id:
        return False
    today = time.strftime("%Y-%m-%d", time.gmtime())
    conn = db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM points_log WHERE user_id=? AND reason='share' "
            "AND ts > ?",
            (user_id, int(time.time()) - 86400),
        ).fetchone()
        return row[0] == 0
    finally:
        conn.close()


def award_share_points(user_id, username):
    """Начисляет баллы за репост, если сегодня ещё не начисляли."""
    if not can_award_share_today(user_id):
        return 0
    award_points(user_id, username, POINTS_SHARE, "share")
    return POINTS_SHARE

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


FLAG_DELIVERY_TTL = 30 * 60


def is_flag_stale(fkey, ts):
    if fkey == "flag_delivery":
        return (int(time.time()) - ts) > FLAG_DELIVERY_TTL
    return is_stale(ts)
def inc_metric(key, delta=1):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    conn = db()
    try:
        conn.execute(
            "INSERT INTO metrics_counters (day, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(day, key) DO UPDATE SET value = value + excluded.value",
            (today, key, delta),
        )
        conn.commit()
    finally:
        conn.close()


def track_user_today(user_id):
    if not user_id:
        return
    today = time.strftime("%Y-%m-%d", time.gmtime())
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO metrics_users_daily (day, user_id) VALUES (?, ?)",
            (today, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_metrics(days=7):
    today_ts = int(time.time())
    days_list = [
        time.strftime("%Y-%m-%d", time.gmtime(today_ts - i * 86400))
        for i in range(days - 1, -1, -1)
    ]
    placeholders = ",".join("?" * len(days_list))
    conn = db()
    try:
        counters = {}
        for day, key, value in conn.execute(
            f"SELECT day, key, value FROM metrics_counters WHERE day IN ({placeholders})",
            days_list,
        ):
            counters.setdefault(day, {})[key] = value
        users_count = {}
        for day, cnt in conn.execute(
            f"SELECT day, COUNT(*) FROM metrics_users_daily WHERE day IN ({placeholders}) GROUP BY day",
            days_list,
        ):
            users_count[day] = cnt
    finally:
        conn.close()
    result = []
    for d in days_list:
        c = counters.get(d, {})
        result.append((d, c.get("api_hits", 0), c.get("reports", 0), users_count.get(d, 0)))
    return result

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


def upsert_station_override(station_id, name=None, net=None, addr=None, lat=None, lng=None, deleted=0):
    import time as _t
    conn = db()
    now = int(_t.time())
    cur = conn.execute("SELECT id FROM station_overrides WHERE id=?", (station_id,)).fetchone()
    if cur:
        conn.execute(
            "UPDATE station_overrides SET name=COALESCE(?,name), net=COALESCE(?,net), "
            "addr=COALESCE(?,addr), lat=COALESCE(?,lat), lng=COALESCE(?,lng), "
            "deleted=?, updated_ts=? WHERE id=?",
            (name, net, addr, lat, lng, int(deleted), now, station_id),
        )
    else:
        conn.execute(
            "INSERT INTO station_overrides (id, name, net, addr, lat, lng, deleted, updated_ts) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (station_id, name, net, addr, lat, lng, int(deleted), now),
        )
    conn.commit()
    conn.close()


def get_station_overrides():
    conn = db()
    rows = conn.execute("SELECT id, name, net, addr, lat, lng, deleted FROM station_overrides").fetchall()
    conn.close()
    return rows
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
    rows = []
    if MAP_URL:
        rows.append([InlineKeyboardButton(text="🗺 ОТКРЫТЬ КАРТУ — свежие данные", web_app=WebAppInfo(url=MAP_URL), style="primary")])
    rows.append([InlineKeyboardButton(text="🕓 Последние отчёты", callback_data="feed")])
    rows.append([
        InlineKeyboardButton(text="📢 Канал — топ дня и алерты", url="https://t.me/naidibenzin"),
        InlineKeyboardButton(text="📢 Канал MAX", url="https://max.ru/channel_naidibenzin"),
    ])
    rows.append([InlineKeyboardButton(text="🏠 Мои станции", callback_data="my_st:")])
    rows.append([InlineKeyboardButton(text="☕ Поддержать проект", callback_data="donate:")])
    rows.append([InlineKeyboardButton(text="⚠️ Сообщить об ошибке в боте", callback_data="err:")])
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
        is_on = fkey in rep and rep[fkey][0] == "on" and not is_flag_stale(fkey, rep[fkey][1])
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
        if payload == "daily_top":
            try:
                inc_metric("ref_daily_top")
            except Exception:
                log.exception("metric ref_daily_top failed")
        elif payload.startswith("err_"):
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
        "⛽ <b>ГДЕ БЕНЗИН!?</b>\n"
        "<i>От водителя водителю</i>\n\n"
        "Навигатор знает, где заправка.\n"
        "Мы знаем, есть ли там топливо сейчас.\n\n"
        "1. Открой карту\n"
        "2. Тапни АЗС\n"
        "3. Ответь «Есть» или «Нет»\n\n"
        "10 секунд — и следующий водитель знает.\n\n"
        "<b>Баллы</b>\n"
        "• Отчёт +2\n"
        "• Разведка +5\n"
        "• Новая АЗС +50\n"
        "• Правка +20\n"
        "• Репост +10\n\n"
        "<b>В Telegram больше</b>\n"
        "• Точная свежесть (5 мин)\n"
        "• Фото стелл с ценами\n"
        "• ДПС и камеры онлайн\n"
        "• Голосовой ввод\n"
        "• Баллы и топ недели\n\n"
        "<b>Канал @naidibenzin</b>\n"
        "Топ дня в 20:00, топ недели, алерты.\n"
        "Карта работает и без подписки."
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
        _map_base = (MAP_URL or "https://azs-spb-bot-syntetika.amvera.io/map").rstrip("/")
        _pin_link = f"{_map_base}?pin={data['lat']:.6f},{data['lng']:.6f}&brand={net_key}"
        mod_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📍 Открыть на карте", web_app=WebAppInfo(url=_pin_link))],
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"appmod:{pid}:approve"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"appmod:{pid}:reject"),
            ],
        ])
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

        # Начисляем +50 автору заявки
        row = get_pending_station(pid)
        if row and row[6]:
            author_id = row[6]
            author_name = row[7] or None
            try:
                award_points(author_id, author_name, POINTS_ADD_STATION, "add_station", station_id)
                await cq.bot.send_message(
                    author_id,
                    f"🎉 Ваша заявка на новую АЗС одобрена и уже на карте!\n"
                    f"Начислено <b>+{POINTS_ADD_STATION} баллов</b>."
                )
            except TelegramBadRequest:
                pass

        await cq.answer("Одобрено")
        try:
            await cq.message.edit_text(cq.message.text + f"\n\n✅ Одобрено (id {station_id})")
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
    text, ids = feed_text()
    await message.answer(text, reply_markup=feed_kb(ids))


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


def render_profile_text(user_id, name=None, is_self=False):
    """Общий рендер профиля. Возвращает текст (HTML)."""
    if name is None:
        conn0 = db()
        try:
            row = conn0.execute(
                "SELECT COALESCE(username, 'id' || user_id) FROM user_points WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            name = row[0] if row else ("id" + str(user_id))
        finally:
            conn0.close()
    profile = get_points_profile(user_id)
    stats = get_user_stats(user_id)
    fixed = user_fixed_issues_count(user_id)
    week_place, week_points = get_weekly_position(user_id)
    rank_display = profile["rank"]
    if profile["rank"] == "Смотритель района":
        top_district = get_user_top_district(user_id)
        if top_district:
            rank_display = f"Смотритель района «{top_district}»"
    head = "🏅 <b>Профиль " + format_display(name) + "</b>"
    lines = [head, ""]
    lines.append(f"Баллы: <b>{profile['total_points']}</b>")
    lines.append(f"Звание: <b>{rank_display}</b>")
    if is_self:
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
    return "\n".join(lines)


@dp.message(Command("профиль"))
async def on_profile_cmd(message: Message):
    user_id = message.from_user.id
    name = display_name(message.from_user)
    conn = db()
    _ensure_user_row(conn, user_id, name)
    conn.commit()
    conn.close()
    text = render_profile_text(user_id, name=name, is_self=True)
    await message.answer(text, reply_markup=kb_main())


@dp.message(Command("топ"))
async def on_top_cmd(message: Message):
    rows = get_weekly_leaderboard(10)
    if not rows:
        await message.answer("Пока нет отчётов за неделю.", reply_markup=kb_main())
        return
    text = format_leaderboard_text(rows, title="🏆 <b>Топ-10 недели</b>")
    kb_rows = []
    for i, (uid, uname, pts) in enumerate(rows):
        mark = ["🥇", "🥈", "🥉"][i] if i < 3 else str(i + 1) + "."
        label = mark + " " + format_display(uname, uid)[:28] + " · " + str(pts)
        kb_rows.append([InlineKeyboardButton(text=label, callback_data=f"prof:{uid}")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@dp.callback_query(F.data.startswith("prof:"))
async def cb_view_profile(cq: CallbackQuery):
    try:
        target_uid = int(cq.data.split(":", 1)[1])
    except Exception:
        await cq.answer("Некорректная ссылка")
        return
    text = render_profile_text(target_uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к топу", callback_data="top:back")]
    ])
    try:
        await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await cq.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await cq.answer()


@dp.callback_query(F.data == "top:back")
async def cb_top_back(cq: CallbackQuery):
    rows = get_weekly_leaderboard(10)
    if not rows:
        await cq.answer("Нет данных")
        return
    text = format_leaderboard_text(rows, title="🏆 <b>Топ-10 недели</b>")
    kb_rows = []
    for i, (uid, uname, pts) in enumerate(rows):
        mark = ["🥇", "🥈", "🥉"][i] if i < 3 else str(i + 1) + "."
        label = mark + " " + format_display(uname, uid)[:28] + " · " + str(pts)
        kb_rows.append([InlineKeyboardButton(text=label, callback_data=f"prof:{uid}")])
    try:
        await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    except Exception:
        pass
    await cq.answer()

@dp.message(Command("daily_now"))
async def on_daily_now_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    try:
        ok = await post_daily_leaderboard(message.bot)
    except Exception as e:
        await message.answer("Ошибка: " + str(e))
        return
    if ok:
        await message.answer("Топ дня опубликован в канал.")
    else:
        await message.answer("Не опубликовано (нет CHANNEL_ID или ошибка).")


@dp.message(Command("сети", "networks"))
async def on_networks_cmd(message: Message):
    try:
        stats, total_all = get_network_weekly_stats()
    except Exception:
        await message.answer("Не удалось получить статистику.")
        return
    text = format_network_report(stats, total_all)
    if not text:
        await message.answer("Пока нет отчётов за неделю.", reply_markup=kb_main())
        return
    await message.answer(text, reply_markup=kb_main())


@dp.message(Command("netreport_now"))
async def on_netreport_now_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    try:
        ok = await post_network_report(message.bot)
    except Exception as e:
        await message.answer("Ошибка: " + str(e))
        return
    if ok:
        await message.answer("Отчёт по сетям опубликован в канал.")
    else:
        await message.answer("Не опубликовано (нет данных или CHANNEL_ID).")


@dp.message(Command("сети", "networks"))
async def on_networks_cmd(message: Message):
    try:
        stats, total_all = get_network_weekly_stats()
    except Exception:
        await message.answer("Не удалось получить статистику.")
        return
    text = format_network_report(stats, total_all)
    if not text:
        await message.answer("Пока нет отчётов за неделю.", reply_markup=kb_main())
        return
    await message.answer(text, reply_markup=kb_main())


@dp.message(Command("netreport_now"))
async def on_netreport_now_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    try:
        ok = await post_network_report(message.bot)
    except Exception as e:
        await message.answer("Ошибка: " + str(e))
        return
    if ok:
        await message.answer("Отчёт по сетям опубликован в канал.")
    else:
        await message.answer("Не опубликовано (нет данных или CHANNEL_ID).")


@dp.message(Command("мои", "my"))
async def on_my_stations_cmd(message: Message):
    user_id = message.from_user.id
    stations = get_my_stations(user_id, limit=5, min_reports=3)
    if not stations:
        await message.answer(
            "🏠 <b>Моих станций пока нет</b>\n\n"
            "Станция становится «твоей», когда ты отметил на ней "
            "минимум 3 раза. Обычно это заправки, где ты заправляешься "
            "чаще всего.\n\n"
            "За отчёт на «своей» станции — <b>х2 баллов</b>. "
            "Отмечай там, где бываешь регулярно.",
            reply_markup=kb_main()
        )
        return

    lines = ["🏠 <b>Мои станции</b>", ""]
    lines.append("За отчёт на этих станциях — <b>х2 баллов</b>.")
    lines.append("")
    medals = ["1.", "2.", "3.", "4.", "5."]
    for i, st in enumerate(stations):
        lines.append("<b>" + medals[i] + " " + st["name"] + "</b>")
        lines.append("   " + st["addr"])
        lines.append("   Твоих отчётов: <b>" + str(st["cnt"]) + "</b>")
        lines.append("")
    lines.append("Чем чаще отмечаешь здесь — тем свежее данные для тебя и соседей.")
    await message.answer("\n".join(lines), reply_markup=kb_main())


@dp.message(Command("проблема", "проблемы", "баг"))
async def on_problem_cmd(message: Message):
    pending_issue[message.from_user.id] = "__bot__"
    await message.answer(
        "Опишите проблему одним сообщением — отправлю автору бота.\n"
        "Если проблема на конкретной станции — укажите адрес или название."
    )


@dp.message(Command("дашборд", "dashboard"))
async def on_dashboard_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    now = int(time.time())
    d1 = now - 86400
    d7 = now - 7 * 86400
    conn = db()
    try:
        total_feed = conn.execute("SELECT COUNT(*) FROM feed").fetchone()[0]
        feed_24h = conn.execute("SELECT COUNT(*) FROM feed WHERE ts > ?", (d1,)).fetchone()[0]
        feed_7d = conn.execute("SELECT COUNT(*) FROM feed WHERE ts > ?", (d7,)).fetchone()[0]
        d14 = now - 14 * 86400
        feed_prev7d = conn.execute("SELECT COUNT(*) FROM feed WHERE ts > ? AND ts <= ?", (d14, d7)).fetchone()[0]
        users_prev7d = conn.execute("SELECT COUNT(DISTINCT user_id) FROM feed WHERE ts > ? AND ts <= ? AND user_id > 0", (d14, d7)).fetchone()[0]
        stations_prev7d = conn.execute("SELECT COUNT(DISTINCT station_id) FROM feed WHERE ts > ? AND ts <= ?", (d14, d7)).fetchone()[0]
        users_24h = conn.execute("SELECT COUNT(DISTINCT user_id) FROM feed WHERE ts > ? AND user_id > 0", (d1,)).fetchone()[0]
        users_7d = conn.execute("SELECT COUNT(DISTINCT user_id) FROM feed WHERE ts > ? AND user_id > 0", (d7,)).fetchone()[0]
        stations_24h = conn.execute("SELECT COUNT(DISTINCT station_id) FROM feed WHERE ts > ?", (d1,)).fetchone()[0]
        stations_7d = conn.execute("SELECT COUNT(DISTINCT station_id) FROM feed WHERE ts > ?", (d7,)).fetchone()[0]

        # ДПС/камеры
        dps_cutoff = now - 3600
        cam_cutoff = now - 10800
        dps_now = conn.execute("SELECT COUNT(*) FROM dps_reports WHERE kind='dps' AND ts > ?", (dps_cutoff,)).fetchone()[0]
        cam_now = conn.execute("SELECT COUNT(*) FROM dps_reports WHERE kind='camera' AND ts > ?", (cam_cutoff,)).fetchone()[0]
        dps_7d = conn.execute("SELECT COUNT(*) FROM dps_reports WHERE kind='dps' AND ts > ?", (d7,)).fetchone()[0]
        cam_7d = conn.execute("SELECT COUNT(*) FROM dps_reports WHERE kind='camera' AND ts > ?", (d7,)).fetchone()[0]

        # Заявки
        issues_open = conn.execute("SELECT COUNT(*) FROM issue_reports WHERE status='open'").fetchone()[0]
        issues_7d = conn.execute("SELECT COUNT(*) FROM issue_reports WHERE ts > ?", (d7,)).fetchone()[0]

        # Кастомные АЗС
        custom_total = conn.execute("SELECT COUNT(*) FROM custom_stations").fetchone()[0]
        custom_7d = conn.execute("SELECT COUNT(*) FROM custom_stations WHERE created_ts > ?", (d7,)).fetchone()[0]

        # Топ активных за 7д
        top_users = conn.execute(
            "SELECT user_id, COALESCE(username,'id'||user_id), COUNT(*) FROM feed "
            "WHERE ts > ? AND user_id > 0 GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 5",
            (d7,)
        ).fetchall()

        # Топливо по всей карте (свежие, не старше 24ч)
        fuel_agg = conn.execute(
            "SELECT fuel, "
            "SUM(CASE WHEN status IN ('ok','low') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status='none' THEN 1 ELSE 0 END) "
            "FROM reports WHERE ts > ? GROUP BY fuel", (d1,)
        ).fetchall()

        # По дням (7 дней, МСК)
        days_agg = conn.execute(
            "SELECT date(ts, 'unixepoch', '+3 hours') AS d, COUNT(*), "
            "COUNT(DISTINCT CASE WHEN user_id > 0 THEN user_id END) "
            "FROM feed WHERE ts > ? "
            "GROUP BY d ORDER BY d DESC LIMIT 7", (d7,)
        ).fetchall()

        # По районам за 7д
        district_stats = {}
        _dist_rows = conn.execute(
            "SELECT station_id, COUNT(*) FROM feed WHERE ts > ? GROUP BY station_id",
            (d7,)
        ).fetchall()
        for _sid, _cnt in _dist_rows:
            _st = STATION_BY_ID.get(_sid)
            if not _st:
                continue
            try:
                _dname = district_for_station(_st[4], _st[5])
            except Exception:
                _dname = None
            if not _dname:
                continue
            if _dname not in district_stats:
                district_stats[_dname] = {"reports": 0, "stations": set()}
            district_stats[_dname]["reports"] += _cnt
            district_stats[_dname]["stations"].add(_sid)

        # Размер БД (приблиз.)
        db_size = 0
        try:
            import os as _os
            db_size = _os.path.getsize(DB_PATH)
        except Exception:
            pass
    finally:
        conn.close()

    # Пользователи по сети за 7д
    net_agg = []
    try:
        stats, total_all = get_network_weekly_stats()
        top_nets = sorted(stats.items(), key=lambda kv: kv[1]["total"], reverse=True)[:5]
        for net, st in top_nets:
            label = NETWORKS.get(net, {}).get("label", net)
            pct = round(st["total"] / total_all * 100) if total_all else 0
            net_agg.append((label, st["total"], pct))
    except Exception:
        pass

    def _delta(cur, prev):
        if prev <= 0:
            return ("0%" if cur <= 0 else "\U0001F195")
        d = (cur - prev) / prev * 100
        sign = "+" if d >= 0 else ""
        return sign + str(round(d)) + "%"

    lines = ["\U0001F4CA <b>\u0414\u0430\u0448\u0431\u043e\u0440\u0434</b> \u00b7 \u043f\u0440\u043e\u0435\u043a\u0442 \u00ab\u0413\u0414\u0415 \u0411\u0415\u041d\u0417\u0418\u041d!?\u00bb", ""]
    lines.append("<b>\u041e\u0442\u0447\u0451\u0442\u044b</b>")
    lines.append("\u2022 \u0412\u0441\u0435\u0433\u043e: <b>" + str(total_feed) + "</b>")
    lines.append("\u2022 \u0417\u0430 24\u0447: <b>" + str(feed_24h) + "</b>")
    lines.append("\u2022 \u0417\u0430 7\u0434: <b>" + str(feed_7d) + "</b>")
    lines.append("")
    lines.append("<b>\u0410\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u044c</b>")
    lines.append("\u2022 \u0423\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445 \u0437\u0430 24\u0447: <b>" + str(users_24h) + "</b>")
    lines.append("\u2022 \u0423\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445 \u0437\u0430 7\u0434: <b>" + str(users_7d) + "</b>")
    lines.append("\u2022 \u0421\u0442\u0430\u043d\u0446\u0438\u0439 \u0437\u0430 24\u0447: <b>" + str(stations_24h) + "</b>")
    lines.append("\u2022 \u0421\u0442\u0430\u043d\u0446\u0438\u0439 \u0437\u0430 7\u0434: <b>" + str(stations_7d) + "</b>")
    lines.append("")
    lines.append("<b>\u041f\u0440\u043e\u0442\u0438\u0432 \u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0435\u0439 \u043d\u0435\u0434\u0435\u043b\u0438</b>")
    lines.append("\u2022 \u041e\u0442\u0447\u0451\u0442\u044b: <b>" + _delta(feed_7d, feed_prev7d) + "</b>")
    lines.append("\u2022 \u0423\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0435: <b>" + _delta(users_7d, users_prev7d) + "</b>")
    lines.append("\u2022 \u0421\u0442\u0430\u043d\u0446\u0438\u0438: <b>" + _delta(stations_7d, stations_prev7d) + "</b>")
    lines.append("")
    lines.append("<b>\U0001F4C5 \u041f\u043e \u0434\u043d\u044f\u043c</b>")
    for _d, _cnt, _ucnt in days_agg:
        try:
            _lbl = _d[8:10] + "." + _d[5:7]
        except Exception:
            _lbl = _d
        lines.append("\u2022 " + _lbl + ": <b>" + str(_cnt) + "</b> \u043e\u0442\u0447 \u00b7 " + str(_ucnt) + " \u044e\u0437")
    lines.append("")
    lines.append("<b>\u0422\u043e\u043f-5 \u0437\u0430 7\u0434</b>")
    medals = ["\U0001F947", "\U0001F948", "\U0001F949", "4.", "5."]
    for i, (uid, uname, cnt) in enumerate(top_users):
        mark = medals[i] if i < 3 else str(i+1) + "."
        name = uname if uname and not uname.startswith("id") else ("id" + str(uid))
        lines.append(mark + " " + str(name) + " \u2014 " + str(cnt))
    lines.append("")
    lines.append("<b>\u0421\u0435\u0442\u0438 \u0437\u0430 7\u0434</b>")
    for label, total, pct in net_agg:
        lines.append("\u2022 " + label + ": <b>" + str(pct) + "%</b> (" + str(total) + ")")
    lines.append("")
    lines.append("<b>\u0414\u041f\u0421 \u0438 \u043a\u0430\u043c\u0435\u0440\u044b</b>")
    lines.append("\u2022 \u0421\u0435\u0439\u0447\u0430\u0441 \u0414\u041f\u0421: <b>" + str(dps_now) + "</b> \u00b7 \u043a\u0430\u043c\u0435\u0440\u044b: <b>" + str(cam_now) + "</b>")
    lines.append("\u2022 \u0417\u0430 7\u0434 \u0414\u041f\u0421: <b>" + str(dps_7d) + "</b> \u00b7 \u043a\u0430\u043c\u0435\u0440\u044b: <b>" + str(cam_7d) + "</b>")
    lines.append("")
    lines.append("<b>\u0417\u0430\u044f\u0432\u043a\u0438</b>")
    lines.append("\u2022 \u041e\u0442\u043a\u0440\u044b\u0442\u044b\u0445: <b>" + str(issues_open) + "</b> \u00b7 \u0437\u0430 7\u0434: <b>" + str(issues_7d) + "</b>")
    lines.append("")
    lines.append("<b>\u041d\u043e\u0432\u044b\u0435 \u0410\u0417\u0421</b>")
    lines.append("\u2022 \u0412\u0441\u0435\u0433\u043e: <b>" + str(custom_total) + "</b> \u00b7 \u0437\u0430 7\u0434: <b>" + str(custom_7d) + "</b>")
    lines.append("")
    if district_stats:
        lines.append("<b>\U0001F5FA \u0420\u0430\u0439\u043e\u043d\u044b (\u0437\u0430 7\u0434)</b>")
        _top_dist = sorted(district_stats.items(), key=lambda kv: kv[1]["reports"], reverse=True)[:8]
        for _dn, _ds in _top_dist:
            lines.append("\u2022 " + _dn + ": <b>" + str(_ds["reports"]) + "</b> \u043e\u0442\u0447 \u00b7 " + str(len(_ds["stations"])) + " \u0410\u0417\u0421")
        lines.append("")
    if fuel_agg:
        lines.append("<b>\u0422\u043e\u043f\u043b\u0438\u0432\u043e (\u0437\u0430 24\u0447)</b>")
        for fk, ok_cnt, none_cnt in fuel_agg:
            fname = FUEL_SHORT.get(fk, fk)
            total_f = (ok_cnt or 0) + (none_cnt or 0)
            if total_f == 0:
                continue
            pct_ok = round((ok_cnt or 0) / total_f * 100)
            lines.append("\u2022 " + fname + ": <b>" + str(pct_ok) + "%</b> \u0435\u0441\u0442\u044c (" + str(ok_cnt) + "/" + str(total_f) + ")")
    if db_size:
        lines.append("")
        lines.append("\u2022 \u0411\u0414: " + str(round(db_size / 1024 / 1024, 1)) + " MB")
    await message.answer("\n".join(lines))


@dp.message(Command("районы", "districts"))
async def on_districts_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    now = int(time.time())
    d7 = now - 7 * 86400
    d1 = now - 86400
    conn = db()
    try:
        _dist_rows = conn.execute(
            "SELECT station_id, COUNT(*), MAX(ts) FROM feed WHERE ts > ? GROUP BY station_id",
            (d7,)
        ).fetchall()
    finally:
        conn.close()
    district_stats = {}
    for _sid, _cnt, _last in _dist_rows:
        _st = STATION_BY_ID.get(_sid)
        if not _st:
            continue
        try:
            _dname = district_for_station(_st[4], _st[5])
        except Exception:
            _dname = None
        if not _dname:
            continue
        if _dname not in district_stats:
            district_stats[_dname] = {"reports": 0, "stations": set(), "last": 0}
        district_stats[_dname]["reports"] += _cnt
        district_stats[_dname]["stations"].add(_sid)
        if _last and _last > district_stats[_dname]["last"]:
            district_stats[_dname]["last"] = _last
    if not district_stats:
        await message.answer("\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445 \u0437\u0430 7 \u0434\u043d\u0435\u0439.")
        return
    total_reports = sum(v["reports"] for v in district_stats.values())
    total_stations = sum(len(v["stations"]) for v in district_stats.values())
    lines = ["\U0001F5FA <b>\u0420\u0430\u0439\u043e\u043d\u044b \u00b7 \u0437\u0430 7 \u0434\u043d\u0435\u0439</b>", ""]
    lines.append("\u0412\u0441\u0435\u0433\u043e: <b>" + str(total_reports) + "</b> \u043e\u0442\u0447 \u043f\u043e <b>" + str(total_stations) + "</b> \u0410\u0417\u0421")
    lines.append("")
    ranked = sorted(district_stats.items(), key=lambda kv: kv[1]["reports"], reverse=True)
    medals = ["\U0001F947", "\U0001F948", "\U0001F949"]
    for i, (_dn, _ds) in enumerate(ranked):
        mark = medals[i] if i < 3 else str(i + 1) + "."
        lines.append(mark + " " + _dn + " \u2014 <b>" + str(_ds["reports"]) + "</b> \u043e\u0442\u0447 \u00b7 " + str(len(_ds["stations"])) + " \u0410\u0417\u0421")
    await message.answer("\n".join(lines))


def _quickchart_url(cfg, w=900, h=400, bkg="1A1D21"):
    import json as _json
    from urllib.parse import quote
    c = _json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))
    return "https://quickchart.io/chart?w=" + str(w) + "&h=" + str(h) + "&bkg=%23" + bkg + "&c=" + quote(c)


@dp.message(Command("графики", "charts"))
async def on_charts_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return

    now = int(time.time())
    d14 = now - 14 * 86400

    conn = db()
    try:
        rows = conn.execute(
            "SELECT date(ts, 'unixepoch') as d, COUNT(*) FROM feed "
            "WHERE ts > ? GROUP BY d ORDER BY d", (d14,)
        ).fetchall()
    finally:
        conn.close()
    by_day = {d: cnt for d, cnt in rows}
    labels = []
    values = []
    for i in range(13, -1, -1):
        day = time.strftime("%Y-%m-%d", time.gmtime(now - i * 86400))
        labels.append(day[5:])
        values.append(by_day.get(day, 0))

    line_cfg = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "Отчёты",
                "data": values,
                "borderColor": "#FFB000",
                "backgroundColor": "rgba(255,176,0,0.2)",
                "fill": True,
                "tension": 0.3,
                "pointRadius": 3,
                "pointBackgroundColor": "#FFB000",
                "borderWidth": 3
            }]
        },
        "options": {
            "plugins": {"legend": {"labels": {"color": "#E8E6E1"}}},
            "scales": {
                "x": {"ticks": {"color": "#8A8F98"}, "grid": {"color": "rgba(43,48,54,0.6)"}},
                "y": {"ticks": {"color": "#8A8F98"}, "grid": {"color": "rgba(43,48,54,0.6)"}, "beginAtZero": True}
            }
        }
    }

    d7 = now - 7 * 86400
    conn = db()
    try:
        top = conn.execute(
            "SELECT COALESCE(username,'id'||user_id) as n, COUNT(*) as c FROM feed "
            "WHERE ts > ? AND user_id > 0 GROUP BY user_id ORDER BY c DESC LIMIT 5",
            (d7,)
        ).fetchall()
    finally:
        conn.close()

    show_top = list(top)
    excluded_top = None
    if len(show_top) >= 2:
        first_c = show_top[0][1]
        second_c = show_top[1][1]
        if second_c > 0 and first_c / second_c >= 10:
            excluded_top = show_top[0]
            show_top = show_top[1:]

    bar_cfg = {
        "type": "horizontalBar",
        "data": {
            "labels": [n for n, _ in show_top] or ["—"],
            "datasets": [{
                "label": "Отчётов",
                "data": [c for _, c in show_top] or [0],
                "backgroundColor": "#FFB000",
                "borderRadius": 6
            }]
        },
        "options": {
            "plugins": {"legend": {"display": False}},
            "scales": {
                "x": {"ticks": {"color": "#E8E6E1", "font": {"size": 13}}, "grid": {"color": "rgba(43,48,54,0.6)"}, "beginAtZero": True},
                "y": {"ticks": {"color": "#E8E6E1", "font": {"size": 15, "weight": "bold"}}, "grid": {"display": False}}
            }
        }
    }

    net_labels = []
    net_values = []
    try:
        stats, total_all = get_network_weekly_stats()
        top_nets = sorted(stats.items(), key=lambda kv: kv[1]["total"], reverse=True)[:6]
        for net, st in top_nets:
            net_labels.append(NETWORKS.get(net, {}).get("label", net))
            net_values.append(st["total"])
    except Exception:
        pass

    palette = ["#FFB000", "#30D158", "#1E88E5", "#26C6DA", "#8A8F98", "#B975FF"]
    dough_cfg = {
        "type": "doughnut",
        "data": {
            "labels": net_labels or ["—"],
            "datasets": [{
                "data": net_values or [1],
                "backgroundColor": palette[:max(1, len(net_labels))],
                "borderColor": "#14171A",
                "borderWidth": 2
            }]
        },
        "options": {"plugins": {"legend": {"position": "right", "labels": {"color": "#E8E6E1"}}}}
    }

    await message.answer("📈 Графики")

    items = [
        ("📈 Отчёты по дням (14 дней)", line_cfg, 900, 400),
        ("🏆 Топ-5 за 7 дней" + (" (без №1: " + excluded_top[0] + " — " + str(excluded_top[1]) + ")" if excluded_top else ""), bar_cfg, 900, 400),
        ("📊 Сети за 7 дней", dough_cfg, 800, 500),
    ]
    for title, cfg, w, h in items:
        try:
            url = _quickchart_url(cfg, w=w, h=h)
            await message.answer_photo(photo=url, caption=title)
        except Exception as e:
            try:
                await message.answer(title + "\nНе удалось: " + str(e)[:200])
            except Exception:
                pass


def get_trends_report():
    """Аналитика за 7 дней: дефицит по сетям и топливу, волны бензовозов, свежесть."""
    now = int(time.time())
    d1 = now - 86400
    d7 = now - 7 * 86400
    conn = db()
    try:
        # 1) Все отчёты по топливу за 7 дней (исключаем флаги)
        rows = conn.execute(
            "SELECT station_id, fuel, status FROM feed "
            "WHERE ts > ? AND fuel IN ('f92','f95','f98','dt')",
            (d7,)
        ).fetchall()
        # 2) Бензовозы за 24ч
        benz = conn.execute(
            "SELECT station_id FROM feed WHERE ts > ? AND fuel='flag_delivery' AND status IN ('on','true','1')",
            (d1,)
        ).fetchall()
        # 3) Свежесть: последний отчёт по каждой станции
        fresh = conn.execute(
            "SELECT station_id, MAX(ts) FROM reports WHERE fuel IN ('f92','f95','f98','dt') GROUP BY station_id"
        ).fetchall()
    finally:
        conn.close()

    # Сети
    net_total = {}
    net_none = {}
    for sid, fuel, status in rows:
        st = STATION_BY_ID.get(sid)
        if not st:
            continue
        net = st[2] if st[2] in NETWORKS else "other"
        net_total[net] = net_total.get(net, 0) + 1
        if status == "none":
            net_none[net] = net_none.get(net, 0) + 1

    net_deficit = []
    for net, total in net_total.items():
        if total < 5:
            continue
        pct = net_none.get(net, 0) / total * 100
        net_deficit.append((net, pct, total))
    net_deficit.sort(key=lambda x: x[1], reverse=True)

    # Топливо
    fuel_total = {}
    fuel_ok = {}
    for sid, fuel, status in rows:
        fuel_total[fuel] = fuel_total.get(fuel, 0) + 1
        if status in ("ok", "low"):
            fuel_ok[fuel] = fuel_ok.get(fuel, 0) + 1

    fuel_stats = []
    for fk in ("f92", "f95", "f98", "dt"):
        total = fuel_total.get(fk, 0)
        if total < 5:
            continue
        pct = fuel_ok.get(fk, 0) / total * 100
        fuel_stats.append((fk, pct, total))
    fuel_stats.sort(key=lambda x: x[1])

    # Бензовозы по сетям
    benz_by_net = {}
    for sid, in benz:
        st = STATION_BY_ID.get(sid)
        if not st:
            continue
        net = st[2] if st[2] in NETWORKS else "other"
        benz_by_net[net] = benz_by_net.get(net, 0) + 1
    benz_top = sorted(benz_by_net.items(), key=lambda kv: kv[1], reverse=True)[:3]

    # Свежесть сетей: % станций, обновлённых за 24ч
    day_ago = now - 86400
    net_all = {}
    net_fresh_cnt = {}
    for sid, last_ts in fresh:
        st = STATION_BY_ID.get(sid)
        if not st:
            continue
        net = st[2] if st[2] in NETWORKS else "other"
        net_all[net] = net_all.get(net, 0) + 1
        if last_ts >= day_ago:
            net_fresh_cnt[net] = net_fresh_cnt.get(net, 0) + 1
    net_fresh = []
    for net, total in net_all.items():
        if total < 10:
            continue
        pct = net_fresh_cnt.get(net, 0) / total * 100
        net_fresh.append((net, pct, total))
    net_fresh.sort(key=lambda x: x[1], reverse=True)

    return {
        "net_deficit": net_deficit[:5],
        "fuel_stats": fuel_stats,
        "benz_total": len(benz),
        "benz_top": benz_top,
        "net_fresh": net_fresh[:5],
    }


def format_trends_report():
    d = get_trends_report()
    lines = ["📈 <b>Тренды за 7 дней</b>", ""]

    # Топливо
    if d["fuel_stats"]:
        lines.append("<b>Дефицит по топливу</b>")
        for fk, pct, total in d["fuel_stats"]:
            name = FUEL_SHORT.get(fk, fk)
            if pct < 30:
                emoji = "🔴"
            elif pct < 60:
                emoji = "🟡"
            else:
                emoji = "🟢"
            lines.append(emoji + " " + name + " — <b>" + str(round(pct)) + "%</b> есть")
        lines.append("")

    # Сети — дефицит
    if d["net_deficit"]:
        lines.append("<b>Проблемные сети</b>")
        for net, pct, total in d["net_deficit"]:
            label = NETWORKS.get(net, {}).get("label", net)
            lines.append("• " + label + " — <b>" + str(round(pct)) + "%</b> «нет» (" + str(total) + ")")
        lines.append("")

    # Свежесть сетей
    if d["net_fresh"]:
        lines.append("<b>Свежесть данных (за 24ч)</b>")
        for net, pct, cnt in d["net_fresh"]:
            label = NETWORKS.get(net, {}).get("label", net)
            if pct >= 30:
                emoji = "🟢"
            elif pct >= 10:
                emoji = "🟡"
            else:
                emoji = "🔴"
            lines.append(emoji + " " + label + " — " + str(round(pct)) + "% обновлено (" + str(cnt) + ")")
        lines.append("")

    # Бензовозы
    if d["benz_total"] > 0:
        lines.append("<b>🚛 Бензовозы за 24ч: " + str(d["benz_total"]) + "</b>")
        for net, cnt in d["benz_top"]:
            label = NETWORKS.get(net, {}).get("label", net)
            lines.append("• " + label + " — " + str(cnt))
    else:
        lines.append("<b>🚛 Бензовозы за 24ч: 0</b>")

    lines.append("")
    lines.append("Данные от водителей. @naidibenzin_bot")
    return "\n".join(lines)


@dp.message(Command("тренды", "trends"))
async def on_trends_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    try:
        text = format_trends_report()
    except Exception as e:
        await message.answer("Ошибка: " + str(e))
        return
    await message.answer(text)


@dp.message(Command("статистика", "stats"))
async def on_stats_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    rows = get_metrics(7)
    lines = ["📊 <b>Метрики за 7 дней (UTC)</b>", ""]
    lines.append("<code>дата     api   отм  уник</code>")
    for day, api, reps, uniq in rows:
        short = day[5:]
        lines.append(f"<code>{short}  {api:5d} {reps:5d} {uniq:4d}</code>")
    total_api = sum(r[1] for r in rows)
    total_rep = sum(r[2] for r in rows)
    total_uniq = sum(r[3] for r in rows)
    lines.append("")
    lines.append(f"За 7 дней: api {total_api}, отчётов {total_rep}, уник {total_uniq}")
    conn = db()
    try:
        total_feed = conn.execute("SELECT COUNT(*) FROM feed").fetchone()[0]
        day_ago = int(time.time()) - 86400
        stations_24h = conn.execute(
            "SELECT COUNT(DISTINCT station_id) FROM feed WHERE ts > ?", (day_ago,)
        ).fetchone()[0]
        users_24h = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM feed WHERE ts > ? AND user_id != 0",
            (day_ago,),
        ).fetchone()[0]
    finally:
        conn.close()
    lines.append("")
    lines.append(f"Всего отчётов в БД: {total_feed}")
    lines.append(f"За 24ч: станций {stations_24h}, юзеров {users_24h}")

    # Источники трафика за 7 дней
    days_list = [
        time.strftime("%Y-%m-%d", time.gmtime(int(time.time()) - i * 86400))
        for i in range(6, -1, -1)
    ]
    conn = db()
    try:
        ph = ",".join("?" * len(days_list))
        ref_rows = conn.execute(
            f"SELECT key, SUM(value) FROM metrics_counters "
            f"WHERE day IN ({ph}) AND (key LIKE 'ref_%' OR key IN ('landing_view','map_view')) "
            f"GROUP BY key",
            days_list,
        ).fetchall()
    finally:
        conn.close()
    refs = {k: v for k, v in ref_rows}
    landing_total = refs.get("landing_view", 0)
    map_total = refs.get("map_view", 0)
    if landing_total or map_total:
        lines.append("")
        lines.append("<b>📥 Источники (7 дней)</b>")
        lines.append(f"Лендинг: <b>{landing_total}</b>  ·  Карта: <b>{map_total}</b>")
        clicks_map = refs.get("landing_click_map", 0)
        clicks_tg = refs.get("landing_click_tg", 0)
        if landing_total and (clicks_map or clicks_tg):
            pct_map = round(clicks_map / landing_total * 100) if landing_total else 0
            pct_tg = round(clicks_tg / landing_total * 100) if landing_total else 0
            lines.append(f"Клики: карта <b>{clicks_map}</b> ({pct_map}%)  ·  TG <b>{clicks_tg}</b> ({pct_tg}%)")
        srcs = {}
        for k, v in refs.items():
            if k.startswith("ref_landing_"):
                name = k[len("ref_landing_"):]
                srcs.setdefault(name, {"landing": 0, "map": 0})
                srcs[name]["landing"] = v
            elif k.startswith("ref_map_"):
                name = k[len("ref_map_"):]
                srcs.setdefault(name, {"landing": 0, "map": 0})
                srcs[name]["map"] = v
        for name in sorted(srcs, key=lambda n: -srcs[n]["landing"]):
            s_ = srcs[name]
            lines.append(f"• <b>{name}</b>: лендинг {s_['landing']}, карта {s_['map']}")

    await message.answer("\n".join(lines), reply_markup=kb_main())
@dp.message(Command("смотрители", "районы"))
async def on_ambassadors_cmd(message: Message):
    conn = db()
    try:
        rows = conn.execute(
            "SELECT user_id, username, total_points FROM user_points "
            "WHERE total_points >= 301 ORDER BY total_points DESC LIMIT 50"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        await message.answer(
            "🏛 <b>Смотрители районов</b>\n\n"
            "Пока никто не набрал 301 балл. Первый, кто дойдёт — станет Смотрителем своего района.\n\n"
            "Твои баллы: /профиль",
            reply_markup=kb_main(),
        )
        return
    # группируем по районам
    by_district = {}
    for uid, name, pts in rows:
        district = get_user_top_district(uid)
        if not district:
            continue
        by_district.setdefault(district, []).append((uid, name, pts))
    if not by_district:
        await message.answer("Пока нет Смотрителей. Стань первым — /профиль")
        return
    lines = ["🏛 <b>Смотрители районов</b>", ""]
    for district in sorted(by_district):
        people = by_district[district]
        top = people[0]
        label = format_display(top[1], top[0])
        lines.append(f"• <b>{district}</b> — {label} ({top[2]} баллов)")
    lines.append("")
    lines.append("Набрать 301 балл = стать Смотрителем. /профиль — твои баллы.")
    await message.answer("\n".join(lines), reply_markup=kb_main())

@dp.message(Command("правила"))
async def on_rules_cmd(message: Message):
    text = (
        "📋 <b>Правила сообщества</b>\n\n"
        "<b>Главное правило:</b> отмечай только то, что видел лично. "
        "Не ставь ложные отметки — от этого страдают другие водители.\n\n"
        "<b>Когда отмечать:</b>\n"
        "• Заправился или проезжал мимо АЗС.\n"
        "• Увидел, что топливо появилось или кончилось.\n"
        "• Заметил очередь или лимит на литры.\n\n"
        "<b>Чего делать не стоит:</b>\n"
        "• Отмечать станцию, где ты не был.\n"
        "• Ставить статус «по памяти» — только сейчас.\n"
        "• Спамить одинаковыми отметками в короткий срок.\n\n"
        "<b>Что мы храним:</b> Telegram ID, username (если задан), отметки о топливе. "
        "Точные координаты — только если вы сами сообщаете об отсутствующей станции.\n\n"
        "<b>Кому передаются данные:</b> никому. Нет рекламы, нет продажи третьим лицам.\n\n"
        "Несогласны с чем-то или нашли баг — напишите: /проблема"
    )
    await message.answer(text, reply_markup=kb_main())
    await message.answer(text, reply_markup=kb_main())


def feed_text():
    rows = get_recent_feed(12)
    if not rows:
        return "Пока нет отчётов. Станьте первым — выберите станцию через /start."
    fuel_label = {k: v for k, v in FUELS}
    lines = ["🕓 <b>Последние отчёты сообщества</b>", ""]
    seen = []
    for ts, station_id, fuel, status, username in rows:
        s = get_station(station_id)
        if not s:
            continue
        who = f" · {format_display(username)}" if username else ""
        lines.append(f"{s[1]}, {s[3]} — {fuel_label.get(fuel, fuel)} {STATUS_LABEL[status]} · {time_ago(ts)}{who}")
        if station_id not in seen:
            seen.append(station_id)
    return "\n".join(lines), seen


def feed_kb(station_ids):
    rows = []
    for sid in station_ids[:12]:
        s = get_station(sid)
        if not s:
            continue
        label = s[1] + " · " + (s[3] or "—")
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([InlineKeyboardButton(text="⛽ " + label, callback_data=f"stn:{sid}")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "menu")
async def cb_menu(cq: CallbackQuery):
    await safe_edit(cq, "Выберите сеть:", kb_main())
    await cq.answer()


@dp.callback_query(F.data == "feed")
async def cb_feed(cq: CallbackQuery):
    text, ids = feed_text()
    await safe_edit(cq, text, feed_kb(ids))
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


_SUPPORT_RECEIVER = "4100119644232499"
def _support_url(amount=None):
    from urllib.parse import quote
    base = "https://yoomoney.ru/quickpay/confirm.xml?receiver=" + _SUPPORT_RECEIVER + "&quickpay-form=button&targets=" + quote("Поддержка проекта ГДЕ БЕНЗИН!?")
    if amount:
        base += "&sum=" + str(amount)
    return base
SUPPORT_URL = _support_url()


@dp.callback_query(F.data == "my_st:")
async def cb_my_stations(cq: CallbackQuery):
    await cq.answer()
    user_id = cq.from_user.id
    stations = get_my_stations(user_id, limit=5, min_reports=3)
    if not stations:
        text = (
            "🏠 <b>Моих станций пока нет</b>\n\n"
            "Станция становится «твоей», когда ты отметил на ней "
            "минимум 3 раза. Обычно это заправки, где ты заправляешься "
            "чаще всего.\n\n"
            "За отчёт на «своей» станции — <b>х2 баллов</b>."
        )
    else:
        lines = ["🏠 <b>Мои станции</b>", ""]
        lines.append("За отчёт на этих станциях — <b>х2 баллов</b>.")
        lines.append("")
        medals = ["1.", "2.", "3.", "4.", "5."]
        for i, st in enumerate(stations):
            lines.append("<b>" + medals[i] + " " + st["name"] + "</b>")
            lines.append("   " + st["addr"])
            lines.append("   Твоих отчётов: <b>" + str(st["cnt"]) + "</b>")
            lines.append("")
        lines.append("Чем чаще отмечаешь здесь — тем свежее данные для тебя и соседей.")
        text = "\n".join(lines)
    try:
        await cq.message.answer(text)
    except Exception:
        pass


@dp.callback_query(F.data == "donate:")
async def cb_donate(cq: CallbackQuery):
    await cq.answer()
    text = (
        "\u2615 <b>\u041f\u043e\u0434\u0434\u0435\u0440\u0436\u0430\u0442\u044c \u043f\u0440\u043e\u0435\u043a\u0442</b>\n\n"
        "\u041f\u0440\u043e\u0435\u043a\u0442 \u0436\u0438\u0432\u0451\u0442 \u043d\u0430 \u044d\u043d\u0442\u0443\u0437\u0438\u0430\u0437\u043c\u0435 \u043e\u0434\u043d\u043e\u0433\u043e \u0447\u0435\u043b\u043e\u0432\u0435\u043a\u0430. "
        "\u0421\u0435\u0440\u0432\u0435\u0440\u044b, \u043a\u0430\u0440\u0442\u044b, \u0434\u043e\u043c\u0435\u043d\u044b, \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u2014 "
        "\u0438\u0437 \u0441\u0432\u043e\u0435\u0433\u043e \u043a\u0430\u0440\u043c\u0430\u043d\u0430.\n\n"
        "<b>\u041e\u0440\u0438\u0435\u043d\u0442\u0438\u0440\u044b:</b>\n"
        "\u2022 100 \u20bd \u2014 \u0434\u0435\u043d\u044c \u0445\u043e\u0441\u0442\u0438\u043d\u0433\u0430\n"
        "\u2022 500 \u20bd \u2014 \u043c\u0435\u0441\u044f\u0446 \u043a\u0430\u0440\u0442\n"
        "\u2022 1000 \u20bd \u2014 \u043d\u0435\u0434\u0435\u043b\u044f \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0438\n\n"
        "\u0421\u043f\u0430\u0441\u0438\u0431\u043e, \u0447\u0442\u043e \u0442\u044b \u0441 \u043d\u0430\u043c\u0438 \U0001F64F"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F4B3 100 \u20bd", url=_support_url(100)),
         InlineKeyboardButton(text="\U0001F4B3 300 \u20bd", url=_support_url(300))],
        [InlineKeyboardButton(text="\U0001F4B3 500 \u20bd", url=_support_url(500)),
         InlineKeyboardButton(text="\U0001F4B3 1000 \u20bd", url=_support_url(1000))],
    ])
    try:
        await cq.message.answer(text, reply_markup=kb)
    except Exception:
        await cq.message.answer(text)


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
    if raw == "__bot__":
        station_id = None
        text_for_db = message.text
    elif raw.startswith("missing:"):
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
        _kb_rows = []
        if station_id:
            try:
                _st = get_station(station_id)
                if _st:
                    _url = (MAP_URL or "https://azs-spb-bot-syntetika.amvera.io/map").rstrip("/")
                    _link = f"{_url}?pin={_st[4]:.6f},{_st[5]:.6f}&brand={_st[2]}"
                    _kb_rows.append([InlineKeyboardButton(text="📍 Открыть на карте", web_app=WebAppInfo(url=_link))])
            except Exception:
                pass
        _kb_rows.append([InlineKeyboardButton(text="✅ Исправлено", callback_data=f"fix:{issue_id}")])
        fix_kb = InlineKeyboardMarkup(inline_keyboard=_kb_rows)
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
    # Начисляем баллы за исправление
    if reporter_id:
        try:
            name = None
            conn = db()
            row = conn.execute("SELECT username FROM user_points WHERE user_id=?", (reporter_id,)).fetchone()
            conn.close()
            if row:
                name = row[0]
            award_points(reporter_id, name, POINTS_FIX_ISSUE, "fix_issue")
        except Exception:
            log.exception("Не удалось начислить баллы за исправление")
    try:
        await cq.message.bot.send_message(
            reporter_id,
            f"Ваше сообщение о неточности разобрали и исправили — спасибо! 🙌\n"
            f"Начислено <b>+{POINTS_FIX_ISSUE} баллов</b>."
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





def get_daily_leaderboard(limit=3):
    day_ago = int(time.time()) - 24 * 3600
    conn = db()
    rows = conn.execute("""
        SELECT p.user_id, COALESCE(u.username, 'id' || p.user_id) AS username,
               COUNT(DISTINCT p.station_id) AS cnt
        FROM points_log p LEFT JOIN user_points u ON u.user_id = p.user_id
        WHERE p.ts > ? AND p.reason = 'report' AND p.station_id IS NOT NULL
        GROUP BY p.user_id ORDER BY cnt DESC LIMIT ?
    """, (day_ago, limit)).fetchall()
    conn.close()
    return rows


def get_daily_totals():
    day_ago = int(time.time()) - 24 * 3600
    conn = db()
    row = conn.execute("""
        SELECT COUNT(*), COUNT(DISTINCT user_id) FROM points_log
        WHERE ts > ? AND reason = 'report' AND station_id IS NOT NULL
    """, (day_ago,)).fetchone()
    conn.close()
    return (row[0] or 0, row[1] or 0)


def format_daily_leaderboard_text(rows):
    medals = ["\U0001F947", "\U0001F948", "\U0001F949"]
    cta = "Хочешь быть здесь завтра? Отмечай наличие топлива:\nt.me/naidibenzin_bot?start=daily_top"
    if not rows:
        return (
            "\U0001F6F0 <b>Топ разведчиков дня</b>\n\n"
            "Пока никто не отметился. Будь первым!\n\n"
            + cta
        )
    if len(rows) >= 3:
        lines = ["\U0001F6F0 <b>Топ разведчиков дня</b>", ""]
    else:
        lines = ["\U0001F6F0 <b>Сегодня помогали</b>", ""]
    for i, (uid, username, cnt) in enumerate(rows):
        mark = medals[i] if i < 3 else (str(i + 1) + ".")
        display = format_display(username, uid)
        lines.append(mark + " " + display + " — " + str(cnt) + " АЗС")
    lines.append("")
    try:
        total_reports, total_users = get_daily_totals()
        if total_users >= 2:
            lines.append("Сегодня в городе: " + str(total_reports) + " отчётов от " + str(total_users) + " человек.")
            lines.append("")
    except Exception:
        pass
    lines.append("Каждый отчёт — это чей-то заправленный бак.")
    lines.append("")
    lines.append(cta)
    return "\n".join(lines)


async def post_daily_leaderboard(bot: Bot):
    if not CHANNEL_ID:
        return False
    rows = get_daily_leaderboard(3)
    text = format_daily_leaderboard_text(rows)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\U0001F5FA \u041E\u0442\u043A\u0440\u044B\u0442\u044C \u043A\u0430\u0440\u0442\u0443", url="https://t.me/naidibenzin_bot/azs")
    ]])
    await bot.send_message(CHANNEL_ID, text, parse_mode="HTML", reply_markup=kb)
    log.info("Топ дня опубликован в канал %s", CHANNEL_ID)
    return True


async def daily_leaderboard_task(bot: Bot):
    if not CHANNEL_ID:
        log.info("CHANNEL_ID не задан — автопост топа дня отключён.")
        return
    POST_HOUR_UTC = 17
    POLL_INTERVAL = 600
    while True:
        now = datetime.utcnow()
        if now.hour >= POST_HOUR_UTC:
            today_str = now.strftime("%Y-%m-%d")
            if get_state("last_daily_post_date") != today_str:
                sent = False
                try:
                    sent = await post_daily_leaderboard(bot)
                except Exception:
                    log.exception("Ошибка при публикации топа дня")
                if sent:
                    set_state("last_daily_post_date", today_str)
        await asyncio.sleep(POLL_INTERVAL)


STALE_DAYS = 5
STALE_NOTIFY_COOLDOWN_DAYS = 7


async def stale_stations_task(bot: Bot):
    """Раз в сутки проверяет у юзеров их 'свои' станции и шлёт напоминание,
    если давно не было отчётов."""
    POST_HOUR_UTC = 10  # 13:00 МСК
    POLL_INTERVAL = 1800
    while True:
        try:
            now = datetime.utcnow()
            if now.hour >= POST_HOUR_UTC:
                today_str = now.strftime("%Y-%m-%d")
                if get_state("last_stale_notify_date") != today_str:
                    await _run_stale_notifications(bot)
                    set_state("last_stale_notify_date", today_str)
        except Exception:
            log.exception("stale_stations_task error")
        await asyncio.sleep(POLL_INTERVAL)


async def _run_stale_notifications(bot: Bot):
    cutoff_stale = int(time.time()) - STALE_DAYS * 86400
    cutoff_cooldown = int(time.time()) - STALE_NOTIFY_COOLDOWN_DAYS * 86400
    conn = db()
    try:
        user_rows = conn.execute(
            "SELECT DISTINCT user_id FROM feed "
            "WHERE user_id > 0 AND ts > ?",
            (int(time.time()) - 30 * 86400,)
        ).fetchall()
    finally:
        conn.close()

    map_base = (MAP_URL or "https://azs-spb-bot-syntetika.amvera.io/map").rstrip("/")
    sent_count = 0
    for (uid,) in user_rows:
        if not uid:
            continue
        try:
            stations = get_my_stations(uid, limit=20, min_reports=3)
        except Exception:
            continue
        if not stations:
            continue
        stale = [st for st in stations if st["last_ts"] and st["last_ts"] < cutoff_stale]
        if not stale:
            continue
        last_sent = get_state("stale_notify_%d" % uid)
        if last_sent:
            try:
                if int(last_sent) > cutoff_cooldown:
                    continue
            except Exception:
                pass
        stale.sort(key=lambda x: x["last_ts"])
        lines = ["\U0001F551 <b>\u041d\u0430 \u0442\u0432\u043e\u0438\u0445 \u0441\u0442\u0430\u043d\u0446\u0438\u044f\u0445 \u0434\u0430\u0432\u043d\u043e \u043d\u0435 \u0431\u044b\u043b\u043e \u043e\u0442\u0447\u0451\u0442\u043e\u0432:</b>", ""]
        for st in stale[:5]:
            days = (int(time.time()) - st["last_ts"]) // 86400
            lines.append("\u2022 " + st["name"] + " \u2014 " + str(days) + " \u0434\u043d \u043d\u0430\u0437\u0430\u0434")
        lines.append("")
        lines.append("\u0415\u0441\u043b\u0438 \u043f\u0440\u043e\u0435\u0437\u0436\u0430\u043b \u043c\u0438\u043c\u043e \u2014 \u0437\u0430\u0433\u043b\u044f\u043d\u0438, \u043e\u0442\u043c\u0435\u0442\u044c \u0441\u0442\u0430\u0442\u0443\u0441. \u0412\u043e\u0434\u0438\u0442\u0435\u043b\u044f\u043c \u0432\u0430\u0436\u043d\u0430 \u0441\u0432\u0435\u0436\u0430\u044f \u0438\u043d\u0444\u0430.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\U0001F5FA \u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043a\u0430\u0440\u0442\u0443", web_app=WebAppInfo(url=map_base))]
        ])
        try:
            await bot.send_message(uid, "\n".join(lines), reply_markup=kb)
            set_state("stale_notify_%d" % uid, str(int(time.time())))
            sent_count += 1
        except Exception:
            pass
    log.info("stale_stations_task: sent=%d", sent_count)





def get_network_weekly_stats():
    """Аналитика по сетям за 7 дней на основе feed."""
    week_ago = int(time.time()) - 7 * 86400
    conn = db()
    rows = conn.execute("""
        SELECT station_id, fuel, status, ts FROM feed
        WHERE ts > ?
    """, (week_ago,)).fetchall()
    conn.close()

    stats = {}  # net_key -> {"total": N, "fuels": {fk: {"ok":N,"low":N,"none":N}}, "last_ts": max}
    total_all = 0
    for station_id, fuel, status, ts in rows:
        st = STATION_BY_ID.get(station_id)
        if not st:
            continue
        net = st[2]
        if net not in NETWORKS:
            net = "other"
        if net not in stats:
            stats[net] = {"total": 0, "last_ts": 0, "fuels": {fk: {"ok":0,"low":0,"none":0} for fk,_ in FUELS}}
        stats[net]["total"] += 1
        if ts > stats[net]["last_ts"]:
            stats[net]["last_ts"] = ts
        if fuel in stats[net]["fuels"] and status in ("ok","low","none"):
            stats[net]["fuels"][fuel][status] += 1
        total_all += 1
    return stats, total_all


def format_network_report(stats, total_all):
    if not stats or total_all == 0:
        return None

    medals = ["\U0001F947", "\U0001F948", "\U0001F949"]
    ranked = sorted(stats.items(), key=lambda kv: kv[1]["total"], reverse=True)
    top5 = ranked[:5]

    lines = ["\U0001F4CA <b>\u0421\u0435\u0442\u0438 \u043d\u0435\u0434\u0435\u043b\u0438</b>", ""]

    # Доля рынка
    lines.append("<b>\u0414\u043e\u043b\u044f \u0440\u044b\u043d\u043a\u0430 \u043f\u043e \u043e\u0442\u0447\u0451\u0442\u0430\u043c</b>")
    for idx, (net, st) in enumerate(top5):
        label = NETWORKS.get(net, {}).get("label", net)
        pct = round(st["total"] / total_all * 100)
        mark = medals[idx] if idx < 3 else "  "
        lines.append(mark + " " + label + " — <b>" + str(pct) + "%</b>")
    if len(ranked) > 5:
        rest_pct = sum(st["total"] for _, st in ranked[5:]) / total_all * 100
        lines.append("  \u041e\u0441\u0442\u0430\u043b\u044c\u043d\u044b\u0435 — " + str(round(rest_pct)) + "%")
    lines.append("")

    # Свежесть
    now = int(time.time())
    ranked_fresh = sorted(
        [(n, s) for n, s in stats.items() if s["total"] >= 5],
        key=lambda kv: kv[1]["last_ts"], reverse=True
    )
    if ranked_fresh:
        freshest = ranked_fresh[0]
        hours_ago = max(1, round((now - freshest[1]["last_ts"]) / 3600))
        label = NETWORKS.get(freshest[0], {}).get("label", freshest[0])
        lines.append("\U0001F7E2 <b>\u0421\u0432\u0435\u0436\u0435\u0435 \u0432\u0441\u0435\u0445:</b> " + label + " (\u043e\u0442\u0447\u0451\u0442 " + str(hours_ago) + " \u0447 \u043d\u0430\u0437\u0430\u0434)")

    # Проблемные
    problematics = []
    for net, st in stats.items():
        if st["total"] < 8:
            continue
        total_none = sum(st["fuels"][fk]["none"] for fk,_ in FUELS)
        pct_none = total_none / st["total"] * 100
        problematics.append((net, pct_none, total_none))
    if problematics:
        problematics.sort(key=lambda x: x[1], reverse=True)
        top_none = problematics[0]
        if top_none[1] >= 25:
            label = NETWORKS.get(top_none[0], {}).get("label", top_none[0])
            lines.append("\U0001F534 <b>\u041f\u0440\u043e\u0431\u043b\u0435\u043c\u043d\u0435\u0435 \u0432\u0441\u0435\u0445:</b> " + label + " (" + str(round(top_none[1])) + "% \u00ab\u043d\u0435\u0442\u00bb)")
    lines.append("")

    # Топливо по топ-3 — компактно, с эмодзи статуса
    lines.append("<b>\u0422\u043e\u043f\u043b\u0438\u0432\u043e \u0443 \u0442\u043e\u043f-3</b>")
    for net, st in top5[:3]:
        label = NETWORKS.get(net, {}).get("label", net)
        lines.append("<b>" + label + "</b>")
        for fk, fname in FUELS:
            f = st["fuels"][fk]
            total_f = f["ok"] + f["low"] + f["none"]
            if total_f == 0:
                continue
            pct_ok = round(f["ok"] / total_f * 100)
            if pct_ok >= 70:
                emoji = "\U0001F7E2"
            elif pct_ok >= 40:
                emoji = "\U0001F7E1"
            else:
                emoji = "\U0001F534"
            lines.append("  " + emoji + " " + FUEL_SHORT[fk] + " — " + str(pct_ok) + "% \u0435\u0441\u0442\u044c")
    lines.append("")
    lines.append("\u0414\u0430\u043d\u043d\u044b\u0435 \u0437\u0430 7 \u0434\u043d\u0435\u0439 \u043e\u0442 \u0432\u043e\u0434\u0438\u0442\u0435\u043b\u0435\u0439. @naidibenzin_bot")
    return "\n".join(lines)


async def post_network_report(bot: Bot):
    if not CHANNEL_ID:
        return False
    try:
        stats, total_all = get_network_weekly_stats()
    except Exception:
        log.exception("get_network_weekly_stats failed")
        return False
    text = format_network_report(stats, total_all)
    if not text:
        log.info("Отчёт по сетям пропущен: нет данных.")
        return False
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\U0001F5FA \u041E\u0442\u043A\u0440\u044B\u0442\u044C \u043A\u0430\u0440\u0442\u0443", url="https://t.me/naidibenzin_bot/azs")
    ]])
    await bot.send_message(CHANNEL_ID, text, parse_mode="HTML", reply_markup=kb)
    log.info("Отчёт по сетям опубликован")
    return True


async def weekly_network_task(bot: Bot):
    if not CHANNEL_ID:
        return
    POST_HOUR_UTC = 6  # 9:00 МСК, вторник
    POLL_INTERVAL = 600
    while True:
        now = datetime.utcnow()
        if now.weekday() == 1 and now.hour >= POST_HOUR_UTC:
            today_str = now.strftime("%Y-%m-%d")
            if get_state("last_network_post_date") != today_str:
                sent = False
                try:
                    sent = await post_network_report(bot)
                except Exception:
                    log.exception("Ошибка публикации отчёта по сетям")
                if sent:
                    set_state("last_network_post_date", today_str)
        await asyncio.sleep(POLL_INTERVAL)





def _haversine_m(la1, lo1, la2, lo2):
    import math
    R = 6371000.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp = math.radians(la2 - la1); dl = math.radians(lo2 - lo1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))


def merge_duplicate_stations(pairs):
    """pairs: список {"keep": id, "drop": [id, ...]}.
    Переносит feed/reports с drop на keep, удаляет drop из custom_stations.
    Возвращает {"moved_feed": N, "moved_reports": M, "deleted_stations": K}."""
    moved_feed = 0
    moved_reports = 0
    deleted_stations = 0
    conn = db()
    try:
        for p in pairs:
            keep = str(p.get("keep") or "").strip()
            drops = p.get("drop") or []
            if not keep:
                continue
            for dr in drops:
                drop = str(dr).strip()
                if not drop or drop == keep:
                    continue
                # feed — простой UPDATE (PK AUTOINCREMENT, конфликтов нет)
                cur1 = conn.execute("UPDATE feed SET station_id=? WHERE station_id=?", (keep, drop))
                moved_feed += cur1.rowcount or 0
                # reports — PK (station_id, fuel): переносим по одному топливу,
                # оставляем более свежий отчёт
                rep_rows = conn.execute(
                    "SELECT fuel, status, ts, user_id, username FROM reports WHERE station_id=?",
                    (drop,)
                ).fetchall()
                for fuel, status, ts, uid, uname in rep_rows:
                    existing = conn.execute(
                        "SELECT ts FROM reports WHERE station_id=? AND fuel=?",
                        (keep, fuel)
                    ).fetchone()
                    if existing and (existing[0] or 0) >= (ts or 0):
                        # у keep свежее — drop-отчёт просто снимаем
                        continue
                    conn.execute(
                        "INSERT OR REPLACE INTO reports (station_id, fuel, status, ts, user_id, username) VALUES (?,?,?,?,?,?)",
                        (keep, fuel, status, ts, uid, uname)
                    )
                    moved_reports += 1
                conn.execute("DELETE FROM reports WHERE station_id=?", (drop,))
                # Удаляем станцию
                cur3 = conn.execute("DELETE FROM custom_stations WHERE id=?", (drop,))
                deleted_stations += cur3.rowcount or 0
                try:
                    STATION_BY_ID.pop(drop, None)
                except Exception:
                    pass
        conn.commit()
    finally:
        conn.close()
    return {"moved_feed": moved_feed, "moved_reports": moved_reports, "deleted_stations": deleted_stations}


def find_duplicate_pairs(radius_m=200):
    """Возвращает список пар [((sid_a, net, name, addr, lat, lng, cnt_a), (sid_b, ...), dist_m)]."""
    conn = db()
    # Все станции: статичные + кастомные + overrides
    rows = conn.execute("SELECT id, name, net, addr, lat, lng FROM custom_stations").fetchall()
    # Считаем отчёты по каждой станции из feed
    feed = conn.execute("SELECT station_id, COUNT(*) FROM feed GROUP BY station_id").fetchall()
    conn.close()
    counts = {sid: cnt for sid, cnt in feed}
    items = []
    for sid, name, net, addr, lat, lng in rows:
        items.append((sid, net, name, addr or "", lat, lng, counts.get(sid, 0)))
    pairs = []
    n = len(items)
    for i in range(n):
        a = items[i]
        for j in range(i+1, n):
            b = items[j]
            if a[1] != b[1]:
                continue
            d = _haversine_m(a[4], a[5], b[4], b[5])
            if d <= radius_m:
                pairs.append((a, b, d))
    pairs.sort(key=lambda x: x[2])
    return pairs


def _dup_score(sid, name, net, addr, cnt):
    sc = 0
    a = (addr or "").strip().lower()
    if a and a not in ("добавлено с карты", "добавлено пользователем"):
        sc += 1000
    sc += int(cnt or 0) * 10
    if not str(sid).startswith("custom-"):
        sc += 5000
    return sc


def build_dup_merge_plan(radius_m=10):
    """Возвращает список {keep: {...}, drop: [{...}, ...]} для групп дублей."""
    conn = db()
    rows = conn.execute("SELECT id, name, net, addr, lat, lng FROM custom_stations").fetchall()
    feed = conn.execute("SELECT station_id, COUNT(*) FROM feed GROUP BY station_id").fetchall()
    conn.close()
    counts = {sid: cnt for sid, cnt in feed}

    # Только custom_stations + один проход. STATIC-станции не трогаем
    # (они не в custom_stations). Дубли custom↔custom или custom↔static
    # мы не обнаружим по этой выборке — берём только custom↔custom.
    items = []
    for sid, name, net, addr, lat, lng in rows:
        items.append({
            "id": sid, "name": name, "net": net, "addr": addr or "",
            "lat": lat, "lng": lng, "cnt": counts.get(sid, 0)
        })

    # Ищем пары <=radius_m, одна сеть
    n = len(items)
    pairs = []
    for i in range(n):
        a = items[i]
        for j in range(i+1, n):
            b = items[j]
            if a["net"] != b["net"]:
                continue
            d = _haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
            if d <= radius_m:
                pairs.append((i, j, d))

    # Union-find по индексам
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[rb] = ra
    for i, j, d in pairs:
        union(i, j)

    groups = {}
    for i, it in enumerate(items):
        r = find(i)
        groups.setdefault(r, []).append(it)

    plan = []
    for root, members in groups.items():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=lambda x: _dup_score(x["id"], x["name"], x["net"], x["addr"], x["cnt"]), reverse=True)
        plan.append({"keep": ranked[0], "drop": ranked[1:]})
    return plan


@dp.message(Command("dupmerge"))
async def on_dupmerge_cmd(message: Message):
    import traceback
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    await message.answer("Считаю план…")
    try:
        plan = build_dup_merge_plan(10)
    except Exception:
        tb = traceback.format_exc()
        await message.answer("Ошибка:\n<pre>" + html.escape(tb[-1500:]) + "</pre>")
        return
    if not plan:
        await message.answer("Нечего сливать.")
        return
    total_drop = sum(len(g["drop"]) for g in plan)
    lines = ["🧹 <b>План слияния дублей</b>", ""]
    lines.append("Групп: <b>" + str(len(plan)) + "</b> · удалить: <b>" + str(total_drop) + "</b>")
    lines.append("")
    for g in plan[:15]:
        keep = g["keep"]
        lines.append("<b>✔ " + str(keep["id"]) + "</b> | " + (keep["addr"] or "—"))
        for d in g["drop"]:
            lines.append("  ✖ " + str(d["id"]) + " | " + (d["addr"] or "—"))
    if len(plan) > 15:
        lines.append("… и ещё " + str(len(plan) - 15) + " групп")
    # Собираем pairs для API
    pairs = [{"keep": g["keep"]["id"], "drop": [d["id"] for d in g["drop"]]} for g in plan]
    payload = json.dumps(pairs)
    # Inline-кнопка «Применить»
    # Из-за лимита callback_data 64 байта — сохраним план в bot_state и передадим id
    token = str(int(time.time()))
    set_state("dupmerge_plan_" + token, payload)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Применить", callback_data="dupmerge:apply:" + token),
        InlineKeyboardButton(text="❌ Отмена", callback_data="dupmerge:cancel")
    ]])
    await message.answer("\n".join(lines), reply_markup=kb)


@dp.callback_query(F.data.startswith("dupmerge:"))
async def cb_dupmerge(cq: CallbackQuery):
    if not ADMIN_ID or cq.from_user.id != ADMIN_ID:
        await cq.answer("Только админ.", show_alert=True)
        return
    parts = cq.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "cancel":
        await cq.message.edit_reply_markup(reply_markup=None)
        await cq.answer("Отменено.")
        return
    if action == "apply" and len(parts) == 3:
        token = parts[2]
        raw = get_state("dupmerge_plan_" + token)
        if not raw:
            await cq.answer("План истёк.", show_alert=True)
            return
        try:
            pairs = json.loads(raw)
        except Exception:
            await cq.answer("План повреждён.", show_alert=True)
            return
        try:
            result = merge_duplicate_stations(pairs)
        except Exception as e:
            await cq.answer("Ошибка: " + str(e), show_alert=True)
            return
        set_state("dupmerge_plan_" + token, "")
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        text = ("✅ <b>Слияние выполнено</b>\n\n"
                "• Перенесено feed-записей: <b>" + str(result["moved_feed"]) + "</b>\n"
                "• Перенесено reports: <b>" + str(result["moved_reports"]) + "</b>\n"
                "• Удалено станций: <b>" + str(result["deleted_stations"]) + "</b>")
        await cq.message.answer(text)
        await cq.answer("Готово")
        return
    await cq.answer("")


@dp.message(Command("dups"))
async def on_dups_cmd(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("Команда только для админа.")
        return
    await message.answer("Считаю дубли… может занять 5-10 секунд.")
    try:
        pairs = find_duplicate_pairs(200)
    except Exception as e:
        await message.answer("Ошибка: " + str(e))
        return
    if not pairs:
        await message.answer("Дублей не найдено.")
        return
    lines = ["\U0001F50D <b>Дубли одной сети (<=200м)</b>", ""]
    zero_pairs = [p for p in pairs if p[2] < 1.0]
    near_pairs = [p for p in pairs if 1.0 <= p[2] <= 200.0]
    lines.append("Всего пар: <b>" + str(len(pairs)) + "</b>")
    lines.append("Точных (0м): <b>" + str(len(zero_pairs)) + "</b>")
    lines.append("Близких (1-200м): <b>" + str(len(near_pairs)) + "</b>")
    lines.append("")
    lines.append("<b>Точные 0м — кандидаты на авто-merge:</b>")
    for a, b, d in zero_pairs[:20]:
        lines.append("\u2022 <code>" + a[0] + "</code> (" + str(a[6]) + " отч.)  \u2194  <code>" + b[0] + "</code> (" + str(b[6]) + " отч.)")
    if len(zero_pairs) > 20:
        lines.append("... и ещё " + str(len(zero_pairs) - 20))
    lines.append("")
    lines.append("<b>Близкие 1-200м — проверить вручную:</b>")
    for a, b, d in near_pairs[:15]:
        lines.append("\u2022 <code>" + a[0] + "</code> (" + str(a[6]) + ") \u2194 <code>" + b[0] + "</code> (" + str(b[6]) + ") — " + str(int(d)) + " м")
    if len(near_pairs) > 15:
        lines.append("... и ещё " + str(len(near_pairs) - 15))
    await message.answer("\n".join(lines))


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN.")
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    init_db()          # один раз: PRAGMA WAL, схема, индексы
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
    asyncio.create_task(daily_leaderboard_task(bot))
    asyncio.create_task(weekly_network_task(bot))
    asyncio.create_task(stale_stations_task(bot))

    await dp.start_polling(bot, request_timeout=15)


if __name__ == "__main__":
    asyncio.run(main())
