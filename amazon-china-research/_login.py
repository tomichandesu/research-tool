"""1688ログインランチャー（非対話式）"""
import asyncio
import sys
sys.path.insert(0, ".")
from src.utils.auth import AuthManager

async def main():
    am = AuthManager()
    print("1688 ログイン画面を開きます...")
    print("ブラウザでQRコード/SMS/パスワードでログインしてください")
    print("5分以内にログインすると自動保存されます")
    result = await am.setup_login(timeout_minutes=5)
    if result:
        print("ログイン成功！セッション保存済み")
    else:
        print("ログイン失敗またはタイムアウト")

asyncio.run(main())
