from datetime import datetime
from itertools import chain
from os import mkdir
from os.path import isdir
from time import sleep

import pytz
import telebot.types
from PIL import Image
from flask import render_template, flash, redirect, url_for, Response
from sqlalchemy import func
from sqlalchemy.util import symbol

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, Update, WebAppInfo
from telebot.util import antiflood

from handlers import restaurant_callback, cart_callback, order_callback, other_callback, favorites_callback
from utils import check_user, write_history, rest_menu_keyboard, stat5, stat8, stat7, stat6, stat4, stat3, stat2, stat1

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
    text = 'Не могу найти то, что Вы ищете🧐 Попробуйте изменить запрос😊'
    result = None
    for word in message.text:
        result = db.session.query(SearchWords.id).filter(SearchWords.words.ilike("%" + word + "%")).first()
    if result:
        query = db.session.query(Category.id, Restaurant.name, Dish.img_link, SearchDishes.dish_name, Dish.composition,
                                 Dish.cost, Dish.id, Restaurant.id).filter(
            SearchDishes.search_words_id == result.id).filter(
            Restaurant.id == SearchDishes.rest_id, Dish.id == SearchDishes.dish_id).filter(
            Category.name == SearchDishes.dish_category, Category.restaurant_id == SearchDishes.rest_id).all()
        for item in query:
            text = f'{item[1]}\n<a href="{item[2]}">.</a>\n{item[3]}\n{item[4]}\n{item[5]} р.'
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
            kbd.add(InlineKeyboardButton('Меню ресторана', callback_data=f'rest_{item[7]}_menu'))
            kbd.add(InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart'))
            BOT.send_message(chat_id=message.chat.id, text=text, parse_mode='HTML', reply_markup=kbd)
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
    keyboard = InlineKeyboardMarkup()
    for dish in promo_dishes:
        text = f'<a href="{dish.img_link}">.</a>'
        cb_data = f'restaurant_{dish.rest_id}'
        keyboard.add(InlineKeyboardButton(text="Меню ресторана", callback_data=cb_data))
        BOT.send_message(chat_id=message.chat.id, text=text, parse_mode="HTML", reply_markup=keyboard)


@BOT.message_handler(commands=['show_cart'])
def show_cart(message):
    chat_id = message.from_user.id if type(message) is telebot.types.CallbackQuery else message.chat.id
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
