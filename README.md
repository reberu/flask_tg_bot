# flask_tg_bot
Telegram bot based on standard python-telegram-api and Flask + Sqlite as backend.
Ngrok is used as an external utility to test telegram webhook.
Flask listens POST and GET requests.

The main idea of this project is one message operations. 
When you start interacting with the bot, you will receive a message from the bot with an interactive menu.
The bot message will change depending on the selected menu item.
In the case of a choice of dishes, you don't have to scroll through a bunch of messages with images of dishes!
The highlight of this project is the carousel restaurant menu in the bot message.
Finally, your chat history will be minimal.

Telegram bot works with webhook. To set up webhook you should call https://api.telegram.org/bot<token>/setwebhook?url=<yoururl>.
For local testing you can use NGROK to obtain public URL (https://ngrok.com).
  
  
After you setted up webhook run main.py with runserver parameter:
  - python3 main.py runserver
