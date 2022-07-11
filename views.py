import sqlite3
import traceback
from datetime import datetime, timedelta
from os import mkdir
from os.path import isdir
from itertools import chain

import pytz
import telegram.error
from flask import render_template, flash, redirect, url_for, jsonify
from sqlalchemy.util import symbol
from telegram import Bot, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, KeyboardButton
from telegram import error

from forms import LoginForm, DishForm, CategoryForm, DishDeleteForm, RestaurantForm, CategoryDeleteForm, \
    RestaurantDeleteForm, RestaurantEditForm, AdminAddForm, RestaurantDeliveryTermsForm, \
    RestaurantDeliveryTermsEditForm, SubcategoryForm, SpecialDishForm, PromoDishForm, PromoDishDeleteForm, \
    SpecialDishDeleteForm, DishEditForm, SubcategoryDeleteForm
from settings import BOT_TOKEN, BASE_URL, RULES, MONTHS
from static.contract import contract_text

import re
import requests
import json

from flask import request
from flask_login import login_required, login_user, current_user, logout_user

from app import app, db, sched, login_manager, send_email

from models import Restaurant, Category, Dish, Cart, User, Order, History, OrderDetail, Admin, \
    RestaurantDeliveryTerms, Subcategory, SpecialDish, PromoDish, Favorites

from werkzeug.utils import secure_filename

from transliterate import translit

BOT = Bot(BOT_TOKEN)
URL = f'https://api.telegram.org/bot{BOT_TOKEN}/'
YKT = pytz.timezone('Asia/Yakutsk')


@app.route('/', methods=['POST', 'GET'])
def index():
    if request.method == 'POST' and (request.get_json().get('callback_query') or request.get_json().get('message')):
        r = request.get_json()
        write_json(json.loads(json.dumps(r)))

        try:
            chat_id, first_name, last_name, username, date = None, None, None, None, None
            message_id, msg_text, msg_type = None, None, None
            if get_value('callback_query', r):
                chat_id = r.get('callback_query').get('message').get('chat').get('id')
                first_name = r.get('callback_query').get('message').get('chat').get('first_name')
                last_name = r.get('callback_query').get('message').get('chat').get('last_name')
                username = r.get('callback_query').get('message').get('chat').get('username')
                message_id = r.get('callback_query').get('message').get('message_id')
                msg_text = r.get('callback_query').get('message').get('text')
            elif get_value('message', r):
                chat_id = r.get('message').get('chat').get('id')
                first_name = r.get('message').get('chat').get('first_name')
                last_name = r.get('message').get('chat').get('last_name')
                username = r.get('message').get('chat').get('username')
                message_id = r.get('message').get('message_id')
                msg_text = r.get('message').get('text')
            else:
                raise Exception('Wrong message type', r)
            user = db.session.query(User).filter_by(uid=chat_id).first()
            if not user:
                print(r)
                print("User adding:", chat_id, first_name, last_name, username)
                user = User(uid=chat_id, first_name=first_name, last_name=last_name, username=username)
                db.session.add(user)
                db.session.commit()
            write_history(message_id, chat_id, msg_text, is_bot=False)

            # Callback handlers
            if get_value("callback_query", r):
                data = r['callback_query']['data']
                print(data)
                buttons = []
                if History.query.filter_by(message_id=r['callback_query']['message']['message_id']):
                    message_id = r['callback_query']['message']['message_id']
                else:
                    message_id = History.query.filter_by(chat_id=chat_id).order_by(History.message_id.desc()).first()
                    message_id = message_id.message_id
                print(message_id)
                if re.search(r'(restaurant_[0-9]+$)|'
                             r'(restaurant_[0-9]+_menu$)|'
                             r'(restaurant_[0-9]+_from_promo)', data):
                    rest_id = int(data.split('_')[1])
                    categories = Category.query.filter_by(restaurant_id=rest_id).all()
                    rest_name = Restaurant.query.filter_by(id=rest_id).first().name
                    for category in categories:
                        buttons.append(
                            [InlineKeyboardButton(category.name,
                                                  callback_data=f'restaurant_{rest_id}_cat{category.id}')])
                    cb_data = f'restaurant_{rest_id}_delivery_time'
                    buttons.append([InlineKeyboardButton('Узнать время доставки', callback_data=cb_data)])
                    cb_data = f'restaurant_{rest_id}_delivery_terms'
                    buttons.append([InlineKeyboardButton('Условия доставки', callback_data=cb_data)])
                    text = f'Меню ресторана {rest_name}. В некоторых случаях доставка платная, районы и стоимость ' \
                           'смотрите в "Условия доставки " в списке меню Ресторана.'
                    cb_data = 'back_to_rest_kb'
                    if 'from_promo' not in data:
                        buttons.append([InlineKeyboardButton('Назад', callback_data=cb_data)])
                    if 'menu' in data:
                        BOT.sendMessage(
                            text=text,
                            chat_id=chat_id,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    else:
                        BOT.editMessageText(
                            text=text,
                            chat_id=chat_id,
                            message_id=message_id,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                elif re.search(r'back_to_rest_kb', data):
                    text = 'Пожалуйста, выберите ресторан:'
                    BOT.editMessageText(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        reply_markup=rest_menu_keyboard()
                    )
                elif re.search(r'back_to_rest_promo', data):
                    promo_dish = PromoDish.query.filter_by().first()
                    text = f'<a href="{promo_dish.img_link}">.</a>'
                    cb_data = f'restaurant_{promo_dish.rest_id}_from_promo'
                    button = [InlineKeyboardButton('Меню ресторана', callback_data=cb_data)]
                    markup = InlineKeyboardMarkup([button])
                    BOT.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML
                    )
                elif re.search(r'(restaurant_[0-9]+_cat[0-9]+$)', data) \
                        or re.search(r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_add_[0-9]+_[0-9]+$)', data) \
                        or re.search(r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_rem_[0-9]+_[0-9]+$)', data):
                    rest_id, cat_id = int(data.split('_')[1]), int(data.split('_')[2][3:])
                    category = db.session.query(Category.name).filter_by(id=cat_id).first()[0]
                    rest_name = db.session.query(Restaurant.name).filter_by(id=rest_id).first()[0]
                    sql_result = Dish.query.filter_by(id_rest=rest_id, category=category).all()

                    if len(data.split('_')) == 8:
                        dish_id = int(data.split('_')[4])
                        cur_chat_id = int(data.split('_')[6])
                        cur_msg_id = int(data.split('_')[7])
                        dish_name = None
                        cur_id = 0
                        for i, item in enumerate(sql_result):
                            if item.id == dish_id:
                                dish_name = item.name
                                cur_id = i
                        try:
                            dish_count = db.session.query(Cart.quantity).filter_by(name=dish_name, user_uid=cur_chat_id,
                                                                                   restaurant_id=data.split('_')[
                                                                                       1]).first()[0]
                        except TypeError:
                            dish_count = 0
                        if data.split('_')[5] == 'add':
                            if dish_count and dish_count > 0:
                                cart_item_updater = db.session.query(Cart).filter_by(
                                    name=sql_result[cur_id].name,
                                    user_uid=cur_chat_id,
                                    restaurant_id=data.split('_')[1]).first()
                                cart_item_updater.quantity += 1
                                db.session.commit()
                            else:
                                cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                                rest_id = int(data.split('_')[1])
                                text = ''
                                service_uid = db.session.query(Restaurant.service_uid).filter_by(id=rest_id).first()[0]
                                if cart:
                                    for item in cart:
                                        if rest_id != item.restaurant_id:
                                            text = 'Вы добавили блюдо другого ресторана. Корзина будет очищена.'
                                            db.session.query(Cart).filter_by(user_uid=chat_id, id=item.id).delete()
                                        db.session.commit()
                                cart_item = Cart(
                                    name=dish_name,
                                    price=sql_result[cur_id].cost,
                                    quantity=1,
                                    user_uid=cur_chat_id,
                                    is_dish=1,
                                    is_water=0,
                                    dish_id=data.split('_')[4],
                                    restaurant_id=data.split('_')[1],
                                    service_uid=service_uid
                                )
                                db.session.add(cart_item)
                                db.session.commit()
                                if text != '':
                                    BOT.sendMessage(chat_id=chat_id, text=text)
                        elif data.split('_')[5] == 'rem':
                            if dish_count and dish_count > 1:
                                cart_item_updater = db.session.query(Cart).filter_by(
                                    name=sql_result[cur_id].name,
                                    user_uid=cur_chat_id,
                                    restaurant_id=data.split('_')[1]).first()
                                cart_item_updater.quantity -= 1
                                db.session.commit()
                            elif dish_count and dish_count == 1:
                                db.session.query(Cart).filter_by(name=dish_name, user_uid=cur_chat_id,
                                                                 restaurant_id=data.split('_')[1]).delete()
                                db.session.commit()
                        text = f'{rest_name}\n'
                        text += f'<a href="{sql_result[cur_id].img_link}">.</a>'
                        text += f'\n<b>{dish_name}</b>'
                        text += f'\n{sql_result[cur_id].composition}'
                        text += f'\n{sql_result[cur_id].cost} р.'

                        dish_id = sql_result[cur_id].id
                        try:
                            cart_count = db.session.query(Cart.quantity).filter_by(user_uid=cur_chat_id,
                                                                                   dish_id=dish_id).first()[0]
                        except TypeError:
                            cart_count = 0
                        except IndexError:
                            cart_count = 0
                        cb_data_first = f'restaurant_{rest_id}_cat{cat_id}_dish_{dish_id}'
                        cb_data_last = f'{cur_chat_id}_{message_id}'
                        cb_data = f'fav_{chat_id}_{rest_id}_{dish_id}'
                        buttons = [[
                            InlineKeyboardButton('⭐️', callback_data=cb_data),
                            InlineKeyboardButton('-️',
                                                 callback_data=f'{cb_data_first}_rem_{cb_data_last}'),
                            InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                            InlineKeyboardButton('+️',
                                                 callback_data=f'{cb_data_first}_add_{cb_data_last}')
                        ]]
                        total = 0
                        cart_items = db.session.query(Cart).filter_by(user_uid=cur_chat_id).all()
                        if cart_items:
                            for item in cart_items:
                                total += item.price * item.quantity
                        buttons.append(
                            [InlineKeyboardButton('Главное меню', callback_data=f'restaurant_{rest_id}_menu')])
                        buttons.append(
                            [InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart')])
                        BOT.editMessageText(
                            chat_id=cur_chat_id,
                            text=text,
                            message_id=message_id,
                            reply_markup=InlineKeyboardMarkup(buttons),
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        text = 'Если отключены автозагрузки фотографий для удобства просмотра блюд включите в ' \
                               'настройках Telegram - Данные и память, Автозагрузка медиа, включить Фото через ' \
                               'мобильную сеть и через Wi-Fi. '
                        BOT.sendMessage(text=text, chat_id=chat_id)
                        for current_id, dish in enumerate(sql_result, start=1):
                            text = f'{rest_name}\n'
                            text += f'<a href="{dish.img_link}">.</a>'
                            text += f'\n<b>{dish.name}</b>'
                            text += f'\n{dish.composition}'
                            text += f'\n{dish.cost} р.'

                            try:
                                cart_count = db.session.query(Cart.quantity).filter_by(user_uid=chat_id,
                                                                                       dish_id=dish.id).first()[0]
                            except TypeError:
                                cart_count = 0
                            except IndexError:
                                cart_count = 0
                            cb_data_first = f'restaurant_{rest_id}_cat{cat_id}_dish_{dish.id}'
                            cb_data_last = f'{chat_id}_{message_id + current_id}'
                            cb_data = f'fav_{chat_id}_{rest_id}_{dish.id}'
                            buttons = [[
                                InlineKeyboardButton('⭐️', callback_data=cb_data),
                                InlineKeyboardButton('-',
                                                     callback_data=f'{cb_data_first}_rem_{cb_data_last}'),
                                InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                                InlineKeyboardButton('+️',
                                                     callback_data=f'{cb_data_first}_add_{cb_data_last}')
                            ]]
                            total = 0

                            cart_items = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                            if cart_items:
                                for item in cart_items:
                                    total += item.price * item.quantity
                            buttons.append(
                                [InlineKeyboardButton('Главное меню', callback_data=f'restaurant_{rest_id}_menu')])
                            buttons.append(
                                [InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart')])

                            BOT.send_message(
                                text=text,
                                chat_id=chat_id,
                                reply_markup=InlineKeyboardMarkup(buttons),
                                parse_mode=ParseMode.HTML
                            )
                elif re.search(r'^restaurant_[0-9]+_delivery_terms$', data):
                    delivery_terms = RestaurantDeliveryTerms.query.filter_by(rest_id=int(data.split('_')[1])).first()
                    text = ''
                    if delivery_terms:
                        text += delivery_terms.terms + '\n'
                        if delivery_terms.rest_inn:
                            text += f'ИНН: {delivery_terms.rest_inn}\n'
                        if delivery_terms.rest_ogrn:
                            text += f'ОГРН: {delivery_terms.rest_ogrn}\n'
                        if delivery_terms.rest_fullname:
                            text += f'Название организации: {delivery_terms.rest_fullname}\n'
                        if delivery_terms.rest_address:
                            text += f'Адрес: {delivery_terms.rest_address}'
                    else:
                        text += 'Ресторан не предоставил сведений'
                    BOT.sendMessage(text=text, chat_id=chat_id)
                elif re.search(r'^restaurant_[0-9]+_delivery_time$', data):
                    rest_id = int(data.split('_')[1])
                    user = User.query.filter_by(uid=chat_id).first()
                    address = user.address
                    if address:
                        text = f'Вы указали:\nАдрес доставки: {address}'
                        cb_data1 = f'rest_{rest_id}_delivery_time_confirm_{chat_id}'
                        cb_data2 = f'rest_{rest_id}_delivery_time_change_{chat_id}'
                        buttons = [
                            [InlineKeyboardButton('Отправить', callback_data=cb_data1)],
                            [InlineKeyboardButton('Изменить данные', callback_data=cb_data2)]
                        ]
                        BOT.send_message(text=text, chat_id=chat_id, reply_markup=InlineKeyboardMarkup(buttons))
                    else:
                        rest_name = Restaurant.query.filter_by(id=rest_id).first().name
                        text = f'Укажите только адрес доставки для ресторана {rest_name}.'
                        BOT.send_message(text=text, chat_id=chat_id)
                    write_history(message_id, chat_id, text, is_bot=True)
                elif re.search(r'(^rest_[0-9]+_delivery_time_confirm_[0-9]+$)', data):
                    rest = Restaurant.query.filter_by(id=int(data.split('_')[1])).first()
                    user = User.query.filter_by(uid=int(data.split('_')[5])).first()
                    text = f'Ваш запрос отправлен, ждем ответа ресторана {rest.name}'
                    BOT.sendMessage(chat_id=user.uid, text=text)
                    text = f'Клиент хочет узнать время доставки, укажите примерное время.\n' \
                           f'Адрес доставки: {user.address}'
                    cb_text = 'Можем доставить за'
                    cb_text_no = 'Не можем доставить на этот адрес'
                    cb_data = f'rest_{rest.id}_uid_{user.uid}_delivery_time'
                    buttons = [
                        [InlineKeyboardButton(f'{cb_text} 30 минут', callback_data=f'{cb_data}_30')],
                        [InlineKeyboardButton(f'{cb_text} 1 час', callback_data=f'{cb_data}_60')],
                        [InlineKeyboardButton(f'{cb_text} 1 час 30 минут', callback_data=f'{cb_data}_90')],
                        [InlineKeyboardButton(f'{cb_text} 2 часа', callback_data=f'{cb_data}_120')],
                        [InlineKeyboardButton(f'{cb_text} 3 часа', callback_data=f'{cb_data}_180')],
                        [InlineKeyboardButton(cb_text_no, callback_data=f'{cb_data}_no')]
                    ]
                    BOT.sendMessage(
                        chat_id=rest.service_uid,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                elif re.search(r'(^rest_[0-9]+_delivery_time_change_[0-9]+$)', data):
                    rest = Restaurant.query.filter_by(id=int(data.split('_')[1])).first()
                    user = User.query.filter_by(uid=int(data.split('_')[5])).first()
                    text = f'Укажите только адрес доставки для ресторана {rest.name}'
                    BOT.send_message(text=text, chat_id=user.uid)
                    write_history(message_id, chat_id, text, is_bot=True)
                elif re.search(r'(^cart$)|'
                               r'(^cart_id_[0-9]+$)|'
                               r'(^cart_id_[0-9]+_clear$)|'
                               r'(^cart_purge$)|'
                               r'(^cart_id_[0-9]+_add$)|'
                               r'(^cart_id_[0-9]+_remove$)', data):
                    cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()

                    if len(cart) == 0:
                        text = 'Ваша корзина пуста'
                        BOT.send_message(chat_id=chat_id, text=text)
                        write_history(message_id, chat_id, text, is_bot=True)
                    else:
                        rest = db.session.query(Restaurant.name).filter_by(id=cart[0].restaurant_id).first()[0]
                        total = 0
                        current_id = cart[0].id
                        if re.search(r'(^cart_id_[0-9]+$)', data):
                            current_id = int(data.split('_')[2])
                        elif re.search(r'(^cart_id_[0-9]+_clear$)', data):
                            current_id = int(data.split('_')[2])
                            db.session.query(Cart).filter_by(id=current_id).delete()
                            db.session.commit()
                            cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                            cart_count = None
                            if cart:
                                current_id = cart[0].id
                                try:
                                    for item in cart:
                                        if current_id == item.id:
                                            cart_count = item.quantity
                                except UnboundLocalError:
                                    print("UnboundLocalError: local variable 'current_id' referenced before assignment")

                                buttons = []
                                if current_id:
                                    cart_buttons = [
                                        InlineKeyboardButton('❌', callback_data=f'cart_id_{current_id}_clear')]
                                else:
                                    cart_buttons = [
                                        InlineKeyboardButton('❌', callback_data=f'cart_id_{cart[0].id}_clear')]
                                text = '<b>Корзина</b>\n'
                                cart_dish_id = None
                                for i, item in enumerate(cart, start=1):
                                    cart_buttons.append(
                                        InlineKeyboardButton(f'{i}', callback_data=f'cart_id_{item.id}'))
                                    total += item.quantity * item.price

                                    if item.id == current_id:
                                        cart_dish_id = item.dish_id
                                dish = db.session.query(Dish).filter_by(id=cart_dish_id).first()
                                text += f'<a href="{dish.img_link}">{rest}</a>'
                                text += dish.name
                                text += f'\n{dish.composition}'
                                text += f'\n{dish.cost}'
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
                                BOT.editMessageText(
                                    text=text,
                                    chat_id=chat_id,
                                    message_id=message_id,
                                    reply_markup=InlineKeyboardMarkup(buttons),
                                    parse_mode=ParseMode.HTML
                                )
                                return text
                            else:
                                text = 'Ваша корзина пуста'
                                BOT.sendMessage(chat_id=chat_id, text=text)
                            return data
                        elif re.search(r'(^cart_purge$)', data):
                            db.session.query(Cart).filter_by(user_uid=chat_id).delete()
                            db.session.commit()
                            text = 'Ваша корзина пуста'
                            BOT.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
                            return text
                        elif re.search(r'(^cart_id_[0-9]+_add$)', data):
                            current_id = int(data.split('_')[2])
                            for item in cart:
                                if current_id == item.id:
                                    item.quantity += 1
                            db.session.commit()
                        elif re.search(r'(^cart_id_[0-9]+_remove$)', data):
                            current_id = int(data.split('_')[2])
                            for item in cart:
                                if current_id == item.id:
                                    if len(cart) >= 1 and item.quantity > 1:
                                        item.quantity -= 1
                                        db.session.commit()
                                    elif len(cart) == 1 and item.quantity == 1:
                                        db.session.query(Cart).filter_by(id=current_id).delete()
                                        db.session.commit()
                                        text = 'Ваша корзина пуста'
                                        BOT.editMessageText(chat_id=chat_id, message_id=message_id, text=text)
                                        return 'empty cart'
                                    elif len(cart) > 1 and item.quantity == 1:
                                        db.session.query(Cart).filter_by(id=current_id).delete()
                                        db.session.commit()
                                        cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                                        current_id = cart[0].id
                                        cart_count = cart[0].quantity
                                        buttons = []
                                        cart_buttons = [
                                            InlineKeyboardButton('❌', callback_data=f'cart_id_{cart[0].id}_clear')]
                                        text = '<b>Корзина</b>\n'
                                        cart_dish_id = None
                                        for i, good in enumerate(cart, start=1):
                                            cart_buttons.append(
                                                InlineKeyboardButton(f'{i}', callback_data=f'cart_id_{good.id}'))
                                            total += item.quantity * good.price

                                            if good.id == current_id:
                                                cart_dish_id = good.dish_id
                                        dish = db.session.query(Dish).filter_by(id=cart_dish_id).first()
                                        text += f'<a href="{dish.img_link}">{rest}</a>'
                                        text += f'{dish.name}\n'
                                        text += f'\n{dish.composition}'
                                        text += f'\n{dish.cost}'
                                        buttons.append(cart_buttons)
                                        buttons.append([
                                            InlineKeyboardButton('-',
                                                                 callback_data=f'cart_id_{current_id}_remove'),
                                            InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                                            InlineKeyboardButton('+',
                                                                 callback_data=f'cart_id_{current_id}_add')
                                        ])
                                        buttons.append([
                                            InlineKeyboardButton('Очистить️',
                                                                 callback_data=f'cart_purge'),
                                            InlineKeyboardButton('Меню️',
                                                                 callback_data=f'restaurant_{cart[0].restaurant_id}')
                                        ])
                                        buttons.append([InlineKeyboardButton(f'Оформить заказ на сумму {total}',
                                                                             callback_data='cart_confirm')])
                                        BOT.editMessageText(
                                            text=text,
                                            chat_id=chat_id,
                                            message_id=message_id,
                                            reply_markup=InlineKeyboardMarkup(buttons),
                                            parse_mode=ParseMode.HTML
                                        )
                                        return "cart item removed"
                                    else:
                                        pass
                        cart_count = None
                        try:
                            for item in cart:
                                if current_id == item.id:
                                    cart_count = item.quantity
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
                        if dish is not None:
                            text += f'<a href="{dish.img_link}">{rest}</a>\n'
                            text += dish.name
                            text += f'\n{dish.composition}'
                            text += f'\n{dish.cost}'
                            buttons.append(cart_buttons)
                            buttons.append([
                                InlineKeyboardButton('-',
                                                     callback_data=f'cart_id_{current_id}_remove'),
                                InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                                InlineKeyboardButton('+',
                                                     callback_data=f'cart_id_{current_id}_add')
                            ])
                            buttons.append([
                                InlineKeyboardButton('Очистить️',
                                                     callback_data=f'cart_purge'),
                                InlineKeyboardButton('Меню️',
                                                     callback_data=f'restaurant_{cart[0].restaurant_id}')
                            ])
                            buttons.append([InlineKeyboardButton(f'Оформить заказ на сумму {total}',
                                                                 callback_data='cart_confirm')])
                        else:
                            text = 'Произошла ошибка, попробуйте еще раз'
                            cb_data = f'restaurant_{cart[0].restaurant_id}'
                            buttons = [InlineKeyboardButton('Меню️', callback_data=cb_data)]
                        if re.search(r'^cart$', data):
                            BOT.sendMessage(
                                text=text,
                                chat_id=chat_id,
                                reply_markup=InlineKeyboardMarkup(buttons),
                                parse_mode=ParseMode.HTML
                            )
                        else:
                            BOT.editMessageText(
                                text=text,
                                chat_id=chat_id,
                                message_id=message_id,
                                reply_markup=InlineKeyboardMarkup(buttons),
                                parse_mode=ParseMode.HTML
                            )
                elif re.search(r'(^cart_confirm$)', data):
                    items = Cart.query.filter_by(user_uid=chat_id).all()
                    total = 0
                    rest_id = None
                    for item in items:
                        total += item.price * item.quantity
                        rest_id = item.restaurant_id
                    restaurant = Restaurant.query.filter_by(id=rest_id).first()
                    if restaurant.min_total != 0 and total < restaurant.min_total:
                        text = f'Минимальная сумма заказа должна быть не менее {restaurant.min_total}'
                        buttons = [
                            [InlineKeyboardButton('Меню', callback_data=f'restaurant_{restaurant.id}')],
                            [InlineKeyboardButton('Корзина', callback_data='cart')]
                        ]
                        BOT.sendMessage(text=text, chat_id=chat_id, reply_markup=InlineKeyboardMarkup(buttons))
                    else:
                        buttons = [
                            [InlineKeyboardButton('Доставка', callback_data='cart_confirm_delivery')],
                            [InlineKeyboardButton('Самовывоз', callback_data='cart_confirm_takeaway')]
                        ]
                        BOT.sendMessage(
                            text='Выберите вариант:',
                            chat_id=chat_id,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                elif re.search(r'(^cart_confirm_delivery$)', data):
                    user = User.query.filter_by(uid=chat_id).first()
                    if not user or not user.address:
                        text = 'Укажите адрес доставки. Улица, дом, кв, подъезд:'
                        BOT.send_message(text=text, chat_id=chat_id)
                    else:
                        text = "Вы укалази:\n"
                        text += "Адрес доставки: " + user.address
                        text += "\nКонтактный номер: " + user.phone
                        buttons = [
                            [InlineKeyboardButton('Отправить', callback_data='order_confirm')],
                            [InlineKeyboardButton('Изменить данные', callback_data='cart_confirm_change')]
                        ]
                        BOT.sendMessage(
                            text=text,
                            chat_id=chat_id,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    write_history(message_id, chat_id, text, is_bot=True)
                elif re.search(r'(^cart_confirm_takeaway$)', data):
                    text = 'Напишите во сколько хотите забрать Ваш заказ ( в цифрах без букв)'
                    BOT.sendMessage(
                        text=text,
                        chat_id=chat_id
                    )
                    write_history(message_id, chat_id, text, is_bot=True)

                elif re.search(r'(^cart_confirm_change$)', data):
                    text = 'Укажите адрес доставки. Улица, дом, кв, подъезд:'
                    BOT.send_message(text=text, chat_id=chat_id)
                    write_history(message_id, chat_id, text, is_bot=True)

                elif data == 'to_rest':
                    rest_menu_edit_msg(chat_id, message_id)
                elif re.search(r'(^order_confirm$)|'
                               r'(^order_confirm_takeaway_.+)', data):
                    cart = Cart.query.filter_by(user_uid=chat_id).all()
                    rest = Restaurant.query.filter_by(id=cart[0].restaurant_id).first()
                    total = sum(list(map(lambda good: good.price * good.quantity, cart)))
                    try:
                        order = Order(
                            id=Order.query.order_by(Order.id.desc()).first().id+1,
                            uid=chat_id,
                            first_name=first_name,
                            last_name=last_name,
                            order_total=total,
                            order_rest_id=rest.id,
                            order_datetime=datetime.now(YKT).strftime('%s'),
                            order_confirm=False
                        )

                        text = f'Заказ оформлен, ждем подтверждения ресторана {rest.name}'
                        BOT.send_message(chat_id=order.uid, text=text)
                        print(order.id)
                        text = f'Поступил заказ № {order.id}\n'
                        text += 'Состав заказа:\n'
                        for item in cart:
                            db.session.add(OrderDetail(
                                order_id=order.id,
                                order_dish_name=item.name,
                                order_dish_cost=item.price,
                                order_dish_id=item.dish_id,
                                order_dish_quantity=item.quantity,
                                order_rest_id=order.order_rest_id
                            ))
                            text += f'{item.name} - {item.quantity} шт.\n'
                        text += f'Общая сумма заказа: {total} р.\n'
                        bt_text = "Принять и доставить"
                        cb_data = f'order_change_{order.id}'
                        if "takeaway" in data:
                            text += "Самовывоз, время " + data.split('_')[3]
                            cb_text = f'order_accept_{order.id}_0_{data.split("_")[3]}'
                            buttons = [
                                [InlineKeyboardButton('Принять', callback_data=cb_text)],
                                [InlineKeyboardButton('Отменить', callback_data=cb_data)]
                            ]
                        else:
                            text += f'Адрес доставки" ' \
                                    f'{db.session.query(User.address).filter_by(uid=order.uid).first()[0]}'
                            buttons = [
                                [InlineKeyboardButton(bt_text + ' за 30 минут',
                                                      callback_data=f'order_accept_{order.id}_30')],
                                [InlineKeyboardButton(bt_text + ' за 1 час',
                                                      callback_data=f'order_accept_{order.id}_60')],
                                [InlineKeyboardButton(bt_text + ' за 1 час и 30 минут',
                                                      callback_data=f'order_accept_{order.id}_90')],
                                [InlineKeyboardButton(bt_text + ' за 2 часа',
                                                      callback_data=f'order_accept_{order.id}_120')],
                                [InlineKeyboardButton(bt_text + ' за 3 часа',
                                                      callback_data=f'order_accept_{order.id}_180')],
                                [InlineKeyboardButton('Не принят', callback_data='None')],
                                [InlineKeyboardButton(f'Изменить заказ № {order.id}', callback_data=cb_data)]
                            ]
                        db.session.add(order)
                        Cart.query.filter_by(user_uid=chat_id).delete()
                        db.session.commit()

                        BOT.send_message(chat_id=rest.service_uid, text=text, reply_markup=InlineKeyboardMarkup(buttons))
                        write_history(message_id, chat_id, text, is_bot=True)

                        # Отправка email
                        send_email(rest.email, f"Поступил заказ из Robofood № {order.id}", text)

                    except IndexError:
                        text = "Произошла ошибка IndexError в order_confirm\n"
                        text += traceback.format_exc()
                        BOT.send_message(chat_id=113737020, text=text)
                elif re.search(r'^order_confirm_change_time_takeaway_+', data):
                    time = data.split('_')[5]
                    text = 'Напишите во сколько хотите забрать Ваш заказ.'
                    BOT.send_message(chat_id=chat_id, text=text)
                    write_history(message_id, chat_id, text, is_bot=True)
                elif re.search(r'^order_confirm_change_phone_takeaway_+', data):
                    time = data.split('_')[5]
                    phone = data.split('_')[6]
                    text = 'Укажите номер телефона для самовывоза:'
                    BOT.send_message(chat_id=chat_id, text=text)
                    write_history(message_id, chat_id, text, is_bot=True)
                elif re.search(r'^order_accept_[0-9]+_(30|60|90|120|180|240|0_.+)$', data):
                    order_id = int(data.split('_')[2])
                    time = int(data.split('_')[3])
                    order = db.session.query(Order).filter_by(id=order_id).first()
                    rest_name = Restaurant.query.filter_by(id=order.order_rest_id).first().name
                    pattern = r'(.[0-2][0-9]:[0-5][0-9](.*)[0-2][0-9]:[0-5][0-9])|' \
                              r'(.[а-яА-Я][a-яА-Я]-[а-яА-Я][a-яА-Я].[0-2][0-9]:[0-5][0-9](.*)[0-2][0-9]:[0-5][0-9])'
                    rest_name = re.sub(pattern, '', rest_name)
                    text = f'Ресторан {rest_name} принял ваш заказ № {order.id} '
                    time_text = ''
                    current_tz = pytz.timezone('Asia/Yakutsk')
                    if time > 0:
                        sched_time = current_tz.localize(datetime.now() + timedelta(minutes=time))
                    if time == 30:
                        time_text += 'и доставит в течении 30 минут'
                    elif time == 60:
                        time_text += 'и доставит в течение 1 часа'
                    elif time == 90:
                        time_text += 'и доставит в течении 1 часа и 30 минут'
                    elif time == 120:
                        time_text += 'и доставит в течении 2 часов'
                    elif time == 180:
                        time_text += 'и доставит в течении 3 часов'
                    elif time == 240:
                        time_text += 'и доставит в течении 3 часов'
                    BOT.send_message(chat_id=order.uid, text=text + time_text)
                    service_uid = db.session.query(Restaurant.service_uid).filter_by(id=order.order_rest_id).first()[0]
                    client = db.session.query(User).filter_by(uid=order.uid).first()

                    order_detail = db.session.query(OrderDetail).filter_by(order_id=order.id).all()
                    text = f'Поступил заказ № {order.id}\n'
                    text += 'Состав заказа:\n'
                    for item in order_detail:
                        text += f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n'
                    text += f'Общая сумма заказа: {order.order_total} р.\n'
                    text += f'Адрес доставки: {db.session.query(User.address).filter_by(uid=order.uid).first()[0]}'
                    cb_data = f'order_change_{order.id}'
                    if time != 0:
                        buttons = [
                            [InlineKeyboardButton('Принять и доставить за 30 минут',
                                                  callback_data=f'order_accept_{order.id}_30')],
                            [InlineKeyboardButton('Принять и доставить за 1 час',
                                                  callback_data=f'order_accept_{order.id}_60')],
                            [InlineKeyboardButton('Принять и доставить за 1 час и 30 минут',
                                                  callback_data=f'order_accept_{order.id}_90')],
                            [InlineKeyboardButton('Принять и доставить за 2 часа',
                                                  callback_data=f'order_accept_{order.id}_120')],
                            [InlineKeyboardButton('Принять и доставить за 3 часа',
                                                  callback_data=f'order_accept_{order.id}_180')],
                            [InlineKeyboardButton(f'Принят на доставку {time_text}', callback_data='None')],
                            [InlineKeyboardButton(f'Изменить заказ № {order.id}', callback_data=cb_data)]
                        ]
                        BOT.editMessageText(
                            chat_id=service_uid,
                            message_id=message_id,
                            text=text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )

                    text = f'Мы оповестили клиента, что Вы приняли заказ № {order.id}'
                    if time != 0:
                        text += f', доставка {time_text} на адрес: {client.address}\n'
                    else:
                        text += f'\nСамовывоз, {data.split("_")[4]}\n'
                    text += f'Контактный номер: {client.phone}'
                    BOT.send_message(chat_id=service_uid, text=text)
                    order.order_confirm = True
                    order.order_state = 'Подтверждена'
                    db.session.commit()

                elif re.search(r'^order_change_[0-9]+$', data):
                    order_id = int(data.split('_')[2])
                    order = db.session.query(Order).filter_by(id=order_id).first()
                    service_uid = db.session.query(Restaurant.service_uid).filter_by(id=order.order_rest_id).first()[0]
                    details = db.session.query(OrderDetail).filter_by(order_id=order_id).all()
                    text = f'Что хотите изменить в заказе № {order.id}?'
                    buttons = []
                    for detail in details:
                        cb_data = f'{detail.order_dish_name}, {detail.order_dish_quantity} шт.'
                        buttons.append([
                            InlineKeyboardButton(cb_data, callback_data='None'),
                            InlineKeyboardButton('❌', callback_data=f'order_{order.id}_del_{detail.id}')
                        ])
                    buttons.append([InlineKeyboardButton('Назад', callback_data=f'order_{order.id}_menu')])
                    BOT.editMessageText(
                        chat_id=service_uid,
                        message_id=message_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                    write_history(message_id, service_uid, text, is_bot=True)
                elif re.search(r'^order_[0-9]+_delivered$', data):
                    order_id = int(data.split('_')[1])
                    order = db.session.query(Order).filter_by(id=order_id).first()
                    order.order_state = 'Доставлен'
                    db.session.commit()
                    BOT.send_message(chat_id=chat_id, text='Доставка подтвеждена')
                elif re.search(r'^order_[0-9]+_del_[0-9]+', data):
                    order_id, detail_id = int(data.split('_')[1]), int(data.split('_')[3])
                    order = db.session.query(Order).filter_by(id=order_id).first()
                    service_uid = db.session.query(Restaurant.service_uid).filter_by(id=order.order_rest_id).first()[0]
                    try:
                        db.session.query(OrderDetail).filter_by(id=detail_id).delete()
                        total = 0
                        for item in db.session.query(OrderDetail).filter_by(order_id=order_id).all():
                            total += item.order_dish_cost * item.order_dish_quantity
                        order.order_total = total
                        db.session.commit()
                    except Exception:
                        BOT.send_message(chat_id=service_uid, text='При попытке удалить блюдо произошла ошибка')
                    details = OrderDetail.query.filter_by(order_id=order_id).all()
                    text = f'Что хотите изменить в заказе № {order.id}?'
                    buttons = []
                    if details:
                        for detail in details:
                            cb_data = f'{detail.order_dish_name}, {detail.order_dish_quantity} шт.'
                            buttons.append([
                                InlineKeyboardButton(cb_data, callback_data='None'),
                                InlineKeyboardButton('❌', callback_data=f'order_{order.id}_del_{detail.id}')
                            ])
                        cb_data = f'order_{order.id}_send2user'
                        buttons.append([InlineKeyboardButton('Отправить клиенту', callback_data=cb_data)])
                        buttons.append([InlineKeyboardButton('Назад', callback_data=f'order_{order.id}_menu')])
                        BOT.editMessageText(
                            chat_id=service_uid,
                            message_id=message_id,
                            text=text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    else:
                        try:
                            markup = rest_menu_keyboard()
                            uid = Order.query.filter_by(id=order_id).first().uid
                            rest_id = Order.query.filter_by(id=order_id).first().order_rest_id
                            rest_name = Restaurant.query.filter_by(id=rest_id).first().name
                            if not markup.inline_keyboard:
                                text = f'Ресторан {rest_name} отменил заказ. В данное время нет работающих ресторанов'
                                BOT.send_message(chat_id=uid, text=text)
                            else:
                                text = f'Ресторан {rest_name} отменил заказ. Пожалуйста, выберите ресторан:'
                                BOT.send_message(chat_id=uid, text=text, reply_markup=markup)
                            OrderDetail.query.filter_by(order_id=order_id).delete()
                            Order.query.filter_by(id=order_id).delete()
                            db.session.commit()
                            text = 'Заказ отменен, клиенту направлено соответствующее сообщение'
                            BOT.send_message(chat_id=service_uid, text=text)
                        except Exception:
                            text = 'При попытке отменить заказ произошла ошибка'
                            BOT.send_message(chat_id=service_uid, text=text)
                    write_history(message_id, service_uid, text, is_bot=True)
                elif re.search(r'(^order_[0-9]+_menu$)|'
                               r'(^order_[0-9]+_user_confirm$)', data):
                    order = db.session.query(Order).filter_by(id=int(data.split('_')[1])).first()
                    cb_data = f'order_change_{order.id}'
                    details = db.session.query(OrderDetail).filter_by(order_id=order.id).all()
                    total = sum(list(map(lambda good: good.order_dish_cost * good.order_dish_quantity, details)))
                    rest_name = db.session.query(Restaurant.name).filter_by(id=order.order_rest_id).first()[0]
                    service_uid = db.session.query(Restaurant.service_uid).filter_by(
                        id=order.order_rest_id).first()[0]
                    if re.search(r'(^order_[0-9]+_user_confirm$)', data):
                        text = f'Заказ оформлен, ждем подтверждения ресторана {rest_name}'
                        BOT.send_message(chat_id=order.uid, text=text)

                        text = f'Поступил заказ № {order.id}\n'
                        text += 'Состав заказа:\n'
                        for item in details:
                            text += f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n'
                        text += f'Общая сумма заказа: {total} р.\n'
                        text += f'Адрес доставки: {db.session.query(User.address).filter_by(uid=order.uid).first()[0]}'
                        buttons = [
                            [InlineKeyboardButton('Принять и доставить за 30 минут',
                                                  callback_data=f'order_accept_{order.id}_30')],
                            [InlineKeyboardButton('Принять и доставить за 1 час',
                                                  callback_data=f'order_accept_{order.id}_60')],
                            [InlineKeyboardButton('Принять и доставить за 2 часа',
                                                  callback_data=f'order_accept_{order.id}_120')],
                            [InlineKeyboardButton('Принять и доставить за 3 часа',
                                                  callback_data=f'order_accept_{order.id}_180')],
                            [InlineKeyboardButton('Не принят', callback_data='None')],
                            [InlineKeyboardButton(f'Изменить заказ № {order.id}', callback_data=cb_data)]
                        ]
                        BOT.sendMessage(
                            chat_id=service_uid,
                            text=text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    else:
                        text = f'Клиент согласен с изменением заказа № {order.id}\n'
                        text += 'Состав заказа:\n'
                        for item in details:
                            text += f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n'
                        text += f'Общая сумма заказа: {total} р.\n'
                        text += f'Адрес доставки: {db.session.query(User.address).filter_by(uid=order.uid).first()[0]}'
                        buttons = [
                            [InlineKeyboardButton('Принять и доставить за 30 минут',
                                                  callback_data=f'order_accept_{order.id}_30')],
                            [InlineKeyboardButton('Принять и доставить за 1 час',
                                                  callback_data=f'order_accept_{order.id}_60')],
                            [InlineKeyboardButton('Принять и доставить за 2 часа',
                                                  callback_data=f'order_accept_{order.id}_120')],
                            [InlineKeyboardButton('Принять и доставить за 3 часа',
                                                  callback_data=f'order_accept_{order.id}_180')],
                            [InlineKeyboardButton('Не принят', callback_data='None')],
                            [InlineKeyboardButton(f'Изменить заказ № {order.id}', callback_data=cb_data)]
                        ]
                        BOT.sendMessage(
                            chat_id=service_uid,
                            text=text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                elif re.search(r'^order_[0-9]+_send2user$', data):
                    order = db.session.query(Order).filter_by(id=int(data.split('_')[1])).first()
                    details = db.session.query(OrderDetail).filter_by(order_id=int(data.split('_')[1])).all()
                    rest = db.session.query(Restaurant).filter_by(id=order.order_rest_id).first()
                    BOT.sendMessage(text='Отправлен измененный заказ', chat_id=rest.service_uid)
                    text = f'<b>В связи с отсутствием одного из блюд, ресторан {rest.name} изменил Ваш заказ</b>\n'
                    text += 'Состав Вашего заказа:\n'
                    buttons = []
                    for item in details:
                        text += f'{item.order_dish_name}, {item.order_dish_quantity} шт.\n'
                    text += f'На общую сумму - {order.order_total} р.'
                    cb_text = f'Оформить заказ'
                    cb_data = f'order_{order.id}_user_confirm'
                    buttons.append([InlineKeyboardButton(cb_text, callback_data=cb_data)])
                    cb_data = f'order_{order.id}_user_change'
                    buttons.append([InlineKeyboardButton('Изменить заказ', callback_data=cb_data)])
                    cb_data = f'order_{order.id}_user_cancel'
                    buttons.append([InlineKeyboardButton('Отменить заказ', callback_data=cb_data)])
                    BOT.sendMessage(
                        text=text,
                        chat_id=order.uid,
                        reply_markup=InlineKeyboardMarkup(buttons),
                        parse_mode=ParseMode.HTML
                    )
                elif re.search(r'^order_[0-9]+_user_change$', data):
                    order = db.session.query(Order).filter_by(id=int(data.split('_')[1])).first()
                    order.order_state = 'Изменен'
                    service_uid = db.session.query(Restaurant.service_uid).filter_by(
                        id=order.order_rest_id).first()[0]
                    details = db.session.query(OrderDetail).filter_by(order_id=int(data.split('_')[1])).all()
                    for item in details:
                        cart_item = Cart(
                            name=item.order_dish_name,
                            price=item.order_dish_cost,
                            quantity=item.order_dish_quantity,
                            user_uid=order.uid,
                            is_dish=True,
                            is_water=False,
                            dish_id=item.order_dish_id,
                            restaurant_id=order.order_rest_id,
                            service_uid=service_uid
                        )
                        db.session.add(cart_item)
                        db.session.commit()
                    cart = db.session.query(Cart).filter_by(user_uid=order.uid).all()
                    text = f'Клиент решил изменить заказ № {order.id}. Номер заказа будет изменен.'
                    BOT.send_message(chat_id=service_uid, text=text)
                    rest = db.session.query(Restaurant.name).filter_by(id=order.order_rest_id).first()[0]
                    buttons = []
                    cart_buttons = [InlineKeyboardButton('❌', callback_data=f'cart_id_{cart[0].id}_clear')]
                    for i, item in enumerate(cart, start=1):
                        cart_buttons.append(InlineKeyboardButton(f'{i}', callback_data=f'cart_id_{item.id}'))
                    buttons.append(cart_buttons)
                    cb_data = f'cart_id_{cart[0].id}_'
                    buttons.append([
                        InlineKeyboardButton('-️', callback_data=cb_data + 'remove'),
                        InlineKeyboardButton(f'{cart[0].quantity} шт', callback_data='None'),
                        InlineKeyboardButton('+️', callback_data=cb_data + 'add')
                    ])
                    buttons.append([
                        InlineKeyboardButton('Очистить️',
                                             callback_data=f'cart_purge'),
                        InlineKeyboardButton('Меню️',
                                             callback_data=f'restaurant_{cart[0].restaurant_id}')
                    ])
                    cb_text = f'Оформить заказ на сумму {order.order_total}'
                    buttons.append([InlineKeyboardButton(cb_text, callback_data='cart_confirm')])
                    dish = db.session.query(Dish).filter_by(id=cart[0].dish_id).first()
                    text = '<b>Корзина</b>\n'
                    text += f'<a href="{dish.img_link}">{rest}</a>'
                    text += f'\n{dish.composition}'
                    text += f'\n{cart[0].price}'
                    BOT.send_message(
                        text=text,
                        chat_id=order.uid,
                        reply_markup=InlineKeyboardMarkup(buttons),
                        parse_mode=ParseMode.HTML
                    )
                elif re.search(r'^order_[0-9]+_user_cancel$', data):
                    order = db.session.query(Order).filter_by(id=int(data.split('_')[1])).first()
                    text = f'Ваш заказ № {order.id} отменен'
                    BOT.sendMessage(chat_id=order.uid, text=text)
                    service_uid = db.session.query(Restaurant.service_uid).filter_by(
                        id=order.order_rest_id).first()[0]
                    text = f'Клиент отменил заказ № {order.id}'
                    BOT.send_message(chat_id=service_uid, text=text)
                    order.order_state = 'Отменен'
                    db.session.commit()
                elif re.search(r'^rest_[0-9]+_uid_[0-9]+_delivery_time_(30|60|90|120|180|240|no)$', data):
                    rest_id, uid = int(data.split('_')[1]), int(data.split('_')[3])
                    service_uid = Restaurant.query.filter_by(id=rest_id).first().service_uid
                    client = User.query.filter_by(uid=uid).first()
                    rest_name = Restaurant.query.filter_by(id=rest_id).first().name
                    pattern = r'(.[0-2][0-9]:[0-5][0-9](.*)[0-2][0-9]:[0-5][0-9])|' \
                              r'(.[а-яА-Я][a-яА-Я]-[а-яА-Я][a-яА-Я].[0-2][0-9]:[0-5][0-9](.*)[0-2][0-9]:[0-5][0-9])'
                    rest_name = re.sub(pattern, '', rest_name)
                    try:
                        time = int(data.split('_')[6])
                        text = f'Ответ ресторана {rest_name}: примерное время доставки '
                        time_text = ''
                        if time == 30:
                            time_text += f'{time} минут'
                        elif time == 60:
                            time_text += '1 час'
                        elif time == 90:
                            time_text += '1 час и 30 минут'
                        elif time == 120 or time == 180 or time == 240:
                            time_text += f'{time // 60} часа'
                        text += time_text + f' на адрес {client.address}'
                        BOT.sendMessage(chat_id=uid, text=text)
                        text = f'Мы оповестили клиента, что можем доставить за {time_text} на адрес {client.address}'
                        BOT.sendMessage(chat_id=service_uid, text=text)
                    except ValueError:
                        text = f'К сожалению, ресторан {rest_name} не сможет осуществить доставку на указанный адрес'
                        BOT.sendMessage(chat_id=uid, text=text)
                        text = 'Мы оповестили клиента о невозможности осуществления доставки на указанный адрес'
                        BOT.sendMessage(chat_id=service_uid, text=text)
                elif re.search(r'^fav_[0-9]+_[0-9]+_[0-9]+$', data):
                    uid = int(data.split('_')[1])
                    rest_id = int(data.split('_')[2])
                    dish_id = int(data.split('_')[3])
                    favs = Favorites.query.all()
                    check = False
                    for fav in favs:
                        if fav.uid == uid and fav.dish_id == dish_id:
                            check = True
                    if not check:
                        db.session.add(Favorites(uid=uid, dish_id=dish_id, rest_id=rest_id))
                        db.session.commit()
                        text = 'Блюдо добавлено в избранное'
                        BOT.answer_callback_query(
                            callback_query_id=r.get('callback_query').get('id'),
                            show_alert=False, text=text
                        )
                    else:
                        text = 'Блюдо удалено из избранного'
                        Favorites.query.filter_by(uid=uid, dish_id=dish_id, rest_id=rest_id).delete()
                        db.session.commit()
                        BOT.answer_callback_query(
                            callback_query_id=r.get('callback_query').get('id'),
                            show_alert=False, text=text
                        )
                elif re.search(r'^fav_[0-9]+_rest_[0-9]+$', data):
                    uid = int(data.split('_')[1])
                    rest_id = int(data.split('_')[3])
                    favs = Favorites.query.filter_by(uid=uid, rest_id=rest_id).all()
                    for fav in favs:
                        dish = Dish.query.filter_by(id=fav.dish_id).first()
                        rest = Restaurant.query.filter_by(id=fav.rest_id).first().name
                        buttons = []
                        text = rest
                        text += f'\n<a href="{dish.img_link}">.</a>'
                        text += f'\n<b>{dish.name}</b>'
                        text += f'\n{dish.composition}'
                        text += f'\n{dish.cost} р.'
                        try:
                            quantity = Cart.query.filter_by(
                                user_uid=uid, dish_id=fav.dish_id, restaurant_id=rest_id).first().quantity
                        except AttributeError:
                            quantity = 0
                        cart = Cart.query.filter_by(user_uid=chat_id, restaurant_id=rest_id).all()
                        category_id = Category.query.filter_by(name=dish.category).first().id
                        cb_data = f'fav_{chat_id}_{rest_id}_{fav.dish_id}'
                        cb_data_first = f'restaurant_{rest_id}_cat{category_id}_dish_{fav.dish_id}'
                        cb_data_last = f'{chat_id}_{message_id}'
                        buttons.append([
                            InlineKeyboardButton('⭐️', callback_data=cb_data),
                            InlineKeyboardButton('-', callback_data=f'{cb_data_first}_rem_{cb_data_last}'),
                            InlineKeyboardButton(f'{quantity} шт', callback_data='None'),
                            InlineKeyboardButton('+', callback_data=f'{cb_data_first}_add_{cb_data_last}')
                        ])
                        cb_text = 'Меню ресторана'
                        buttons.append([InlineKeyboardButton(cb_text, callback_data=f'restaurant_{rest_id}')])
                        total = 0
                        for item in cart:
                            total += item.price
                        cb_text = f'В корзину: заказ на сумму {total} р'
                        buttons.append([InlineKeyboardButton(cb_text, callback_data='cart_confirm')])
                        markup = InlineKeyboardMarkup(buttons)
                        BOT.sendMessage(chat_id=uid, text=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                elif re.search(r'^subcat_recommend_[0-9]+$', data):
                    subcat_id = int(data.split('_')[2])
                    s_dishes = SpecialDish.query.filter_by(subcat_id=subcat_id).order_by(SpecialDish.rest_id).all()
                    dishes = Dish.query.all()
                    restaurants = Restaurant.query.all()
                    kb = rest_menu_keyboard()
                    buttons = list(chain.from_iterable(kb['inline_keyboard']))
                    rests = []
                    for item in buttons:
                        rests.append(item['text'])
                    for s_dish in s_dishes:
                        text = ''
                        buttons = []
                        for dish in dishes:
                            if s_dish.dish_id == dish.id:
                                for restaurant in restaurants:
                                    if restaurant.name in rests and restaurant.id == s_dish.rest_id:
                                        rest_id = restaurant.id
                                        text += f'<b>{restaurant.name}</b>'
                                        text += '\n' + dish.name
                                        text += '\n' + dish.composition
                                        text += '\n' + str(dish.cost)
                                        text += f'\n<a href="{dish.img_link}">.</a>'
                                        cart = Cart.query.filter_by(
                                            user_uid=chat_id, dish_id=s_dish.dish_id, restaurant_id=rest_id
                                        ).first()
                                        quantity = 0
                                        if cart:
                                            quantity = cart.quantity
                                        cart = Cart.query.filter_by(user_uid=chat_id, restaurant_id=rest_id).all()
                                        cb_data = f'fav_{chat_id}_{rest_id}_{s_dish.dish_id}'
                                        cb_data_first = f'restaurant_{rest_id}_cat{s_dish.category_id}_dish_{s_dish.dish_id}'
                                        cb_data_last = f'{chat_id}_{message_id}'
                                        buttons.append([
                                            InlineKeyboardButton('⭐️', callback_data=cb_data),
                                            InlineKeyboardButton('-', callback_data=f'{cb_data_first}_rem_{cb_data_last}'),
                                            InlineKeyboardButton(f'{quantity} шт', callback_data='None'),
                                            InlineKeyboardButton('+', callback_data=f'{cb_data_first}_add_{cb_data_last}')
                                        ])
                                        total = 0
                                        for item in cart:
                                            total += item.price
                                        cb_text = f'В корзину: заказ на сумму {total} р'
                                        buttons.append([InlineKeyboardButton(cb_text, callback_data='cart')])
                                        BOT.send_message(
                                            chat_id=chat_id,
                                            text=text,
                                            reply_markup=InlineKeyboardMarkup(buttons),
                                            parse_mode=ParseMode.HTML
                                        )
                elif re.search(r'^user_orders_[0-9]+$', data):
                    order = Order.query.filter_by(uid=chat_id).order_by(Order.id.desc()).first()
                    if order:
                        details = OrderDetail.query.filter_by(order_id=order.id).all()
                        text = f'Заказ № {order.id}\n'
                        text += f'Статус: {order.order_state}\n'
                        text += 'Состав заказа:\n'
                        for item in details:
                            text += f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n'
                        text += f'Сумма - {order.order_total} р.'
                    else:
                        text = 'У вас нет заказов'
                    BOT.sendMessage(chat_id=chat_id, text=text)
                elif re.search(r'^show_contract$', data):
                    BOT.send_message(chat_id, 'https://telegra.ph/Polzovatelskoe-soglashenie-12-07-5')
                elif re.search(r'^show_rules$', data):
                    BOT.send_message(chat_id, RULES)

                elif re.search(r'^stat_[0-9]+$', data):
                    stat_id = int(data.split('_')[1])
                    stat_data = db.session.query(Order).all()

                    if stat_id == 1:
                        BOT.send_message(chat_id=chat_id, text=stat1())
                    elif stat_id == 2:
                        BOT.send_message(chat_id=chat_id, text=f'Количество заказов по ресторанам\n{stat_data}')
                    elif stat_id == 3:
                        BOT.send_message(chat_id=chat_id, text=f'Количество заказов в общем\n{stat_data}')
                    elif stat_id == 4:
                        BOT.send_message(chat_id=chat_id, text=f'Статистика заказов блюд\n{stat_data}')
                    elif stat_id == 5:
                        BOT.send_message(chat_id=chat_id, text=f'Количество изменений в заказе\n{stat_data}')
                    elif stat_id == 6:
                        BOT.send_message(chat_id=chat_id, text=f'Количество отмен заказов\n{stat_data}')
                    elif stat_id == 7:
                        BOT.send_message(chat_id=chat_id, text=f'Количество посещений\n{stat_data}')

            else:
                # write message handlers
                try:
                    message = r['message']['text']
                    message_id = r['message']['message_id']
                    if r["message"]["chat"]["first_name"] != '':
                        name = r["message"]["chat"]["first_name"]
                    else:
                        name = r["message"]["chat"]["username"]
                    try:
                        bot_msg = History.query.filter_by(
                            chat_id=chat_id,
                            is_bot=True
                        ).order_by(History.id.desc()).first().message_text
                    except AttributeError:
                        bot_msg = None
                    restaurants = db.session.query(Restaurant).all()
                    for rest in restaurants:
                        if message == rest.passwd:
                            rest.service_uid = chat_id
                            BOT.send_message(chat_id=chat_id,
                                             text=f'Вы назначены администратором ресторана {rest.name}')
                            db.session.commit()
                            return 'Restaurant service uid correction'

                    # Обработка события /start
                    if parse_text(message) == '/start':
                        text = f'Приветствую, {name}!\nВыбери что нужно.'
                        remove_keyboard = {'remove_keyboard': True}
                        remove_keyboard_encoded = json.dumps(remove_keyboard)
                        BOT.send_message(chat_id, text, reply_markup=remove_keyboard_encoded)
                    elif parse_text(message) == '/my_orders':
                        order = Order.query.filter_by(uid=chat_id, order_state='Подтверждена')
                        order = order.order_by(Order.id.desc()).first()
                        rest = Restaurant.query
                        if order and rest.filter_by(id=order.order_rest_id).first():
                            date = order.order_datetime
                            current_tz = pytz.timezone('Asia/Yakutsk')
                            date = current_tz.localize(datetime.fromtimestamp(date)).strftime('%d.%m.%Y %H:%M:%S')
                            text = f'Ваш заказ № {order.id} от {date}\n'
                            details = db.session.query(OrderDetail).filter_by(order_id=order.id).all()
                            for item in details:
                                text += f'- {item.order_dish_name}\n'
                            text += f'Общая стоимость заказа - {order.order_total}\n'
                            try:
                                restaurant = Restaurant.query.filter_by(id=order.order_rest_id).first()
                                text += f'Ресторан - {restaurant.name}, {restaurant.address}, {restaurant.contact}'
                            except AttributeError as e:
                                print(e)
                                text = 'Возникла ошибка при обработке команды. Пожалуйста, свяжитесь с администратором.'
                        else:
                            text = 'У Вас пока нет оформленных заказов'
                        BOT.send_message(chat_id=chat_id, text=text)
                    elif parse_text(message) == 'Рестораны' or parse_text(message) == '/restaurants':
                        rest_menu_send_msg(chat_id)
                    elif parse_text(message) == 'Комбо Наборы (КБ)' or parse_text(message) == '/combo_set':
                        text = 'Здесь представлены лучшие Комбо Наборы разных ресторанов:'
                        BOT.send_message(chat_id=chat_id, text=text)
                        write_history(message_id, chat_id, text, is_bot=True)
                        combo_dishes = SpecialDish.query.filter_by(subcat_id=-1).order_by(SpecialDish.rest_id).all()
                        dishes = Dish.query.all()
                        restaurants = Restaurant.query.all()
                        kb = rest_menu_keyboard()
                        buttons = list(chain.from_iterable(kb['inline_keyboard']))
                        rests = []
                        for item in buttons:
                            rests.append(item['text'])
                        for combo in combo_dishes:
                            text = ''
                            buttons = []
                            for dish in dishes:
                                if combo.dish_id == dish.id:
                                    for restaurant in restaurants:
                                        if restaurant.name in rests and restaurant.id == combo.rest_id:
                                            rest_id = restaurant.id
                                            text += f'<b>Ресторан {restaurant.name}</b>'
                                            text += '\n' + dish.name
                                            text += '\n' + dish.composition
                                            text += '\n' + str(dish.cost) + ' р.'
                                            text += f'\n<a href="{dish.img_link}">.</a>'
                                            cart = Cart.query.filter_by(
                                                user_uid=chat_id, dish_id=combo.dish_id, restaurant_id=rest_id
                                            ).first()
                                            quantity = 0
                                            if cart:
                                                quantity = cart.quantity
                                            cart = Cart.query.filter_by(user_uid=chat_id, restaurant_id=rest_id).all()
                                            cb_data = f'fav_{chat_id}_{rest_id}_{combo.dish_id}'
                                            cb_data_first = f'restaurant_{rest_id}_cat{combo.category_id}_dish_{combo.dish_id}'
                                            cb_data_last = f'{chat_id}_{message_id}'
                                            buttons.append([
                                                InlineKeyboardButton('⭐️', callback_data=cb_data),
                                                InlineKeyboardButton('-', callback_data=f'{cb_data_first}_rem_{cb_data_last}'),
                                                InlineKeyboardButton(f'{quantity} шт', callback_data='None'),
                                                InlineKeyboardButton('+', callback_data=f'{cb_data_first}_add_{cb_data_last}')
                                            ])
                                            total = 0
                                            for item in cart:
                                                total += item.price
                                            cb_text = f'В корзину: заказ на сумму {total} р'
                                            buttons.append([InlineKeyboardButton(cb_text, callback_data='cart')])
                                            BOT.send_message(
                                                chat_id=chat_id,
                                                text=text,
                                                reply_markup=InlineKeyboardMarkup(buttons),
                                                parse_mode=ParseMode.HTML
                                            )
                        write_history(message_id, chat_id, text, is_bot=True)
                    elif parse_text(message) == 'Рекомендуем' or parse_text(message) == '/recommend':
                        text = 'Рекомендуем'
                        buttons = []
                        for sub in Subcategory.query.all():
                            buttons.append([InlineKeyboardButton(sub.name, callback_data=f'subcat_recommend_{sub.id}')])
                        BOT.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(buttons))
                        write_history(message_id, chat_id, text, is_bot=True)
                    elif parse_text(message) == 'Акции' or parse_text(message) == '/promotions':
                        promo_dishes = PromoDish.query.all()
                        for promo_dish in promo_dishes:
                            text = f'<a href="{promo_dish.img_link}">.</a>'
                            cb_data = f'restaurant_{promo_dish.rest_id}_from_promo'
                            button = [InlineKeyboardButton('Меню ресторана', callback_data=cb_data)]
                            markup = InlineKeyboardMarkup([button])
                            BOT.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode=ParseMode.HTML)
                    elif parse_text(message) == 'Корзина' or parse_text(message) == '/show_cart':
                        cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                        if len(cart) == 0:
                            text = 'Ваша корзина пуста'
                            BOT.send_message(chat_id=chat_id, text=text)
                        else:
                            rest = db.session.query(Restaurant.name).filter_by(id=cart[0].restaurant_id).first()[0]
                            dishes = db.session.query(Dish).all()
                            total = 0

                            current_id = cart[0].id
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
                                    text += f'\n{dish.composition}'
                                    text += f'\n{cart[0].price}'
                            buttons.append(cart_buttons)
                            buttons.append([
                                InlineKeyboardButton('-️',
                                                     callback_data=f'cart_id_{cart[0].id}_remove'),
                                InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                                InlineKeyboardButton('+️',
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
                                reply_markup=InlineKeyboardMarkup(buttons),
                                parse_mode=ParseMode.HTML
                            )
                    elif parse_text(message) == '/favorites':
                        favs = Favorites.query.filter_by(uid=chat_id).all()
                        if not favs:
                            BOT.sendMessage(chat_id=chat_id, text='У Вас пусто в Избранном')
                        else:
                            buttons = []
                            for fav in favs:
                                rest = Restaurant.query.filter_by(id=fav.rest_id).first()
                                cb_data = f'fav_{chat_id}_rest_{fav.rest_id}'
                                if [InlineKeyboardButton(rest.name, callback_data=cb_data)] not in buttons:
                                    buttons.append([InlineKeyboardButton(rest.name, callback_data=cb_data)])
                            markup = InlineKeyboardMarkup(buttons)
                            text = 'Выберите ресторан'
                            BOT.sendMessage(chat_id=chat_id, text=text, reply_markup=markup)
                            write_history(message_id, chat_id, text, is_bot=True)

                    elif parse_text(message) == '/help':
                        buttons = [
                            [InlineKeyboardButton('Мои заказы', callback_data=f'user_orders_{chat_id}')],
                            [InlineKeyboardButton('Правила и помощь', callback_data='show_rules')],
                            [InlineKeyboardButton('Пользовательское соглашение (Договор для пользователей)',
                                                  callback_data='show_contract')]
                        ]

                        BOT.sendMessage(chat_id=chat_id, text='Справка', reply_markup=InlineKeyboardMarkup(buttons))

                    elif parse_text(message) == 'Оформить заказ':
                        BOT.send_message(chat_id, 'Вы выбрали оформить заказ')
                    elif parse_text(message) == 'Статистика':
                        if chat_id in [113737020, 697637170]:
                            BOT.send_message(chat_id=chat_id, text='СТАТИСТИКА', reply_markup=stat_menu_keyboard())
                        else:
                            text = 'Бот действует через кнопки. Начните с кнопки "Меню" в нижнем левом углу😊'
                            BOT.send_message(chat_id=chat_id, text=text)
                    elif parse_text(message) is None:
                        try:
                            if re.search(r'^Напишите пожалуйста что хотите изменить в заказе № [0-9]+ .+$', bot_msg):
                                order_id = int(re.search(r'[0-9]+', message).group(0))
                                order = db.session.query(Order).filter_by(id=order_id).first()

                                BOT.send_message(chat_id=order.uid, text=message)

                                order_detail = db.session.query(OrderDetail).filter_by(order_id=order_id).all()
                                for item in order_detail:
                                    user_cart = Cart(
                                        name=item.order_dish_name,
                                        price=item.order_dish_cost,
                                        quantity=item.order_dish_quantity,
                                        user_uid=order.uid,
                                        is_dish=1,
                                        is_water=0,
                                        dish_id=item.order_dish_id,
                                        restaurant_id=item.order_rest_id,
                                        service_uid=chat_id
                                    )
                                    db.session.add(user_cart)
                                    db.session.commit()

                                cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()

                                dishes = db.session.query(Dish).all()
                                total = 0

                                current_id = cart[0].id
                                cart_count = 0
                                for i in cart:
                                    if current_id == i.id:
                                        cart_count = i.quantity

                                buttons = []
                                cart_buttons = [InlineKeyboardButton('❌', callback_data=f'cart_id_{current_id}_clear')]
                                text = '<b>Корзина</b>\n'
                                for i, item in enumerate(cart, start=1):
                                    cart_buttons.append(
                                        InlineKeyboardButton(f'{i}', callback_data=f'cart_id_{item.id}'))
                                    total += item.price * item.quantity
                                cart_dish_id = None
                                for item in cart:
                                    if item.id == current_id:
                                        cart_dish_id = item.dish_id
                                for dish in dishes:

                                    if dish.id == cart_dish_id:
                                        text += f'<a href="{dish.img_link}">{order.order_rest_id}</a>'
                                        text += f'\n{dish.composition}'
                                        text += f'\n{cart[0].price}'
                                buttons.append(cart_buttons)
                                buttons.append([
                                    InlineKeyboardButton('-️',
                                                         callback_data=f'cart_id_{cart[0].id}_remove'),
                                    InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                                    InlineKeyboardButton('+️',
                                                         callback_data=f'cart_id_{cart[0].id}_add')
                                ])
                                buttons.append([
                                    InlineKeyboardButton('Очистить️',
                                                         callback_data=f'cart_purge'),
                                    InlineKeyboardButton('Меню️',
                                                         callback_data=f'restaurant_{cart[0].restaurant_id}')
                                ])
                                cb_data = f'cart_change_confirm_order_{order.id}'
                                buttons.append([InlineKeyboardButton(f'Оформить заказ на сумму {total}',
                                                                     callback_data=cb_data)])
                                BOT.send_message(
                                    text=text,
                                    chat_id=order.uid,
                                    reply_markup=InlineKeyboardMarkup(buttons),
                                    parse_mode=ParseMode.HTML
                                )
                                return 'Order change'
                            elif bot_msg == 'Укажите адрес доставки. Улица, дом, кв, подъезд:':
                                usr_msg = History.query.filter_by(chat_id=chat_id).order_by(History.id.desc()).first()
                                cur_usr = db.session.query(User).filter_by(uid=chat_id).first()
                                cur_usr.address = usr_msg.message_text
                                db.session.commit()
                                text = 'Укажите номер телефона'
                                BOT.send_message(chat_id=chat_id, text=text)
                                write_history(message_id, chat_id, text, is_bot=True)
                            elif bot_msg == 'Укажите номер телефона':
                                bot_msg = db.session.query(History).filter_by(message_id=message_id - 2,
                                                                              is_bot=False).first().message_text
                                cur_usr = db.session.query(User).filter_by(uid=chat_id).first()
                                cur_usr.phone = message
                                db.session.commit()
                                text = 'Вы указали:\n'
                                text += f'Адрес доставки: {cur_usr.address}\n'
                                text += f'Контактный номер: {cur_usr.phone}'

                                buttons = [
                                    [InlineKeyboardButton('Отправить', callback_data='order_confirm')],
                                    [InlineKeyboardButton('Изменить данные', callback_data='cart_confirm_change')]
                                ]
                                BOT.send_message(chat_id=chat_id,
                                                 text=text,
                                                 reply_markup=InlineKeyboardMarkup(buttons))
                            elif bot_msg == 'Напишите во сколько хотите забрать Ваш заказ ( в цифрах без букв)':
                                phone = User.query.filter_by(uid=chat_id).first().phone
                                text = ''
                                if phone:
                                    time = History.query.filter_by(chat_id=chat_id, is_bot=False).all()[-1].message_text
                                    text += "Вы указали:\n"
                                    text += "Самовывоз: " + time
                                    text += "\nКонтактный номер: " + phone
                                    cb_data_time = f'order_confirm_change_time_takeaway_{time}_{phone}'
                                    cb_data_phone = f'order_confirm_change_phone_takeaway_{time}_{phone}'
                                    buttons = [
                                        [InlineKeyboardButton('Отправить',
                                                              callback_data=f'order_confirm_takeaway_{time}')],
                                        [InlineKeyboardButton('Изменить время', callback_data=cb_data_time)],
                                        [InlineKeyboardButton('Изменить телефон', callback_data=cb_data_phone)]
                                    ]
                                    BOT.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(buttons))
                                    write_history(message_id, chat_id, text, is_bot=True)
                                else:
                                    text = "Укажите номер телефона для самовывоза:"
                                    BOT.send_message(chat_id, text)
                                write_history(message_id, chat_id, text, is_bot=True)
                            elif 'Ваш номер телефона для самовывоза:' in bot_msg:
                                phone = User.query.filter_by(uid=chat_id).first().phone
                                time = History.query.filter_by(chat_id=chat_id, is_bot=False).all()[-2].message_text
                                text = "Вы указали:\n"
                                text += "Самовывоз: " + time
                                text += "\nКонтактный номер: " + phone
                                buttons = [
                                    [InlineKeyboardButton('Отправить', callback_data=f'order_confirm_takeaway_{time}')],
                                    [InlineKeyboardButton('Изменить данные', callback_data='cart_confirm_takeaway')]
                                ]
                                BOT.send_message(chat_id=chat_id,
                                                 text=text,
                                                 reply_markup=InlineKeyboardMarkup(buttons))
                            elif 'Ваш номер телефона:' in bot_msg:
                                text = "Укажите номер телефона для самовывоза:"
                                BOT.send_message(chat_id, text)
                                write_history(message_id, chat_id, text, is_bot=True)
                            elif bot_msg == 'Укажите номер телефона для самовывоза:':
                                phone = History.query.filter_by(chat_id=chat_id, is_bot=False).all()[-1].message_text
                                time = History.query.filter_by(chat_id=chat_id, is_bot=False).all()[-2].message_text
                                if 'Вы указали:' in time:
                                    time = time.split('\n')[1][11:]
                                text = "Вы указали:\n"
                                text += "Самовывоз: " + time
                                text += "\nКонтактный номер: " + phone
                                cb_data_time = f'order_confirm_change_time_takeaway_{time}_{phone}'
                                cb_data_phone = f'order_confirm_change_phone_takeaway_{time}_{phone}'
                                buttons = [
                                    [InlineKeyboardButton('Отправить', callback_data=f'order_confirm_takeaway_{time}')],
                                    [InlineKeyboardButton('Изменить время', callback_data=cb_data_time)],
                                    [InlineKeyboardButton('Изменить телефон', callback_data=cb_data_phone)]
                                ]
                                BOT.send_message(chat_id=chat_id,
                                                 text=text,
                                                 reply_markup=InlineKeyboardMarkup(buttons))
                                User.query.filter_by(uid=chat_id).first().phone = phone
                                db.session.commit()
                            elif 'Укажите только адрес доставки для ресторана' in bot_msg:
                                rest_name = bot_msg[44:]
                                address = message
                                rest = Restaurant.query.filter_by(name=rest_name).first()
                                text = f'Ваш запрос отправлен, ждем ответа ресторана {rest_name}'
                                BOT.sendMessage(chat_id=chat_id, text=text)
                                text = f'Клиент хочет узнать время доставки, укажите примерное время.\n' \
                                       f'Адрес доставки: {address}'
                                cb_text = 'Можем доставить за'
                                cb_text_no = 'Не можем доставить на этот адрес'
                                cb_data = f'rest_{rest.id}_uid_{chat_id}_delivery_time'
                                buttons = [
                                    [InlineKeyboardButton(f'{cb_text} 30 минут', callback_data=f'{cb_data}_30')],
                                    [InlineKeyboardButton(f'{cb_text} 1 час', callback_data=f'{cb_data}_60')],
                                    [InlineKeyboardButton(f'{cb_text} 1 час 30 минут', callback_data=f'{cb_data}_90')],
                                    [InlineKeyboardButton(f'{cb_text} 2 часа', callback_data=f'{cb_data}_120')],
                                    [InlineKeyboardButton(f'{cb_text} 3 часа', callback_data=f'{cb_data}_180')],
                                    [InlineKeyboardButton(cb_text_no, callback_data=f'{cb_data}_no')]
                                ]
                                BOT.sendMessage(
                                    chat_id=rest.service_uid,
                                    text=text,
                                    reply_markup=InlineKeyboardMarkup(buttons)
                                )
                                client = User.query.filter_by(uid=chat_id).first()
                                client.address = address
                                db.session.commit()
                            else:
                                text = 'Бот действует через кнопки. Начните с кнопки "Меню" в нижнем левом углу😊'
                                BOT.send_message(chat_id=chat_id, text=text)
                        except TypeError:
                            pass
                    else:
                        text = 'Бот действует через кнопки. Начните с кнопки "Меню" в нижнем левом углу😊'
                        BOT.send_message(chat_id=chat_id, text=text)

                except telegram.error.Unauthorized:
                    pass
                except TypeError:
                    pass
                finally:
                    print('msg:', r['message']['text'])
        except KeyError:
            print('KeyError', r)
        except error.BadRequest:
            print('BAD REQUEST!', r)
            print(traceback.format_exc())
        except sqlite3.IntegrityError:
            print('BAD SQL QUERY', r)
        return 'Bot action returned'
    elif request.method == 'GET':
        r = request.get_json()
        print(r)
        return render_template('index.html')
    else:
        print('request method - ', request.method)


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


@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    dishes = db.session.query(Dish).all()
    s_dishes = SpecialDish.query.all()
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
    admin_add_form = AdminAddForm()
    delivery_terms = RestaurantDeliveryTerms.query.all()
    rest_delivery_terms_form = RestaurantDeliveryTermsForm()
    rest_delivery_terms_edit_form = RestaurantDeliveryTermsEditForm()
    subcategory_add_form = SubcategoryForm()
    subcategory_del_form = SubcategoryDeleteForm()
    special_dish_form = SpecialDishForm()
    special_dish_delete_form = SpecialDishDeleteForm()
    dish_edit_form = DishEditForm()
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
            except:
                pass
            try:
                dish = Dish.query.filter_by(id=id_dish, id_rest=id_rest).first()
                dish.name = name
                dish.id_rest = id_rest
                dish.cost = cost
                dish.composition = composition
                dish.category = category
                if file_flag:
                    dish.img_link = img_link
                db.session.commit()
                flash("Блюдо изменено", "success")
                return redirect(url_for('admin'))
            except Exception as e:
                print(e)
                flash("Попытка изменить блюдо неудачна", "error")
                return redirect(url_for('admin'))

    if promo_dishes_form.promo_dish_submit.data:
        if promo_dishes_form.validate_on_submit() or promo_dishes_form.is_submitted():
            rest_id = promo_dishes_form.rest_id.data
            if not rest_id:
                rest_id = request.form['promo_rest_selector']
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
        db.session.query(Dish).filter_by(id=dish_id).delete()
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
            email = restaurant_form.email.data
            if not email:
                email = None
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

            if current_user.ownership == 'all':
                restaurant_id = request.form['category_del_rest_selector']
                name = request.form['category_delete_select_field']
            else:
                name = request.form['category_rest_delete_select_field']
                print(name)
                restaurant_id = category_delete_form.restaurant_id.data
                print(restaurant_id)
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
            enabled = rest.enabled
            if request.form['rest_edit_submit'] == 'Включить':
                enabled = True
            elif request.form['rest_edit_submit'] == 'Выключить':
                enabled = False
            if name:
                rest.name = name
                if owner:
                    owner.ownership = name
            if address:
                rest.address = address
            if contact:
                rest.contact = contact
            if passwd:
                rest.passwd = passwd
            if email:
                rest.email = email
            if min_total:
                rest.min_total = min_total
            rest.enabled = enabled
            db.session.commit()
            flash("Изменения успешно внесены", "success")
            return redirect(url_for('admin'))

    if admin_add_form.admin_add_button.data:
        if admin_add_form.validate_on_submit() or admin_add_form.is_submitted():
            username = admin_add_form.username.data
            passwd = admin_add_form.passwd.data
            mail = admin_add_form.email.data
            ownership = request.form['admin_add_rest_selector']
            usr = Admin(
                username=username,
                email=mail,
                password=passwd,
                ownership=ownership
            )
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
                if terms_data:
                    terms.terms = terms_data
                if rest_inn:
                    terms.rest_inn = rest_inn
                if rest_ogrn:
                    terms.rest_ogrn = rest_ogrn
                if rest_fullname:
                    terms.rest_fullname = rest_fullname
                if rest_address:
                    terms.rest_address = rest_address
                db.session.commit()
            return redirect(url_for('admin'))

    return render_template(
        'admin.html',
        dishes=dishes,
        s_dishes=s_dishes,
        promo_dishes=promo_dishes,
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
        admin_add_form=admin_add_form,
        rest_delivery_terms_form=rest_delivery_terms_form,
        rest_delivery_terms_edit_form=rest_delivery_terms_edit_form,
        delivery_terms=delivery_terms,
        stat1=stat1(),
        stat2=stat2(),
        stat3=stat3(),
        stat4=stat4(),
        stat5=stat5(),
        stat6=stat6(),
        stat7=stat7(),
        stat8=stat8()
    )


@app.route('/contract/', methods=['POST', 'GET'])
def contract():
    return render_template('contract.html', contract_text=contract_text)


@login_manager.user_loader
def load_user(user_id):
    return db.session.query(Admin).get(user_id)


def sendMsg(uid, text, buttons):
    BOT.send_message(chat_id=uid, text=text, reply_markup=InlineKeyboardMarkup(buttons))


def write_json(data, filename='answer.json'):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_text(text):
    pattern = r'(^Рестораны$)|(^Корзина$)|(^Оформить заказ$)|(^\/\w+)|(\w+_[0-9]+$)|(^Статистика$)'
    try:
        value = re.search(pattern, text).group()
    except AttributeError:
        return None
    return value


def send_message(chat_id, text='bla-bla-bla'):
    url = URL + 'sendMessage'
    answer = {'chat_id': chat_id, 'text': text}
    r = requests.get(url, json=answer)
    return r.json()


def get_value(val, data):
    try:
        for key, value in data.items():
            if val == key:
                return True
    except AttributeError:
        return False


def rest_menu_edit_msg(chat_id, message_id):
    markup = rest_menu_keyboard()
    if not markup.inline_keyboard:
        BOT.editMessageText(
            chat_id=chat_id,
            text='В данное время нет работающих ресторанов',
            message_id=message_id,
        )
    else:
        BOT.editMessageText(
            chat_id=chat_id,
            text='Пожалуйста, выберите ресторан:',
            message_id=message_id,
            reply_markup=markup
        )


def rest_menu_send_msg(chat_id):
    markup = rest_menu_keyboard()
    if not markup.inline_keyboard:
        BOT.send_message(
            chat_id=chat_id,
            text='В данное время нет работающих ресторанов'
        )
    else:
        BOT.sendMessage(
            chat_id=chat_id,
            text='Пожалуйста, выберите ресторан:',
            reply_markup=markup
        )


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
    keyboard = []
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
                keyboard.append(
                    [InlineKeyboardButton(f'{restaurant.name}', callback_data=f'restaurant_{restaurant.id}')])
        else:
            keyboard.append([InlineKeyboardButton(f'{restaurant.name}', callback_data=f'restaurant_{restaurant.id}')])

    return InlineKeyboardMarkup(keyboard)


def stat_menu_keyboard():
    """Возвращает меню статистики"""
    keyboard = []
    for i in range(1, 8):
        keyboard.append([InlineKeyboardButton(f'{i}', callback_data=f'stat_{i}')])
    return InlineKeyboardMarkup(keyboard)


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
            if order_date == month and data.order_state == 'Подтверждена' and Restaurant.query.filter_by(
                    id=data.order_rest_id).first():
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
        if data.order_state == 'Подтверждена' and rest.filter_by(id=data.order_rest_id).first():
            rest_name = rest.filter_by(id=data.order_rest_id).first().name
            day = str(datetime.fromtimestamp(data.order_datetime).strftime("%d"))
            rests_data.append([rest_name, day, data.order_total, '{:02d}'.format(current_month)])
    for i in range(len(rests_data)):
        if i == 0 or (i != 0 and rests_data[i][0] != rests_data[i - 1][0]):
            text += f'{rests_data[i][0]}\n'
            text += f'{rests_data[i][1]}.{rests_data[i][3]} - {rests_data[i][2]} р.\n'
        elif i != 0 and rests_data[i][0] == rests_data[i - 1][0]:
            text += f'{rests_data[i][1]}.{rests_data[i][3]} - {rests_data[i][2]} р.\n'
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
        if data.order_state == 'Подтверждена':
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
    orders = Order.query.filter_by(order_state="Отменен").all()
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
    return text


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
