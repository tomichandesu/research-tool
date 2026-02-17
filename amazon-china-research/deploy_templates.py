import paramiko
import os
import time

HOST = "220.158.17.127"
USER = "root"
PASSWORD = "tomidokoro"
CONTAINER = "5efe943fa337"

LOCAL_BASE = r"C:\Users\tomic\OneDrive\dev\リサーチツール\amazon-china-research"
REMOTE_TMP = "/tmp/deploy_templates"

files = [
    ("web/templates/base.html", "/app/web/templates/base.html"),
    ("web/templates/dashboard.html", "/app/web/templates/dashboard.html"),
    ("web/templates/expired.html", "/app/web/templates/expired.html"),
    ("web/templates/research/detail.html", "/app/web/templates/research/detail.html"),
    ("web/templates/research/new.html", "/app/web/templates/research/new.html"),
    ("web/templates/research/history.html", "/app/web/templates/research/history.html"),
    ("web/templates/auth/login.html", "/app/web/templates/auth/login.html"),
    ("web/templates/auth/register.html", "/app/web/templates/auth/register.html"),
    ("web/templates/admin/jobs.html", "/app/web/templates/admin/jobs.html"),
    ("web/templates/admin/invites.html", "/app/web/templates/admin/invites.html"),
    ("web/templates/admin/login.html", "/app/web/templates/admin/login.html"),
    ("web/templates/admin/excluded_keywords.html", "/app/web/templates/admin/excluded_keywords.html"),
    ("web/templates/admin/dashboard.html", "/app/web/templates/admin/dashboard.html"),
    ("web/templates/admin/users.html", "/app/web/templates/admin/users.html"),
    ("web/templates/admin/user_detail.html", "/app/web/templates/admin/user_detail.html"),
    ("web/templates/billing/success.html", "/app/web/templates/billing/success.html"),
    ("web/templates/billing/request_consul_done.html", "/app/web/templates/billing/request_consul_done.html"),
    ("web/templates/account/settings.html", "/app/web/templates/account/settings.html"),
    ("web/templates/help.html", "/app/web/templates/help.html"),
    ("web/templates/keyword_guide.html", "/app/web/templates/keyword_guide.html"),
    ("web/templates/auth/forgot_password.html", "/app/web/templates/auth/forgot_password.html"),
    ("web/templates/auth/reset_password.html", "/app/web/templates/auth/reset_password.html"),
    ("web/app.py", "/app/web/app.py"),
    ("web/models.py", "/app/web/models.py"),
    ("web/config.py", "/app/web/config.py"),
    ("web/routes/account.py", "/app/web/routes/account.py"),
    ("web/routes/auth.py", "/app/web/routes/auth.py"),
    ("web/routes/research.py", "/app/web/routes/research.py"),
    ("web/routes/admin.py", "/app/web/routes/admin.py"),
    ("web/routes/billing.py", "/app/web/routes/billing.py"),
    ("web/routes/dashboard.py", "/app/web/routes/dashboard.py"),
    ("web/services/email_service.py", "/app/web/services/email_service.py"),
    ("web/services/job_runner.py", "/app/web/services/job_runner.py"),
    ("web/services/stripe_service.py", "/app/web/services/stripe_service.py"),
    ("web/services/usage_tracker.py", "/app/web/services/usage_tracker.py"),
    ("web/services/user_service.py", "/app/web/services/user_service.py"),
    (".env", "/app/.env"),
]

print("=" * 60)
print("Deploy to VPS - Templates & Python files")
print("=" * 60)

# Connect
print(f"\nConnecting to {HOST}...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD)
print("Connected!")

sftp = ssh.open_sftp()

# Create temp directory structure
print("\nCreating temp directories on VPS...")
mkdir_cmd = (
    f"mkdir -p {REMOTE_TMP}/web/templates/research "
    f"{REMOTE_TMP}/web/templates/auth "
    f"{REMOTE_TMP}/web/templates/admin "
    f"{REMOTE_TMP}/web/templates/billing "
    f"{REMOTE_TMP}/web/templates/account "
    f"{REMOTE_TMP}/web/routes "
    f"{REMOTE_TMP}/web/services"
)
stdin, stdout, stderr = ssh.exec_command(mkdir_cmd)
stdout.channel.recv_exit_status()
print("Done.")

# Also ensure container directories exist
print("Ensuring container directories exist...")
container_dirs = [
    "/app/web/templates/research",
    "/app/web/templates/auth",
    "/app/web/templates/admin",
    "/app/web/templates/billing",
    "/app/web/templates/account",
    "/app/web/routes",
    "/app/web/services",
]
for d in container_dirs:
    cmd = f"docker exec {CONTAINER} mkdir -p {d}"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    stdout.channel.recv_exit_status()
print("Done.")

# Upload and deploy each file
print("\n--- Uploading and deploying files ---\n")
success_count = 0
error_count = 0

for local_rel, container_path in files:
    local_path = os.path.join(LOCAL_BASE, local_rel)
    remote_tmp_path = f"{REMOTE_TMP}/{local_rel}"

    # Check local file exists
    if not os.path.exists(local_path):
        print(f"  SKIP (not found): {local_path}")
        error_count += 1
        continue

    print(f"  [{local_rel}]")
    try:
        # Upload to VPS temp
        sftp.put(local_path, remote_tmp_path)
        print(f"    SFTP upload OK")

        # docker cp into container
        cmd = f"docker cp {remote_tmp_path} {CONTAINER}:{container_path}"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            err = stderr.read().decode().strip()
            print(f"    ERROR (docker cp): {err}")
            error_count += 1
        else:
            print(f"    -> {container_path} OK")
            success_count += 1
    except Exception as e:
        print(f"    ERROR: {e}")
        error_count += 1

print(f"\n--- Results: {success_count} OK, {error_count} errors ---")

# Restart the web process inside container
print("\nRestarting web server...")
stdin, stdout, stderr = ssh.exec_command(
    f"docker exec {CONTAINER} pkill -f 'python.*run_web' || true"
)
stdout.channel.recv_exit_status()
time.sleep(3)

# Check processes
print("Checking processes in container...")
stdin, stdout, stderr = ssh.exec_command(f"docker exec {CONTAINER} ps aux")
ps_output = stdout.read().decode()
print(ps_output)

# Clean up temp
print("Cleaning up temp files...")
stdin, stdout, stderr = ssh.exec_command(f"rm -rf {REMOTE_TMP}")
stdout.channel.recv_exit_status()

sftp.close()
ssh.close()

print("=" * 60)
print("Deploy complete!")
print("=" * 60)
