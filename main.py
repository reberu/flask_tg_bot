from app import manager, sched
import views
import logging

logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.DEBUG)

if __name__ == '__main__':
    sched.start()
    manager.run()
