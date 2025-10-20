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

# --- CÓDIGO DE SEGURANÇA (AUTENTICAÇÃO) ---
auth = HTTPBasicAuth()

SHARED_PASSWORD = os.environ.get("APP_PASSWORD", "SENHA_NAO_LIDA_DO_RENDER")
MASTER_USER = "adm"

ALLOWED_USERS_STR = os.environ.get("ALLOWED_USERS", "").strip()
ALLOWED_USERS_LIST = set([MASTER_USER] + [u.strip() for u in ALLOWED_USERS_STR.split(',') if u.strip()])

USERS = {
    user: SHARED_PASSWORD
    for user in ALLOWED_USERS_LIST
}

@auth.get_password
def get_password(username):
    return USERS.get(username)
# --- FIM DO CÓDIGO DE SEGURANÇA ---


# =============================================================================
# LÓGICA DO BOT (API ORIGINAL: /recent/1)
# =============================================================================

# API ORIGINAL REVERTIDA, CONFORME SOLICITADO
API_URL = 'https://blaze.bet/api/singleplayer-originals/originals/roulette_games/recent/1' 
FUSO_BRASIL = timezone(timedelta(hours=-3))

# HEADERS ADICIONADOS PARA FAZER A REQUISIÇÃO PARECER UM NAVEGADOR
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Connection': 'keep-alive',
}

def agora_brasil():
    """Retorna o datetime atual no fuso horário do Brasil"""
    return datetime.now(FUSO_BRASIL)

# === ESQUELETO DAS CLASSES (MANTIDO) ===

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
        # Lógica de processamento de resultado...
        pass
    def get_sinais_ativos(self): return []
    def get_sinais_finalizados(self): return list(self.historico_finalizados)

class AnalisadorEstrategiaHorarios:
    def __init__(self):
        self.ultimas_rodadas = deque(maxlen=None) 
        self.gerenciador = GerenciadorSinais()
    def adicionar_rodada(self, cor, numero, horario_real):
        self.ultimas_rodadas.append((cor, numero, horario_real))
        self.gerenciador.processar_resultado(horario_real, cor)

# =============================================================================
# INSTANCIAÇÃO GLOBAL
# =============================================================================
analisar_global = AnalisadorEstrategiaHorarios()
last_id_processed = None 

# =============================================================================
# FUNÇÃO DE BUSCA DE DADOS EM SEGUNDO PLANO (AJUSTADA PARA /recent/1)
# =============================================================================

def verificar_resultados():
    """Busca o último resultado da Blaze e processa se for novo."""
    global last_id_processed
    
    REQUEST_TIMEOUT = 30
    
    while True:
        try:
            print(f"THREAD: Tentando buscar API (Original /recent/1). Tempo limite: {REQUEST_TIMEOUT}s. last_id_processed: {last_id_processed}", file=sys.stderr)
            
            # 1. Busca os resultados com timeout E HEADERS
            response = requests.get(API_URL, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            response.raise_for_status() 
            data = response.json()
            
            # --- MUDANÇA: API /recent/1 retorna uma lista, pegamos o primeiro item ---
            if not isinstance(data, list) or not data:
                print("THREAD: Resposta inesperada (não é uma lista vazia).", file=sys.stderr)
                time.sleep(3)
                continue
            
            last_game = data[0]
            game_id = last_game.get('id')
            
            # Ignora resultados que já foram processados
            if last_id_processed is not None and game_id <= last_id_processed:
                time.sleep(3)
                continue

            # Mapeamento de cores (a API /recent/1 retorna 0, 1, 2 como inteiros)
            cor_int = last_game.get('color')
            color_map = {0: 'vermelho', 1: 'preto', 2: 'branco'}
            
            cor = color_map.get(cor_int)
            numero = last_game.get('roll')
            created_at_str = last_game.get('created_at')
            
            if cor is not None and numero is not None and created_at_str:
                horario_utc = datetime.strptime(created_at_str.split('.')[0], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                horario_brasil = horario_utc.astimezone(FUSO_BRASIL)
                
                # 2. Processa o novo resultado
                analisar_global.adicionar_rodada(cor, numero, horario_brasil)
                last_id_processed = max(last_id_processed or 0, game_id) 
                
                print(f"THREAD: SUCESSO! Rodada {numero} ({cor}) processada. ID: {last_id_processed}", file=sys.stderr)
            
        except HTTPError as e:
            # ESTE VAI CAPTURAR O 451
            print(f"THREAD ERRO: HTTPError ao buscar API: {e}. ESTE ERA O ERRO 451 ORIGINAL.", file=sys.stderr)
        except requests.exceptions.RequestException as e:
            # Captura Timeout, ConnectionError
            print(f"THREAD ERRO: RequestException (rede/tempo limite): {e}", file=sys.stderr)
        except json.JSONDecodeError:
            print("THREAD ERRO: Erro ao decodificar JSON da API.", file=sys.stderr)
        except Exception as e:
            print(f"THREAD ERRO CRÍTICO: Erro inesperado ao processar resultado. Detalhes abaixo:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            
        time.sleep(3)


# =============================================================================
# FLASK E ROTAS
# =============================================================================

app = Flask(__name__)

@app.route('/')
@auth.login_required
def index():
    return render_template('index.html') 

@app.route('/data')
@auth.login_required
def data():
    # Coleta sinais e estatísticas (Lógica mantida)
    gerenciador = analisar_global.gerenciador 
    sinais_finalizados = gerenciador.get_sinais_finalizados()
    todas_estatisticas = gerenciador.estatisticas.get_todas_estatisticas()
    
    # --- CÁLCULO DE ESTATÍSTICAS ---
    hoje = agora_brasil().date()
    sinais_finalizados_hoje = [s for s in sinais_finalizados if s['horario_previsto'].date() == hoje]
    total = len(sinais_finalizados_hoje)
    wins = sum(1 for s in sinais_finalizados_hoje if s['resultado'] == 'WIN')
    losses = sum(1 for s in sinais_finalizados_hoje if s['resultado'] == 'LOSS')
    percentual = (wins / total * 100) if total > 0 else 0

    # --- MONTA RESPOSTA DE DADOS ---
    todas_rodadas = list(analisar_global.ultimas_rodadas) 
    
    ultima_rodada = None
    if todas_rodadas:
        r = todas_rodadas[-1]
        ultima_rodada = {
            'cor': r[0],
            'numero': r[1],
            'horario': r[2].strftime('%H:%M:%S')
        }

    ultimas_10_rodadas_raw = todas_rodadas[-10:]
    ultimas_10_rodadas = [
        {
            'cor': r[0],
            'numero': r[1],
            'horario': r[2].strftime('%H:%M:%S')
        } for r in ultimas_10_rodadas_raw
    ]
    
    data = {
        'ultima_rodada': ultima_rodada, 
        'ultimas_10_rodadas': ultimas_10_rodadas, 
        'estatisticas': {
            'sinais': total,
            'win': wins,
            'loss': losses,
            'perc': f"{percentual:.0f}%"
        },
        'sinais_ativos': [
            {
                'horario': s['horario_previsto'].strftime('%H:%M'),
                'forca': f"{s['nivel_confluencia']} ({s['confluencias']})",
                'estrategias': ', '.join([e.split('. ')[1] if '. ' in e else e for e in s['estrategias']]),
                'nivel': s['nivel_confluencia']
            } for s in sorted(gerenciador.get_sinais_ativos(), key=lambda x: x['horario_previsto'])
        ],
        'historico_sinais': [
             {
                'horario': s['horario_previsto'].strftime('%H:%M'),
                'forca': f"{s['nivel_confluencia']} ({s['confluencias']})",
                'estrategias': ', '.join([e.split('. ')[1] if '. ' in e else e for e in s['estrategias']]),
                'resultado': s['resultado']
            } for s in sinais_finalizados
        ]
    }
    return jsonify(data)


# =============================================================================
# INICIALIZAÇÃO DA THREAD
# =============================================================================
daemon = threading.Thread(name='verificador_resultados',
                          target=verificar_resultados,
                          daemon=True)

if not daemon.is_alive():
    daemon.start()


if __name__ == '__main__':
    # O gunicorn usará 0.0.0.0:8080. Esta linha é apenas para debug local.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
