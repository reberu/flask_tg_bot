from flask import Flask
from flask_script import Manager
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from settings import Config
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(host, subject, text):
    smtp_server = "smtp.office365.com"
    user = "robofood1bot@outlook.com"
    pswd = "Gps888Rcb"
    port = 587
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = user
    msg['To'] = host
    msg.attach(MIMEText(text, 'plain'))
    try:
        with smtplib.SMTP(smtp_server, port) as server:
            server.starttls()
            server.login(user, pswd)
            server.send_message(msg)
            server.quit()
    except Exception as e:
        print('oops: ', e)


app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
manager = Manager(app)

sched = BackgroundScheduler()
login_manager = LoginManager(app)
login_manager.login_view = 'login'
