import eventlet
import sys

try:
    eventlet.monkey_patch() 
except RuntimeError:
    pass

from flask import Flask, render_template, request, redirect, url_for, session, current_app, flash
from flask_socketio import SocketIO, emit, disconnect
from flask_mysqldb import MySQL
# IMPORTAÇÕES DO CHATBOT
from google import genai
from google.genai import types
from dotenv import load_dotenv
from uuid import uuid4
from unidecode import unidecode
import os
import hashlib
import json
import re

NIVEIS_ORDEM = {
    'Básico': 'Intermediário',
    'Intermediário': 'Avançado',
    'Avançado': 'Concluído'
}

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

# -------------------------------------------------------------------
# CONFIGURAÇÃO DO CHATBOT COM CHAVES ROTATIVAS (NOVO SISTEMA)
# -------------------------------------------------------------------
# 1. Carregar todas as chaves disponíveis do .env
GENAI_KEYS = []
i = 1   
while os.getenv(f"GENAI_KEY_{i}"):
    GENAI_KEYS.append(os.getenv(f"GENAI_KEY_{i}"))
    i += 1

if not GENAI_KEYS:
    # Se isso acontecer, ele para o programa e alerta que não há chaves.
    raise RuntimeError("Nenhuma chave Gemini API encontrada no arquivo .env (Esperando GENAI_KEY_1, GENAI_KEY_2, etc.)")

# 2. Variável de controle (global) para a chave ativa
API_STATE = {
    'active_key_index': 0,
    # Inicializa o cliente usando a primeira chave (índice 0)
    'client': genai.Client(api_key=GENAI_KEYS[0]) 
}
# -------------------------------------------------------------------

def switch_to_next_api_key():
    """
    Alterna para a próxima chave de API disponível.
    Retorna True se conseguir mudar, False se todas falharam.
    """
    global API_STATE, GENAI_KEYS
    
    current_index = API_STATE['active_key_index']
    next_index = (current_index + 1) % len(GENAI_KEYS) # Rota para o próximo índice

    if next_index == current_index:
        # Significa que só há 1 chave, ou que o loop deu uma volta completa.
        app.logger.error("ERRO GRAVE: A única chave API falhou ou todas as chaves falharam.")
        return False
        
    try:
        new_key = GENAI_KEYS[next_index]
        API_STATE['client'] = genai.Client(api_key=new_key)
        API_STATE['active_key_index'] = next_index
        app.logger.warning(f"Chave API esgotada/falhou. Mudando para a chave no índice {next_index}.")
        return True
    except Exception as e:
        app.logger.error(f"Falha ao inicializar o cliente com a chave no índice {next_index}: {e}")
        return False

def send_message_with_rotation(chat_session, mensagem_usuario):
    """
    Envia a mensagem e tenta rotacionar a chave em caso de erro da API.
    Retorna a resposta do Gemini ou levanta uma exceção final.
    """
    global API_STATE
    
    # Tentativa 1
    try:
        return chat_session.send_message(mensagem_usuario)
    except (genai.errors.ResourceExhausted, genai.errors.PermissionDenied) as e:
        # ResourceExhausted: Limite atingido (rate limit)
        # PermissionDenied: Chave inválida ou expirada
        app.logger.warning(f"Erro da API (chave): {type(e).__name__}. Tentando rotacionar a chave...")
        
        # 1. Tentar rotacionar a chave
        if switch_to_next_api_key():
            # 2. Recriar a sessão de chat (pois a antiga está ligada ao cliente velho)
            # Nota: Isso recria o histórico, então o contexto anterior será perdido!
            # Para manter o histórico, você precisaria reconstruir a conversa manualmente.
            # Por simplicidade e em caso de falha de chave, vamos começar do zero.
            curso_acesso = chat_session.config.system_instruction.split("curso de ")[-1].strip().split()[0]
            
            # Recria o chat usando o NOVO cliente da API_STATE
            new_chat_session = API_STATE['client'].chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=get_curso_system_instruction(curso_acesso)
                )
            )
            
            # 3. Tentar enviar a mensagem novamente com a nova sessão
            return new_chat_session.send_message(mensagem_usuario)
        else:
            # Não conseguiu mudar de chave
            raise RuntimeError("Todas as chaves da API falharam ou foram esgotadas.") from e
    
    # Outros erros (conexão, etc.) são levantados
    except Exception as e:
        raise
# *******************************************************************
# LÓGICA DO CHATBOT (NOVO CONTEXTO: Professor do Curso)
# *******************************************************************
active_chats = {} # Armazena as sessões de chat contínuo por session_id

def limpar_nome_nivel(nivel):
    # Converte para minúsculas
    limpo = nivel.lower() 
    limpo = limpo.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    
    return limpo

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
            instrucoes_curso = get_curso_system_instruction(curso_acesso)
            
            # ATENÇÃO: Usa o cliente ATIVO em API_STATE
            chat_session = API_STATE['client'].chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(system_instruction=instrucoes_curso)
            )
            active_chats[chat_key] = chat_session
        except Exception as e:
            app.logger.error(f"Erro ao criar chat Gemini para {chat_key}: {e}", exc_info=True)
            raise
            
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
            curso_acesso = data.get('curso_acesso')
            nome = session.get('nome', 'Aluno') 
            
            if not mensagem_usuario or not curso_acesso:
                emit('erro', {"erro": "Mensagem ou contexto do curso ausente."})
                return

            user_chat = get_user_chat(curso_acesso)

            if user_chat is None:
                emit('erro', {"erro": "Sessão de chat não pôde ser estabelecida."})
                return
                
            # 1. NOVO PASSO: Chama a função de envio com rotação
            resposta_gemini = send_message_with_rotation(user_chat, mensagem_usuario)
            
            # 2. Extrai o texto da resposta
            resposta_texto = resposta_gemini.text
            
            # ... (Emite a resposta) ...
            emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto})
            
        except Exception as e:
            app.logger.error(f"Erro ao processar 'enviar_mensagem': {e}", exc_info=True)
            # Mensagem de erro mais amigável para o usuário:
            if "Todas as chaves" in str(e):
                    emit('erro', {"erro": "O sistema de IA está indisponível. Tente novamente mais tarde."})
            else:
                    emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})

@socketio.on('disconnect')
def handle_disconnect():
    app.logger.info(f"Cliente desconectado: {request.sid}")


# *******************************************************************
# FUNÇÕES E ROTAS EXISTENTES DO SEU APP.PY (NÃO ALTERADAS)
# *******************************************************************

def carregar_conteudo_json(curso, ordem, nivel):
    """
    Carrega o conteúdo do módulo a partir de um arquivo JSON, incluindo o nível.
    Caminho assumido: ../static/json_content/{curso}/{nivel}/modulo_{ordem}.json
    """
    try:
        # Pega o diretório base do projeto (onde app.py está)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        curso_limpo = curso.lower().replace('ê', 'e').replace('ã', 'a')
        nivel_limpo = nivel.lower().replace('á', 'a').replace('é', 'e')
        
        # Constrói o caminho completo do arquivo
        caminho_arquivo = os.path.join(base_dir, 
                                       '..', 
                                       'static', 
                                       'json_content', 
                                       curso_limpo,
                                       nivel_limpo,
                                       f'modulo_{ordem}.json')
        
        # DEBUG (é bom manter isso por enquanto):
        print(f"\n[DEBUG JSON] Tentando abrir: {caminho_arquivo}\n")
            
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            conteudo = json.load(f)
            
            # -------------------------------------------------------------------
            # ✅ NOVO CÓDIGO: EXTRAÇÃO E CRIAÇÃO DA URL DE INCORPORAÇÃO (EMBED)
            # -------------------------------------------------------------------
            youtube_url = conteudo.get('youtube_url')
            
            if youtube_url:
                # Usa regex para encontrar o ID do vídeo, seja em youtu.be/ID ou watch?v=ID
                # O (?:...) cria um grupo de não-captura para simplificar
                video_id_match = re.search(r'(?:youtu\.be/|v=)([\w-]+)', youtube_url)
                
                if video_id_match:
                    video_id = video_id_match.group(1)
                    # Cria a URL de incorporação (embed) que o iframe precisa
                    # ?rel=0 evita que vídeos relacionados de outros canais sejam exibidos ao final.
                    conteudo['embed_url'] = f'https://www.youtube.com/embed/{video_id}?rel=0'
                else:
                    # Se não conseguir extrair o ID
                    conteudo['embed_url'] = None
                    print(f"[ERRO YOUTUBE] URL do YouTube inválida no JSON: {youtube_url}")
            else:
                # Se a chave youtube_url não estiver no JSON
                conteudo['embed_url'] = None
            # -------------------------------------------------------------------

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
        cur.execute("SELECT aluno_id, nome, senha_hash, curso_acesso, nivel_curso FROM aluno WHERE email = %s", [email])
        aluno = cur.fetchone()
        cur.close()

        if aluno:
            senha_hash_input = hashlib.sha256(senha.encode()).hexdigest()
            
            if senha_hash_input == aluno['senha_hash']:
                session['loggedin'] = True
                session['aluno_id'] = aluno['aluno_id']
                session['nome'] = aluno['nome']
                session['curso_acesso'] = aluno['curso_acesso']
                session['nivel_curso'] = aluno['nivel_curso']
                
                flash('Login realizado com sucesso!', 'success')
                return redirect(url_for('curso_home'))
            else:
                # Senha incorreta
                flash('Email ou senha incorretos.', 'danger')
                return redirect(url_for('login'))
        else:
            # Usuário não encontrado
            flash('Email ou senha incorretos.', 'danger')
            return redirect(url_for('login'))
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

        cur.execute("""
            INSERT INTO aluno (nome, email, senha_hash, curso_acesso, nivel_curso) 
            VALUES (%s, %s, %s, %s, %s)
        """, (nome, email, senha_hash, 'Inglês', 'Básico'))
        
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
    nivel_atual = session.get('nivel_curso')
    
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT modulo_id, nome, ordem FROM modulo WHERE curso_acesso = %s AND nivel = %s ORDER BY ordem ASC", 
                [curso_acesso, nivel_atual])
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
                            nivel=nivel_atual,
                            modulos=modulos_com_progresso,
                            progresso_curso=progresso_curso_porcentagem)

@app.route('/curso/<string:curso>/modulo/<int:ordem>', methods=['GET'])
@login_required
def modulo_page(curso, ordem):
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']
    nivel_atual = session.get('nivel_curso')

    print(f"\n[DEBUG 1] ACESSANDO MODULO PAGE: {curso_acesso}, Nivel: {nivel_atual}, Ordem: {ordem}")
    
    curso_limpo = curso.lower().replace('ê', 'e').replace('ã', 'a')
    curso_session_limpo = curso_acesso.lower().replace('ê', 'e').replace('ã', 'a')

    if curso_limpo != curso_session_limpo:
        return "Acesso negado ao curso.", 403

    cur = mysql.connection.cursor()
    
    # -----------------------------------------------------
    # Lógica de Validação de Acesso (Sequencial e Nível)
    # -----------------------------------------------------

    if ordem > 1:
        # Lógica de validação do módulo anterior (Ordem > 1)
        # O código está OK neste bloco
        modulo_anterior_ordem = ordem - 1
        
        cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND nivel = %s AND ordem = %s", 
                     [curso_acesso, nivel_atual, modulo_anterior_ordem])
        modulo_anterior = cur.fetchone()
        
        if modulo_anterior:
            cur.execute("SELECT status_modulo FROM desempenho_modulo WHERE aluno_id = %s AND modulo_id = %s AND nivel_modulo = %s", 
                          [aluno_id, modulo_anterior['modulo_id'], nivel_atual])
            progresso_anterior = cur.fetchone()
            
            if not progresso_anterior or progresso_anterior['status_modulo'] != 'Concluído':
                print("[DEBUG 2] BLOQUEADO: Módulo anterior não concluído.")
                flash("Você precisa concluir o módulo anterior para acessar este.", 'warning')
                cur.close() 
                return redirect(url_for('curso_home'))
        else:
            print("[DEBUG 3] ERRO: Módulo anterior não encontrado no banco.")
            cur.close()
            return "Módulo anterior não encontrado.", 404

    elif ordem == 1 and nivel_atual != 'Básico':
        # Lógica de validação do nível anterior (Módulo 1 de um Nível novo)
        
        # Presume-se que NIVEIS_ORDEM é um dicionário global
        NIVEIS_ANTERIORES = {'Intermediário': 'Básico', 'Avançado': 'Intermediário'} # Simplificando para o caso
        nivel_anterior = NIVEIS_ANTERIORES.get(nivel_atual)
        
        if nivel_anterior:
            # 2a. Encontrar o último módulo do nível anterior
            cur.execute("SELECT modulo_id, ordem FROM modulo WHERE curso_acesso = %s AND nivel = %s ORDER BY ordem DESC LIMIT 1", 
                         [curso_acesso, nivel_anterior])
            ultimo_modulo_anterior = cur.fetchone()
            
            # 🚨 CORREÇÃO PRINCIPAL: Verificação de 'None' deve redirecionar
            if not ultimo_modulo_anterior:
                 # 🔴 DEBUG 5: Redirecionamento por Último Módulo Anterior não encontrado (Erro de configuração)
                print("[DEBUG 5] ERRO: Último Módulo do Nível Anterior não encontrado no banco.")
                cur.close()
                flash("Erro de configuração de nível. Módulo Final não encontrado.", 'danger')
                return redirect(url_for('curso_home'))
            
            ultimo_modulo_id = ultimo_modulo_anterior['modulo_id']
            
            # 2b. Verificar se o último módulo do nível anterior está Concluído
            cur.execute("SELECT status_modulo FROM desempenho_modulo WHERE aluno_id = %s AND modulo_id = %s", 
                         [aluno_id, ultimo_modulo_id])
            progresso_nivel_anterior = cur.fetchone()
            
            if not progresso_nivel_anterior or progresso_nivel_anterior['status_modulo'] != 'Concluído':
                print(f"[DEBUG 4] BLOQUEADO: Nível {nivel_anterior} não concluído. Módulo ID: {ultimo_modulo_anterior['modulo_id']}")
                flash(f"Você precisa concluir o Nível {nivel_anterior} para iniciar o Nível {nivel_atual}.", 'warning')
                cur.close()
                return redirect(url_for('curso_home'))
        # Se 'nivel_anterior' não for encontrado, o código simplesmente continua, o que está correto para evitar falha no Básico.
        
    # -----------------------------------------------------
    # Carregamento de Conteúdo Final (Se todas as validações passarem)
    # -----------------------------------------------------
    
    # 🟢 DEBUG 6: Chamando a função de carregamento
    print("[DEBUG 6] INICIANDO CARREGAMENTO DO JSON...")
    
    # 🚨 LEMBRETE: Sua função carregar_conteudo_json precisa da correção do acento (nivel.lower().replace('á', 'a'))
    conteudo = carregar_conteudo_json(curso_limpo, ordem, nivel_atual) 
    
    if not conteudo:
        cur.close()
        return "Conteúdo do módulo não encontrado ou inválido.", 404

    cur.close() 

    # -----------------------------------------------------
    # Renderização
    # -----------------------------------------------------

    return render_template('modulo_page.html', 
                            curso=curso_limpo, 
                            ordem=ordem, 
                            nivel=nivel_atual, 
                            modulo=conteudo)

@app.route('/curso/<string:curso>/modulo/<int:ordem>', methods=['POST'])
@login_required
def enviar_atividade(curso, ordem):
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']
    nivel_atual = session.get('nivel_curso')
    
    # 🔴 VERIFICAÇÃO DE NÍVEL:
    if not nivel_atual:
        flash("Erro: O seu nível de curso não foi encontrado. Por favor, refaça o login.", 'danger')
        return redirect(url_for('login'))
        
    NOTA_MINIMA_ACERTOS = 7 
    
    curso_limpo = curso.lower().replace('ê', 'e').replace('ã', 'a')
    
    # 🔴 MUDANÇA: Passa o nível para a função JSON
    conteudo = carregar_conteudo_json(curso_limpo, ordem, nivel_atual) 
    if not conteudo:
        return "Erro: Conteúdo do módulo indisponível.", 404

    # --- Lógica de Avaliação (Inalterada) ---
    respostas_corretas = conteudo.get('respostas_corretas', {})
    respostas_aluno = request.form
    total_perguntas = len(respostas_corretas)
    acertos = 0
    # ... (Seu loop de correção) ...
    for id_pergunta, resposta_correta in respostas_corretas.items():
        resposta_aluno = respostas_aluno.get(f'pergunta_{id_pergunta}')
        if resposta_aluno and resposta_aluno.upper() == resposta_correta.upper():
            acertos += 1
            
    erros = total_perguntas - acertos
    nota_final = (acertos / total_perguntas) * 100 if total_perguntas > 0 else 0
    aprovado = acertos >= NOTA_MINIMA_ACERTOS
    novo_status = 'Concluído' if aprovado else 'Em Andamento' 
    
    cur = mysql.connection.cursor()

    # 🔴 MUDANÇA: Buscar modulo_id com filtro de nível
    cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND nivel = %s AND ordem = %s", 
                [curso_acesso, nivel_atual, ordem])
    modulo_info = cur.fetchone()
    
    if not modulo_info:
        cur.close()
        return "Módulo não encontrado no banco de dados para o seu nível atual.", 404

    modulo_id = modulo_info['modulo_id']
    
    # 🔴 MUDANÇA: Inserir 'nivel_modulo' no desempenho
    sql_desempenho = """
        INSERT INTO desempenho_modulo (aluno_id, modulo_id, nivel_modulo, status_modulo, nota_final, data_conclusao)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE 
            status_modulo = VALUES(status_modulo), 
            nota_final = VALUES(nota_final),
            data_conclusao = NOW()
    """
    cur.execute(sql_desempenho, (aluno_id, modulo_id, nivel_atual, novo_status, nota_final)) # 🔴 NOVO: nivel_atual aqui

    
    # -----------------------------------------------------
    # 🔴 LÓGICA DE AVANÇO DE NÍVEL OU DESBLOQUEIO SEQUENCIAL
    # -----------------------------------------------------
    should_redirect = False # Flag para forçar o redirecionamento
    
    if aprovado:
        proxima_ordem = ordem + 1
        
        # 1. Tenta encontrar o próximo módulo DENTRO DO NÍVEL ATUAL
        cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND nivel = %s AND ordem = %s", 
                    [curso_acesso, nivel_atual, proxima_ordem])
        proximo_modulo_mesmo_nivel = cur.fetchone()

        if proximo_modulo_mesmo_nivel:
            # Desbloqueia o próximo módulo do MESMO NÍVEL
            proximo_modulo_id = proximo_modulo_mesmo_nivel['modulo_id']
            
            # 🔴 MUDANÇA: Inserir o nivel_modulo ao desbloquear
            sql_desbloqueio = """
                INSERT INTO desempenho_modulo (aluno_id, modulo_id, status_modulo, nivel_modulo)
                VALUES (%s, %s, 'Em Andamento', %s)
                ON DUPLICATE KEY UPDATE aluno_id = aluno_id
            """
            cur.execute(sql_desbloqueio, (aluno_id, proximo_modulo_id, nivel_atual))
            
        else:
            # 2. Não há próximo módulo no nível. Tenta avançar para o PRÓXIMO NÍVEL.
            proximo_nivel = NIVEIS_ORDEM.get(nivel_atual)
            
            if proximo_nivel == 'Concluído':
                # FIM DO CURSO
                flash(f'Parabéns! Você concluiu o curso de {curso_acesso}!', 'success')
            
            elif proximo_nivel:
                # TRANSIÇÃO DE NÍVEL
                
                # a. Atualiza o banco de dados do aluno
                cur.execute("UPDATE aluno SET nivel_curso = %s WHERE aluno_id = %s", 
                            [proximo_nivel, aluno_id])
                
                # b. Desbloqueia o primeiro módulo (ordem 1) do NOVO NÍVEL
                cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND nivel = %s AND ordem = 1", 
                            [curso_acesso, proximo_nivel])
                primeiro_modulo_proximo_nivel = cur.fetchone()
                
                if primeiro_modulo_proximo_nivel:
                    primeiro_modulo_id = primeiro_modulo_proximo_nivel['modulo_id']
                    
                    # 🔴 MUDANÇA: Desbloqueio usando o NOVO NÍVEL
                    sql_desbloqueio_novo_nivel = """
                        INSERT INTO desempenho_modulo (aluno_id, modulo_id, status_modulo, nivel_modulo)
                        VALUES (%s, %s, 'Em Andamento', %s)
                        ON DUPLICATE KEY UPDATE aluno_id = aluno_id
                    """
                    cur.execute(sql_desbloqueio_novo_nivel, (aluno_id, primeiro_modulo_id, proximo_nivel))
                
                # c. Atualiza a sessão
                session['nivel_curso'] = proximo_nivel
                
                # 🏆 MUDANÇA AQUI: Usa a categoria 'level_up' para o pop-up
                flash(f'Parabéns! Você concluiu o nível {nivel_atual} e avançou para o nível {proximo_nivel}!', 'level_up')
                should_redirect = True
            
    mysql.connection.commit()
    cur.close()

    # -----------------------------------------------------
    # 🔴 NOVO FLUXO DE RETORNO
    # -----------------------------------------------------
    if should_redirect:
        # Se houve transição de nível, redireciona para a home (onde o pop-up será exibido)
        return redirect(url_for('curso_home'))
    
    # Se não houve transição (aprovou, reprovou ou atingiu o final sem mais níveis), retorna o popup
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