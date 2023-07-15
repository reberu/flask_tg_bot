import logging
import sys
from logging.handlers import RotatingFileHandler
import re

from telebot import types
from telebot.types import WebAppInfo

from app import db
from models import User, History, Restaurant, Order
from datetime import datetime
from settings import YKT, MONTHS, BASE_URL


def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s",
        handlers=[
            logging.FileHandler("restobot.log"),
            logging.StreamHandler(stream=sys.stdout)
        ]
    )


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


def rest_menu_keyboard(uid):
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
        webapp = WebAppInfo(BASE_URL + f"webapp/{restaurant.id}?uid={uid}")
        if match := re.search(pattern, restaurant.name, re.IGNORECASE):
            if ' ' not in match.group(1):
                start_time = datetime.strptime(match.group(1).split('-')[0], '%H:%M').time()
                end_time = datetime.strptime(match.group(1).split('-')[1], '%H:%M').time()
            else:
                start_time = datetime.strptime(match.group(1).split(' ')[0], '%H:%M').time()
                end_time = datetime.strptime(match.group(1).split(' ')[2], '%H:%M').time()

            if is_time_between(start_time, end_time, current_time):
                keyboard.add(
                    types.InlineKeyboardButton(text=f'{restaurant.name}', web_app=webapp))
        else:
            keyboard.add(
                types.InlineKeyboardButton(text=f'{restaurant.name}', web_app=webapp))
    return keyboard


def stat1():
    current_month = datetime.now(YKT).month
    first_day = datetime(datetime.now(YKT).year, 1, 1, 0, 0, 0).strftime('%s')
    today = datetime.now(YKT).strftime('%s')
    stat_data = Order.query.filter(Order.order_datetime.between(first_day, today)).all()
    text = ''
    for month in MONTHS:
        if month > current_month:
            break
        current_month_total = 0
        current_month_rests_total = {}
        for data in stat_data:
            order_date = int(datetime.fromtimestamp(data.order_datetime).strftime("%m"))
            if order_date == month and ('Подтверждена' in data.order_state or 'Заказ принят рестораном' in
                                        data.order_state) \
                    and Restaurant.query.filter_by(id=data.order_rest_id).first():
                current_month_total += data.order_total
                rest_name = Restaurant.query.filter_by(id=data.order_rest_id).first().name
                try:
                    current_month_rests_total.update(
                        {rest_name: current_month_rests_total[rest_name] + data.order_total}
                    )
                except KeyError:
                    current_month_rests_total.update({rest_name: data.order_total})
        text += f'Общая сумма за {MONTHS[month]}: {current_month_total}р.\n'
        for rest in current_month_rests_total:
            text += f'Общая сумма заказов в ресторане {rest} за {MONTHS[month]} - ' \
                    f'{current_month_rests_total[rest]}р.\n'
    return text


def stat2():
    current_month = datetime.now(YKT).month
    first_day = datetime.today().replace(day=1, hour=0, minute=0, second=0).strftime('%s')
    today = datetime.now(YKT).strftime('%s')
    stat_data = Order.query.filter(Order.order_datetime.between(first_day, today)).order_by(Order.order_rest_id).all()
    rests_data, text = [], ''
    rest = Restaurant.query
    for data in stat_data:
        if ('Подтверждена' in data.order_state or 'Заказ принят рестораном' in data.order_state) and rest.filter_by(
                id=data.order_rest_id).first():
            rest_name = rest.filter_by(id=data.order_rest_id).first().name
            day = str(datetime.fromtimestamp(data.order_datetime).strftime("%d"))
            rests_data.append([rest_name, day, data.order_total, '{:02d}'.format(current_month)])
    for i in range(len(rests_data)):
        if i == 0 or (i != 0 and rests_data[i][0] != rests_data[i - 1][0]):
            text += f'{rests_data[i][0]}\n'
            text += f'{rests_data[i][1]}.{rests_data[i][3]} - {rests_data[i][2]} р.\n'
        elif i != 0 and rests_data[i][0] == rests_data[i - 1][0]:
            text += f'{rests_data[i][1]}.{rests_data[i][3]} - {rests_data[i][2]} р.\n'
    if not text:
        text = 'В этом месяце еще не было заказов'
    return text


def stat3():
    current_month = datetime.now(YKT).month
    first_day = datetime.today().replace(day=1, hour=0, minute=0, second=0).strftime('%s')
    today = datetime.now(YKT).strftime('%s')
    order_data = Order.query.filter(Order.order_datetime.between(first_day, today)).all()
    text = f'{MONTHS[current_month].capitalize()}\n'
    stat = {}
    days = []
    for data in order_data:
        day = int(datetime.fromtimestamp(data.order_datetime).strftime("%d"))
        if 'Подтверждена' in data.order_state or 'Заказ принят рестораном' in data.order_state:
            if day in days:
                stat.update({day: stat[day] + 1})
            else:
                stat.update({day: 1})
                days.append(day)
    if not stat:
        text += 'Заказов не было'
    for data in stat:
        text += f'{data}: {stat[data]}\n'
    return text


def stat4():
    orders = Order.query.filter((Order.order_state == "Отменен") | (Order.order_state == "Заказ отменен")).all()
    text = f'Всего отмененных заказов: {len(orders)}\n'
    for order in orders:
        text += Restaurant.query.filter_by(id=order.order_rest_id).first().name
        order_date = datetime.fromtimestamp(order.order_datetime).strftime("%d.%m.%Y")
        text += f' - {order_date}\n'
    return text


def stat5():
    first_day = datetime(datetime.now(YKT).year, 1, 1, 0, 0, 0).strftime('%s')
    today = datetime.now(YKT).strftime('%s')
    stat_data = History.query.filter(History.date.between(first_day, today)).all()
    current_month = datetime.now(YKT).month
    users = []
    text = f'{datetime.now(YKT).year} г.\n'
    for month in MONTHS:
        if month > current_month:
            break
        days = []
        count = 0
        text += f'{MONTHS[month].capitalize()}: '
        for data in stat_data:
            msg_month = int(datetime.fromtimestamp(data.date).strftime("%m"))
            dt = datetime.fromtimestamp(data.date).strftime("%d.%m.%Y %H:%M:%S")
            day = int(datetime.fromtimestamp(data.date).strftime("%d"))
            if msg_month == month and day not in days:
                dt_start = datetime.strptime(dt, "%d.%m.%Y %H:%M:%S").replace(hour=0, minute=0, second=0).strftime("%s")
                dt_end = datetime.strptime(dt, "%d.%m.%Y %H:%M:%S").replace(hour=23, minute=59, second=59).strftime(
                    "%s")
                query = History.query.filter(History.date.between(dt_start, dt_end)).with_entities(
                    History.chat_id).distinct().all()
                for uid in query:
                    if uid[0] not in users:
                        count += 1
                        users.append(uid[0])
                days.append(day)
        text += f'{count}\n'
    return text, users


def stat6():
    first_day = datetime(datetime.now(YKT).year, 1, 1, 0, 0, 0).strftime('%s')
    today = datetime.now(YKT).strftime('%s')
    stat_data = History.query.filter(History.date.between(first_day, today)).all()
    current_month = datetime.now(YKT).month
    users = []
    text = f'{datetime.now(YKT).year} г.\n'
    for month in MONTHS:
        if month > current_month:
            break
        days = []
        text += f'{MONTHS[month].capitalize()}:\n'
        for data in stat_data:
            msg_month = int(datetime.fromtimestamp(data.date).strftime("%m"))
            dt = datetime.fromtimestamp(data.date).strftime("%d.%m.%Y %H:%M:%S")
            day = int(datetime.fromtimestamp(data.date).strftime("%d"))
            if msg_month == month and day not in days:
                count = 0
                dt_start = datetime.strptime(dt, "%d.%m.%Y %H:%M:%S").replace(hour=0, minute=0, second=0).strftime("%s")
                dt_end = datetime.strptime(dt, "%d.%m.%Y %H:%M:%S").replace(hour=23, minute=59, second=59).strftime(
                    "%s")
                query = History.query.filter(History.date.between(dt_start, dt_end)).with_entities(
                    History.chat_id).distinct().all()
                for uid in query:
                    if uid[0] not in users:
                        count += 1
                        users.append(uid[0])
                days.append(day)
                if count != 0:
                    text += f'{datetime.fromtimestamp(data.date).strftime("%d.%m.%y")}: {count}\n'
    return text


def stat7():
    first_day = datetime(datetime.now(YKT).year, 1, 1, 0, 0, 0).strftime('%s')
    today = datetime.now(YKT).strftime('%s')
    stat_data = History.query.filter(History.date.between(first_day, today)).all()
    current_month = datetime.now(YKT).month
    text = f'{datetime.now(YKT).year} г.\n'
    for month in MONTHS:
        if month > current_month:
            break
        days = []
        visit_count = 0
        text += f'{MONTHS[month].capitalize()}: '
        for data in stat_data:
            msg_month = int(datetime.fromtimestamp(data.date).strftime("%m"))
            dt = datetime.fromtimestamp(data.date).strftime("%d.%m.%Y %H:%M:%S")
            day = int(datetime.fromtimestamp(data.date).strftime("%d"))
            if msg_month == month and day not in days:
                dt_start = datetime.strptime(dt, "%d.%m.%Y %H:%M:%S").replace(hour=0, minute=0, second=0).strftime("%s")
                dt_end = datetime.strptime(dt, "%d.%m.%Y %H:%M:%S").replace(hour=23, minute=59, second=59).strftime(
                    "%s")
                query = History.query.filter(History.date.between(dt_start, dt_end)).with_entities(
                    History.chat_id).distinct().all()
                visit_count += len(query)
                days.append(day)
        text += f'{visit_count}\n'
    return text


def stat8():
    first_day = datetime(datetime.now(YKT).year, 1, 1, 0, 0, 0).strftime('%s')
    today = datetime.now(YKT).strftime('%s')
    stat_data = History.query.filter(History.date.between(first_day, today)).all()
    current_month = datetime.now(YKT).month
    text = f'{datetime.now(YKT).year} г.\n'
    for month in MONTHS:
        if month > current_month:
            break
        days = []
        text += f'{MONTHS[month].capitalize()}:\n'
        for data in stat_data:
            msg_month = int(datetime.fromtimestamp(data.date).strftime("%m"))
            dt = datetime.fromtimestamp(data.date).strftime("%d.%m.%Y %H:%M:%S")
            day = int(datetime.fromtimestamp(data.date).strftime("%d"))
            if msg_month == month and day not in days:
                dt_start = datetime.strptime(dt, "%d.%m.%Y %H:%M:%S").replace(hour=0, minute=0, second=0).strftime("%s")
                dt_end = datetime.strptime(dt, "%d.%m.%Y %H:%M:%S").replace(hour=23, minute=59, second=59).strftime(
                    "%s")
                query = History.query.filter(History.date.between(dt_start, dt_end)).with_entities(
                    History.chat_id).distinct().all()
                visit_count = len(query)
                days.append(day)
                text += f'{datetime.fromtimestamp(data.date).strftime("%d.%m.%y")}: {visit_count}\n'
    return text
