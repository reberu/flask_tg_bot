import logging
import re
from datetime import datetime

from sqlalchemy import func
from telebot import formatting
from telebot.types import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB, WebAppInfo
from app import db, send_email
from models import Category, Restaurant, PromoDish, Dish, Cart, RestaurantDeliveryTerms, User, Order, Favorites, \
    SpecialDish, TextMenuMessage as Menu, RestaurantInfo, TextMenuMessage
from models import OrderDetail as OD
from settings import BOT, YKT, RULES, BASE_URL
from utils import rest_menu_keyboard, write_history


def restaurant_callback(call):
    data = call.data.split('_')
    logging.log(logging.INFO, f'rest_callback {data}')
    rest_id = int(data[1])
    categories = Category.query.filter_by(restaurant_id=rest_id)
    rest = Restaurant.query.filter_by(id=rest_id).first()
    webapp = WebAppInfo(BASE_URL + f"webapp/{rest_id}?uid={call.from_user.id}")
    webapp_info = WebAppInfo(BASE_URL + f"webapp_info/{rest.id}")

    def categories_menu():
        kbd = IKM()
        kbd.add(IKB(text="Компактный просмотр", web_app=webapp))
        for category in categories.all():
            kbd.add(IKB(text=category.name, callback_data=f'rest_{rest_id}_cat_{category.id}'))
        cb_data = f'rest_{rest_id}_delivery_time_call_back'
        kbd.add(IKB(text='Узнать время доставки', callback_data=cb_data))
        cb_data = f'rest_{rest_id}_delivery_terms_show'
        kbd.add(IKB('Условия доставки', callback_data=cb_data))
        text = f'Меню ресторана {rest.name}. В некоторых случаях доставка платная, районы и стоимость ' \
               'смотрите в "Условия доставки " в списке меню Ресторана.'
        if 'from_promo' not in call.data:
            cb_data = 'back_to_rest_kb'
            kbd.add(IKB(text='Назад', callback_data=cb_data))
        if 'menu' in call.data:
            BOT.send_message(text=text, chat_id=call.from_user.id, reply_markup=kbd)
        else:
            BOT.edit_message_text(text=text, chat_id=call.from_user.id, message_id=call.message.message_id,
                                  reply_markup=kbd)
        write_history(call.message.id, call.from_user.id, rest_id, False)

    def show_dishes():
        text = 'Если отключены автозагрузки фотографий для удобства просмотра блюд включите в ' \
               'настройках Telegram - Данные и память, Автозагрузка медиа, включить Фото через ' \
               'мобильную сеть и через Wi-Fi. '
        BOT.send_message(text=text, chat_id=call.from_user.id)
        category_id = int(data[3])
        category_name = categories.filter(Category.id == category_id).first().name
        dishes = Dish.query.filter_by(id_rest=rest.id, category=category_name).all()
        # total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        # total = total[0][0] if total[0][0] else 0
        for dish in dishes:
            rest_info = RestaurantInfo.query.filter_by(rest_id=rest.id).first()
            delivery_time = rest_info.delivery_time if rest_info else 'с ожиданием'
            takeaway_address = rest_info.takeaway_address if rest_info else rest.address
            keyboard = IKM()
            text = f'{rest.name}\nДоставка - {delivery_time}\nСамовывоз - {takeaway_address}\n\n<b>{dish.name}</b>' \
                   f'\n{dish.composition}\n{dish.cost} ₽\n<a href="{dish.img_link}">.</a>'
            dish_count = db.session.query(Cart.quantity).filter_by(user_uid=call.from_user.id, dish_id=dish.id).first()
            dish_count = dish_count[0] if dish_count else 0
            change_callback = f'rest_{rest_id}_cat_{category_id}_dish_{dish.id}'
            fav_callback = f'fav_{call.from_user.id}_{rest_id}_{dish.id}'
            keyboard.row(
                IKB(text='⭐️', callback_data=fav_callback),
                IKB(text='-', callback_data=f'{change_callback}_rem_{call.from_user.id}'),
                IKB(text=f'{dish_count} шт', callback_data='None'),
                IKB(text='+', callback_data=f'{change_callback}_add_{call.from_user.id}')
            )
            # keyboard.row(
            #     IKB('Инфо', web_app=webapp_info),
            #     IKB('В меню ресторана', callback_data=f'rest_{rest_id}_menu')
            # )
            # keyboard.add(IKB(f'В корзину: заказ на сумму {total} р.', callback_data='cart'))
            BOT.send_message(text=text, chat_id=call.from_user.id, reply_markup=keyboard, parse_mode='HTML')
        return 'Ok', 200

    def dish_change():
        rest_id, cat_id, dish_id, method = int(data[1]), int(data[3]), int(data[5]), data[6]
        operation = {'add': 1, 'rem': -1}
        dish = Dish.query.filter_by(id=dish_id).first()
        cart_item = Cart.query.filter_by(user_uid=call.from_user.id, dish_id=dish.id).first()
        dish_count = cart_item.quantity if cart_item else 0
        if method == 'add' and dish_count == 0:
            if Cart.query.filter(Cart.user_uid == call.from_user.id, Cart.restaurant_id.notlike(rest.id)).all():
                Cart.query.filter(
                    Cart.user_uid == call.from_user.id, Cart.restaurant_id.notlike(rest.id)
                ).delete(synchronize_session=False)
                menu = Menu.query.filter(Menu.user_id == call.from_user.id, Menu.rest_id != rest.id).all()
                for item in menu:
                    cb_data = f'fav_{item.user_id}_{item.rest_id}_{item.dish_id}'
                    change_callback = f'rest_{item.rest_id}_cat_{item.category_id}_dish_{item.dish_id}'
                    keyboard = IKM(row_width=4)
                    button1 = IKB(text='⭐', callback_data=cb_data)
                    button2 = IKB(text='-', callback_data=f'{change_callback}_rem_{item.user_id}')
                    button3 = IKB(text='0 шт.', callback_data='None')
                    button4 = IKB(text='+', callback_data=f'{change_callback}_add_{item.user_id}')
                    keyboard.add(button1, button2, button3, button4)
                    try:
                        BOT.edit_message_reply_markup(
                            chat_id=item.user_id, message_id=item.message_id, reply_markup=keyboard
                        )
                    except Exception as e:
                        print(e)

                txt = "Вы добавили блюдо другого ресторана, корзина будет очищена"
                BOT.answer_callback_query(callback_query_id=call.id, show_alert=False, text=txt)
            new_item = Cart(
                name=dish.name, price=dish.cost, quantity=1, user_uid=call.from_user.id,
                is_dish=1, is_water=0, dish_id=dish.id, restaurant_id=rest_id,
                service_uid=Restaurant.query.filter_by(id=rest_id).first().service_uid
            )
            db.session.add(new_item)
            db.session.commit()
        elif method == 'add' or 'rem' and dish_count > 1:
            cart_item.quantity += operation.get(method)
            db.session.commit()
        elif method == 'rem' and dish_count == 0:
            return 'Ok', 200
        elif method == 'rem' and dish_count == 1:
            Cart.query.filter_by(id=cart_item.id).delete()
            db.session.commit()
        dish_count = Cart.query.filter_by(user_uid=call.from_user.id, dish_id=dish.id).first()
        dish_count = dish_count.quantity if dish_count else 0
        total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        total = total[0][0] if total[0][0] else 0
        change_callback = f'rest_{rest_id}_cat_{cat_id}_dish_{dish.id}'
        fav_callback = f'fav_{call.from_user.id}_{rest_id}_{dish.id}'
        keyboard = IKM()
        keyboard.row(
            IKB(text='⭐️', callback_data=fav_callback),
            IKB(text='-', callback_data=f'{change_callback}_rem_{call.from_user.id}'),
            IKB(text=f'{dish_count} шт', callback_data='None'),
            IKB(text='+', callback_data=f'{change_callback}_add_{call.from_user.id}')
        )
        if dish_count > 0:
            webapp = WebAppInfo(BASE_URL + f"webapp/{rest_id}?dishId={dish.id}&uid={call.from_user.id}")
            keyboard.row(IKB('Инфо', web_app=webapp_info))
            keyboard.add(IKB(f'В корзину: заказ на сумму {total} р.', callback_data='cart'))
            keyboard.add(IKB(f'Добавить другие блюда', web_app=webapp))
        BOT.edit_message_reply_markup(
            chat_id=call.from_user.id,
            message_id=call.message.id,
            reply_markup=keyboard
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
        text = f'Укажите только адрес доставки для ресторана {rest.name}.'
        keyboard = None
        if user.address:
            keyboard = IKM()
            text = f'Вы указали:\nАдрес доставки: {user.address}'
            cb_data1 = f'rest_{rest_id}_delivery_time_confirm_{call.from_user.id}_data'
            cb_data2 = f'rest_{rest_id}_delivery_t_i_m_e_change_{call.from_user.id}'
            cb_text = 'Отправить и узнать время доставки'
            keyboard.add(IKB(text=cb_text, callback_data=cb_data1))
            keyboard.add(IKB(text='Изменить данные', callback_data=cb_data2))
        BOT.send_message(text=text, chat_id=call.from_user.id, reply_markup=keyboard if keyboard else None)
        write_history(call.message.id, call.from_user.id, text, True)

    def delivery_time_confirm():
        user = User.query.filter_by(uid=call.from_user.id).first()
        service_uid = Restaurant.query.filter_by(id=rest_id).first().service_uid
        text = f'Ваш запрос отправлен, ждем ответа ресторана {rest.name}'
        BOT.send_message(chat_id=user.uid, text=text)
        text = f'Клиент хочет узнать время доставки, укажите примерное время.\n' \
               f'Адрес доставки: {user.address}'
        cb_text = 'Можем доставить за '
        cb_text_no = 'Не можем доставить на этот адрес'
        cb_data = f'rest_{rest_id}_uid_{user.uid}_delivery_time_callback_time_count'
        keyboard = IKM()
        opts = {1: '30 минут', 2: '1 час', 3: '1 час и 30 минут', 4: '2 часа', 6: '3 часа'}
        for i in opts:
            keyboard.add(IKB(cb_text + opts[i], callback_data=f'{cb_data}_{30 * i}'))
        keyboard.add(IKB(text=cb_text_no, callback_data=f'{cb_data}_no'))
        BOT.send_message(chat_id=service_uid, text=text, reply_markup=keyboard)
        write_history(call.message.id, call.from_user.id, text, True)

    def delivery_time_change():
        text = f'Укажите только адрес доставки для ресторана {rest.name}'
        msg = BOT.send_message(text=text, chat_id=call.from_user.id)
        BOT.register_next_step_handler(msg, delivery_time_change_address)
        write_history(call.message.id, call.from_user.id, text, True)

    def delivery_time_change_address(pair):
        text = f'Ваш запрос отправлен, ждем ответа ресторана {rest.name}'
        BOT.send_message(chat_id=pair.chat.id, text=text)
        text = f'Клиент хочет узнать время доставки, укажите примерное время.\nАдрес доставки: {pair.text}'
        cb_text = 'Можем доставить за '
        cb_text_no = 'Не можем доставить на этот адрес'
        cb_data = f'rest_{rest.id}_uid_{pair.chat.id}_delivery_time_callback_time_count'
        keyboard = IKM()
        opts = {1: '30 минут', 2: '1 час', 3: '1 час и 30 минут', 4: '2 часа', 6: '3 часа'}
        for i in opts:
            keyboard.add(IKB(cb_text + opts[i], callback_data=f'{cb_data}_{30 * i}'))
        keyboard.add(IKB(text=cb_text_no, callback_data=f'{cb_data}_no'))
        BOT.send_message(chat_id=rest.service_uid, text=text, reply_markup=keyboard)
        client = User.query.filter_by(uid=pair.chat.id).first()
        client.address = pair.text
        db.session.commit()

    def delivery_time_rest():
        service_uid = Restaurant.query.filter_by(id=rest_id).first().service_uid
        user = User.query.filter_by(uid=call.from_user.id).first()
        text_user = f'К сожалению, ресторан {rest.name} не сможет осуществить доставку на указанный адрес'
        text_rest = 'Мы оповестили клиента о невозможности осуществления доставки на указанный адрес'
        if data[9] != 'no':
            time = int(data[9])
            text_user = f'Ответ ресторана {rest.name}: примерное время доставки '
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
    data = call.data.split('_')
    cart = Cart.query.filter_by(user_uid=call.from_user.id).all()
    rest = Restaurant.query.filter_by(id=cart[0].restaurant_id).first()

    def cart_confirm():
        total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        total = total[0][0] if total[0][0] else 0
        keyboard = IKM()
        text = 'Выберите вариант:'
        first_button = IKB(text='Доставка', callback_data='cart_confirm_delivery')
        second_button = IKB(text='Самовывоз', callback_data='cart_confirm_takeaway')
        if rest.min_total or total < rest.min_total:
            text = f'Минимальная сумма заказа должна быть не менее {rest.min_total}'
            first_button = IKB(text='Меню', callback_data=f'rest_{rest.id}')
            second_button = IKB(text='Корзина', callback_data='cart')
        keyboard.add(first_button, second_button)
        BOT.send_message(chat_id=call.from_user.id, text=text, reply_markup=keyboard)

    def cart_confirm_options():
        user = User.query.filter_by(uid=call.from_user.id).first()
        option = call.data.split('_')[2]

        def delivery():
            try:
                text = f"Вы указали:\nАдрес доставки: {user.address}\nКонтактный номер: {user.phone}"
                keyboard = IKM()
                keyboard.add(IKB(text='Отправить', callback_data='order_confirm'))
                keyboard.add(IKB(text='Изменить данные', callback_data='cart_confirm_change'))
                BOT.send_message(chat_id=call.from_user.id, text=text, reply_markup=keyboard)
            except AttributeError:
                text = 'Укажите адрес доставки. Улица, дом, кв, подъезд:'
                mesg = BOT.send_message(text=text, chat_id=call.from_user.id)
                BOT.register_next_step_handler(mesg, cart_delivery_address)
            write_history(call.message.id, call.from_user.id, text, True)

        opts = {
            'change': 'Укажите адрес доставки. Улица, дом, кв, подъезд:',
            'takeaway': 'Напишите во сколько хотите забрать Ваш заказ (в цифрах без букв)'
        }

        def cart_delivery_address(pair):
            usr = User.query.filter_by(uid=pair.chat.id).first()
            usr.address = pair.text
            db.session.commit()
            mesg = BOT.send_message(chat_id=pair.chat.id, text='Укажите номер телефона')
            BOT.register_next_step_handler(mesg, cart_delivery_phone)

        def cart_delivery_phone(pair):
            usr = User.query.filter_by(uid=pair.chat.id).first()
            usr.phone = pair.text
            db.session.commit()
            text = f'Вы указали:\nАдрес доставки: {usr.address}\nКонтактный номер: {usr.phone}'
            keyboard = IKM()
            keyboard.add(IKB(text='Отправить', callback_data='order_confirm'))
            keyboard.add(IKB(text='Изменить данные', callback_data='cart_confirm_change'))
            BOT.send_message(chat_id=pair.chat.id, text=text, reply_markup=keyboard)

        def cart_takeaway(pair):
            usr = User.query.filter_by(uid=pair.chat.id).first()
            text, kbd = 'Укажите номер телефона для самовывоза:', None
            if usr.phone:
                text = f'Вы указали:\nСамовывоз: {pair.text}\nКонтактный номер: {usr.phone}'
                cb_time = f'order_confirm_change_time_takeaway_{pair.text}'
                cb_phone = f'order_confirm_change_phone_takeaway_{pair.text}'
                kbd = IKM()
                kbd.add(IKB(text='Отправить', callback_data=f'order_id_confirm_takeaway_{pair.text}'))
                kbd.add(IKB(text='Изменить время', callback_data=cb_time))
                kbd.add(IKB(text='Изменить телефон', callback_data=cb_phone))
                BOT.send_message(chat_id=pair.chat.id, text=text, reply_markup=kbd)
            else:
                mesg = BOT.send_message(chat_id=pair.chat.id, text=text)
                BOT.register_next_step_handler(mesg, cart_takeaway_phone, pair.text)

        def cart_takeaway_phone(pair, time):
            usr = User.query.filter_by(uid=pair.chat.id).first()
            usr.phone = pair.text
            db.session.commit()
            text = f'Вы указали:\nСамовывоз: {time}\nКонтактный номер: {usr.phone}'
            cb_time = f'order_confirm_change_time_takeaway_{time}'
            cb_phone = f'order_confirm_change_phone_takeaway_{usr.phone}'
            db.session.commit()
            kbd = IKM()
            kbd.add(IKB(text='Отправить', callback_data=f'order_id_confirm_takeaway_{time}'))
            kbd.add(IKB(text='Изменить время', callback_data=cb_time))
            kbd.add(IKB(text='Изменить телефон', callback_data=cb_phone))
            BOT.send_message(chat_id=pair.chat.id, text=text, reply_markup=kbd)

        if option in opts:
            msg = BOT.send_message(chat_id=call.from_user.id, text=opts.get(option))
            BOT.register_next_step_handler(msg, cart_delivery_address if option == 'change' else cart_takeaway)
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
        keyboard = IKM()
        total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
        total = total[0][0] if total[0][0] else 0
        text = '<b>Корзина</b>\n'
        row = [IKB(text=f'{i}', callback_data=f'cart_item_id_{item.id}') for i, item in
               enumerate(cart, start=1)]
        row.insert(0, IKB(text='❌', callback_data=f'cart_item_id_{item_id}_clear'))
        dish = Dish.query.filter_by(id=cart_item.dish_id).first()
        text += f'<a href="{dish.img_link}">{rest.name}</a>\n{dish.name}\n{dish.composition}\n{dish.cost}'
        keyboard.row(*row)
        row = [
            IKB(text='-', callback_data=f'cart_item_id_{item_id}_remove'),
            IKB(text=f'{cart_item.quantity} шт', callback_data='None'),
            IKB(text='+', callback_data=f'cart_item_id_{item_id}_add')
        ]
        keyboard.row(*row)
        row = [
            IKB(text='Очистить', callback_data='purge'),
            IKB(text='Меню', web_app=WebAppInfo(BASE_URL + f"webapp/{rest.id}?uid={call.from_user.id}"))
        ]
        keyboard.row(*row)
        keyboard.add(IKB(text=f'Оформить заказ на сумму {total}', callback_data='cart_confirm'))
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
        txt = f'Заказ отправлен, ждите ответа ресторана {rstrnt.name}.\n' \
              'За статусом заказа смотрите в "Мои заказы" в разделе Справка.'
        BOT.send_message(chat_id=call.from_user.id, text=txt)
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
        txt += f'Адрес доставки: {user.address}\n'
        tlg_link = 'Перейдите в чат-бот, чтобы обработать заказ https://t.me/robofood1bot'
        kbd = IKM()
        d = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
        for item in d:
            kbd.add(IKB(bt_label + d[item], callback_data=f'order_{new_order.id}_accept_{30 * item}_send'))
        kbd.add(IKB(text='Не принят', callback_data='None')),
        kbd.add(IKB(f'Изменить заказ № {new_order.id}', callback_data=cb_data))
        Cart.query.filter_by(user_uid=call.from_user.id).delete()
        db.session.commit()
        del cart
        send_email(rstrnt.email, f'Поступил заказ из Robofood № {new_order.id}', txt + tlg_link)
        return rstrnt.service_uid, txt, kbd

    def order_confirm_change_actions():
        action = call.data.split('_')[3]
        txt = 'Напишите во сколько хотите забрать Ваш заказ.'
        if action == 'phone':
            txt = 'Укажите номер телефона для самовывоза:'
        msg = BOT.send_message(chat_id=call.from_user.id, text=txt)
        BOT.register_next_step_handler(msg, order_takeaway_phone if action == 'phone' else order_takeaway_time)

    def order_takeaway_time(pair):
        usr = User.query.filter_by(uid=pair.chat.id).first()
        usr.address = pair.text
        db.session.commit()
        mesg = BOT.send_message(chat_id=pair.chat.id, text='Укажите номер телефона')
        BOT.register_next_step_handler(mesg, order_takeaway_phone)

    def order_takeaway_phone(pair):
        usr = User.query.filter_by(uid=pair.chat.id).first()
        usr.phone = pair.text
        db.session.commit()
        txt = f'Вы указали:\nАдрес доставки: {usr.address}\nКонтактный номер: {usr.phone}'
        kbd = IKM()
        kbd.add(IKB(text='Отправить', callback_data='order_confirm'))
        kbd.add(IKB(text='Изменить данные', callback_data='cart_confirm_change'))
        BOT.send_message(chat_id=pair.chat.id, text=txt, reply_markup=kbd)

    def order_triple_actions():
        order = Order.query.filter_by(id=int(data[1])).first()
        rest = Restaurant.query.filter_by(id=order.order_rest_id).first()
        details = OD.query.filter_by(order_id=order.id).all()
        user_id, txt, kbd = None, None, IKM()
        if data[2] == 'change':
            txt = f'Что хотите изменить в заказе № {order.id}?'
            for item in details:
                cb_txt = f'{item.order_dish_name}, {item.order_dish_quantity} шт.'
                kbd.row(IKB(text=cb_txt, callback_data='None'),
                        IKB(text='❌', callback_data=f'order_{order.id}_del_{item.id}'))
            kbd.add(IKB(text='Назад', callback_data=f'order_{order.id}_menu'))
            BOT.edit_message_text(text=txt, chat_id=rest.service_uid, message_id=call.message.id, reply_markup=kbd)
            txt, kbd = None, None
        elif data[2] == 'delivered':
            kbd = None
            order.order_state = 'Доставлен'
            db.session.commit()
            BOT.send_message(chat_id=order.uid, text='Доставка подтвеждена')
        elif data[2] == 'menu':
            user = User.query.filter_by(uid=order.uid).first()
            txt = f'Клиент согласен с изменением заказа № {order.id}\nСостав заказа:\n'
            txt += ''.join(f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n' for item in details)
            txt += f'Общая сумма заказа: {order.order_total} р.\nАдрес доставки: {user.address}'
            bt_text = "Принять и доставить "
            opts = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
            for i in opts:
                kbd.add(IKB(bt_text + opts[i], callback_data=f'order_{order.id}_accept_{30 * i}'))
            kbd.add(IKB(text='Не принят', callback_data='None')),
            kbd.add(IKB(f'Изменить заказ № {order.id}', callback_data=f'order_{order.id}_change'))
            user_id = rest.service_uid
        elif data[2] == 'send2user':
            BOT.send_message(text='Отправлен измененный заказ', chat_id=rest.service_uid)
            txt = f'<b>В связи с отсутствием одного из блюд, ресторан {rest.name} изменил Ваш заказ</b>\n'
            txt += 'Состав Вашего заказа:\n'
            txt += ''.join(f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n' for item in details)
            txt += f'На общую сумму - {order.order_total} р.'
            kbd.add(IKB(text='Оформить заказ', callback_data=f'order_{order.id}_user_confirm'))
            kbd.add(IKB(text='Изменить заказ', callback_data=f'order_{order.id}_user_change'))
            kbd.add(IKB(text='Отменить заказ', callback_data=f'order_{order.id}_user_cancel'))
            user_id = order.uid
        return user_id, txt, kbd

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
            kbd = IKM()
            bt_text = "Принять и доставить "
            opts = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
            for i in opts:
                kbd.add(IKB(bt_text + opts[i], callback_data=f'order_{order.id}_accept_{30 * i}_send'))
            kbd.add(IKB(text='Не принят', callback_data='None')),
            kbd.add(IKB(f'Изменить заказ № {order.id}', callback_data=f'order_{order.id}_change'))
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
            BOT.send_message(chat_id=rest.service_uid, text=txt)
            kbd = IKM()
            row = [IKB(text=f'{i}', callback_data=f'cart_item_id_{item.id}') for i, item in
                   enumerate(cart, start=1)]
            row.insert(0, IKB(text='❌', callback_data=f'cart_item_id_{cart[0].id}_clear'))
            kbd.row(*row)
            row = [
                IKB(text='-', callback_data=f'cart_id_{cart[0].id}_remove'),
                IKB(text=f'{cart[0].quantity} шт', callback_data='None'),
                IKB(text='+', callback_data=f'cart_id_{cart[0].id}_add')
            ]
            kbd.row(*row)
            row = [
                IKB(text='Очистить', callback_data=f'cart_purge'),
                IKB(text='Меню', callback_data=f'rest_{cart[0].restaurant_id}')
            ]
            kbd.row(*row)
            cb_text = f'Оформить заказ на сумму {order.order_total}'
            kbd.add(IKB(text=cb_text, callback_data='cart_confirm'))
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
                markup = rest_menu_keyboard(order.uid)
                txt = f'Ресторан {rest.name} отменил заказ. Пожалуйста, выберите ресторан:'
                if not markup.keyboard:
                    txt = f'Ресторан {rest.name} отменил заказ. В данное время нет работающих ресторанов'
                    markup = None
                BOT.send_message(chat_id=order.uid, text=txt, reply_markup=markup)
                order.order_state = 'Заказ отменен'
                db.session.commit()
                txt = 'Заказ отменен, клиенту направлено соответствующее сообщение'
                user_id = rest.service_uid
            else:
                txt = f'Что хотите изменить в заказе № {order.id}?'
                kbd = IKM()
                for item in details:
                    cb_txt = f'{item.order_dish_name}, {item.order_dish_quantity} шт.'
                    kbd.row(
                        IKB(text=cb_txt, callback_data='None'),
                        IKB(text='❌', callback_data=f'order_{order.id}_del_{item.id}')
                    )
                kbd.add(IKB(text='Отправить клиенту', callback_data=f'order_{order.id}_send2user'))
                kbd.add(IKB(text='Назад', callback_data=f'order_{order.id}_menu'))
                BOT.edit_message_text(text=txt, chat_id=rest.service_uid, message_id=call.message.id, reply_markup=kbd)
                txt, kbd = None, None
        return user_id, txt, kbd

    def order_quintuple_actions():
        order = Order.query.filter_by(id=int(data[1])).first()
        details = OD.query.filter_by(order_id=order.id).all()
        user_id, txt, kbd = None, None, None
        rest = Restaurant.query.filter_by(id=order.order_rest_id).first()
        total = db.session.query(func.sum(OD.order_dish_cost * OD.order_dish_quantity)).filter_by(
            order_id=order.id).all()
        total = total[0][0] if total[0][0] else 0
        if data[2] == 'confirm':
            kbd = IKM()
            user_id = rest.service_uid
            txt = f'Поступил заказ № {order.id}\nСостав заказа:\n'
            txt += ''.join(f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n' for item in details)
            txt += f'Общая сумма заказа: {total} р.\nСамовывоз, время {data[4]}'
            kbd.add(IKB(text='Принять', callback_data=f'order_{order.id}_accept_0_{data[4]}'))
            kbd.add(IKB(text='Отменить', callback_data=f'order_{order.id}_change'))
        elif data[2] == 'accept':
            time = int(data[3])
            pattern = r'(.[0-2][0-9]:[0-5][0-9](.*)[0-2][0-9]:[0-5][0-9])|' \
                      r'(.[а-яА-Я][a-яА-Я]-[а-яА-Я][a-яА-Я].[0-2][0-9]:[0-5][0-9](.*)[0-2][0-9]:[0-5][0-9])'
            rest_name = re.sub(pattern, '', rest.name)
            answers = {30: f'{time} минут', 60: '1 часа', 90: '1 часа и 30 минут'}
            default = f'{time // 60} часов'
            time_txt = answers.get(time, default)
            user_id = rest.service_uid
            if time != 0:
                txt = f'Ресторан {rest_name} принял ваш заказ № {order.id} и доставит в течении '
                BOT.send_message(chat_id=order.uid, text=txt + time_txt)
                kbd = IKM()
                cb_text = 'Принять и доставить '
                cb_data = f'order_{order.id}_accept'
                opts = {1: 'за 30 минут', 2: 'за 1 час', 3: 'за 1 час и 30 минут', 4: 'за 2 часа', 6: 'за 3 часа'}
                for i in opts:
                    kbd.add(IKB(cb_text + opts[i], callback_data=f'{cb_data}_{30 * i}'))
                cb_data = f'order_{order.id}_change'
                kbd.add(IKB(text=f'Принят на доставку в течении {time_txt}', callback_data='None'))
                kbd.add(IKB(text=f'Изменить заказ № {order.id}', callback_data=cb_data))
            state = 'самовывоз' if time == 0 else 'доставка'
            order.order_state = 'Заказ принят рестораном, ' + state
            order.order_state += txt[53:] + time_txt if time != 0 else ''
            client = User.query.filter_by(uid=order.uid).first()
            txt = f'Поступил заказ № {order.id}\nСостав заказа:\n'
            txt += ''.join(f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n' for item in details)
            txt += f'Общая сумма заказа: {order.order_total} р.\n'
            txt += f'Адрес доставки: {client.address}' if time != 0 else f'Самовывоз, {time_txt}'
            BOT.edit_message_text(text=txt, chat_id=user_id, message_id=call.message.id, reply_markup=kbd)
            txt = f'Мы оповестили клиента, что Вы приняли заказ № {order.id}'
            txt += f', доставка в течении {time_txt} на адрес: {client.address}\n' if time != 0 else f'\nСамовывоз, {time_txt}'
            txt += f'Контактный номер: {client.phone}'
            kbd = None
            db.session.commit()

        return user_id, txt, kbd

    actions = {
        2: order_confirm, 3: order_triple_actions, 4: order_quadruple_actions,
        5: order_quintuple_actions, 6: order_confirm_change_actions
    }
    uid, text, keyboard = actions.get(len(data))()
    BOT.send_message(chat_id=uid, text=text, reply_markup=keyboard, parse_mode='HTML')
    write_history(call.message.id, call.from_user.id, text, True)


def favorites_callback(call):
    data, txt = call.data.split('_'), ''
    rest_id, dish_id = int(data[3]) if data[2] == 'rest' else int(data[2]), int(data[3])
    favs = Favorites.query.filter_by(uid=int(data[1]), rest_id=rest_id).all()
    if data[2] != 'rest':
        txt = 'Блюдо удалено из избранного'
        if Favorites.query.filter_by(uid=int(data[1]), dish_id=dish_id).first():
            Favorites.query.filter_by(uid=call.from_user.id, dish_id=dish_id).delete()
        else:
            db.session.add(Favorites(uid=call.from_user.id, dish_id=dish_id, rest_id=rest_id))
            txt = 'Блюдо добавлено в избранное'
        db.session.commit()
        BOT.answer_callback_query(callback_query_id=call.id, show_alert=False, text=txt)
    else:
        for item in favs:
            kbd = IKM()
            dish = Dish.query.filter_by(id=item.dish_id).first()
            rest = Restaurant.query.filter_by(id=item.rest_id).first()
            txt = f'{rest.name}\n<a href="{dish.img_link}">.</a>\n<b>{dish.name}</b>\n{dish.composition}\n{dish.cost} р.'
            cart = Cart.query.filter_by(user_uid=call.from_user.id, dish_id=item.dish_id, restaurant_id=rest_id).first()
            quantity = cart.quantity if cart else 0
            category_id = Category.query.filter_by(name=dish.category).first().id
            fav_callback = f'fav_{call.from_user.id}_{rest_id}_{item.dish_id}'
            change_callback = f'rest_{rest_id}_cat_{category_id}_dish_{item.dish_id}'
            kbd.row(
                IKB(text='⭐️', callback_data=fav_callback),
                IKB(text='-', callback_data=f'{change_callback}_rem_{call.from_user.id}'),
                IKB(text=f'{quantity} шт', callback_data='None'),
                IKB(text='+', callback_data=f'{change_callback}_add_{call.from_user.id}')
            )
            # kbd.row(
            #     IKB('Инфо', web_app=WebAppInfo(BASE_URL + f"webapp_info/{rest.id}")),
            #     IKB('В меню ресторана', callback_data=f'rest_{rest_id}_menu')
            # )
            # total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(user_uid=call.from_user.id).all()
            # total = total[0][0] if total[0][0] else 0
            # kbd.add(IKB(text=f'В корзину: заказ на сумму {total} р', callback_data='cart_confirm'))
            BOT.send_message(chat_id=call.from_user.id, text=txt, parse_mode='HTML', reply_markup=kbd)


def other_callback(call):
    def back_to_rest(data):
        text = 'Пожалуйста, выберите ресторан:'
        BOT.edit_message_text(
            chat_id=data.from_user.id,
            message_id=data.message.message_id,
            text=text,
            reply_markup=rest_menu_keyboard(data.from_user.id)
        )

    def back_to_rest_promo(data):
        keyboard = IKM()
        promo_dish = PromoDish.query.first()
        text = f'<a href="{promo_dish.img_link}">.</a>'
        cb_data = f'rest_{promo_dish.rest_id}_from_promo'
        keyboard.add(IKB(text='Меню ресторана', callback_data=cb_data))
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

    def other(data):
        callback = data.data.split('_')
        uid, text, kbd = data.from_user.id, None, None
        if callback[0] == 'subcat':
            subcat_id = int(callback[2])
            query = db.session.query(
                Restaurant.id, Restaurant.name, Dish.name, Dish.composition, Dish.cost, Dish.img_link, Dish.id,
                SpecialDish.category_id, Restaurant.address).filter(SpecialDish.subcat_id == subcat_id,
                                                SpecialDish.rest_id == Restaurant.id,
                                                SpecialDish.dish_id == Dish.id).all()
            for item in query:
                rest_info = RestaurantInfo.query.filter_by(rest_id=item[0]).first()
                delivery_time = rest_info.delivery_time if rest_info else 'с ожиданием'
                takeaway_address = rest_info.takeaway_address if rest_info else item[8]
                kbd = IKM()
                text = f'<b>{item[1]}</b>\nДоставка - {delivery_time}\nСамовывоз - {takeaway_address}\n\n'
                text += f'{item[2]}\n{item[3]}\n{item[4]} р.\n<a href="{item[5]}">.</a>\n'
                cart = Cart.query.filter_by(user_uid=uid, dish_id=item[6]).first()
                quantity = cart.quantity if cart else 0
                fav_callback = f'fav_{uid}_{item[0]}_{item[6]}'
                change_callback = f'rest_{item[0]}_cat_{item[7]}_dish_{item[6]}'
                kbd.row(
                    IKB(text='⭐️', callback_data=fav_callback),
                    IKB(text='-', callback_data=f'{change_callback}_rem_{uid}'),
                    IKB(text=f'{quantity} шт', callback_data='None'),
                    IKB(text='+', callback_data=f'{change_callback}_add_{uid}')
                )
                # total = db.session.query(func.sum(Cart.price * Cart.quantity)).filter_by(
                #     user_uid=call.from_user.id).all()
                # total = total[0][0] if total[0][0] else 0
                # kbd.add(IKB(text=f'В корзину: заказ на сумму {total} р', callback_data='cart'))
                msg = BOT.send_message(chat_id=uid, text=text, parse_mode='HTML' if kbd else None, reply_markup=kbd)
                txt_menu = TextMenuMessage(
                    user_id=uid, message_id=msg.id, rest_id=item[0], text=text, img=item[5],
                    category_id=item[7], dish_id=item[6], quantity=quantity
                )
                db.session.add(txt_menu)
                db.session.commit()
            return 'Ok', 200
        elif callback[0] == 'user':
            order = Order.query.filter_by(uid=uid).order_by(Order.id.desc()).first()
            text = 'У Вас пока нет оформленных заказов.'
            if order:
                details = OD.query.filter_by(order_id=order.id).all()
                rest = Restaurant.query.filter_by(id=order.order_rest_id).first()
                date = datetime.fromtimestamp(order.order_datetime).strftime('%H:%M %d.%m.%Y')
                text = f'Заказ № {order.id} от {date}\nСтатус: {order.order_state}\n'
                if order.order_state != 'Заказ отменен':
                    text += 'Состав заказа:\n'
                    text += ''.join(f'{item.order_dish_name} - {item.order_dish_quantity} шт.\n' for item in details)
                    text += f'Сумма - {order.order_total} р.\n\n'
                text += f'Ресторан: {rest.name}\nАдрес: {rest.address}\nНомер телефона: {rest.contact}'
        elif callback[1] == 'contract':
            text = 'https://telegra.ph/Polzovatelskoe-soglashenie-12-07-5'
        elif callback[1] == 'rules':
            text = RULES
        BOT.send_message(chat_id=uid, text=text, parse_mode='HTML' if kbd else None, reply_markup=kbd)

    options = {
        'back_to_rest_kb': back_to_rest,
        'back_to_rest_promo': back_to_rest_promo,
        'purge': cart_purge,
        'to_rest': None
    }

    options.get(call.data, other)(call)
