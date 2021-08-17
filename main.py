import os
from app import app, manager, sched
import views
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.DEBUG)

if __name__ == '__main__':
    sched.start()
    manager.run()
