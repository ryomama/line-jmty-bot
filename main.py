import os
import json
import requests
from flask import Flask, request, abort
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction

# .env ファイル読み込み（存在しなくても動くように）
load_dotenv()

# 環境変数取得（未設定時も落ちない）
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "NOT_SET"
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET") or "NOT_SET"
ADMIN_USER_ID = os.getenv("LINE_ADMIN_USER_ID") or "NOT_SET"

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

app = Flask(__name__)
SETTINGS_PATH = "data/user_urls.json"
user_settings = {}

# 管理者にのみ通知を送る
def notify_admin(message):
    if not ADMIN_USER_ID:
        print("[WARN] 管理者LINE IDが設定されていないため通知をスキップします。")
        return
    try:
        line_bot_api.push_message(ADMIN_USER_ID, TextSendMessage(text=message))
        print("[INFO] 管理者に通知を送信しました。")
    except Exception as e:
        print(f"[ERROR] 管理者への通知に失敗: {e}")

def load_user_settings():
    global user_settings
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content == "":
                print("[WARN] user_urls.json が空ファイルです。初期化します。")
                user_settings = {}
                # LINE通知で警告
                notify_admin("⚠️監視システム異常：設定ファイルが空です。再設定してください。")
                return
            user_settings = json.loads(content)
            print("[INFO] ユーザー設定を読み込みました。")
    except FileNotFoundError:
        print("[WARN] user_urls.json が見つかりません。新規作成します。")
        user_settings = {}
    except json.JSONDecodeError:
        print("[ERROR] user_urls.json が破損しています。初期化します。")
        user_settings = {}
        # LINE通知で警告
        notify_admin("⚠️監視システム異常：設定ファイル破損。再設定が必要です。")

def save_user_settings():
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(user_settings, f, indent=2, ensure_ascii=False)
        print("[INFO] ユーザー設定を保存しました。")
        print(f"[DEBUG] 保存直後の設定内容: {json.dumps(user_settings, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"[ERROR] ユーザー設定の保存に失敗: {e}")

def scrape_latest_title(url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        listing = soup.select_one(".list_item .post-link")
        if not listing:
            return None
        return listing.text.strip()
    except Exception as e:
        print(f"[ERROR] スクレイピング失敗: {e}")
        return None

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[ERROR] Invalid signature. リクエスト拒否")
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    # 全角スペースも半角スペースに置換した後、split()で処理
    msg = msg.replace('\u3000', ' ')  # 全角スペース → 半角スペース
    tokens = msg.split()

    if user_id not in user_settings:
        user_settings[user_id] = {"url": "", "interval": 5, "last_title": "", "active": False}

    if msg == "ヘルプ":
        help_text = "\n".join([
            "コマンド一覧:",
            "セット [URL] - 監視対象のURLを設定",
            "時間 [分] - 監視間隔を設定",
            "開始 - 監視を開始",
            "終了 - 監視を停止",
            "確認 - 現在の設定確認",
            "ヘルプ - このコマンド一覧を表示"
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=help_text))
        return
    
    if msg == "間隔選択":
        quick_reply_buttons = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="1分", text="時間 1")),
            QuickReplyButton(action=MessageAction(label="5分", text="時間 5")),
            QuickReplyButton(action=MessageAction(label="10分", text="時間 10")),
            QuickReplyButton(action=MessageAction(label="15分", text="時間 15")),
            QuickReplyButton(action=MessageAction(label="30分", text="時間 30")),
        ])
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="監視間隔を選択してください。",
                quick_reply=quick_reply_buttons
            )
        )
        return

    if tokens[0] == "セット" and len(tokens) > 1:
        user_settings[user_id]["url"] = tokens[1]
        save_user_settings()
        reply = f"URLを設定しました：{tokens[1]}"

    elif tokens[0] == "時間" and len(tokens) > 1 and tokens[1].isdigit():
        interval = int(tokens[1])
        user_settings[user_id]["interval"] = interval
        save_user_settings()
        reply = f"監視間隔を{interval}分に設定しました。"

    elif msg == "開始":
        user_settings[user_id]["active"] = True
        save_user_settings()
        reply = "監視を開始しました。"

    elif msg == "終了":
        user_settings[user_id]["active"] = False
        save_user_settings()
        reply = "監視を停止しました。"

    elif msg == "確認":
        conf = user_settings[user_id]
        reply = (
            f"URL: {conf.get('url', '')}\n"
            f"間隔: {conf.get('interval', '')}分\n"
            f"監視状態: {'ON' if conf.get('active') else 'OFF'}"
        )
    else:
        reply = "無効なコマンドです。'ヘルプ' で使い方を確認してください。"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    load_user_settings()
    print("[INFO] Flaskサーバを起動します（ポート5000）")
    app.run(host="0.0.0.0", port=5000, debug=False)
