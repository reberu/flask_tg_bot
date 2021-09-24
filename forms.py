from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, SubmitField, BooleanField, PasswordField, IntegerField, HiddenField
from wtforms.validators import DataRequired


class LoginForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired()])
    password = PasswordField("Пароль", validators=[DataRequired()])
    remember = BooleanField("Запомнить меня")
    submit = SubmitField("Войти")


class DishForm(FlaskForm):
    name = StringField("Наименование", validators=[DataRequired()])
    cost = IntegerField("Стоимость", validators=[DataRequired()])
    composition = StringField("Состав", validators=[DataRequired()])
    img_file = FileField("Загрузите изображение", validators=[DataRequired()])
    category = StringField("Категория", validators=[DataRequired()])
    id_rest = HiddenField("Идентификатор ресторана")
    submit = SubmitField("Добавить")


class CategoryForm(FlaskForm):
    name = StringField("Наименование", validators=[DataRequired()])
    restaurant_id = HiddenField("Идентификатор ресторана")
    submit = SubmitField("Добавить")


class DeleteForm(FlaskForm):
    delete_id = HiddenField("Hidden dish id")
    delete = SubmitField("Delete")
