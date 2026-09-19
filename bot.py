import os
import json
from datetime import datetime, timedelta
import io
from PIL import Image
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import google.generativeai as genai
import database

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
# We use gemini-1.5-pro for deep reasoning and vision tasks
model = genai.GenerativeModel('gemini-1.5-pro')

SYSTEM_PROMPT = """
Actúa como un Preparador Físico de Alto Rendimiento Olímpico y Táctico, especialista en fisiología del ejercicio concurrente (fuerza y resistencia simultáneas) para oposiciones a bomberos de aeropuertos (AENA). 

Manejas el modelo de doble umbral (Ingebrigtsen) para el 1500m, el sistema High-Low (Charlie Francis) para el 60m, la gimnasia soviética para la cuerda y el FNP extremo para la flexibilidad. Debes evitar a toda costa el efecto de interferencia (conflicto AMPK vs. mTOR) en un atleta de 80 kg.

Tu trabajo ahora es analizar la sesión que el atleta acaba de registrar (incluyendo capturas de pantalla de su reloj si las hay) y darle un feedback profesional. 
1. Evalúa su rendimiento, RPE y molestias.
2. Si hay problemas o fatiga excesiva, ajusta su PRÓXIMA sesión equivalente (ej. si hoy era pista, ajusta la próxima pista). 
3. Mantén un tono técnico, directo y motivador (máximo 150 palabras).
"""

# Load training plan
with open("plan_data.json", "r", encoding="utf-8") as f:
    PLAN_DATA = json.load(f)
PLAN_BY_ISO = {day["iso"]: day for day in PLAN_DATA}

# Conversation states
RPE, PAIN, NOTES_AND_PHOTO, FINAL = range(4)

def get_today_plan():
    today_iso = datetime.now().strftime("%Y-%m-%d")
    plan = PLAN_BY_ISO.get(today_iso)
    return plan, today_iso

def get_next_session(context_keyword, current_iso):
    current_date = datetime.strptime(current_iso, "%Y-%m-%d")
    for i in range(1, 14):
        next_date = current_date + timedelta(days=i)
        next_iso = next_date.strftime("%Y-%m-%d")
        plan = PLAN_BY_ISO.get(next_iso)
        if plan and context_keyword.lower() in plan.get("context", "").lower():
            return plan
    return None

def format_plan_text(plan):
    if not plan["tables"] and not plan["notes"]:
        return f"💤 {plan['day_name']} - Descanso absoluto. Sin sesión prevista."
    
    text = f"🔥 *{plan['day_name']} - Semana {plan['week']} (Mesociclo {plan['mesociclo']})*\n"
    text += f"Contexto: {plan['context']}\n\n"
    
    for table in plan["tables"]:
        for row in table["rows"]:
            text += f"🔸 *{row[0]}*\n"
            if len(row) > 1:
                parts = []
                for i in range(1, len(row)):
                    if row[i] and row[i] != '—':
                        parts.append(f"{table['header'][i]}: {row[i]}")
                text += "   " + " | ".join(parts) + "\n"
    
    if plan["notes"]:
        text += "\n📝 *Notas:*\n"
        for note in plan["notes"]:
            text += f"- {note}\n"
    
    return text

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# ... (skipping to start command)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    database.init_db()
    
    # We will use a placeholder URL for the Web App until it is hosted
    WEBAPP_URL = os.getenv("WEBAPP_URL", "https://tudominio.onrender.com") 
    
    keyboard = [
        [InlineKeyboardButton("📅 Abrir Calendario", web_app=WebAppInfo(url=WEBAPP_URL))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"¡Hola {user.first_name}! Soy tu preparador táctico para AENA.\n\n"
        "Comandos disponibles:\n"
        "/hoy - Ver el entrenamiento de hoy\n"
        "/registrar - Registrar la sesión de hoy (texto y capturas)\n\n"
        "Pulsa el botón de abajo para ver tu Macrociclo completo:",
        reply_markup=reply_markup
    )

async def hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plan, today_iso = get_today_plan()
    if not plan:
        await update.message.reply_text(f"No tengo datos de entrenamiento para la fecha de hoy ({today_iso}).")
        return
    text = format_plan_text(plan)
    await update.message.reply_markdown(text)

# --- Conversation Flow ---
async def registrar_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    plan, today_iso = get_today_plan()
    if not plan:
        await update.message.reply_text("No hay sesión programada para hoy.")
        return ConversationHandler.END
        
    context.user_data['today_iso'] = today_iso
    context.user_data['plan'] = plan
    context.user_data['image_bytes'] = None
    
    reply_keyboard = [['Tal cual', 'Parcial', 'No pude entrenar']]
    await update.message.reply_text(
        "¿Cómo ha ido la sesión de hoy?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return RPE

async def registrar_rpe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['completed_status'] = update.message.text
    if context.user_data['plan']["tables"] == []: 
        context.user_data['rpe'] = None
        await update.message.reply_text("¿Tienes alguna molestia o dolor hoy? (Responde 'Ninguna' si estás bien)", reply_markup=ReplyKeyboardRemove())
        return PAIN
        
    await update.message.reply_text("Del 1 al 10, ¿cuál ha sido tu Esfuerzo Percibido (RPE)? (Envía un número)", reply_markup=ReplyKeyboardRemove())
    return PAIN

async def registrar_pain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'rpe' not in context.user_data or context.user_data['rpe'] is not None:
        try:
            context.user_data['rpe'] = int(update.message.text)
        except ValueError:
            await update.message.reply_text("Por favor, envía un número válido del 1 al 10.")
            return PAIN
            
    await update.message.reply_text("¿Tienes alguna molestia o dolor físico hoy? (Responde 'Ninguna' si estás bien)")
    return NOTES_AND_PHOTO

async def registrar_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['pain_notes'] = update.message.text
    await update.message.reply_text("Añade notas libres o *envía una captura de pantalla* (Strava, Garmin, notas). Si no tienes, escribe 'Ninguna'.")
    return FINAL

async def registrar_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    general_notes = ""
    
    # Check if user sent a photo
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        context.user_data['image_bytes'] = bytes(image_bytes)
        if update.message.caption:
            general_notes = update.message.caption
    else:
        general_notes = update.message.text
        
    context.user_data['general_notes'] = general_notes
    
    await update.message.reply_text("📊 Analizando tu sesión con Gemini 1.5 Pro...")
    
    plan = context.user_data['plan']
    # Find next session of this type to see if we need to adjust it
    context_type = plan['context'].split()[0] if plan['context'] else ""
    next_plan = get_next_session(context_type, context.user_data['today_iso']) if context_type else None
    
    prompt = f"""
    {SYSTEM_PROMPT}
    
    Sesión programada de hoy: {plan['context']}
    - Detalle: {format_plan_text(plan)}
    
    Lo que hizo el atleta:
    - Estado de completado: {context.user_data['completed_status']}
    - RPE: {context.user_data['rpe']}
    - Molestias reportadas: {context.user_data['pain_notes']}
    - Notas extra o contexto de imagen: {general_notes}
    """
    
    if next_plan:
        prompt += f"\nPróxima sesión similar programada: {format_plan_text(next_plan)}\n¿Deberíamos ajustar algo de esta próxima sesión en base a los datos de hoy?"
    
    try:
        contents = [prompt]
        if context.user_data.get('image_bytes'):
            image = Image.open(io.BytesIO(context.user_data['image_bytes']))
            contents.append(image)
            
        response = model.generate_content(contents)
        ai_feedback = response.text
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error generating AI feedback: {e}\n{error_details}")
        ai_feedback = "Error de conexión con la IA, pero tu sesión se ha guardado correctamente."
        
    database.log_session(
        user_id,
        context.user_data['today_iso'],
        context.user_data['completed_status'],
        context.user_data['rpe'],
        context.user_data['pain_notes'],
        context.user_data['general_notes'],
        ai_feedback,
        ""
    )
    
    await update.message.reply_text(f"🧠 *Análisis del Preparador:*\n\n{ai_feedback}", parse_mode='Markdown')
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Registro cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    database.init_db()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("hoy", hoy))
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('registrar', registrar_start)],
        states={
            RPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_rpe)],
            PAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_pain)],
            NOTES_AND_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_notes)],
            FINAL: [MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, registrar_final)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(conv_handler)
    print("Bot is polling with Gemini Pro...")
    application.run_polling()

if __name__ == '__main__':
    main()
