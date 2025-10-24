import eventlet
import sys

try:
    eventlet.monkey_patch() 
except RuntimeError:
    pass

from flask import Flask, render_template, request, redirect, url_for, session, current_app
from flask_socketio import SocketIO, emit, disconnect
from flask_mysqldb import MySQL
# IMPORTAÇÕES DO CHATBOT
from google import genai
from google.genai import types
from dotenv import load_dotenv
from uuid import uuid4
import os
import hashlib
import json

# Carrega variáveis de ambiente (GENAI_KEY)
load_dotenv()

# *******************************************************************
# CONFIGURAÇÃO GERAL DO FLASK E MYSQL
# *******************************************************************
app = Flask(__name__, 
            template_folder='../templates', 
            static_folder='../static') 

# CONFIGURAÇÃO DE SEGURANÇA
app.secret_key = 'levelup' # Mantenha a chave do app.py
# CONFIGURAÇÃO DO CHATBOT: Substitua pela sua chave GENAI_KEY
GENAI_KEY = os.getenv("GENAI_KEY")
client = genai.Client(api_key=GENAI_KEY)

# CONFIGURAÇÃO DO BANCO DE DADOS (MySQL)
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'         # Mude para seu usuário MySQL
app.config['MYSQL_PASSWORD'] = 'rdbanco' # Mude para sua senha MySQL
app.config['MYSQL_DB'] = 'levelup'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# CONFIGURAÇÃO DO SOCKETIO
# O SocketIO usará o objeto Flask (app)
socketio = SocketIO(app, 
                    cors_allowed_origins="*",
                    # Garante que a sessão Flask seja acessível no SocketIO
                    manage_session=False, 
                    async_mode='eventlet') 

# *******************************************************************
# LÓGICA DO CHATBOT (NOVO CONTEXTO: Professor do Curso)
# *******************************************************************
active_chats = {} # Armazena as sessões de chat contínuo por session_id

def get_curso_system_instruction(curso_acesso):
    """Gera as instruções do sistema baseadas no curso atual do aluno."""
    return f"""
Você é o Professor Dinossauro, um assistente virtual inteligente, amigável e focado.
Seu papel é atuar como um professor particular, oferecendo informações, dicas e tirando dúvidas **APENAS** sobre o conteúdo do curso de {curso_acesso} que o aluno está estudando.

Seja breve, direto e sucinto. Evite respostas longas. Use um tom encorajador e educativo.
Se a pergunta for irrelevante ou fora do escopo do curso de {curso_acesso}, responda educadamente que você é especialista apenas neste curso.

Regras importantes:
Não incentive nem normalize conteúdos impróprios, ilegais ou perigosos.
Não forneça diagnósticos médicos, conselhos legais ou instruções perigosas. Sempre recomende profissionais.
Ignore provocações.

Exemplos de tom:
“Opa! Vou te ajudar rapidinho com isso do {curso_acesso}.”
“Boa pergunta! No módulo X, você viu que...”
"""

def get_user_chat(curso_acesso):
    """Obtém ou cria uma sessão de chat Gemini para o usuário atual, baseada no curso."""
    # Como você quer o contexto do curso, a instrução de sistema deve ser específica.
    # Usaremos o curso_acesso da sessão para gerar a instrução.
    
    if 'session_id' not in session:
        session['session_id'] = str(uuid4())
    
    session_id = session['session_id']
    
    # 1. Gera uma chave única que inclui o curso, para garantir que o chat mude se o aluno mudar de curso
    chat_key = f"{session_id}_{curso_acesso}"
    
    if chat_key not in active_chats:
        app.logger.info(f"Criando novo chat Gemini para chave: {chat_key}")
        try:
            # Gera as instruções específicas do curso
            instrucoes_curso = get_curso_system_instruction(curso_acesso)
            
            chat_session = client.chats.create(
                model="gemini-2.5-flash", # Modelo mais moderno e capaz
                config=types.GenerateContentConfig(system_instruction=instrucoes_curso)
            )
            active_chats[chat_key] = chat_session
        except Exception as e:
            app.logger.error(f"Erro ao criar chat Gemini para {chat_key}: {e}", exc_info=True)
            raise
            
    # Retorna o chat associado à chave única (session_id + curso)
    return active_chats[chat_key]

@socketio.on('connect')
def handle_connect():
    """Chamado quando um cliente se conecta via WebSocket."""
    # O 'curso_acesso' não está diretamente disponível aqui, mas a conexão inicializa a sessão Flask.
    # A primeira mensagem do cliente (enviada por JS) deve ser o gatilho principal para get_user_chat.
    with current_app.app_context():
        user_session_id = session.get('session_id', 'N/A')
        emit('status_conexao', {'data': 'Conectado. Olá! Como posso ajudar com o curso?', 'session_id': user_session_id})

@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    """Manipulador para o evento 'enviar_mensagem' emitido pelo cliente."""
    with current_app.app_context():
        try:
            mensagem_usuario = data.get("mensagem")
            # NOVO: Recebe o nome do curso para contextualizar
            curso_acesso = data.get('curso_acesso')
            nome = session.get('nome', 'Aluno')
            
            if not mensagem_usuario or not curso_acesso:
                emit('erro', {"erro": "Mensagem ou contexto do curso ausente."})
                return
                
            app.logger.info(f"Mensagem recebida para o curso '{curso_acesso}': {mensagem_usuario}")
            
            # OBTÉM OU CRIA A SESSÃO DE CHAT (com contexto do curso)
            user_chat = get_user_chat(curso_acesso)

            if user_chat is None:
                emit('erro', {"erro": "Sessão de chat não pôde ser estabelecida."})
                return
                
            # 1. Envia a mensagem para o Gemini
            resposta_gemini = user_chat.send_message(mensagem_usuario)
            
            # 2. Extrai o texto da resposta
            resposta_texto = resposta_gemini.text
            
            # 3. Emite a resposta de volta para o cliente
            emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto})
            
        except Exception as e:
            app.logger.error(f"Erro ao processar 'enviar_mensagem': {e}", exc_info=True)
            emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})

@socketio.on('disconnect')
def handle_disconnect():
    app.logger.info(f"Cliente desconectado: {request.sid}")


# *******************************************************************
# FUNÇÕES E ROTAS EXISTENTES DO SEU APP.PY (NÃO ALTERADAS)
# *******************************************************************

def carregar_conteudo_json(curso, ordem):
    # ... (Sua função carregar_conteudo_json)
    """
    Carrega o conteúdo do módulo a partir de um arquivo JSON.
    Assumimos que o arquivo está em: ../static/json_content/{curso}/modulo_{ordem}.json
    """
    try:
        # Pega o diretório base do projeto (onde app.py está)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        curso_limpo = curso.lower().replace('ê', 'e').replace('ã', 'a')
        
        # Constrói o caminho completo do arquivo
        caminho_arquivo = os.path.join(base_dir, 
                                       '..', 
                                       'static', 
                                       'json_content', 
                                       curso_limpo, 
                                       f'modulo_{ordem}.json')
        
        print(f"\n[DEBUG JSON] Tentando abrir: {caminho_arquivo}\n")
            
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            conteudo = json.load(f)
            return conteudo
    except FileNotFoundError:
        print(f"[ERRO JSON] Arquivo não encontrado no caminho: {caminho_arquivo}")
        return None
    except json.JSONDecodeError:
        print(f"[ERRO JSON] JSON mal formatado em: {caminho_arquivo}")
        return None

def login_required(f):
    """Verifica se o aluno está logado na sessão."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'loggedin' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# *******************************************************************
# ROTAS DO FLASK (RF01 - RF14)
# *******************************************************************
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT aluno_id, nome, senha_hash, curso_acesso FROM aluno WHERE email = %s", [email])
        aluno = cur.fetchone()
        cur.close()

        if aluno:
            senha_hash_input = hashlib.sha256(senha.encode()).hexdigest()
            
            if senha_hash_input == aluno['senha_hash']:
                session['loggedin'] = True
                session['aluno_id'] = aluno['aluno_id']
                session['nome'] = aluno['nome']
                session['curso_acesso'] = aluno['curso_acesso']
                
                return redirect(url_for('curso_home'))
            else:
                return render_template('login.html', erro='Email ou senha incorretos.')
        else:
            return render_template('login.html', erro='Email ou senha incorretos.')
    
    return render_template('login.html')

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']
        curso_acesso = request.form['curso_acesso']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM aluno WHERE email = %s", [email])
        if cur.fetchone():
            cur.close()
            return render_template('cadastro.html', erro='Este email já está cadastrado.')

        senha_hash = hashlib.sha256(senha.encode()).hexdigest()

        cur.execute("INSERT INTO aluno (nome, email, senha_hash, curso_acesso) VALUES (%s, %s, %s, %s)", 
                    (nome, email, senha_hash, curso_acesso))
        
        mysql.connection.commit()
        cur.close()
        
        return redirect(url_for('login'))

    return render_template('cadastro.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/curso')
@login_required
def curso_home():
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']
    
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT modulo_id, nome, ordem FROM modulo WHERE curso_acesso = %s ORDER BY ordem ASC", [curso_acesso])
    modulos = cur.fetchall()
    
    cur.execute("SELECT modulo_id, status_modulo, nota_final FROM desempenho_modulo WHERE aluno_id = %s", [aluno_id])
    desempenho = cur.fetchall()
    
    cur.close()

    desempenho_map = {item['modulo_id']: item for item in desempenho}

    modulos_com_progresso = []
    modulos_concluidos = 0
    total_modulos = len(modulos)

    for modulo in modulos:
        modulo_progresso = desempenho_map.get(modulo['modulo_id'], None)
        
        status = modulo_progresso['status_modulo'] if modulo_progresso else 'Não Iniciado'
        
        if status == 'Concluído':
            modulos_concluidos += 1
        
        modulos_com_progresso.append({
            'modulo_id': modulo['modulo_id'],
            'nome': modulo['nome'],
            'ordem': modulo['ordem'],
            'status': status,
            'nota_final': modulo_progresso.get('nota_final') if modulo_progresso else None
        })

    progresso_curso_porcentagem = 0
    if total_modulos > 0:
        progresso_curso_porcentagem = round((modulos_concluidos / total_modulos) * 100)
    
    # Renderiza a página principal do curso
    return render_template('curso_home.html', 
                            curso=curso_acesso,
                            modulos=modulos_com_progresso,
                            progresso_curso=progresso_curso_porcentagem)

@app.route('/curso/<string:curso>/modulo/<int:ordem>', methods=['GET'])
@login_required
def modulo_page(curso, ordem):
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']
    
    curso_limpo = curso.lower().replace('ê', 'e').replace('ã', 'a')
    curso_session_limpo = curso_acesso.lower().replace('ê', 'e').replace('ã', 'a')

    if curso_limpo != curso_session_limpo:
        return "Acesso negado ao curso.", 403

    if ordem > 1:
        modulo_anterior_ordem = ordem - 1
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND ordem = %s", 
                    [curso_acesso, modulo_anterior_ordem])
        modulo_anterior = cur.fetchone()
        
        if modulo_anterior:
            cur.execute("SELECT status_modulo FROM desempenho_modulo WHERE aluno_id = %s AND modulo_id = %s", 
                        [aluno_id, modulo_anterior['modulo_id']])
            progresso_anterior = cur.fetchone()
            cur.close()
            
            if not progresso_anterior or progresso_anterior['status_modulo'] != 'Concluído':
                return redirect(url_for('curso_home'))
        else:
            cur.close()
            return "Módulo anterior não encontrado.", 404

    conteudo = carregar_conteudo_json(curso_limpo, ordem)
    if not conteudo:
        return "Conteúdo do módulo não encontrado ou inválido.", 404
    
    return render_template('modulo_page.html', 
                            curso=curso_limpo, 
                            ordem=ordem, 
                            conteudo=conteudo)

@app.route('/curso/<string:curso>/modulo/<int:ordem>', methods=['POST'])
@login_required
def enviar_atividade(curso, ordem):
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']
    NOTA_MINIMA_ACERTOS = 7 
    
    curso_limpo = curso.lower().replace('ê', 'e').replace('ã', 'a')
    
    conteudo = carregar_conteudo_json(curso_limpo, ordem)
    if not conteudo:
        return "Erro: Conteúdo do módulo indisponível.", 404

    respostas_corretas = conteudo.get('respostas_corretas', {})
    respostas_aluno = request.form
    
    total_perguntas = len(respostas_corretas)
    acertos = 0
    
    for id_pergunta, resposta_correta in respostas_corretas.items():
        resposta_aluno = respostas_aluno.get(f'pergunta_{id_pergunta}')
        if resposta_aluno and resposta_aluno.upper() == resposta_correta.upper():
            acertos += 1
            
    erros = total_perguntas - acertos
    nota_final = (acertos / total_perguntas) * 100 if total_perguntas > 0 else 0
    
    aprovado = acertos >= NOTA_MINIMA_ACERTOS
    # Mapeamento para o ENUM do DB (Concluído/Em Andamento)
    novo_status = 'Concluído' if aprovado else 'Em Andamento' 
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND ordem = %s", [curso_acesso, ordem])
    modulo_info = cur.fetchone()
    
    if not modulo_info:
        cur.close()
        return "Módulo não encontrado no banco de dados.", 404

    modulo_id = modulo_info['modulo_id']
    
    sql_desempenho = """
        INSERT INTO desempenho_modulo (aluno_id, modulo_id, status_modulo, nota_final, data_conclusao)
        VALUES (%s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE 
            status_modulo = VALUES(status_modulo), 
            nota_final = VALUES(nota_final),
            data_conclusao = NOW()
    """
    cur.execute(sql_desempenho, (aluno_id, modulo_id, novo_status, nota_final))

    if aprovado:
        proxima_ordem = ordem + 1
        cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND ordem = %s", [curso_acesso, proxima_ordem])
        proximo_modulo = cur.fetchone()
        
        if proximo_modulo:
            proximo_modulo_id = proximo_modulo['modulo_id']
            
            # Usando 'Em Andamento' para o desbloqueio, conforme ajustado.
            sql_desbloqueio = """
                INSERT INTO desempenho_modulo (aluno_id, modulo_id, status_modulo, nota_final, data_conclusao)
                VALUES (%s, %s, 'Em Andamento', 0.00, NULL)
                ON DUPLICATE KEY UPDATE 
                    aluno_id = aluno_id
            """
            cur.execute(sql_desbloqueio, (aluno_id, proximo_modulo_id))
            
    mysql.connection.commit()
    cur.close()

    return render_template('desempenho_popup.html', 
                            acertos=acertos, 
                            erros=erros, 
                            total_perguntas=total_perguntas,
                            nota_final=nota_final,
                            aprovado=aprovado)

@app.route('/perfil')
@login_required
def perfil():
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']
    
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT nome, email, curso_acesso FROM aluno WHERE aluno_id = %s", [aluno_id])
    dados_aluno = cur.fetchone()
    
    if not dados_aluno:
        cur.close()
        session.clear()
        return redirect(url_for('login'))

    cur.execute("SELECT COUNT(modulo_id) AS total_modulos FROM modulo WHERE curso_acesso = %s", [curso_acesso])
    total_modulos = cur.fetchone()['total_modulos']

    sql_concluidos = """
        SELECT COUNT(dm.modulo_id) AS modulos_concluidos 
        FROM desempenho_modulo dm
        JOIN modulo m ON dm.modulo_id = m.modulo_id
        WHERE dm.aluno_id = %s 
        AND m.curso_acesso = %s
        AND dm.status_modulo = 'Concluído'
    """
    cur.execute(sql_concluidos, [aluno_id, curso_acesso])
    modulos_concluidos = cur.fetchone()['modulos_concluidos']

    sql_atividade_recente = """
        SELECT m.nome, dm.data_conclusao
        FROM desempenho_modulo dm
        JOIN modulo m ON dm.modulo_id = m.modulo_id
        WHERE dm.aluno_id = %s 
        AND dm.status_modulo = 'Concluído'
        ORDER BY dm.data_conclusao DESC
        LIMIT 5
    """
    cur.execute(sql_atividade_recente, [aluno_id])
    atividades_recente = cur.fetchall()
    
    cur.close()

    progresso_curso_porcentagem = 0
    if total_modulos > 0:
        progresso_curso_porcentagem = round((modulos_concluidos / total_modulos) * 100)
    
    return render_template('perfil.html', 
                            nome=dados_aluno['nome'],
                            email=dados_aluno['email'],
                            curso=dados_aluno['curso_acesso'],
                            progresso_curso=progresso_curso_porcentagem,
                            modulos_concluidos=modulos_concluidos,
                            total_modulos=total_modulos,
                            atividades_recente=atividades_recente)

@app.route('/pagamento/<string:curso_acesso>')
def pagamento_ficticio(curso_acesso):
    if curso_acesso not in ['Inglês', 'Espanhol']:
        return redirect(url_for('index'))
    return render_template('pagamento.html', curso_acesso=curso_acesso)
                            
if __name__ == '__main__':
    # IMPORTANTE: Mude a forma de execução para usar o SocketIO
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, use_reloader=False)