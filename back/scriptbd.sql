CREATE DATABASE IF NOT EXISTS levelup CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE levelup;

CREATE TABLE aluno (
    aluno_id INT PRIMARY KEY AUTO_INCREMENT,
    nome VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    senha_hash VARCHAR(255) NOT NULL,
    curso_acesso ENUM('Inglês', 'Espanhol') NOT NULL
);

CREATE TABLE modulo (
    modulo_id INT PRIMARY KEY AUTO_INCREMENT,
    nome VARCHAR(100) NOT NULL,
    ordem INT NOT NULL,
    curso_acesso ENUM('Inglês', 'Espanhol') NOT NULL,
    UNIQUE KEY uk_curso_ordem (curso_acesso, ordem) 
);

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

INSERT INTO modulo (nome, ordem, curso_acesso) VALUES 
('Inglês - Módulo 1: Fundamentos', 1, 'Inglês'),
('Inglês - Módulo 2: Presente Simples', 2, 'Inglês'),
('Inglês - Módulo 3: Passado e Futuro', 3, 'Inglês');

INSERT INTO modulo (nome, ordem, curso_acesso) VALUES 
('Espanhol - Módulo 1: Primeiras Palavras', 1, 'Espanhol'),
('Espanhol - Módulo 2: Verbos Regulares', 2, 'Espanhol'),
('Espanhol - Módulo 3: Cultura e Conversação', 3, 'Espanhol');
