import os
import requests
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

HF_TOKEN = os.getenv("HF_TOKEN", "")
DB_FILE = "thoughts.db"

# AI handler z HuggingFace
async def summarize_and_categorize(text: str) -> (str, str):
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    summarize_prompt = f"Streść: {text}"
    category_prompt = f"Przypisz kategorię: {text} (projekt, nauka, osobiste, praca, technologia, inspiracja, inne)"

    # Streszczenie
    payload = {"inputs": summarize_prompt, "parameters": {"max_new_tokens": 30}}
    url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.1"
    response = requests.post(url, headers=headers, json=payload)
    out_summary = response.json()[0]['generated_text'].strip()

    # Kategoria
    payload_cat = {"inputs": category_prompt, "parameters": {"max_new_tokens": 10}}
    response_cat = requests.post(url, headers=headers, json=payload_cat)
    out_category = response_cat.json()[0]['generated_text'].strip().lower()
    if out_category not in ["projekt", "nauka", "osobiste", "praca", "technologia", "inspiracja", "inne"]:
        out_category = "inne"
    return (out_summary, out_category)

# Prosta baza danych
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS thoughts (
    id INTEGER PRIMARY KEY, text TEXT, summary TEXT, category TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()
conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cześć! Wyślij mi dowolną myśl, zapiszę ją i spróbuję zautomatyzować streszczenie + kategorię.")

async def save_thought(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    summary, category = await summarize_and_categorize(text)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO thoughts (text, summary, category) VALUES (?, ?, ?)", (text, summary, category))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✔️ Zapisane!
Kategoria: {category}
Streszczenie: {summary}")

async def list_thoughts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, summary, category, date FROM thoughts ORDER BY date DESC LIMIT 5")
    rows = c.fetchall()
    conn.close()
    response = "📚 Ostatnie myśli:
"
    for r in rows:
        response += f"{r[0]}. [{r[2]}] {r[1]} ({r[3]})
"
    await update.message.reply_text(response)

def main():
    app = Application.builder().token("TU_WSTAW_TOKEN_TELEGRAM").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_thoughts))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_thought))
    app.run_polling()

if __name__ == "__main__":
    main()
