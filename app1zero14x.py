from flask import Flask, jsonify, render_template
import threading
import time
import requests

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
    while True:
        try:
            url = "https://blaze.com/api/roulette_games/recent"
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

                print("✅ Dados atualizados com sucesso.")

            else:
                print(f"⚠️ Erro ao acessar API Blaze ({resposta.status_code})")

        except Exception as e:
            print(f"❌ Erro na coleta de dados: {e}")

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


if __name__ == '__main__':
    # Inicia o coletor da Blaze em segundo plano
    coletor_thread = threading.Thread(target=coletar_dados_blaze, daemon=True)
    coletor_thread.start()

    print("🚀 Servidor Flask iniciado — Acesse via Render")
    app.run(host='0.0.0.0', port=5000)
