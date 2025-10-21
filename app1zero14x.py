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
# LÓGICA DO BOT (API ORIGINAL)
# =============================================================================

# URL FINAL CORRIGIDA
API_URL = 'https://blaze.bet/api/singleplayer-originals/originals/roulette_games/recent/1'
FUSO_BRASIL = timezone(timedelta(hours=-3))

def agora_brasil():
    """Retorna o datetime atual no fuso horário do Brasil"""
    return datetime.now(FUSO_BRASIL)

# --- CONFIGURAÇÃO DO PROXY ---
# Pega as variáveis de ambiente (HTTPS_PROXY é a mais importante para a Blaze)
PROXY_HTTP = os.environ.get("HTTP_PROXY")
PROXY_HTTPS = os.environ.get("HTTPS_PROXY")

# Cria o dicionário de proxies (Será None se as variáveis não existirem)
PROXIES = {}
if PROXY_HTTP:
    PROXIES['http'] = PROXY_HTTP
if PROXY_HTTPS:
    PROXIES['https'] = PROXY_HTTPS

# Exemplo de como ficaria o dicionário (se estiver configurado):
# PROXIES = {'http': 'http://endereco:porta', 'https': 'http://endereco:porta'}
# -----------------------------


# === ESQUELETO DAS CLASSES ===
# ... (Classes EstatisticasEstrategias, GerenciadorSinais, AnalisadorEstrategiaHorarios inalteradas)
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
        self.ultimas_rodadas = deque(maxlen=100) 
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
# FUNÇÃO DE BUSCA DE DADOS EM SEGUNDO PLANO (AGORA COM PROXY)
# =============================================================================

def verificar_resultados():
    """Busca o último resultado da Blaze e processa se for novo, usando proxy se configurado."""
    global last_id_processed
    
    # Informa se está usando proxy
    if PROXIES:
        proxy_info = PROXIES.get('https') or PROXIES.get('http')
        print(f"[THREAD] Iniciando busca com PROXY: {proxy_info}", file=sys.stderr)
    else:
        print("[THREAD] Iniciando busca SEM PROXY (dependendo do IP do Render).", file=sys.stderr)

    while True:
        try:
            print(f"[THREAD] Tentando buscar API. Último ID: {last_id_processed}", file=sys.stderr)
            
            # 1. Busca os resultados (Adicionado 'proxies=PROXIES')
            response = requests.get(API_URL, timeout=10, proxies=PROXIES) 
            
            # 2. TRATAMENTO DE ERROS (lança HTTPError)
            response.raise_for_status() 
            data = response.json()
            
            # ... (Restante da lógica de processamento de dados inalterada) ...
            print(f"[THREAD] Busca API OK. Resultados encontrados: {len(data)}", file=sys.stderr)
            
            # 3. Processa os resultados
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
                print(f"[THREAD] Processamento BEM SUCEDIDO. {len(new_results)} novos resultados. Última rodada ID: {last_id_processed}", file=sys.stderr)

        # Trata erros específicos
        except requests.exceptions.RequestException as e:
            # O ERRO DE BLOQUEIO DE IP/TIMEOUT CONTINUARÁ AQUI SE NÃO HOUVER PROXY FUNCIONAL
            print(f"[ERRO THREAD] RequestException (Rede/Timeout/Bloqueio/Proxy): {e}", file=sys.stderr)
        except Exception as e:
            # Captura qualquer erro inesperado
            print(f"[ERRO THREAD] Erro inesperado: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            
        time.sleep(3)


# =============================================================================
# FLASK E ROTAS
# =============================================================================

app = Flask(__name__)

# ROTA HEALTH CHECK
@app.route('/health')
def health_check():
    """Rota para o servidor verificar se o app está vivo."""
    return 'OK', 200

@app.route('/')
@auth.login_required
def index():
    return render_template('index.html') 

@app.route('/data')
@auth.login_required
def data():
    # ... (Restante do bloco /data inalterado) ...
    gerenciador = analisar_global.gerenciador 
    sinais_finalizados = gerenciador.get_sinais_finalizados()
    
    # --- CÁLCULO DE ESTATÍSTICAS (RESUMIDO) ---
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
# INICIALIZAÇÃO DA THREAD (FORA DE __main__)
# =============================================================================
daemon = threading.Thread(name='verificador_resultados',
                          target=verificar_resultados,
                          daemon=True)

if not daemon.is_alive():
    daemon.start()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
