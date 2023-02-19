import re

from telebot import types

from app import db
from models import User, History, Restaurant
from datetime import datetime
from settings import YKT


def check_user(msg):
    user = User.query.filter_by(uid=msg["from"]["id"]).first()
    if not user:
        user = User(
            uid=msg["from"]["id"],
            first_name=msg["from"]["first_name"],
            last_name=msg["from"]["last_name"],
            username=msg["from"]["username"]
        )
        db.session.add(user)
        db.session.commit()


def write_history(msg_id, chat_id, text, is_bot):
    msg = History(
        message_id=msg_id,
        chat_id=chat_id,
        date=datetime.now(YKT).strftime('%s'),
        type='message',
        message_text=text,
        is_bot=is_bot
    )
    db.session.add(msg)
    db.session.commit()


def rest_menu_keyboard():
    """Возвращает меню с наименованиями ресторанов"""

    def is_time_between(begin_time, ending_time, check_time=None):
        # If check time is not given, default to current time
        check_time = check_time or datetime.now(YKT).time()
        if begin_time < ending_time:
            return begin_time <= check_time <= ending_time
        else:  # crosses midnight
            return check_time >= begin_time or check_time <= ending_time

    restaurants = Restaurant.query.filter(Restaurant.id != 1).all()
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    current_time = datetime.now(YKT).time()
    pattern = r'(([0-9]|0[0-9]|1[0-9]|2[0-3]):[0-5][0-9](-|\s-\s)([0-9]|0[0-9]|1[0-9]|2[0-3]):[0-5][0-9])'
    for restaurant in restaurants:
        if not restaurant.enabled:
            continue
        if match := re.search(pattern, restaurant.name, re.IGNORECASE):
            if ' ' not in match.group(1):
                start_time = datetime.strptime(match.group(1).split('-')[0], '%H:%M').time()
                end_time = datetime.strptime(match.group(1).split('-')[1], '%H:%M').time()
            else:
                start_time = datetime.strptime(match.group(1).split(' ')[0], '%H:%M').time()
                end_time = datetime.strptime(match.group(1).split(' ')[2], '%H:%M').time()

            if is_time_between(start_time, end_time, current_time):
                keyboard.add(
                    types.InlineKeyboardButton(text=f'{restaurant.name}', callback_data=f'rest_{restaurant.id}'))
        else:
            keyboard.add(
                types.InlineKeyboardButton(text=f'{restaurant.name}', callback_data=f'rest_{restaurant.id}'))
    return keyboard
