import re
import sqlite3

import requests
import json
from settings import BOT_TOKEN

from flask import Flask
from flask import request

from telegram import Bot, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup

import keyboards

app = Flask(__name__)

BOT = Bot(BOT_TOKEN)
URL = f'https://api.telegram.org/bot{BOT_TOKEN}/'


def write_json(data, filename='answer.json'):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_text(text):
    pattern = r'(^Рестораны$)|(^Корзина$)|(^Оформить заказ$)|(\/\w+)|(\w+_[0-9]+$)'
    value = re.search(pattern, text).group()
    return value


def send_message(chat_id, text='bla-bla-bla', *args, **kwargs):
    url = URL + 'sendMessage'
    answer = {'chat_id': chat_id, 'text': text}
    r = requests.get(url, json=answer)
    return r.json()


def get_value(val, data):
    for key, value in data.items():
        if val == key:
            return True
    return False


@app.route('/', methods=['POST', 'GET'])
def index():
    if request.method == 'POST':
        r = request.get_json()
        write_json(json.loads(json.dumps(r)))
        if get_value("callback_query", r):
            # write callback handlers
            print('callback!')
            data = r['callback_query']['data']
            print(data)
            chat_id = r['callback_query']['message']['chat']['id']
            message_id = r['callback_query']['message']['message_id']
            rest_id = int(data.split('_')[1])
            categories_sql = "SELECT id, name FROM categories WHERE restaurant_id = ?"
            categories = sql_query(categories_sql, rest_id)
            buttons = []
            for category in categories:
                buttons.append(
                    [InlineKeyboardButton(category[1], callback_data=f'restaurant_{rest_id}_cat{category[0]}')])
            buttons.append(
                [InlineKeyboardButton('Узнать время доставки',
                                      callback_data=f'restaurant_{rest_id}_deliverytime')])
            buttons.append([InlineKeyboardButton('Назад', callback_data='back')])
            BOT.editMessageText(
                text='Пожалуйста выберите подходящую категорию',
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            # write message handlers
            print('message!')
            chat_id = r['message']['chat']['id']
            message = r['message']['text']
            # Берем имя, если поле имя пустое, то берем юзернейм
            if r["message"]["from"]["first_name"] != '':
                name = r["message"]["from"]["first_name"]
            else:
                name = r["message"]["from"]["username"]
            # Обработка события /start
            if parse_text(message) == '/start':
                text = f'Приветствую, {name}!\nВыбери что нужно.'
                keyboard = [
                    ['Рестораны', 'Корзина'],
                    [' ', 'Оформить заказ']
                ]
                markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                BOT.send_message(chat_id, text, reply_markup=markup)
            elif parse_text(message) == 'Рестораны':
                BOT.send_message(
                    chat_id=chat_id,
                    text='Пожалуйста, выберите ресторан:',
                    reply_markup=keyboards.rest_menu_keyboard())
            elif parse_text(message) == 'Корзина':
                BOT.send_message(chat_id, 'Вы выбрали корзину')
            elif parse_text(message) == 'Оформить заказ':
                BOT.send_message(chat_id, 'Вы выбрали оформить заказ')

    return '<h1>From bot you are welcome!</h1>'


def sql_query(sql_text, *args):
    """Возвращает результат запроса в БД"""
    con = sqlite3.connect('db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute(sql_text, args)
        sql_result = cur.fetchall()
        if 'INSERT' or 'DELETE' or 'UPDATE' in sql_text:
            con.commit()
        return sql_result
    except Exception:
        print('Запрос в БД не выполнен')
    con.close()


if __name__ == '__main__':
    app.run()
