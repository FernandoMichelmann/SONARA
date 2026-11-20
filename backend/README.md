# SONARA Backend

API da SONARA com cadastro e autenticação, painel administrativo, upload de tracks, registro manual de receitas e recuperação segura de senha por e-mail.

## Requisitos
- Python 3.11+
- SQLite para desenvolvimento local ou PostgreSQL configurado por `DATABASE_URL`.

## Instalação local (macOS)

Na raiz do repositório:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edite `.env`: defina `JWT_SECRET_KEY` com um segredo aleatório exclusivo, `DEVELOPER_EMAIL` e `DEVELOPER_PASSWORD` com suas credenciais privadas. A senha administrativa deve ter pelo menos 14 caracteres. Nunca envie o arquivo `.env` ao GitHub.

## Configurar envio de e-mails pelo Gmail

A recuperação de senha envia o link diretamente pelo servidor SONARA usando SMTP do Gmail. A conexão do Gmail ao ChatGPT não fornece credenciais SMTP para a aplicação.

1. Entre na conta `sonaramultitracks@gmail.com`.
2. Ative a verificação em duas etapas na Conta Google.
3. Gere uma **Senha de app** nas configurações de segurança da Conta Google (se a opção estiver disponível).
4. No arquivo local `backend/.env`, mantenha `SMTP_USERNAME` e `SMTP_FROM_EMAIL` como `sonaramultitracks@gmail.com` e substitua `SMTP_PASSWORD` pela senha de app gerada. Não use a senha normal da conta.
5. Mantenha `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true` e `SMTP_USE_SSL=false`.
6. Ajuste `FRONTEND_BASE_URL` para a URL pública do site quando a SONARA estiver publicada. Localmente, use `http://127.0.0.1:5500`.
7. Reinicie a API para carregar as variáveis.

**Segurança:** o arquivo `.env` contém segredos e não deve ser enviado ao GitHub, compartilhado ou incluído em capturas de tela. O repositório contém apenas `.env.example`, sem a senha real.

## Iniciar a API

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Documentação: http://127.0.0.1:8000/docs  
Saúde: http://127.0.0.1:8000/health  
Painel: abra `developer.html` pelo Live Server. A interface local usa `http://127.0.0.1:8000/api/v1`.

## Endpoints principais

### Usuários
- `POST /api/v1/auth/register` — cadastro público com papel `user`.
- `POST /api/v1/auth/login` e `GET /api/v1/auth/me`.
- `POST /api/v1/auth/forgot-password` — solicita envio de link de redefinição.
- `POST /api/v1/auth/reset-password` — valida o token e grava a nova senha.
- `GET /api/v1/developer/users` — lista e pesquisa usuários comuns.
- `PATCH /api/v1/developer/users/{id}/status` — ativa/desativa uma conta comum.

### Tracks
- `POST /api/v1/developer/tracks` — upload autenticado de áudio e metadados multipart.
- `GET /api/v1/developer/tracks` — lista administrativa.
- `PATCH /api/v1/developer/tracks/{id}` — atualiza metadados/publicação.
- `GET /api/v1/catalog/tracks` — lista pública somente das tracks publicadas.
- `GET /api/v1/tracks/{id}/audio` — entrega áudio somente quando publicado.

Formatos aceitos: MP3, WAV, FLAC, M4A, OGG e AAC; limite por arquivo de 500 MB. Arquivos são armazenados localmente em `backend/uploads/tracks/`, pasta excluída do Git. Faça backup dela separadamente. Em produção, migre os arquivos para armazenamento de objetos privado com URLs assinadas, limites de upload no proxy e validação adicional de conteúdo.

### Receitas
- `GET /api/v1/developer/revenues` — histórico.
- `POST /api/v1/developer/revenues` — registra manualmente um lançamento.
- `GET /api/v1/developer/revenue-summary` — totais recebidos e pendentes.

**Importante:** receitas são lançamentos manuais e não são vendas verificadas por um gateway de pagamento. A integração de cobrança e conciliação ainda não existe.

### Autenticação
- `POST /api/v1/developer/login` e `GET /api/v1/developer/me`.

As senhas são armazenadas com Argon2 e os tokens JWT são validados no servidor. Os links de recuperação expiram em 30 minutos, são de uso único e armazenados como hash. O endpoint retorna uma mensagem genérica para não revelar se um e-mail possui cadastro; há intervalo mínimo entre solicitações.

## Dados e limites atuais
As tabelas novas são criadas com `Base.metadata.create_all` ao iniciar. Ainda não há sistema de migrações versionadas, testes automatizados, auditoria administrativa, integração de pagamentos ou armazenamento de áudio pronto para produção. Faça backup do banco SQLite e da pasta de uploads antes de mudanças importantes.
