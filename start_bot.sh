#!/usr/bin/env bash
# RolexBomber start script - Hermes server (army server)
cd /root/workspace/rolexbomber
export BOT_TOKEN="8749399634:AAF02JeWdCj3v1MtD0AFX2bh1RFVx1j0klQ"
export OWNER_ID="7812058540"
export ADMIN_ID="7812058540"
export DB_PATH="/root/workspace/rolexbomber/rolexbomber.db"
export PORT="8080"

# Kill any old instance
pkill -f "rolexbomber_bot.py" 2>/dev/null
sleep 1

exec /root/workspace/.venv/bin/python -u rolexbomber_bot.py >> bot.log 2>&1
