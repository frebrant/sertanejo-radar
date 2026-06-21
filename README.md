# 🎤 Sertanejo Radar

Monitor de notícias virais do mundo sertanejo — escaneia 20+ portais, Twitter (via Nitter/RSSHub) e Instagram (via RSSHub), aplica score de viralidade (frescor × multi-fonte × menção de artista) e te notifica no Telegram quando algo está pegando.

**Roda 100% na nuvem grátis.** Seu PC pode ficar desligado.

## Arquitetura

```
GitHub Actions (cron 30min)  →  SQLite no repo  →  Streamlit Cloud (dashboard)
                              ↓
                          Telegram bot (notificação)
```

## Setup (passo a passo)

### 1. Criar bot do Telegram (5 min)
1. Abra o Telegram, busque **@BotFather**, mande `/newbot`, siga as instruções.
2. Guarde o **TOKEN** que ele te dá.
3. Inicie conversa com seu bot (mande `/start` pra ele).
4. Busque **@userinfobot** e copie seu **CHAT_ID**.

### 2. Criar API key do Gemini (3 min) — para copy IA pronta
1. Acesse https://aistudio.google.com/apikey (precisa de conta Google)
2. Click em "Create API key" → escolha um projeto qualquer
3. Copie a key (formato `AIza...`)
4. **Limite grátis**: 1.500 chamadas/dia — sobra muito.
   Se você pular esta etapa, o sistema usa copy estática como fallback.

### 3. Criar repo público no GitHub (3 min)
- github.com/new → nome `sertanejo-radar` → **público** (libera Actions ilimitado)
- Suba este código pra lá.

### 4. Adicionar secrets no GitHub (2 min)
- Repo → Settings → Secrets and variables → Actions → New repository secret
- Crie `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (passo 1) e `GEMINI_API_KEY` (passo 2).

### 5. Rodar o pipeline pela primeira vez
- Repo → Actions → "Sertanejo Radar Pipeline" → **Run workflow**
- Vai rodar em ~3 min, popular `data/radar.db` e commitar de volta.

### 6. Deploy do dashboard (5 min)
- Acesse https://streamlit.io/cloud → New app → conecte sua conta GitHub.
- Escolha o repo `sertanejo-radar`, branch `main`, arquivo `dashboard/app.py`.
- Deploy. Você ganha uma URL `https://<nome>.streamlit.app`.
- Salve essa URL nos favoritos do celular.

Pronto. A partir daqui, a cada 30 min o GitHub Actions roda o pipeline; matérias com score `>= 0.6` ganham copy IA (3 títulos + legenda Instagram); matérias com score `>= 0.75` pingam no seu Telegram com a copy pronta; o dashboard sempre mostra o top atual.

## Rodar localmente (opcional, para testar/debugar)

```powershell
cd "c:\Users\frebr\Claude code\sertanejo-radar"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Crie .env a partir de .env.example e preencha
copy .env.example .env

python scripts/setup_db.py
python scripts/run_pipeline.py
streamlit run dashboard/app.py
```

## Personalização

Tudo editável sem mexer no código Python:

- **`config/sources.yaml`**: portais RSS, perfis Twitter/Instagram, instâncias de fallback.
- **`config/artistas.yaml`**: nomes que disparam `bonus_artista` no score.
- **`src/scoring.py`**: pesos da fórmula de viralidade (se quiser ajustar).
- **`src/pipeline.py`**: constante `NOTIFY_THRESHOLD` (default `0.75`) controla a barra de envio Telegram.

## Roadmap

- ✅ **v0.5 (entregue)**: Gemini Flash gera 3 sugestões de título + 1 legenda Instagram pra cada matéria com `score >= 0.6`. Copy aparece no dashboard e no push do Telegram.
- **v1.0**: YouTube Data API alimenta fator `engajamento_yt`, pytrends pra `trending_match`, dashboard com histórico ("o que postei e bombou?"), auto-arquivar matérias > 7 dias.
