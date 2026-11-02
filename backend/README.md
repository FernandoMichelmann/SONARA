# SONARA Backend

API da SONARA com cadastro e autenticação, painel administrativo, upload de tracks e registro manual de receitas.

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

Inicie a API:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Documentação: http://127.0.0.1:8000/docs  
Saúde: http://127.0.0.1:8000/health  
Painel: abra `developer.html` pelo Live Server. A interface usa a API local em `http://127.0.0.1:8000/api/v1`.

## Endpoints principais

### Usuários
- `POST /api/v1/auth/register` — cadastro público com papel `user`.
- `POST /api/v1/auth/login` e `GET /api/v1/auth/me`.
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

As senhas são armazenadas com Argon2 e os tokens JWT são validados no servidor. Não há cadastro público de desenvolvedor.

## Dados e limites atuais
As tabelas novas são criadas com `Base.metadata.create_all` ao iniciar. Ainda não há sistema de migrações versionadas, testes automatizados, auditoria administrativa, integração de pagamentos, recuperação de senha, rate limiting ou armazenamento de áudio pronto para produção. Faça backup do banco SQLite e da pasta de uploads antes de mudanças importantes.
