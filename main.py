from app import manager, sched
import views
from utils import setup_logger

if __name__ == '__main__':
    setup_logger()
    # logging.basicConfig(filename='restobot.log', level=logging.DEBUG)
    sched.start()
    manager.run()
