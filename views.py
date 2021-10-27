from datetime import datetime, timedelta
from os import mkdir
from os.path import isdir

import pytz
import telegram.error
from flask import render_template, flash, redirect, url_for
from telegram import Bot, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, KeyboardButton
from telegram import error

from forms import LoginForm, DishForm, CategoryForm, DishDeleteForm, RestaurantForm, CategoryDeleteForm, \
    RestaurantDeleteForm, RestaurantEditForm, AdminAddForm, RestaurantDeliveryTermsForm, RestaurantDeliveryTermsEditForm
from settings import BOT_TOKEN, BASE_URL

import re
import requests
import json

from flask import request
from flask_login import login_required, login_user, current_user, logout_user

from app import app, db, sched, login_manager

from models import Restaurant, Category, Dish, Cart, User, Order, History, OrderDetail, Admin, RestaurantDeliveryTerms

from werkzeug.utils import secure_filename

from transliterate import translit

BOT = Bot(BOT_TOKEN)
URL = f'https://api.telegram.org/bot{BOT_TOKEN}/'


@app.route('/', methods=['POST', 'GET'])
def index():
    if request.method == 'POST':
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
                pass
            user = db.session.query(User).filter_by(uid=chat_id).first()
            if not user:
                user = User(uid=chat_id, first_name=first_name, last_name=last_name, username=username)
                db.session.add(user)
                db.session.commit()
            write_history(message_id, chat_id, msg_text, is_bot=False)

            # Callback handlers
            if get_value("callback_query", r):
                data = r['callback_query']['data']
                buttons = []
                message_id = r['callback_query']['message']['message_id']
                if re.search(r'(restaurant_[0-9]+$)|'
                             r'(restaurant_[0-9]+_menu$)', data):
                    rest_id = int(data.split('_')[1])
                    categories = db.session.query(Category).filter_by(restaurant_id=rest_id).all()
                    for category in categories:
                        buttons.append(
                            [InlineKeyboardButton(category.name,
                                                  callback_data=f'restaurant_{rest_id}_cat{category.id}')])

                    cb_data = f'restaurant_{rest_id}_delivery_terms'
                    buttons.append([InlineKeyboardButton('Условия доставки', callback_data=cb_data)])
                    buttons.append([InlineKeyboardButton('Назад', callback_data='back_to_rest_kb')])
                    if 'menu' in data:
                        BOT.sendMessage(
                            text='Пожалуйста выберите подходящую категорию',
                            chat_id=chat_id,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    else:
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

                elif re.search(r'(restaurant_[0-9]+_cat[0-9]+$)', data) \
                        or re.search(r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_add_[0-9]+_[0-9]+$)', data) \
                        or re.search(r'(restaurant_[0-9]+_cat[0-9]+_dish_[0-9]+_rem_[0-9]+_[0-9]+$)', data):
                    rest_id, cat_id = int(data.split('_')[1]), int(data.split('_')[2][3:])
                    category = db.session.query(Category.name).filter_by(id=cat_id).first()[0]
                    rest_name = db.session.query(Restaurant.name).filter_by(id=rest_id).first()[0]
                    sql_result = db.session.query(Dish).filter_by(id_rest=rest_id, category=category).all()

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
                        buttons = [[
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
                            message_id=cur_msg_id,
                            reply_markup=InlineKeyboardMarkup(buttons),
                            parse_mode=ParseMode.HTML
                        )
                    else:
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
                            buttons = [[
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
                        if re.search('^cart$', data):
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
                    text = 'Укажите только адрес доставки без номера телефона. Можете написать так же ваши пожелания.'
                    BOT.send_message(text=text, chat_id=chat_id)
                    write_history(message_id, chat_id, text, is_bot=True)

                elif data == 'to_rest':
                    BOT.editMessageText(
                        chat_id=chat_id,
                        message_id=message_id,
                        text='Пожалуйста, выберите ресторан:',
                        reply_markup=rest_menu_keyboard())
                elif re.search(r'(^order_confirm$)', data):
                    cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                    total = sum(list(map(lambda good: good.price * good.quantity, cart)))
                    current_tz = pytz.timezone('Asia/Yakutsk')
                    try:
                        order = Order(
                            uid=chat_id,
                            first_name=first_name,
                            last_name=last_name,
                            order_total=total,
                            order_rest_id=cart[0].restaurant_id,
                            order_datetime=datetime.now(current_tz).strftime('%s'),
                            order_confirm=False
                        )
                        db.session.add(order)
                        db.session.flush()
                        rest_name = db.session.query(Restaurant.name).filter_by(id=order.order_rest_id).first()[0]
                        text = f'Заказ оформлен, ждем подтверждения ресторана {rest_name}'
                        BOT.send_message(chat_id=order.uid, text=text)

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
                        text += f'Адрес доставки: {db.session.query(User.address).filter_by(uid=order.uid).first()[0]}'
                        db.session.query(Cart).filter_by(user_uid=chat_id).delete()
                        service_uid = db.session.query(Restaurant.service_uid).filter_by(
                            id=order.order_rest_id).first()[0]
                        db.session.commit()
                        cb_data = f'order_change_{order.id}'
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
                        BOT.send_message(chat_id=service_uid, text=text, reply_markup=InlineKeyboardMarkup(buttons))
                        write_history(message_id, chat_id, text, is_bot=True)
                    except IndexError:
                        BOT.send_message(chat_id=113737020, text='Произошла ошибка IndexError в order_confirm')

                elif re.search(r'^order_accept_[0-9]+_(30|60|120|180)$', data):
                    order_id = int(data.split('_')[2])
                    time = int(data.split('_')[3])
                    order = db.session.query(Order).filter_by(id=order_id).first()
                    text = f'Ресторан принял ваш заказ № {order.id} и доставит '
                    time_text = ''
                    current_tz = pytz.timezone('Asia/Yakutsk')
                    sched_time = current_tz.localize(datetime.now() + timedelta(minutes=time))
                    if time == 30:
                        time_text += 'в течении 30 минут'
                    elif time == 60:
                        time_text += 'в течение 1 часа'
                    elif time == 120:
                        time_text += 'в течении 2 часов'
                    elif time == 180:
                        time_text += 'в течении 3 часов'
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
                    buttons = [
                        [InlineKeyboardButton('Принять и доставить за 30 минут',
                                              callback_data=f'order_accept_{order.id}_30')],
                        [InlineKeyboardButton('Принять и доставить за 1 час',
                                              callback_data=f'order_accept_{order.id}_60')],
                        [InlineKeyboardButton('Принять и доставить за 2 часа',
                                              callback_data=f'order_accept_{order.id}_120')],
                        [InlineKeyboardButton('Принять и доставить за 3 часа',
                                              callback_data=f'order_accept_{order.id}_180')],
                        [InlineKeyboardButton('Заказ принят', callback_data='None')],
                        [InlineKeyboardButton(f'Изменить заказ № {order.id}', callback_data=cb_data)]
                    ]
                    BOT.editMessageText(
                        chat_id=service_uid,
                        message_id=message_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )

                    text = f'Мы оповестили клиента, что Вы приняли заказ № {order.id}, доставка {time_text} '
                    text += f'на адрес: {client.address}\n'
                    text += f'Контактный номер: {client.phone}'
                    BOT.send_message(chat_id=service_uid, text=text)
                    order.order_confirm = True
                    order.order_state = 'Подтверждена'
                    db.session.commit()

                    # text = f'Заданное время по заказу № {order_id} закончилось. Подвтердить доставку?'
                    # buttons = [
                    #     InlineKeyboardButton('Подтвердить доставку', callback_data=f'order_{order.id}_delivered')
                    # ]
                    # sched.add_job(sendMsg, 'date', run_date=sched_time, args=[service_uid, text, buttons])
                    # text = f'Заказ № {order_id} доставлен?'
                    # sched.add_job(sendMsg, 'date', run_date=sched_time, args=[client.uid, text, buttons])
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
                    details = db.session.query(OrderDetail).filter_by(order_id=order_id).all()
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
                            text = 'Ресторан отменил заказ. Пожалуйста выберите ресторан:'
                            BOT.sendMessage(chat_id=order.uid, text=text, reply_markup=rest_menu_keyboard())
                            db.session.query(Order).filter_by(id=order_id).delete()
                            db.session.query(OrderDetail).filter_by(order_id=order_id).delete()
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
                        InlineKeyboardButton('-️', callback_data=cb_data+'remove'),
                        InlineKeyboardButton(f'{cart[0].quantity} шт', callback_data='None'),
                        InlineKeyboardButton('+️', callback_data=cb_data+'add')
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
                        bot_msg = db.session.query(History).filter_by(chat_id=chat_id, message_id=message_id - 2,
                                                                      is_bot=True).first().message_text
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
                        keyboard = [
                            [KeyboardButton('Рестораны'), KeyboardButton('Корзина')],
                            [KeyboardButton(' '), KeyboardButton('Оформить заказ')]
                        ]
                        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        BOT.send_message(chat_id, text, reply_markup=markup)
                    elif parse_text(message) == '/my_orders':
                        order = Order.query.filter_by(uid=chat_id, order_state='Подтверждена')
                        order = order.order_by(Order.id.desc()).first()
                        if order:
                            date = order.order_datetime
                            current_tz = pytz.timezone('Asia/Yakutsk')
                            date = current_tz.localize(datetime.fromtimestamp(date)).strftime('%d.%m.%Y %H:%M:%S')
                            text = f'Ваш заказ № {order.id} от {date}\n'
                            details = db.session.query(OrderDetail).filter_by(order_id=order.id).all()
                            for item in details:
                                text += f'- {item.order_dish_name}\n'
                            text += f'Общая стоимость заказа - {order.order_total}\n'
                            restaurant = db.session.query(Restaurant).filter_by(id=order.order_rest_id).first()
                            text += f'Ресторан - {restaurant.name}, {restaurant.address}, {restaurant.contact}'
                        else:
                            text = 'У Вас пока нет оформленных заказов'
                        BOT.send_message(chat_id=chat_id, text=text)
                    elif parse_text(message) == 'Рестораны' or parse_text(message) == '/restaurants':
                        text = 'Пожалуйста, выберите ресторан:'
                        BOT.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=rest_menu_keyboard())
                        write_history(message_id, chat_id, text, is_bot=True)
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
                    elif parse_text(message) == '/show_contract':
                        BOT.send_message(chat_id, 'Ссылка на договор')

                    elif parse_text(message) == 'Оформить заказ':
                        BOT.send_message(chat_id, 'Вы выбрали оформить заказ')
                    elif parse_text(message) == 'Статистика':
                        BOT.send_message(chat_id=chat_id, text='СТАТИСТИКА', reply_markup=stat_menu_keyboard())
                    elif parse_text(message) == 'Тест':
                        mention = "[" + username + "](tg://user?id=" + str(chat_id) + ")"
                        text = f'hi {mention}'
                        BOT.send_message(chat_id=chat_id, text=f'hi {mention}', parse_mode="Markdown")
                        if re.search(r'\[.+\(tg:user\?id=[0-9]+\)', bot_msg):
                            print('We found mention tag!')
                        write_history(message_id, chat_id, text, is_bot=True)
                    elif parse_text(message) == 'Test':
                        text = "Напишите пожалуйста что хотите изменить в заказе № 3 и мы перенаправим ваше " \
                               "сообщение клиенту "
                        BOT.sendMessage(chat_id=chat_id, text=text, reply_to_message_id=message_id)
                        write_history(message_id, chat_id, text, is_bot=True)
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
                            elif bot_msg == 'Укажите только адрес доставки без номера телефона. Можете написать так ' \
                                            'же ваши пожелания.':
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
                                    [InlineKeyboardButton('Изменить данные', callback_data='cart_confirm')]
                                ]
                                BOT.send_message(chat_id=chat_id,
                                                 text=text,
                                                 reply_markup=InlineKeyboardMarkup(buttons))
                        except TypeError:
                            print('TypeError')
                            print("We can't handle this message", message)
                except telegram.error.Unauthorized:
                    pass
                finally:
                    print('Final processing')
        except KeyError:
            print('KeyError', r)
        except error.BadRequest:
            print('BAD REQUEST!')
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
    restaurants = db.session.query(Restaurant).all()
    categories = db.session.query(Category).all()
    dish_delete_form = DishDeleteForm()
    restaurant_form = RestaurantForm()
    restaurant_delete_form = RestaurantDeleteForm()
    restaurant_edit_form = RestaurantEditForm()
    admin_add_form = AdminAddForm()
    delivery_terms = RestaurantDeliveryTerms.query.all()
    rest_delivery_terms_form = RestaurantDeliveryTermsForm()
    rest_delivery_terms_edit_form = RestaurantDeliveryTermsEditForm()
    if current_user.username != 'admin':
        dish_form = DishForm(hide_rest=True)
        category_form = CategoryForm(hide_rest_id=True)
        category_delete_form = CategoryDeleteForm(hide_rest_id=True)
    else:
        dish_form = DishForm(hide_rest=False)
        category_form = CategoryForm(hide_rest_id=False)
        category_delete_form = CategoryDeleteForm(hide_rest_id=False)
    if dish_form.validate_on_submit() and dish_form.dish_add_submit.data:
        name = dish_form.name.data
        cost = dish_form.cost.data
        composition = dish_form.composition.data
        id_rest = dish_form.id_rest.data
        if re.search('[а-яА-Я]', dish_form.img_file.data.filename):
            img_file = secure_filename(translit(dish_form.img_file.data.filename, reversed=True))
        else:
            img_file = secure_filename(dish_form.img_file.data.filename)
        static_path = 'static/' + str(id_rest) + '/'
        if not isdir(static_path):
            mkdir(static_path)
        dish_form.img_file.data.save(static_path + img_file)
        img_link = BASE_URL + static_path + img_file
        category = dish_form.category.data

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

    elif category_form.validate_on_submit() and category_form.category_add_submit.data:
        name = category_form.name.data
        restaurant_id = category_form.restaurant_id.data

        category = Category(name=name, restaurant_id=restaurant_id)
        db.session.add(category)
        db.session.commit()
        flash("Категория добавлена", "success")
        return redirect(url_for('admin'))

    elif dish_delete_form.validate_on_submit() and dish_delete_form.dish_delete_submit.data:
        dish_id = dish_delete_form.delete_id.data
        db.session.query(Dish).filter_by(id=dish_id).delete()
        db.session.commit()
        flash("Блюдо успешно удалено", "success")
        return redirect(url_for('admin'))

    elif restaurant_form.validate_on_submit() and restaurant_form.rest_add_submit.data:
        name = restaurant_form.name.data
        address = restaurant_form.address.data
        contact = restaurant_form.contact.data
        passwd = restaurant_form.contact.data
        service_uid = restaurant_form.service_uid.data
        restaurant = Restaurant(name=name, address=address, contact=contact, passwd=passwd, service_uid=service_uid)
        db.session.add(restaurant)
        db.session.commit()
        flash("Ресторан добавлен", "success")
        return redirect(url_for('admin'))

    elif category_delete_form.validate_on_submit() and category_delete_form.category_delete_submit.data:
        name = category_delete_form.name.data
        restaurant_id = category_delete_form.restaurant_id.data
        db.session.query(Category).filter_by(name=name, restaurant_id=restaurant_id).delete()
        db.session.commit()
        flash("Категория успешно удалена", "success")
        return redirect(url_for('admin'))

    elif restaurant_delete_form.validate_on_submit() and restaurant_delete_form.rest_delete_submit.data:
        name = restaurant_delete_form.name.data
        db.session.query(Restaurant).filter_by(name=name).delete()
        db.session.commit()
        flash("Ресторан успешно удален", "success")
        return redirect(url_for('admin'))

    elif restaurant_edit_form.validate_on_submit() and restaurant_edit_form.rest_edit_submit.data:
        rest_id = restaurant_edit_form.id.data
        name = restaurant_edit_form.name.data
        address = restaurant_edit_form.address.data
        contact = restaurant_edit_form.contact.data
        passwd = restaurant_edit_form.passwd.data
        rest = Restaurant.query.filter_by(id=rest_id).first()
        if name:
            rest.name = name
        if address:
            rest.address = address
        if contact:
            rest.contact = contact
        if passwd:
            rest.passwd = passwd
        db.session.commit()
        return redirect(url_for('admin'))

    elif admin_add_form.validate_on_submit() and admin_add_form.admin_add_button.data:
        username = admin_add_form.username.data
        passwd = admin_add_form.passwd.data
        mail = admin_add_form.email.data
        ownership = admin_add_form.ownership.data
        usr = Admin(
            username=username,
            email=mail,
            password=passwd,
            ownership=ownership
        )
        db.session.add(usr)
        db.session.commit()
        return redirect(url_for('admin'))

    elif rest_delivery_terms_form.validate_on_submit() and rest_delivery_terms_form.delivery_terms_submit.data:
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
    
    elif rest_delivery_terms_edit_form.validate_on_submit() and rest_delivery_terms_edit_form.terms_edit_submit.data:
        rest_id = rest_delivery_terms_edit_form.rest_id.data
        terms_data = rest_delivery_terms_edit_form.terms.data
        rest_inn = rest_delivery_terms_edit_form.rest_inn.data
        rest_ogrn = rest_delivery_terms_edit_form.rest_ogrn.data
        rest_fullname = rest_delivery_terms_edit_form.rest_fullname.data
        rest_address = rest_delivery_terms_edit_form.rest_address.data
        terms = RestaurantDeliveryTerms.query.filter_by(id=rest_id).first()
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
        restaurants=restaurants,
        categories=categories,
        dish_form=dish_form,
        category_form=category_form,
        dish_delete_form=dish_delete_form,
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
        stat6=stat6(),
        stat7=stat7()
    )


@app.route('/contract/', methods=['POST', 'GET'])
def contract():
    return render_template('contract.html')


@login_manager.user_loader
def load_user(user_id):
    return db.session.query(Admin).get(user_id)


def sendMsg(uid, text, buttons):
    BOT.send_message(chat_id=uid, text=text, reply_markup=InlineKeyboardMarkup(buttons))


def write_json(data, filename='answer.json'):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_text(text):
    pattern = r'(^Рестораны$)|(^Корзина$)|(^Оформить заказ$)|(^\/\w+)|(\w+_[0-9]+$)|(^Статистика$)|(^Тест$)|(^Test$)'
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
    for key, value in data.items():
        if val == key:
            return True
    return False


def rest_menu_keyboard():
    """Возвращает меню с наименованиями ресторанов"""
    restaurants = db.session.query(Restaurant).all()
    keyboard = []
    for restaurant in restaurants:
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
        date=datetime.now().strftime('%s'),
        type='message',
        message_text=text,
        is_bot=is_bot
    )
    db.session.add(msg)
    db.session.commit()


def stat1():
    months = {
        1: 'январь',
        2: 'февраль',
        3: 'март',
        4: 'апрель',
        5: 'май',
        6: 'июнь',
        7: 'июль',
        8: 'август',
        9: 'сентябрь',
        10: 'октябрь',
        11: 'ноябрь',
        12: 'декабрь'
    }
    current_month = datetime.now().month
    current_month_total = 0
    current_month_rests_total = {}
    stat_data = db.session.query(Order).all()
    for data in stat_data:
        order_date = int(datetime.fromtimestamp(data.order_datetime).strftime("%m"))
        if order_date == current_month:
            current_month_total += data.order_total
            rest = db.session.query(Restaurant.name).filter_by(id=data.order_rest_id).first()[0]
            try:
                current_month_rests_total.update(
                    {rest: current_month_rests_total[rest] + data.order_total}
                )
            except KeyError:
                current_month_rests_total.update({rest: data.order_total})
    text = f'Общая сумма за {months[current_month]}: {current_month_total}р.\n'
    for rest in current_month_rests_total:
        text += f'Общая сумма заказов в ресторане {rest} за {months[current_month]} - ' \
                f'{current_month_rests_total[rest]}р.\n'
    return text


def stat2():
    current_month = datetime.now().month
    stat_data = db.session.query(Order).order_by(Order.order_rest_id).all()
    rests_data, text = [], ''
    for data in stat_data:
        month = int(datetime.fromtimestamp(data.order_datetime).strftime("%m"))
        if month == current_month:
            rest = db.session.query(Restaurant.name).filter_by(id=data.order_rest_id).first()[0]
            day = str(datetime.fromtimestamp(data.order_datetime).strftime("%d"))
            rests_data.append([rest, day, data.order_total, month])
    for i in range(len(rests_data)):
        if i == 0 or (i != 0 and rests_data[i][0] != rests_data[i-1][0]):
            text += f'{rests_data[i][0]}\n'
            text += f'{rests_data[i][1]}.{rests_data[i][3]} - {rests_data[i][2]} р.\n'
        elif i != 0 and rests_data[i][0] == rests_data[i-1][0]:
            text += f'{rests_data[i][1]}.{rests_data[i][3]} - {rests_data[i][2]} р.\n'
    return text


def stat6():
    return db.session.query(Order).filter_by(order_state="Отменен").count()


def stat7():
    return db.session.query(User.id).count()
