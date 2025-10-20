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
        self.todas_estrategias = []  # Armazena TODAS as estratégias verificadas
        self.sinais_agrupados = defaultdict(list)  # Agrupa por horário
        self.sinais_ativos = []  # Sinais com confluência mínima
        
        # --- MODIFICAÇÃO SOLICITADA ---
        # Histórico de sinais finalizados limitado aos últimos 20
        self.historico_finalizados = deque(maxlen=20) 
        
        self.estatisticas = EstatisticasEstrategias()
        self.estrategias_ativas = self.criar_estrategias_padrao()
        
        # CONFIGURAÇÃO DE CONFLUÊNCIA (PADRÃO: 4+ para sinal ativo)
        self.config_confluencia = {
            'baixa': 3,      # 3+ estratégias = BAIXA
            'media': 4,      # 4+ estratégias = MÉDIA  
            'alta': 5,       # 5+ estratégias = ALTA
            'minima_ativa': 4  # Mínimo para criar sinal ativo
        }
        
    def set_config_confluencia(self, nova_config):
        """Define nova configuração de confluência"""
        self.config_confluencia = nova_config
        
        # Re-processa todos os sinais agrupados com a nova configuração
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
        
        # Agrupa por horário (minuto exato)
        minuto_chave = horario.replace(second=0, microsecond=0)
        self.sinais_agrupados[minuto_chave].append(estrategia_data)
        
        # Verifica se virou sinal ativo (confluência mínima)
        self.verificar_confluencia(minuto_chave)
        
        # Limpa dados antigos
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
        
        # Registra estatística
        self.estatisticas.registrar_sinal(estrategia)
        
        self.sinais_ativos.append(sinal_direto)
    
    def verificar_confluencia(self, minuto_chave):
        """Verifica se há confluência para um minuto específico"""
        estrategias_no_minuto = self.sinais_agrupados[minuto_chave]
        confluencias = len(estrategias_no_minuto)
        
        # Verifica se atinge o mínimo para sinal ativo
        if confluencias >= self.config_confluencia['minima_ativa']:
            # Verifica se já existe sinal ativo para este minuto
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
                
                # Registra estatísticas para cada estratégia que entrou no sinal ativo
                for estrategia_data in estrategias_no_minuto:
                    self.estatisticas.registrar_sinal(estrategia_data['estrategia'])
            else:
                # Atualiza sinal existente
                sinal_existente['estrategias'] = [e['estrategia'] for e in estrategias_no_minuto]
                sinal_existente['confluencias'] = confluencias
                sinal_existente['nivel_confluencia'] = self.get_nivel_confluencia(confluencias)
    
    def processar_resultado(self, horario_resultado, cor):
        """Processa resultado para verificar se acertou algum sinal ativo - CORRIGIDO"""
        agora = agora_brasil()
        sinais_para_remover = []
        
        for sinal in self.sinais_ativos:
            if sinal['status'] == 'aguardando':
                horario_resultado_sem_segundos = horario_resultado.replace(second=0, microsecond=0)
                janela_inicio_sem_segundos = sinal['janela_inicio'].replace(second=0, microsecond=0)
                janela_fim_sem_segundos = sinal['janela_fim'].replace(second=0, microsecond=0)
                
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
        # --- MODIFICAÇÃO SOLICITADA ---
        # Removido o limite (maxlen=100) para manter todo o histórico de rodadas (rodadas ilimitadas)
        self.ultimas_rodadas = deque(maxlen=None) 
        
        self.gerenciador = GerenciadorSinais()
        self.ultimo_branco = None
        self.brancos_pendentes = []
        self.contador_sem_branco = 0
        self.ultimo_branco_antes_sequencia = None
        
    def adicionar_rodada(self, cor, numero, horario_real):
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
    
    def estrategia_dobra_branco(self, horario_branco):
        minuto_branco = horario_branco.minute
        soma_minutos = minuto_branco + minuto_branco
        minuto_destino = self.calcular_minuto_destino(soma_minutos)
        
        if minuto_destino:
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_branco.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "22. Dobra de Branco"
                self.gerenciador.adicionar_estrategia(estrategia_nome, horario_sinal, minuto_destino, horario_branco)

    def verificar_gemeas(self, cor, numero, horario):
        if len(self.ultimas_rodadas) >= 2:
            rodadas_lista = list(self.ultimas_rodadas)
            ultima = rodadas_lista[-1]
            penultima = rodadas_lista[-2]
            
            if (ultima[1] == penultima[1] and 
                ultima[1] != 0 and
                ultima[2].replace(second=0) == penultima[2].replace(second=0)):
                
                minuto_atual = horario.minute
                valor_gemeas = ultima[1]
                soma = minuto_atual + valor_gemeas + 10
                minuto_destino = self.calcular_minuto_destino(soma)
                
                if minuto_destino:
                    horario_sinal = self.calcular_horario_destino(minuto_destino, horario.hour)
                    if horario_sinal and horario_sinal > agora_brasil():
                        estrategia_nome = f"23. Gêmeas"
                        self.gerenciador.adicionar_estrategia(estrategia_nome, horario_sinal, minuto_destino, horario)

    def verificar_50_sem_brancos(self, horario_atual):
        if self.contador_sem_branco == 50:
            minuto_destino = (horario_atual.minute + 4) % 60
            if minuto_destino == 0: minuto_destino = 60
            
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "24. 50 sem Branco +4min"
                self.gerenciador.adicionar_sinal_direto(estrategia_nome, horario_sinal, minuto_destino, horario_atual)

    def verificar_60_sem_brancos(self, horario_atual):
        if self.contador_sem_branco == 60:
            minuto_destino = (horario_atual.minute + 4) % 60
            if minuto_destino == 0: minuto_destino = 60
            
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "25. 60 sem Branco +4min"
                self.gerenciador.adicionar_sinal_direto(estrategia_nome, horario_sinal, minuto_destino, horario_atual)

    def verificar_80_sem_brancos(self, horario_atual):
        if self.contador_sem_branco == 80:
            minuto_destino = (horario_atual.minute + 4) % 60
            if minuto_destino == 0: minuto_destino = 60
            
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "26. 80 sem Branco +4min"
                self.gerenciador.adicionar_sinal_direto(estrategia_nome, horario_sinal, minuto_destino, horario_atual)

    def estrategia_19_branco_minuto_duplo(self, horario_branco):
        minuto_branco = horario_branco.minute
        soma_minutos = minuto_branco + minuto_branco
        
        minuto_destino = self.calcular_minuto_destino(soma_minutos)
        if minuto_destino:
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_branco.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("19. Branco + Minuto Duplo", horario_sinal, minuto_destino, horario_branco)

    def verificar_30_sem_brancos(self, horario_atual):
        if self.contador_sem_branco >= 30 and self.ultimo_branco_antes_sequencia:
            sequencia_somas = [35, 3, 3, 5, 3, 5, 3]
            minuto_base = self.ultimo_branco_antes_sequencia.minute
            hora_base = self.ultimo_branco_antes_sequencia.hour
            minuto_atual = minuto_base
            
            for i, soma in enumerate(sequencia_somas):
                minuto_atual += soma
                minuto_destino = self.calcular_minuto_destino(minuto_atual)
                
                if minuto_destino:
                    horario_sinal = self.calcular_horario_destino(minuto_destino, hora_base)
                    if horario_sinal and horario_sinal > agora_brasil():
                        nome = f"21. Seq30 [{i+1}] +{soma}min"
                        self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, self.ultimo_branco_antes_sequencia)
            
            self.contador_sem_branco = 0 # Reseta para não gerar novamente

    def gerar_sinais_imediatos_apos_branco(self, horario_branco, numero_branco):
        minuto_branco = horario_branco.minute
        hora_branco = horario_branco.hour
        
        estrategias_imediatas = [
            ("1. Pedra anterior + minuto", 
             lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_pedra_anterior_para_branco(horario_branco)) + minuto_branco)),
            ("3. 2 pedras anteriores + minuto",
             lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_soma_2_anteriores_para_branco(horario_branco)) + minuto_branco)),
            ("5. 2ª pedra anterior + minuto",
             lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_segunda_anterior_para_branco(horario_branco)) + minuto_branco)),
            ("8. Minuto invertido + hora",
             lambda: self.calcular_minuto_destino(int(str(minuto_branco).zfill(2)[::-1]) + self.soma_horario_completo(horario_branco))),
            ("9. Branco + 5min", lambda: self.calcular_minuto_destino_fixo(minuto_branco + 5)),
            ("10. Branco + 10min", lambda: self.calcular_minuto_destino_fixo(minuto_branco + 10)),
            ("17. 2ant+min+2post",
             lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_soma_2_anteriores_para_branco(horario_branco)) + minuto_branco + self.get_valor_seguro(self.get_soma_2_posteriores_para_branco(horario_branco)))),
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

    def get_valor_seguro(self, valor):
        return valor if valor is not None else 0

    def calcular_minuto_destino_fixo(self, minuto_calculado):
        if minuto_calculado is None: return None
        if minuto_calculado > 60: minuto_calculado -= 60
        elif minuto_calculado < 1: minuto_calculado += 60
        return minuto_calculado if 1 <= minuto_calculado <= 60 else None

    def processar_estrategias_posteriores(self, cor, numero, horario_pedra):
        if not self.brancos_pendentes: return
        brancos_processados = []
        
        for horario_branco in self.brancos_pendentes:
            minuto_branco = horario_branco.minute
            hora_branco = horario_branco.hour
            
            if horario_pedra > horario_branco:
                estrategias_posteriores = [
                    ("2. Pedra posterior + minuto",
                     lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_pedra_posterior_para_branco(horario_branco)) + minuto_branco)),
                    ("4. 2 pedras posteriores + minuto",
                     lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_soma_2_posteriores_para_branco(horario_branco)) + minuto_branco)),
                    ("6. 2ª pedra posterior + minuto",
                     lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_segunda_posterior_para_branco(horario_branco)) + minuto_branco)),
                    ("7. Ant+min+post",
                     lambda: self.calcular_minuto_destino(self.get_valor_seguro(self.get_pedra_anterior_para_branco(horario_branco)) + minuto_branco + self.get_valor_seguro(self.get_pedra_posterior_para_branco(horario_branco)))),
                ]
                
                for nome, calculo_minuto in estrategias_posteriores:
                    try:
                        minuto_destino = calculo_minuto()
                        if minuto_destino:
                            horario_sinal = self.calcular_horario_destino(minuto_destino, hora_branco)
                            if horario_sinal and horario_sinal > agora_brasil():
                                self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, horario_branco)
                    except Exception as e:
                        pass # Ignora erros de cálculo
                
                brancos_processados.append(horario_branco)
        
        for branco in brancos_processados:
            if branco in self.brancos_pendentes:
                self.brancos_pendentes.remove(branco)

    def calcular_minuto_destino(self, soma):
        if soma is None or soma == 0: return None
        while soma > 60: soma -= 60
        while soma < 1: soma += 60
        return soma if 1 <= soma <= 60 else None

    def calcular_horario_destino(self, minuto_destino, hora_base):
        if minuto_destino is None: return None
        try:
            agora = agora_brasil()
            horario_destino = agora.replace(hour=hora_base, minute=minuto_destino, second=30, microsecond=0)
            while horario_destino <= agora:
                horario_destino += timedelta(hours=1)
            return horario_destino
        except:
            return None

    def gerar_sinais_pedra_atual(self, cor, numero, horario):
        if cor == 'branco': return
        estrategias_pedra = [(4, "11. Pedra 4 + 4min", 4), (14, "12. Pedra 14 + 5min", 5), (11, "13. Pedra 11 + 3min", 3)]
        
        for num_pedra, nome, minutos in estrategias_pedra:
            if numero == num_pedra:
                minuto_destino = (horario.minute + minutos) % 60
                if minuto_destino == 0: minuto_destino = 60
                horario_sinal = self.calcular_horario_destino(minuto_destino, horario.hour)
                if horario_sinal and horario_sinal > agora_brasil():
                    self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, horario)

    def verificar_duas_pedras_iguais(self, cor, numero, horario):
        if len(self.ultimas_rodadas) >= 2:
            rodadas_lista = list(self.ultimas_rodadas)
            ultima = rodadas_lista[-1]
            penultima = rodadas_lista[-2]
            
            if (ultima[1] == penultima[1] and ultima[2].replace(second=0) == penultima[2].replace(second=0)):
                minuto_destino = horario.minute
                horario_sinal = horario.replace(hour=horario.hour + 1, minute=minuto_destino, second=30)
                if horario_sinal <= agora_brasil(): horario_sinal += timedelta(days=1)
                if horario_sinal > agora_brasil():
                    self.gerenciador.adicionar_estrategia("14. 2 pedras iguais +1h", horario_sinal, minuto_destino, horario)
                
                minuto_destino_20 = (horario.minute + 14) % 60
                if minuto_destino_20 == 0: minuto_destino_20 = 60
                horario_sinal_20 = self.calcular_horario_destino(minuto_destino_20, horario.hour)
                if horario_sinal_20 and horario_sinal_20 > agora_brasil():
                    self.gerenciador.adicionar_estrategia("20. 2 pedras iguais +14min", horario_sinal_20, minuto_destino_20, horario)

    def verificar_minuto_final_zero(self, cor, numero, horario):
        minuto_atual = horario.minute
        if minuto_atual % 10 == 0:
            horario_sem_segundos = horario.replace(second=0)
            pedras_do_minuto = [r for r in self.ultimas_rodadas if r[2].replace(second=0) == horario_sem_segundos and r[1] != 0]
            
            if pedras_do_minuto:
                ultima_pedra = pedras_do_minuto[-1]
                if ultima_pedra[1] != 0:
                    soma = ultima_pedra[1] + minuto_atual
                    minuto_destino = self.calcular_minuto_destino(soma)
                    if minuto_destino:
                        horario_sinal = self.calcular_horario_destino(minuto_destino, horario.hour)
                        if horario_sinal and horario_sinal > agora_brasil():
                            nome = f"15. Minuto zero + pedra"
                            self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, horario)

    def verificar_soma_15_21(self, cor, numero, horario):
        if len(self.ultimas_rodadas) >= 2:
            rodadas_lista = list(self.ultimas_rodadas)
            ultima = rodadas_lista[-1]
            penultima = rodadas_lista[-2]
            
            if ultima[1] != 0 and penultima[1] != 0:
                soma = ultima[1] + penultima[1]
                if soma in [15, 21]:
                    minuto_destino = (horario.minute + 10) % 60
                    if minuto_destino == 0: minuto_destino = 60
                    horario_sinal = self.calcular_horario_destino(minuto_destino, horario.hour)
                    if horario_sinal and horario_sinal > agora_brasil():
                        self.gerenciador.adicionar_estrategia("16. Soma 15/21 +10min", horario_sinal, minuto_destino, horario)

    def verificar_dois_brancos_juntos(self, horario_branco):
        if len(self.ultimas_rodadas) >= 2:
            rodadas_lista = list(self.ultimas_rodadas)
            ultima = rodadas_lista[-1]
            penultima = rodadas_lista[-2]
            
            if (ultima[0] == 'branco' and penultima[0] == 'branco' and ultima[2].replace(second=0) == penultima[2].replace(second=0)):
                minuto_destino = (horario_branco.minute + 3) % 60
                if minuto_destino == 0: minuto_destino = 60
                horario_sinal = self.calcular_horario_destino(minuto_destino, horario_branco.hour)
                if horario_sinal and horario_sinal > agora_brasil():
                    self.gerenciador.adicionar_estrategia("18. 2 brancos +3min", horario_sinal, minuto_destino, horario_branco)

    def soma_horario_completo(self, horario):
        hora_str = horario.strftime('%H%M')
        return sum(int(d) for d in hora_str)

    def get_pedra_anterior_para_branco(self, horario_branco):
        rodadas_ordenadas = sorted(self.ultimas_rodadas, key=lambda x: x[2])
        for i, rodada in enumerate(rodadas_ordenadas):
            if rodada[2] == horario_branco and i > 0:
                anterior = rodadas_ordenadas[i-1][1]
                return anterior if anterior != 0 else None
        return None

    def get_pedra_posterior_para_branco(self, horario_branco):
        rodadas_ordenadas = sorted(self.ultimas_rodadas, key=lambda x: x[2])
        for i, rodada in enumerate(rodadas_ordenadas):
            if rodada[2] == horario_branco and i < len(rodadas_ordenadas) - 1:
                posterior = rodadas_ordenadas[i+1][1]
                return posterior if posterior != 0 else None
        return None

    def get_soma_2_anteriores_para_branco(self, horario_branco):
        rodadas_ordenadas = sorted(self.ultimas_rodadas, key=lambda x: x[2])
        for i, rodada in enumerate(rodadas_ordenadas):
            if rodada[2] == horario_branco and i >= 2:
                anterior1 = rodadas_ordenadas[i-1][1]
                anterior2 = rodadas_ordenadas[i-2][1]
                if anterior1 != 0 and anterior2 != 0: return anterior1 + anterior2
        return None

    def get_soma_2_posteriores_para_branco(self, horario_branco):
        rodadas_ordenadas = sorted(self.ultimas_rodadas, key=lambda x: x[2])
        for i, rodada in enumerate(rodadas_ordenadas):
            if rodada[2] == horario_branco and i <= len(rodadas_ordenadas) - 3:
                posterior1 = rodadas_ordenadas[i+1][1]
                posterior2 = rodadas_ordenadas[i+2][1]
                if posterior1 != 0 and posterior2 != 0: return posterior1 + posterior2
        return None

    def get_segunda_anterior_para_branco(self, horario_branco):
        rodadas_ordenadas = sorted(self.ultimas_rodadas, key=lambda x: x[2])
        for i, rodada in enumerate(rodadas_ordenadas):
            if rodada[2] == horario_branco and i >= 2:
                segunda_anterior = rodadas_ordenadas[i-2][1]
                return segunda_anterior if segunda_anterior != 0 else None
        return None

    def get_segunda_posterior_para_branco(self, horario_branco):
        rodadas_ordenadas = sorted(self.ultimas_rodadas, key=lambda x: x[2])
        for i, rodada in enumerate(rodadas_ordenadas):
            if rodada[2] == horario_branco and i <= len(rodadas_ordenadas) - 3:
                segunda_posterior = rodadas_ordenadas[i+2][1]
                return segunda_posterior if segunda_posterior != 0 else None
        return None

# =============================================================================
# --- Configuração do Web App ---
# =============================================================================

app = Flask(__name__)

# --- Instância Global do Analisador ---
analisador_global = AnalisadorEstrategiaHorarios()
ultimo_id_global = None
ultimas_10_rodadas_global = deque(maxlen=10)
ultimo_resultado_global = {"numero": "--", "cor": "branco", "horario": "--:--:--"}

def verificar_resultados_em_loop():
    """
    Esta função roda em uma thread separada, continuamente buscando
    novos resultados e atualizando nosso analisador_global.
    Adicionado tratamento de erro robusto para evitar o 'travamento'.
    """
    global ultimo_id_global, ultimo_resultado_global
    
    # Tempo de espera padrão e tempo de espera após erro
    INTERVALO_SUCESSO = 3 # Segundos
    INTERVALO_ERRO = 15 # Segundos

    while True:
        try:
            # Tenta buscar a API com um timeout para evitar que a thread trave
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(API_URL, headers=headers, timeout=10)
            response.raise_for_status() # Lança HTTPError se o status code for 4xx ou 5xx
            
            data = response.json()

            if data and data[0]['id'] != ultimo_id_global:
                ultimo_id_global = data[0]['id']
                cor_num = data[0]['color']
                cor = 'branco' if cor_num in [None, 0] else 'vermelho' if cor_num == 1 else 'preto'
                numero = data[0]['roll']

                horario_str = data[0]['created_at']
                horario_utc = datetime.fromisoformat(horario_str.replace('Z', '+00:00'))
                horario_real = horario_utc.astimezone(FUSO_BRASIL)

                # Atualiza os dados globais
                analisador_global.adicionar_rodada(cor, numero, horario_real)
                ultimas_10_rodadas_global.appendleft({"numero": numero, "cor": cor, "horario": horario_real.strftime('%H:%M')})
                ultimo_resultado_global = {"numero": numero, "cor": cor, "horario": horario_real.strftime('%H:%M:%S')}
                
                # Sucesso: Espera o intervalo padrão
                time.sleep(INTERVALO_SUCESSO)

        except Timeout:
            print(f"[{agora_brasil().strftime('%Y-%m-%d %H:%M:%S')}] ERRO: Timeout na requisição. Tentando novamente em {INTERVALO_ERRO} segundos.", file=sys.stderr)
            time.sleep(INTERVALO_ERRO)
        except RequestException as e:
            # Captura erros de HTTP (4xx, 5xx) e outros erros de requisição
            print(f"[{agora_brasil().strftime('%Y-%m-%d %H:%M:%S')}] ERRO: Falha na requisição da API: {e}. Tentando novamente em {INTERVALO_ERRO} segundos.", file=sys.stderr)
            time.sleep(INTERVALO_ERRO)
        except json.JSONDecodeError:
            print(f"[{agora_brasil().strftime('%Y-%m-%d %H:%M:%S')}] ERRO: Falha ao decodificar JSON da API. Tentando novamente em {INTERVALO_ERRO} segundos.", file=sys.stderr)
            time.sleep(INTERVALO_ERRO)
        except Exception as e:
            # Captura qualquer outro erro inesperado (a causa do travamento)
            INTERVALO_ERRO_GRAVE = 30
            print(f"[{agora_brasil().strftime('%Y-%m-%d %H:%M:%S')}] ERRO INESPERADO no loop de verificação: {e}. Tentando novamente em {INTERVALO_ERRO_GRAVE} segundos.", file=sys.stderr)
            time.sleep(INTERVALO_ERRO_GRAVE)

# --- Rotas do Site ---

@app.route('/')
@auth.login_required 
def index():
    """ Rota principal que renderiza a nossa página HTML. """
    # Assumindo que você tem um arquivo index.html na pasta 'templates'
    return render_template('index.html')

@app.route('/data')
@auth.login_required 
def get_data():
    """
    Esta rota é um 'API endpoint'. O JavaScript da página vai chamar
    esta URL a cada 3 segundos para pegar os dados mais recentes.
    """
    gerenciador = analisador_global.gerenciador
    sinais_finalizados = gerenciador.get_sinais_finalizados()
    
    # Calcula estatísticas
    wins = sum(1 for s in sinais_finalizados if s['resultado'] == 'WIN')
    losses = sum(1 for s in sinais_finalizados if s['resultado'] == 'LOSS')
    total = wins + losses
    percentual = (wins / total * 100) if total > 0 else 0
    
    # Prepara os dados para enviar como JSON
    data = {
        'ultimo_resultado': ultimo_resultado_global,
        'ultimas_10_rodadas': list(ultimas_10_rodadas_global),
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
                              target=verificar_resultados_em_loop,
                              daemon=True)
    daemon.start()

    # Inicia o servidor web Flask (usando a porta do Render)
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 5000), debug=False)
