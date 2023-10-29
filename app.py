from flask import Flask
from flask_script import Manager
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from settings import Config, SMTP_USER, SMTP_PASSWORD
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(host, subject, body):
    smtp_server = "smtp.yandex.ru"
    imap_server = "imap.yandex.ru"
    port = 465
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = host
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    text = msg.as_string()
    try:
        smtp = smtplib.SMTP_SSL(host=smtp_server, port=port)
        smtp.ehlo(SMTP_USER)
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.auth_plain()
        smtp.sendmail(from_addr=SMTP_USER, to_addrs=host, msg=text)
        smtp.sendmail(from_addr=SMTP_USER, to_addrs=SMTP_USER, msg=text)
        smtp.quit()
    except Exception as e:
        print('oops: ', e)


app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
manager = Manager(app)

sched = BackgroundScheduler()
login_manager = LoginManager(app)
login_manager.login_view = 'login'
