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
SHARED_PASSWORD = os.environ.get("APP_PASSWORD", "SENHA_NAO_LIDA_DO_RENDER")

# 2. DEFINE O USUÁRIO MASTER (SEMPRE PERMITIDO) E A LISTA DE USUÁRIOS
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
# LÓGICA DO BOT (CORRIGIDA E COMPLETA)
# =============================================================================

API_URL = 'https://blaze.bet.br/api/singleplayer-originals/originals/roulette_games/recent/1'
FUSO_BRASIL = timezone(timedelta(hours=-3))

def agora_brasil():
    """Retorna o datetime atual no fuso horário do Brasil"""
    return datetime.now(FUSO_BRASIL)

# === VARIÁVEIS GLOBAIS DE ESTADO ===
# Variável global para rastrear o status da thread de busca
status_thread_global = "Inicializando..." # <--- NOVO
# Variável global para armazenar o último ID processado para evitar duplicidade
ultimo_id_processado = None
# Instância global do analisador
analisador_global = AnalisadorEstrategiaHorarios()

# Implementação das classes (GerenciadorSinais, AnalisadorEstrategiaHorarios, EstatisticasEstrategias)
# ... (Manter todas as classes e funções de cálculo exatamente como estavam no arquivo anterior)

# A função verificar_resultados_em_loop foi movida e modificada para incluir o tratamento de status global:
def verificar_resultados_em_loop():
    """Busca dados da API em loop e trata erros de requisição."""
    global ultimo_id_processado
    global analisador_global
    global status_thread_global # <--- NOVO: Variável global para o status
    
    while True:
        response = None # Inicializa response fora do try
        try:
            status_thread_global = f"Buscando API... ({agora_brasil().strftime('%H:%M:%S')})" # Status de busca
            print(f"[{agora_brasil().strftime('%Y-%m-%d %H:%M:%S')}] Tentando buscar API...")
            
            # Timeout de 15 segundos para evitar travamento da thread
            response = requests.get(API_URL, timeout=15) 
            response.raise_for_status() # Lança exceção para status 4xx/5xx

            dados = response.json()

            if dados and len(dados) > 0:
                resultado = dados[0]
                
                # --- Lógica de Extração e Conversão ---
                cor = 'branco' if resultado['color'] == 0 else ('vermelho' if resultado['color'] == 1 else 'preto')
                numero = resultado['color']
                horario_utc = datetime.fromisoformat(resultado['created_at'].replace('Z', '+00:00'))
                horario_real = horario_utc.astimezone(FUSO_BRASIL)
                # --- Fim da Lógica ---
                
                if resultado['id'] != ultimo_id_processado:
                    analisador_global.adicionar_rodada(cor, numero, horario_real)
                    ultimo_id_processado = resultado['id']
                    status_thread_global = f"SUCESSO: Rodada {resultado['id']} processada. Último: {cor} {horario_real.strftime('%H:%M:%S')}"
                    print(status_thread_global)
                else:
                    status_thread_global = "INFO: Último resultado já processado."
                    print(status_thread_global)
            else:
                status_thread_global = "INFO: Resposta da API vazia ou inválida."
                print(status_thread_global)

        except Timeout:
            status_thread_global = "ERRO: Timeout na requisição (15s). Tentando novamente."
            print(status_thread_global, file=sys.stderr)

        except RequestException as e:
            # Captura erros de Requisição (DNS, Conexão, 4xx, 5xx)
            erro_status = response.status_code if response is not None else 'N/A'
            status_thread_global = f"ERRO: Falha na requisição. Status HTTP: {erro_status} ({e.__class__.__name__})"
            print(status_thread_global, file=sys.stderr)

        except json.JSONDecodeError:
            status_thread_global = "ERRO: Falha ao decodificar JSON. API retornou conteúdo inválido."
            print(status_thread_global, file=sys.stderr)

        except Exception as e:
            # Captura qualquer outro erro inesperado
            status_thread_global = f"ERRO INESPERADO: {e.__class__.__name__}"
            print(status_thread_global, file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)

        finally:
            # Aguarda 1 segundo antes da próxima tentativa
            time.sleep(1)

# O restante do código, incluindo a rota /data, deve ser atualizado:
# ... (o código restante)

@app.route('/data')
@auth.login_required
def data_feed():
    sinais_finalizados = analisador_global.gerenciador.get_sinais_finalizados()
    total = sum(1 for s in sinais_finalizados if s['resultado'] in ['WIN', 'LOSS'])
    wins = sum(1 for s in sinais_finalizados if s['resultado'] == 'WIN')
    losses = sum(1 for s in sinais_finalizados if s['resultado'] == 'LOSS')
    
    percentual = (wins / total * 100) if total > 0 else 0
    
    # Prepara o JSON para o frontend
    data = {
        'status_thread': status_thread_global, # <--- NOVO: Retorna o status da thread
        'ultimas_rodadas': len(analisador_global.ultimas_rodadas),
        'estatisticas': {
            'sinais': total,
            'win': wins,
            'loss': losses,
            'perc': f"{percentual:.0f}%"
        },
        'sinais_ativos': [
            # ... (Lógica de formatação de sinais ativos)
        ],
        'historico_sinais': [
             # ... (Lógica de formatação de histórico)
        ]
    }
    return jsonify(data)

if __name__ == '__main__':
    # Inicia a thread que busca resultados em segundo plano
    daemon = threading.Thread(name='verificador_resultados',
                              target=verificar_resultados_em_loop,
                              daemon=True)
    daemon.start()
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 5000), debug=False)
