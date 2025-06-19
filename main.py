# main.py
import os
import json
import time
import threading
import requests
from flask import Flask, request, abort
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 環境変数の読み込み
load_dotenv()
app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ユーザー設定保持用メモリ（永続化する場合はDB化）
user_settings = {}  # user_id: {"url": str, "interval": int, "last_title": str, "active": bool}

def load_user_settings():
    global user_settings
    try:
        with open("data/user_urls.json", "r", encoding="utf-8") as f:
            user_settings = json.load(f)
            print("[INFO] ユーザー設定を読み込みました。")
    except FileNotFoundError:
        print("[WARN] user_urls.json が見つかりませんでした。新規作成します。")
        user_settings = {}

def save_user_settings():
    try:
        with open("data/user_urls.json", "w", encoding="utf-8") as f:
            json.dump(user_settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] ユーザー設定の保存に失敗しました: {e}")

def scrape_latest_title(url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        listing = soup.select_one(".list_item .post-link")
        title = listing.text.strip() if listing else None
        link = "https://jmty.jp" + listing.get("href") if listing else None
        return title, link
    except Exception as e:
        print(f"[ERROR] scraping: {e}")
        return None, None

def monitor():
    while True:
        for user_id, settings in user_settings.items():
            if not settings.get("active"):
                continue
            url = settings.get("url")
            interval = settings.get("interval", 10)
            last_title = settings.get("last_title")
            title, link = scrape_latest_title(url)
            if title and title != last_title:
                message = f"🆕新着投稿：{title}\n👉 {link}"
                line_bot_api.push_message(user_id, TextSendMessage(text=message))
                settings["last_title"] = title
        time.sleep(60)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    if user_id not in user_settings:
        user_settings[user_id] = {"interval": 10, "active": False}

    if msg.startswith("seturl "):
        url = msg[7:].strip()
        user_settings[user_id]["url"] = url
        user_settings[user_id]["last_title"] = None
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✅ URLを設定しました。"))
        save_user_settings()

    elif msg.startswith("setinterval "):
        try:
            interval = int(msg[12:].strip())
            user_settings[user_id]["interval"] = interval
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ チェック間隔を{interval}分に設定しました。"))
            save_user_settings()
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠ 数字を指定してください（例：setinterval 15）"))

    elif msg == "start":
        user_settings[user_id]["active"] = True
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✅ 監視を開始しました。"))
        save_user_settings()

    elif msg == "stop":
        user_settings[user_id]["active"] = False
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⏹ 監視を停止しました。"))
        save_user_settings()

    elif msg == "status":
        setting = user_settings[user_id]
        msg = f"""📊 現在の設定:
🔗 URL: {setting.get('url', '未設定')}
⏱ 間隔: {setting.get('interval')}分
🟢 状態: {"稼働中" if setting.get("active") else "停止中"}"""
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

    elif msg == "help":
        help_text = (
            "📘 使用できるコマンド:\n"
            "・seturl [URL]：検索URLを設定\n"
            "・setinterval [分]：チェック間隔を設定\n"
            "・start / stop：監視の開始と停止\n"
            "・status：現在の設定を表示\n"
            "・help：このヘルプを表示"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=help_text))

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❓ コマンドが認識されませんでした。`help` と送ってみてください。"))

load_user_settings()
if __name__ == "__main__":
    threading.Thread(target=monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
