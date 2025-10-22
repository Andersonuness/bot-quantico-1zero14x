# ===============================================
# 1ZERO14X - Versão Web (Render / Flask)
# ===============================================
import os
import threading
import time
import requests
from datetime import datetime, timedelta, timezone
from collections import deque, defaultdict
from flask import Flask, jsonify, render_template
from flask_httpauth import HTTPBasicAuth

# -------------------------------
# Configurações gerais e API Blaze
# -------------------------------
API_URL = 'https://blaze.bet.br/api/singleplayer-originals/originals/roulette_games/recent/1'
FUSO_BRASIL = timezone(timedelta(hours=-3))

def agora_brasil():
    return datetime.now(FUSO_BRASIL)

def buscar_dados_api(api_url):
    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get('data', [])
    except Exception as e:
        print(f"[ERRO API] {e}")
        return []

def processar_rodada(rodadas_data):
    if not rodadas_data:
        return None, None, None
    rodada = rodadas_data[0]
    cor = rodada.get('color', '').lower()
    numero = rodada.get('roll')
    horario_utc_str = rodada.get('created_at')
    if horario_utc_str:
        try:
            horario_utc = datetime.fromisoformat(horario_utc_str.replace('Z', '+00:00'))
            horario_brasil = horario_utc.astimezone(FUSO_BRASIL)
            return cor, numero, horario_brasil
        except:
            return cor, numero, None
    return cor, numero, None

# ----------------------------------------
# CLASSES ORIGINAIS (mantém tua lógica toda)
# ----------------------------------------

# === AQUI cola todas as tuas classes originais ===
# EstatisticasEstrategias, GerenciadorSinais e AnalisadorEstrategiaHorarios
# (copiar exatamente como estão no teu código atual)
# ----------------------------------------

# Inicializa o analisador global
analisar_global = None
ultimo_id_processado = None

# ----------------------------------------
# Flask e autenticação
# ----------------------------------------
app = Flask(__name__, template_folder="modelos")
auth = HTTPBasicAuth()

USUARIOS_VALIDOS = {"adm": "P@$1zero14x!"}
for i in range(1, 21):
    USUARIOS_VALIDOS[f"user{i:02}"] = "P@$1zero14x!"

@auth.verify_password
def verificar(usuario, senha):
    return USUARIOS_VALIDOS.get(usuario) == senha

# ----------------------------------------
# Função de coleta em thread
# ----------------------------------------
def iniciar_coleta_blaze():
    global ultimo_id_processado
    global analisar_global

    analisar_global = AnalisadorEstrategiaHorarios()
    print("🔄 Iniciando coleta da API Blaze...")

    while True:
        try:
            dados_rodadas = buscar_dados_api(API_URL)
            if dados_rodadas:
                rodada = dados_rodadas[0]
                rodada_id = rodada.get('id')

                if rodada_id and rodada_id != ultimo_id_processado:
                    cor, numero, horario_real = processar_rodada(dados_rodadas)
                    if cor and numero is not None and horario_real:
                        print(f"[{horario_real.strftime('%H:%M:%S')}] {cor.upper()} {numero}")
                        analisar_global.adicionar_rodada(cor, numero, horario_real)
                        ultimo_id_processado = rodada_id

                analisar_global.gerenciador.limpar_dados_antigos()
            time.sleep(3)
        except Exception as e:
            print(f"[ERRO THREAD] {e}")
            time.sleep(5)

@app.before_first_request
def start_thread():
    t = threading.Thread(target=iniciar_coleta_blaze, daemon=True)
    t.start()

# ----------------------------------------
# Rotas do site
# ----------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data")
@auth.login_required
def data():
    """Retorna dados consolidados para o front"""
    if not analisar_global:
        return jsonify({"status": "aguardando dados..."})

    sinais_ativos = analisar_global.gerenciador.get_sinais_ativos()
    sinais_finalizados = analisar_global.gerenciador.get_sinais_finalizados()
    estatisticas = analisar_global.gerenciador.estatisticas.get_todas_estatisticas()

    return jsonify({
        "status": "ok",
        "ativos": len(sinais_ativos),
        "finalizados": len(sinais_finalizados),
        "estatisticas": estatisticas,
        "sinais_ativos": sinais_ativos[-5:],
        "sinais_finalizados": sinais_finalizados[-5:]
    })

# ----------------------------------------
# Execução
# ----------------------------------------
if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 10000))
    print(f"🚀 Servidor 1ZERO14X ativo na porta {porta}")
    app.run(host="0.0.0.0", port=porta)
