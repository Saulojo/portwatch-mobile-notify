# PortWatch VI → Telegram

Manda uma mensagem no seu Telegram sempre que a porcentagem do projeto líder do
[PortWatch VI](https://portwatch-vi.xyz) mudar, ou quando outro projeto assumir a liderança.

A mensagem traz: porcentagem (antes → depois), projeto e repositório, etapa (Jogável etc.),
história, gráficos, **FPS**, estabilidade, resumo, **o que funciona**, **o que está travando**,
link de prova (vídeo/post) e o top 3.

> **Forma recomendada de rodar sem deixar o PC ligado:** Google Apps Script. Veja
> [apps_script/LEIA-ME.md](apps_script/LEIA-ME.md). O workflow do GitHub Actions abaixo foi
> desativado porque o agendador do GitHub nunca disparou neste repositório.

Não precisa instalar nada além do Python. O script lê o mesmo arquivo de dados que o site
usa (`/data/tracker.json`) e calcula a porcentagem com a mesma fórmula do site.

## Configuração (uma vez só, ~3 minutos)

1. **Crie o bot:** no Telegram, abra uma conversa com **@BotFather**, mande `/newbot`,
   escolha um nome e um usuário (terminando em `bot`). Ele responde com um **token**.
2. **Crie o config:** copie `config.example.json` para `config.json` e cole o token em
   `telegram_bot_token`.
3. **Descubra o seu chat_id:** abra o seu bot no Telegram, mande `/start`, e rode:
   ```powershell
   python portwatch_notify.py --get-chat-id
   ```
   Cole o número que aparecer em `telegram_chat_id` no `config.json`.
4. **Teste:**
   ```powershell
   python portwatch_notify.py --test
   ```
   A mensagem com o status atual deve chegar no seu celular.

## Rodando

Dê dois cliques em `iniciar.bat` (ou rode `python portwatch_notify.py`). Ele checa o site a
cada 5 minutos (`interval_seconds`) e só manda mensagem quando algo muda. Na primeira
execução manda uma mensagem de "monitoramento iniciado". O PC precisa ficar ligado.

Opções do `config.json`:

| Campo | O que faz |
|---|---|
| `interval_seconds` | intervalo entre checagens (mínimo 60) |
| `notify_on_fps_change` | `true` para avisar também quando só o FPS do líder mudar |

Outros comandos:

- `python portwatch_notify.py --dry-run`: mostra a mensagem no terminal, sem enviar
- `python portwatch_notify.py --once`: checa uma vez e sai (para usar no Agendador de Tarefas)

### Iniciar junto com o Windows (opcional)

Aperte `Win + R`, digite `shell:startup` e coloque ali um atalho para o `iniciar.bat`.

## Rodando na nuvem, de graça (GitHub Actions), sem deixar o PC ligado

O arquivo `.github/workflows/portwatch.yml` faz o GitHub rodar `portwatch_notify.py --once`
a cada 5 minutos. O `state.json` (líder e % da última checagem) é salvo de volta no repositório.

1. Crie um repositório **público** no GitHub e envie esta pasta (o `config.json` fica de fora
   pelo `.gitignore`). Em repositório público o Actions é ilimitado; em privado o limite
   gratuito de 2.000 min/mês acaba em ~1 semana com checagens a cada 5 min.
2. Em **Settings → Secrets and variables → Actions → New repository secret**, crie:
   - `TELEGRAM_BOT_TOKEN`: o token do bot
   - `TELEGRAM_CHAT_ID`: o seu chat_id

   Os secrets ficam criptografados e não aparecem para quem visita o repositório.
3. Na aba **Actions**, abra "PortWatch -> Telegram" e clique em **Run workflow** para testar.

Observações:
- O GitHub pode atrasar as execuções agendadas alguns minutos (às vezes 10-20) em horários de pico.
- Se o repositório ficar 60 dias sem nenhum commit, o GitHub pausa o agendamento. Os commits
  do `state.json` a cada mudança do líder normalmente evitam isso; se pausar, é só reativar na aba Actions.
- Se usar a nuvem, pare o `iniciar.bat` no PC para não receber mensagens repetidas.

### Se o agendamento do GitHub não disparar: cron-job.org

O agendador do GitHub é "melhor esforço" e pode simplesmente não rodar. Neste repositório ele
nunca disparou, mas o disparo manual funciona. Então um serviço externo e gratuito chama o
disparo a cada 5 minutos:

1. **Token do GitHub:** em GitHub → Settings → Developer settings → Personal access tokens →
   **Fine-grained tokens** → Generate new token.
   - Repository access: *Only select repositories* → `portwatch-mobile-notify`
   - Permissions → Repository permissions → **Actions: Read and write**
   - Copie o token gerado.
2. **cron-job.org:** crie uma conta gratuita em https://cron-job.org e clique em *Create cronjob*:
   - URL: `https://api.github.com/repos/Saulojo/portwatch-mobile-notify/actions/workflows/portwatch.yml/dispatches`
   - Execution schedule: a cada 5 minutos
   - Aba *Advanced*:
     - Request method: **POST**
     - Headers:
       - `Authorization`: `Bearer SEU_TOKEN`
       - `Accept`: `application/vnd.github+json`
       - `Content-Type`: `application/json`
     - Request body: `{"ref":"main"}`
3. Salve e clique em *Test run*. A resposta certa é **204 No Content**, e uma nova execução
   aparece na aba Actions do repositório.
