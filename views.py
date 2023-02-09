import datetime
from itertools import chain

import pytz
import telebot.types
from flask import render_template, flash, redirect, url_for, Response
from sqlalchemy.util import symbol

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, Update, WebAppInfo

from handlers import restaurant_callback, cart_callback, order_callback, other_callback
from utils import check_user, write_history, rest_menu_keyboard

from forms import LoginForm, DishForm, CategoryForm, DishDeleteForm, RestaurantForm, CategoryDeleteForm, \
    RestaurantDeleteForm, RestaurantEditForm, AdminAddForm, RestaurantDeliveryTermsForm, \
    RestaurantDeliveryTermsEditForm, SubcategoryForm, SpecialDishForm, PromoDishForm, PromoDishDeleteForm, \
    SpecialDishDeleteForm, DishEditForm, SubcategoryDeleteForm, SearchWordForm, SearchDishForm, SearchDishDelForm, \
    SearchWordDelForm, DateForm, RestaurantsEnableForm
from settings import BOT, BASE_URL, RULES, MONTHS, SET_WEBHOOK, YKT, ADMINS
from static.contract import contract_text

import re
import requests
import json

from flask import request
from flask_login import login_required, login_user, current_user, logout_user

from app import app, db, login_manager, send_email

from models import Restaurant, Category, Dish, Cart, User, Order, History, OrderDetail, Admin, \
    RestaurantDeliveryTerms, Subcategory, SpecialDish, PromoDish, Favorites, SearchWords, SearchDishes

from werkzeug.utils import secure_filename

from transliterate import translit

requests.get(SET_WEBHOOK)
# URL = f'https://api.telegram.org/bot{BOT_TOKEN}/'


def webAppKeyboardInline():
    keyboard = InlineKeyboardMarkup(row_width=1)
    webApp = WebAppInfo("https://telegram.mihailgok.ru")
    one = InlineKeyboardButton(text="Веб приложение", web_app=webApp)
    keyboard.add(one)
    return keyboard


def rest_menu_send_msg(chat_id):
    if type(chat_id) is Message:
        chat_id = chat_id.chat.id
    markup = rest_menu_keyboard()
    if not markup:
        text = 'В данное время нет работающих ресторанов'
        BOT.send_message(chat_id=chat_id, text=text)
    else:
        text = 'Пожалуйста, выберите ресторан:'
        BOT.send_message(chat_id=chat_id, text=text, reply_markup=markup)


def stat_menu_keyboard(message):
    if message.chat.id not in ADMINS:
        return 'Ok'
    keyboard = InlineKeyboardMarkup()
    for i in range(1, 8):
        keyboard.add(InlineKeyboardButton(f'{i}', callback_data=f'stat_{i}'))
    BOT.send_message(chat_id=message.chat.id, text='СТАТИСТИКА', reply_markup=keyboard)


def default_message(message):
    text = 'DEFAULT TEXT'
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
           "Здесь `Вы` можете заказать еду из ресторанов на доставку и самовывоз. "\
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
    date = YKT.localize(datetime.datetime.fromtimestamp(date)).strftime('%d.%m.%Y %H:%M:%S')
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
    BOT.send_message(message.chat.id, text)
    write_history(message.id, message.chat.id, text, is_bot=True)
    kb = rest_menu_keyboard()
    rests = []
    kb_parsed = list(chain.from_iterable(kb.keyboard))
    for item in kb_parsed:
        rests.append(item.text)
    combo_dishes = db.session.query(
            Dish, Restaurant, SpecialDish
        ).filter(SpecialDish.subcat_id == -1).filter(
            SpecialDish.dish_id == Dish.id, SpecialDish.rest_id == Restaurant.id
        ).all()
    cart = Cart.query.filter_by(user_uid=message.chat.id).all()
    for item in combo_dishes:
        """item[0] - Dish object, item[1] - Restaurant object"""
        keyboard = InlineKeyboardMarkup(row_width=4)
        text = ''
        text += f'<b>Ресторан {item[1].name}</b>'
        text += '\n' + item[0].name
        text += '\n' + item[0].composition
        text += f'\n {item[0].cost} р.'
        text += f'\n<a href="{item[0].img_link}">.</a>'
        quantity = 0
        cart_item = Cart.query.filter_by(user_uid=message.chat.id, dish_id=item[0].id).first()
        if cart_item:
            quantity = cart.quantity
        cb_data = f'fav_{message.chat.id}_{item[1].id}_{item[0].id}'
        cb_data_first = f'restaurant_{item[1].id}_cat{item[2].category_id}_dish_{item[0].id}'
        cb_data_last = f'{message.chat.id}_{message.id}'
        button1 = InlineKeyboardButton(text='⭐', callback_data=cb_data)
        button2 = InlineKeyboardButton(text='-', callback_data=f'{cb_data_first}_rem_{cb_data_last}')
        button3 = InlineKeyboardButton(text=f'{quantity} шт.', callback_data='None')
        button4 = InlineKeyboardButton(text='+', callback_data=f'{cb_data_first}_add_{cb_data_last}')
        total = 0
        for cart_item in cart:
            total += cart_item.price
        cb_text = f'В корзину: заказ на сумму {total} р'
        keyboard.add(button1, button2, button3, button4)
        keyboard.add(InlineKeyboardButton(text=cb_text, callback_data='cart'))
        BOT.send_message(chat_id=message.chat.id, text=text, parse_mode='HTML', reply_markup=keyboard)
    write_history(message.id, message.chat.id, text, is_bot=True)


@BOT.message_handler(commands=['recommend'])
def recommend(message):
    text = 'Здесь представлены блюда разных Ресторанов. Обращайте внимание на название Ресторана ' \
           'в описании блюда. В корзину можно добавить блюда только одного Ресторана. '
    keyboard = InlineKeyboardMarkup()
    cb_data = f'subcat_remmend_'
    for subcat in Subcategory.query.all():
        keyboard.add(InlineKeyboardButton(text=subcat.name, callback_data=f'{cb_data}{subcat.id}'))
    BOT.send_message(chat_id=message.chat.id, text=text, reply_markup=keyboard)
    write_history(message.id, message.chat.id, text, is_bot=True)


@BOT.message_handler(commands=['promotions'])
def promotions(message):
    promo_dishes = PromoDish.query.all()
    for dish in promo_dishes:
        text = f'<a href="{dish.img_link}">.</a>'
        cb_data = f'restaurant_{dish.id_rest}'
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text="Меню ресторана", callback_data=cb_data))
        BOT.send_message(chat_id=message.chat.id, text=text, parse_mode="HTML", reply_markup=keyboard)


@BOT.message_handler(commands=['show_cart'])
def show_cart(message):
    print(type(message))
    if type(message) is telebot.types.CallbackQuery:
        chat_id = message.from_user.id
    else:
        chat_id = message.chat.id
    cart = Cart.query.filter_by(user_uid=chat_id).all()
    if not cart:
        text = 'Ваша корзина пуста'
        BOT.send_message(chat_id=chat_id, text=text)
        return 'Ok', 200
    keyboard = InlineKeyboardMarkup()
    rest = db.session.query(Restaurant.name).filter_by(id=cart[0].restaurant_id).first()[0]
    total = 0
    cart_count = db.session.query(Cart.quantity).filter(Cart.id == cart[0].id).first()[0]
    text = '<b>Корзина</b>\n'
    row = [InlineKeyboardButton(text='❌', callback_data=f'cart_item_id_{cart[0].id}_clear')]
    for i, item in enumerate(cart, start=1):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f'cart_item_id_{item.id}'))
        total += item.price * item.quantity
    keyboard.row(*row)
    cart_dish_id = None if not cart else db.session.query(Cart.dish_id).filter(Cart.id == cart[0].id).first()[0]
    current_dish = Dish.query.filter_by(id=cart_dish_id).first()
    text += f'<a href="{current_dish.img_link}">{rest}</a>'
    text += f'\n{current_dish.composition}'
    text += f'\n{cart[0].price}'
    keyboard.row(
        InlineKeyboardButton('-️', callback_data=f'cart_id_{cart[0].id}_remove'),
        InlineKeyboardButton(f'{cart_count} шт.', callback_data='None'),
        InlineKeyboardButton('+️', callback_data=f'cart_id_{cart[0].id}_add')
    )
    keyboard.row(
        InlineKeyboardButton('Очистить️', callback_data=f'cart_purge'),
        InlineKeyboardButton('Меню️️', callback_data=f'restaurant_{cart[0].restaurant_id}')
    )
    keyboard.add(InlineKeyboardButton(f'Оформить заказ на сумму {total}', callback_data='cart_confirm'))
    BOT.send_message(text=text, chat_id=chat_id, parse_mode="HTML", reply_markup=keyboard)


@BOT.message_handler(commands=["favorites"])
def favorites(message):
    favs = db.session.query(Favorites.rest_id, Restaurant.name).filter_by(
        uid=message.chat.id).filter(Favorites.rest_id == Restaurant.id).distinct().all()
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
        "Рестораны": rest_menu_send_msg,
        "Комбо Наборы (КБ)": combo,
        "Рекомендуем": recommend,
        "Акции": promotions,
        "Корзина": show_cart,
        "Статистика": stat_menu_keyboard,
    }
    options.get(message.text, default_message)(message)


@BOT.callback_query_handler(func=lambda call: True)
def callback_query(call):
    """Обработка колбэков"""
    req = call.data.split('_')
    options = {
        'restaurant': restaurant_callback,
        'cart': cart_callback,
        'order': order_callback,
    }
    if call.data == 'cart':
        show_cart(call)
        return 'Ok', 200
    options.get(req[0], other_callback)(call)


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@login_manager.user_loader
def load_user(user_id):
    return db.session.query(Admin).get(user_id)
