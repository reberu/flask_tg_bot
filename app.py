from flask import Flask
from flask_script import Manager
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from settings import Config
from apscheduler.schedulers.background import BackgroundScheduler
from flask_admin import Admin

from dishes.blueprint import dishes


app = Flask(__name__)
app.config.from_object(Config)

app.register_blueprint(dishes, url_prefix='/dishes')

manager = Manager(app)
db = SQLAlchemy(app)
sched = BackgroundScheduler()
# admin = Admin(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
