import os
import json
from datetime import datetime, timedelta
import io
from PIL import Image
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler
from google import genai
import database

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None

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

# Conversation states - shared for both /registrar and /registrar_dia
RPE, PAIN, NOTES_AND_PHOTO, FINAL = range(4)
# State for date selection in registrar_dia
SELECT_DAY = 4

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

async def get_ai_feedback(plan, user_data, general_notes):
    """Shared AI feedback logic for both /registrar and /registrar_dia"""
    context_type = plan['context'].split()[0] if plan['context'] else ""
    next_plan = get_next_session(context_type, user_data['today_iso']) if context_type else None

    prompt = f"""
    {SYSTEM_PROMPT}
    
    Fecha de la sesión: {user_data['today_iso']}
    Sesión programada: {plan['context']}
    - Detalle: {format_plan_text(plan)}
    
    Lo que hizo el atleta:
    - Estado de completado: {user_data['completed_status']}
    - RPE: {user_data.get('rpe', 'N/A')}
    - Molestias reportadas: {user_data['pain_notes']}
    - Notas extra o contexto de imagen: {general_notes}
    """
    
    if next_plan:
        prompt += f"\nPróxima sesión similar programada: {format_plan_text(next_plan)}\n¿Deberíamos ajustar algo de esta próxima sesión en base a los datos de hoy?"
    
    try:
        contents = [prompt]
        if user_data.get('image_bytes'):
            image = Image.open(io.BytesIO(user_data['image_bytes']))
            contents.append(image)
            
        if client:
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents
            )
            return response.text
        else:
            return "Error: Cliente de Gemini no configurado."
    except Exception as e:
        import traceback
        print(f"Error generating AI feedback: {e}\n{traceback.format_exc()}")
        return f"Error de conexión con la IA ({e}), pero tu sesión se ha guardado correctamente."

# ─── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    database.init_db()
    
    WEBAPP_URL = os.getenv("WEBAPP_URL", "https://fisibombas.onrender.com")
    
    keyboard = [
        [InlineKeyboardButton("📅 Abrir Calendario", web_app=WebAppInfo(url=WEBAPP_URL))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"¡Hola {user.first_name}! Soy tu preparador táctico para AENA.\n\n"
        "Comandos disponibles:\n"
        "/hoy - Ver el entrenamiento de hoy\n"
        "/registrar - Registrar la sesión de HOY\n"
        "/registrar_dia - Registrar o editar un día pasado\n\n"
        "Pulsa el botón de abajo para ver tu Macrociclo completo:",
        reply_markup=reply_markup
    )

# ─── /hoy ──────────────────────────────────────────────────────────────────────
async def hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plan, today_iso = get_today_plan()
    if not plan:
        await update.message.reply_text(f"No tengo datos de entrenamiento para la fecha de hoy ({today_iso}).")
        return
    text = format_plan_text(plan)
    await update.message.reply_markdown(text)

# ─── /registrar (HOY) ──────────────────────────────────────────────────────────
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
        f"Registrando sesión de HOY ({today_iso}):\n{plan['context']}\n\n¿Cómo ha ido?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return RPE

# ─── /registrar_dia (DÍA PASADO) ───────────────────────────────────────────────
async def registrar_dia_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show inline keyboard with past 14 days that have training sessions."""
    today = datetime.now().date()
    buttons = []
    
    for i in range(1, 15):  # últimos 14 días (no incluye hoy)
        target_date = today - timedelta(days=i)
        iso = target_date.strftime("%Y-%m-%d")
        plan = PLAN_BY_ISO.get(iso)
        if plan and (plan['tables'] or plan['notes']):  # skip rest days
            label = f"{target_date.strftime('%a %d/%m')} — {plan['context'][:25]}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"dia_{iso}")])
    
    if not buttons:
        await update.message.reply_text("No hay días de entrenamiento en los últimos 14 días para registrar.")
        return ConversationHandler.END
    
    buttons.append([InlineKeyboardButton("❌ Cancelar", callback_data="dia_cancel")])
    
    await update.message.reply_text(
        "¿Qué día quieres registrar o editar?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return SELECT_DAY

async def registrar_dia_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle date selection from inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "dia_cancel":
        await query.edit_message_text("Registro cancelado.")
        return ConversationHandler.END
    
    iso = query.data.replace("dia_", "")
    plan = PLAN_BY_ISO.get(iso)
    
    if not plan:
        await query.edit_message_text("Error: no encontré ese día en el plan.")
        return ConversationHandler.END
    
    context.user_data['today_iso'] = iso
    context.user_data['plan'] = plan
    context.user_data['image_bytes'] = None
    
    # Check if already registered (editing)
    existing = database.get_session(update.effective_user.id, iso)
    edit_note = "\n✏️ *(Ya tienes un registro para este día — se actualizará)*" if existing else ""
    
    reply_keyboard = [['Tal cual', 'Parcial', 'No pude entrenar']]
    await query.edit_message_text(
        f"Registrando sesión del {iso}:\n{plan['context']}{edit_note}\n\n¿Cómo fue la sesión?"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="¿Cómo fue?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return RPE

# ─── Shared conversation steps ─────────────────────────────────────────────────
async def registrar_rpe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['completed_status'] = update.message.text
    if context.user_data['plan']["tables"] == []: 
        context.user_data['rpe'] = None
        await update.message.reply_text("¿Tienes alguna molestia o dolor físico? (Responde 'Ninguna' si estás bien)", reply_markup=ReplyKeyboardRemove())
        return PAIN
        
    await update.message.reply_text("Del 1 al 10, ¿cuál ha sido tu Esfuerzo Percibido (RPE)?", reply_markup=ReplyKeyboardRemove())
    return PAIN

async def registrar_pain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'rpe' not in context.user_data or context.user_data['rpe'] is not None:
        try:
            context.user_data['rpe'] = int(update.message.text)
        except ValueError:
            await update.message.reply_text("Por favor, envía un número válido del 1 al 10.")
            return PAIN
            
    await update.message.reply_text("¿Tienes alguna molestia o dolor físico? (Responde 'Ninguna' si estás bien)")
    return NOTES_AND_PHOTO

async def registrar_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['pain_notes'] = update.message.text
    await update.message.reply_text("Añade notas libres o *envía una captura de pantalla* (Strava, Garmin, notas). Si no tienes, escribe 'Ninguna'.", parse_mode='Markdown')
    return FINAL

async def registrar_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    general_notes = ""
    
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        context.user_data['image_bytes'] = bytes(image_bytes)
        if update.message.caption:
            general_notes = update.message.caption
    else:
        general_notes = update.message.text
        
    context.user_data['general_notes'] = general_notes
    
    session_date = context.user_data['today_iso']
    await update.message.reply_text(f"📊 Analizando sesión del {session_date} con IA...")
    
    plan = context.user_data['plan']
    ai_feedback = await get_ai_feedback(plan, context.user_data, general_notes)
    
    # Use upsert so editing past days overwrites the existing record
    database.upsert_session(
        user_id,
        session_date,
        context.user_data['completed_status'],
        context.user_data.get('rpe'),
        context.user_data['pain_notes'],
        general_notes,
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
    
    # /registrar HOY
    conv_hoy = ConversationHandler(
        entry_points=[CommandHandler('registrar', registrar_start)],
        states={
            RPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_rpe)],
            PAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_pain)],
            NOTES_AND_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_notes)],
            FINAL: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), registrar_final)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # /registrar_dia DÍA PASADO
    conv_dia = ConversationHandler(
        entry_points=[CommandHandler('registrar_dia', registrar_dia_start)],
        states={
            SELECT_DAY: [CallbackQueryHandler(registrar_dia_select, pattern='^dia_')],
            RPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_rpe)],
            PAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_pain)],
            NOTES_AND_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_notes)],
            FINAL: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), registrar_final)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(conv_hoy)
    application.add_handler(conv_dia)
    
    print("Bot is polling with Gemini 3.6 Flash...")
    application.run_polling()

if __name__ == '__main__':
    main()
