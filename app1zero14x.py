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
        
        self.historico_finalizados = deque(maxlen=20) 
        
        self.estatisticas = EstatisticasEstrategias()
        self.estrategias_ativas = self.criar_estrategias_padrao()
        
        self.config_confluencia = {
            'baixa': 3,      # 3+ estratégias = BAIXA
            'media': 4,      # 4+ estratégias = MÉDIA  
            'alta': 5,       # 5+ estratégias = ALTA
            'minima_ativa': 4  # Mínimo para criar sinal ativo
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
        self.ultimas_rodadas = deque(maxlen=None) 
        
        # O gerenciador DEVE ser inicializado AQUI dentro da classe AnalisadorEstrategiaHorarios.
        # Ele não pode ser 'analisar_global.gerenciador' porque 'analisar_global' ainda não existe.
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
            
            if (ultima[1] == penultima[1] and ultima[1] != 0 and ultima[2].replace(second=0) == penultima[2].replace(second=0)):
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
            if minuto_destino == 0:
                minuto_destino = 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "24. 50 sem Branco +4min"
                self.gerenciador.adicionar_sinal_direto(estrategia_nome, horario_sinal, minuto_destino, horario_atual)
        
    def verificar_60_sem_brancos(self, horario_atual):
        if self.contador_sem_branco == 60:
            minuto_destino = (horario_atual.minute + 4) % 60
            if minuto_destino == 0:
                minuto_destino = 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "25. 60 sem Branco +4min"
                self.gerenciador.adicionar_sinal_direto(estrategia_nome, horario_sinal, minuto_destino, horario_atual)
        
    def verificar_80_sem_brancos(self, horario_atual):
        if self.contador_sem_branco == 80:
            minuto_destino = (horario_atual.minute + 4) % 60
            if minuto_destino == 0:
                minuto_destino = 60
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
        if len(self.ultimas_rodadas) >= 30 and all(r[0] != 'branco' for r in list(self.ultimas_rodadas)[-30:]):
            
            estrategias_30 = [
                ("21. Seq30 [1] +35min", 35),
                ("21. Seq30 [2] +3min", 3),
                ("21. Seq30 [3] +3min", 3),
                ("21. Seq30 [4] +5min", 5),
                ("21. Seq30 [5] +3min", 3),
                ("21. Seq30 [6] +5min", 5),
                ("21. Seq30 [7] +3min", 3)
            ]
            
            for nome, minutos_add in estrategias_30:
                minuto_destino = (horario_atual.minute + minutos_add) % 60
                if minuto_destino == 0:
                    minuto_destino = 60
                
                horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
                if horario_sinal and horario_sinal > agora_brasil():
                    self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, horario_atual)

    def verificar_duas_pedras_iguais(self, cor, numero, horario_atual):
        if len(self.ultimas_rodadas) >= 2:
            rodadas_lista = list(self.ultimas_rodadas)
            ultima = rodadas_lista[-1]
            penultima = rodadas_lista[-2]
            
            if ultima[1] == penultima[1] and ultima[1] != 0:
                # 14. 2 pedras iguais +1h
                minuto_atual = horario_atual.minute
                hora_destino = (horario_atual.hour + 1) % 24
                horario_sinal = horario_atual.replace(hour=hora_destino, minute=minuto_atual, second=0)
                
                if horario_sinal > agora_brasil():
                    estrategia_nome = f"14. 2 pedras iguais +1h"
                    self.gerenciador.adicionar_estrategia(estrategia_nome, horario_sinal, minuto_atual, horario_atual)
                
                # 20. 2 pedras iguais +14min
                minuto_destino = (horario_atual.minute + 14) % 60
                horario_sinal_14min = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
                
                if horario_sinal_14min and horario_sinal_14min > agora_brasil():
                    estrategia_nome = f"20. 2 pedras iguais +14min"
                    self.gerenciador.adicionar_estrategia(estrategia_nome, horario_sinal_14min, minuto_destino, horario_atual)
        
    def verificar_minuto_final_zero(self, cor, numero, horario_atual):
        if horario_atual.minute % 10 == 0:
            minuto_destino = (horario_atual.minute + 1) % 60
            if minuto_destino == 0:
                minuto_destino = 60
                
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = f"15. Minuto zero + pedra"
                self.gerenciador.adicionar_estrategia(estrategia_nome, horario_sinal, minuto_destino, horario_atual)

    def verificar_soma_15_21(self, cor, numero, horario_atual):
        if len(self.ultimas_rodadas) >= 2:
            rodadas_lista = list(self.ultimas_rodadas)
            soma = rodadas_lista[-1][1] + rodadas_lista[-2][1]
            
            if soma in [15, 21]:
                minuto_destino = (horario_atual.minute + 10) % 60
                if minuto_destino == 0:
                    minuto_destino = 60
                    
                horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
                if horario_sinal and horario_sinal > agora_brasil():
                    estrategia_nome = f"16. Soma {soma} +10min"
                    self.gerenciador.adicionar_estrategia(estrategia_nome, horario_sinal, minuto_destino, horario_atual)

    def gerar_sinais_imediatos_apos_branco(self, horario_branco, numero):
        # 9. Branco + 5min
        minuto_destino_5 = (horario_branco.minute + 5) % 60
        horario_sinal_5 = self.calcular_horario_destino(minuto_destino_5, horario_branco.hour)
        if horario_sinal_5 and horario_sinal_5 > agora_brasil():
            self.gerenciador.adicionar_estrategia("9. Branco + 5min", horario_sinal_5, minuto_destino_5, horario_branco)

        # 10. Branco + 10min
        minuto_destino_10 = (horario_branco.minute + 10) % 60
        horario_sinal_10 = self.calcular_horario_destino(minuto_destino_10, horario_branco.hour)
        if horario_sinal_10 and horario_sinal_10 > agora_brasil():
            self.gerenciador.adicionar_estrategia("10. Branco + 10min", horario_sinal_10, minuto_destino_10, horario_branco)
            
    def verificar_dois_brancos_juntos(self, horario_branco):
        if len(self.brancos_pendentes) >= 2:
            # Verifica se os dois últimos brancos ocorreram na mesma hora ou com uma hora de diferença, mas em minutos próximos
            ultimo = self.brancos_pendentes[-1]
            penultimo = self.brancos_pendentes[-2]
            
            # Se a diferença for menor que 10 minutos (incluindo virada de hora)
            if (ultimo - penultimo) < timedelta(minutes=10):
                minuto_destino = (horario_branco.minute + 3) % 60
                horario_sinal = self.calcular_horario_destino(minuto_destino, horario_branco.hour)
                
                if horario_sinal and horario_sinal > agora_brasil():
                    self.gerenciador.adicionar_estrategia("18. 2 brancos +3min", horario_sinal, minuto_destino, horario_branco)
        
    def gerar_sinais_pedra_atual(self, cor, numero, horario_atual):
        
        # 11. Pedra 4 + 4min
        if numero == 4:
            minuto_destino = (horario_atual.minute + 4) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("11. Pedra 4 + 4min", horario_sinal, minuto_destino, horario_atual)
                
        # 12. Pedra 14 + 5min
        if numero == 14:
            minuto_destino = (horario_atual.minute + 5) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("12. Pedra 14 + 5min", horario_sinal, minuto_destino, horario_atual)
                
        # 13. Pedra 11 + 3min
        if numero == 11:
            minuto_destino = (horario_atual.minute + 3) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("13. Pedra 11 + 3min", horario_sinal, minuto_destino, horario_atual)

    def processar_estrategias_posteriores(self, cor, numero, horario_atual):
        """Processa estratégias baseadas em rodadas anteriores."""
        if len(self.ultimas_rodadas) >= 1:
            rodada_anterior = list(self.ultimas_rodadas)[-1]
            pedra_anterior = rodada_anterior[1]
            
            # Estratégia 1: Pedra anterior + minuto
            minuto_destino = (horario_atual.minute + pedra_anterior) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("1. Pedra anterior + minuto", horario_sinal, minuto_destino, horario_atual)

            # Estratégia 2: Pedra posterior + minuto (Baseado na pedra atual)
            minuto_destino = (horario_atual.minute + numero) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("2. Pedra posterior + minuto", horario_sinal, minuto_destino, horario_atual)
        
        if len(self.ultimas_rodadas) >= 2:
            rodada_anterior = list(self.ultimas_rodadas)[-1]
            rodada_2_anterior = list(self.ultimas_rodadas)[-2]
            
            # Estratégia 3: 2 pedras anteriores + minuto
            soma_pedras_ant = rodada_anterior[1] + rodada_2_anterior[1]
            minuto_destino = (horario_atual.minute + soma_pedras_ant) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("3. 2 pedras anteriores + minuto", horario_sinal, minuto_destino, horario_atual)

            # Estratégia 4: 2 pedras posteriores + minuto (Baseado em 2x Pedra atual)
            soma_pedras_post = numero * 2
            minuto_destino = (horario_atual.minute + soma_pedras_post) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("4. 2 pedras posteriores + minuto", horario_sinal, minuto_destino, horario_atual)

            # Estratégia 5: 2ª pedra anterior + minuto
            pedra_2_anterior = rodada_2_anterior[1]
            minuto_destino = (horario_atual.minute + pedra_2_anterior) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("5. 2ª pedra anterior + minuto", horario_sinal, minuto_destino, horario_atual)

            # Estratégia 6: 2ª pedra posterior + minuto (Baseado em 2x Pedra anterior)
            pedra_anterior = rodada_anterior[1]
            minuto_destino = (horario_atual.minute + pedra_anterior * 2) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("6. 2ª pedra posterior + minuto", horario_sinal, minuto_destino, horario_atual)
            
            # Estratégia 7: Ant+min+post
            minuto_destino = (horario_atual.minute + pedra_anterior + numero) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("7. Ant+min+post", horario_sinal, minuto_destino, horario_atual)

        if len(self.ultimas_rodadas) >= 3:
            rodada_anterior = list(self.ultimas_rodadas)[-1]
            rodada_2_anterior = list(self.ultimas_rodadas)[-2]
            rodada_3_anterior = list(self.ultimas_rodadas)[-3]
            
            # Estratégia 17: 2ant+min+2post
            pedra_ant = rodada_anterior[1]
            pedra_2ant = rodada_2_anterior[1]
            pedra_3ant = rodada_3_anterior[1]
            
            minuto_destino = (horario_atual.minute + pedra_ant + pedra_2ant + numero + numero) % 60
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("17. 2ant+min+2post", horario_sinal, minuto_destino, horario_atual)

        # Estratégia 8: Minuto invertido + hora
        hora_atual = horario_atual.hour
        minuto_invertido = int(str(horario_atual.minute).zfill(2)[::-1])
        minuto_destino = (minuto_invertido + hora_atual) % 60
        horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
        if horario_sinal and horario_sinal > agora_brasil():
            self.gerenciador.adicionar_estrategia("8. Minuto invertido + hora", horario_sinal, minuto_destino, horario_atual)


    def calcular_minuto_destino(self, soma_minutos):
        """Calcula o minuto destino (1 a 60), tratando estouros de 60."""
        minuto_destino = soma_minutos % 60
        if minuto_destino == 0:
            return 60 # Minuto 60 representa o minuto 00 da próxima hora
        return minuto_destino

    def calcular_horario_destino(self, minuto_destino, hora_base):
        """Calcula o datetime de destino no fuso BR, tratando virada de hora (minuto 60)"""
        agora = agora_brasil()
        hora_alvo = hora_base
        minuto_alvo = minuto_destino % 60
        
        if minuto_destino == 60:
            minuto_alvo = 0
            hora_alvo = (hora_base + 1) % 24
        elif minuto_destino > 60:
            # Se for, por exemplo, minuto 65, o minuto é 5 e a hora deve avançar
            minuto_alvo = minuto_destino % 60
            horas_extras = minuto_destino // 60
            hora_alvo = (hora_base + horas_extras) % 24
        
        try:
            horario_previsto = agora.replace(hour=hora_alvo, minute=minuto_alvo, second=30, microsecond=0)
            
            # Se o horário previsto for muito no passado (ex: virou o dia), joga para amanhã.
            # Isso é importante para o minuto 60, que deve ser na próxima hora.
            if horario_previsto < agora - timedelta(minutes=5):
                 horario_previsto += timedelta(days=1)
                 
            return horario_previsto
            
        except ValueError:
            # Caso raro, como minuto 60 (agora resolvido acima)
            return None


# === FIM DAS CLASSES ===

# -----------------------------------------------------------------------------
# VARIÁVEIS GLOBAIS DE ESTADO E INICIALIZAÇÃO DA LÓGICA
# (ESTE TRECHO FOI MOVIDO PARA CÁ PARA RESOLVER O NameError)
# -----------------------------------------------------------------------------
analisar_global = AnalisadorEstrategiaHorarios()
status_thread_global = {'status': 'INICIANDO...'} # Para o debug na web

# =============================================================================
# THREAD DE VERIFICAÇÃO DE RESULTADOS
# =============================================================================

def verificar_resultados():
    """Busca resultados da API em loop e alimenta o AnalisadorEstrategiaHorarios."""
    global status_thread_global 
    
    ultimo_id = None
    
    # 1. PEGA O TOKEN DE AUTENTICAÇÃO
    # Usando o mesmo token de forma global para simplificar, se necessário.
    HEADERS = {
        'Authorization': f'Basic {USERS[MASTER_USER]}:{SHARED_PASSWORD}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }
    
    print(f"[{agora_brasil().strftime('%H:%M:%S')}] THREAD: Iniciada com sucesso. Aguardando dados...")
    
    while True:
        try:
            # 2. REQUISIÇÃO
            # Adiciona um timeout de 15 segundos para evitar travamento em caso de falha de rede
            response = requests.get(API_URL, timeout=15, headers=HEADERS)
            response.raise_for_status() # Lança exceção para códigos de status HTTP 4xx/5xx
            
            data = response.json()
            rodadas = data.get('games', [])
            
            if rodadas:
                ultima_rodada = rodadas[0]
                
                # 3. EXTRAÇÃO DE DADOS
                novo_id = ultima_rodada['id']
                cor = ultima_rodada['color']
                numero = ultima_rodada['roll']
                horario_utc_str = ultima_rodada['created_at']
                
                # 4. CONVERSÃO DE TEMPO
                # Horário que a rodada foi registrada no servidor (UTC)
                horario_utc = datetime.strptime(horario_utc_str, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
                # Converte para o fuso horário do Brasil (GMT-3)
                horario_brasil = horario_utc.astimezone(FUSO_BRASIL)
                
                # 5. PROCESSAMENTO
                if novo_id != ultimo_id:
                    analisar_global.adicionar_rodada(cor, numero, horario_brasil)
                    ultimo_id = novo_id
                    
                    # Atualiza o status de debug
                    status_thread_global['status'] = f"SUCESSO: Rodada {novo_id} processada. {cor.upper()} {numero} @ {horario_brasil.strftime('%H:%M:%S')}"
                    print(f"[{horario_brasil.strftime('%H:%M:%S')}] NOVO: ID {novo_id}, {cor} {numero}. Status: OK")
                else:
                    status_thread_global['status'] = f"AGUARDANDO: Última ID {ultimo_id} @ {horario_brasil.strftime('%H:%M:%S')}"
                    
            else:
                status_thread_global['status'] = f"ERRO: API vazia. Última checagem: {agora_brasil().strftime('%H:%M:%S')}"

        except Timeout:
            # Erro de tempo limite
            status_thread_global['status'] = f"ERRO: Timeout (15s). API não respondeu @ {agora_brasil().strftime('%H:%M:%S')}"
        except RequestException as e:
            # Outros erros de requisição (Conexão, HTTP 4xx/5xx)
            status = f"ERRO: Falha na requisição. Status HTTP: {e.response.status_code if e.response else 'N/A (ConnectionError)'} @ {agora_brasil().strftime('%H:%M:%S')}"
            status_thread_global['status'] = status
        except Exception as e:
            # Erros de código inesperados
            status = f"ERRO: Código inesperado ({type(e).__name__}). @ {agora_brasil().strftime('%H:%M:%S')}"
            status_thread_global['status'] = status
            print(f"Erro inesperado na thread: {e}", file=sys.stderr)
            
        # Espera 1 segundo antes da próxima checagem
        time.sleep(1)


# =============================================================================
# APLICATIVO FLASK
# =============================================================================

app = Flask(__name__)

# Rota protegida pela senha
@app.route('/')
@auth.login_required
def index():
    """Renderiza a interface web principal."""
    return render_template('index.html')

# Rota para obter os dados do bot em JSON
@app.route('/data')
@auth.login_required
def get_data():
    """Retorna o JSON com dados para o frontend."""
    # Garante que estamos pegando a última instância e status
    gerenciador = analisar_global.gerenciador
    
    # Prepara estatísticas
    sinais_finalizados = gerenciador.get_sinais_finalizados()
    total = len(sinais_finalizados)
    wins = sum(1 for s in sinais_finalizados if s['resultado'] == 'WIN')
    losses = sum(1 for s in sinais_finalizados if s['resultado'] == 'LOSS')
    percentual = (wins / total * 100) if total > 0 else 0
    
    # Prepara a última rodada
    ultima_rodada_obj = analizar_global.ultimas_rodadas[-1] if analizar_global.ultimas_rodadas else ('-', 0, agora_brasil())
    cor_ultima = ultima_rodada_obj[0]
    numero_ultima = ultima_rodada_obj[1]
    horario_ultima = ultima_rodada_obj[2].strftime('%H:%M:%S')

    # Prepara o histórico de rodadas (as últimas 10)
    historico_rodadas = [
        {
            'cor': r[0],
            'numero': r[1],
            'horario': r[2].strftime('%H:%M')
        } for r in list(analizar_global.ultimas_rodadas)[-10:]
    ]

    data = {
        'status_thread': status_thread_global['status'],
        'ultima_rodada': {
            'cor': cor_ultima,
            'numero': numero_ultima,
            'horario': horario_ultima
        },
        'historico_rodadas': historico_rodadas,
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
                              daemon=True) # daemon=True faz a thread morrer se o Flask parar
    daemon.start()
    
    # Inicia o servidor Flask com gunicorn/waitress ou no modo debug (local)
    # No Render, ele será iniciado pelo comando 'gunicorn app1zero14x:app'
    app.run(debug=True, host='0.0.0.0', port=os.environ.get("PORT", 5000))
