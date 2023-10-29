from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, SubmitField, BooleanField, PasswordField, IntegerField, HiddenField, widgets, \
    SelectField, TextField
from wtforms.validators import DataRequired, Email, Regexp
from app import db
from models import *


class LoginForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired()])
    password = PasswordField("Пароль", validators=[DataRequired()])
    remember = BooleanField("Запомнить меня")
    login_submit = SubmitField("Войти")


class DishForm(FlaskForm):
    name = StringField("Наименование", validators=[DataRequired()])
    cost = IntegerField("Стоимость", default=0)
    composition = StringField("Состав", validators=[DataRequired()])
    img_file = FileField("Загрузите изображение", validators=[DataRequired()])
    category = StringField("Категория")
    id_rest = IntegerField("Идентификатор ресторана")
    dish_add_submit = SubmitField("Добавить")

    def __init__(self, *args, **kwargs):
        hide_id = kwargs.pop('hide_rest')
        super(DishForm, self).__init__(*args, **kwargs)
        if hide_id:
            self.id_rest.widget = widgets.HiddenInput()


class DishEditForm(FlaskForm):
    name = StringField("Наименование")
    cost = IntegerField("Стоимость")
    composition = StringField("Состав")
    img_file = FileField("Загрузите изображение")
    category = StringField("Категория")
    id_rest = IntegerField("Идентификатор ресторана")
    id_dish = IntegerField("Идентификатор блюда")
    dish_edit_submit = SubmitField("Изменить")


class SpecialDishForm(FlaskForm):
    rest_id = IntegerField('Ресторан')
    category_id = IntegerField('Категория')
    dish_id = IntegerField('Блюдо')
    subcat_id = IntegerField('Подкатегория')
    s_dish_add_submit = SubmitField("Добавить")


class SearchDishForm(FlaskForm):
    dish_id = IntegerField('Блюдо')
    rest_id = IntegerField('Ресторан')
    search_word_id = IntegerField('Идентификатор команды')
    search_dish_submit = SubmitField('Добавить')


class SearchDishDelForm(FlaskForm):
    search_dish_id = IntegerField('Блюдо')
    search_dish_del_submit = SubmitField('Удалить')


class SearchWordForm(FlaskForm):
    search_name = TextField('Название команды')
    search_word = TextField('Команда')
    search_word_submit = SubmitField('Добавить')


class SearchWordDelForm(FlaskForm):
    search_word = TextField('Команда')
    search_word_del_submit = SubmitField('Удалить')


class PromoDishForm(FlaskForm):
    img_file = FileField("Загрузите изображение", validators=[DataRequired()])
    rest_id = IntegerField('Ресторан')
    selected = BooleanField('Выбрать')
    promo_dish_submit = SubmitField('Добавить')


class PromoDishDeleteForm(FlaskForm):
    promo_dish_id = IntegerField('Hidden promo dish id')
    promo_rest_id = IntegerField('Hidden promo rest id')
    promo_dish_delete_submit = SubmitField("Удалить")


class CategoryForm(FlaskForm):
    name = StringField("Наименование", validators=[DataRequired()])
    restaurant_id = IntegerField("Идентификатор ресторана", id="id_cat_add_rest_id")
    category_add_submit = SubmitField("Добавить")

    def __init__(self, *args, **kwargs):
        hide_id = kwargs.pop('hide_rest_id')
        super(CategoryForm, self).__init__(*args, **kwargs)
        if hide_id:
            self.restaurant_id.widget = widgets.HiddenInput()


class SubcategoryForm(FlaskForm):
    name = StringField("Наименование", validators=[DataRequired()])
    category_id = IntegerField("Идентификатор ресторана", id="id_subcat_add_cat_id")
    subcategory_add_submit = SubmitField("Добавить")


class SubcategoryDeleteForm(FlaskForm):
    subcategory_id = IntegerField("Hidden subcategory id")
    subcategory_del_submit = SubmitField("Удалить")


class SpecialDishDeleteForm(FlaskForm):
    special_dish_id = IntegerField("Hidden special dish id")
    special_dish_delete_submit = SubmitField("Удалить")


class DishDeleteForm(FlaskForm):
    delete_id = HiddenField("Hidden dish id")
    dish_delete_submit = SubmitField("Удалить", id="id_dish_delete_submit")


class RestaurantForm(FlaskForm):
    name = StringField("Название", validators=[DataRequired()])
    address = StringField("Адрес", validators=[DataRequired()])
    contact = StringField("Контактный номер", validators=[DataRequired()])
    passwd = StringField("Кодовая фраза", validators=[DataRequired()])
    email = StringField("Электронная почта", validators=[Email()])
    service_uid = HiddenField("Hidden uid field")
    min_total = IntegerField("Минимальная сумма заказа")
    enabled = HiddenField("Hidden toggle field")
    rest_add_submit = SubmitField("Добавить")


class RestaurantEditForm(FlaskForm):
    id = HiddenField("Hidden restaurant id field")
    name = StringField("Название")
    address = StringField("Адрес")
    contact = StringField("Контактный номер")
    passwd = StringField("Кодовая фраза")
    email = StringField("Электронная почта", validators=[Email()])
    min_total = IntegerField("Минимальная сумма заказа")
    rest_edit_submit = SubmitField("Отправить", id="id_rest_edit_submit")


class RestaurantsEnableForm(FlaskForm):
    rest_id = HiddenField("Hidden restaurant id field")
    status = BooleanField()
    rest_enable_submit = SubmitField("Изменить")


class RestaurantDeleteForm(FlaskForm):
    choices = [rest.name for rest in Restaurant.query.all()]
    name = SelectField("Название", choices=choices)
    rest_delete_submit = SubmitField("Удалить")


class RestaurantInfoForm(FlaskForm):
    rest_id = HiddenField("Hidden restaurant id field")
    rest_img = FileField("Загрузите изображение")
    delivery_time = StringField("Время доставки")
    takeaway_address = StringField("Адрес самовывоза")
    rest_info_submit = SubmitField("Применить")


class CategoryDeleteForm(FlaskForm):
    choices = [''] + [choice.name for choice in db.session.query(Category).all()]
    name = SelectField("Название категории", choices=choices)
    restaurant_id = IntegerField("Идентификатор ресторана")
    category_delete_submit = SubmitField("Удалить")

    def __init__(self, *args, **kwargs):
        hide_id = kwargs.pop('hide_rest_id')
        super(CategoryDeleteForm, self).__init__(*args, **kwargs)
        if hide_id:
            self.restaurant_id.widget = widgets.HiddenInput()


class AdminAddForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired(), Regexp(r"^[a-zA-Z0-9_]*$")])
    passwd = StringField("Пароль", validators=[DataRequired()])
    email = StringField("Почта", validators=[DataRequired()])
    ownership = StringField("Наименование ресторана")
    admin_add_button = SubmitField("Создать")


class RestaurantDeliveryTermsForm(FlaskForm):
    rest_id = HiddenField("Hidden restaurant id field", validators=[DataRequired()])
    terms = TextField("Условия доставки")
    rest_inn = IntegerField("ИНН")
    rest_ogrn = IntegerField("ОГРН")
    rest_fullname = StringField("Название организации")
    rest_address = StringField("Адрес")
    delivery_terms_submit = SubmitField("Отправить")


class RestaurantDeliveryTermsEditForm(FlaskForm):
    rest_id = HiddenField("Hidden restaurant id field", validators=[DataRequired()])
    terms = TextField("Условия доставки")
    rest_inn = IntegerField("ИНН")
    rest_ogrn = IntegerField("ОГРН")
    rest_fullname = StringField("Название организации")
    rest_address = StringField("Адрес")
    terms_edit_submit = SubmitField("Изменить")


class DateForm(FlaskForm):
    date = StringField("Дата")
    date_submit = SubmitField("Показать")
