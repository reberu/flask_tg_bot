from flask import Flask
from flask_script import Manager
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from settings import Config
from apscheduler.schedulers.background import BackgroundScheduler


app = Flask(__name__)
app.config.from_object(Config)

manager = Manager(app)
db = SQLAlchemy(app)
sched = BackgroundScheduler()
login_manager = LoginManager(app)
login_manager.login_view = 'login'
