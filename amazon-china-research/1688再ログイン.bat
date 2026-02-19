@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   1688 再ログイン
echo ========================================
echo.
echo ブラウザが開きます。1688にログインしてください。
echo ログインが完了したら自動的に保存されます。
echo.

cd /d "%~dp0"

rem 古い認証データを削除（選択肢を聞かれないようにする）
if exist "config\auth\1688_storage.json" del "config\auth\1688_storage.json"

python run_research.py --login

echo.
if %errorlevel%==0 (
    echo ログイン成功！VPSに転送中...
    python deploy_auth.py
    echo.
    echo 完了！このウィンドウを閉じてOKです。
) else (
    echo ログインに失敗しました。もう一度お試しください。
)
pause
