"""
🃏 Joker Shop — Backend Server + Telegram Bot
Запуск: python server.py
"""
import json
import os
import time
import asyncio
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════
TOKEN      = "8505960991:AAFeV_5_pNVcL4H-tczJRCPquELJyAHekOU"
ADMIN_IDS  = [1044367167, 615831055]
ADMIN_KEY  = os.environ.get("ADMIN_KEY", "Joker@Shop#2025")
DB_FILE    = "db.json"
PORT       = int(os.environ.get("PORT", 8080))

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ══════════════════════════════════════════════
# DATABASE (JSON file)
# ══════════════════════════════════════════════
def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        return {"products": [], "orders": []}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"products": [], "orders": []}

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

# ══════════════════════════════════════════════
# AUTH MIDDLEWARE
# ══════════════════════════════════════════════
def check_auth(req) -> bool:
    key = req.headers.get("X-Admin-Key") or req.args.get("key")
    return key == ADMIN_KEY

# ══════════════════════════════════════════════
# REST API — PRODUCTS
# ══════════════════════════════════════════════
@app.route("/api/products", methods=["GET"])
def api_get_products():
    db = load_db()
    return jsonify(db["products"])

@app.route("/api/products", methods=["POST"])
def api_add_product():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    db = load_db()
    p = request.json or {}
    p["id"]        = int(time.time() * 1000)
    p["created_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    # ensure photos is list
    if "photos" not in p or not isinstance(p["photos"], list):
        img = p.get("img") or p.get("image") or ""
        p["photos"] = [img] if img else []
    db["products"].append(p)
    save_db(db)
    log.info(f"Product added: {p.get('name')}")
    return jsonify(p), 201

@app.route("/api/products/<int:pid>", methods=["PUT"])
def api_update_product(pid):
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    db = load_db()
    for i, p in enumerate(db["products"]):
        if p["id"] == pid:
            data = request.json or {}
            data["id"] = pid
            data["created_at"] = p.get("created_at", "")
            if "photos" not in data or not isinstance(data["photos"], list):
                img = data.get("img") or data.get("image") or ""
                data["photos"] = [img] if img else []
            db["products"][i] = data
            save_db(db)
            return jsonify(data)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/products/<int:pid>", methods=["DELETE"])
def api_delete_product(pid):
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    db = load_db()
    db["products"] = [p for p in db["products"] if p["id"] != pid]
    save_db(db)
    return jsonify({"ok": True})

@app.route("/api/products/<int:pid>/hit", methods=["POST"])
def api_toggle_hit(pid):
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    db = load_db()
    for p in db["products"]:
        if p["id"] == pid:
            p["hit"] = not p.get("hit", False)
            save_db(db)
            return jsonify({"hit": p["hit"]})
    return jsonify({"error": "Not found"}), 404

# ══════════════════════════════════════════════
# REST API — ORDERS
# ══════════════════════════════════════════════
@app.route("/api/orders", methods=["GET"])
def api_get_orders():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    db = load_db()
    return jsonify(db["orders"])

@app.route("/api/orders", methods=["POST"])
def api_add_order():
    db = load_db()
    o = request.json or {}
    o["id"]        = int(time.time() * 1000)
    o["timestamp"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    o["status"]    = "new"
    db["orders"].insert(0, o)
    save_db(db)
    log.info(f"New order from {o.get('name')} for {o.get('product')}")
    # Send TG notification async
    threading.Thread(target=send_order_notification, args=(o,), daemon=True).start()
    return jsonify(o), 201

@app.route("/api/orders/<int:oid>/done", methods=["POST"])
def api_mark_done(oid):
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    db = load_db()
    for o in db["orders"]:
        if o["id"] == oid:
            o["status"] = "done"
            save_db(db)
            return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/orders", methods=["DELETE"])
def api_clear_orders():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    db = load_db()
    db["orders"] = []
    save_db(db)
    return jsonify({"ok": True})

# Stats
@app.route("/api/stats", methods=["GET"])
def api_stats():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    db = load_db()
    orders = db["orders"]
    return jsonify({
        "products":  len(db["products"]),
        "orders":    len(orders),
        "new":       sum(1 for o in orders if o.get("status") == "new"),
        "revenue":   sum(o.get("total", 0) for o in orders),
        "hits":      sum(1 for p in db["products"] if p.get("hit"))
    })

# Health check
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Joker Shop API"})

# ══════════════════════════════════════════════
# TELEGRAM NOTIFICATIONS
# ══════════════════════════════════════════════
def send_order_notification(order: dict):
    """Send order notification to all admins via TG"""
    qty = order.get("qty", 1)
    total = order.get("total", 0)
    msg = (
        f"🃏 <b>НОВЕ ЗАМОВЛЕННЯ #{str(order['id'])[-6:]}</b>\n\n"
        f"📦 <b>Товар:</b> {order.get('product', '?')}\n"
        f"🔢 <b>Кількість:</b> {qty} шт\n"
        f"💰 <b>Сума:</b> {total} грн\n"
        f"💳 <b>Передоплата:</b> 500 грн\n\n"
        f"👤 <b>Ім'я:</b> {order.get('name', '?')}\n"
        f"📞 <b>Телефон:</b> {order.get('phone', '?')}\n"
    )
    if order.get("comment"):
        msg += f"💬 <b>Коментар:</b> {order['comment']}\n"
    msg += f"\n🕐 <b>Час:</b> {order.get('timestamp', '?')}"

    async def _send():
        bot = Bot(token=TOKEN)
        for cid in ADMIN_IDS:
            try:
                await bot.send_message(chat_id=cid, text=msg, parse_mode="HTML")
            except Exception as e:
                log.warning(f"TG send failed for {cid}: {e}")

    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_send())
        loop.close()
    except Exception as e:
        log.error(f"TG notification error: {e}")

# ══════════════════════════════════════════════
# TELEGRAM BOT COMMANDS
# ══════════════════════════════════════════════
def is_admin(uid): return uid in ADMIN_IDS

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🃏 Joker Shop\nЗамовлення: joker-shops.netlify.app\nТел: 0962000369")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Замовлення", callback_data="orders"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("📦 Товари",    callback_data="prods")],
    ])
    await update.message.reply_text(
        f"👋 Привіт! Це бот <b>Joker Shop</b>\n\n"
        f"🌐 Сайт: joker-shops.netlify.app\n"
        f"📩 Нові замовлення приходять сюди автоматично\n\n"
        f"/orders — замовлення\n/stats — статистика\n/products — список товарів",
        parse_mode="HTML", reply_markup=kb
    )

async def cmd_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    db = load_db()
    orders = db["orders"]
    if not orders:
        await update.message.reply_text("📭 Замовлень ще немає."); return
    last = orders[:10]
    txt = f"🛒 <b>Останні {len(last)} замовлень:</b>\n\n"
    for o in last:
        status = "✅" if o.get("status") == "done" else "🔴"
        txt += (f"{status} <b>#{str(o['id'])[-6:]}</b> — {o.get('product','?')}\n"
                f"   👤 {o.get('name')} | 📞 {o.get('phone')}\n"
                f"   💰 {o.get('total',0)} грн | 🕐 {o.get('timestamp','')}\n\n")
    await update.message.reply_text(txt, parse_mode="HTML")

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    db = load_db()
    orders = db["orders"]
    revenue = sum(o.get("total", 0) for o in orders)
    new_o   = sum(1 for o in orders if o.get("status") == "new")
    await update.message.reply_text(
        f"📊 <b>Статистика Joker Shop</b>\n\n"
        f"📦 Товарів: <b>{len(db['products'])}</b>\n"
        f"🛒 Замовлень: <b>{len(orders)}</b>\n"
        f"🔴 Нових: <b>{new_o}</b>\n"
        f"✅ Виконаних: <b>{len(orders)-new_o}</b>\n"
        f"💰 Загальна сума: <b>{revenue:,} грн</b>\n\n"
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        parse_mode="HTML"
    )

async def cmd_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    db = load_db()
    prods = db["products"]
    if not prods:
        await update.message.reply_text("📦 Товарів ще немає. Додайте через сайт!"); return
    txt = f"📦 <b>Товари ({len(prods)}):</b>\n\n"
    for p in prods:
        hit = " ⭐" if p.get("hit") else ""
        txt += f"• <b>{p.get('name','?')}</b>{hit} — {p.get('price',0)} грн\n"
    await update.message.reply_text(txt, parse_mode="HTML")

async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    if q.data == "orders":
        db = load_db(); orders = db["orders"]
        if not orders:
            await q.edit_message_text("📭 Замовлень немає."); return
        last = orders[:5]
        txt = "🛒 <b>Останні замовлення:</b>\n\n"
        for o in last:
            st = "✅" if o.get("status")=="done" else "🔴"
            txt += f"{st} {o.get('product','?')} — {o.get('total',0)} грн\n👤 {o.get('name')} {o.get('phone')}\n\n"
        await q.edit_message_text(txt, parse_mode="HTML")
    elif q.data == "stats":
        db = load_db(); orders = db["orders"]
        rev = sum(o.get("total",0) for o in orders)
        await q.edit_message_text(
            f"📊 Товарів: {len(db['products'])} | Замовлень: {len(orders)}\n💰 Сума: {rev:,} грн",
            parse_mode="HTML"
        )
    elif q.data == "prods":
        db = load_db()
        txt = "\n".join(f"• {p.get('name')} — {p.get('price')} грн" for p in db["products"]) or "Порожньо"
        await q.edit_message_text(f"📦 <b>Товари:</b>\n{txt}", parse_mode="HTML")

async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🃏 joker-shops.netlify.app | 0962000369")

# ══════════════════════════════════════════════
# RUN BOTH FLASK + TELEGRAM BOT
# ══════════════════════════════════════════════
def run_bot():
    """Run TG bot in separate thread"""
    async def _run():
        tg = Application.builder().token(TOKEN).build()
        tg.add_handler(CommandHandler("start",    cmd_start))
        tg.add_handler(CommandHandler("orders",   cmd_orders))
        tg.add_handler(CommandHandler("stats",    cmd_stats))
        tg.add_handler(CommandHandler("products", cmd_products))
        tg.add_handler(CallbackQueryHandler(cb_handler))
        tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
        log.info("TG Bot started")
        await tg.run_polling(drop_pending_updates=True)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_run())

if __name__ == "__main__":
    log.info(f"Starting Joker Shop Server on port {PORT}")
    # Start TG bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    # Start Flask API
    app.run(host="0.0.0.0", port=PORT, debug=False)
