import re
from datetime import datetime

from sqlalchemy import func
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from app import db, send_email
from models import Category, Restaurant, PromoDish, Dish, Cart, RestaurantDeliveryTerms, User, Order
from models import OrderDetail as OD
from settings import BOT, YKT
from utils import rest_menu_keyboard, write_history


def restaurant_callback(call):
    data = call.data.split('_')
    rest_id = data[1]
    categories = Category.query.filter_by(restaurant_id=rest_id)
    rest_name = Restaurant.query.filter_by(id=rest_id).first().name

    def categories_menu():
        kbd = InlineKeyboardMarkup()
        for category in categories.all():
            kbd.add(InlineKeyboardButton(text=category.name, callback_data=f'restaurant_{rest_id}_cat_{category.id}'))
        cb_data = f'restaurant_{rest_id}_delivery_time_call_back'
        kbd.add(InlineKeyboardButton(text='Узнать время доставки', callback_data=cb_data))
        cb_data = f'restaurant_{rest_id}_delivery_terms_show'
        kbd.add(InlineKeyboardButton('Условия доставки', callback_data=cb_data))
        text = f'Меню ресторана {rest_name}. В некоторых случаях доставка платная, районы и стоимость ' \
               'смотрите в "Условия доставки " в списке меню Ресторана.'
        if 'from_promo' not in call.data:
            cb_data = 'back_to_rest_kb'
            kbd.add(InlineKeyboardButton(text='Назад', callback_data=cb_data))
        if 'menu' in call.data:
            BOT.send_message(text=text, chat_id=call.from_user.id, reply_markup=kbd)
        else:
            BOT.edit_message_text(text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
                                  reply_markup=kbd)

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
            text = f'{rest_name}\n<a href="{dish.img_link}">.</a>\n<b>{dish.name}</b>\n{dish.composition}\n{dish.cost}'
            dish_count = db.session.query(Cart.quantity).filter_by(user_uid=call.from_user.id, dish_id=dish.id).first()
            dish_count = dish_count[0] if dish_count else 0
            cb_first = f'restaurant_{rest_id}_cat_{category_id}_dish_{dish.id}'
            cb_last = f'{call.from_user.id}'
            cb_fav = f'fav_{call.from_user.id}_{rest_id}_{dish.id}'
            keyboard.row(
                InlineKeyboardButton(text='⭐️', callback_data=cb_fav),
                InlineKeyboardButton(text='-', callback_data=f'{cb_first}_rem_{cb_last}'),
                InlineKeyboardButton(text=f'{dish_count} шт', callback_data='None'),
                InlineKeyboardButton(text='+', callback_data=f'{cb_first}_add_{cb_last}')
            )
            keyboard.add(InlineKeyboardButton('Главное меню', callback_data=f'restaurant_{rest_id}_menu'))
            keyboard.add(InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart'))
            BOT.send_message(text=text, chat_id=call.from_user.id, reply_markup=keyboard, parse_mode='HTML')
        return 'Ok'

    def dish_change():
        keyboard = InlineKeyboardMarkup()
        operation = {'add': 1, 'rem': -1}
        dish = Dish.query.filter_by(id=int(data[5])).first()
        cart_item = Cart.query.filter_by(user_uid=call.from_user.id, dish_id=dish.id).first()
        dish_count = cart_item.quantity if cart_item else 0
        if data[6] == 'add' and dish_count == 0:
            new_item = Cart(
                name=dish.name, price=dish.cost, quantity=1, user_uid=call.from_user.id,
                is_dish=1, is_water=0, dish_id=dish.id, restaurant_id=rest_id,
                service_uid=Restaurant.query.filter_by(id=rest_id).first().service_uid
            )
            db.session.add(new_item)
            db.session.commit()
        elif data[6] == 'add' or 'rem' and dish_count > 1:
            cart_item.quantity += operation.get(data[6])
            db.session.commit()
        elif data[6] == 'rem' and dish_count == 0:
            return 'Ok', 200
        elif data[6] == 'rem' and dish_count == 1:
            Cart.query.filter_by(id=cart_item.id).delete()
            db.session.commit()
        dish_count = Cart.query.filter_by(user_uid=call.from_user.id, dish_id=dish.id).first()
        dish_count = dish_count.quantity if dish_count else 0
        total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        total = total[0][0] if total[0][0] else 0
        text = f'{rest_name}\n<a href="{dish.img_link}">.</a>\n<b>{dish.name}</b>\n{dish.composition}\n{dish.cost} р.'
        cb_first = f'restaurant_{rest_id}_cat_{int(data[3])}_dish_{dish.id}'
        cb_last = f'{call.from_user.id}'
        cb_data = f'fav_{call.from_user.id}_{rest_id}_{dish.id}'
        keyboard.row(
            InlineKeyboardButton(text='⭐️', callback_data=cb_data),
            InlineKeyboardButton(text='-', callback_data=f'{cb_first}_rem_{cb_last}'),
            InlineKeyboardButton(text=f'{dish_count} шт', callback_data='None'),
            InlineKeyboardButton(text='+', callback_data=f'{cb_first}_add_{cb_last}')
        )
        keyboard.add(InlineKeyboardButton('Главное меню', callback_data=f'restaurant_{rest_id}_menu'))
        keyboard.add(InlineKeyboardButton(f'В корзину: заказ на сумму {total} р.', callback_data='cart'))
        BOT.edit_message_text(
            chat_id=call.from_user.id,
            text=text,
            message_id=call.message.id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )

    def show_terms():
        terms = RestaurantDeliveryTerms.query.filter_by(rest_id=rest_id).first()
        text = 'Ресторан не предоставил сведений'
        if terms:
            text = f'{terms.terms}\nИНН: {terms.rest_inn if terms.rest_inn else ""}\n'
            text += f'ОГРН: {terms.rest_ogrn if terms.rest_ogrn else ""}\n'
            text += f'Название организации: {terms.rest_fullname if terms.rest_fullname else ""}\n'
            text += f'Адрес: {terms.rest_address if terms.rest_address else ""}'
        BOT.send_message(chat_id=call.from_user.id, text=text)

    def show_delivery_time():
        user = User.query.filter_by(uid=call.from_user.id).first()
        text = f'Укажите только адрес доставки для ресторана {rest_name}.'
        keyboard = None
        if user.address:
            keyboard = InlineKeyboardMarkup()
            text = f'Вы указали:\nАдрес доставки: {user.address}'
            cb_data1 = f'restaurant_{rest_id}_delivery_time_confirm_{call.from_user.id}_data'
            cb_data2 = f'restaurant_{rest_id}_delivery_time_change_{call.from_user.id}'
            cb_text = 'Отправить и узнать время доставки'
            keyboard.add(InlineKeyboardButton(text=cb_text, callback_data=cb_data1))
            keyboard.add(InlineKeyboardButton(text='Изменить данные', callback_data=cb_data2))
        BOT.send_message(text=text, chat_id=call.from_user.id, reply_markup=keyboard if keyboard else None)
        write_history(call.message.id, call.from_user.id, text, True)

    def delivery_time_confirm():
        user = User.query.filter_by(uid=call.from_user.id).first()
        service_uid = Restaurant.query.filter_by(id=rest_id).first().service_uid
        text = f'Ваш запрос отправлен, ждем ответа ресторана {rest_name}'
        BOT.send_message(chat_id=user.uid, text=text)
        text = f'Клиент хочет узнать время доставки, укажите примерное время.\n' \
               f'Адрес доставки: {user.address}'
        cb_text = 'Можем доставить за'
        cb_text_no = 'Не можем доставить на этот адрес'
        cb_data = f'restaurant_{rest_id}_uid_{user.uid}_delivery_time_callback_time_count'
        keyboard = InlineKeyboardMarkup()
        opts = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
        for i in opts:
            keyboard.add(InlineKeyboardButton(cb_text + opts[i], callback_data=f'{cb_data}_{30 * i}'))
        keyboard.add(InlineKeyboardButton(text=cb_text_no, callback_data=f'{cb_data}_no'))
        BOT.send_message(chat_id=service_uid, text=text, reply_markup=keyboard)
        write_history(call.message.id, call.from_user.id, text, True)

    def delivery_time_change():
        text = f'Укажите только адрес доставки для ресторана {rest_name}'
        BOT.send_message(text=text, chat_id=call.from_user.id)
        write_history(call.message.id, call.from_user.id, text, True)

    def delivery_time_rest():
        service_uid = Restaurant.query.filter_by(id=rest_id).first().service_uid
        user = User.query.filter_by(uid=call.from_user.id).first()
        text_user = f'К сожалению, ресторан {rest_name} не сможет осуществить доставку на указанный адрес'
        text_rest = 'Мы оповестили клиента о невозможности осуществления доставки на указанный адрес'
        if data[9] != 'no':
            time = int(data[9])
            text_user = f'Ответ ресторана {rest_name}: примерное время доставки '
            answers = {30: f'{time} минут', 60: '1 час', 90: '1 час и 30 минут'}
            default = f'{time // 60} часа'
            time_text = answers.get(time, default)
            text_user += time_text + f' на адрес {user.address}'
            text_rest = f'Мы оповестили клиента, что можем доставить за {time_text} на адрес {user.address}'
        BOT.send_message(chat_id=call.from_user.id, text=text_user)
        BOT.send_message(chat_id=service_uid, text=text_rest)

    options = {
        2: categories_menu,
        3: categories_menu,
        4: show_dishes,
        5: show_terms,
        6: show_delivery_time,
        7: delivery_time_confirm,
        8: dish_change,
        9: delivery_time_change,
        10: delivery_time_rest
    }
    options.get(len(data))()


def cart_callback(call):
    print('cart callback', call.data)
    data = call.data.split('_')
    cart = Cart.query.filter_by(user_uid=call.from_user.id).all()
    rest = Restaurant.query.filter_by(id=cart[0].restaurant_id).first()

    def cart_confirm():
        total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        total = total[0][0] if total[0][0] else 0
        keyboard = InlineKeyboardMarkup()
        text = 'Выберите вариант:'
        first_button = InlineKeyboardButton(text='Доставка', callback_data='cart_confirm_delivery')
        second_button = InlineKeyboardButton(text='Самовывоз', callback_data='cart_confirm_takeaway')
        if rest.min_total or total < rest.min_total:
            text = f'Минимальная сумма заказа должна быть не менее {rest.min_total}'
            first_button = InlineKeyboardButton(text='Меню', callback_data=f'restaurant_{rest.id}')
            second_button = InlineKeyboardButton(text='Корзина', callback_data='cart')
        keyboard.add(first_button, second_button)
        BOT.send_message(chat_id=call.from_user.id, text=text, reply_markup=keyboard)

    def cart_confirm_options():
        user = User.query.filter_by(uid=call.from_user.id).first()
        option = call.data.split('_')[2]

        def delivery():
            try:
                text = f"Вы укалази:\nАдрес доставки: {user.address}\nКонтактный номер: {user.phone}"
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton(text='Отправить', callback_data='order_confirm'))
                keyboard.add(InlineKeyboardButton(text='Изменить данные', callback_data='cart_confirm_change'))
                BOT.send_message(chat_id=call.from_user.id, text=text, reply_markup=keyboard)
            except AttributeError:
                text = 'Укажите адрес доставки. Улица, дом, кв, подъезд:'
                BOT.send_message(text=text, chat_id=call.from_user.id)
            write_history(call.message.id, call.from_user.id, text, True)

        opts = {
            'change': 'Укажите адрес доставки. Улица, дом, кв, подъезд:',
            'takeaway': 'Напишите во сколько хотите забрать Ваш заказ ( в цифрах без букв)'
        }
        if option in opts:
            BOT.send_message(chat_id=call.from_user.id, text=opts.get(option))
            write_history(call.message.id, call.from_user.id, opts.get(option), True)
        else:
            delivery()

    def cart_carousel():
        cart = Cart.query.filter_by(user_uid=call.from_user.id).all()
        if not cart:
            text = 'Ваша корзина пуста'
            BOT.send_message(chat_id=call.from_user.id, text=text)
            return 'Ok', 200
        item_id = int(data[3])
        cart_item = Cart.query.filter_by(id=item_id).first()
        cart_item = cart_item if cart_item else cart[0]
        item_id = cart_item.id
        keyboard = InlineKeyboardMarkup()
        total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        total = total[0][0] if total[0][0] else 0
        text = '<b>Корзина</b>\n'
        row = [InlineKeyboardButton(text=f'{i}', callback_data=f'cart_item_id_{item.id}') for i, item in
               enumerate(cart, start=1)]
        row.insert(0, InlineKeyboardButton(text='❌', callback_data=f'cart_item_id_{item_id}_clear'))
        dish = Dish.query.filter_by(id=cart_item.dish_id).first()
        text += f'<a href="{dish.img_link}">{rest.name}</a>\n{dish.name}\n{dish.composition}\n{dish.cost}'
        keyboard.row(*row)
        row = [
            InlineKeyboardButton(text='-', callback_data=f'cart_item_id_{item_id}_remove'),
            InlineKeyboardButton(text=f'{cart_item.quantity} шт', callback_data='None'),
            InlineKeyboardButton(text='+', callback_data=f'cart_item_id_{item_id}_add')
        ]
        keyboard.row(*row)
        row = [
            InlineKeyboardButton(text='Очистить', callback_data='purge'),
            InlineKeyboardButton(text='Меню', callback_data=f'restaurant_{cart_item.restaurant_id}')
        ]
        keyboard.row(*row)
        keyboard.add(InlineKeyboardButton(text=f'Оформить заказ на сумму {total}', callback_data='cart_confirm'))
        BOT.edit_message_text(
            chat_id=call.from_user.id,
            text=text,
            message_id=call.message.id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )

    def cart_item_actions():
        operation = {'add': 1, 'remove': -1}
        item_id = int(data[3])
        item = Cart.query.filter_by(id=item_id).first()
        if data[4] in operation:
            item.quantity += operation.get(data[4])
            db.session.commit()
        elif data[4] == 'clear':
            Cart.query.filter_by(id=item.id).delete()
            db.session.commit()
        else:
            return 'Ok', 200
        if item.quantity == 0:
            Cart.query.filter_by(id=item.id).delete()
            db.session.commit()
        cart_carousel()

    options = {
        2: cart_confirm,
        3: cart_confirm_options,
        4: cart_carousel,
        5: cart_item_actions
    }
    options.get(len(data))()


def order_callback(call):
    print('order callback', call.data)
    data = call.data.split('_')

    def order_confirm():
        cart = Cart.query.filter_by(user_uid=call.from_user.id).all()
        rstrnt = Restaurant.query.filter_by(id=cart[0].restaurant_id).first()
        summ = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        summ = summ[0][0] if summ[0][0] else 0
        last_order = db.engine.execute("SELECT MAX(id) FROM Orders;").first()[0]
        new_order = Order(
            id=last_order + 1,
            uid=call.from_user.id,
            first_name=call.from_user.first_name,
            last_name=call.from_user.last_name,
            order_total=summ,
            order_rest_id=rstrnt.id,
            order_datetime=datetime.now(YKT).strftime('%s'),
            order_confirm=False,
            order_state="Заказ отправлен, ожидание ответа ресторана."
        )
        db.session.add(new_order)
        txt = f'Заказ отправлен, ждите ответа ресторана {rstrnt.name}.' \
               'За статусом заказа смотрите в "Мои заказы" в разделе Справка.'
        BOT.send_message(chat_id=call.from_user.id, text=txt)
        write_history(call.message.id, call.from_user.id, txt, True)
        user = User.query.filter_by(uid=new_order.uid).first()
        txt = f'Поступил заказ № {new_order.id}\nСостав заказа:\n'
        for item in cart:
            db.session.add(OD(
                order_id=new_order.id,
                order_dish_name=item.name,
                order_dish_cost=item.price,
                order_dish_id=item.dish_id,
                order_dish_quantity=item.quantity,
                order_rest_id=new_order.order_rest_id
            ))
            txt += f'{item.name} - {item.quantity} шт.\n'
        txt += f'Общая сумма заказа: {summ} р.\n'
        bt_label = "Принять и доставить "
        cb_data = f'order_{new_order.id}_change'
        txt += f'Адрес доставки {user.address}\nПерейдите в чат-бот, чтобы обработать заказ https://t.me/robofood1bot'
        kbd = InlineKeyboardMarkup()
        d = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
        for item in d:
            kbd.add(InlineKeyboardButton(bt_label + d[item], callback_data=f'order_{new_order.id}_accept_{30*item}'))
        kbd.add(InlineKeyboardButton(text='Не принят', callback_data='None')),
        kbd.add(InlineKeyboardButton(f'Изменить заказ № {new_order.id}', callback_data=cb_data))
        Cart.query.filter_by(user_uid=call.from_user.id).delete()
        db.session.commit()
        del cart
        send_email(rstrnt.email, f'Поступил заказ из Robofood № {new_order.id}', txt)
        return rstrnt.service_uid, txt, kbd

    def order_confirm_change_actions():
        action = call.data.split('_')[3]
        txt = 'Напишите во сколько хотите забрать Ваш заказ.'
        if action == 'phone':
            txt = 'Укажите номер телефона для самовывоза:'
        return call.from_user.id, txt, None
    
    def order_quadruple_actions():
        order = Order.query.filter_by(id=int(data[1])).first()
        details = OD.query.filter_by(order_id=order.id).all()
        user_id, txt, kbd = None, None, None
        rest = Restaurant.query.filter_by(id=order.order_rest_id).first()
        if data[3] == 'confirm':
            user_id = call.from_user.id
            details = OD.query.filter_by(order_id=order.id).all()
            txt = f'Заказ отправлен ждите ответа ресторана {rest.name}. За статусом заказа смотрите в "Мои ' \
                   f'заказы" в разделе Справка.'
            order.order_state = 'Заказ отправлен, ожидание ответа ресторана'
            BOT.send_message(chat_id=user_id, text=txt)
            txt = f'Поступил заказ № {order.id}\nСостав заказа:\n'
            txt += ''.join(f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n' for item in details)
            txt += f'Общая сумма заказа: {order.order_total} р.\n'
            txt += f'Адрес доставки: {db.session.query(User.address).filter_by(uid=user_id).first()[0]}'
            kbd = InlineKeyboardMarkup()
            bt_text = "Принять и доставить "
            opts = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
            for i in opts:
                keyboard.add(InlineKeyboardButton(bt_text + opts[i], callback_data=f'order_{order.id}_accept_{30 * i}'))
            keyboard.add(InlineKeyboardButton(text='Не принят', callback_data='None')),
            keyboard.add(InlineKeyboardButton(f'Изменить заказ № {order.id}', callback_data=f'order_{order.id}_change'))
            user_id = rest.service_uid
            db.session.commit()
        elif data[3] == 'cancel':
            txt = f'Ваш заказ № {order.id} отменен'
            BOT.send_message(chat_id=call.from_user.id, text=txt)
            txt = f'Клиент отменил заказ № {order.id}'
            order.order_state = 'Отменен'
            user_id = rest.service_uid
            db.session.commit()
        elif data[3] == 'change':
            order.order_state = 'Изменен'
            for item in details:
                db.session.add(Cart(
                    name=item.order_dish_name,
                    price=item.order_dish_cost,
                    quantity=item.order_dish_quantity,
                    user_uid=order.uid,
                    is_dish=True,
                    is_water=False,
                    dish_id=item.order_dish_id,
                    restaurant_id=order.order_rest_id,
                    service_uid=rest.service_uid
                ))
            db.session.commit()
            cart = Cart.query.filter_by(user_uid=order.uid).all()
            txt = f'Клиент решил изменить заказ № {order.id}. Номер заказа будет изменен.'
            BOT.send_message(chat_id=call.from_user.id, text=txt)
            kbd = InlineKeyboardMarkup()
            row = [InlineKeyboardButton(text=f'{i}', callback_data=f'cart_item_id_{item.id}') for i, item in
                   enumerate(cart, start=1)]
            row.insert(0, InlineKeyboardButton(text='❌', callback_data=f'cart_item_id_{cart[0].id}_clear'))
            kbd.row(*row)
            row = [
                InlineKeyboardButton(text='-', callback_data=f'cart_id_{cart[0].id}_remove'),
                InlineKeyboardButton(text=f'{cart[0].quantity} шт', callback_data='None'),
                InlineKeyboardButton(text='+', callback_data=f'cart_id_{cart[0].id}_add')
            ]
            kbd.row(*row)
            row = [
                InlineKeyboardButton(text='Очистить', callback_data=f'cart_purge'),
                InlineKeyboardButton(text='Меню', callback_data=f'restaurant_{cart[0].restaurant_id}')
            ]
            kbd.row(*row)
            cb_text = f'Оформить заказ на сумму {order.order_total}'
            kbd.add(InlineKeyboardButton(text=cb_text, callback_data='cart_confirm'))
            dish = Dish.query.filter_by(id=cart[0].dish_id).first()
            txt = f'<b>Корзина</b>\n<a href="{dish.img_link}">{rest}</a>\n{dish.composition}\n{cart[0].price}'
            user_id = order.uid
        else:
            OD.query.filter_by(id=int(data[3])).delete()
            user_id = call.from_user.id
            total = db.session.query(func.sum(OD.order_dish_cost * OD.order_dish_quantity)).filter_by(
                order_id=order.id).all()
            total = total[0][0] if total[0][0] else 0
            order.total = total
            db.session.commit()
            details = OD.query.filter_by(order_id=order.id).all()
            if not details:
                markup = rest_menu_keyboard()
                txt = f'Ресторан {rest.name} отменил заказ. Пожалуйста, выберите ресторан:'
                if not markup.keyboard:
                    txt = f'Ресторан {rest.name} отменил заказ. В данное время нет работающих ресторанов'
                    markup = None
                BOT.send_message(chat_id=user_id, text=txt, reply_markup=markup)
                order.state = 'Заказ отменен'
                db.session.commit()
                txt = 'Заказ отменен, клиенту направлено соответствующее сообщение'
                user_id = rest.service_uid
            else:
                txt = f'Что хотите изменить в заказе № {order.id}?'
                kbd = InlineKeyboardMarkup()
                for item in details:
                    cb_txt = f'{item.order_dish_name}, {item.order_dish_quantity} шт.'
                    kbd.row(
                        InlineKeyboardButton(text=cb_txt, callback_data='None'),
                        InlineKeyboardButton(text='❌', callback_data=f'order_{order.id}_del_{item.id}')
                    )
                kbd.add(InlineKeyboardButton(text='Отправить клиенту', callback_data=f'order_{order.id}_send2user'))
                kbd.add(InlineKeyboardButton(text='Назад', callback_data=f'order_{order.id}_menu'))
                BOT.edit_message_text(text=txt, chat_id=rest.service_uid, message_id=call.message.id, reply_markup=kbd)
                txt, kbd = None, None
        return user_id, txt, kbd

    def order_quintuple_actions():
        order = Order.query.filter_by(id=int(data[1])).first()
        details = OD.query.filter_by(order_id=order.id).all()
        user_id, txt, kbd = None, None, None
        rest = Restaurant.query.filter_by(id=order.order_rest_id).first()
        total = db.session.query(func.sum(OD.order_dish_cost*OD.order_dish_quantity)).filter_by(order_id=order.id).all()
        total = total[0][0] if total[0][0] else 0
        if data[2] == 'confirm':
            kbd = InlineKeyboardMarkup()
            user_id = rest.service_uid
            txt = f'Поступил заказ № {order.id}\nСостав заказа:\n'
            txt += ''.join(f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n' for item in details)
            txt += f'Общая сумма заказа: {total} р.\nСамовывоз, время {data[4]}'
            kbd.add(InlineKeyboardButton(text='Принять', callback_data=f'order_{order.id}_accept_0_{data[4]}'))
            kbd.add(InlineKeyboardButton(text='Отменить', callback_data=f'order_{order.id}_change'))
        elif data[2] == 'accept':
            time = int(data[4])
            pattern = r'(.[0-2][0-9]:[0-5][0-9](.*)[0-2][0-9]:[0-5][0-9])|' \
                      r'(.[а-яА-Я][a-яА-Я]-[а-яА-Я][a-яА-Я].[0-2][0-9]:[0-5][0-9](.*)[0-2][0-9]:[0-5][0-9])'
            rest_name = re.sub(pattern, '', rest.name)
            answers = {30: f'{time} минут', 60: '1 часа', 90: '1 часа и 30 минут'}
            default = f'{time // 60} часов'
            time_txt = answers.get(time, default)
            user_id = rest.service_uid
            if time != 0:
                txt = f'Ресторан {rest_name} принял ваш заказ № {order.id} и доставит в течении '
                BOT.send_message(chat_id=user_id, text=txt+time_txt)
                kbd = InlineKeyboardMarkup()
                cb_text = 'Принять и доставить '
                cb_data = f'order_{order.id}_accept'
                opts = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
                for i in opts:
                    kbd.add(InlineKeyboardButton(cb_text + opts[i], callback_data=f'{cb_data}_{30 * i}'))
                cb_data = f'order_{order.id}_change'
                kbd.add(InlineKeyboardButton(text=f'Принят на доставку в течении {time_txt}', callback_data='None'))
                kbd.add(InlineKeyboardButton(text=f'Изменить заказ № {order.id}', callback_data=cb_data))
            state = 'самовывоз' if time == 0 else 'доставка'
            order.order_state = 'Заказ принят рестораном, ' + state
            order.order_state += txt[53:] if time != 0 else ''
            client = User.query.filter_by(uid=order.uid).first()
            txt = f'Поступил заказ № {order.id}\nСостав заказа:\n'
            txt += ''.join(f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n' for item in details)
            txt += f'Общая сумма заказа: {order.order_total} р.\n'
            txt += f'Адрес доставки: {client.address}' if time != 0 else f'Самовывоз, {time_txt}'
            BOT.edit_message_text(text=txt, chat_id=user_id, message_id=call.message.id, reply_markup=kbd)
            txt = f'Мы оповестили клиента, что Вы приняли заказ № {order.id}'
            txt += f', доставка {time_txt} на адрес: {client.address}\n' if time != 0 else f'\nСамовывоз, {time_txt}'
            txt += f'Контактный номер: {client.phone}'
            kbd = None
            db.session.commit()

        return user_id, txt, kbd

    actions = {
        2: order_confirm, 4: order_quadruple_actions, 5: order_quintuple_actions, 6: order_confirm_change_actions
    }
    uid, text, keyboard = actions.get(len(data))()
    BOT.send_message(chat_id=uid, text=text, reply_markup=keyboard, parse_mode='HTML')
    write_history(call.message.id, call.from_user.id, text, True)


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

    def cart_purge(data):
        Cart.query.filter_by(user_uid=data.from_user.id).delete()
        db.session.commit()
        text = 'Ваша корзина пуста'
        BOT.edit_message_text(chat_id=data.from_user.id, message_id=data.message.id, text=text)

    options = {
        'back_to_rest_kb': back_to_rest,
        'back_to_rest_promo': back_to_rest_promo,
        'purge': cart_purge,
        'to_rest': None
    }

    options.get(call.data)(call)
