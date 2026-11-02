# SONARA Backend

API inicial da SONARA: cadastro e login de usuários, mais autenticação separada para o proprietário/desenvolvedor.

## Requisitos
- Python 3.11+
- SQLite para desenvolvimento local ou PostgreSQL para produção.

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

Edite `.env`. Configure `JWT_SECRET_KEY` com um segredo aleatório longo e exclusivo, `DEVELOPER_EMAIL` e `DEVELOPER_PASSWORD` com suas credenciais privadas. A senha administrativa deve ter pelo menos 14 caracteres. Não use valores de exemplo e nunca envie o arquivo `.env` ao GitHub.

Inicie:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Documentação: http://127.0.0.1:8000/docs  
Saúde: http://127.0.0.1:8000/health

O banco `sonara.db` é criado em `backend/`. Para PostgreSQL, configure `DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/banco`.

## Endpoints
### Usuário
- `POST /api/v1/auth/register` — cadastro público, sempre cria papel `user`.
- `POST /api/v1/auth/login` — login de usuário.
- `GET /api/v1/auth/me` — sessão do usuário autenticado.

### Desenvolvedor
- `POST /api/v1/developer/login` — login exclusivo da conta provisionada pelo ambiente.
- `GET /api/v1/developer/me` — sessão administrativa.

As senhas são armazenadas com Argon2. Tokens JWT assinados expiram conforme `ACCESS_TOKEN_EXPIRE_MINUTES`. O papel é validado também contra o registro atual do banco. Não existe cadastro público nem promoção de conta para desenvolvedor.

## Escopo desta entrega
Esta é a fundação funcional de identidade e sessão. Catálogo real, player multitrack, arquivos de áudio, playlists persistentes, downloads protegidos, pagamentos, recuperação de senha, rate limiting, auditoria e painéis administrativos operacionais ainda precisam de módulos próprios. Para produção, adicione migrações versionadas, HTTPS, backups, gestão de segredos, monitoramento e controles contra tentativas automatizadas.
