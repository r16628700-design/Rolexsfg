# RolexBomber 🔥

Premium Multi-Target SMS/Call/WhatsApp Bomber Telegram Bot

## Features
- 📡 115 APIs (SMS + Call + WhatsApp)
- 🎯 Multi-target attacks (2/5/10 concurrent per plan)
- 💳 Subscription plans with redeem codes
- 🔒 Force Channel Join system (admin set karta hai channel, users ko join karna padta hai)
- 🛡 Number protection
- 📢 Broadcast + Admin panel
- 🗄 SQLite storage (aiosqlite) - no MongoDB needed

## Plans
| Plan | Price | Concurrent | Max Duration |
|------|-------|-----------|--------------|
| Standard | ₹149 | 2 | 300 min |
| Premium | ₹249 | 5 | 720 min |
| Ultimate | ₹349 | 10 | 720 min |

## Setup (VPS)

```bash
# 1. Clone
git clone https://github.com/jiy326173-sketch/rolexbomber.git
cd rolexbomber

# 2. Python venv + deps
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. Edit token/owner in rolexbomber_bot.py (top section)
#    BOT_TOKEN, OWNER_ID, ADMIN_ID

# 4. Run
bash start_bot.sh
```

Bot runs on port 8080 (health check: `/health`).

## Owner/Admin
- Owner ID: 7812058540
- Admin panel: main menu mein "👑 Admin" button (sirf owner ko dikhta hai)
- Set Channel: Admin panel -> "📣 Set Channel (Force Join)" -> channel link bhejo
