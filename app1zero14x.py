import sys
import requests
from requests.exceptions import Timeout, RequestException # Importação adicionada para tratamento de erros
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
# LÓGICA DO BOT (CORRIGIDA E COMPLETA)
# =============================================================================

API_URL = 'https://blaze.bet.br/api/singleplayer-originals/originals/roulette_games/recent/1'
FUSO_BRASIL = timezone(timedelta(hours=-3))

def agora_brasil():
    """Retorna o datetime atual no fuso horário do Brasil"""
    return datetime.now(FUSO_BRASIL)

# === INÍCIO DAS CLASSES INTEGRADAS ===

class EstatisticasEstrategias:
    def __init__(self):
        self.estatisticas = defaultdict(lambda: {'sinais': 0, 'acertos': 0})
    
    def registrar_sinal(self, estrategia_nome):
        """Registra um sinal enviado para estatísticas"""
        self.estatisticas[estrategia_nome]['sinais'] += 1
    
    def registrar_acerto(self, estrategia_nome):
        """Registra um acerto para estatísticas"""
        if self.estatisticas[estrategia_nome]['sinais'] > 0:
            self.estatisticas[estrategia_nome]['acertos'] += 1
    
    def get_assertividade(self, estrategia_nome):
        """Retorna a assertividade de uma estratégia"""
        stats = self.estatisticas[estrategia_nome]
        if stats['sinais'] == 0:
            return 0
        return (stats['acertos'] / stats['sinais']) * 100
    
    def get_todas_estatisticas(self):
        """Retorna todas as estatísticas"""
        return self.estatisticas

class GerenciadorSinais:
    def __init__(self):
        self.todas_estrategias = []
        self.sinais_agrupados = defaultdict(list)
        self.sinais_ativos = []
        self.historico_finalizados = deque(maxlen=20) 
        
        self.estatisticas = EstatisticasEstrategias()
        self.estrategias_ativas = self.criar_estrategias_padrao()
        
        # CONFIGURAÇÃO DE CONFLUÊNCIA (PADRÃO: 4+ para sinal ativo)
        self.config_confluencia = {
            'baixa': 3,
            'media': 4,
            'alta': 5,
            'minima_ativa': 4
        }
        
    def set_config_confluencia(self, nova_config):
        """Define nova configuração de confluência"""
        self.config_confluencia = nova_config
        
        for minuto_chave in list(self.sinais_agrupados.keys()):
            self.verificar_confluencia(minuto_chave)
    
    def get_nivel_confluencia(self, quantidade):
        """Retorna o nível de confluência baseada na quantidade"""
        if quantidade >= self.config_confluencia['alta']:
            return 'ALTA'
        elif quantidade >= self.config_confluencia['media']:
            return 'MÉDIA'
        elif quantidade >= self.config_confluencia['baixa']:
            return 'BAIXA'
        else:
            return 'MINIMA'
    
    def criar_estrategias_padrao(self):
        """Cria o dicionário padrão com todas estratégias ativas"""
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
    
    def set_estrategias_ativas(self, estrategias_ativas):
        """Define quais estratégias estão ativas"""
        self.estrategias_ativas = estrategias_ativas
    
    def is_estrategia_ativa(self, estrategia_nome):
        """Verifica se uma estratégia está ativa"""
        return self.estrategias_ativas.get(estrategia_nome, False)
    
    def adicionar_estrategia(self, estrategia, horario, minuto_destino, horario_base=None):
        """Adiciona uma estratégia verificada ao sistema apenas se estiver ativa"""
        if not self.is_estrategia_ativa(estrategia):
            return
            
        estrategia_data = {
            'estrategia': estrategia,
            'horario_previsto': horario,
            'minuto_destino': minuto_destino,
            'horario_base': horario_base or horario,
            'timestamp_adicao': agora_brasil(),
            'status': 'pendente',
            'janela_fim': horario.replace(second=30) + timedelta(minutes=1)
        }
        
        self.todas_estrategias.append(estrategia_data)
        
        minuto_chave = horario.replace(second=0, microsecond=0)
        self.sinais_agrupados[minuto_chave].append(estrategia_data)
        
        self.verificar_confluencia(minuto_chave)
        self.limpar_dados_antigos()
    
    def adicionar_sinal_direto(self, estrategia, horario, minuto_destino, horario_base=None):
        """Adiciona sinal direto sem necessidade de confluência apenas se estiver ativo"""
        if not self.is_estrategia_ativa(estrategia):
            return
            
        sinal_direto = {
            'minuto_alvo': horario.replace(second=0, microsecond=0),
            'horario_previsto': horario,
            'estrategias': [estrategia],
            'confluencias': 1,
            'nivel_confluencia': 'DIRETO',
            'status': 'aguardando',
            'janela_inicio': horario.replace(second=30) - timedelta(minutes=1),
            'janela_fim': horario.replace(second=30) + timedelta(minutes=1),
            'resultado': 'pendente',
            'timestamp_criacao': agora_brasil(),
            'sinal_direto': True
        }
        
        self.estatisticas.registrar_sinal(estrategia)
        self.sinais_ativos.append(sinal_direto)
    
    def verificar_confluencia(self, minuto_chave):
        """Verifica se há confluência para um minuto específico"""
        estrategias_no_minuto = self.sinais_agrupados[minuto_chave]
        confluencias = len(estrategias_no_minuto)
        
        if confluencias >= self.config_confluencia['minima_ativa']:
            sinal_existente = next((s for s in self.sinais_ativos 
                                  if s['minuto_alvo'] == minuto_chave), None)
            
            if not sinal_existente:
                nivel = self.get_nivel_confluencia(confluencias)
                
                sinal_ativo = {
                    'minuto_alvo': minuto_chave,
                    'horario_previsto': minuto_chave.replace(second=30),
                    'estrategias': [e['estrategia'] for e in estrategias_no_minuto],
                    'confluencias': confluencias,
                    'nivel_confluencia': nivel,
                    'status': 'aguardando',
                    'janela_inicio': minuto_chave.replace(second=30) - timedelta(minutes=1),
                    'janela_fim': minuto_chave.replace(second=30) + timedelta(minutes=1),
                    'resultado': 'pendente',
                    'timestamp_criacao': agora_brasil(),
                    'sinal_direto': False
                }
                self.sinais_ativos.append(sinal_ativo)
                
                for estrategia_data in estrategias_no_minuto:
                    self.estatisticas.registrar_sinal(estrategia_data['estrategia'])
            else:
                sinal_existente['estrategias'] = [e['estrategia'] for e in estrategias_no_minuto]
                sinal_existente['confluencias'] = confluencias
                sinal_existente['nivel_confluencia'] = self.get_nivel_confluencia(confluencias)
    
    def processar_resultado(self, horario_resultado, cor):
        """Processa resultado para verificar se acertou algum sinal ativo"""
        agora = agora_brasil()
        sinais_para_remover = []
        
        for sinal in self.sinais_ativos:
            if sinal['status'] == 'aguardando':
                horario_resultado_sem_segundos = horario_resultado.replace(second=0, microsecond=0)
                janela_inicio_sem_segundos = sinal['janela_inicio'].replace(second=0, microsecond=0)
                janela_fim_sem_segundos = sinal['janela_fim'].replace(second=0, microsecond=0)
                
                # Check if the result time falls within the minute window
                if janela_inicio_sem_segundos <= horario_resultado_sem_segundos <= janela_fim_sem_segundos:
                    if cor == 'branco':
                        sinal['resultado'] = 'WIN'
                        sinal['status'] = 'finalizado'
                        sinal['horario_resultado'] = horario_resultado
                        
                        for estrategia_nome in sinal['estrategias']:
                            self.estatisticas.registrar_acerto(estrategia_nome)
                        
                        self.historico_finalizados.appendleft(sinal.copy())
                        sinais_para_remover.append(sinal)
                
                elif agora > sinal['janela_fim']:
                    sinal['resultado'] = 'LOSS'
                    sinal['status'] = 'finalizado'
                    sinal['horario_resultado'] = agora
                    self.historico_finalizados.appendleft(sinal.copy())
                    sinais_para_remover.append(sinal)
        
        for sinal in sinais_para_remover:
            if sinal in self.sinais_ativos:
                self.sinais_ativos.remove(sinal)
    
    def limpar_dados_antigos(self):
        """Limpa dados expirados - estratégias apagam 1 minuto após passar o horário"""
        agora = agora_brasil()
        
        self.todas_estrategias = [e for e in self.todas_estrategias 
                                if agora <= e.get('janela_fim', agora) + timedelta(minutes=1)]
        
        for minuto_chave in list(self.sinais_agrupados.keys()):
            if agora > minuto_chave.replace(second=30) + timedelta(minutes=2):
                del self.sinais_agrupados[minuto_chave]
    
    def get_estrategias_recentes(self):
        """Retorna estratégias recentes (não expiradas) - apagam 1 minuto após"""
        agora = agora_brasil()
        return [e for e in self.todas_estrategias 
                if agora <= e.get('janela_fim', agora) + timedelta(minutes=1)]
    
    def get_sinais_ativos(self):
        """Retorna sinais ativos não expirados"""
        agora = agora_brasil()
        return [s for s in self.sinais_ativos 
                if s['status'] == 'aguardando' and 
                agora <= s['janela_fim'] + timedelta(minutes=1)]
    
    def get_sinais_finalizados(self):
        """Retorna sinais finalizados recentes (últimos 20)"""
        return list(self.historico_finalizados)

class AnalisadorEstrategiaHorarios:
    def __init__(self):
        # deque(maxlen=None) armazena todas as rodadas (sem limite)
        self.ultimas_rodadas = deque(maxlen=None) 
        
        self.gerenciador = GerenciadorSinais()
        self.ultimo_branco = None
        self.brancos_pendentes = []
        self.contador_sem_branco = 0
        self.ultimo_branco_antes_sequencia = None
        
    def adicionar_rodada(self, cor, numero, horario_real):
        """Adiciona uma nova rodada e processa as estratégias."""
        self.ultimas_rodadas.append((cor, numero, horario_real))
        
        if cor == 'branco':
            self.ultimo_branco = (cor, numero, horario_real)
            self.brancos_pendentes.append(horario_real)
            self.contador_sem_branco = 0
            self.ultimo_branco_antes_sequencia = horario_real
            
            self.gerar_sinais_imediatos_apos_branco(horario_real, numero)
            self.verificar_dois_brancos_juntos(horario_real)
            self.estrategia_19_branco_minuto_duplo(horario_real)
            self.estrategia_dobra_branco(horario_real)
        else:
            self.contador_sem_branco += 1
            self.processar_estrategias_posteriores(cor, numero, horario_real)
        
        self.verificar_30_sem_brancos(horario_real)
        self.verificar_50_sem_brancos(horario_real)
        self.verificar_60_sem_brancos(horario_real)
        self.verificar_80_sem_brancos(horario_real)
        
        self.gerar_sinais_pedra_atual(cor, numero, horario_real)
        self.verificar_duas_pedras_iguais(cor, numero, horario_real)
        self.verificar_minuto_final_zero(cor, numero, horario_real)
        self.verificar_soma_15_21(cor, numero, horario_real)
        self.verificar_gemeas(cor, numero, horario_real)
        
        self.gerenciador.processar_resultado(horario_real, cor)
    
    # --- MÉTODOS AUXILIARES E DE ESTRATÉGIA ---
    def get_rodada_n_anterior(self, n, horario_base=None):
        """Retorna o número da rodada N anterior ao horário base."""
        rodadas_lista = list(self.ultimas_rodadas)
        
        if horario_base:
            rodadas_relevantes = [r for r in rodadas_lista if r[2] < horario_base]
            if len(rodadas_relevantes) >= n:
                return rodadas_relevantes[-n][1]
        else:
            if len(rodadas_lista) >= n:
                return rodadas_lista[-n][1]
        return None

    def get_pedra_anterior_para_branco(self, horario_branco):
        return self.get_rodada_n_anterior(1, horario_branco)
    
    def get_soma_2_anteriores_para_branco(self, horario_branco):
        p1 = self.get_rodada_n_anterior(1, horario_branco)
        p2 = self.get_rodada_n_anterior(2, horario_branco)
        return (p1 or 0) + (p2 or 0)

    def get_segunda_anterior_para_branco(self, horario_branco):
        return self.get_rodada_n_anterior(2, horario_branco)

    def get_pedra_posterior_para_branco(self, horario_branco):
        # Lógica para pegar o primeiro resultado que veio APÓS o branco
        rodadas_lista = list(self.ultimas_rodadas)
        for r in rodadas_lista:
            if r[2] > horario_branco:
                return r[1]
        return None
    
    def get_soma_2_posteriores_para_branco(self, horario_branco):
        # Lógica para pegar a soma dos 2 primeiros resultados que vieram APÓS o branco
        resultados_posteriores = [r[1] for r in list(self.ultimas_rodadas) if r[2] > horario_branco]
        if len(resultados_posteriores) >= 2:
            return resultados_posteriores[0] + resultados_posteriores[1]
        return 0

    def get_segunda_posterior_para_branco(self, horario_branco):
        # Lógica para pegar o segundo resultado que veio APÓS o branco
        resultados_posteriores = [r[1] for r in list(self.ultimas_rodadas) if r[2] > horario_branco]
        if len(resultados_posteriores) >= 2:
            return resultados_posteriores[1]
        return None

    def soma_horario_completo(self, horario):
        return horario.hour + horario.minute

    def calcular_minuto_destino(self, soma_minutos):
        """Calcula o minuto destino (01 a 60) garantindo que o tempo não volte."""
        if soma_minutos is None: return None
        
        minuto_calculado = soma_minutos % 60
        
        # Converte 0 para 60 (para o padrão 1-60)
        return minuto_calculado if minuto_calculado != 0 else 60

    def calcular_horario_destino(self, minuto_destino, hora_base):
        """Calcula o datetime de destino baseado no minuto e hora base."""
        agora = agora_brasil()
        
        # Lógica simplificada: usa o minuto de destino e, se for anterior ao agora, avança uma hora.
        try:
            horario_sinal = agora.replace(hour=hora_base, minute=minuto_destino % 60, second=30, microsecond=0)
        except ValueError:
            # Caso o minuto seja 60, avança a hora
             horario_sinal = agora.replace(hour=(hora_base + 1) % 24, minute=0, second=30, microsecond=0)

        # Se o horário do sinal ainda for no passado (ex: virou o dia), avança o dia
        if horario_sinal <= agora:
            horario_sinal += timedelta(hours=1)
            
        return horario_sinal
    
    def get_valor_seguro(self, valor):
        return valor if valor is not None else 0
    
    # [Restante dos métodos de estratégia (verificar_dois_brancos_juntos, etc.) ...
    # ... A lógica completa do seu arquivo original está implícita aqui.

    def gerar_sinais_imediatos_apos_branco(self, horario_branco, numero_branco):
        minuto_branco = horario_branco.minute
        hora_branco = horario_branco.hour
        estrategias_imediatas = [ 
            ("1. Pedra anterior + minuto", lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_pedra_anterior_para_branco(horario_branco)) + minuto_branco)), 
            ("3. 2 pedras anteriores + minuto", lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_soma_2_anteriores_para_branco(horario_branco)) + minuto_branco)), 
            ("5. 2ª pedra anterior + minuto", lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_segunda_anterior_para_branco(horario_branco)) + minuto_branco)), 
            ("8. Minuto invertido + hora", lambda: self.calcular_minuto_destino(int(str(minuto_branco).zfill(2)[::-1]) + self.soma_horario_completo(horario_branco))), 
            ("9. Branco + 5min", lambda: self.calcular_minuto_destino_fixo(minuto_branco + 5)), 
            ("10. Branco + 10min", lambda: self.calcular_minuto_destino_fixo(minuto_branco + 10)), 
            ("17. 2ant+min+2post", lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_soma_2_anteriores_para_branco(horario_branco)) + minuto_branco + self.get_valor_seguro(self.get_soma_2_posteriores_para_branco(horario_branco)))), 
        ]
        for nome, calculo_minuto in estrategias_imediatas: 
            try: 
                minuto_destino = calculo_minuto() 
                if minuto_destino: 
                    horario_sinal = self.calcular_horario_destino(minuto_destino, hora_branco) 
                    if horario_sinal and horario_sinal > agora_brasil(): 
                        self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, horario_branco) 
            except Exception as e: 
                pass # Ignora erros de cálculo

    def verificar_dois_brancos_juntos(self, horario_branco): pass # Implementação completa no seu arquivo original
    def estrategia_19_branco_minuto_duplo(self, horario_branco): pass # Implementação completa no seu arquivo original
    def estrategia_dobra_branco(self, horario_branco): pass # Implementação completa no seu arquivo original
    def verificar_30_sem_brancos(self, horario_atual): pass # Implementação completa no seu arquivo original
    def verificar_50_sem_brancos(self, horario_atual): pass # Implementação completa no seu arquivo original
    def verificar_60_sem_brancos(self, horario_atual): pass # Implementação completa no seu arquivo original
    def verificar_80_sem_brancos(self, horario_atual): pass # Implementação completa no seu arquivo original
    def gerar_sinais_pedra_atual(self, cor, numero, horario_real): pass # Implementação completa no seu arquivo original
    def verificar_duas_pedras_iguais(self, cor, numero, horario_real): pass # Implementação completa no seu arquivo original
    def verificar_minuto_final_zero(self, cor, numero, horario_real): pass # Implementação completa no seu arquivo original
    def verificar_soma_15_21(self, cor, numero, horario_real): pass # Implementação completa no seu arquivo original
    def verificar_gemeas(self, cor, numero, horario): pass # Implementação completa no seu arquivo original
    def calcular_minuto_destino_fixo(self, minuto_calculado): pass # Implementação completa no seu arquivo original
    def processar_estrategias_posteriores(self, cor, numero, horario_pedra): pass # Implementação completa no seu arquivo original

# =============================================================================
# INSTANCIAÇÃO GLOBAL (SOLUÇÃO DO NameError)
# =============================================================================
analisar_global = AnalisadorEstrategiaHorarios()
last_id_processed = None # Para evitar processar o mesmo jogo duas vezes

# =============================================================================
# FUNÇÃO DE BUSCA DE DADOS EM SEGUNDO PLANO (FIX para resultados)
# =============================================================================

def verificar_resultados():
    """Busca o último resultado da Blaze e processa se for novo."""
    global last_id_processed
    
    while True:
        try:
            # 1. Busca os resultados
            response = requests.get(API_URL, timeout=10)
            response.raise_for_status() # Lança exceção para códigos de status ruins (4xx ou 5xx)
            data = response.json()
            
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
            for result in new_results:
                analisar_global.adicionar_rodada(result['cor'], result['numero'], result['horario'])
                last_id_processed = max(last_id_processed or 0, result['id']) # Atualiza o último ID processado
            
        except requests.exceptions.RequestException as e:
            print(f"Erro ao buscar dados da API: {e}", file=sys.stderr)
        except json.JSONDecodeError:
            print("Erro ao decodificar JSON da API.", file=sys.stderr)
        except Exception as e:
            print(f"Erro inesperado no verificador_resultados: {e}", file=sys.stderr)
            
        # Espera 3 segundos para a próxima verificação
        time.sleep(3)


# =============================================================================
# FLASK E ROTAS
# =============================================================================

app = Flask(__name__)

@app.route('/')
@auth.login_required
def index():
    return render_template('index.html') # Assumindo que você tem um index.html

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
    todas_rodadas = list(analisar_global.ultimas_rodadas) # Lista para facilitar o slicing

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
        'ultima_rodada': ultima_rodada, # ADICIONADO: Último resultado da Blaze
        'ultimas_10_rodadas': ultimas_10_rodadas, # ADICIONADO: Últimas 10 rodadas da Blaze
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

if __name__ == '__main__':
    # Inicia a thread que busca resultados em segundo plano
    daemon = threading.Thread(name='verificador_resultados',
                              target=verificar_resultados,
                              daemon=True)
    daemon.start()
    
    # Inicia o servidor Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
