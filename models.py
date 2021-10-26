from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db
from datetime import datetime


class Restaurant(db.Model):
    __tablename__ = 'restaurants'
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.Text(), nullable=False)
    address = db.Column(db.Text(), nullable=False)
    contact = db.Column(db.Text(), nullable=False)
    passwd = db.Column(db.Text())
    service_uid = db.Column(db.Integer())


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.Text(), nullable=False)
    restaurant_id = db.Column(db.Integer(), db.ForeignKey('restaurants.id'))


class Dish(db.Model):
    __tablename__ = 'dishes'
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.Text(), nullable=False)
    cost = db.Column(db.Integer(), nullable=False)
    composition = db.Column(db.Text(), nullable=False)
    img_link = db.Column(db.Text(), nullable=False)
    category = db.Column(db.Text(), db.ForeignKey('categories.name'))
    id_rest = db.Column(db.Integer(), db.ForeignKey('restaurants.id'))


class Cart(db.Model):
    __tablename__ = 'cart'
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.Text(), db.ForeignKey('dishes.name'))
    price = db.Column(db.Integer(), db.ForeignKey('dishes.cost'))
    quantity = db.Column(db.Integer(), nullable=False)
    user_uid = db.Column(db.Integer(), nullable=False)
    is_dish = db.Column(db.Integer(), nullable=False)
    is_water = db.Column(db.Integer(), nullable=False)
    dish_id = db.Column(db.Integer(), db.ForeignKey('dishes.id'))
    restaurant_id = db.Column(db.Integer(), db.ForeignKey('restaurants.id'))
    service_uid = db.Column(db.Integer(), db.ForeignKey('restaurants.service_uid'))


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer(), primary_key=True)
    uid = db.Column(db.Integer(), unique=True, nullable=False)
    first_name = db.Column(db.Text())
    last_name = db.Column(db.Text())
    username = db.Column(db.Text())
    address = db.Column(db.Text())
    phone = db.Column(db.Text())


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer(), primary_key=True)
    uid = db.Column(db.Integer(), db.ForeignKey('users.uid'))
    first_name = db.Column(db.Text(), db.ForeignKey('users.first_name'))
    last_name = db.Column(db.Text(), db.ForeignKey('users.last_name'))
    order_total = db.Column(db.Integer())
    order_rest_id = db.Column(db.Integer(), db.ForeignKey('restaurants.id'))
    order_datetime = db.Column(db.Integer())
    order_confirm = db.Column(db.Boolean(), default=False)
    order_state = db.Column(db.Text(), default='Собран')


class OrderDetail(db.Model):
    __tablename__ = 'details'
    id = db.Column(db.Integer(), primary_key=True)
    order_id = db.Column(db.Integer(), db.ForeignKey('orders.id'))
    order_dish_name = db.Column(db.Integer(), db.ForeignKey('dishes.name'))
    order_dish_cost = db.Column(db.Integer(), db.ForeignKey('dishes.cost'))
    order_dish_id = db.Column(db.Integer(), db.ForeignKey('dishes.id'))
    order_dish_quantity = db.Column(db.Integer())
    order_rest_id = db.Column(db.Integer(), db.ForeignKey('restaurants.id'))


class History(db.Model):
    __tablename__ = 'history'
    id = db.Column(db.Integer(), primary_key=True)
    message_id = db.Column(db.Integer())
    chat_id = db.Column(db.Integer())
    date = db.Column(db.Integer())
    type = db.Column(db.Text())
    message_text = db.Column(db.Text())
    is_bot = db.Column(db.Boolean())


class Admin(db.Model, UserMixin):
    __tablename__ = 'admins'
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(100))
    username = db.Column(db.String(50), nullable=False, unique=True)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(100), nullable=False)
    created_on = db.Column(db.DateTime(), default=datetime.now)
    updated_on = db.Column(db.DateTime(), default=datetime.now, onupdate=datetime.now)
    ownership = db.Column(db.String(100))

    @property
    def password(self):
        raise AttributeError('Пароль не читаем!')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)


class RestaurantDeliveryTerms(db.Model):
    __tablename__ = 'delivery_terms'
    id = db.Column(db.Integer(), primary_key=True)
    rest_id = db.Column(db.Integer(), nullable=False)
    terms = db.Column(db.Text())
    rest_inn = db.Column(db.Integer())
    rest_ogrn = db.Column(db.Integer())
    rest_fullname = db.Column(db.String())
    rest_address = db.Column(db.String())
