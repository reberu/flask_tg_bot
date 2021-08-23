from datetime import datetime, timedelta

import telegram.error
from flask import render_template, flash, redirect, url_for
from telegram import Bot, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram import error

from forms import LoginForm, DishForm, CategoryForm
from settings import BOT_TOKEN

import re
import requests
import json

from flask import request
from flask_login import login_required, login_user, current_user, logout_user

from app import app, db, sched, login_manager

from models import Restaurant, Category, Dish, Cart, User, Order, History, OrderDetail, Admin

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
                chat_id = r['callback_query']['message']['chat']['id']
                first_name = r['callback_query']['message']['chat']['first_name']
                last_name = r['callback_query']['message']['chat']['last_name']
                username = r['callback_query']['message']['chat']['username']
                message_id = r['callback_query']['message']['message_id']
                date = r['callback_query']['message']['date']
                msg_text = r['callback_query']['message']['text']
                msg_type = 'callback_query'
            elif get_value('message', r):
                chat_id = r['message']['chat']['id']
                first_name = r['message']['chat']['first_name']
                last_name = r['message']['chat']['last_name']
                username = r['message']['chat']['username']
                message_id = r['message']['message_id']
                date = r['message']['date']
                msg_text = r['message']['text']
                msg_type = 'message'
            else:
                pass
            user = db.session.query(User).filter_by(uid=chat_id).first()
            if not user:
                user = User(uid=chat_id, first_name=first_name, last_name=last_name, username=username)
                db.session.add(user)
                db.session.commit()
            msg = History(
                message_id=message_id,
                chat_id=chat_id,
                date=date,
                type=msg_type,
                message_text=msg_text,
                is_bot=False)
            db.session.add(msg)
            db.session.commit()

            # Callback handlers
            if get_value("callback_query", r):
                data = r['callback_query']['data']
                print('callback - ', data)
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
                    buttons.append(
                        [InlineKeyboardButton('Узнать время доставки',
                                              callback_data=f'restaurant_{rest_id}_deliverytime')])
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
                    print('restaurant callback', data)
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
                        print(dish_name, cur_chat_id, data.split('_')[1])
                        try:
                            dish_count = db.session.query(Cart.quantity).filter_by(name=dish_name, user_uid=cur_chat_id,
                                                                                   restaurant_id=data.split('_')[
                                                                                       1]).first()[0]
                        except TypeError:
                            dish_count = 0
                        print(cur_id, cur_chat_id, cur_msg_id, dish_count)
                        if data.split('_')[5] == 'add':
                            if dish_count and dish_count > 0:
                                cart_item_updater = db.session.query(Cart).filter_by(
                                    name=sql_result[cur_id].name,
                                    user_uid=cur_chat_id,
                                    restaurant_id=data.split('_')[1]).first()
                                cart_item_updater.quantity += 1
                                db.session.commit()
                            else:
                                print('add new item')
                                cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                                rest_id = data.split('_')[1]
                                text = ''
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
                                    restaurant_id=data.split('_')[1]
                                )
                                db.session.add(cart_item)
                                db.session.commit()
                                if text != '':
                                    BOT.sendMessage(chat_id=chat_id, text=text)
                        elif data.split('_')[5] == 'rem':
                            if dish_count and dish_count > 1:
                                print('UPDATE')
                                cart_item_updater = db.session.query(Cart).filter_by(
                                    name=sql_result[cur_id].name,
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
                        text += f'<a href="{sql_result[cur_id].img_link}">.</a>'
                        text += f'\n<b>{dish_name}</b>'
                        text += f'\nОписание - {sql_result[cur_id].description}'
                        text += f'\nСостав: {sql_result[cur_id].composition}'
                        text += f'\nСтоимость - {sql_result[cur_id].cost} р.'

                        dish_id = sql_result[cur_id].id
                        try:
                            cart_count = db.session.query(Cart.quantity).filter_by(user_uid=cur_chat_id,
                                                                                   dish_id=dish_id).first()[0]
                        except TypeError:
                            cart_count = 0
                        except IndexError:
                            cart_count = 0
                        print('cart_count', dish_name, cart_count)
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
                        print(dish_id, dish_name, dish_count)
                    else:
                        for current_id, dish in enumerate(sql_result, start=1):
                            text = f'{rest_name}\n'
                            text += f'<a href="{dish.img_link}">.</a>'
                            text += f'\n<b>{dish.name}</b>'
                            text += f'\nОписание - {dish.description}'
                            text += f'\nСостав: {dish.composition}'
                            text += f'\nСтоимость - {dish.cost} р.'

                            try:
                                cart_count = db.session.query(Cart.quantity).filter_by(user_uid=chat_id,
                                                                                       dish_id=dish.id).first()[0]
                            except TypeError:
                                cart_count = 0
                            except IndexError:
                                cart_count = 0
                            print(dish)
                            cb_data_first = f'restaurant_{rest_id}_cat{cat_id}_dish_{dish.id}'
                            cb_data_last = f'{chat_id}_{message_id + current_id}'
                            buttons = [[
                                InlineKeyboardButton('-',
                                                     callback_data=f'{cb_data_first}_rem_{cb_data_last}'),
                                InlineKeyboardButton(f'{cart_count} шт', callback_data='None'),
                                InlineKeyboardButton('+️',
                                                     callback_data=f'{cb_data_first}_add_{cb_data_last}')
                            ]]
                            print(message_id + current_id)
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
                            msg = History(
                                message_id=message_id,
                                chat_id=chat_id,
                                date=datetime.now().strftime('%s'),
                                type='message',
                                message_text=text,
                                is_bot=True
                            )
                            db.session.add(msg)
                            db.session.commit()
                            print(dish.id, dish.name, cart_count)
                elif re.search(r'(^cart$)|'
                               r'(^cart_id_[0-9]+$)|'
                               r'(^cart_id_[0-9]+_clear$)|'
                               r'(^cart_purge$)|'
                               r'(^cart_id_[0-9]+_add$)|'
                               r'(^cart_id_[0-9]+_remove$)', data):
                    cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()

                    if len(cart) == 0:
                        text = 'Ваша корзина пуста'
                        buttons = [[InlineKeyboardButton('Назад', callback_data='to_rest')]]
                        BOT.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                        msg = History(
                            message_id=message_id,
                            chat_id=chat_id,
                            date=datetime.now().strftime('%s'),
                            type='message',
                            message_text=text,
                            is_bot=True
                        )
                        db.session.add(msg)
                        db.session.commit()
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
                                    print('cart_count', cart_count)
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
                                buttons = [[InlineKeyboardButton('Назад', callback_data='to_rest')]]
                                BOT.sendMessage(
                                    chat_id=chat_id,
                                    # message_id=message_id,
                                    text=text,
                                    reply_markup=InlineKeyboardMarkup(buttons)
                                )
                            return data
                        elif re.search(r'(^cart_purge$)', data):
                            db.session.query(Cart).filter_by(user_uid=chat_id).delete()
                            db.session.commit()
                            text = 'Ваша корзина пуста'
                            buttons = [[InlineKeyboardButton('Назад', callback_data='to_rest')]]
                            BOT.edit_message_text(
                                chat_id=chat_id,
                                message_id=message_id,
                                text=text,
                                reply_markup=InlineKeyboardMarkup(buttons)
                            )
                            return text
                        elif re.search(r'(^cart_id_[0-9]+_add$)', data):
                            current_id = int(data.split('_')[2])
                            for item in cart:
                                if current_id == item.id:
                                    item.quantity += 1
                            db.session.commit()
                        elif re.search(r'(^cart_id_[0-9]+_remove$)', data):
                            current_id = int(data.split('_')[2])
                            if cart[current_id-1].quantity > 1:
                                cart[current_id-1].quantity -= 1
                            else:
                                print('Cart item remove handler')
                                print(cart)
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
                                for i, item in enumerate(cart, start=1):
                                    cart_buttons.append(
                                        InlineKeyboardButton(f'{i}', callback_data=f'cart_id_{item.id}'))
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
                        print('show_cart handler')
                        print(cart)
                        cart_count = None
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
                        msg = History(
                            message_id=message_id,
                            chat_id=chat_id,
                            date=datetime.now().strftime('%s'),
                            type='message',
                            message_text=text,
                            is_bot=True
                        )
                        db.session.add(msg)
                        db.session.commit()
                elif re.search(r'(^cart_confirm$)', data):
                    text = 'Укажите адрес доставки'
                    BOT.send_message(text=text, chat_id=chat_id)
                    msg = History(
                        message_id=message_id,
                        chat_id=chat_id,
                        date=datetime.now().strftime('%s'),
                        type='message',
                        message_text=text,
                        is_bot=True
                    )
                    db.session.add(msg)
                    db.session.commit()
                elif data == 'to_rest':
                    BOT.editMessageText(
                        chat_id=chat_id,
                        message_id=message_id,
                        text='Пожалуйста, выберите ресторан:',
                        reply_markup=rest_menu_keyboard())
                elif re.search(r'(^order_confirm$)', data):
                    print('Order confirm')
                    cart = db.session.query(Cart).filter_by(user_uid=chat_id).all()
                    total = sum(list(map(lambda good: good.price, cart)))
                    try:
                        order = Order(
                            uid=chat_id,
                            first_name=first_name,
                            last_name=last_name,
                            order_total=total,
                            order_rest_id=cart[0].restaurant_id,
                            order_datetime=datetime.now().strftime('%s')
                        )
                        db.session.add(order)
                        db.session.flush()
                        text = f'Поступил заказ № {order.id}\n'
                        text += 'Состав заказа:\n'
                        for item in cart:
                            db.session.add(OrderDetail(
                                order_id=order.id,
                                order_dish_name=item.name,
                                order_dish_cost=item.price,
                                order_dish_quantity=item.quantity,
                                order_rest_id=order.order_rest_id
                            ))
                            text += f'{item.name} - {item.quantity} шт.\n'
                        text += f'Общая сумма заказа: {total} р.\n'
                        text += f'Адрес доставки: {db.session.query(User.address).filter_by(uid=chat_id).first()[0]}'
                        db.session.query(Cart).filter_by(user_uid=chat_id).delete()
                        service_uid = db.session.query(Restaurant.service_uid).filter_by(
                            id=order.order_rest_id).first()[0]
                        db.session.commit()
                        BOT.send_message(chat_id=chat_id, text='Заказ оформлен')
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
                        msg = History(
                            message_id=message_id,
                            chat_id=chat_id,
                            date=datetime.now().strftime('%s'),
                            type='message',
                            message_text=text,
                            is_bot=True
                        )
                        db.session.add(msg)
                        db.session.commit()
                    except IndexError:
                        BOT.send_message(chat_id=113737020, text='Произошла ошибка IndexError в order_confirm')

                elif re.search(r'^order_accept_[0-9]+_(30|60|120|180)$', data):
                    order_id = int(data.split('_')[2])
                    time = int(data.split('_')[3])
                    order = db.session.query(Order).filter_by(id=order_id).first()
                    text = f'Ресторан принял ваш заказ № {order.id} и доставит '
                    time_text = ''
                    sched_time = datetime.now() + timedelta(minutes=time)
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
                    text = f'Мы оповестили клиента, что Вы приняли заказ № {order.id}, доставка {time_text} '
                    text += f'на адрес: {client.address}\n'
                    text += f'Контактный номер: {client.phone}'
                    BOT.send_message(chat_id=service_uid, text=text)
                    job = sched.add_job(sendMsg, 'date', run_date=sched_time, args=[service_uid])
                elif re.search(r'^order_change_[0-9]+$', data):
                    order_id = int(data.split('_')[2])
                    order = db.session.query(Order).filter_by(id=order_id).first()
                    service_uid = db.session.query(Restaurant.service_uid).filter_by(id=order.order_rest_id).first()[0]
                    text = f'Напишите пожалуйста что хотите изменить в заказе № {order.id} и мы перенаправим ваше ' \
                           'сообщение клиенту '
                    BOT.send_message(chat_id=service_uid, text=text)
                elif re.search(r'^stat_[0-9]+$', data):
                    stat_id = int(data.split('_')[1])
                    stat_data = db.session.query(Order).all()
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
                    if stat_id == 1:
                        current_month = datetime.now().month
                        current_month_total = 0
                        current_month_rests_total = {}
                        stat_data = db.session.query(Order).all()
                        for data in stat_data:
                            # print(f'Order #{data.id} from {datetime.utcfromtimestamp(data.order_datetime).strftime(
                            # "%Y.%m.%d %H:%M:%S")}')
                            order_date = int(datetime.utcfromtimestamp(data.order_datetime).strftime("%m"))
                            if order_date == current_month:
                                current_month_total += data.order_total
                                rest = db.session.query(Restaurant.name).filter_by(id=data.order_rest_id).first()[0]
                                try:
                                    current_month_rests_total.update(
                                        {rest: current_month_rests_total[rest] + data.order_total})
                                except KeyError:
                                    current_month_rests_total.update({rest: data.order_total})
                        text = f'Общая сумма за {months[current_month]}: {current_month_total}р.\n'
                        for item in current_month_rests_total:
                            text += f'Общая сумма заказов в ресторане {item} за {months[current_month]} - ' \
                                    f'{current_month_rests_total[item]}р.\n'

                        BOT.send_message(chat_id=chat_id, text=text)
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
                    print('message!')
                    # chat_id = r['message']['chat']['id']
                    message = r['message']['text']
                    message_id = r['message']['message_id']
                    # Берем имя, если поле имя пустое, то берем юзернейм
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
                            ['Рестораны', 'Корзина'],
                            [' ', 'Оформить заказ']
                        ]
                        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        BOT.send_message(chat_id, text, reply_markup=markup)

                    elif parse_text(message) == 'Рестораны' or parse_text(message) == '/restaurants':
                        text = 'Пожалуйста, выберите ресторан:'
                        BOT.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=rest_menu_keyboard())
                        msg = History(
                            message_id=message_id,
                            chat_id=chat_id,
                            date=datetime.now().strftime('%s'),
                            type='message',
                            message_text=text,
                            is_bot=True
                        )
                        db.session.add(msg)
                        db.session.commit()
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
                            rest = db.session.query(Restaurant.name).filter_by(id=cart[0].restaurant_id).first()[0]
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
                        msg_id = 3844
                        BOT.editMessageText(
                            chat_id=chat_id,
                            message_id=msg_id,
                            text=123
                        )
                    elif parse_text(message) == 'Оформить заказ':
                        BOT.send_message(chat_id, 'Вы выбрали оформить заказ')
                    elif parse_text(message) == 'Статистика':
                        BOT.send_message(chat_id=chat_id, text='СТАТИСТИКА', reply_markup=stat_menu_keyboard())
                    elif parse_text(message) == 'Тест':
                        BOT.send_message(chat_id=chat_id, text='test', parse_mode=ParseMode.HTML)
                    elif bot_msg == 'Укажите адрес доставки':
                        text = 'Укажите номер телефона'
                        BOT.send_message(chat_id=chat_id, text=text)
                        msg = History(
                            message_id=message_id,
                            chat_id=chat_id,
                            date=datetime.now().strftime('%s'),
                            type='message',
                            message_text=text,
                            is_bot=True
                        )
                        db.session.add(msg)
                        db.session.commit()
                    elif bot_msg == 'Укажите номер телефона' or 'Вы указали некорректный номер телефона':
                        if re.search(r'^((\+7|7|8)+([0-9]){10})$', message):
                            bot_msg = db.session.query(History).filter_by(message_id=message_id - 2,
                                                                          is_bot=False).first().message_text
                            cur_usr = db.session.query(User).filter_by(uid=chat_id).first()
                            cur_usr.address = bot_msg
                            cur_usr.phone = message
                            db.session.commit()
                            text = f'Адрес доставки: {bot_msg}\n'
                            text += f'Контактный номер: {message}'
                            button = [[InlineKeyboardButton('Отправить', callback_data='order_confirm')]]
                            BOT.send_message(chat_id=chat_id,
                                             text='Мы приняли ваши данные',
                                             reply_markup=InlineKeyboardMarkup(button))
                        else:
                            BOT.send_message(chat_id=chat_id, text='Вы указали некорректный номер телефона')

                except telegram.error.Unauthorized:
                    pass
        except KeyError:
            print('KeyError', r)
        except error.BadRequest:
            print('BAD REQUEST!')
        return 'Bot action returned'
    elif request.method == 'GET':
        # return 'Main page is temporarily unavailable'
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
        if user and user.check_password(form.password.data):
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
    dish_form = DishForm()
    if dish_form.validate_on_submit():
        name = dish_form.name.data
        cost = dish_form.cost.data
        description = dish_form.description.data
        composition = dish_form.composition.data
        img_link = dish_form.img_link.data
        category = dish_form.category.data
        id_rest = dish_form.id_rest.data

        dish = Dish(
            name=name,
            cost=cost,
            description=description,
            composition=composition,
            img_link=img_link,
            category=category,
            id_rest=id_rest
        )
        db.session.add(dish)
        db.session.commit()
        flash("Блюдо добавлено", "success")
        return redirect(url_for('admin'))
    category_form = CategoryForm()
    if category_form.validate_on_submit():
        name = category_form.name.data
        restaurant_id = category_form.restaurant_id.data

        category = Category(name=name, restaurant_id=restaurant_id)
        db.session.add(category)
        db.session.commit()
        flash("Категория добавлена", "success")
        return redirect(url_for('admin'))
    return render_template(
        'admin.html',
        dishes=dishes,
        restaurants=restaurants,
        dish_form=dish_form,
        category_form=category_form
    )


@login_manager.user_loader
def load_user(user_id):
    return db.session.query(Admin).get(user_id)


def sendMsg(uid):
    BOT.send_message(chat_id=uid, text='Заданное время закончилось')


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
