"""Update all users' plan_expires_at to created_at + 6 months."""
import sqlite3
import os
from datetime import datetime

db_path = "/app/data/app.db"
if not os.path.exists(db_path):
    print(f"ERROR: DB not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# Show current state
print("=== BEFORE ===")
c.execute("SELECT id, email, plan_type, service_type, created_at, plan_expires_at FROM users")
rows = c.fetchall()
for r in rows:
    print(f"  ID={r[0]} | {r[1]} | plan={r[2]} | service={r[3]} | created={r[4]} | expires={r[5]}")

# Update each user: plan_expires_at = created_at + 6 months
print("\n=== Updating: plan_expires_at = created_at + 6 months ===")
c.execute("SELECT id, email, created_at FROM users")
users = c.fetchall()

for uid, email, created_str in users:
    # Parse created_at
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            created = datetime.strptime(created_str, fmt)
            break
        except ValueError:
            continue
    else:
        print(f"  SKIP ID={uid} - cannot parse created_at: {created_str}")
        continue

    # Add 6 months
    month = created.month + 6
    year = created.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(created.day, 28)  # safe day
    new_expiry = created.replace(year=year, month=month, day=day)
    new_expiry_str = new_expiry.strftime("%Y-%m-%d %H:%M:%S")

    c.execute("UPDATE users SET plan_expires_at = ? WHERE id = ?", (new_expiry_str, uid))
    print(f"  ID={uid} | {email} | created={created_str} -> expires={new_expiry_str}")

conn.commit()

# Show after state
print("\n=== AFTER ===")
c.execute("SELECT id, email, plan_type, service_type, created_at, plan_expires_at FROM users")
rows = c.fetchall()
for r in rows:
    print(f"  ID={r[0]} | {r[1]} | plan={r[2]} | service={r[3]} | created={r[4]} | expires={r[5]}")

conn.close()
print("\nDone!")
