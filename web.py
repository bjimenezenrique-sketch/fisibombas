import os
import json
from flask import Flask, request, jsonify, render_template
from google import genai
from dotenv import load_dotenv
import database

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None

app = Flask(__name__)

# ── Objectives and starting points for each test ──────────────────────────────
TESTS = {
    "60m":         {"label": "60 metros",         "start": 8.50,  "goal": 8.00,  "unit": "s",    "lower_is_better": True},
    "1500m":       {"label": "1500 metros",        "start": 345.0, "goal": 315.0, "unit": "s",    "lower_is_better": True},  # seconds
    "banca_40kg":  {"label": "Banca 40 kg",        "start": 20.0,  "goal": 30.0,  "unit": "reps", "lower_is_better": False},
    "dominadas":   {"label": "Dominadas 30s",      "start": 10.0,  "goal": 18.0,  "unit": "reps", "lower_is_better": False},
    "flexibilidad":{"label": "Flexibilidad cajón", "start": 17.0,  "goal": 38.0,  "unit": "cm",   "lower_is_better": False},
    "cuerda_6m":   {"label": "Cuerda 6 metros",    "start": 30.0,  "goal": 12.0,  "unit": "s",    "lower_is_better": True},
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/records', methods=['GET'])
def get_records():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    records = database.get_all_records(user_id)
    return jsonify({"records": records})

@app.route('/api/plan', methods=['GET'])
def get_plan():
    with open('plan_data.json', 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
    return jsonify(plan_data)

# Error strings that indicate AI failed to generate proper feedback
FAILED_FEEDBACK_MARKERS = [
    "Error de conexión con la IA",
    "La IA está saturada",
    "Error:",
    "503",
    "UNAVAILABLE",
    "no está configurada",
]

def feedback_is_failed(text: str) -> bool:
    if not text:
        return True
    return any(marker in text for marker in FAILED_FEEDBACK_MARKERS)

@app.route('/api/regenerate-feedback', methods=['POST'])
def regenerate_feedback():
    """Re-run AI on a saved session that has a failed/missing feedback."""
    data = request.json
    user_id  = data.get('user_id')
    date_iso = data.get('date_iso')
    if not user_id or not date_iso:
        return jsonify({"error": "user_id and date_iso required"}), 400

    rec = database.get_session(user_id, date_iso)
    if not rec:
        return jsonify({"error": "No session found for that date"}), 404

    # Load plan for that day
    with open('plan_data.json', 'r', encoding='utf-8') as f:
        all_days = json.load(f)
    plan_by_iso = {d["iso"]: d for d in all_days}
    day = plan_by_iso.get(date_iso)
    if not day:
        return jsonify({"error": "Day not found in plan"}), 404

    if not client:
        return jsonify({"error": "Gemini client not configured"}), 500

    # Build the same prompt structure as the bot
    def fmt_plan(p):
        if not p.get("tables") and not p.get("notes"):
            return f"{p['day_name']} — Descanso absoluto."
        t = f"{p['day_name']} · Semana {p['week']} · {p['context']}\n"
        for table in p.get("tables", []):
            for row in table["rows"]:
                t += f"• {' | '.join(str(c) for c in row if c and c != '—')}\n"
        return t

    prompt = f"""Actúa como Preparador Físico de Alto Rendimiento para oposiciones AENA (doble umbral, High-Low, FNP extremo, atleta 80 kg).

Sesión del {date_iso}: {day.get('context')}
{fmt_plan(day)}

Registro del atleta:
- Estado: {rec.get('completed_status')}
- RPE: {rec.get('rpe')}
- Molestias: {rec.get('pain_notes')}
- Notas: {rec.get('general_notes')}

Evalúa su rendimiento y da feedback profesional. Si hay fatiga o problemas, ajusta la próxima sesión similar. Máximo 150 palabras, tono técnico y motivador."""

    import time
    last_err = None
    # Try different models to bypass saturation
    fallback_models = ['gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.0-flash']
    
    for model_name in fallback_models:
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            new_feedback = response.text
            # Save updated feedback to DB
            database.upsert_session(
                user_id, date_iso,
                rec.get('completed_status'), rec.get('rpe'),
                rec.get('pain_notes'), rec.get('general_notes'),
                new_feedback, rec.get('ai_adjustment', '')
            )
            return jsonify({"ok": True, "feedback": new_feedback})
        except Exception as e:
            last_err = e
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                print(f"Model {model_name} saturated, trying next...")
                time.sleep(1) # short wait before fallback
                continue
            else:
                break # break on non-503 errors

    return jsonify({"error": f"IA no disponible: {last_err}"}), 503

@app.route('/api/targets', methods=['GET'])
def get_targets():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    custom = database.get_targets(user_id)
    # Merge defaults with custom overrides
    result = {}
    for key, test in TESTS.items():
        result[key] = {
            "label": test["label"],
            "unit": test["unit"],
            "lower_is_better": test["lower_is_better"],
            "start": custom.get(key, {}).get("start", test["start"]),
            "goal":  custom.get(key, {}).get("goal",  test["goal"]),
            "is_custom": key in custom
        }
    return jsonify(result)

@app.route('/api/targets', methods=['POST'])
def save_target():
    data = request.json
    user_id   = data.get('user_id')
    test_name = data.get('test_name')
    start_val = data.get('start')
    goal_val  = data.get('goal')
    if not all([user_id, test_name, start_val is not None, goal_val is not None]):
        return jsonify({"error": "user_id, test_name, start and goal required"}), 400
    if test_name not in TESTS:
        return jsonify({"error": f"Unknown test. Valid: {list(TESTS.keys())}"}), 400
    database.save_target(user_id, test_name, float(start_val), float(goal_val))
    return jsonify({"ok": True})

@app.route('/api/progress', methods=['GET'])
def get_progress():
    """Returns progress toward objectives. Uses saved marks or estimates from AI."""
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    
    marks   = database.get_marks(user_id)
    records = database.get_all_records(user_id)
    custom_targets = database.get_targets(user_id)
    
    result = {}
    for key, default_test in TESTS.items():
        # Use custom start/goal if saved, otherwise use hardcoded defaults
        start = custom_targets.get(key, {}).get("start", default_test["start"])
        goal  = custom_targets.get(key, {}).get("goal",  default_test["goal"])
        lower_is_better = default_test["lower_is_better"]
        
        current_value = marks.get(key, {}).get("value")
        last_updated  = marks.get(key, {}).get("updated")
        
        if current_value is not None:
            total_to_improve = (start - goal) if lower_is_better else (goal - start)
            improved = (start - current_value) if lower_is_better else (current_value - start)
            pct = max(0, min(100, round((improved / total_to_improve) * 100))) if total_to_improve != 0 else 100
            status = "real"
        else:
            pct    = None
            status = "estimated"
        
        result[key] = {
            "label": default_test["label"],
            "unit":  default_test["unit"],
            "lower_is_better": lower_is_better,
            "start": start, "goal": goal,
            "current": current_value,
            "pct": pct, "status": status,
            "last_updated": last_updated
        }
    
    # For tests without marks, ask AI to estimate based on records
    tests_needing_estimate = [k for k, v in result.items() if v["status"] == "estimated"]
    if tests_needing_estimate and records and client:
        # Build a summary of training records for AI
        recent_records = records[:20]  # last 20 sessions
        records_summary = "\n".join([
            f"- {r['date']}: {r['status']}, RPE {r['rpe']}, molestias: {r['pain']}, notas: {r['notes'][:100] if r['notes'] else 'ninguna'}"
            for r in recent_records
        ])
        
        tests_str = ", ".join([TESTS[k]["label"] for k in tests_needing_estimate])
        
        prompt = f"""Eres un Preparador Físico de Alto Rendimiento para oposiciones AENA.
        
El atleta tiene las siguientes marcas de inicio y objetivos:
{chr(10).join([f"- {TESTS[k]['label']}: parte de {TESTS[k]['start']}{TESTS[k]['unit']}, objetivo {TESTS[k]['goal']}{TESTS[k]['unit']}" for k in tests_needing_estimate])}

Estos son sus últimos registros de entrenamiento (fecha, estado, RPE, molestias, notas):
{records_summary}

Basándote en la calidad de los entrenamientos, RPE, molestias y el progreso típico esperado en el macrociclo de doble umbral/High-Low, estima la probabilidad (0-100%) de que el atleta alcance el objetivo de cada prueba en el tiempo del plan (objetivo: semana 12, ~noviembre).

Devuelve SOLO un JSON válido con este formato exacto, sin texto adicional, sin markdown:
{{"60m": 72, "1500m": 65, "banca_40kg": 80, "dominadas": 55, "flexibilidad": 40, "cuerda_6m": 60}}

Solo incluye las pruebas que te haya indicado: {", ".join(tests_needing_estimate)}"""

        try:
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt
            )
            raw = response.text.strip()
            # Clean any markdown if present
            if "```" in raw:
                raw = raw.split("```")[1].replace("json", "").strip()
            estimates = json.loads(raw)
            for key in tests_needing_estimate:
                if key in estimates:
                    result[key]["pct"] = estimates[key]
                    result[key]["status"] = "estimated"
        except Exception as e:
            print(f"Error estimating progress: {e}")
            # Fallback: neutral 50%
            for key in tests_needing_estimate:
                result[key]["pct"] = 50
    elif tests_needing_estimate and not records:
        # No records at all — default to 0%
        for key in tests_needing_estimate:
            result[key]["pct"] = 0
    
    return jsonify(result)

@app.route('/api/mark', methods=['POST'])
def save_mark():
    """Save a performance mark for a test."""
    data = request.json
    user_id = data.get('user_id')
    test_name = data.get('test_name')
    value = data.get('value')
    
    if not all([user_id, test_name, value is not None]):
        return jsonify({"error": "user_id, test_name and value required"}), 400
    
    if test_name not in TESTS:
        return jsonify({"error": f"Unknown test. Valid: {list(TESTS.keys())}"}), 400
    
    database.save_mark(user_id, test_name, float(value))
    return jsonify({"ok": True})

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json
    question = data.get('question')
    
    if not client:
        return jsonify({"answer": "La API de Gemini no está configurada."})
        
    prompt = f"""Eres un Preparador Físico de Alto Rendimiento Olímpico y Táctico para oposiciones AENA (bomberos de aeropuerto). 
    Manejas el doble umbral (Ingebrigtsen), High-Low (Charlie Francis), gimnasia soviética y FNP extremo.
    Responde a la duda del atleta de forma técnica, directa y concisa (máximo 100 palabras):
    
    Pregunta: {question}"""
    
    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt
        )
        return jsonify({"answer": response.text})
    except Exception as e:
        return jsonify({"answer": f"Error: {e}"}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)
