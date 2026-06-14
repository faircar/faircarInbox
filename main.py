from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3
import httpx
import json
import hmac
import hashlib
import time
from datetime import datetime, timezone
import os

# ─── CONFIG (จาก environment variables) ───────────────────────────────────────
FB_TOKEN_FAIRCAR    = os.getenv("FB_TOKEN_FAIRCAR", "")
FB_TOKEN_ASAP       = os.getenv("FB_TOKEN_ASAP", "")
FB_APP_SECRET       = os.getenv("FB_APP_SECRET", "")
FB_VERIFY_TOKEN     = os.getenv("FB_VERIFY_TOKEN", "maew_inbox_2024")
FB_PAGE_ID_FAIRCAR  = os.getenv("FB_PAGE_ID_FAIRCAR", "100735478552467")
FB_PAGE_ID_ASAP     = os.getenv("FB_PAGE_ID_ASAP", "117865866278291")

LINE_SECRET_ASAP    = os.getenv("LINE_SECRET_ASAP", "")
LINE_TOKEN_ASAP     = os.getenv("LINE_TOKEN_ASAP", "")
LINE_SECRET_FAIRCAR = os.getenv("LINE_SECRET_FAIRCAR", "")
LINE_TOKEN_FAIRCAR  = os.getenv("LINE_TOKEN_FAIRCAR", "")

DB_PATH = "inbox.db"

# ─── DATABASE ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            platform_user_id TEXT NOT NULL,
            name TEXT DEFAULT 'ไม่ทราบชื่อ',
            avatar_url TEXT,
            phone TEXT,
            UNIQUE(platform, platform_user_id)
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            last_message TEXT,
            last_message_time TEXT,
            status TEXT DEFAULT 'pending',
            assigned_admin TEXT,
            unanswered_since TEXT,
            FOREIGN KEY(contact_id) REFERENCES contacts(id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            direction TEXT NOT NULL,
            content TEXT,
            message_type TEXT DEFAULT 'text',
            admin_name TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def upsert_contact(platform: str, uid: str, name: str = None, avatar: str = None) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO contacts (platform, platform_user_id, name, avatar_url) VALUES (?,?,?,?)",
        (platform, uid, name or "ไม่ทราบชื่อ", avatar)
    )
    if name:
        c.execute("UPDATE contacts SET name=? WHERE platform=? AND platform_user_id=?", (name, platform, uid))
    conn.commit()
    c.execute("SELECT id FROM contacts WHERE platform=? AND platform_user_id=?", (platform, uid))
    row = c.fetchone()
    conn.close()
    return row["id"]

def upsert_conversation(contact_id: int, platform: str, last_msg: str) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM conversations WHERE contact_id=? AND platform=?", (contact_id, platform))
    row = c.fetchone()
    ts = now_str()
    if row:
        conv_id = row["id"]
        c.execute(
            "UPDATE conversations SET last_message=?, last_message_time=?, status='pending', unanswered_since=? WHERE id=?",
            (last_msg, ts, ts, conv_id)
        )
    else:
        c.execute(
            "INSERT INTO conversations (contact_id, platform, last_message, last_message_time, unanswered_since) VALUES (?,?,?,?,?)",
            (contact_id, platform, last_msg, ts, ts)
        )
        conv_id = c.lastrowid
    conn.commit()
    conn.close()
    return conv_id

def save_message(conv_id: int, direction: str, content: str, msg_type: str = "text", admin: str = None):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (conversation_id, direction, content, message_type, admin_name, timestamp) VALUES (?,?,?,?,?,?)",
        (conv_id, direction, content, msg_type, admin, now_str())
    )
    conn.commit()
    conn.close()

def get_fb_token(page_id: str) -> str:
    if page_id == FB_PAGE_ID_FAIRCAR:
        return FB_TOKEN_FAIRCAR
    if page_id == FB_PAGE_ID_ASAP:
        return FB_TOKEN_ASAP
    return ""

def platform_label(platform: str) -> str:
    labels = {
        "facebook_faircar": "FB Faircar",
        "facebook_asap": "FB Asap",
        "line_asap": "LINE OA Asap",
        "line_faircar": "LINE OA Faircar",
        "instagram_faircar": "IG Faircar",
    }
    return labels.get(platform, platform)

# ─── FASTAPI ──────────────────────────────────────────────────────────────────
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

# ─── API: GET CONVERSATIONS ───────────────────────────────────────────────────
@app.get("/api/conversations")
async def get_conversations(platform: str = "all"):
    conn = get_db()
    c = conn.cursor()
    if platform == "all":
        c.execute("""
            SELECT cv.id, cv.platform, cv.last_message, cv.last_message_time,
                   cv.status, cv.assigned_admin, cv.unanswered_since,
                   ct.name, ct.avatar_url, ct.phone
            FROM conversations cv
            JOIN contacts ct ON ct.id = cv.contact_id
            ORDER BY cv.last_message_time DESC
        """)
    else:
        c.execute("""
            SELECT cv.id, cv.platform, cv.last_message, cv.last_message_time,
                   cv.status, cv.assigned_admin, cv.unanswered_since,
                   ct.name, ct.avatar_url, ct.phone
            FROM conversations cv
            JOIN contacts ct ON ct.id = cv.contact_id
            WHERE cv.platform = ?
            ORDER BY cv.last_message_time DESC
        """, (platform,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

# ─── API: GET MESSAGES ────────────────────────────────────────────────────────
@app.get("/api/conversations/{conv_id}/messages")
async def get_messages(conv_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY timestamp ASC", (conv_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

# ─── API: SEND MESSAGE ────────────────────────────────────────────────────────
class ReplyBody(BaseModel):
    admin_name: str
    content: str
    message_type: str = "text"

@app.post("/api/conversations/{conv_id}/reply")
async def send_reply(conv_id: int, body: ReplyBody):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT cv.platform, ct.platform_user_id
        FROM conversations cv
        JOIN contacts ct ON ct.id = cv.contact_id
        WHERE cv.id = ?
    """, (conv_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")

    platform = row["platform"]
    uid = row["platform_user_id"]

    # ส่งข้อความจริง
    success = False
    if platform.startswith("facebook") or platform.startswith("instagram"):
        page_id = FB_PAGE_ID_FAIRCAR if "faircar" in platform else FB_PAGE_ID_ASAP
        token = get_fb_token(page_id)
        success = await send_fb_message(uid, body.content, token)
    elif platform.startswith("line"):
        channel = "asap" if "asap" in platform else "faircar"
        success = await send_line_message(uid, body.content, channel)

    if success:
        save_message(conv_id, "outgoing", body.content, body.message_type, body.admin_name)
        # อัพเดต status เป็น answered
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "UPDATE conversations SET status='answered', assigned_admin=?, unanswered_since=NULL WHERE id=?",
            (body.admin_name, conv_id)
        )
        conn.commit()
        conn.close()
        return {"ok": True}
    else:
        raise HTTPException(status_code=500, detail="ส่งข้อความไม่สำเร็จ")

# ─── SEND FB MESSAGE ──────────────────────────────────────────────────────────
async def send_fb_message(recipient_id: str, text: str, token: str) -> bool:
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload)
        return r.status_code == 200

# ─── SEND LINE MESSAGE ────────────────────────────────────────────────────────
async def send_line_message(user_id: str, text: str, channel: str) -> bool:
    token = LINE_TOKEN_ASAP if channel == "asap" else LINE_TOKEN_FAIRCAR
    url = "https://api.line.me/v2/bot/message/push"
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}]
    }
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=headers)
        return r.status_code == 200

# ─── WEBHOOK: FACEBOOK VERIFY ────────────────────────────────────────────────
@app.get("/webhook/facebook")
async def fb_verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == FB_VERIFY_TOKEN:
        return int(params.get("hub.challenge", 0))
    raise HTTPException(status_code=403, detail="Verify token ไม่ถูกต้อง")

# ─── WEBHOOK: FACEBOOK RECEIVE ───────────────────────────────────────────────
@app.post("/webhook/facebook")
async def fb_receive(request: Request):
    body = await request.json()
    for entry in body.get("entry", []):
        page_id = entry.get("id", "")
        platform_suffix = "faircar" if page_id == FB_PAGE_ID_FAIRCAR else "asap"
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id", "")
            if sender_id == page_id:
                continue  # ข้ามข้อความของเราเอง
            msg = event.get("message", {})
            text = msg.get("text", "")
            attachments = msg.get("attachments", [])
            if not text and not attachments:
                continue

            # ดึงชื่อผู้ส่ง
            name = await get_fb_user_name(sender_id, get_fb_token(page_id))
            platform = f"facebook_{platform_suffix}"
            contact_id = upsert_contact(platform, sender_id, name)
            content = text if text else "[รูปภาพ/ไฟล์แนบ]"
            conv_id = upsert_conversation(contact_id, platform, content)
            save_message(conv_id, "incoming", content)

    return {"status": "ok"}

async def get_fb_user_name(user_id: str, token: str) -> str:
    try:
        url = f"https://graph.facebook.com/{user_id}?fields=name&access_token={token}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.json().get("name", "ไม่ทราบชื่อ")
    except:
        pass
    return "ไม่ทราบชื่อ"

# ─── WEBHOOK: LINE ────────────────────────────────────────────────────────────
@app.post("/webhook/line/{channel}")
async def line_receive(channel: str, request: Request):
    if channel not in ("asap", "faircar"):
        raise HTTPException(status_code=404)

    secret = LINE_SECRET_ASAP if channel == "asap" else LINE_SECRET_FAIRCAR
    body_bytes = await request.body()
    sig = request.headers.get("x-line-signature", "")

    # ตรวจสอบ signature
    hash_ = hmac.new(secret.encode(), body_bytes, hashlib.sha256).digest()
    import base64
    expected = base64.b64encode(hash_).decode()
    if sig != expected:
        raise HTTPException(status_code=400, detail="Signature ไม่ถูกต้อง")

    body = json.loads(body_bytes)
    platform = f"line_{channel}"

    for event in body.get("events", []):
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        user_id = event.get("source", {}).get("userId", "")
        text = msg.get("text", "") if msg.get("type") == "text" else "[รูปภาพ/ไฟล์แนบ]"

        # ดึงชื่อผู้ส่ง
        token = LINE_TOKEN_ASAP if channel == "asap" else LINE_TOKEN_FAIRCAR
        name = await get_line_user_name(user_id, token)
        contact_id = upsert_contact(platform, user_id, name)
        conv_id = upsert_conversation(contact_id, platform, text)
        save_message(conv_id, "incoming", text)

    return {"status": "ok"}

async def get_line_user_name(user_id: str, token: str) -> str:
    try:
        url = f"https://api.line.me/v2/bot/profile/{user_id}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                return r.json().get("displayName", "ไม่ทราบชื่อ")
    except:
        pass
    return "ไม่ทราบชื่อ"

# ─── API: STATS (สำหรับ notification badge) ──────────────────────────────────
@app.get("/api/stats")
async def get_stats():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM conversations WHERE status='pending'")
    pending = c.fetchone()["cnt"]
    # ค้างตอบเกิน 30 นาที
    c.execute("""
        SELECT COUNT(*) as cnt FROM conversations
        WHERE status='pending'
        AND unanswered_since < datetime('now', '-30 minutes', 'localtime')
    """)
    overdue = c.fetchone()["cnt"]
    conn.close()
    return {"pending": pending, "overdue": overdue}

# ─── API: UPDATE CONVERSATION STATUS ─────────────────────────────────────────
@app.post("/api/conversations/{conv_id}/status")
async def update_status(conv_id: int, request: Request):
    body = await request.json()
    status = body.get("status", "pending")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE conversations SET status=? WHERE id=?", (status, conv_id))
    conn.commit()
    conn.close()
    return {"ok": True}
