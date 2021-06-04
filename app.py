from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from settings import Config

# from flask_migrate import Migrate, MigrateCommand
# from flask_script import Manager

from flask_admin import Admin

from dishes.blueprint import dishes


app = Flask(__name__)
app.config.from_object(Config)

app.register_blueprint(dishes, url_prefix='/dishes')

admin = Admin(app)
