import time

from sqlalchemy import func
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from app import db
from models import Category, Restaurant, PromoDish, Dish, Cart
from settings import BOT
from utils import rest_menu_keyboard


def restaurant_callback(call):
    keyboard = InlineKeyboardMarkup()
    data = call.data.split('_')
    rest_id = data[1]
    categories = Category.query.filter_by(restaurant_id=rest_id)
    rest_name = Restaurant.query.filter_by(id=rest_id).first().name

    def categories_menu():
        for category in categories.all():
            keyboard.add(
                InlineKeyboardButton(text=category.name, callback_data=f'restaurant_{rest_id}_cat_{category.id}'))
        cb_data = f'restaurant_{rest_id}_delivery_time'
        keyboard.add(InlineKeyboardButton(text='Узнать время доставки', callback_data=cb_data))
        cb_data = f'restaurant_{rest_id}_delivery_terms'
        keyboard.add(InlineKeyboardButton('Условия доставки', callback_data=cb_data))
        text = f'Меню ресторана {rest_name}. В некоторых случаях доставка платная, районы и стоимость ' \
               'смотрите в "Условия доставки " в списке меню Ресторана.'
        if 'from_promo' not in call.data:
            cb_data = 'back_to_rest_kb'
            keyboard.add(InlineKeyboardButton(text='Назад', callback_data=cb_data))
        if 'menu' in call.data:
            BOT.send_message(text=text, chat_id=call.from_user.id, reply_markup=keyboard)
        else:
            BOT.edit_message_text(text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
                                  reply_markup=keyboard)

    def show_dishes():
        text = 'Если отключены автозагрузки фотографий для удобства просмотра блюд включите в ' \
               'настройках Telegram - Данные и память, Автозагрузка медиа, включить Фото через ' \
               'мобильную сеть и через Wi-Fi. '
        BOT.send_message(text=text, chat_id=call.from_user.id)
        category_id = int(data[3])
        category_name = categories.filter(Category.id == category_id).first().name
        dishes = Dish.query.filter_by(id_rest=rest_id, category=category_name).all()
        total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        total = total[0][0] if total[0][0] else 0
        for dish in dishes:
            keyboard = InlineKeyboardMarkup()
            text = f'{rest_name}\n<a href="{dish.img_link}">.</a>'
            text += f'\n<b>{dish.name}</b>\n{dish.composition}\n{dish.cost}'
            dish_count = db.session.query(Cart.quantity).filter_by(user_uid=call.from_user.id, dish_id=dish.id).first()
            dish_count = dish_count[0] if dish_count else 0
            cb_first = f'restaurant_{rest_id}_cat_{category_id}_dish_{dish.id}'
            cb_last = f'{call.from_user.id}'
            cb_fav = f'fav_{call.from_user.id}_{rest_id}_{dish.id}'
            keyboard.row(
                InlineKeyboardButton('⭐️', callback_data=cb_fav),
                InlineKeyboardButton('-', callback_data=f'{cb_first}_rem_{cb_last}'),
                InlineKeyboardButton(f'{dish_count} шт', callback_data='None'),
                InlineKeyboardButton('+️', callback_data=f'{cb_first}_add_{cb_last}')
            )
            keyboard.add(InlineKeyboardButton('Главное меню', callback_data=f'restaurant_{rest_id}_menu'))
            keyboard.add(InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart'))
            BOT.send_message(text=text, chat_id=call.from_user.id, reply_markup=keyboard, parse_mode='HTML')
        return 'Ok'

    def dish_change():
        operation = {'add': 1, 'rem': -1}
        dish = Dish.query.filter_by(id=int(data[5])).first()
        cart_item = Cart.query.filter_by(user_uid=call.from_user.id, dish_id=dish.id).first()
        dish_count = cart_item.quantity if cart_item else 0
        if data[6] == 'add' and dish_count == 0:
            new_item = Cart(
                name=dish.name,
                price=dish.cost,
                quantity=1,
                user_uid=call.from_user.id,
                is_dish=1,
                is_water=0,
                dish_id=dish.id,
                restaurant_id=rest_id,
                service_uid=Restaurant.query.filter_by(id=rest_id).first().service_uid
            )
            db.session.add(new_item)
            db.session.commit()
        else:
            cart_item.quantity += operation.get(data[6])
            if cart_item.quantity < 0:
                return 'Ok', 200
            db.session.commit()
        text = f'{rest_name}\n'
        text += f'<a href="{dish.img_link}">.</a>'
        text += f'\n<b>{dish.name}</b>'
        text += f'\n{dish.composition}'
        text += f'\n{dish.cost} р.'
        dish_count = Cart.query.filter_by(user_uid=call.from_user.id, dish_id=dish.id).first().quantity
        cb_first = f'restaurant_{rest_id}_cat_{int(data[3])}_dish_{dish.id}'
        cb_last = f'{call.from_user.id}'
        cb_data = f'fav_{call.from_user.id}_{rest_id}_{dish.id}'
        keyboard.row(
            InlineKeyboardButton('⭐️', callback_data=cb_data),
            InlineKeyboardButton('-️', callback_data=f'{cb_first}_rem_{cb_last}'),
            InlineKeyboardButton(f'{dish_count} шт', callback_data='None'),
            InlineKeyboardButton('+️', callback_data=f'{cb_first}_add_{cb_last}')
        )
        total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        total = total[0][0] if total[0][0] else 0
        keyboard.add(InlineKeyboardButton('Главное меню', callback_data=f'restaurant_{rest_id}_menu'))
        keyboard.add(InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart'))
        BOT.edit_message_text(
            chat_id=call.from_user.id,
            text=text,
            message_id=call.message.id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )

    print(data)
    options = {
        2: categories_menu,
        4: show_dishes,
        8: dish_change,
    }
    options.get(len(data))()


def cart_callback(call):
    print('cart callback', call.data)


def order_callback(call):
    print('order callback', call.data)


def other_callback(call):
    print('other callback')

    def back_to_rest(data):
        text = 'Пожалуйста, выберите ресторан:'
        BOT.edit_message_text(
            chat_id=data.from_user.id,
            message_id=data.message.message_id,
            text=text,
            reply_markup=rest_menu_keyboard()
        )

    def back_to_rest_promo(data):
        keyboard = InlineKeyboardMarkup()
        promo_dish = PromoDish.query.first()
        text = f'<a href="{promo_dish.img_link}">.</a>'
        cb_data = f'restaurant_{promo_dish.rest_id}_from_promo'
        keyboard.add(InlineKeyboardButton(text='Меню ресторана', callback_data=cb_data))
        BOT.edit_message_text(
            chat_id=data.from_user.id,
            message_id=data.message.message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode='HTML'
        )

    options = {
        'back_to_rest_kb': back_to_rest,
        'back_to_rest_promo': back_to_rest_promo,
    }

    options.get(call.data)(call)
