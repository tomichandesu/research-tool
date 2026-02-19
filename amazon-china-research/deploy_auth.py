"""Transfer 1688 auth data to VPS container."""
import paramiko
import os

HOST = "220.158.17.127"
USER = "root"
PASSWORD = "tomidokoro"
CONTAINER = "194590d42e07"

LOCAL_AUTH = os.path.join(os.path.dirname(__file__), "config", "auth", "1688_storage.json")
REMOTE_TMP = "/tmp/1688_storage.json"
CONTAINER_PATH = "/app/config/auth/1688_storage.json"

if not os.path.exists(LOCAL_AUTH):
    print("ERROR: 認証ファイルがありません。先にログインしてください。")
    exit(1)

print("1688認証データをVPSに転送中...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD)

sftp = ssh.open_sftp()
sftp.put(LOCAL_AUTH, REMOTE_TMP)
sftp.close()

# Ensure directory exists in container
ssh.exec_command(f"docker exec {CONTAINER} mkdir -p /app/config/auth")
stdin, stdout, stderr = ssh.exec_command(f"docker exec {CONTAINER} mkdir -p /app/config/auth")
stdout.channel.recv_exit_status()

# Copy into container
stdin, stdout, stderr = ssh.exec_command(f"docker cp {REMOTE_TMP} {CONTAINER}:{CONTAINER_PATH}")
exit_code = stdout.channel.recv_exit_status()

# Cleanup
ssh.exec_command(f"rm -f {REMOTE_TMP}")

ssh.close()

if exit_code == 0:
    print("転送完了！1688セッションが更新されました。")
else:
    err = stderr.read().decode().strip()
    print(f"ERROR: 転送失敗 - {err}")
    exit(1)
