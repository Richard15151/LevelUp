from flask import Flask, render_template, request, redirect, url_for, session
from flask_mysqldb import MySQL
import hashlib
import json
import os

# Inicialização do App Flask
app = Flask(__name__, 
            template_folder='../templates', # Diz ao Flask onde encontrar os arquivos Jinja
            static_folder='../static')      # Diz ao Flask onde encontrar os arquivos estáticos

# CONFIGURAÇÃO DE SEGURANÇA (Obrigatório para usar a session)
app.secret_key = 'levelup' # Mude isso! É usado para proteger as sessões.

# CONFIGURAÇÃO DO BANCO DE DADOS (MySQL)
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'         # Mude para seu usuário MySQL
app.config['MYSQL_PASSWORD'] = 'rdbanco' # Mude para sua senha MySQL
app.config['MYSQL_DB'] = 'levelup'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor' # Retorna resultados como dicionários

mysql = MySQL(app)

def carregar_conteudo_json(curso, ordem):
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
        
        # *** LINHA DE DEBUG: Adicione isso ***
        print(f"\n[DEBUG JSON] Tentando abrir: {caminho_arquivo}\n")
        # ***********************************
            
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
# RF01: Acessar os planos (Landing Page)
# *******************************************************************
@app.route('/')
def index():
    # Renderiza a landing page com as opções de cursos/planos
    return render_template('index.html')

# *******************************************************************
# RF04: Fazer Login
# *******************************************************************
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        
        # 1. Busca o aluno no DB
        cur = mysql.connection.cursor()
        cur.execute("SELECT aluno_id, nome, senha_hash, curso_acesso FROM aluno WHERE email = %s", [email])
        aluno = cur.fetchone() # Fetches a single record (dict)
        cur.close()

        if aluno:
            # 2. Verifica a senha
            senha_hash_input = hashlib.sha256(senha.encode()).hexdigest()
            
            if senha_hash_input == aluno['senha_hash']:
                # Login bem-sucedido
                session['loggedin'] = True
                session['aluno_id'] = aluno['aluno_id']
                session['nome'] = aluno['nome']
                session['curso_acesso'] = aluno['curso_acesso']
                
                return redirect(url_for('curso_home')) # Redireciona para a Home do Curso
            else:
                # Senha incorreta
                return render_template('login.html', erro='Email ou senha incorretos.')
        else:
            # Usuário não encontrado
            return render_template('login.html', erro='Email ou senha incorretos.')
    
    # Se GET, apenas exibe o formulário de login
    return render_template('login.html')

# *******************************************************************
# RF03: Criar Cadastro (Após a escolha do plano/curso simulado)
# *******************************************************************
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']
        curso_acesso = request.form['curso_acesso'] # Campo escondido ou selecionado na tela de planos

        # Verifica se o email já existe
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM aluno WHERE email = %s", [email])
        if cur.fetchone():
            cur.close()
            return render_template('cadastro.html', erro='Este email já está cadastrado.')

        # Criptografa a senha antes de salvar
        senha_hash = hashlib.sha256(senha.encode()).hexdigest()

        # Insere o novo aluno no DB
        cur.execute("INSERT INTO aluno (nome, email, senha_hash, curso_acesso) VALUES (%s, %s, %s, %s)", 
                    (nome, email, senha_hash, curso_acesso))
        
        mysql.connection.commit()
        cur.close()
        
        # Redireciona para o login após o cadastro
        return redirect(url_for('login'))

    # Se GET, exibe o formulário de cadastro
    return render_template('cadastro.html')

# Se precisar de uma rota de logout (RF05)
@app.route('/logout')
def logout():
    session.clear() # Limpa todos os dados da sessão
    return redirect(url_for('index'))

# *******************************************************************
# RF06, RF08: Acessar seu curso / Ver módulos (Home do Curso)
# *******************************************************************
@app.route('/curso')
@login_required
def curso_home():
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']
    
    cur = mysql.connection.cursor()
    
    # 1. Busca a lista de módulos para o curso do aluno, ordenados.
    cur.execute("SELECT modulo_id, nome, ordem FROM modulo WHERE curso_acesso = %s ORDER BY ordem ASC", [curso_acesso])
    modulos = cur.fetchall()
    
    # 2. Busca o desempenho do aluno (status e nota) em todos os módulos.
    cur.execute("SELECT modulo_id, status_modulo, nota_final FROM desempenho_modulo WHERE aluno_id = %s", [aluno_id])
    desempenho = cur.fetchall()
    
    cur.close()

    # 3. Combina Módulos com Desempenho
    # Converte desempenho para um dicionário para busca rápida: {modulo_id: progresso_dict}
    desempenho_map = {item['modulo_id']: item for item in desempenho}

    modulos_com_progresso = []
    modulos_concluidos = 0  # <--- INÍCIO: Contador de módulos concluídos
    total_modulos = len(modulos) # <--- Total de módulos

    # Prepara os dados para o Jinja
    for modulo in modulos:
        modulo_progresso = desempenho_map.get(modulo['modulo_id'], None)
        
        # Pega o status do DB ou assume 'Não Iniciado'
        status = modulo_progresso['status_modulo'] if modulo_progresso else 'Não Iniciado'
        
        # <--- MEIO: Incrementa se o status for 'Concluído'
        if status == 'Concluído':
            modulos_concluidos += 1
        
        # Adiciona o status e outros dados ao objeto do módulo
        modulos_com_progresso.append({
            'modulo_id': modulo['modulo_id'],
            'nome': modulo['nome'],
            'ordem': modulo['ordem'],
            'status': status,
            'nota_final': modulo_progresso.get('nota_final') if modulo_progresso else None
        })

    # Renderiza a página principal do curso
    return render_template('curso_home.html', 
                           curso=curso_acesso,
                           modulos=modulos_com_progresso)

# *******************************************************************
# RF09, RF10, RF11: Acessar módulo / Assistir vídeo / Ver atividades
# *******************************************************************
@app.route('/curso/<string:curso>/modulo/<int:ordem>', methods=['GET'])
@login_required
def modulo_page(curso, ordem):
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']
    
    curso_limpo = curso.lower().replace('ê', 'e').replace('ã', 'a')
    curso_session_limpo = curso_acesso.lower().replace('ê', 'e').replace('ã', 'a')

    # 1. Valida se o curso na URL é o curso do aluno
    if curso_limpo != curso_session_limpo: # <--- COMPARAÇÃO CORRETA AGORA
        return "Acesso negado ao curso.", 403

    # 2. Lógica de Desbloqueio (CRUCIAL):
    # O módulo 1 está sempre desbloqueado. Para N > 1, Módulo (N-1) deve estar 'Concluído'.
    if ordem > 1:
        modulo_anterior_ordem = ordem - 1
        
        cur = mysql.connection.cursor()
        # Busca o ID do módulo anterior
        cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND ordem = %s", 
                    [curso_acesso, modulo_anterior_ordem])
        modulo_anterior = cur.fetchone()
        
        # Se encontrou o módulo anterior, verifica seu desempenho
        if modulo_anterior:
            cur.execute("SELECT status_modulo FROM desempenho_modulo WHERE aluno_id = %s AND modulo_id = %s", 
                        [aluno_id, modulo_anterior['modulo_id']])
            progresso_anterior = cur.fetchone()
            cur.close()
            
            # Bloqueia se o módulo anterior NÃO estiver 'Concluído'
            if not progresso_anterior or progresso_anterior['status_modulo'] != 'Concluído':
                return redirect(url_for('curso_home')) # Redireciona para home, pois está bloqueado
        else:
            cur.close()
            return "Módulo anterior não encontrado.", 404

    # 3. Carrega o Conteúdo (Vídeo/Atividades) do JSON
    conteudo = carregar_conteudo_json(curso_limpo, ordem)
    if not conteudo:
        return "Conteúdo do módulo não encontrado ou inválido.", 404
    
    # Renderiza a página do módulo
    return render_template('modulo_page.html', 
                           curso=curso_limpo, 
                           ordem=ordem, 
                           conteudo=conteudo)

# *******************************************************************
# RF12, RF13: Responder atividades / Ver desempenho
# *******************************************************************
@app.route('/curso/<string:curso>/modulo/<int:ordem>', methods=['POST'])
@login_required
def enviar_atividade(curso, ordem):
    aluno_id = session['aluno_id']
    curso_acesso = session['curso_acesso']

    curso_limpo = curso.lower().replace('ê', 'e').replace('ã', 'a')
    
    # 1. Carrega o JSON para obter as respostas CORRETAS
    conteudo = carregar_conteudo_json(curso_limpo, ordem)
    if not conteudo:
        return "Erro: Conteúdo do módulo indisponível.", 404

    respostas_corretas = conteudo.get('respostas_corretas', {}) # Obtém o mapa de respostas corretas do JSON
    respostas_aluno = request.form # Dados enviados pelo formulário do aluno
    
    total_perguntas = len(respostas_corretas)
    acertos = 0
    
    # 2. Verifica as respostas
    for id_pergunta, resposta_correta in respostas_corretas.items():
        resposta_aluno = respostas_aluno.get(f'pergunta_{id_pergunta}')
        if resposta_aluno and resposta_aluno.upper() == resposta_correta.upper():
            acertos += 1
            
    erros = total_perguntas - acertos
    nota_final = (acertos / total_perguntas) * 100 if total_perguntas > 0 else 0
    
    # 3. Busca o modulo_id no DB
    cur = mysql.connection.cursor()
    cur.execute("SELECT modulo_id FROM modulo WHERE curso_acesso = %s AND ordem = %s", [curso_acesso, ordem])
    modulo = cur.fetchone()
    
    if not modulo:
        cur.close()
        return "Módulo não encontrado no banco de dados.", 404

    modulo_id = modulo['modulo_id']

    # 4. Salva/Atualiza o Desempenho no DB (RF13)
    # Usa INSERT...ON DUPLICATE KEY UPDATE para ser idempotente (evita duplicidade)
    sql = """
        INSERT INTO desempenho_modulo (aluno_id, modulo_id, status_modulo, nota_final, data_conclusao)
        VALUES (%s, %s, 'Concluído', %s, NOW())
        ON DUPLICATE KEY UPDATE 
            status_modulo = 'Concluído', 
            nota_final = %s,
            data_conclusao = NOW()
    """
    cur.execute(sql, (aluno_id, modulo_id, nota_final, nota_final))
    mysql.connection.commit()
    cur.close()

    # 5. Retorna o pop-up de desempenho (RF13)
    # Você pode renderizar um template ou redirecionar com parâmetros de query/flash
    return render_template('desempenho_popup.html', 
                           acertos=acertos, 
                           erros=erros, 
                           nota_final=nota_final)

# *******************************************************************
# RF14: Tela de Perfil do Aluno
# *******************************************************************
@app.route('/perfil')
@login_required
def perfil():
    aluno_id = session['aluno_id']
    
    # Busca informações do DB (nome, email, curso) para garantir que são atuais
    cur = mysql.connection.cursor()
    cur.execute("SELECT nome, email, curso_acesso FROM aluno WHERE aluno_id = %s", [aluno_id])
    dados_aluno = cur.fetchone()
    cur.close()
    
    if not dados_aluno:
        # Se por algum motivo não encontrar o aluno, encerra a sessão e redireciona
        session.clear()
        return redirect(url_for('login'))

    # Renderiza a página de perfil
    return render_template('perfil.html', 
                           nome=dados_aluno['nome'],
                           email=dados_aluno['email'],
                           curso=dados_aluno['curso_acesso'])


@app.route('/pagamento/<string:curso_acesso>')
def pagamento_ficticio(curso_acesso):
    # Garante que o curso_acesso é válido antes de renderizar
    if curso_acesso not in ['Inglês', 'Espanhol']:
        return redirect(url_for('index'))
    return render_template('pagamento.html', curso_acesso=curso_acesso)
                           
if __name__ == '__main__':
    # Utilize `0.0.0.0` para que o servidor seja acessível externamente 
    # (em um ambiente de desenvolvimento ou docker)
    app.run(debug=True, host='0.0.0.0', port=5000)