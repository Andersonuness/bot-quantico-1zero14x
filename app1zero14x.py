import threading
import time
import requests
from collections import deque, defaultdict
from datetime import datetime
from flask import Flask, jsonify
from flask_httpauth import HTTPBasicAuth

# =========================================
# CONFIGURAÇÕES INICIAIS
# =========================================
app = Flask(__name__)
auth = HTTPBasicAuth()

# Usuários e senha padrão
USUARIOS_VALIDOS = {
    "adm": "P@$1zero14x!"
}
for i in range(1, 21):
    USUARIOS_VALIDOS[f"user{i:02}"] = "P@$1zero14x!"


@auth.verify_password
def verificar_usuario(usuario, senha):
    return USUARIOS_VALIDOS.get(usuario) == senha


# =========================================
# CLASSES PRINCIPAIS
# =========================================
class EstatisticasEstrategias:
    def __init__(self):
        self.sinais = 0
        self.win = 0
        self.loss = 0

    def calcular_percentual(self):
        if self.sinais == 0:
            return "0%"
        return f"{round((self.win / self.sinais) * 100)}%"


class GerenciadorSinais:
    def __init__(self):
        self.sinais_ativos = []
        self.historico_finalizados = deque(maxlen=60)
        self.estatisticas = EstatisticasEstrategias()

    def processar_resultado(self, horario_resultado, cor):
        """
        Processa o resultado retornado da Blaze.
        Adiciona ao histórico e define sinal ativo.
        """
        self.historico_finalizados.append({
            'horario': horario_resultado.strftime('%H:%M:%S'),
            'cor': cor
        })

        # Exemplo: ativa sinal apenas para cores relevantes
        if cor in ['vermelho', 'branco']:
            self.sinais_ativos = [{
                'horario': horario_resultado.strftime('%H:%M:%S'),
                'forca': 'MÉDIA',
                'estrategias': 'Detecção de cor ' + cor.upper()
            }]
        else:
            self.sinais_ativos = []


class ColetorResultados:
    def __init__(self):
        self.ultimas_rodadas = deque(maxlen=100)
        self.gerenciador = GerenciadorSinais()
        self.api_url = "https://blaze.com/api/roulette_games/recent"

    def buscar_resultados(self):
        """
        Faz a coleta dos dados da API da Blaze.
        """
        try:
            resposta = requests.get(self.api_url, timeout=10)
            if resposta.status_code == 200:
                dados = resposta.json()
                novos = []
                for item in dados:
                    cor = self.definir_cor(item)
                    numero = item['roll']
                    horario = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
                    novos.append((cor, numero, horario))

                # Adiciona apenas novos resultados
                novos = list(reversed(novos))
                for r in novos:
                    if not self.ultimas_rodadas or self.ultimas_rodadas[-1][2] < r[2]:
                        self.ultimas_rodadas.append(r)
                        self.gerenciador.processar_resultado(r[2], r[0])
                        print(f"[THREAD] Novo resultado processado: {r[0]} {r[1]} {r[2].strftime('%H:%M:%S')}")

        except Exception as e:
            print(f"[ERRO API] {e}")

    @staticmethod
    def definir_cor(item):
        if item['color'] == 0:
            return 'vermelho'
        elif item['color'] == 1:
            return 'preto'
        else:
            return 'branco'


# =========================================
# OBJETO GLOBAL DO COLETOR
# =========================================
analisar_global = ColetorResultados()


def thread_coleta_dados():
    while True:
        analisar_global.buscar_resultados()
        time.sleep(5)  # Atualiza a cada 5 segundos


# =========================================
# ROTAS FLASK
# =========================================
@app.route('/')
def index():
    return "API 1ZERO14X em execução - acesso via /data"


@app.route('/data')
@auth.login_required
def data():
    """
    Rota que envia os dados para o painel web.
    """
    ger = analisar_global.gerenciador
    todas_rodadas = list(analisar_global.ultimas_rodadas)

    ultima_rodada = None
    if todas_rodadas:
        r = todas_rodadas[-1]
        ultima_rodada = {
            'cor': r[0],
            'numero': r[1],
            'horario': r[2].strftime('%H:%M:%S')
        }

    ultimas_10 = todas_rodadas[-10:]
    ultimas_10_formatadas = [
        {'cor': r[0], 'numero': r[1], 'horario': r[2].strftime('%H:%M:%S')}
        for r in ultimas_10
    ]

    data = {
        'ultimo_resultado': ultima_rodada,
        'ultimas_10_rodadas': ultimas_10_formatadas,
        'estatisticas': {
            'sinais': len(ger.historico_finalizados),
            'win': ger.estatisticas.win,
            'loss': ger.estatisticas.loss,
            'perc': ger.estatisticas.calcular_percentual()
        },
        'sinais_ativos': ger.sinais_ativos,
        'historico_sinais': list(ger.historico_finalizados)
    }

    return jsonify(data)


# =========================================
# EXECUÇÃO
# =========================================
if __name__ == '__main__':
    # Inicia a thread de coleta
    thread = threading.Thread(target=thread_coleta_dados, daemon=True)
    thread.start()

    print("[SERVIDOR] Flask iniciado com coleta em thread paralela.")
    app.run(host='0.0.0.0', port=5000)
