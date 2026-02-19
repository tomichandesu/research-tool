import json, time
data = json.loads(open('/app/config/auth/1688_storage.json').read())
now = time.time()
for c in data.get('cookies', []):
    domain = c.get('domain', '')
    name = c.get('name', '')
    if '.1688.com' not in domain:
        continue
    if name not in ('cookie2', 'csg'):
        continue
    exp = c.get('expires', -1)
    if exp > 0:
        remaining_h = (exp - now) / 3600
        status = 'OK' if remaining_h > 0 else 'EXPIRED'
        print(f"{name}: {status} (remaining: {remaining_h:.1f}h)")
    else:
        print(f"{name}: session cookie (no expiry)")
