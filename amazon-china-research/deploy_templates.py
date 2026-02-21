import paramiko
import os
import time

HOST = "220.158.17.127"
USER = "root"
PASSWORD = "tomidokoro"
CONTAINER = "194590d42e07"

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
    ("web/templates/admin/reference_sellers.html", "/app/web/templates/admin/reference_sellers.html"),
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
    ("web/services/ai_keyword_service.py", "/app/web/services/ai_keyword_service.py"),
    ("web/services/alibaba_login.py", "/app/web/services/alibaba_login.py"),
    ("web/services/job_queue.py", "/app/web/services/job_queue.py"),
    ("web/services/seller_scraper.py", "/app/web/services/seller_scraper.py"),
    ("src/modules/matcher/dino.py", "/app/src/modules/matcher/dino.py"),
    ("src/modules/matcher/smart.py", "/app/src/modules/matcher/smart.py"),
    ("src/modules/alibaba/image_search.py", "/app/src/modules/alibaba/image_search.py"),
    ("src/modules/amazon/auto_researcher.py", "/app/src/modules/amazon/auto_researcher.py"),
    ("src/models/result.py", "/app/src/models/result.py"),
    ("src/output/html_report.py", "/app/src/output/html_report.py"),
    ("src/output/session_report.py", "/app/src/output/session_report.py"),
    ("src/config.py", "/app/src/config.py"),
    ("run_research.py", "/app/run_research.py"),
    ("web/database.py", "/app/web/database.py"),
    ("web/static/css/style.css", "/app/web/static/css/style.css"),
    ("web/static/data/amazon_categories.json", "/app/web/static/data/amazon_categories.json"),
    ("web_requirements.txt", "/app/web_requirements.txt"),
    ("run_web.py", "/app/run_web.py"),
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
    f"{REMOTE_TMP}/web/services "
    f"{REMOTE_TMP}/web/static/css "
    f"{REMOTE_TMP}/web/static/data "
    f"{REMOTE_TMP}/src/modules/matcher "
    f"{REMOTE_TMP}/src/modules/alibaba "
    f"{REMOTE_TMP}/src/modules/amazon "
    f"{REMOTE_TMP}/src/models "
    f"{REMOTE_TMP}/src/output"
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
    "/app/web/static/css",
    "/app/web/static/data",
    "/app/src/modules/matcher",
    "/app/src/modules/alibaba",
    "/app/src/modules/amazon",
    "/app/src/models",
    "/app/src/output",
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

# Install required packages in container
for pkg_name, pkg_import, pkg_spec in [
    ("openai", "openai", "openai>=1.30.0"),
    ("httpx", "httpx", "httpx>=0.27.0"),
    ("beautifulsoup4", "bs4", "beautifulsoup4>=4.12.0"),
    ("torch", "torch", "torch"),
    ("torchvision", "torchvision", "torchvision"),
]:
    print(f"\nChecking {pkg_name} package...")
    stdin, stdout, stderr = ssh.exec_command(
        f"docker exec {CONTAINER} python -c \"import {pkg_import}; print(getattr({pkg_import}, '__version__', 'ok'))\""
    )
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        print(f"  Installing {pkg_name}...")
        stdin, stdout, stderr = ssh.exec_command(
            f"docker exec {CONTAINER} pip install '{pkg_spec}'"
        )
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print(f"  {pkg_name} installed OK")
        else:
            err = stderr.read().decode().strip()
            print(f"  {pkg_name} install error: {err}")
    else:
        ver = stdout.read().decode().strip()
        print(f"  {pkg_name} already installed: v{ver}")

# Restart the container entirely.
# pkill/ps are not available inside the minimal container image,
# so use `docker restart` from the host instead.
print("\nRestarting container (docker restart)...")
print("  Note: Any running research jobs will auto-retry after restart.")
stdin, stdout, stderr = ssh.exec_command(f"docker restart {CONTAINER}")
exit_code = stdout.channel.recv_exit_status()
if exit_code == 0:
    print("  Container restarted successfully.")
else:
    err = stderr.read().decode().strip()
    print(f"  WARNING: docker restart failed (exit {exit_code}): {err}")
time.sleep(8)

# Verify container is running
print("Verifying container status...")
stdin, stdout, stderr = ssh.exec_command(f"docker logs {CONTAINER} --tail 3")
log_tail = stdout.read().decode().strip()
print(f"  Last log lines:\n  {log_tail}")

# Clean up temp
print("Cleaning up temp files...")
stdin, stdout, stderr = ssh.exec_command(f"rm -rf {REMOTE_TMP}")
stdout.channel.recv_exit_status()

sftp.close()
ssh.close()

print("=" * 60)
print("Deploy complete!")
print("  Running jobs will auto-retry after server restart.")
print("=" * 60)
