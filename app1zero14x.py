import sys
import requests
import traceback
from requests.exceptions import Timeout, RequestException, HTTPError
from datetime import datetime, timedelta, timezone
from collections import deque, defaultdict
import threading
import time
import json
import os
from flask import Flask, render_template, jsonify
from flask_httpauth import HTTPBasicAuth

# --- AUTENTICAÇÃO ---
auth = HTTPBasicAuth()
SHARED_PASSWORD = os.environ.get("APP_PASSWORD", "SENHA_NAO_LIDA_DO_RENDER")
MASTER_USER = "adm"

ALLOWED_USERS_STR = os.environ.get("ALLOWED_USERS", "").strip()
ALLOWED_USERS_LIST = set([MASTER_USER] + [u.strip() for u in ALLOWED_USERS_STR.split(',') if u.strip()])

USERS = {user: SHARED_PASSWORD for user in ALLOWED_USERS_LIST}

@auth.get_password
def get_password(username):
    return USERS.get(username)

# --- CONFIGURAÇÕES ---
API_URL = 'https://blaze.bet.br/api/singleplayer-originals/originals/roulette_games/recent/1'
FUSO_BRASIL = timezone(timedelta(hours=-3))

def agora_brasil():
    return datetime.now(FUSO_BRASIL)

# --- CLASSES PRINCIPAIS (RESUMIDAS) ---
class EstatisticasEstrategias:
    def __init__(self):
        self.estatisticas = defaultdict(lambda: {'sinais': 0, 'acertos': 0})

    def registrar_sinal(self, estrategia_nome):
        self.estatisticas[estrategia_nome]['sinais'] += 1

    def registrar_acerto(self, estrategia_nome):
        if self.estatisticas[estrategia_nome]['sinais'] > 0:
            self.estatisticas[estrategia_nome]['acertos'] += 1

    def get_todas_estatisticas(self):
        return self.estatisticas


class GerenciadorSinais:
    def __init__(self):
        self.todas_estrategias = []
        self.sinais_agrupados = defaultdict(list)
        self.sinais_ativos = []
        self.historico_finalizados = deque(maxlen=20)
        self.estatisticas = EstatisticasEstrategias()
        self.config_confluencia = {'baixa': 3, 'media': 4, 'alta': 5, 'minima_ativa': 4}

    def processar_resultado(self, horario_resultado, cor):
        pass

    def get_sinais_ativos(self): return []
    def get_sinais_finalizados(self): return list(self.historico_finalizados)


class AnalisadorEstrategiaHorarios:
    def __init__(self):
        self.ultimas_rodadas = deque(maxlen=100)
        self.gerenciador = GerenciadorSinais()

    def adicionar_rodada(self, cor, numero, horario_real):
        self.ultimas_rodadas.append((cor, numero, horario_real))
        self.gerenciador.processar_resultado(horario_real, cor)


# --- INSTÂNCIAS ---
analisar_global = AnalisadorEstrategiaHorarios()
last_id_processed = None

# --- THREAD DE COLETA ---
def verificar_resultados():
    global last_id_processed
    while True:
        try:
            print(f"[THREAD] Buscando dados da API... Último ID: {last_id_processed}", file=sys.stderr)
            response = requests.get(API_URL, timeout=10)
            response.raise_for_status()
            data = response.json()

            new_results = []
            for result in reversed(data):
                game_id = result.get('id')
                if last_id_processed is not None and game_id <= last_id_processed:
                    continue

                color_map = {0: 'vermelho', 1: 'preto', 2: 'branco'}
                cor = color_map.get(result.get('color'))
                numero = result.get('roll')
                created_at_str = result.get('created_at')

                if cor is not None and numero is not None and created_at_str:
                    horario_utc = datetime.strptime(created_at_str.split('.')[0], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                    horario_brasil = horario_utc.astimezone(FUSO_BRASIL)

                    new_results.append({
                        'id': game_id,
                        'cor': cor,
                        'numero': numero,
                        'horario': horario_brasil
                    })

            for result in new_results:
                analisar_global.adicionar_rodada(result['cor'], result['numero'], result['horario'])
                last_id_processed = max(last_id_processed or 0, result['id'])

            if new_results:
                print(f"[THREAD] {len(new_results)} novos resultados processados. Último ID: {last_id_processed}", file=sys.stderr)

        except Exception as e:
            print(f"[ERRO THREAD] {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

        time.sleep(3)


# --- FLASK ---
app = Flask(__name__)

@app.route('/')
@auth.login_required
def index():
    return render_template('index.html')

@app.route('/data')
@auth.login_required
def data():
    gerenciador = analisar_global.gerenciador
    todas_rodadas = list(analisar_global.ultimas_rodadas)
    ultima_rodada = None

    if todas_rodadas:
        r = todas_rodadas[-1]
        ultima_rodada = {'cor': r[0], 'numero': r[1], 'horario': r[2].strftime('%H:%M:%S')}

    ultimas_10_rodadas_raw = todas_rodadas[-10:]
    ultimas_10_rodadas = [{'cor': r[0], 'numero': r[1], 'horario': r[2].strftime('%H:%M:%S')} for r in ultimas_10_rodadas_raw]

    data = {
        'ultimo_resultado': ultima_rodada,
        'ultimas_10_rodadas': ultimas_10_rodadas,
        'estatisticas': {'sinais': 0, 'win': 0, 'loss': 0, 'perc': "0%"},
        'sinais_ativos': [],
        'historico_sinais': []
    }
    return jsonify(data)


# --- INÍCIO AUTOMÁTICO DA THREAD ---
if __name__ == '__main__':
    thread_api = threading.Thread(target=verificar_resultados, daemon=True)
    thread_api.start()
    print("🚀 Servidor Flask iniciado com coleta ativa (thread).", file=sys.stderr)
    app.run(host='0.0.0.0', port=5000)

