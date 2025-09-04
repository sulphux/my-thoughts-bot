import os
import requests
import sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

HF_TOKEN = os.getenv("HF_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DB_FILE = "thoughts.db"
API_URL = "https://api-inference.huggingface.co/models/google/gemma-2b-it"
WHISPER_URL = "https://api-inference.huggingface.co/models/openai/whisper-base"

def init_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS thoughts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        summary TEXT,
        category TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER
    )""")
    conn.commit()
    conn.close()

async def call_hf_api(prompt: str, max_tokens: int = 50) -> str:
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": max_tokens, "temperature":0.3}}
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                return result[0].get("generated_text", prompt[:40])
        else:
            print("Błąd HF:", response.status_code, response.text)
    except Exception as e:
        print("Wyjątek HF:", e)
    return prompt[:40] + "..."

async def call_whisper_api(url: str) -> str:
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": url}
    try:
        response = requests.post(WHISPER_URL, headers=headers, json=payload, timeout=45)
        if response.status_code == 200:
            result = response.json()
            return result.get("text", "")
        else:
            print("Błąd Whisper:", response.status_code, response.text)
    except Exception as e:
        print("Wyjątek Whisper:", e)
    return ""

async def categorize_text(text: str) -> str:
    categories = {
        "projekt": ["pomysł", "idea", "startup", "projekt"],
        "nauka": ["artykuł", "kurs", "nauka", "wiedza", "ai"],
        "osobiste": ["kupić", "rodzina", "zdrowie", "osobiste"],
        "praca": ["spotkanie", "klient", "deadline", "praca"],
        "technologia": ["kod", "github", "framework", "technologia"],
        "inspiracja": ["cytat", "motywacja", "cel"]
    }
    text_lower = text.lower()
    for category, words in categories.items():
        if any(w in text_lower for w in words):
            return category
    return "inne"

async def summarize_and_categorize(text: str):
    summary = await call_hf_api(f"Streść w 12 słowach: {text}", 20) if len(text) > 20 else text
    category = await categorize_text(text)
    return summary, category

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧠 Witaj! Wyślij mi dowolną myśl (także głosową!), zapiszę, skategoryzuję i zsyntezuję.\n"
        "Komendy:\n- /list <kategoria>\n- /stats\n- /help"
    )

async def save_thought(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if len(text.strip()) < 3:
        await update.message.reply_text("⚠️ Myśl jest za krótka! Napisz coś więcej.")
        return
    processing_msg = await update.message.reply_text("🤖 Analizuję Twoją myśl...")
    try:
        summary, category = await summarize_and_categorize(text)
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO thoughts (text, summary, category, user_id) VALUES (?, ?, ?, ?)",
                  (text, summary, category, user_id))
        thought_id = c.lastrowid
        conn.commit()
        conn.close()
        emoji = {"projekt": "🚀", "nauka": "📖", "osobiste": "👤", "praca": "💼", "technologia": "💻", "inspiracja": "✨", "inne": "📄"}
        response = (
            f"✅ Myśl #{thought_id} zapisana!\n\n"
            f"{emoji.get(category,'📄')} Kategoria: {category}\n"
            f"📝 Streszczenie: {summary}\n"
            f"🕒 Czas: {datetime.now().strftime('%H:%M')}"
        )
        await processing_msg.edit_text(response)
    except Exception as e:
        print("Błąd podczas zapisu:", e)
        await processing_msg.edit_text("❌ Wystąpił błąd podczas przetwarzania. Spróbuj ponownie.")

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    file_url = file.file_path
    await update.message.reply_text("🤖 Przetwarzam głos na tekst...")
    try:
        transcribed_text = await call_whisper_api(file_url)
        if transcribed_text.strip():
            update.message.text = transcribed_text
            await save_thought(update, context)
        else:
            await update.message.reply_text("❌ Nie udało się rozpoznać głosu.")
    except Exception as e:
        print("Błąd głosówki:", e)
        await update.message.reply_text("❌ Nie można zapisać głosówki.")

async def list_thoughts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    category = args[0].lower() if args else None
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if category:
        c.execute("SELECT id, summary, category, created_at FROM thoughts WHERE user_id=? AND category=? ORDER BY created_at DESC LIMIT 20", (user_id, category))
    else:
        c.execute("SELECT id, summary, category, created_at FROM thoughts WHERE user_id=? ORDER BY created_at DESC LIMIT 5", (user_id,))
    thoughts = c.fetchall()
    conn.close()
    if not thoughts:
        await update.message.reply_text("📭 Nie masz jeszcze żadnych myśli wpisanych.")
        return
    response = "📚 Twoje myśli:\n"
    for t in thoughts:
        response += f"{t[0]}. [{t[2]}] {t[1][:50]}... ({t[3]})\n"
    await update.message.reply_text(response)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT category, COUNT(*) FROM thoughts WHERE user_id=? GROUP BY category", (user_id,))
    data = c.fetchall()
    c.execute("SELECT COUNT(*) FROM thoughts WHERE user_id=?", (user_id,))
    total = c.fetchone()[0]
    conn.close()
    if not data:
        await update.message.reply_text("📊 Brak danych do statystyk.")
        return
    response = "📊 Twoje statystyki kategorii:\n"
    for cat, count in data:
        emoji = {"projekt": "🚀", "nauka": "📖", "osobiste": "👤", "praca": "💼", "technologia": "💻", "inspiracja": "✨", "inne": "📄"}
        response += f"{emoji.get(cat, '📄')} {cat}: {count}\n"
    response += f"\n📝 Łącznie: {total} myśli."
    await update.message.reply_text(response)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Wysyłając wiadomość (lub głos!), zapiszesz myśl.\n"
        "Możesz:\n"
        "- /list [kategoria] – przeglądać notatki wg kategorii\n"
        "- /stats – statystyki\n"
        "- /help – ta pomoc\n"
        "Przykład: /list technologia\n"
        "Możesz też wysłać głosówkę!"
    )

def main():
    print("🚀 Startuje MyThoughtsBot...")
    if not TELEGRAM_TOKEN:
        print("❌ Brak TELEGRAM_TOKEN!")
        raise ValueError("Brak TELEGRAM_TOKEN!")
    if not HF_TOKEN:
        print("⚠️ Brak HF_TOKEN – bot będzie działał bez AI!")
    init_database()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_thoughts))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_thought))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    print("✅ Bot wystartował – wyślij wiadomość na Telegram!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
