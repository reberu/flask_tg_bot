from app import db


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
    description = db.Column(db.Text(), nullable=False)
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
    uid = db.Column(db.Integer(), unique=True)
    first_name = db.Column(db.Text())
    last_name = db.Column(db.Text())
    address = db.Column(db.Text())
    phone = db.Column(db.Text())


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer(), primary_key=True)
    uid = db.Column(db.Integer(), db.ForeignKey('users.uid'))
    first_name = db.Column(db.Text(), db.ForeignKey('users.first_name'))
    last_name = db.Column(db.Text(), db.ForeignKey('users.last_name'))
    order_list = db.Column(db.Text())
    order_total = db.Column(db.Integer())
    order_rest_id = db.Column(db.Integer(), db.ForeignKey('restaurants.id'))
