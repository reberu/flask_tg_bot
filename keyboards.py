from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from main import sql_query


def rest_menu_keyboard():
    """Возвращает меню с наименованиями ресторанов"""

    rest_sql = "SELECT id, name FROM restaurants;"

    restaurants = sql_query(rest_sql)
    keyboard = []
    for restaurant in restaurants:
        keyboard.append([InlineKeyboardButton(f'{restaurant[1]}', callback_data=f'restaurant_{restaurant[0]}')])
    keyboard.append([InlineKeyboardButton('Назад', callback_data='back')])
    return InlineKeyboardMarkup(keyboard)


def stat_menu_keyboard():
    """Возвращает меню статистики"""
    keyboard = []
    for i in range(1, 8):
        keyboard.append([InlineKeyboardButton(f'{i}', callback_data=f'stat_{i}')])
    return InlineKeyboardMarkup(keyboard)
