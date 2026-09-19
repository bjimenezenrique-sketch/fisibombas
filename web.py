import os
import sqlite3
from flask import Flask, request, jsonify, render_template
from google import genai
from dotenv import load_dotenv

# Load environment
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None

app = Flask(__name__)
DB_PATH = 'aena_bot.db'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/records', methods=['GET'])
def get_records():
    import database
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
        
    records = database.get_all_records(user_id)
    return jsonify({"records": records})

@app.route('/api/plan', methods=['GET'])
def get_plan():
    import json
    with open('plan_data.json', 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
    return jsonify(plan_data)

@app.route('/api/ask', methods=['POST'])
def ask():
    data = request.json
    question = data.get('question')
    
    if not client:
        return jsonify({"answer": "La API de Gemini no está configurada."})
        
    prompt = f"""
    Eres un Preparador Físico de Alto Rendimiento. 
    Responde a la duda del atleta sobre su entrenamiento:
    Pregunta: {question}
    
    Sé conciso y claro.
    """
    try:
        response = client.models.generate_content(
            model='gemini-1.5-pro',
            contents=prompt
        )
        return jsonify({"answer": response.text})
    except Exception as e:
        return jsonify({"answer": f"Error: {e}"}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)
