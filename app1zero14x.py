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
    """Retorna o datetime atual no fuso horário do Brasil"""
    return datetime.now(FUSO_BRASIL)

def buscar_dados_api(api_url):
    """Função para buscar os dados de rodadas recentes da API com User-Agent."""
    # Adicionando um User-Agent de navegador para tentar evitar bloqueio 451
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(api_url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get('data', [])
    except Exception as e:
        print(f"[ERRO API] {e}")
        return []

def processar_rodada(rodadas_data):
    """Processa a rodada mais recente e retorna (cor, numero, horario_real)"""
    if not rodadas_data:
        return None, None, None
    
    rodada = rodadas_data[0]
    cor = rodada.get('color', '').lower()
    numero = rodada.get('roll')
    horario_utc_str = rodada.get('created_at')
    
    if horario_utc_str:
        try:
            # Converte string UTC para objeto datetime e depois para fuso Brasil
            horario_utc = datetime.fromisoformat(horario_utc_str.replace('Z', '+00:00'))
            horario_brasil = horario_utc.astimezone(FUSO_BRASIL)
            return cor, numero, horario_brasil
        except:
            return cor, numero, None
    
    return cor, numero, None

# ----------------------------------------
# CLASSES ORIGINAIS (Lógica de Sinais)
# ----------------------------------------

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
        self.historico_finalizados = deque(maxlen=60)  # Histórico de sinais finalizados (máximo 60)
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
        
        for minuto_chave in list(self.sinais_agrupados.keys()):
            self.verificar_confluencia(minuto_chave)
    
    def get_nivel_confluencia(self, quantidade):
        """Retorna o nível de confluência baseado na quantidade"""
        if quantidade >= self.config_confluencia['alta']:
            return 'ALTA'
        elif quantidade >= self.config_confluencia['media']:
            return 'MÉDIA'
        elif quantidade >= self.config_confluencia['baixa']:
            return 'BAIXA'
        else:
            return 'MINIMA'
    
    def criar_estrategias_padrao(self):
        """Cria o dicionário padrão com todas estratégias ativas (APENAS as que têm lógica completa)"""
        todas_estrategias = [
            "2. Pedra posterior + minuto", "4. 2 pedras posteriores + minuto", 
            "6. 2ª pedra posterior + minuto", "8. Minuto invertido + hora", "9. Branco + 5min", 
            "10. Branco + 10min", "11. Pedra 4 + 4min", "12. Pedra 14 + 5min", 
            "13. Pedra 11 + 3min", "14. 2 pedras iguais +1h", "16. Soma 15/21 +10min", 
            "19. Branco + Minuto Duplo", "20. 2 pedras iguais +14min", 
            "21. Seq30 [1] +35min", "21. Seq30 [2] +3min", "21. Seq30 [3] +3min", 
            "21. Seq30 [4] +5min", "21. Seq30 [5] +3min", "21. Seq30 [6] +5min", 
            "21. Seq30 [7] +3min", "22. Dobra de Branco", "23. Gêmeas",
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
        """Processa resultado para verificar se acertou algum sinal ativo"""
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
                        
                        self.historico_finalizados.append(sinal.copy())
                        sinais_para_remover.append(sinal)
                    else:
                        pass # Continua aguardando na janela
                
                # Verifica se passou do tempo de janela para marcar como LOSS
                elif agora > sinal['janela_fim']:
                    sinal['resultado'] = 'LOSS'
                    sinal['status'] = 'finalizado'
                    sinal['horario_resultado'] = agora
                    self.historico_finalizados.append(sinal.copy())
                    sinais_para_remover.append(sinal)
        
        # Remove sinais processados
        for sinal in sinais_para_remover:
            if sinal in self.sinais_ativos:
                self.sinais_ativos.remove(sinal)
    
    def limpar_dados_antigos(self):
        """Limpa dados expirados - estratégias apagam 1 minuto após passar o horário"""
        agora = agora_brasil()
        
        # Limpa estratégias com mais de 1 minuto após a janela
        self.todas_estrategias = [e for e in self.todas_estrategias 
                                if agora <= e.get('janela_fim', agora) + timedelta(minutes=1)]
        
        # Limpa sinais agrupados expirados
        for minuto_chave in list(self.sinais_agrupados.keys()):
            if agora > minuto_chave.replace(second=30) + timedelta(minutes=2):  # Janela + 1min
                del self.sinais_agrupados[minuto_chave]
    
    def get_estrategias_recentes(self):
        """Retorna estratégias recentes (não expiradas)"""
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
        """Retorna sinais finalizados recentes (últimos 60)"""
        return list(self.historico_finalizados)

class AnalisadorEstrategiaHorarios:
    def __init__(self):
        self.ultimas_rodadas = deque(maxlen=100)
        self.gerenciador = GerenciadorSinais()
        self.ultimo_branco = None
        self.brancos_pendentes = []
        self.contador_sem_branco = 0
        self.ultimo_branco_antes_sequencia = None
    
    # === Métodos de Utilidade/Lookback (APENAS LÓGICA COMPLETA) ===

    def get_pedra_posterior_para_branco(self, horario_branco):
        """Retorna o número da primeira pedra posterior ao branco (ou None/0)"""
        for cor, numero, horario in reversed(self.ultimas_rodadas):
            if horario > horario_branco and cor != 'branco':
                return numero
        return 0
    
    def get_soma_2_posteriores_para_branco(self, horario_branco):
        """Retorna a soma das duas primeiras pedras posteriores ao branco (ou None/0)"""
        somas = []
        for cor, numero, horario in reversed(self.ultimas_rodadas):
            if horario > horario_branco and cor != 'branco':
                somas.append(numero)
                if len(somas) == 2:
                    return sum(somas)
        return sum(somas)

    def get_segunda_posterior_para_branco(self, horario_branco):
        """Retorna o número da segunda pedra posterior ao branco (ou None/0)"""
        contador = 0
        for cor, numero, horario in reversed(self.ultimas_rodadas):
            if horario > horario_branco and cor != 'branco':
                contador += 1
                if contador == 2:
                    return numero
        return 0

    def soma_horario_completo(self, horario):
        """Lógica para somar componentes do horário (hora, minuto, etc.)"""
        return horario.hour + horario.minute
    
    def get_valor_seguro(self, valor):
        """Retorna 0 se o valor for None para evitar erros de tipo"""
        return valor if valor is not None else 0
    
    def calcular_minuto_destino(self, soma):
        """Calcula o minuto de destino baseado na soma (1 a 60)"""
        if soma is None or soma == 0:
            return None
        if soma > 60:
            while soma > 60:
                soma -= 60
        elif soma < 1:
            while soma < 1:
                soma += 60
        return soma if 1 <= soma <= 60 else None

    def calcular_minuto_destino_fixo(self, minuto_calculado):
        """Calcula minuto destino para estratégias fixas"""
        if minuto_calculado is None:
            return None
        if minuto_calculado > 60:
            minuto_calculado -= 60
        elif minuto_calculado < 1:
            minuto_calculado += 60
        return minuto_calculado if 1 <= minuto_calculado <= 60 else None

    def calcular_horario_destino(self, minuto_destino, hora_base):
        """Calcula o horário completo de destino"""
        if minuto_destino is None:
            return None
        try:
            agora = agora_brasil()
            horario_destino = agora.replace(hour=hora_base, minute=minuto_destino, second=30, microsecond=0)
            if horario_destino <= agora:
                horario_destino += timedelta(hours=1)
            while horario_destino <= agora:
                horario_destino += timedelta(hours=1)
            return horario_destino
        except:
            return None
    
    # === Lógica de Adição de Rodada e Processamento de Sinais ===
    def adicionar_rodada(self, cor, numero, horario_real):
        self.ultimas_rodadas.append((cor, numero, horario_real))
        
        # Atualiza contador de pedras sem branco
        if cor == 'branco':
            self.ultimo_branco = (cor, numero, horario_real)
            self.brancos_pendentes.append(horario_real)
            self.contador_sem_branco = 0
            self.ultimo_branco_antes_sequencia = horario_real
            
            # Estratégias imediatas ao sair branco
            self.gerar_sinais_imediatos_apos_branco(horario_real, numero)
            self.estrategia_19_branco_minuto_duplo(horario_real)
            self.estrategia_dobra_branco(horario_real)
        else:
            self.contador_sem_branco += 1
            self.processar_estrategias_posteriores(cor, numero, horario_real)
        
        # Verifica estratégias de contagem
        self.verificar_30_sem_brancos(horario_real)
        self.verificar_50_sem_brancos(horario_real)
        self.verificar_60_sem_brancos(horario_real)
        self.verificar_80_sem_brancos(horario_real)
        
        self.gerar_sinais_pedra_atual(cor, numero, horario_real)
        self.verificar_duas_pedras_iguais(cor, numero, horario_real)
        self.verificar_soma_15_21(cor, numero, horario_real)
        self.verificar_gemeas(cor, numero, horario_real)
        
        # Processa resultado para sinais ativos
        self.gerenciador.processar_resultado(horario_real, cor)

    # === Implementação das Estratégias ===
    
    def estrategia_dobra_branco(self, horario_branco):
        """ESTRATÉGIA 22: Dobra de Branco"""
        minuto_branco = horario_branco.minute
        soma_minutos = minuto_branco + minuto_branco
        minuto_destino = self.calcular_minuto_destino(soma_minutos)
        
        if minuto_destino:
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_branco.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "22. Dobra de Branco"
                self.gerenciador.adicionar_estrategia(estrategia_nome, horario_sinal, minuto_destino, horario_branco)
    
    def verificar_gemeas(self, cor, numero, horario):
        """ESTRATÉGIA 23: Gêmeas - Duas pedras iguais no mesmo minuto"""
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
                        estrategia_nome = f"23. Gêmeas {valor_gemeas}"
                        self.gerenciador.adicionar_estrategia(estrategia_nome, horario_sinal, minuto_destino, horario)
    
    def verificar_50_sem_brancos(self, horario_atual):
        """ESTRATÉGIA 24: 50 rodadas sem branco → sinal direto +4min"""
        if self.contador_sem_branco == 50:
            minuto_destino = (horario_atual.minute + 4) % 60
            if minuto_destino == 0:
                minuto_destino = 60
            
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "24. 50 sem Branco +4min"
                self.gerenciador.adicionar_sinal_direto(estrategia_nome, horario_sinal, minuto_destino, horario_atual)
    
    def verificar_60_sem_brancos(self, horario_atual):
        """ESTRATÉGIA 25: 60 rodadas sem branco → sinal direto +4min"""
        if self.contador_sem_branco == 60:
            minuto_destino = (horario_atual.minute + 4) % 60
            if minuto_destino == 0:
                minuto_destino = 60
            
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "25. 60 sem Branco +4min"
                self.gerenciador.adicionar_sinal_direto(estrategia_nome, horario_sinal, minuto_destino, horario_atual)
    
    def verificar_80_sem_brancos(self, horario_atual):
        """ESTRATÉGIA 26: 80 rodadas sem branco → sinal direto +4min"""
        if self.contador_sem_branco == 80:
            minuto_destino = (horario_atual.minute + 4) % 60
            if minuto_destino == 0:
                minuto_destino = 60
            
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_atual.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                estrategia_nome = "26. 80 sem Branco +4min"
                self.gerenciador.adicionar_sinal_direto(estrategia_nome, horario_sinal, minuto_destino, horario_atual)
    
    def estrategia_19_branco_minuto_duplo(self, horario_branco):
        """ESTRATÉGIA 19: Branco + Minuto Duplo"""
        minuto_branco = horario_branco.minute
        soma_minutos = minuto_branco + minuto_branco
        
        minuto_destino = self.calcular_minuto_destino(soma_minutos)
        if minuto_destino:
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario_branco.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("19. Branco + Minuto Duplo", horario_sinal, minuto_destino, horario_branco)
    
    def verificar_30_sem_brancos(self, horario_atual):
        """ESTRATÉGIA 21: Sequência após 30 pedras sem brancos"""
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
            
            self.contador_sem_branco = 0
    
    def gerar_sinais_imediatos_apos_branco(self, horario_branco, numero_branco):
        """Gera estratégias IMEDIATAS usando o minuto como horário de destino"""
        minuto_branco = horario_branco.minute
        hora_branco = horario_branco.hour
        
        estrategias_imediatas = [
            ("8. Minuto invertido + hora", lambda: self.calcular_minuto_destino( 
                int(str(minuto_branco).zfill(2)[::-1]) + self.soma_horario_completo(horario_branco))),
            ("9. Branco + 5min", lambda: self.calcular_minuto_destino_fixo(minuto_branco + 5)),
            ("10. Branco + 10min", lambda: self.calcular_minuto_destino_fixo(minuto_branco + 10)),
        ]
        
        for nome, calculo_minuto in estrategias_imediatas:
            try:
                minuto_destino = calculo_minuto()
                if minuto_destino:
                    horario_sinal = self.calcular_horario_destino(minuto_destino, hora_branco)
                    if horario_sinal and horario_sinal > agora_brasil():
                        self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, horario_branco)
            except (TypeError, ValueError, Exception):
                pass

    def processar_estrategias_posteriores(self, cor, numero, horario_pedra):
        """Processa estratégias POSTERIORES quando aparece uma pedra colorida"""
        if not self.brancos_pendentes:
            return
        
        brancos_processados = []
        for horario_branco in self.brancos_pendentes:
            minuto_branco = horario_branco.minute
            hora_branco = horario_branco.hour
            
            if horario_pedra > horario_branco:
                estrategias_posteriores = [
                    ("2. Pedra posterior + minuto", lambda: self.calcular_minuto_destino( 
                        self.get_valor_seguro(self.get_pedra_posterior_para_branco(horario_branco)) + minuto_branco)),
                    ("4. 2 pedras posteriores + minuto", lambda: self.calcular_minuto_destino( 
                        self.get_valor_seguro(self.get_soma_2_posteriores_para_branco(horario_branco)) + minuto_branco)),
                    ("6. 2ª pedra posterior + minuto", lambda: self.calcular_minuto_destino( 
                        self.get_valor_seguro(self.get_segunda_posterior_para_branco(horario_branco)) + minuto_branco)),
                ]
                
                for nome, calculo_minuto in estrategias_posteriores:
                    try:
                        minuto_destino = calculo_minuto()
                        if minuto_destino:
                            horario_sinal = self.calcular_horario_destino(minuto_destino, hora_branco)
                            if horario_sinal and horario_sinal > agora_brasil():
                                self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, horario_branco)
                    except (TypeError, ValueError, Exception):
                        pass

                brancos_processados.append(horario_branco)
            
        for branco in brancos_processados:
            if branco in self.brancos_pendentes:
                self.brancos_pendentes.remove(branco)

    def gerar_sinais_pedra_atual(self, cor, numero, horario):
        """Gera sinais baseados em pedras específicas (11, 14, 4)"""
        if cor == 'branco':
            return
        
        estrategias_pedra = [
            (4, "11. Pedra 4 + 4min", 4),
            (14, "12. Pedra 14 + 5min", 5),
            (11, "13. Pedra 11 + 3min", 3),
        ]
        
        for num_pedra, nome, minutos in estrategias_pedra:
            if numero == num_pedra:
                minuto_destino = (horario.minute + minutos) % 60
                if minuto_destino == 0:
                    minuto_destino = 60
                
                horario_sinal = self.calcular_horario_destino(minuto_destino, horario.hour)
                if horario_sinal and horario_sinal > agora_brasil():
                    self.gerenciador.adicionar_estrategia(nome, horario_sinal, minuto_destino, horario)

    def verificar_duas_pedras_iguais(self, cor, numero, horario):
        """Verifica se duas pedras iguais saíram no mesmo minuto"""
        if len(self.ultimas_rodadas) >= 2:
            rodadas_lista = list(self.ultimas_rodadas)
            ultima = rodadas_lista[-1]
            penultima = rodadas_lista[-2]
            
            # Verifica se são do mesmo número e no mesmo minuto (ignorando segundos)
            if (ultima[1] == penultima[1] and 
                ultima[2].replace(second=0) == penultima[2].replace(second=0)):
                
                # ESTRATÉGIA 14: 2 pedras iguais +1h
                minuto_destino = horario.minute
                horario_sinal = horario.replace(hour=horario.hour + 1, minute=minuto_destino, second=30)
                
                if horario_sinal <= agora_brasil():
                    horario_sinal += timedelta(days=1)
                    
                if horario_sinal > agora_brasil():
                    self.gerenciador.adicionar_estrategia("14. 2 pedras iguais +1h", horario_sinal, minuto_destino, horario)
                
                # ESTRATÉGIA 20: Duas pedras iguais +14min
                minuto_destino_20 = (horario.minute + 14) % 60
                if minuto_destino_20 == 0:
                    minuto_destino_20 = 60
                horario_sinal_20 = self.calcular_horario_destino(minuto_destino_20, horario.hour)
                if horario_sinal_20 and horario_sinal_20 > agora_brasil():
                    self.gerenciador.adicionar_estrategia("20. 2 pedras iguais +14min", horario_sinal_20, minuto_destino_20, horario)

    def verificar_soma_15_21(self, cor, numero, horario):
        """Verifica se a pedra é 15 ou 21 → sinal +10min"""
        if numero in [15, 21]:
            minuto_destino = (horario.minute + 10) % 60
            if minuto_destino == 0:
                minuto_destino = 60
            
            horario_sinal = self.calcular_horario_destino(minuto_destino, horario.hour)
            if horario_sinal and horario_sinal > agora_brasil():
                self.gerenciador.adicionar_estrategia("16. Soma 15/21 +10min", horario_sinal, minuto_destino, horario)

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

    if analisar_global is None:
        analisar_global = AnalisadorEstrategiaHorarios()
        print("🔄 Inicializando o Analisador de Estratégias.")
        
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

# ----------------------------------------
# Inicialização do Thread de Coleta (CORRIGIDO)
# ----------------------------------------
@app.before_request 
def start_thread():
    # Verifica se a thread já está rodando para evitar múltiplos inícios no Gunicorn
    if not hasattr(start_thread, 'thread_started'):
        start_thread.thread_started = False

    if not start_thread.thread_started:
        t = threading.Thread(target=iniciar_coleta_blaze, daemon=True)
        t.start()
        start_thread.thread_started = True

# ----------------------------------------
# Rotas do site
# ----------------------------------------
@app.route("/")
def index():
    # OBS: O arquivo 'index.html' deve estar na pasta 'modelos/'
    return render_template("index.html")

@app.route("/data")
@auth.login_required
def data():
    """Retorna dados consolidados para o front"""
    global analisar_global
    
    if analisar_global is None:
        return jsonify({"status": "aguardando inicialização..."})

    sinais_ativos = analisar_global.gerenciador.get_sinais_ativos()
    
    # CORRIGIDO: Usando 'analisar_global'
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
