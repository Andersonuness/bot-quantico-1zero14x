import sys
import requests
from requests.exceptions import Timeout, RequestException 
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

# 1. PEGA A SENHA COMPARTILHADA DO RENDER
# Se o Render falhar, usa uma senha de fallback temporária para debug.
SHARED_PASSWORD = os.environ.get("APP_PASSWORD", "SENHA_NAO_LIDA_DO_RENDER")

# 2. DEFINE O USUÁRIO MASTER (SEMPRE PERMITIDO) E A LISTA DE USUÁRIOS
MASTER_USER = "adm"

# Pega a lista do Render e adiciona o Master para garantir
ALLOWED_USERS_STR = os.environ.get("ALLOWED_USERS", "").strip()
# Cria a lista de usuários únicos, garantindo que o master (adm) esteja sempre presente
ALLOWED_USERS_LIST = set([MASTER_USER] + [u.strip() for u in ALLOWED_USERS_STR.split(',') if u.strip()])

# CRIA UM DICIONÁRIO ONDE TODOS OS USUÁRIOS TÊM A MESMA SENHA
USERS = {
    user: SHARED_PASSWORD
    for user in ALLOWED_USERS_LIST
}

@auth.get_password
def get_password(username):
    # Retorna a senha associada ao nome de usuário
    return USERS.get(username)
# --- FIM DO CÓDIGO DE SEGURANÇA ---


# =============================================================================
# LÓGICA DO BOT
# =============================================================================

API_URL = 'https://blaze.bet.br/api/singleplayer-originals/originals/roulette_games/recent/1'
FUSO_BRASIL = timezone(timedelta(hours=-3))

def agora_brasil():
    """Retorna o datetime atual no fuso horário do Brasil"""
    return datetime.now(FUSO_BRASIL)

# === INÍCIO DAS CLASSES INTEGRADAS (Omitidas para brevidade, mas devem estar no seu arquivo) ===
# ... (AQUI VÃO AS CLASSES EstatisticasEstrategias, GerenciadorSinais e AnalisadorEstrategiaHorarios) ...
# Para garantir que o código seja funcional, vou colocar apenas o esqueleto necessário.

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
    def criar_estrategias_padrao(self):
        todas_estrategias = [
            "1. Pedra anterior + minuto", "2. Pedra posterior + minuto", "3. 2 pedras anteriores + minuto",
            "4. 2 pedras posteriores + minuto", "5. 2ª pedra anterior + minuto", "6. 2ª pedra posterior + minuto",
            "7. Ant+min+post", "8. Minuto invertido + hora", "9. Branco + 5min", "10. Branco + 10min",
            "11. Pedra 4 + 4min", "12. Pedra 14 + 5min", "13. Pedra 11 + 3min", "14. 2 pedras iguais +1h",
            "15. Minuto zero + pedra", "16. Soma 15/21 +10min", "17. 2ant+min+2post", "18. 2 brancos +3min",
            "19. Branco + Minuto Duplo", "20. 2 pedras iguais +14min", "21. Seq30 [1] +35min",
            "21. Seq30 [2] +3min", "21. Seq30 [3] +3min", "21. Seq30 [4] +5min", "21. Seq30 [5] +3min",
            "21. Seq30 [6] +5min", "21. Seq30 [7] +3min", "22. Dobra de Branco", "23. Gêmeas",
            "24. 50 sem Branco +4min", "25. 60 sem Branco +4min", "26. 80 sem Branco +4min"
        ]
        return {estrategia: True for estrategia in todas_estrategias}
    def is_estrategia_ativa(self, estrategia_nome): return True
    def adicionar_estrategia(self, estrategia, horario, minuto_destino, horario_base=None): pass
    def adicionar_sinal_direto(self, estrategia, horario, minuto_destino, horario_base=None): pass
    def verificar_confluencia(self, minuto_chave): pass
    def processar_resultado(self, horario_resultado, cor): pass
    def limpar_dados_antigos(self): pass
    def get_sinais_ativos(self): return []
    def get_sinais_finalizados(self): return list(self.historico_finalizados)

class AnalisadorEstrategiaHorarios:
    def __init__(self):
        self.ultimas_rodadas = deque(maxlen=None) 
        self.gerenciador = GerenciadorSinais()
    def adicionar_rodada(self, cor, numero, horario_real):
        self.ultimas_rodadas.append((cor, numero, horario_real))
        self.gerenciador.processar_resultado(horario_real, cor)
    def gerar_sinais_imediatos_apos_branco(self, horario_branco, numero_branco): pass
    def verificar_dois_brancos_juntos(self, horario_branco): pass 
    def estrategia_19_branco_minuto_duplo(self, horario_branco): pass 
    def estrategia_dobra_branco(self, horario_branco): pass 
    def verificar_30_sem_brancos(self, horario_atual): pass 
    def verificar_50_sem_brancos(self, horario_atual): pass 
    def verificar_60_sem_brancos(self, horario_atual): pass 
    def verificar_80_sem_brancos(self, horario_atual): pass 
    def gerar_sinais_pedra_atual(self, cor, numero, horario_real): pass 
    def verificar_duas_pedras_iguais(self, cor, numero, horario_real): pass 
    def verificar_minuto_final_zero(self, cor, numero, horario_real): pass 
    def verificar_soma_15_21(self, cor, numero, horario_real): pass 
    def verificar_gemeas(self, cor, numero, horario): pass 
    def calcular_minuto_destino_fixo(self, minuto_calculado): pass 
    def processar_estrategias_posteriores(self, cor, numero, horario_pedra): pass 

# =============================================================================
# INSTANCIAÇÃO GLOBAL
# =============================================================================
analisar_global = AnalisadorEstrategiaHorarios()
last_id_processed = None # Para evitar processar o mesmo jogo duas vezes

# =============================================================================
# FUNÇÃO DE BUSCA DE DADOS EM SEGUNDO PLANO (COM DIAGNÓSTICO)
# =============================================================================

def verificar_resultados():
    """Busca o último resultado da Blaze e processa se for novo."""
    global last_id_processed
    
    while True:
        try:
            print(f"THREAD: Tentando buscar API. last_id_processed: {last_id_processed}", file=sys.stderr)
            
            # 1. Busca os resultados
            response = requests.get(API_URL, timeout=10)
            response.raise_for_status() 
            data = response.json()
            
            print(f"THREAD: Busca API OK. Resultados encontrados: {len(data)}", file=sys.stderr)
            
            # 2. Processa os resultados do mais antigo para o mais novo
            new_results = []
            
            for result in reversed(data):
                game_id = result.get('id')
                
                # Ignora resultados que já foram processados
                if last_id_processed is not None and game_id <= last_id_processed:
                    continue
                
                # Mapeamento de cores (0: vermelho, 1: preto, 2: branco)
                color_map = {0: 'vermelho', 1: 'preto', 2: 'branco'}
                
                cor = color_map.get(result.get('color'))
                numero = result.get('roll')
                created_at_str = result.get('created_at')
                
                if cor is not None and numero is not None and created_at_str:
                    # Converte o timestamp UTC para o fuso horário do Brasil
                    horario_utc = datetime.strptime(created_at_str.split('.')[0], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                    horario_brasil = horario_utc.astimezone(FUSO_BRASIL)
                    
                    new_results.append({
                        'id': game_id,
                        'cor': cor,
                        'numero': numero,
                        'horario': horario_brasil
                    })
            
            # 3. Processa os novos resultados em ordem cronológica
            if new_results:
                print(f"THREAD: Processando {len(new_results)} novos resultados.", file=sys.stderr)
            
            for result in new_results:
                analisar_global.adicionar_rodada(result['cor'], result['numero'], result['horario'])
                last_id_processed = max(last_id_processed or 0, result['id']) 
            
            if new_results:
                print(f"THREAD: Última rodada ID processada: {last_id_processed}", file=sys.stderr)

        except requests.exceptions.RequestException as e:
            print(f"THREAD ERRO: RequestException ao buscar dados da API: {e}", file=sys.stderr)
        except json.JSONDecodeError:
            print("THREAD ERRO: Erro ao decodificar JSON da API.", file=sys.stderr)
        except Exception as e:
            # Qualquer outro erro, como falha no parsing de data, será capturado aqui.
            print(f"THREAD ERRO: Erro inesperado no verificador_resultados: {e}", file=sys.stderr)
            
        # Espera 3 segundos para a próxima verificação
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
    # Coleta sinais e estatísticas
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

    # --- NOVO CÓDIGO PARA PEGAR O ÚLTIMO RESULTADO E AS ÚLTIMAS 10 RODADAS ---
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
    # --------------------------------------------------------------------------
    
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
# INICIALIZAÇÃO DA THREAD (FORA do if __name__ para Gunicorn)
# =============================================================================
daemon = threading.Thread(name='verificador_resultados',
                          target=verificar_resultados,
                          daemon=True)

# Garante que a thread só inicie se não estiver ativa
if not daemon.is_alive():
    daemon.start()


if __name__ == '__main__':
    # Inicia o servidor Flask (APENAS para ambiente LOCAL de desenvolvimento)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
