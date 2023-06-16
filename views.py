import json
import os
from datetime import datetime
from itertools import chain
from os import mkdir
from os.path import isdir

import telebot.types
from PIL import Image
from flask import render_template, flash, redirect, url_for, abort, send_from_directory
from sqlalchemy import func

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, Update, WebAppInfo, CallbackQuery
from telebot.util import antiflood

from handlers import restaurant_callback, cart_callback, order_callback, other_callback, favorites_callback
from utils import check_user, write_history, rest_menu_keyboard, stat5, stat8, stat7, stat6, stat4, stat3, stat2, stat1

from forms import LoginForm, DishForm, CategoryForm, DishDeleteForm, RestaurantForm, CategoryDeleteForm, \
    RestaurantDeleteForm, RestaurantEditForm, AdminAddForm, RestaurantDeliveryTermsForm, \
    RestaurantDeliveryTermsEditForm, SubcategoryForm, SpecialDishForm, PromoDishForm, PromoDishDeleteForm, \
    SpecialDishDeleteForm, DishEditForm, SubcategoryDeleteForm, SearchWordForm, SearchDishForm, SearchDishDelForm, \
    SearchWordDelForm, DateForm, RestaurantsEnableForm, RestaurantInfoForm
from settings import BOT, BASE_URL, SET_WEBHOOK, YKT, ADMINS
from static.contract import contract_text

import re
import requests

from flask import request
from flask_login import login_required, login_user, current_user, logout_user

from app import app, db, login_manager, send_email

from models import Restaurant, Category, Dish, Cart, User, Order, History, OrderDetail, Admin, \
    RestaurantDeliveryTerms, Subcategory, SpecialDish, PromoDish, Favorites, SearchWords, SearchDishes, RestaurantInfo, \
    TextMenuMessage

from werkzeug.utils import secure_filename

from transliterate import translit

requests.get(SET_WEBHOOK)


def rest_menu_send_msg(chat_id):
    if type(chat_id) is Message:
        chat_id = chat_id.chat.id
    markup = rest_menu_keyboard(chat_id)
    if not markup.keyboard:
        text = 'В данное время нет работающих ресторанов'
        BOT.send_message(chat_id=chat_id, text=text)
    else:
        text = 'Пожалуйста, выберите ресторан:'
        BOT.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        telebot.TeleBot.edit_message_text()


def stat_menu_keyboard(message):
    if message.chat.id not in ADMINS:
        return 'Ok'
    keyboard = InlineKeyboardMarkup()
    for i in range(1, 8):
        keyboard.add(InlineKeyboardButton(f'{i}', callback_data=f'stat_{i}'))
    BOT.send_message(chat_id=message.chat.id, text='СТАТИСТИКА', reply_markup=keyboard)


def default_message(message):
    text = 'Не могу найти то, что Вы ищете🧐 Попробуйте изменить запрос😊'
    result, query = [], None
    for word in message.text.split(' '):
        query = db.session.query(SearchWords.id).filter(SearchWords.words.ilike("%" + word.lower() + "%"))
        temp = query.first() if len(word) > 1 else None
        if temp: result.append(*temp)
    if result:
        query = db.session.query(Category.id, Restaurant.name, Dish.img_link, SearchDishes.dish_name, Dish.composition,
                                 Dish.cost, Dish.id, Restaurant.id, Restaurant.address).filter(
            SearchDishes.search_words_id.in_(result)).filter(
            Restaurant.id == SearchDishes.rest_id, Dish.id == SearchDishes.dish_id).filter(
            Category.name == SearchDishes.dish_category, Category.restaurant_id == SearchDishes.rest_id).all()
        if TextMenuMessage.query.filter_by(user_id=message.chat.id).all():
            TextMenuMessage.query.filter_by(user_id=message.chat.id).delete()
        for item in query:
            text = f'<b>{item[1]}</b>\nДоставка - ЗНАЧ!\nСамовывоз - {item[8]}\n\n'
            text += f'{item[3]}\n{item[4]}\n{item[5]} р.\n<a href="{item[2]}">.</a>'
            cart = Cart.query.filter_by(user_uid=message.chat.id, dish_id=item[6]).first()
            quantity = cart.quantity if cart else 0
            cb_data = f'rest_{item[7]}_cat_{item[0]}_dish_{item[6]}'
            cb_fav = f'fav_{message.chat.id}_{item[7]}_{item[6]}'
            kbd = InlineKeyboardMarkup()
            kbd.row(
                InlineKeyboardButton(text='⭐️', callback_data=cb_fav),
                InlineKeyboardButton(text='-', callback_data=f'{cb_data}_rem_{message.chat.id}'),
                InlineKeyboardButton(text=f'{quantity} шт', callback_data='None'),
                InlineKeyboardButton(text='+', callback_data=f'{cb_data}_add_{message.chat.id}')
            )
            total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=message.chat.id).all()
            total = total[0][0] if total[0][0] else 0
            # kbd.add(InlineKeyboardButton('Меню ресторана', callback_data=f'rest_{item[7]}_menu'))
            # kbd.add(InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart'))
            msg = BOT.send_message(chat_id=message.chat.id, text=text, parse_mode='HTML', reply_markup=kbd)
            txt_menu = TextMenuMessage(
                user_id=message.chat.id, message_id=msg.id, rest_id=item[7], text=text, img=item[2],
                category_id=item[0], dish_id=item[6], quantity=quantity
            )
            db.session.add(txt_menu)
            db.session.commit()
        return 'Ok', 200
    result = Restaurant.query.filter_by(passwd=message.text).first()
    if result:
        text = f'Вы назначены администратором ресторана {result.name}'
        result.service_uid = message.chat.id
        db.session.commit()
    BOT.send_message(chat_id=message.chat.id, text=text)


@app.route('/', methods=['POST'])
def webhook():
    update = Update.de_json(request.stream.read().decode('utf-8'))
    BOT.process_new_updates([update])
    try:
        check_user(update.message.json)
        write_history(
            msg_id=update.message.json["message_id"],
            chat_id=update.message.json["chat"]["id"],
            text=update.message.json["text"],
            is_bot=False
        )
    except AttributeError:
        pass
    return 'Ok', 200


@BOT.message_handler(commands=['start'])
def start(message):
    """Обработка команды /start"""
    text = "*Добро пожаловать в Robofood*😊\n" \
           "Здесь `Вы` можете заказать еду из ресторанов на доставку и самовывоз. " \
           "Начните с кнопки “Меню” или наберите в сообщении интересующую еду 🍱🥤🍕 "
    BOT.send_message(message.chat.id, text, parse_mode="MARKDOWN")


@BOT.message_handler(commands=['my_orders'])
def user_orders(message):
    order = Order.query.filter_by(uid=message.chat.id, order_state='Подтверждена')
    order = order.order_by(Order.id.desc()).first()
    if not order:
        text = 'У Вас пока нет оформленных заказов'
        BOT.send_message(message.chat.id, text, parse_mode="MARKDOWN")
        return 'Ok', 200
    date = order.order_datetime
    date = YKT.localize(datetime.fromtimestamp(date)).strftime('%d.%m.%Y %H:%M:%S')
    text = f'Ваш заказ № {order.id} от {date}\n- '
    details = OrderDetail.query.filter_by(order_id=order.id).all()
    text += '- '.join("%s\n" % item.order_dish_name for item in details)
    text += f'Общая стоимость заказа - {order.order_total}\n'
    try:
        restaurant = Restaurant.query.filter_by(id=order.order_rest_id).first()
        text += f'Ресторан - {restaurant.name}, {restaurant.address}, {restaurant.contact}'
    except Exception as e:
        print("/My_orders parse error:", e)
        text = 'Возникла ошибка при обработке команды. Пожалуйста, свяжитесь с администратором.'
    BOT.send_message(message.chat.id, text, parse_mode="MARKDOWN")


@BOT.message_handler(commands=['restaurants'])
def restaurants(message):
    rest_menu_send_msg(message.chat.id)


@BOT.message_handler(commands=['combo_set'])
def combo(message):
    text = 'Здесь представлены лучшие Комбо Наборы разных ресторанов:'
    chat_id = message.chat.id
    BOT.send_message(chat_id, text)
    write_history(message.id, chat_id, text, is_bot=True)
    kb = rest_menu_keyboard(chat_id)
    rests = []
    kb_parsed = list(chain.from_iterable(kb.keyboard))
    for item in kb_parsed:
        rests.append(item.text)
    combo_dishes = db.session.query(
        Dish, Restaurant, SpecialDish
    ).filter(SpecialDish.subcat_id == -1).filter(
        SpecialDish.dish_id == Dish.id, SpecialDish.rest_id == Restaurant.id, Restaurant.name.in_(rests)
    ).all()
    if TextMenuMessage.query.filter_by(user_id=chat_id).all():
        TextMenuMessage.query.filter_by(user_id=chat_id).delete()
    for item in combo_dishes:
        rest = Restaurant.query.filter_by(id=item[0].id_rest).first()
        keyboard = InlineKeyboardMarkup(row_width=4)
        text = ''
        text += f'<b>Ресторан {item[1].name}</b>\nДоставка - ЗНАЧ!\nСамовывоз - {rest.address}\n'
        text += f'\n{item[0].name}\n{item[0].composition}\n{item[0].cost} р.\n<a href="{item[0].img_link}">.</a>'
        cart_item = Cart.query.filter_by(user_uid=chat_id, dish_id=item[0].id).first()
        quantity = cart_item.quantity if cart_item else 0
        cb_data = f'fav_{chat_id}_{item[1].id}_{item[0].id}'
        change_callback = f'rest_{item[1].id}_cat_{item[2].category_id}_dish_{item[0].id}'
        button1 = InlineKeyboardButton(text='⭐', callback_data=cb_data)
        button2 = InlineKeyboardButton(text='-', callback_data=f'{change_callback}_rem_{chat_id}')
        button3 = InlineKeyboardButton(text=f'{quantity} шт.', callback_data='None')
        button4 = InlineKeyboardButton(text='+', callback_data=f'{change_callback}_add_{chat_id}')
        keyboard.add(button1, button2, button3, button4)
        msg = BOT.send_message(chat_id=chat_id, text=text, parse_mode='HTML', reply_markup=keyboard)
        txt_menu = TextMenuMessage(
            user_id=chat_id, message_id=msg.id, rest_id=rest.id, text=text, img=item[0].img_link,
            category_id=item[2].category_id, dish_id=item[0].id, quantity=quantity
        )
        db.session.add(txt_menu)
        db.session.commit()
        write_history(message.id, chat_id, text, is_bot=True)


@BOT.message_handler(commands=['recommend'])
def recommend(message):
    text = 'Здесь представлены блюда разных Ресторанов. Обращайте внимание на название Ресторана ' \
           'в описании блюда. В корзину можно добавить блюда только одного Ресторана. '
    keyboard = InlineKeyboardMarkup()
    cb_data = f'subcat_recommend_'
    for subcat in Subcategory.query.all():
        keyboard.add(InlineKeyboardButton(text=subcat.name, callback_data=f'{cb_data}{subcat.id}'))
    BOT.send_message(chat_id=message.chat.id, text=text, reply_markup=keyboard)
    write_history(message.id, message.chat.id, text, is_bot=True)


@BOT.message_handler(commands=['promotions'])
def promotions(message):
    promo_dishes = PromoDish.query.all()
    keyboard = InlineKeyboardMarkup()
    for dish in promo_dishes:
        text = f'<a href="{dish.img_link}">.</a>'
        cb_data = f'restaurant_{dish.rest_id}'
        keyboard.add(InlineKeyboardButton(text="Меню ресторана", callback_data=cb_data))
        BOT.send_message(chat_id=message.chat.id, text=text, parse_mode="HTML", reply_markup=keyboard)


@BOT.message_handler(commands=['show_cart'])
def show_cart(message):
    chat_id = message.from_user.id if type(message) is CallbackQuery else message.chat.id
    cart = Cart.query.filter_by(user_uid=chat_id).all()
    if not cart:
        text = 'Ваша корзина пуста'
        BOT.send_message(chat_id=chat_id, text=text)
        return 'Ok', 200
    keyboard = InlineKeyboardMarkup()
    rest = db.session.query(Restaurant.name).filter_by(id=cart[0].restaurant_id).first()[0]
    total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=chat_id).all()
    total = total[0][0] if total[0][0] else 0
    cart_count = db.session.query(Cart.quantity).filter(Cart.id == cart[0].id).first()[0]
    text = '<b>Корзина</b>\n'
    row = [InlineKeyboardButton(text='❌', callback_data=f'cart_item_id_{cart[0].id}_clear')]
    for i, item in enumerate(cart, start=1):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f'cart_item_id_{item.id}'))
    keyboard.row(*row)
    cart_dish_id = None if not cart else db.session.query(Cart.dish_id).filter(Cart.id == cart[0].id).first()[0]
    current_dish = Dish.query.filter_by(id=cart_dish_id).first()
    text += f'<a href="{current_dish.img_link}">{rest}</a>\n{current_dish.name}\n{current_dish.composition}\n{cart[0].price}'
    keyboard.row(
        InlineKeyboardButton('-️', callback_data=f'cart_item_id_{cart[0].id}_remove'),
        InlineKeyboardButton(f'{cart_count} шт.', callback_data='None'),
        InlineKeyboardButton('+️', callback_data=f'cart_item_id_{cart[0].id}_add')
    )
    keyboard.row(
        InlineKeyboardButton('Очистить️', callback_data=f'purge'),
        InlineKeyboardButton(text='Меню️️', web_app=WebAppInfo(BASE_URL + f"webapp/{cart[0].restaurant_id}"))
    )
    keyboard.add(InlineKeyboardButton(f'Оформить заказ на сумму {total}', callback_data='cart_confirm'))
    BOT.send_message(text=text, chat_id=chat_id, parse_mode="HTML", reply_markup=keyboard)


@BOT.message_handler(commands=["favorites"])
def favorites(message):
    favs = db.session.query(Favorites.rest_id, Restaurant.name).filter_by(
        uid=message.chat.id).filter(Favorites.rest_id == Restaurant.id, Restaurant.enabled).distinct().all()
    if not favs:
        BOT.send_message(chat_id=message.chat.id, text='У Вас пусто в Избранном')
        return 'Ok', 200
    text = 'Выберите ресторан'
    keyboard = InlineKeyboardMarkup()
    for fav in favs:
        cb_data = f'fav_{message.chat.id}_rest_{fav[0]}'
        keyboard.add(InlineKeyboardButton(text=fav[1], callback_data=cb_data))
    BOT.send_message(chat_id=message.chat.id, text=text, reply_markup=keyboard)
    write_history(message.id, message.chat.id, text, True)


@BOT.message_handler(commands=["help"])
def send_help(message):
    keyboard = InlineKeyboardMarkup()
    agreement = 'Пользовательское соглашение (Договор для пользователей)'
    buttons = [
        InlineKeyboardButton('Мои заказы', callback_data=f'user_orders_{message.chat.id}'),
        InlineKeyboardButton('Правила и помощь', callback_data='show_rules'),
        InlineKeyboardButton(agreement, callback_data='show_contract')
    ]
    keyboard.add(*buttons, row_width=1)
    BOT.send_message(chat_id=message.chat.id, text='Справка', reply_markup=keyboard)


@BOT.message_handler(content_types=["text"])
def new_msg(message):
    """Обработка текстовых сообщений"""
    options = {
        "рестораны": rest_menu_send_msg,
        "комбо наборы (кб)": combo,
        "рекомендуем": recommend,
        "акции": promotions,
        "корзина": show_cart,
        "статистика": stat_menu_keyboard,
    }
    options.get(message.text.lower(), default_message)(message)


@BOT.callback_query_handler(func=lambda call: True)
def callback_query(call):
    """Обработка колбэков"""
    req = call.data.split('_')
    options = {
        'rest': restaurant_callback,
        'cart': cart_callback,
        'order': order_callback,
        'fav': favorites_callback
    }
    if call.data == 'cart':
        show_cart(call)
        return 'Ok', 200
    options.get(req[0], other_callback)(call)


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/webapp/', methods=['POST'])
def webapp():
    uid = int(request.form['uid'])
    dish_id = int(request.form['dish_id'])
    quantity = int(request.form['quantity'])
    dish = Dish.query.filter_by(id=dish_id).first()
    rest = Restaurant.query.filter_by(id=dish.id_rest).first()
    if Cart.query.filter(Cart.user_uid == uid, Cart.restaurant_id.notlike(rest.id)).all():
        Cart.query.filter(
            Cart.user_uid == uid, Cart.restaurant_id.notlike(rest.id)
        ).delete(synchronize_session=False)
        db.session.commit()
    cart_item = Cart.query.filter_by(user_uid=uid, dish_id=dish_id).first()
    if cart_item:
        cart_item.quantity = quantity
    else:
        db.session.add(Cart(
            name=dish.name, price=dish.cost, quantity=quantity, user_uid=uid,
            is_dish=1, is_water=0, dish_id=dish_id, restaurant_id=dish.id_rest, service_uid=rest.service_uid))
    db.session.commit()
    return redirect(f'/webapp/{rest.id}')


@app.route('/webapp/<int:Number>', methods=['GET'])
def webapp_main(Number):
    try:
        uid = int(request.args.get('uid'))
    except Exception as e:
        print("Exception of int(request.args.get('uid')) is:", e)
        uid = None
    rest = Restaurant.query.filter_by(id=Number).first()
    if Cart.query.filter(Cart.user_uid == uid, Cart.restaurant_id.notlike(rest.id)).all():
        Cart.query.filter(
            Cart.user_uid == uid, Cart.restaurant_id.notlike(rest.id)
        ).delete(synchronize_session=False)
        db.session.commit()
    info = RestaurantInfo.query.filter_by(rest_id=Number).first()
    categories = Category.query.filter_by(restaurant_id=Number).all()
    dishes = Dish.query.filter_by(id_rest=Number).all()
    dish_id = None
    try:
        dish_id = request.args.get('dishId', type=str)
    except Exception as e:
        print(e)
    return render_template('webapp.html', dishes=dishes, categories=categories, rest=rest, info=info, dish_id=dish_id)


@app.route('/webapp_rest/<int:Number>', methods=['GET'])
def webapp_rest_info(Number):
    rest = Restaurant.query.filter_by(id=Number).first()
    terms = RestaurantDeliveryTerms.query.filter_by(rest_id=Number).first()
    return render_template('webapp_terms.html', rest=rest, terms=terms)


@app.route('/webapp_cart', methods=['GET'])
def webapp_cart():
    uid = request.args.get('uid', default=0, type=int)
    # uid = 113737020
    rest_id = request.args.get('restId', default=0, type=int)
    cart = Cart.query.filter_by(user_uid=uid).all()
    items = {}
    dish_id = None
    for item in cart:
        items[item.dish_id] = {'img_link': Dish.query.filter_by(id=item.dish_id).first().img_link, 'name': item.name,
                               'quantity': item.quantity, 'cost': item.price}
    if items:
        dish_id = list(items.keys())[-1]
    return render_template('webapp_cart.html', uid=uid, items=items, rest_id=rest_id, dish_id=dish_id)


@app.route('/webapp_confirm', methods=['GET'])
def webapp_confirm():
    uid = request.args.get('uid', default=0, type=int)
    user = User.query.filter_by(uid=uid).first()
    total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=uid).all()[0][0]
    total = total if total else 0
    try:
        return render_template('webapp_confirm.html', phone=user.phone, address=user.address, total=total)
    except AttributeError:
        return abort(404)


@app.route('/webapp_item', methods=['GET'])
def webapp_item():
    uid = request.args.get('uid', default=0, type=int)
    dish_id = request.args.get('item', type=int)
    category = request.args.get('category', type=str)
    dish = Dish.query.filter_by(id=dish_id).first()
    return render_template('webapp_item.html', uid=uid, dish=dish, category=category)


@app.route('/webapp/data', methods=['POST', 'GET'])
def webapp_data():
    if request.method == 'POST':
        uid = int(request.form['uid']) if request.form['uid'] else None
        method = request.form['method']
        dish_id = quantity = cart = None
        jCart = {}

        def create():
            nonlocal dish_id, quantity
            dish_id = int(request.form['dish_id'])
            quantity = int(request.form['quantity'])
            dish = Dish.query.filter_by(id=dish_id).first()
            rest_id = dish.id_rest
            service_uid = Restaurant.query.filter_by(id=rest_id).first()
            service_uid = service_uid.service_uid if service_uid else None
            if not Cart.query.filter_by(user_uid=uid, dish_id=dish_id).first():
                cart = Cart(name=dish.name, price=dish.cost, quantity=quantity, user_uid=uid,
                            is_dish=1, is_water=0, dish_id=dish_id, restaurant_id=dish.id_rest, service_uid=service_uid)
                db.session.add(cart)

        def update():
            nonlocal dish_id, quantity
            dish_id = int(request.form['dish_id'])
            cart = Cart.query.filter_by(user_uid=uid, dish_id=dish_id).first()
            operation = request.form['operation']
            operations = {'add': 1, 'rem': -1}
            cart.quantity += operations[operation]
            quantity = cart.quantity
            if quantity == 0:
                Cart.query.filter_by(user_uid=uid, dish_id=dish_id).delete()
            db.session.commit()

        def add():
            nonlocal dish_id, quantity
            dish_id = int(request.form['dish_id'])
            quantity = int(request.form['quantity'])
            cart_item = Cart.query.filter_by(user_uid=uid, dish_id=dish_id).first()
            if cart_item:
                cart_item.quantity += quantity
            else:
                dish = Dish.query.filter_by(id=dish_id).first()
                service_uid = Restaurant.query.filter_by(id=dish.id_rest).first()
                service_uid = service_uid.service_uid if service_uid else None
                db.session.add(Cart(name=dish.name, price=dish.cost, quantity=quantity, user_uid=uid, is_dish=1,
                            is_water=0, dish_id=dish_id, restaurant_id=dish.id_rest, service_uid=service_uid))

        def onload():
            rest_id = request.form['rest_id']
            rest_id = int(rest_id.split('_')[1])
            if Cart.query.filter(Cart.user_uid == uid, Cart.restaurant_id.notlike(rest_id)).all():
                Cart.query.filter(
                    Cart.user_uid == uid, Cart.restaurant_id.notlike(rest_id)
                ).delete(synchronize_session=False)
                db.session.commit()
            nonlocal cart, jCart
            cart = Cart.query.filter_by(user_uid=uid).all()
            jCart = {}
            for item in cart:
                jCart[item.dish_id] = {'price': item.price, 'quantity': item.quantity}

        post_methods = {'create': create, 'update': update, 'onload': onload, 'add': add}
        post_methods.get(method)()
        db.session.commit()
        return {"uid": uid, "dish_id": dish_id, "quantity": quantity, "cart": jCart}
    else:
        uid = request.args.get('uid')
        method = request.args.get('method')
        payment = request.args.get('payment')
        phone = request.args.get('phone')
        address = request.args.get('address')
        total = request.args.get('total')
        cart = Cart.query.filter_by(user_uid=uid).all()
        rest_id = Cart.query.filter_by(user_uid=uid).first().restaurant_id
        rest = Restaurant.query.filter_by(id=rest_id).first()
        text = 'Вы указали:\n'
        text += f'Адрес доставки: {address}\n' if method == 'delivery' else 'Самовывоз\n'
        text += f'Контактный номер: {phone}\nСумма заказа: {total}\n'
        text += f'Заказ отправлен, ждите ответа ресторана {rest.name}. ' \
                'За статусом заказа смотрите в "Мои заказы" в разделе Справка.'
        BOT.send_message(chat_id=uid, text=text)
        last_order = db.engine.execute("SELECT MAX(id) FROM Orders;").first()[0]
        user = User.query.filter_by(uid=uid).first()
        user.address = address
        user.phone = phone
        new_order = Order(
            id=last_order + 1,
            uid=uid,
            first_name=user.first_name,
            last_name=user.last_name,
            order_total=int(total),
            order_rest_id=rest_id,
            order_datetime=datetime.now(YKT).strftime('%s'),
            order_confirm=False,
            order_state="Заказ отправлен, ожидание ответа ресторана."
        )
        db.session.add(new_order)
        text = f'Поступил заказ № {new_order.id}\nСостав заказа:\n'
        for item in cart:
            db.session.add(OrderDetail(
                order_id=new_order.id,
                order_dish_name=item.name,
                order_dish_cost=item.price,
                order_dish_id=item.dish_id,
                order_dish_quantity=item.quantity,
                order_rest_id=new_order.order_rest_id
            ))
            text += f'{item.name} - {item.quantity} шт.\n'
        text += f'Общая сумма заказа: {total} р.\n'
        bt_label = "Принять и доставить "
        cb_data = f'order_{new_order.id}_change'
        text += f'Адрес доставки {user.address}\n'
        kbd = InlineKeyboardMarkup()
        d = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
        for item in d:
            kbd.add(InlineKeyboardButton(bt_label + d[item], callback_data=f'order_{new_order.id}_accept_{30 * item}_send'))
        kbd.add(InlineKeyboardButton(text='Не принят', callback_data='None')),
        kbd.add(InlineKeyboardButton(f'Изменить заказ № {new_order.id}', callback_data=cb_data))
        Cart.query.filter_by(user_uid=uid).delete()
        db.session.commit()
        del cart
        BOT.send_message(chat_id=uid, text=text, reply_markup=kbd, parse_mode='HTML')
        send_email(rest.email, f'Поступил заказ из Robofood № {new_order.id}', text)
        return 'Ok', 200


@login_manager.user_loader
def load_user(user_id):
    return db.session.query(Admin).get(user_id)


@app.route('/login/', methods=['POST', 'GET'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin'))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.query(Admin).filter(Admin.username == form.username.data).first()
        if user and user.verify_password(form.password.data):
            login_user(user, remember=form.remember.data)
            return redirect(url_for('admin'))

        flash("Invalid username/password", 'error')
        return redirect(url_for('login'))
    return render_template('login.html', form=form)


@app.route('/logout/')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.")
    return redirect(url_for('login'))


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')


@app.route('/statistics', methods=['GET'])
@login_required
def statistics():
    return render_template(
        'statistics.html'
    )


@app.route('/statistics/1', methods=['GET'])
@login_required
def statistics1():
    return render_template('stat1.html', stat1=stat1())


@app.route('/statistics/2', methods=['GET'])
@login_required
def statistics2():
    return render_template('stat2.html', stat2=stat2())


@app.route('/statistics/3', methods=['GET'])
@login_required
def statistics3():
    return render_template('stat3.html', stat3=stat3())


@app.route('/statistics/4', methods=['GET'])
@login_required
def statistics4():
    return render_template('stat4.html', stat4=stat4())


@app.route('/statistics/5', methods=['GET'])
@login_required
def statistics5():
    return render_template('stat5.html', stat5=stat5()[0])


@app.route('/statistics/6', methods=['GET'])
@login_required
def statistics6():
    return render_template('stat6.html', stat6=stat6())


@app.route('/statistics/7', methods=['GET'])
@login_required
def statistics7():
    return render_template('stat7.html', stat7=stat7())


@app.route('/statistics/8', methods=['GET'])
@login_required
def statistics8():
    return render_template('stat8.html', stat8=stat8())


@app.route('/database', methods=['GET', 'POST'])
@login_required
def get_database():
    date_form = DateForm()
    date = datetime.now().strftime('%Y-%m-%d')
    if date_form.is_submitted():
        date = request.form['input_date']
        date_start = date + '-0-0'
        date_end = date + '-23-59'
        date_start_format = datetime.strptime(date_start, "%Y-%m-%d-%H-%M")
        date_end_format = datetime.strptime(date_end, "%Y-%m-%d-%H-%M")

        unix_time_start = datetime.timestamp(date_start_format)
        unix_time_end = datetime.timestamp(date_end_format)

        history_data = db.session.query(History.chat_id).filter(
            History.date.between(unix_time_start, unix_time_end)).distinct().all()
        data = [i for sub in history_data for i in sub]
        users = User.query.filter(User.uid.in_(data)).all()
        return render_template('database.html', date_form=date_form, users=users, orders=Order.query.all(),
                               details=OrderDetail.query.all(), unique=stat5()[1], date=date)
    else:
        return render_template('database.html', date_form=date_form, date=date)


@app.route('/send_message', methods=['GET', 'POST'])
@login_required
def send_message():
    if request.method == 'POST':
        users = User.query.all()
        img_file = request.files['msg_img']
        temp_path = 'tmp/'
        if not isdir(temp_path):
            mkdir(temp_path)
        path = temp_path + secure_filename(img_file.filename)
        with Image.open(img_file) as img:
            width, height = img.size
            resized_dimensions = (int(width * 0.5), int(height * 0.5))
            resized = img.resize(resized_dimensions)
            resized.save(path, format='png')
            for user in users:
                msg = antiflood(BOT.send_photo, chat_id=user.uid, photo=open(path, 'rb'),
                                caption=request.form.get('msg_txt'))
        return redirect(url_for('send_message'))
        # TODO remove files in tmp after sending
    return render_template('send_message.html')


@app.route('/contract/', methods=['GET'])
def contract():
    return render_template('contract.html', contract_text=contract_text)


@app.route('/admin/data', methods=['POST'])
def admin_data():
    dish_id = request.form['dish_id']
    method = request.form['method']
    dish = Dish.query.filter_by(id=int(dish_id)).first()
    dish.status = True if method == 'Включить' else False
    db.session.commit()
    return 'Ok', 200


@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    dishes = db.session.query(Dish).all()
    s_dishes = SpecialDish.query.all()
    search_dishes = SearchDishes.query.all()
    search_words = SearchWords.query.all()
    promo_dishes = PromoDish.query.all()
    restaurants = db.session.query(Restaurant).all()
    categories = db.session.query(Category).all()
    subcategories = Subcategory.query.all()
    promo_dishes_form = PromoDishForm()
    promo_dishes_delete_form = PromoDishDeleteForm()
    dish_delete_form = DishDeleteForm()
    restaurant_form = RestaurantForm()
    restaurant_delete_form = RestaurantDeleteForm()
    restaurant_edit_form = RestaurantEditForm()
    restaurant_enable_form = RestaurantsEnableForm()
    admin_add_form = AdminAddForm()
    delivery_terms = RestaurantDeliveryTerms.query.all()
    rest_delivery_terms_form = RestaurantDeliveryTermsForm()
    rest_delivery_terms_edit_form = RestaurantDeliveryTermsEditForm()
    restaurant_info_form = RestaurantInfoForm()
    subcategory_add_form = SubcategoryForm()
    subcategory_del_form = SubcategoryDeleteForm()
    special_dish_form = SpecialDishForm()
    special_dish_delete_form = SpecialDishDeleteForm()
    dish_edit_form = DishEditForm()
    search_word_form = SearchWordForm()
    search_word_del_form = SearchWordDelForm()
    search_dish_form = SearchDishForm()
    search_dish_del_form = SearchDishDelForm()
    if current_user.username != 'admin':
        dish_form = DishForm(hide_rest=True)
        category_form = CategoryForm(hide_rest_id=True)
        category_delete_form = CategoryDeleteForm(hide_rest_id=True)
    else:
        dish_form = DishForm(hide_rest=False)
        category_form = CategoryForm(hide_rest_id=False)
        category_delete_form = CategoryDeleteForm(hide_rest_id=False)
    if dish_form.dish_add_submit.data:
        if dish_form.validate_on_submit() or dish_form.is_submitted():
            name = dish_form.name.data
            cost = dish_form.cost.data
            composition = dish_form.composition.data
            if current_user.ownership == 'all':
                id_rest = request.form['dish_add_rest_selector']
                category = request.form['dish_add_admin_category_selector']
            else:
                id_rest = dish_form.id_rest.data
                category = request.form['dish_add_category_selector']
            if re.search(r'[а-яА-Я]', dish_form.img_file.data.filename):
                img_file = secure_filename(translit(dish_form.img_file.data.filename, reversed=True))
            else:
                img_file = secure_filename(dish_form.img_file.data.filename)
            static_path = 'static/' + str(id_rest) + '/'
            if not isdir(static_path):
                mkdir(static_path)
            dish_form.img_file.data.save(static_path + img_file)
            img_link = BASE_URL + static_path + img_file
            dish = Dish(
                name=name,
                cost=cost,
                composition=composition,
                img_link=img_link,
                category=category,
                id_rest=id_rest
            )
            db.session.add(dish)
            db.session.commit()
            flash("Блюдо добавлено", "success")
            return redirect(url_for('admin'))

    if dish_edit_form.dish_edit_submit.data:
        if dish_edit_form.validate_on_submit() or dish_edit_form.is_submitted():
            id_dish = dish_edit_form.id_dish.data
            name = dish_edit_form.name.data
            cost = dish_edit_form.cost.data
            composition = dish_edit_form.composition.data
            id_rest = dish_edit_form.id_rest.data
            category = dish_edit_form.category.data
            file_flag = False
            try:
                if re.search(r'[а-яА-Я]', dish_edit_form.img_file.data.filename):
                    img_file = secure_filename(translit(dish_edit_form.img_file.data.filename, reversed=True))
                else:
                    img_file = secure_filename(dish_edit_form.img_file.data.filename)
                static_path = 'static/' + str(id_rest) + '/'
                if not isdir(static_path):
                    mkdir(static_path)
                dish_form.img_file.data.save(static_path + img_file)
                img_link = BASE_URL + static_path + img_file
                file_flag = True
            except Exception as e:
                print(e)
            try:
                dish = Dish.query.filter_by(id=id_dish).first()
                search_dish = SearchDishes.query.filter_by(dish_id=id_dish).first()
                dish.name = name
                search_dish.dish_name = name
                dish.id_rest = id_rest
                search_dish.rest_id = id_rest
                dish.cost = cost
                dish.composition = composition
                dish.category = category
                search_dish.dish_category = category
                img_link = None
                if file_flag:
                    dish.img_link = img_link
                db.session.commit()
                flash("Блюдо изменено", "success")
                return redirect(url_for('admin'))
            except Exception as e:
                flash(f"Попытка изменить блюдо неудачна\n{e}", "error")
                return redirect(url_for('admin'))

    if promo_dishes_form.promo_dish_submit.data:
        if promo_dishes_form.validate_on_submit() or promo_dishes_form.is_submitted():
            rest_id = promo_dishes_form.rest_id.data if promo_dishes_form.rest_id.data else request.form[
                'promo_rest_selector']
            if re.search(r'[а-яА-Я]', promo_dishes_form.img_file.data.filename):
                img_file = secure_filename(translit(promo_dishes_form.img_file.data.filename, reversed=True))
            else:
                img_file = secure_filename(promo_dishes_form.img_file.data.filename)
            static_path = 'static/' + str(rest_id) + '/'
            if not isdir(static_path):
                mkdir(static_path)
            dish_form.img_file.data.save(static_path + img_file)
            img_link = BASE_URL + static_path + img_file
            promo_dish = PromoDish(img_link=img_link, rest_id=rest_id)
            if PromoDish.query.filter_by(rest_id=rest_id).count() > 0:
                PromoDish.query.filter_by(rest_id=rest_id).delete()
            db.session.add(promo_dish)
            db.session.commit()
            flash("Акция добавлена", "success")
            return redirect(url_for('admin'))
    if promo_dishes_delete_form.promo_dish_delete_submit.data:
        if promo_dishes_delete_form.validate_on_submit() or promo_dishes_delete_form.is_submitted():
            if promo_dishes_delete_form.promo_dish_id.data:
                promo_dish_id = promo_dishes_delete_form.promo_dish_id.data
                PromoDish.query.filter_by(id=promo_dish_id).delete()
            if promo_dishes_delete_form.promo_rest_id.data:
                promo_rest_id = promo_dishes_delete_form.promo_rest_id.data
                PromoDish.query.filter_by(rest_id=promo_rest_id).delete()
            db.session.commit()
            flash("Акция успешно удалена", "success")
            return redirect(url_for('admin'))
    if special_dish_form.s_dish_add_submit.data:
        if special_dish_form.validate_on_submit() or special_dish_form.is_submitted():
            try:
                rest_id = request.form['s_dish_rest_selector']
                cat_id = request.form['s_dish_cat_selector']
                dish_id = request.form['s_dish_selector']
                subcat_id = request.form['s_dish_subcat_selector']
            except KeyError:
                rest_id = request.form['combo_rest_selector']
                cat_id = request.form['combo_cat_selector']
                dish_id = request.form['combo_selector']
                subcat_id = special_dish_form.subcat_id.data
            s_dish = SpecialDish(subcat_id=subcat_id, dish_id=dish_id, category_id=cat_id, rest_id=rest_id)
            db.session.add(s_dish)
            db.session.commit()
            flash("Блюдо добавлено", "success")
            return redirect(url_for("admin"))
    if search_word_form.search_word_submit.data:
        if search_word_form.validate_on_submit() or search_word_form.is_submitted():
            search_word = search_word_form.search_word.data
            search_name = search_word_form.search_name.data
            try:
                db.session.add(SearchWords(name=search_name, words=search_word.lower()))
                db.session.commit()
                flash("Команда успешно добавлена", "success")
            except Exception as inst:
                flash(inst, "error")
            return redirect(url_for("admin"))
    if search_dish_form.search_dish_submit.data:
        if search_dish_form.validate_on_submit() or search_dish_form.is_submitted():
            search_word_id = search_dish_form.search_word_id.data
            dish_id = search_dish_form.dish_id.data if search_dish_form.dish_id.data else request.form[
                f'search_dish_selector_{search_word_id}']
            dish_name = Dish.query.filter_by(id=dish_id).first().name
            category = Dish.query.filter_by(id=dish_id).first().category
            rest_id = search_dish_form.rest_id.data if search_dish_form.rest_id.data else request.form[
                f'search_dish_rest_selector_{search_word_id}']
            try:
                db.session.add(
                    SearchDishes(
                        dish_id=dish_id,
                        dish_name=dish_name,
                        dish_category=category,
                        rest_id=rest_id,
                        search_words_id=search_word_id
                    )
                )
                db.session.commit()
                flash("Блюдо успешно добавлено", "success")
            except Exception as inst:
                flash(inst, "error")
            return redirect(url_for("admin"))
    if search_dish_del_form.search_dish_del_submit.data:
        if search_dish_del_form.validate_on_submit() or search_dish_del_form.is_submitted():
            search_dish_id = search_dish_del_form.search_dish_id.data
            try:
                SearchDishes.query.filter_by(id=search_dish_id).delete()
                db.session.commit()
                flash("Успешно удалено", "success")
            except Exception as inst:
                flash(inst, "error")
            return redirect(url_for("admin"))
    if search_word_del_form.search_word_del_submit.data:
        if search_word_del_form.validate_on_submit() or search_word_del_form.is_submitted():
            search_word_id = request.form['search_word_selector']
            try:
                SearchWords.query.filter_by(id=search_word_id).delete()
                db.session.commit()
                flash("Успешно удалено", "success")
            except Exception as inst:
                flash(inst, "error")
            return redirect(url_for("admin"))
    if special_dish_delete_form.special_dish_delete_submit.data:
        if special_dish_delete_form.validate_on_submit() or special_dish_delete_form.is_submitted():
            special_dish_id = special_dish_delete_form.special_dish_id.data
            SpecialDish.query.filter_by(id=special_dish_id).delete()
            db.session.commit()
            flash("Успешно удалено", "success")
            return redirect(url_for("admin"))

    if category_form.category_add_submit.data:
        if category_form.validate_on_submit() or category_form.is_submitted():
            name = category_form.name.data
            if current_user.ownership == 'all':
                restaurant_id = request.form['category_add_rest_selector']
            else:
                restaurant_id = category_form.restaurant_id.data
            category = Category(name=name, restaurant_id=restaurant_id)
            db.session.add(category)
            db.session.commit()
            flash("Категория добавлена", "success")
            return redirect(url_for('admin'))

    if subcategory_add_form.subcategory_add_submit.data:
        if subcategory_add_form.validate_on_submit() or subcategory_add_form.is_submitted():
            name = subcategory_add_form.name.data
            category_id = subcategory_add_form.category_id.data
            subcategory = Subcategory(name=name, category_id=category_id)
            db.session.add(subcategory)
            db.session.commit()
            flash("Подкатегория добавлена", "success")
            return redirect(url_for('admin'))

    if subcategory_del_form.subcategory_del_submit.data:
        if subcategory_del_form.validate_on_submit() or subcategory_del_form.is_submitted():
            subcat_id = request.form['subcat_del_selector']
            SpecialDish.query.filter_by(subcat_id=subcat_id).delete()
            Subcategory.query.filter_by(id=subcat_id).delete()
            db.session.commit()
            flash("Подкатегория удалена", "success")
            return redirect(url_for('admin'))

    if dish_delete_form.validate_on_submit() and dish_delete_form.dish_delete_submit.data:
        dish_id = dish_delete_form.delete_id.data
        SearchDishes.query.filter_by(dish_id=dish_id).delete()
        Favorites.query.filter_by(dish_id=dish_id).delete()
        OrderDetail.query.filter_by(order_dish_id=dish_id).delete()
        SpecialDish.query.filter_by(dish_id=dish_id).delete()
        Dish.query.filter_by(id=dish_id).delete()
        db.session.commit()
        flash("Блюдо успешно удалено", "success")
        return redirect(url_for('admin'))

    if restaurant_form.rest_add_submit.data:
        if restaurant_form.validate_on_submit() or restaurant_form.is_submitted():
            name = restaurant_form.name.data
            address = restaurant_form.address.data
            contact = restaurant_form.contact.data
            passwd = restaurant_form.passwd.data
            service_uid = restaurant_form.service_uid.data
            email = restaurant_form.email.data if restaurant_form.email.data else None
            restaurant = Restaurant(
                name=name,
                address=address,
                contact=contact,
                passwd=passwd,
                service_uid=service_uid,
                email=email,
                min_total=0,
                enabled=True
            )
            db.session.add(restaurant)
            db.session.commit()
            flash("Ресторан добавлен", "success")
            return redirect(url_for('admin'))

    if category_delete_form.category_delete_submit.data:
        if category_delete_form.validate_on_submit() or category_delete_form.is_submitted():
            restaurant_id = request.form[
                'category_del_rest_selector'] if current_user.ownership == 'all' else category_delete_form.restaurant_id.data
            name = request.form['category_delete_select_field'] if current_user.ownership == 'all' else request.form[
                'category_rest_delete_select_field']
            db.session.query(Category).filter_by(name=name, restaurant_id=restaurant_id).delete()
            db.session.commit()
            flash("Категория успешно удалена", "success")
            return redirect(url_for('admin'))

    if restaurant_delete_form.rest_delete_submit.data:
        if restaurant_delete_form.validate_on_submit() or restaurant_delete_form.is_submitted():
            name = request.form['rest_delete_select_field']
            rest = Restaurant.query.filter_by(name=name).first()
            OrderDetail.query.filter_by(order_rest_id=rest.id).delete()
            Order.query.filter_by(order_rest_id=rest.id).delete()
            Dish.query.filter_by(id_rest=rest.id).delete()
            Category.query.filter_by(restaurant_id=rest.id).delete()
            SpecialDish.query.filter_by(rest_id=rest.id).delete()
            PromoDish.query.filter_by(rest_id=rest.id).delete()
            Favorites.query.filter_by(rest_id=rest.id).delete()
            Cart.query.filter_by(restaurant_id=rest.id).delete()
            RestaurantDeliveryTerms.query.filter_by(rest_id=rest.id).delete()
            Admin.query.filter_by(ownership=rest.name).delete()
            del rest
            Restaurant.query.filter_by(name=name).delete()
            del name
            db.session.commit()
            flash("Ресторан успешно удален", "success")
            return redirect(url_for('admin'))

    if restaurant_edit_form.rest_edit_submit.data:
        if restaurant_edit_form.validate_on_submit() or restaurant_edit_form.is_submitted():
            rest_id = restaurant_edit_form.id.data
            name = restaurant_edit_form.name.data
            address = restaurant_edit_form.address.data
            contact = restaurant_edit_form.contact.data
            passwd = restaurant_edit_form.passwd.data
            email = restaurant_edit_form.email.data
            min_total = restaurant_edit_form.min_total.data
            rest = Restaurant.query.filter_by(id=rest_id).first()
            owner = Admin.query.filter_by(ownership=rest.name).first()
            if name:
                rest.name = name
                if owner:
                    owner.ownership = name
            if address: rest.address = address
            if contact: rest.contact = contact
            if passwd: rest.passwd = passwd
            if email: rest.email = email
            if min_total: rest.min_total = min_total
            db.session.commit()
            flash("Изменения успешно внесены", "success")
            return redirect(url_for('admin'))

    if restaurant_enable_form.rest_enable_submit.data:
        if restaurant_enable_form.validate_on_submit() or restaurant_enable_form.is_submitted():
            enabled = True if request.form['rest_enable_submit'] == 'Включить' else False
            rest_id = restaurant_enable_form.rest_id.data
            try:
                rest = Restaurant.query.filter_by(id=rest_id).first()
                rest.enabled = enabled
                db.session.commit()
                flash("Изменения успешно внесены", "success")
            except Exception as e:
                flash(e)
            return redirect(url_for('admin'))

    if restaurant_info_form.rest_info_submit.data:
        if restaurant_info_form.validate_on_submit() or restaurant_info_form.is_submitted():
            rest_id = restaurant_info_form.rest_id.data
            img_link = None
            if restaurant_info_form.rest_img.data:
                if re.search(r'[а-яА-Я]', restaurant_info_form.rest_img.data.filename):
                    rest_img = secure_filename(translit(restaurant_info_form.rest_img.data.filename, reversed=True))
                else:
                    rest_img = secure_filename(restaurant_info_form.rest_img.data.filename)
                static_path = 'static/' + str(rest_id) + '/'
                if not isdir(static_path):
                    mkdir(static_path)
                restaurant_info_form.rest_img.data.save(static_path + rest_img)
                img_link = BASE_URL + static_path + rest_img
            delivery_time = restaurant_info_form.delivery_time.data
            takeaway_address = restaurant_info_form.takeaway_address.data
            try:
                db.session.add(
                    RestaurantInfo(rest_id=rest_id, img=img_link,
                                   delivery_time=delivery_time, takeaway_address=takeaway_address))
                db.session.commit()
            except Exception as e:
                flash(e)
            return redirect(url_for('admin'))

    if admin_add_form.admin_add_button.data:
        if admin_add_form.validate_on_submit() or admin_add_form.is_submitted():
            username = admin_add_form.username.data
            passwd = admin_add_form.passwd.data
            mail = admin_add_form.email.data
            ownership = request.form['admin_add_rest_selector']
            usr = Admin(username=username, email=mail, password=passwd, ownership=ownership)
            db.session.add(usr)
            db.session.commit()
            return redirect(url_for('admin'))

    if rest_delivery_terms_form.delivery_terms_submit.data:
        if rest_delivery_terms_form.validate_on_submit() or rest_delivery_terms_form.is_submitted():
            rest_id = rest_delivery_terms_form.rest_id.data
            terms = rest_delivery_terms_form.terms.data
            rest_inn = rest_delivery_terms_form.rest_inn.data
            rest_ogrn = rest_delivery_terms_form.rest_ogrn.data
            rest_fullname = rest_delivery_terms_form.rest_fullname.data
            rest_address = rest_delivery_terms_form.rest_address.data
            delivery_terms = RestaurantDeliveryTerms(
                rest_id=rest_id,
                terms=terms,
                rest_inn=rest_inn,
                rest_ogrn=rest_ogrn,
                rest_fullname=rest_fullname,
                rest_address=rest_address
            )
            db.session.add(delivery_terms)
            db.session.commit()
            return redirect(url_for('admin'))

    if rest_delivery_terms_edit_form.terms_edit_submit.data:
        if rest_delivery_terms_edit_form.validate_on_submit() or rest_delivery_terms_edit_form.is_submitted():
            rest_id = rest_delivery_terms_edit_form.rest_id.data
            terms_data = rest_delivery_terms_edit_form.terms.data
            rest_inn = rest_delivery_terms_edit_form.rest_inn.data
            rest_ogrn = rest_delivery_terms_edit_form.rest_ogrn.data
            rest_fullname = rest_delivery_terms_edit_form.rest_fullname.data
            rest_address = rest_delivery_terms_edit_form.rest_address.data
            terms = RestaurantDeliveryTerms.query.filter_by(rest_id=rest_id).first()
            if terms:
                terms.terms = terms_data if terms_data else None
                terms.rest_inn = rest_inn if rest_inn else None
                terms.rest_ogrn = rest_ogrn if rest_ogrn else None
                terms.rest_fullname = rest_fullname if rest_fullname else None
                terms.rest_address = rest_address if rest_address else None
                db.session.commit()
            return redirect(url_for('admin'))

    return render_template(
        'admin.html',
        dishes=dishes,
        s_dishes=s_dishes,
        promo_dishes=promo_dishes,
        search_dishes=search_dishes,
        search_words=search_words,
        restaurants=restaurants,
        categories=categories,
        subcategories=subcategories,
        dish_form=dish_form,
        promo_dishes_form=promo_dishes_form,
        category_form=category_form,
        subcategory_add_form=subcategory_add_form,
        subcategory_del_form=subcategory_del_form,
        special_dish_form=special_dish_form,
        special_dish_delete_form=special_dish_delete_form,
        dish_edit_form=dish_edit_form,
        dish_delete_form=dish_delete_form,
        promo_dishes_delete_form=promo_dishes_delete_form,
        restaurant_form=restaurant_form,
        category_delete_form=category_delete_form,
        restaurant_delete_form=restaurant_delete_form,
        restaurant_edit_form=restaurant_edit_form,
        restaurant_enable_form=restaurant_enable_form,
        admin_add_form=admin_add_form,
        rest_delivery_terms_form=rest_delivery_terms_form,
        rest_delivery_terms_edit_form=rest_delivery_terms_edit_form,
        search_word_form=search_word_form,
        search_word_del_form=search_word_del_form,
        search_dish_form=search_dish_form,
        search_dish_del_form=search_dish_del_form,
        delivery_terms=delivery_terms,
        restaurant_info_form=restaurant_info_form
    )
