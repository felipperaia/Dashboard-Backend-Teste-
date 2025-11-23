# Silo Monitor Backend

Sistema backend moderno para monitoramento inteligente de silos de grãos via ThingSpeak, utilizando FastAPI, MongoDB, múltiplos canais de notificação (email, SMS, Telegram, WebSocket), chatbot LLM e autenticação MFA.

## ✨ Funcionalidades

- ♨️ Monitoramento em tempo real de temperatura, umidade e gases
- 🤖 Chatbot LLM via OpenRouter/DeepSeek para suporte
- 📱 MFA com TOTP (compatível com Microsoft Authenticator)
- 📨 Notificações multicanal:
  - Email via SendGrid
  - SMS via Twilio
  - Mensagens Telegram
  - Web Push Notifications
  - WebSocket para alertas em tempo real
- 📊 Relatórios avançados com métricas estatísticas
- ⚡ API REST + WebSocket para integração front-end
- 🔄 Integração automática com ThingSpeak

***

## 🚀 Tecnologias Utilizadas

| Tecnologia        | Função                                    |
|-------------------|--------------------------------------------|
| FastAPI 0.95.2+   | Framework web assíncrono  |
| MongoDB + Motor   | Banco de dados NoSQL assíncrono |
| ThingSpeak API    | Integração IoT para leitura de sensores |
| SendGrid          | Envio de emails |
| Twilio            | Envio de SMS |
| Telegram Bot API  | Mensagens via Telegram |
| WebPush          | Notificações web push |
| WebSocket        | Alertas em tempo real |
| OpenRouter API    | Chatbot LLM/IA |
| PyOTP            | MFA com TOTP |
| JWT + OAuth2     | Autenticação e autorização |
| APScheduler      | Agendamento de tarefas |
| Pydantic         | Validação e serialização |

***

## 📦 Estrutura do Projeto

```
.
├── app/                    # Módulo principal
│   ├── main.py            # Entrypoint da API
│   ├── config.py          # Configurações globais
│   ├── db.py              # Conexão MongoDB
│   ├── auth.py            # Autenticação (JWT+MFA)
│   ├── schemas.py         # Modelos Pydantic
│   ├── utils.py           # Utilitários
│   ├── routes/            # Endpoints da API
│   │   ├── alerts.py      # Gestão de alertas
│   │   ├── auth.py        # Login/MFA
│   │   ├── silos.py       # CRUD de silos
│   │   ├── readings.py    # Leituras sensores
│   │   └── ...           
│   ├── services/          # Lógica de negócio
│   │   ├── notification.py    # Multi-canal
│   │   └── thing_speak.py     # Integração IoT
│   └── tasks/             # Jobs agendados
│       └── scheduler.py    # Coleta periódica
├── requirements.txt       # Dependências Python
├── runtime.txt           # Versão Python
├── Makefile             # Comandos úteis
└── .env.example         # Template config
```

***

## ⚡️ Como Rodar Localmente

1. **Clone o repositório**
   ```sh
   git clone <nosso repositorio>
   cd <repositorio>
   ```

2. **Configure o ambiente Python**
   ```sh
   python -m venv .venv
   source .venv/bin/activate        # (Linux/Mac)
   .\.venv\Scripts\Activate.ps1     # (Windows)
   ```

3. **Configuração de variáveis (.env)**
   ```ini
   # Banco
   MONGO_URI=mongodb://localhost:27017
   MONGO_DB=silo_db

   # JWT Auth
   JWT_SECRET=seu_secret_aqui
   JWT_ACCESS_EXPIRE_MIN=15
   JWT_REFRESH_EXPIRE_DAYS=7

   # SendGrid SMTP
   SMTP_HOST=smtp.sendgrid.net
   SMTP_PORT=587
   SMTP_USER=apikey
   SMTP_PASS=sua_sendgrid_api_key
   SMTP_FROM=no-reply@seu-dominio.com

   # Twilio SMS
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM=+1234567890

   # Telegram Bot
   TELEGRAM_BOT_TOKEN=123:ABC...
   TELEGRAM_DEFAULT_CHAT_ID=123456

   # Web Push
   VAPID_PUBLIC_KEY=...
   VAPID_PRIVATE_KEY=...

   # OpenRouter/LLM
   OPENROUTER_API_KEY=sk-...
   OPENROUTER_MODEL=deepseek/deepseek-r1-distill-qwen-32b
   LLM_SYSTEM_PROMPT="Você é um assistente especializado..."

   # ThingSpeak
   THINGSPEAK_API_KEYS={"1":"ABC123"}
   THINGSPEAK_CHANNELS={"1":"3082805"}
   ```

4. **Instale as dependências**
   ```sh
   python -m pip install --upgrade pip wheel setuptools
   pip install -r requirements.txt
   ```

5. **Inicialize banco/admin**
   ```sh
   python scripts/seed_admin.py --username admin --email minh@empresa.com --password Minhasenha123 --secret <INIT_ADMIN_SECRET>
   ```

6. **Inicie em desenvolvimento**
   ```sh
   python -m uvicorn app.main:app --reload --port 8000
   ```

7. **Acesse:**
   - Endpoint saúde: [http://localhost:8000/api/health](http://localhost:8000/api/health)
   - Swagger docs: [http://localhost:8000/docs](http://localhost:8000/docs)

***

## 🔥 Principais Endpoints

### Silos e Leituras

- `GET /api/silos` - Lista silos
- `POST /api/silos` - Cria silo  
- `GET /api/silos/{id}` - Detalhes do silo
- `PUT /api/silos/{id}` - Atualiza silo
- `POST /api/silos/import_thingspeak` - Importa do ThingSpeak
- `GET /api/silos/{id}/readings` - Leituras do silo
- `POST /api/silos/{id}/refresh` - Atualiza dados ThingSpeak

### Notificações e Alertas

- `ws://host/api/alerts/ws` - WebSocket para alertas real-time
- `GET /api/alerts/feed` - Feed de alertas (polling)
- `POST /api/notify/test` - Testa notificações

### Chatbot e MFA

- `POST /api/chat` - Conversa com LLM (contexto do DB)
- `POST /api/mfa/setup` - Setup inicial MFA/TOTP
- `POST /api/mfa/verify` - Valida token MFA

### Relatórios

- `POST /api/reports` - Gera relatório
- `GET /api/reports` - Lista relatórios
- `GET /api/reports/{id}` - Detalhes do relatório

***

## 🛠 Comandos Úteis

- Gerar chaves VAPID para push:
  ```sh
  npx web-push generate-vapid-keys --json
  ```

- Testes automatizados:
  ```sh
  pytest
  ```

- Run na Docker Compose (MongoDB + Backend):
  ```sh
  docker-compose up
  ```

***

## 🌱 Dicas para Contribuição

- Forke o projeto
- Use branches temáticos para novas features/fixes
- Mantenha testes automáticos atualizados
- Dúvidas/críticas: abra uma issue

***

## 🚨 Segurança

- 🔒 Nunca submeta `.env` ao git!
- 🔑 Use variáveis secretas em produção
- 🛡️ MFA habilitado por padrão para contas sensíveis
- 📝 Todas as ações são logadas para auditoria
- 🔐 JWT com refresh tokens e expiração curta
- 🌐 CORS configurado apenas para origens confiáveis
- 🔒 Rate limiting em endpoints sensíveis
- 💾 Backup automático do MongoDB

## 📚 Documentação

- 📖 API Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
- 📝 ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- 💡 Postman Collection: [Link](./postman_collection.json)

## 🤝 Suporte

- 📧 Email: suporte@empresa.com
- 💬 Issues no GitHub
- 🤖 Chatbot no próprio sistema

## Notas rápidas sobre MFA e notificações

- O backend expõe endpoints para MFA (TOTP) em `/api/mfa/setup` e `/api/mfa/verify`.
- Notificações suportadas: WebPush (pywebpush), Telegram (bot), Email (SMTP) e SMS (Twilio). Configure as variáveis correspondentes no `.env`.
- Para WebPush gere chaves VAPID com `npx web-push generate-vapid-keys --json` e cole no `.env`.

---

**Resumo das alterações aplicadas nesta refatoração (Deméter)**

- Adicionados campos de luminosidade nas leituras (`luminosity_alert` e `lux`), com defaults e parsing no cliente ThingSpeak (`app/services/thing_speak.py`).
- Configurações novas em `app/config.py`:
   - `LUMINOSITY_DARK_THRESHOLD` (default: 10 lux)
   - `LUMINOSITY_OPEN_THRESHOLD` (default: 100 lux)
   - `IDENTICAL_READINGS_MIN_SECONDS` (default: 18000 = 5 horas)
- Lógica anti-duplicação: antes de salvar uma leitura, o sistema compara com a última leitura do mesmo `silo_id` e evita gravação se TODOS os campos relevantes forem idênticos e a diferença de tempo for menor que `IDENTICAL_READINGS_MIN_SECONDS`.
- Registro de eventos de silo (`silo_events`) quando há transição de luminosidade que indica abertura para manutenção (dark -> open).
- Geração de alertas crítica se `luminosity_alert == 1` (possível fogo) e alerta de aviso quando silo é aberto.
- Schema atualizado: `app/schemas.py` e `app/models.py` para incluir luminosidade e `SiloEvent`.
- Rota de criação de silo (`app/routes/silos.py`) aceita agora `latitude` e `longitude` opcionais (em vez de `location` genérico).

**Front-end integrado (resumo do que o front-end passou a suportar)**

- Nova aba `Dashboard Simplificado` com cards por métrica (Temperatura, Umidade, CO₂, Gases, Luminosidade) e ícones SVG.
- Formulário de criação de silo atualizado para `device_id`, `latitude` e `longitude` (opcionais) e opção de preencher via geolocalização do navegador.
- Formulário de leitura manual expandido (Temperatura, Umidade, CO₂, MQ2, Lux e Flag de Luminosidade) e restrito à role `admin` no front-end.
- Chat (Assistente Deméter) persiste histórico no `localStorage` e renderiza Markdown simples (escape HTML para reduzir XSS).
- Centralização do endpoint do backend via variável de build `VITE_API_URL` (front-end) e fallback para o URL atual.
- Netlify: `netlify.toml` atualizado com redirect `/* -> /index.html` para suportar routing SPA.

**Mapeamento ThingSpeak usado por padrão**
- `field1` -> `temp_C` (Temperatura)
- `field2` -> `rh_pct` (Umidade)
- `field3` -> `co2_ppm_est` (CO₂ estimado)
- `field4` -> `mq2_raw` (Sensor MQ2 raw)
- `field5` -> `luminosity_alert` (flag 0/1) — opcional
- `field6` -> `lux` (valor em lux) — opcional

Se seu canal ThingSpeak utiliza outro mapeamento, atualize `app/services/thing_speak.py` para mapear os fields corretos.

**Variáveis de ambiente ADICIONAIS importantes (backend)**
- `LUMINOSITY_DARK_THRESHOLD` (opcional) — valor em lux para considerar silo escuro (default 10)
- `LUMINOSITY_OPEN_THRESHOLD` (opcional) — valor em lux para considerar silo aberto (default 100)
- `IDENTICAL_READINGS_MIN_SECONDS` (opcional) — tempo mínimo para gravar leituras idênticas (default 18000)

**Variáveis de ambiente front-end**
- `VITE_API_URL` — URL completa do backend (ex.: `https://meu-backend.onrender.com/api`). Configure no Netlify (ou no build env do seu host).

---

Status da entrega — itens concluídos e pendentes

Concluído nesta iteração:
- Suporte a luminosidade + thresholds configuráveis.
- Lógica anti-duplicação de leituras do ThingSpeak.
- Registro de eventos de mudança de luminosidade e criação de alertas.
- Atualizações de schema (leitura/silo) e rotas básicas (`silos.create` adaptado para lat/lon).
- Front-end: logos, ícones SVG, dashboard simplificado, formulários atualizados, chat persistente, Netlify redirect e centralização do API_URL.

Pendências / recomendações (não implementadas nesta iteração):
- Endpoints RAG (resumo de dashboards, histórico para contextos da LLM) e orquestrador de contexto para a Assistente Deméter — posso implementar sob demanda.
- Job semanal para consumir API meteorológica externa, salvar previsões no MongoDB e evitar duplicidade semanal (scheduler + endpoint). Ainda precisa criar `tasks/` + job e rota para disparo manual/cron.
- Geração de PDF do relatório (back-end) — implementar com `WeasyPrint` ou `reportlab`/`wkhtmltopdf` e integrar à tela de Relatório do front.
- Ajustes finos na MFA (QRcode / validação) e políticas de gerenciamento por `admin` (no momento o fluxo básico de MFA está presente, mas recomendo validar com testes reais de QR e TOTP).
- Reorganização dos menus por role (mover `Users` para `Configurações`) e validação raça/role nos endpoints (algumas proteções já existem, mas revisar `routes/users.py` para aceitar enum `admin|operator`).

Se quiser, eu prossigo com qualquer item pendente na ordem de prioridade que você escolher (RAG, Relatório+PDF, MFA, roles). Caso contrário, considere a refatoração aplicada e documentada — você poderá aplicar localmente e validar.

---

Para qualquer dúvida sobre um trecho de código específico que alterei, diga qual arquivo quer revisar que eu descrevo o diff detalhado e rationale de implementação.

