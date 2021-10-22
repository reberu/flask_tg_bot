from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, SubmitField, BooleanField, PasswordField, IntegerField, HiddenField, widgets, \
    SelectField
from wtforms.validators import DataRequired
from app import db
from models import *


class LoginForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired()])
    password = PasswordField("Пароль", validators=[DataRequired()])
    remember = BooleanField("Запомнить меня")
    login_submit = SubmitField("Войти")


class DishForm(FlaskForm):
    name = StringField("Наименование", validators=[DataRequired()])
    cost = IntegerField("Стоимость", validators=[DataRequired()])
    composition = StringField("Состав", validators=[DataRequired()])
    img_file = FileField("Загрузите изображение", validators=[DataRequired()])
    category = StringField("Категория", validators=[DataRequired()])
    id_rest = IntegerField("Идентификатор ресторана", validators=[DataRequired()])
    dish_add_submit = SubmitField("Добавить")

    def __init__(self, *args, **kwargs):
        hide_id = kwargs.pop('hide_rest')
        super(DishForm, self).__init__(*args, **kwargs)
        if hide_id:
            self.id_rest.widget = widgets.HiddenInput()


class CategoryForm(FlaskForm):
    name = StringField("Наименование", validators=[DataRequired()])
    restaurant_id = IntegerField("Идентификатор ресторана", validators=[DataRequired()])
    category_add_submit = SubmitField("Добавить")

    def __init__(self, *args, **kwargs):
        hide_id = kwargs.pop('hide_rest_id')
        super(CategoryForm, self).__init__(*args, **kwargs)
        if hide_id:
            self.restaurant_id.widget = widgets.HiddenInput()


class DishDeleteForm(FlaskForm):
    delete_id = HiddenField("Hidden dish id")
    dish_delete_submit = SubmitField("Удалить")


class RestaurantForm(FlaskForm):
    name = StringField("Название", validators=[DataRequired()])
    address = StringField("Адрес", validators=[DataRequired()])
    contact = StringField("Контактный номер", validators=[DataRequired()])
    passwd = StringField("Кодовая фраза", validators=[DataRequired()])
    service_uid = HiddenField("Hidden uid field")
    rest_add_submit = SubmitField("Добавить")


class RestaurantEditForm(FlaskForm):
    id = HiddenField("Hidden restaurant id field")
    name = StringField("Название")
    address = StringField("Адрес")
    contact = StringField("Контактный номер")
    passwd = StringField("Кодовая фраза")
    rest_edit_submit = SubmitField("Отправить")


class RestaurantDeleteForm(FlaskForm):
    choices = [rest.name for rest in Restaurant.query.all()]
    name = SelectField("Название", choices=choices)
    rest_delete_submit = SubmitField("Удалить")


class CategoryDeleteForm(FlaskForm):
    choices = [choice.name for choice in db.session.query(Category).all()]
    name = SelectField("Название категории", choices=choices, validators=[DataRequired()])
    # name = StringField("Название категории", validators=[DataRequired()])
    restaurant_id = IntegerField("Идентификатор ресторана", validators=[DataRequired()])
    category_delete_submit = SubmitField("Удалить")

    def __init__(self, *args, **kwargs):
        hide_id = kwargs.pop('hide_rest_id')
        super(CategoryDeleteForm, self).__init__(*args, **kwargs)
        if hide_id:
            self.restaurant_id.widget = widgets.HiddenInput()


class AdminAddForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired()])
    passwd = StringField("Пароль", validators=[DataRequired()])
    email = StringField("Почта", validators=[DataRequired()])
    ownership = StringField("Наименование ресторана")
    admin_add_button = SubmitField("Создать")
