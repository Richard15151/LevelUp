CREATE DATABASE IF NOT EXISTS levelup CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE levelup;

-- 1. Tabela ALUNO - Adicionado o campo 'nivel_curso'
CREATE TABLE aluno (
    aluno_id INT PRIMARY KEY AUTO_INCREMENT,
    nome VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    senha_hash VARCHAR(255) NOT NULL,
    curso_acesso ENUM('Inglês', 'Espanhol') NOT NULL,
    nivel_curso VARCHAR(50) NOT NULL DEFAULT 'Básico' -- NOVO CAMPO para rastrear o nível atual do aluno
);

-- 2. Tabela MODULO - Adicionado o campo 'nivel' e ajustada a chave única
CREATE TABLE modulo (
    modulo_id INT PRIMARY KEY AUTO_INCREMENT,
    nome VARCHAR(100) NOT NULL,
    ordem INT NOT NULL,
    nivel VARCHAR(50) NOT NULL, -- CAMPO ADICIONADO para identificar o nível do módulo (Básico, Intermediário, etc.)
    curso_acesso ENUM('Inglês', 'Espanhol') NOT NULL,
    -- Chave única agora combina curso, nível e ordem, permitindo "Módulo 1" em vários níveis.
    UNIQUE KEY uk_curso_nivel_ordem (curso_acesso, nivel, ordem) 
);

-- 3. Tabela DESEMPENHO_MODULO - Sem alterações, já estava completa
CREATE TABLE desempenho_modulo (
    desempenho_id INT PRIMARY KEY AUTO_INCREMENT,
    aluno_id INT NOT NULL,
    modulo_id INT NOT NULL,
    status_modulo ENUM('Não Iniciado', 'Em Andamento', 'Concluído') DEFAULT 'Não Iniciado',
    nota_final DECIMAL(5,2),
    data_conclusao DATETIME,

    FOREIGN KEY (aluno_id) REFERENCES aluno(aluno_id),
    FOREIGN KEY (modulo_id) REFERENCES modulo(modulo_id),
    UNIQUE KEY uk_aluno_modulo (aluno_id, modulo_id) 
);

-- 4. INSERTS para MODULO - Atualizados para incluir o campo 'nivel'
-- INGLÊS (Nível Básico)
INSERT INTO modulo (nome, ordem, nivel, curso_acesso) VALUES 
('Inglês - Módulo 1: Fundamentos', 1, 'Básico', 'Inglês'),
('Inglês - Módulo 2: Presente Simples', 2, 'Básico', 'Inglês'),
('Inglês - Módulo 3: Passado e Futuro', 3, 'Básico', 'Inglês');

-- ESPANHOL (Nível Básico)
INSERT INTO modulo (nome, ordem, nivel, curso_acesso) VALUES 
('Espanhol - Módulo 1: Primeiras Palavras', 1, 'Básico', 'Espanhol'),
('Espanhol - Módulo 2: Verbos Regulares', 2, 'Básico', 'Espanhol'),
('Espanhol - Módulo 3: Cultura e Conversação', 3, 'Básico', 'Espanhol');

-- Exemplo de módulos Intermediários para teste:
INSERT INTO modulo (nome, ordem, nivel, curso_acesso) VALUES 
('Inglês - Módulo 4: Phrasal Verbs', 1, 'Intermediário', 'Inglês'),
('Inglês - Módulo 5: Voz Passiva', 2, 'Intermediário', 'Inglês');