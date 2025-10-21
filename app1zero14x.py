from flask import Flask, jsonify, render_template
import threading
import time
import requests
import os # Necessário para variáveis de ambiente (PORT)
import sys # Melhor para logs em ambiente de produção (Render/Gunicorn)


# Assumindo que sua pasta de templates chama 'modelos'
app = Flask(__name__, template_folder='modelos')

# Dicionário global que armazena os dados coletados
dados_coletados = {
    "ultimo": None,
    "sinais": [],
    "estatisticas": {
        "sinais": 0,
        "win": 0,
        "loss": 0,
        "assertividade": 0
    }
}


def coletar_dados_blaze():
    """Loop contínuo para coletar os dados da Blaze periodicamente"""
    global dados_coletados
    
    # Não há lógica de proxy/VPN aqui, a requisição usará o IP do Render.
    
    while True:
        try:
            url = "https://blaze.com/api/roulette_games/recent"
            
            # Requisição SEM proxy
            resposta = requests.get(url, timeout=10) 

            if resposta.status_code == 200:
                data = resposta.json()

                # Atualiza o último resultado e as 10 últimas jogadas
                dados_coletados["ultimo"] = data[0]
                dados_coletados["sinais"] = data[:10]

                # Atualiza estatísticas básicas
                total = len(data)
                win = len([r for r in data if r["color"] == 1])
                loss = len([r for r in data if r["color"] == 2])
                assertividade = round((win / total) * 100, 2) if total > 0 else 0

                dados_coletados["estatisticas"] = {
                    "sinais": total,
                    "win": win,
                    "loss": loss,
                    "assertividade": assertividade
                }

                print("✅ Dados atualizados com sucesso.", file=sys.stderr)

            else:
                print(f"⚠️ Erro ao acessar API Blaze ({resposta.status_code})", file=sys.stderr)

        except Exception as e:
            # O erro de Bloqueio de IP / Timeout (RequestException) cairá aqui
            print(f"❌ Erro na coleta de dados: {e}", file=sys.stderr)

        # Aguarda 5 segundos entre as coletas
        time.sleep(5)


@app.route('/')
def index():
    """Rota principal — carrega o painel (index.html)"""
    return render_template('index.html')


@app.route('/data')
def data():
    """Rota que fornece os dados atualizados em JSON"""
    return jsonify(dados_coletados)


# =============================================================================
# CORREÇÃO CRÍTICA PARA SERVIDOR GUNICORN/RENDER (Thread)
# A thread de coleta AGORA será iniciada pelo servidor (e não ignorada).
# =============================================================================
@app.before_first_request
def iniciar_coleta():
    coletor_thread = threading.Thread(target=coletar_dados_blaze, daemon=True)
    coletor_thread.start()
    print("🚀 Thread de coleta de dados iniciada com sucesso.", file=sys.stderr)


if __name__ == '__main__':
    # Pega a porta da variável de ambiente, ou usa 5000 como padrão
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Servidor Flask iniciado na porta {port}.", file=sys.stderr)
    # debug=False é crucial para não criar threads duplicadas
    app.run(host='0.0.0.0', port=port, debug=False)
