import os
import json
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import logging
from concurrent.futures import ThreadPoolExecutor
from linebot import LineBotApi
from linebot.models import TextSendMessage

# ログ設定
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 環境変数の読み込み（LINEのトークン用）
load_dotenv()

# LINE BOT API 初期化
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

# ユーザー設定ファイル（各ユーザーの監視URL・間隔・監視状態など）
user_settings_path = "data/user_urls.json"

# LINE通知用にスレッドプールを準備（同期API対応のため）
executor = ThreadPoolExecutor()


# ユーザー設定をJSONファイルから読み込む
def load_settings():
    if not os.path.exists(user_settings_path):
        logger.warning("user_urls.json が見つかりません。")
        return {}
    try:
        with open(user_settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error("user_urls.json が一時的に壊れています。次回読み込みまで待機します。")
        return {}  # 空設定として安全にスキップ


# ユーザー設定をJSONファイルに保存する
def save_settings(settings):
    with open(user_settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


# 指定URLから最新商品タイトルとリンクを取得する
async def scrape_latest_title(url, session):
    try:
        logger.info(f"{url} に対してスクレイピング開始")
        async with session.get(url, timeout=10) as response:
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')

            # href属性に/article-を含むaタグ一覧を取得（順番どおり）
            listings = soup.select('a[href*="/article-"]')

            if not listings:
                logger.warning(f"商品リンク取得失敗: 要素が見つかりません {url}")
                return None, None

            first_item = listings[0]
            img_tag = first_item.find('img')

            # タイトルは画像のalt属性から取得
            if img_tag and img_tag.has_attr('alt'):
                title = img_tag['alt'].strip()
            else:
                title = "(タイトル不明)"

            # リンク取得
            link = first_item.get("href")
            if not link.startswith("http"):
                link = "https://jmty.jp" + link

            # デバッグログ出力
            logger.debug(f"取得したリンク要素のHTML: {str(first_item)}")
            logger.debug(f"取得したタイトル: {repr(title)}")
            logger.debug(f"取得したリンク: {repr(link)}")
            logger.info(f"商品取得成功: {title}")

            return title, link

    except Exception as e:
        logger.error(f"スクレイピング失敗: {e}")
        return None, None


# LINE通知（同期APIをスレッド実行）
async def notify_line(user_id, message):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, line_bot_api.push_message, user_id, TextSendMessage(text=message))


# メイン監視ループ
async def monitor_user(user_id):
    logger.info(f"🎯 {user_id} 用監視タスクを起動")

    while True:
        settings = load_settings()
        config = settings.get(user_id)

        # active=False を検出したらタスク終了
        if not config or not config.get("active"):
            logger.info(f"{user_id} : 監視停止を検出 → タスクを終了します")
            return

        url = config.get("url")
        interval = config.get("interval", 1)
        last_title = config.get("last_title")

        async with aiohttp.ClientSession() as session:
            title, link = await scrape_latest_title(url, session)

        # 新着があればLINE通知
        if title and title != last_title:
            message = f"🆕新着投稿：{title}\n👉 {link}"
            await notify_line(user_id, message)
            config["last_title"] = title
            settings[user_id] = config
            save_settings(settings)
            logger.info(f"新着検出 → 通知送信：{title}")
        else:
            logger.info(f"{user_id} : 新着なし")

        # 次回監視までスリープ（ユーザーごとの監視間隔）
        await asyncio.sleep(interval * 60)


# メイン監視制御（ユーザーごとに独立タスク生成）
async def main():
    logger.info("🔄 Workerサービスを開始します...")
    tasks = []
    started_users = set()

    while True:
        settings = load_settings()

        for user_id, config in settings.items():
            # active=True のユーザーのみ起動し、未起動ユーザーなら監視タスクを開始
            if config.get("active") and user_id not in started_users:
                task = asyncio.create_task(monitor_user(user_id))
                tasks.append(task)
                started_users.add(user_id)
                logger.info(f"{user_id} : 監視タスク起動済み")

            # active=False のユーザーは監視タスク再起動を許可するため set から除外
            if not config.get("active") and user_id in started_users:
                started_users.remove(user_id)

        await asyncio.sleep(60)  # 新規ユーザー追加監視


if __name__ == "__main__":
    asyncio.run(main())
