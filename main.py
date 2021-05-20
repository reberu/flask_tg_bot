import re
import sqlite3

import requests
import json
from settings import BOT_TOKEN

from flask import Flask
from flask import request

from telegram import Bot, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode

import keyboards

app = Flask(__name__)

BOT = Bot(BOT_TOKEN)
URL = f'https://api.telegram.org/bot{BOT_TOKEN}/'


def write_json(data, filename='answer.json'):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_text(text):
    pattern = r'(^Рестораны$)|(^Корзина$)|(^Оформить заказ$)|(\/\w+)|(\w+_[0-9]+$)|(^Статистика$)'
    try:
        value = re.search(pattern, text).group()
    except AttributeError:
        return None
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
            buttons = []
            chat_id = r['callback_query']['message']['chat']['id']
            message_id = r['callback_query']['message']['message_id']
            if re.search(r'restaurant_[0-9]+$', data):
                print(data)
                rest_id = int(data.split('_')[1])
                categories_sql = "SELECT id, name FROM categories WHERE restaurant_id = ?"
                categories = sql_query(categories_sql, rest_id)
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
            elif re.search(r'(restaurant_[0-9]+_cat[0-9]+$)|'
                           r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_forward$)|'
                           r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_backward$)|'
                           r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_add$)', data):
                rest_id, cat_id = int(data.split('_')[1]), int(data.split('_')[2][3:])
                cat_sql = "SELECT name FROM categories WHERE id = ?"
                category = sql_query(cat_sql, cat_id)[0][0]
                rest_name = sql_query("SELECT name FROM restaurants WHERE id = ?;", rest_id)[0][0]
                dishes_sql = """
                        SELECT name, cost, description, composition, img_link, id, category 
                        FROM dishes WHERE id_rest = ? and category = ?;
                    """
                sql_result = sql_query(dishes_sql, rest_id, category)
                text = f'{rest_name}\n'
                current_id = 1
                # Логика прокрутки назад-вперед
                if len(data.split('_')) == 6:
                    if '_backward' in data:
                        temp = int(data.split('_')[4])
                        if temp > 1:
                            current_id = temp - 1
                            print('backward event')
                    elif '_forward' in data:
                        temp = int(data.split('_')[4])
                        if temp < len(sql_result):
                            current_id = temp + 1
                            print('forward event')
                else:
                    current_id = 1

                if len(data.split('_')) == 6 and '_add' in data:
                    print('add event')
                    add_query = "INSERT INTO cart(' \
                                    'name, price, quantity, user_uid, is_dish, is_water, dish_id, restaurant_id') ' \
                                    'VALUES(?, ?, ?, ?, ?, ?, ?, ?);"
                    print(sql_result[current_id - 1][0], sql_result[current_id - 1][1], 1,
                          chat_id, 1, 0, data.split('_')[4], data.split('_')[1])
                    sql_query(add_query, sql_result[current_id - 1][0], sql_result[current_id - 1][1], 1,
                              chat_id, 1, 0, data.split('_')[4], data.split('_')[1])

                # Логика добавления и убавления товаров
                # if 'add' in data.split('_'):

                text += f'<a href="{sql_result[current_id - 1][4]}">.</a>'
                text += f'\n<b>{sql_result[current_id - 1][0]}</b>'
                text += f'\nОписание - {sql_result[current_id - 1][2]}'
                text += f'\nСостав: {sql_result[current_id - 1][3]}'
                text += f'\nСтоимость - {sql_result[current_id - 1][1]} р.'

                cart_count_sql = "SELECT quantity FROM cart WHERE user_uid = ? and dish_id = ?;"
                dish_id = sql_result[current_id - 1][5]
                print(chat_id, dish_id)
                try:
                    cart_count = sql_query(cart_count_sql, chat_id, dish_id)[0][0]
                except TypeError:
                    cart_count = 0
                except IndexError:
                    cart_count = 0

                buttons.append([
                    # InlineKeyboardButton('⬆️ добавить', callback_data='to_cart'),
                    InlineKeyboardButton('⬆️ добавить',
                                         callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{current_id}_add'),
                    InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                    InlineKeyboardButton('⬇️ убавить', callback_data='remove_from_cart')
                ])

                buttons.append([
                    InlineKeyboardButton('⬅️',
                                         callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{current_id}_backward'),
                    InlineKeyboardButton(f'{current_id}/{len(sql_result)}', callback_data='None'),
                    InlineKeyboardButton('➡️',
                                         callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{current_id}_forward')
                ])

                total = 0
                total_sql = "SELECT price, quantity FROM cart WHERE user_uid = ?;"
                total_sql_result = sql_query(total_sql, chat_id)
                if not total_sql_result:
                    total = 0
                else:
                    for sub in total_sql_result:
                        total += sub[0] * sub[1]
                buttons.append([InlineKeyboardButton('Добавить в избранное', callback_data='to_favorites')])
                buttons.append([InlineKeyboardButton('В категории меню', callback_data=f'rest_{rest_id}')])
                buttons.append(
                    [InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='show_cart')])
                BOT.edit_message_text(
                    text=text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=ParseMode.HTML
                )
            elif re.search(r'^stat_[0-9]+$', data):
                stat_id = int(data.split('_')[1])
                if stat_id == 1:
                    stat_query = 'SELECT * FROM orders;'
                    stat_data = sql_query(stat_query)
                    BOT.send_message(chat_id=chat_id, text=f'Количество заказов в сумме\n{stat_data}')
                elif stat_id == 2:
                    stat_query = 'SELECT * FROM orders;'
                    stat_data = sql_query(stat_query)
                    BOT.send_message(chat_id=chat_id, text=f'Количество заказов по ресторанам\n{stat_data}')
                elif stat_id == 3:
                    stat_query = 'SELECT * FROM orders;'
                    stat_data = sql_query(stat_query)
                    BOT.send_message(chat_id=chat_id, text=f'Количество заказов в общем\n{stat_data}')
                elif stat_id == 4:
                    stat_query = 'SELECT * FROM orders;'
                    stat_data = sql_query(stat_query)
                    BOT.send_message(chat_id=chat_id, text=f'Статистика заказов блюд\n{stat_data}')
                elif stat_id == 5:
                    stat_query = 'SELECT * FROM orders;'
                    stat_data = sql_query(stat_query)
                    BOT.send_message(chat_id=chat_id, text=f'Количество изменений в заказе\n{stat_data}')
                elif stat_id == 6:
                    stat_query = 'SELECT * FROM orders;'
                    stat_data = sql_query(stat_query)
                    BOT.send_message(chat_id=chat_id, text=f'Количество отмен заказов\n{stat_data}')
                elif stat_id == 7:
                    stat_query = 'SELECT * FROM users;'
                    stat_data = sql_query(stat_query)
                    BOT.send_message(chat_id=chat_id, text=f'Количество посещений\n{stat_data}')
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
            elif parse_text(message) == 'Статистика':
                BOT.send_message(chat_id=chat_id, text='СТАТИСТИКА', reply_markup=keyboards.stat_menu_keyboard())

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
