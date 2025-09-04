import os
import requests
import sqlite3
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Konfiguracja
HF_TOKEN = os.getenv("HF_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DB_FILE = "thoughts.db"

# SPRAWDZONE modele HuggingFace (wrzesień 2025)
AVAILABLE_MODELS = {
    "gemma": "https://api-inference.huggingface.co/models/google/gemma-2b-it",
    "falcon": "https://api-inference.huggingface.co/models/tiiuae/falcon-7b-instruct", 
    "stablelm": "https://api-inference.huggingface.co/models/stabilityai/stablelm-tuned-alpha-3b",
    "gptj": "https://api-inference.huggingface.co/models/EleutherAI/gpt-j-6B"
}

# Używamy Gemma-2B jako domyślny (najszybszy i najbardziej niezawodny)
API_URL = AVAILABLE_MODELS["gemma"]

def init_database():
    """Inicjalizacja bazy danych SQLite"""
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
    print(f"✅ Baza danych {DB_FILE} zainicjalizowana")

async def call_hf_api(prompt: str, max_tokens: int = 50) -> str:
    """Bezpieczne wywołanie HuggingFace API z obsługą błędów"""
    if not HF_TOKEN:
        print("⚠️ Brak HF_TOKEN - używam fallback")
        return prompt[:30] + "..." if len(prompt) > 30 else prompt

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_tokens,
            "temperature": 0.3,
            "do_sample": True,
            "return_full_text": False
        }
    }

    try:
        print(f"🤖 Wywołuję HF API: {prompt[:50]}...")
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)

        print(f"📊 HF API status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                generated = result[0].get("generated_text", "").strip()
                if generated:
                    return generated

        elif response.status_code == 503:
            print("⏳ Model się ładuje, spróbuję ponownie za 10s...")
            await asyncio.sleep(10)
            # Druga próba
            response = requests.post(API_URL, headers=headers, json=payload, timeout=45)
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    return result[0].get("generated_text", "").strip()

        print(f"❌ HF API błąd {response.status_code}: {response.text[:200]}")

    except Exception as e:
        print(f"⚠️ HF API wyjątek: {e}")

    # Fallback - zwróć skrócony tekst
    return prompt[:40] + "..." if len(prompt) > 40 else prompt

async def categorize_text(text: str) -> str:
    """Kategoryzacja tekstu - prosta heurystyka + AI backup"""
    text_lower = text.lower()

    # Szybka kategoryzacja słowami kluczowymi
    categories = {
        "projekt": ["pomysł", "idea", "startup", "biznes", "projekt", "plan", "aplikacja"],
        "nauka": ["artykuł", "książka", "kurs", "nauka", "wiedza", "ai", "technologia", "programowanie"],
        "osobiste": ["kupić", "pamiętać", "jutro", "dzisiaj", "rodzina", "zdrowie", "sport"],
        "praca": ["spotkanie", "deadline", "klient", "zesp", "prezentacja", "raport", "boss"],
        "technologia": ["kod", "github", "api", "python", "javascript", "framework", "library"],
        "inspiracja": ["cytat", "motywacja", "sukces", "marzenie", "cel"]
    }

    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in text_lower:
                return category

    # Jeśli nie znaleziono słów kluczowych, spróbuj AI
    if len(text) > 10 and HF_TOKEN:
        ai_prompt = f"Kategoryzuj to w jednym słowie (projekt/nauka/osobiste/praca/technologia/inspiracja): {text[:100]}"
        ai_result = await call_hf_api(ai_prompt, max_tokens=5)

        valid_categories = ["projekt", "nauka", "osobiste", "praca", "technologia", "inspiracja"]
        for cat in valid_categories:
            if cat in ai_result.lower():
                return cat

    return "inne"

async def summarize_and_categorize(text: str) -> tuple[str, str]:
    """Główna funkcja przetwarzania myśli"""
    print(f"🧠 Przetwarzam: {text[:50]}...")

    # Równoległe przetwarzanie streszczenia i kategoryzacji
    tasks = []

    # Streszczenie (tylko dla dłuższych tekstów)
    if len(text) > 50:
        summary_prompt = f"Streść w 10 słowach: {text}"
        tasks.append(call_hf_api(summary_prompt, max_tokens=20))
    else:
        tasks.append(asyncio.create_task(asyncio.coroutine(lambda: text)()))

    # Kategoryzacja
    tasks.append(categorize_text(text))

    # Czekaj na wyniki
    summary, category = await asyncio.gather(*tasks)

    # Czyszczenie streszczenia
    if summary and summary != text:
        # Usuń powtórzenia z promptu
        if "Streść" in summary:
            summary = summary.split(":")[-1].strip()
        summary = summary[:100].strip()
    else:
        summary = text[:50] + "..." if len(text) > 50 else text

    print(f"✅ Przetworzone: {category} | {summary[:30]}...")
    return summary, category

# TELEGRAM BOT HANDLERS
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Komenda /start"""
    welcome = """🧠 Witaj w Asystencie Myśli!

Wyślij mi dowolną myśl, a ja:
• 📝 Zapiszę ją w bazie danych
• 🎯 Automatycznie skategoryzuję  
• ✨ Stworzę krótkie streszczenie
• 🔍 Umożliwię ci wyszukiwanie

Komendy:
/start - ta wiadomość
/list - ostatnie 5 myśli
/stats - statystyki kategorii
/help - pomoc

Wyślij pierwszą myśl! 💭"""

    await update.message.reply_text(welcome)

async def save_thought(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zapisanie nowej myśli"""
    user_id = update.effective_user.id
    text = update.message.text

    if len(text.strip()) < 3:
        await update.message.reply_text("⚠️ Myśl jest za krótka! Napisz coś więcej.")
        return

    # Pokazanie że przetwarzamy
    processing_msg = await update.message.reply_text("🤖 Analizuję Twoją myśl...")

    try:
        # AI processing
        summary, category = await summarize_and_categorize(text)

        # Zapis do bazy
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            INSERT INTO thoughts (text, summary, category, user_id) 
            VALUES (?, ?, ?, ?)
        """, (text, summary, category, user_id))
        thought_id = c.lastrowid
        conn.commit()
        conn.close()

        # Emotikony dla kategorii
        emojis = {
            'projekt': '🚀', 'nauka': '📖', 'osobiste': '👤',
            'praca': '💼', 'technologia': '💻', 'inspiracja': '✨', 'inne': '📄'
        }

        emoji = emojis.get(category, '📄')

        # Odpowiedź
        response = f"""✅ Myśl #{thought_id} zapisana!

{emoji} **Kategoria:** {category}
📝 **Streszczenie:** {summary}
🕒 **Czas:** {datetime.now().strftime('%H:%M')}"""

        await processing_msg.edit_text(response, parse_mode='Markdown')

    except Exception as e:
        print(f"❌ Błąd podczas zapisywania myśli: {e}")
        await processing_msg.edit_text("❌ Wystąpił błąd podczas przetwarzania. Spróbuj ponownie.")

async def list_thoughts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista ostatnich myśli"""
    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT id, summary, category, created_at 
        FROM thoughts 
        WHERE user_id = ?
        ORDER BY created_at DESC 
        LIMIT 5
    """, (user_id,))
    thoughts = c.fetchall()
    conn.close()

    if not thoughts:
        await update.message.reply_text("📭 Nie masz jeszcze żadnych zapisanych myśli.")
        return

    emojis = {
        'projekt': '🚀', 'nauka': '📖', 'osobiste': '👤',
        'praca': '💼', 'technologia': '💻', 'inspiracja': '✨', 'inne': '📄'
    }

    response = "📚 **Twoje ostatnie myśli:**\n\n"

    for thought in thoughts:
        thought_id, summary, category, created_at = thought
        emoji = emojis.get(category, '📄')

        # Formatowanie daty
        try:
            dt = datetime.fromisoformat(created_at)
            time_str = dt.strftime('%d.%m %H:%M')
        except:
            time_str = created_at

        response += f"{emoji} **#{thought_id}** [{category}]\n"
        response += f"_{summary[:60]}{'...' if len(summary) > 60 else ''}_\n"
        response += f"📅 {time_str}\n\n"

    await update.message.reply_text(response, parse_mode='Markdown')

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statystyki kategorii użytkownika"""
    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT category, COUNT(*) as count 
        FROM thoughts 
        WHERE user_id = ?
        GROUP BY category 
        ORDER BY count DESC
    """, (user_id,))
    stats_data = c.fetchall()

    c.execute("SELECT COUNT(*) FROM thoughts WHERE user_id = ?", (user_id,))
    total = c.fetchone()[0]
    conn.close()

    if total == 0:
        await update.message.reply_text("📊 Nie masz jeszcze żadnych myśli do analizy.")
        return

    emojis = {
        'projekt': '🚀', 'nauka': '📖', 'osobiste': '👤',
        'praca': '💼', 'technologia': '💻', 'inspiracja': '✨', 'inne': '📄'
    }

    response = "📊 **Twoje statystyki myśli:**\n\n"

    for category, count in stats_data:
        emoji = emojis.get(category, '📄')
        percentage = (count / total) * 100
        response += f"{emoji} **{category}**: {count} ({percentage:.1f}%)\n"

    response += f"\n📝 **Razem**: {total} myśli"

    await update.message.reply_text(response, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pomoc"""
    help_text = """🤖 **Jak używać Asystenta Myśli:**

**📝 Podstawowe użycie:**
Wyślij dowolną wiadomość → zostanie zapisana jako myśl

**🎯 Komendy:**
• `/list` - ostatnie 5 myśli
• `/stats` - statystyki kategorii  
• `/help` - ta pomoc

**📂 Automatyczne kategorie:**
🚀 projekt - pomysły, startupy, plany
📖 nauka - artykuły, kursy, wiedza
👤 osobiste - życie prywatne, zadania
💼 praca - sprawy zawodowe
💻 technologia - programowanie, AI
✨ inspiracja - cytaty, motywacja
📄 inne - pozostałe myśli

**💡 Przykłady:**
"Mam pomysł na aplikację do nauki języków"
"Przeczytałem ciekawy artykuł o AI"
"Jutro spotkanie z klientem o 14:00"

Bot automatycznie stworzy streszczenie i przypisze kategorię! 🧠"""

    await update.message.reply_text(help_text, parse_mode='Markdown')

def main():
    """Główna funkcja uruchamiająca bota"""
    print("🚀 Uruchamianie Asystenta Myśli...")

    # Walidacja tokenów
    if not TELEGRAM_TOKEN:
        print("❌ Brak TELEGRAM_TOKEN w zmiennych środowiskowych!")
        raise ValueError("Brak zmiennej środowiskowej TELEGRAM_TOKEN!")

    if not HF_TOKEN:
        print("⚠️ Brak HF_TOKEN - bot będzie działać w trybie podstawowym")
    else:
        print("✅ HuggingFace token skonfigurowany")

    # Inicjalizacja bazy danych
    init_database()

    # Test API (opcjonalny)
    print(f"🔗 Używam modelu: {API_URL}")

    try:
        # Tworzenie aplikacji Telegram
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        # Dodawanie handlerów
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("list", list_thoughts))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_thought))

        print("✅ Bot skonfigurowany - rozpoczynam polling...")
        print("💬 Wyślij wiadomość do swojego bota na Telegram!")

        # Uruchomienie bota
        app.run_polling(drop_pending_updates=True)

    except Exception as e:
        print(f"❌ Błąd uruchamiania bota: {e}")
        raise

if __name__ == "__main__":
    main()
