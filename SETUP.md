# คู่มือ Deploy Maew Inbox

## ขั้นตอนภาพรวม
1. อัพโค้ดขึ้น GitHub
2. Deploy บน Render.com
3. ตั้ง webhook URL ที่ Facebook + LINE

---

## ขั้นที่ 1 — อัพโค้ดขึ้น GitHub

1. เปิด https://github.com → New Repository → ชื่อ `maew-inbox` → Public หรือ Private → Create
2. เปิด Terminal (หรือ Git Bash) บนเครื่อง แล้วรันคำสั่งนี้ (แทน YOUR_USERNAME):

```bash
cd C:\Users\Lenovo\Documents\Claude\Projects\รถเช่า\inbox-app
git init
git add .
git commit -m "first commit"
git remote add origin https://github.com/YOUR_USERNAME/maew-inbox.git
git push -u origin main
```

---

## ขั้นที่ 2 — Deploy บน Render.com

1. เปิด https://render.com → Sign Up ด้วย GitHub account เดียวกัน
2. กด **New** → **Web Service**
3. เลือก repo `maew-inbox`
4. ตั้งค่า:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. ไปที่ **Environment Variables** กด Add:

| Key | Value |
|-----|-------|
| FB_TOKEN_FAIRCAR | (token จาก Notepad) |
| FB_TOKEN_ASAP | (token จาก Notepad) |
| FB_APP_SECRET | (จาก Meta App → Settings → Basic) |
| FB_VERIFY_TOKEN | maew_inbox_2024 |
| FB_PAGE_ID_FAIRCAR | 100735478552467 |
| FB_PAGE_ID_ASAP | 117865866278291 |
| LINE_SECRET_ASAP | 0f3aa3e22154b9b5c486b8109a3f1d74 |
| LINE_TOKEN_ASAP | (token จาก Notepad) |
| LINE_SECRET_FAIRCAR | 397df18a88f47db51be28fbaeace7532 |
| LINE_TOKEN_FAIRCAR | (token จาก Notepad) |

6. กด **Create Web Service** → รอ ~3 นาที
7. ได้ URL แบบ `https://maew-inbox.onrender.com` ✅

---

## ขั้นที่ 3 — ตั้ง Webhook Facebook

1. เปิด https://developers.facebook.com/apps/102899394280267
2. ไปที่ **Messenger → Settings → Webhooks**
3. กด **Add Callback URL**:
   - URL: `https://maew-inbox.onrender.com/webhook/facebook`
   - Verify Token: `maew_inbox_2024`
4. กด **Verify and Save**
5. Subscribe fields: ✅ `messages`, ✅ `messaging_postbacks`
6. **Subscribe** ทั้ง 2 เพจ (Faircar + Asap)

---

## ขั้นที่ 4 — ตั้ง Webhook LINE

### LINE Asap
1. เปิด https://developers.line.biz
2. เลือก Provider → asap Select cm. → Messaging API Channel
3. **Messaging API** tab → **Webhook settings**:
   - URL: `https://maew-inbox.onrender.com/webhook/line/asap`
   - กด Verify → ✅
   - เปิด **Use webhook** = ON

### LINE Faircar
- URL: `https://maew-inbox.onrender.com/webhook/line/faircar`
- ขั้นตอนเดียวกัน

---

## ตรวจสอบระบบทำงาน

เปิด `https://maew-inbox.onrender.com` → ใส่ชื่อแอดมิน → เข้าระบบได้ = ✅

ทดสอบ: ส่งข้อความมาที่เพจ Faircar หรือ LINE Asap → ควรขึ้นในหน้า inbox ภายใน 30 วินาที

---

## หมายเหตุ

- Render.com free tier จะ sleep หลังไม่มี traffic 15 นาที → ครั้งแรกอาจโหลดช้า ~30 วินาที
- ฐานข้อมูล SQLite อยู่ใน disk ของ Render → ถ้า redeploy ข้อมูลอาจหายได้ (แก้ภายหลังด้วย Postgres ถ้าต้องการ)
- IG จะเพิ่มทีหลังบัญชีถูก unblock (ใช้ webhook เดียวกันกับ Facebook)
