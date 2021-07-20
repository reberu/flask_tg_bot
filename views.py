import telegram.error
from flask import render_template
from telegram import Bot, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram import error

from settings import BOT_TOKEN

import sqlite3
import re
import requests
import json

from flask import request

from app import app, db
from models import Restaurant, Category, Dish, Cart, User

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
                    categories = db.session.query(Category).filter_by(restaurant_id=rest_id).all()
                    for category in categories:
                        buttons.append(
                            [InlineKeyboardButton(category.name,
                                                  callback_data=f'restaurant_{rest_id}_cat{category.id}')])
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

                elif re.search(r'(restaurant_[0-9]+_cat[0-9]+$)', data) or re.search(r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_add_[0-9]+_[0-9]+$)', data) or re.search(r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_rem_[0-9]+_[0-9]+$)', data):
                    print('restaurant callback', data)
                    rest_id, cat_id = int(data.split('_')[1]), int(data.split('_')[2][3:])
                    category = db.session.query(Category.name).filter_by(id=cat_id).first()[0]
                    rest_name = db.session.query(Restaurant.name).filter_by(id=rest_id).first()[0]
                    sql_result = db.session.query(Dish).filter_by(id_rest=rest_id, category=category).all()

                    current_id = 1

                    if len(data.split('_')) == 8:
                        # restaurant_{rest_id}_cat{cat_id}_dish_{current_id}_add_{chat_id}_{message_id}
                        dish_id = int(data.split('_')[4])
                        cur_chat_id = int(data.split('_')[6])
                        cur_msg_id = int(data.split('_')[7])
                        dish_name = ''
                        cur_id = 0
                        for i, item in enumerate(sql_result, start=1):
                            if item.id == dish_id:
                                dish_name = item.name
                                cur_id = i
                        # dish_count = d_count_query(dish_name, cur_chat_id, data.split('_')[1])
                        # dish_count_query = "SELECT quantity FROM cart " \
                        #                    "WHERE name = ? and user_uid = ? and restaurant_id = ?;"
                        print(dish_name, cur_chat_id, data.split('_')[1])
                        try:
                            dish_count = db.session.query(Cart.quantity).filter_by(name=dish_name, user_uid=cur_chat_id, restaurant_id=data.split('_')[1]).first()[0]
                        except TypeError:
                            dish_count = 0
                        print(cur_id, cur_chat_id, cur_msg_id, dish_count)
                        if data.split('_')[5] == 'add':
                            if dish_count and dish_count > 0:
                                cart_item_updater = db.session.query(Cart).filter_by(
                                    name=sql_result[cur_id-1].name,
                                    user_uid=cur_chat_id,
                                    restaurant_id=data.split('_')[1]).first()
                                cart_item_updater.quantity += 1
                                db.session.commit()
                            else:
                                print('add new item')
                                cart_item = Cart(
                                    name=dish_name,
                                    price=sql_result[cur_id-1].cost,
                                    quantity=1,
                                    user_uid=cur_chat_id,
                                    is_dish=1,
                                    is_water=0,
                                    dish_id=data.split('_')[4],
                                    restaurant_id=data.split('_')[4]
                                )
                                db.session.add(cart_item)
                                db.session.commit()
                        elif data.split('_')[5] == 'rem':
                            if dish_count and dish_count > 1:
                                print('UPDATE')
                                cart_item_updater = db.session.query(Cart).filter_by(
                                    name=sql_result[cur_id-1].name,
                                    user_uid=cur_chat_id,
                                    restaurant_id=data.split('_')[1]).first()
                                cart_item_updater.quantity -= 1
                                db.session.commit()
                            elif dish_count and dish_count == 1:
                                print('DELETE')
                                db.session.query(Cart).filter_by(name=dish_name, user_uid=cur_chat_id,
                                                                 restaurant_id=data.split('_')[1]).delete()
                                db.session.commit()
                        text = f'{rest_name}\n'
                        text += f'<a href="{sql_result[cur_id-1].img_link}">.</a>'
                        text += f'\n<b>{dish_name}</b>'
                        text += f'\nОписание - {sql_result[cur_id-1].description}'
                        text += f'\nСостав: {sql_result[cur_id-1].composition}'
                        text += f'\nСтоимость - {sql_result[cur_id-1].cost} р.'

                        dish_id = sql_result[cur_id-1].id
                        try:
                            cart_count = db.session.query(Cart.quantity).filter_by(user_uid=cur_chat_id,
                                                                                   dish_id=dish_id).first()[0]
                        except TypeError:
                            cart_count = 0
                        except IndexError:
                            cart_count = 0
                        print('cart_count', dish_name, cart_count)
                        buttons = [[
                            InlineKeyboardButton('-️',
                                                 callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{cur_id}_rem_{cur_chat_id}_{message_id}'),
                            InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                            InlineKeyboardButton('+️',
                                                 callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{cur_id}_add_{cur_chat_id}_{message_id}')
                        ]]
                        total = 0
                        cart_items = db.session.query(Cart).filter_by(user_uid=cur_chat_id).all()
                        if cart_items:
                            for item in cart_items:
                                total += item.price * item.quantity
                        buttons.append(
                            [InlineKeyboardButton('Главное меню', callback_data=f'restaurant_{rest_id}')])
                        buttons.append(
                            [InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart')])
                        BOT.editMessageText(
                            chat_id=cur_chat_id,
                            text=text,
                            message_id=cur_msg_id,
                            reply_markup=InlineKeyboardMarkup(buttons),
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        for current_id, dish in enumerate(sql_result, start=1):
                            text = f'{rest_name}\n'
                            text += f'<a href="{dish.img_link}">.</a>'
                            text += f'\n<b>{dish.name}</b>'
                            text += f'\nОписание - {dish.description}'
                            text += f'\nСостав: {dish.composition}'
                            text += f'\nСтоимость - {dish.cost} р.'


                            try:
                                cart_count = db.session.query(Cart.quantity).filter_by(user_uid=chat_id, dish_id=dish.id).first()[0]
                            except TypeError:
                                cart_count = 0
                            except IndexError:
                                cart_count = 0
                            print(dish)
                            buttons = [[
                                InlineKeyboardButton('-',
                                                     callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{dish.id}_rem_{chat_id}_{message_id + current_id}'),
                                InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                                InlineKeyboardButton('+️',
                                                     callback_data=f'restaurant_{rest_id}_cat{cat_id}_dish_{dish.id}_add_{chat_id}_{message_id + current_id}')
                            ]]
                            print(message_id + current_id)
                            total = 0

                            cart_items = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                            if cart_items:
                                for item in cart_items:
                                    total += item.price * item.quantity
                            buttons.append(
                                [InlineKeyboardButton('Главное меню', callback_data=f'restaurant_{rest_id}')])
                            buttons.append(
                                [InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart')])

                            BOT.send_message(
                                text=text,
                                chat_id=chat_id,
                                reply_markup=InlineKeyboardMarkup(buttons),
                                parse_mode=ParseMode.HTML
                            )
                elif re.search(r'(^cart$)|'
                               r'(^cart_id_[0-9]+$)|'
                               r'(^cart_id_[0-9]+_clear$)|'
                               r'(^cart_purge$)|'
                               r'(^cart_id_[0-9]+_add$)|'
                               r'(^cart_id_[0-9]+_remove$)', data):
                    # cart_query = """
                    #             SELECT id, name, price, quantity, is_dish, is_water, dish_id, restaurant_id, water_id
                    #             FROM cart WHERE user_uid = ?;
                    #         """
                    # cart = sql_query(cart_query, chat_id)
                    cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()

                    if len(cart) == 0:
                        text = 'Ваша корзина пуста'
                        buttons = [[InlineKeyboardButton('Назад', callback_data='to_rest')]]
                        BOT.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    else:
                        # rest_query = "SELECT name FROM restaurants WHERE id = ?;"
                        # rest = sql_query(rest_query, cart[0][7])[0][0]
                        rest = db.session.query(Restaurant.name).filter_by(id=cart[0].restaurant_id).first()[0]
                        # dishes_query = "SELECT id, name, description, composition, img_link FROM dishes;"
                        # dishes = sql_query(dishes_query)
                        total = 0
                        current_id = cart[0].id
                        if re.search(r'(^cart_id_[0-9]+$)', data):
                            current_id = int(data.split('_')[2])
                        elif re.search(r'(^cart_id_[0-9]+_clear$)', data):
                            current_id = int(data.split('_')[2])
                            # clear_query = "DELETE FROM cart WHERE id = ?;"
                            # sql_query(clear_query, int(data.split('_')[2]))
                            db.session.query(cart).filter_by(id=current_id).delete()
                            db.session.commit()
                            current_id = cart[0].id
                        elif re.search(r'(^cart_purge$)', data):
                            # purge_query = "DELETE FROM cart WHERE user_uid = ?;"
                            # sql_query(purge_query, chat_id)
                            db.session.query(cart).filter_by(user_uid=chat_id).delete()
                            db.session.commit()
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
                            for item in cart:
                                if current_id == item.id:
                                    # query = "UPDATE cart SET quantity = ?;"
                                    # sql_query(query, i[3] + 1)
                                    item.quantity += 1
                            db.session.commit()
                        elif re.search(r'(^cart_id_[0-9]+_remove$)', data):
                            current_id = int(data.split('_')[2])
                            for item in cart:
                                if current_id == item.id:
                                    if item.quantity > 1:
                                        # query = "UPDATE cart SET quantity = ?;"
                                        # sql_query(query, i[3] - 1)
                                        item.quantity -= 1
                                    else:
                                        # query = "DELETE FROM cart WHERE id = ?;"
                                        # sql_query(query, int(data.split('_')[2]))
                                        # cart = sql_query(cart_query, chat_id)
                                        db.session.query(Cart).filter_by(id=current_id).delete()
                            db.session.commit()
                            current_id = cart[0].id
                        print('show_cart handler')
                        print(cart)
                        try:
                            print('current_id', current_id)
                        except UnboundLocalError:
                            print("UnboundLocalError: local variable 'current_id' referenced before assignment")
                        try:
                            for item in cart:
                                if current_id == item.id:
                                    cart_count = item.quantity
                            print('cart_count', cart_count)
                        except UnboundLocalError:
                            print("UnboundLocalError: local variable 'current_id' referenced before assignment")

                        buttons = []
                        if current_id:
                            cart_buttons = [InlineKeyboardButton('❌', callback_data=f'cart_id_{current_id}_clear')]
                        else:
                            cart_buttons = [InlineKeyboardButton('❌', callback_data=f'cart_id_{cart[0].id}_clear')]
                        text = '<b>Корзина</b>\n'
                        cart_dish_id = None
                        for i, item in enumerate(cart, start=1):
                            cart_buttons.append(InlineKeyboardButton(f'{i}', callback_data=f'cart_id_{item.id}'))
                            total += item.quantity * item.price

                            if item.id == current_id:
                                cart_dish_id = item.dish_id
                        dish = db.session.query(Dish).filter_by(id=cart_dish_id).first()

                        text += f'<a href="{dish.img_link}">{rest}</a>'
                        text += f'\nОписание - {dish.description}'
                        text += f'\nСостав: {dish.composition}'
                        text += f'\nСтоимость - {dish.cost}'
                        buttons.append(cart_buttons)
                        buttons.append([
                            InlineKeyboardButton('-',
                                                 callback_data=f'cart_id_{cart[0].id}_remove'),
                            InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                            InlineKeyboardButton('+',
                                                 callback_data=f'cart_id_{cart[0].id}_add')
                        ])
                        buttons.append([
                            InlineKeyboardButton('Очистить️',
                                                 callback_data=f'cart_purge'),
                            InlineKeyboardButton('Меню️',
                                                 callback_data=f'restaurant_{cart[0].restaurant_id}')
                        ])
                        buttons.append([InlineKeyboardButton(f'Оформить заказ на сумму {total}',
                                                             callback_data='cart_confirm')])
                        BOT.send_message(
                            text=text,
                            chat_id=chat_id,
                            # message_id=message_id,
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

            else:
                # write message handlers
                try:
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
                    elif parse_text(message) == 'Рестораны' or parse_text(message) == '/restaurants':
                        BOT.send_message(
                            chat_id=chat_id,
                            text='Пожалуйста, выберите ресторан:',
                            reply_markup=rest_menu_keyboard())
                    elif parse_text(message) == 'Корзина' or parse_text(message) == '/show_cart':
                        cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                        if len(cart) == 0:
                            text = 'Ваша корзина пуста'
                            buttons = [[InlineKeyboardButton('Назад', callback_data='to_rest')]]
                            BOT.send_message(
                                chat_id=chat_id,
                                text=text,
                                reply_markup=InlineKeyboardMarkup(buttons)
                            )
                        else:
                            rest = db.session.query(Restaurant.name).filter_by(id=cart[0].id).first()[0]
                            dishes = db.session.query(Dish).all()
                            total = 0

                            current_id = cart[0].id
                            print('show_cart handler')
                            print(cart)
                            print(current_id)
                            cart_count = 0
                            for i in cart:
                                if current_id == i.id:
                                    cart_count = i.quantity

                            buttons = []
                            cart_buttons = [InlineKeyboardButton('❌', callback_data=f'cart_id_{current_id}_clear')]
                            text = '<b>Корзина</b>\n'
                            for i, item in enumerate(cart, start=1):
                                cart_buttons.append(InlineKeyboardButton(f'{i}', callback_data=f'cart_id_{item.id}'))
                                total += item.price * item.quantity
                            cart_dish_id = None
                            for item in cart:
                                if item.id == current_id:
                                    cart_dish_id = item.dish_id
                            for dish in dishes:

                                if dish.id == cart_dish_id:
                                    text += f'<a href="{dish.img_link}">{rest}</a>'
                                    text += f'\nОписание - {dish.description}'
                                    text += f'\nСостав: {dish.composition}'
                                    text += f'\nСтоимость - {cart[0].price}'
                            buttons.append(cart_buttons)
                            buttons.append([
                                InlineKeyboardButton('⬆️',
                                                     callback_data=f'cart_id_{cart[0].id}_add'),
                                InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                                InlineKeyboardButton('⬇️',
                                                     callback_data=f'cart_id_{cart[0].id}_remove')
                            ])
                            buttons.append([
                                InlineKeyboardButton('Очистить️',
                                                     callback_data=f'cart_purge'),
                                InlineKeyboardButton('Меню️',
                                                     callback_data=f'restaurant_{cart[0].restaurant_id}')
                            ])
                            buttons.append([InlineKeyboardButton(f'Оформить заказ на сумму {total}',
                                                                 callback_data='cart_confirm')])
                            BOT.send_message(
                                text=text,
                                chat_id=chat_id,
                                reply_markup=InlineKeyboardMarkup(buttons),
                                parse_mode=ParseMode.HTML
                            )
                    elif parse_text(message) == '/show_contract':
                        BOT.send_message(chat_id, 'Ссылка на договор')
                    elif parse_text(message) == 'Оформить заказ':
                        BOT.send_message(chat_id, 'Вы выбрали оформить заказ')
                    elif parse_text(message) == 'Статистика':
                        BOT.send_message(chat_id=chat_id, text='СТАТИСТИКА', reply_markup=stat_menu_keyboard())
                    elif parse_text(message) == 'Тест':
                        BOT.send_message(chat_id=chat_id, text='test', parse_mode=ParseMode.HTML)
                except telegram.error.Unauthorized:
                    pass
        except KeyError:
            print('KeyError', r)
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
