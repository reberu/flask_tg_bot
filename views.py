from flask import render_template
from app import app
from telegram import Bot, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram import error

from settings import BOT_TOKEN

import sqlite3
import re
import requests
import json

from flask import request

BOT = Bot(BOT_TOKEN)
URL = f'https://api.telegram.org/bot{BOT_TOKEN}/'


@app.route('/', methods=['POST', 'GET'])
def index():
    if request.method == 'POST':
        r = request.get_json()
        write_json(json.loads(json.dumps(r)))
        try:
            # Callback handlers
            if get_value("callback_query", r):
                data = r['callback_query']['data']
                print('callback - ', data)
                buttons = []
                chat_id = r['callback_query']['message']['chat']['id']
                message_id = r['callback_query']['message']['message_id']
                if re.search(r'(restaurant_[0-9]+$)', data):
                    rest_id = int(data.split('_')[1])
                    categories_sql = "SELECT id, name FROM categories WHERE restaurant_id = ?"
                    categories = sql_query(categories_sql, rest_id)
                    for category in categories:
                        buttons.append(
                            [InlineKeyboardButton(category[1], callback_data=f'restaurant_{rest_id}_cat{category[0]}')])
                    buttons.append(
                        [InlineKeyboardButton('Узнать время доставки',
                                              callback_data=f'restaurant_{rest_id}_deliverytime')])
                    buttons.append([InlineKeyboardButton('Назад', callback_data='back_to_rest_kb')])
                    BOT.editMessageText(
                        text='Пожалуйста выберите подходящую категорию',
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                elif re.search(r'back_to_rest_kb', data):
                    BOT.editMessageText(
                        chat_id=chat_id,
                        text='Пожалуйста, выберите ресторан:',
                        message_id=message_id,
                        reply_markup=rest_menu_keyboard())
                elif re.search(r'(restaurant_[0-9]+_cat[0-9]+$)|'
                               r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_forward$)|'
                               r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_backward$)|'
                               r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_add$)|'
                               r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_rem$)', data):
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
                        if data.split('_')[5] == 'backward':
                            temp = int(data.split('_')[4])
                            if temp > 1:
                                current_id = temp - 1
                                print('backward event')
                        elif data.split('_')[5] == 'forward':
                            temp = int(data.split('_')[4])
                            if temp < len(sql_result):
                                current_id = temp + 1
                                print('forward event')
                        elif data.split('_')[5] == 'add':
                            print('add event')
                            current_id = int(data.split('_')[4])
                            dish_count = d_count_query(sql_result[current_id - 1][0], chat_id, data.split('_')[1])
                            if dish_count and dish_count > 0:
                                add_query = "UPDATE cart SET quantity = ? " \
                                            "WHERE name = ? and user_uid = ? and restaurant_id = ?;"
                                sql_query(add_query, dish_count + 1, sql_result[current_id - 1][0], chat_id,
                                          data.split('_')[1])
                            else:
                                print('add new item')
                                add_query = "INSERT INTO cart('name', 'price', 'quantity', 'user_uid', 'is_dish', " \
                                            "'is_water', 'dish_id', 'restaurant_id') VALUES(?, ?, ?, ?, ?, ?, ?, ?);"
                                sql_query(add_query, sql_result[current_id - 1][0], sql_result[current_id - 1][1], 1,
                                          chat_id, 1, 0, data.split('_')[4], data.split('_')[1])
                        elif data.split('_')[5] == 'rem':
                            print('rem event')
                            current_id = int(data.split('_')[4])
                            dish_count = d_count_query(sql_result[current_id - 1][0], chat_id, data.split('_')[1])
                            print(f'dish count {dish_count}, current_id {current_id}')
                            if dish_count and dish_count > 1:
                                print('UPDATE')
                                rem_query = "UPDATE cart SET quantity = ? " \
                                            "WHERE name = ? and user_uid = ? and restaurant_id = ?;"
                                sql_query(rem_query, dish_count - 1, sql_result[current_id - 1][0], chat_id,
                                          data.split('_')[1])
                            elif dish_count and dish_count == 1:
                                print('DELETE')
                                rem_query = "DELETE FROM cart WHERE name = ? and user_uid = ? and restaurant_id = ?;"
                                sql_query(rem_query, sql_result[current_id - 1][0], chat_id, data.split('_')[1])
                            else:
                                pass
                    else:
                        pass

                    text += f'<a href="{sql_result[current_id - 1][4]}">.</a>'
                    text += f'\n<b>{sql_result[current_id - 1][0]}</b>'
                    text += f'\nОписание - {sql_result[current_id - 1][2]}'
                    text += f'\nСостав: {sql_result[current_id - 1][3]}'
                    text += f'\nСтоимость - {sql_result[current_id - 1][1]} р.'

                    cart_count_sql = "SELECT quantity FROM cart WHERE user_uid = ? and dish_id = ?;"
                    dish_id = sql_result[current_id - 1][5]
                    try:
                        cart_count = sql_query(cart_count_sql, chat_id, dish_id)[0][0]
                    except TypeError:
                        cart_count = 0
                    except IndexError:
                        cart_count = 0

                    buttons.append([
                        InlineKeyboardButton('⬆️',
                                             callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{current_id}_add'),
                        InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                        InlineKeyboardButton('⬇️',
                                             callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{current_id}_rem')
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
                    # buttons.append([InlineKeyboardButton('Добавить в избранное', callback_data='to_favorites')])
                    buttons.append([InlineKeyboardButton('В категории меню', callback_data=f'restaurant_{rest_id}')])
                    buttons.append(
                        [InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart')])
                    buttons.append([InlineKeyboardButton(f'В список ресторанов', callback_data='back_to_rest_kb')])
                    BOT.edit_message_text(
                        text=text,
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_markup=InlineKeyboardMarkup(buttons),
                        parse_mode=ParseMode.HTML
                    )

                elif data == 'to_rest':
                    BOT.editMessageText(
                        chat_id=chat_id,
                        message_id=message_id,
                        text='Пожалуйста, выберите ресторан:',
                        reply_markup=rest_menu_keyboard())

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
                elif re.search(r'(^cart$)|'
                               r'(^cart_id_[0-9]+$)|'
                               r'(^cart_id_[0-9]+_clear$)|'
                               r'(^cart_purge$)|'
                               r'(^cart_id_[0-9]+_add$)|'
                               r'(^cart_id_[0-9]+_remove$)|', data):
                    cart_query = """
                                SELECT id, name, price, quantity, is_dish, is_water, dish_id, restaurant_id, water_id
                                FROM cart WHERE user_uid = ?;
                            """
                    cart = sql_query(cart_query, chat_id)

                    if len(cart) == 0:
                        text = 'Ваша корзина пуста'
                        buttons = [[InlineKeyboardButton('Назад', callback_data='to_rest')]]
                        BOT.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    else:
                        rest_query = "SELECT name FROM restaurants WHERE id = ?;"
                        rest = sql_query(rest_query, cart[0][7])[0][0]
                        dishes_query = "SELECT id, name, description, composition, img_link FROM dishes;"
                        dishes = sql_query(dishes_query)
                        total = 0
                        current_id = cart[0][0]
                        if re.search(r'(^cart_id_[0-9]+$)', data):
                            current_id = int(data.split('_')[2])
                        elif re.search(r'(^cart_id_[0-9]+_clear$)', data):
                            current_id = int(data.split('_')[2])
                            clear_query = "DELETE FROM cart WHERE id = ?;"
                            sql_query(clear_query, int(data.split('_')[2]))
                            cart = sql_query(cart_query, chat_id)
                            current_id = cart[0][0]
                        elif re.search(r'(^cart_purge$)', data):
                            purge_query = "DELETE FROM cart WHERE user_uid = ?;"
                            sql_query(purge_query, chat_id)
                            text = 'Ваша корзина пуста'
                            buttons = [[InlineKeyboardButton('Назад', callback_data='to_rest')]]
                            BOT.edit_message_text(
                                chat_id=chat_id,
                                message_id=message_id,
                                text=text,
                                reply_markup=InlineKeyboardMarkup(buttons)
                            )
                        elif re.search(r'(^cart_id_[0-9]+_add$)', data):
                            current_id = int(data.split('_')[2])
                            for i in cart:
                                if current_id == i[0]:
                                    query = "UPDATE cart SET quantity = ?;"
                                    sql_query(query, i[3] + 1)
                        elif re.search(r'(^cart_id_[0-9]+_remove$)', data):
                            current_id = int(data.split('_')[2])
                            for i in cart:
                                if current_id == i[0]:
                                    if i[3] > 1:
                                        query = "UPDATE cart SET quantity = ?;"
                                        sql_query(query, i[3] - 1)
                                    else:
                                        query = "DELETE FROM cart WHERE id = ?;"
                                        sql_query(query, int(data.split('_')[2]))
                                        cart = sql_query(cart_query, chat_id)
                                        current_id = cart[0][0]
                        print('show_cart handler')
                        print(cart)
                        try:
                            print('current_id', current_id)
                        except UnboundLocalError:
                            print("UnboundLocalError: local variable 'current_id' referenced before assignment")
                        try:
                            for i in cart:
                                if current_id == i[0]:
                                    cart_count = i[3]
                            print('cart_count', cart_count)
                        except UnboundLocalError:
                            print("UnboundLocalError: local variable 'current_id' referenced before assignment")

                        buttons = []
                        if current_id:
                            cart_buttons = [InlineKeyboardButton('❌', callback_data=f'cart_id_{current_id}_clear')]
                        else:
                            cart_buttons = [InlineKeyboardButton('❌', callback_data=f'cart_id_{cart[0][0]}_clear')]
                        text = '<b>Корзина</b>\n'
                        for i in range(len(cart)):
                            cart_buttons.append(InlineKeyboardButton(f'{i + 1}', callback_data=f'cart_id_{cart[i][0]}'))
                            total += cart[i][2] * cart[i][3]
                        cart_dish_id = None
                        for i in cart:
                            if i[0] == current_id:
                                cart_dish_id = i[6]
                        for dish in dishes:

                            if dish[0] == cart_dish_id:
                                text += f'<a href="{dish[4]}">{rest}</a>'
                                # text += f'\n<b>{dish[1]}</b>'
                                text += f'\nОписание - {dish[2]}'
                                text += f'\nСостав: {dish[3]}'
                                text += f'\nСтоимость - {cart[0][2]}'
                        buttons.append(cart_buttons)
                        buttons.append([
                            InlineKeyboardButton('⬆️',
                                                 callback_data=f'cart_id_{cart[0][0]}_add'),
                            InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                            InlineKeyboardButton('⬇️',
                                                 callback_data=f'cart_id_{cart[0][0]}_remove')
                        ])
                        buttons.append([
                            InlineKeyboardButton('Очистить️',
                                                 callback_data=f'cart_purge'),
                            InlineKeyboardButton('Меню️',
                                                 callback_data=f'restaurant_{cart[0][7]}')
                        ])
                        buttons.append([InlineKeyboardButton(f'Оформить заказ на сумму {total}',
                                                             callback_data='cart_confirm')])
                        BOT.edit_message_text(
                            text=text,
                            chat_id=chat_id,
                            message_id=message_id,
                            reply_markup=InlineKeyboardMarkup(buttons),
                            parse_mode=ParseMode.HTML
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
                        reply_markup=rest_menu_keyboard())
                elif parse_text(message) == 'Корзина':
                    cart_query = """
                                                    SELECT id, name, price, quantity, is_dish, is_water, dish_id, restaurant_id, water_id
                                                    FROM cart WHERE user_uid = ?;
                                                """
                    cart = sql_query(cart_query, chat_id)

                    if len(cart) == 0:
                        text = 'Ваша корзина пуста'
                        buttons = [[InlineKeyboardButton('Назад', callback_data='to_rest')]]
                        # query.edit_message_text(
                        BOT.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    else:
                        rest_query = "SELECT name FROM restaurants WHERE id = ?;"
                        rest = sql_query(rest_query, cart[0][7])[0][0]
                        dishes_query = "SELECT id, name, description, composition, img_link FROM dishes;"
                        dishes = sql_query(dishes_query)
                        total = 0

                        current_id = cart[0][0]
                        print('show_cart handler')
                        print(cart)
                        print(current_id)
                        for i in cart:
                            if current_id == i[0]:
                                cart_count = i[3]

                        buttons = []
                        cart_buttons = [InlineKeyboardButton('❌', callback_data=f'cart_id_{current_id}_clear')]
                        text = '<b>Корзина</b>\n'
                        for i in range(len(cart)):
                            cart_buttons.append(InlineKeyboardButton(f'{i + 1}', callback_data=f'cart_id_{cart[i][0]}'))
                            total += cart[i][2] * cart[i][3]
                        cart_dish_id = None
                        for i in cart:
                            if i[0] == current_id:
                                cart_dish_id = i[6]
                        for dish in dishes:

                            if dish[0] == cart_dish_id:
                                text += f'<a href="{dish[4]}">{rest}</a>'
                                # text += f'\n<b>{dish[1]}</b>'
                                text += f'\nОписание - {dish[2]}'
                                text += f'\nСостав: {dish[3]}'
                                text += f'\nСтоимость - {cart[0][2]}'
                        buttons.append(cart_buttons)
                        buttons.append([
                            InlineKeyboardButton('⬆️',
                                                 callback_data=f'cart_id_{cart[0][0]}_add'),
                            InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                            InlineKeyboardButton('⬇️',
                                                 callback_data=f'cart_id_{cart[0][0]}_remove')
                        ])
                        buttons.append([
                            InlineKeyboardButton('Очистить️',
                                                 callback_data=f'cart_purge'),
                            InlineKeyboardButton('Меню️',
                                                 callback_data=f'restaurant_{cart[0][7]}')
                        ])
                        buttons.append([InlineKeyboardButton(f'Оформить заказ на сумму {total}',
                                                             callback_data='cart_confirm')])
                        BOT.send_message(
                            text=text,
                            chat_id=chat_id,
                            reply_markup=InlineKeyboardMarkup(buttons),
                            parse_mode=ParseMode.HTML
                        )
                elif parse_text(message) == 'Оформить заказ':
                    BOT.send_message(chat_id, 'Вы выбрали оформить заказ')
                elif parse_text(message) == 'Статистика':
                    BOT.send_message(chat_id=chat_id, text='СТАТИСТИКА', reply_markup=stat_menu_keyboard())
                elif parse_text(message) == 'Тест':
                    BOT.send_message(chat_id=chat_id, text='test', parse_mode=ParseMode.HTML)
        except error.BadRequest:
            print('BAD REQUEST!')
    return render_template('index.html')


def write_json(data, filename='answer.json'):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_text(text):
    pattern = r'(^Рестораны$)|(^Корзина$)|(^Оформить заказ$)|(\/\w+)|(\w+_[0-9]+$)|(^Статистика$)|(^Тест$)'
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


def d_count_query(dish_name, uid, r_id):
    """Возвращает количество блюд в корзине по признакам name, user_uid, restaurant_id"""
    dish_count_query = "SELECT quantity FROM cart " \
                       "WHERE name = ? and user_uid = ? and restaurant_id = ?;"
    try:
        return sql_query(dish_count_query, dish_name, uid, r_id)[0][0]
    except Exception:
        pass


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
    except sqlite3.Error as er:
        print('Запрос в БД не выполнен')
        print('SQLite error: %s' % (' '.join(er.args)))
        print("Exception class is: ", er.__class__)
    con.close()


def rest_menu_keyboard():
    """Возвращает меню с наименованиями ресторанов"""

    rest_sql = "SELECT id, name FROM restaurants;"

    restaurants = sql_query(rest_sql)
    keyboard = []
    for restaurant in restaurants:
        keyboard.append([InlineKeyboardButton(f'{restaurant[1]}', callback_data=f'restaurant_{restaurant[0]}')])
    # keyboard.append([InlineKeyboardButton('Назад', callback_data='back')])
    return InlineKeyboardMarkup(keyboard)


def stat_menu_keyboard():
    """Возвращает меню статистики"""
    keyboard = []
    for i in range(1, 8):
        keyboard.append([InlineKeyboardButton(f'{i}', callback_data=f'stat_{i}')])
    return InlineKeyboardMarkup(keyboard)
