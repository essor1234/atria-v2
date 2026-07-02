# Atria V2 — run & switch LLM provider (Windows / PowerShell)

Quick cheat-sheet for running Atria locally and flipping the chat LLM between
**Qwen (DashScope)** and **OpenAI (GPT)**.

---

## Go to the project (run this first in every terminal)

The project path contains `[` `]`, which PowerShell treats as wildcards — use
`-LiteralPath` (a plain `cd 'D:\[Project]_atriaV2'` fails):

```powershell
Set-Location -LiteralPath 'D:\[Project]_atriaV2'
```

The `.\run-*.ps1` and `.\switch-llm.ps1` scripts already `cd` to their own folder
internally, so you can also just call them by full path from anywhere, e.g.
`& 'D:\[Project]_atriaV2\switch-llm.ps1' status`.

---

## TL;DR

```powershell
Set-Location -LiteralPath 'D:\[Project]_atriaV2'   # go to project
.\switch-llm.ps1 qwen        # use Qwen via DashScope (default; OpenAI is out of quota)
.\run-backend.ps1            # Terminal 1  -> API  http://127.0.0.1:8080
.\run-frontend.ps1           # Terminal 2  -> Web  http://localhost:5173  (open this)
```

Open **http://localhost:5173** and chat.

---

## 1. Prerequisites (once)

- **uv** installed (`uv --version`).
- **Docker Desktop running** — Atria's backend needs Postgres on `localhost:5432`.
- Frontend deps install automatically on first `run-frontend.ps1` (`npm install`).

### Start Postgres (localhost:5432)

If you already have the Atria Postgres container, just start it:

```powershell
docker start atria-pg
```

First time (creates it, loads schema, publishes 5432):

```powershell
docker run -d --name atria-pg -p 5432:5432 `
  -e POSTGRES_DB=atria -e POSTGRES_USER=atria -e POSTGRES_PASSWORD=atria `
  -v "D:\[Project]_atriaV2\schema.sql:/docker-entrypoint-initdb.d/schema.sql:ro" `
  postgres:16-alpine
```

Check it's up:

```powershell
(Test-NetConnection localhost -Port 5432 -WarningAction SilentlyContinue).TcpTestSucceeded  # -> True
```

`DATABASE_URL` in `.env` is already `postgresql://atria:atria@localhost:5432/atria`.

---

## 2. Run the app (two terminals)

**Terminal 1 — backend** (FastAPI, auto-restart loop, loads `.env` on each start):

```powershell
.\run-backend.ps1     # -> http://127.0.0.1:8080
```

**Terminal 2 — frontend** (Vite dev server, proxies /api + /ws to :8080):

```powershell
.\run-frontend.ps1    # -> http://localhost:5173
```

Then open **http://localhost:5173** in a browser and chat.

---

## 3. Switch LLM provider

The switch rewrites four lines in `.env` (`OPENAI_API_KEY`, `ATRIA_MODEL`,
`ATRIA_FALLBACK_MODEL`, `ATRIA_API_BASE_URL`). Atria reads the active provider's
key via `OPENAI_API_KEY` regardless of provider; both keys are stored (commented)
in the `.env` key vault.

```powershell
.\switch-llm.ps1 qwen      # Qwen via DashScope  (qwen3.5-122b-a10b / fallback qwen3.5-flash)
.\switch-llm.ps1 openai    # OpenAI               (gpt-5.5 / fallback gpt-5.4)
.\switch-llm.ps1 status    # show what's active now
```

**After switching, restart Terminal 1** (Ctrl+C, then `.\run-backend.ps1`) so the
new `.env` is reloaded. The frontend needs no restart.

---

## 4. Quick API smoke test (no app needed)

Confirm a provider's key+endpoint+model are live before launching everything:

```powershell
$key='sk-b0bbbf41d88d4a77a0f3364b73d11502'   # DashScope key (see .env key vault)
$url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions'
$body=@{ model='qwen3.5-122b-a10b'; messages=@(@{role='user';content='Reply with: OK'}); max_tokens=16 } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri $url -Method Post -Headers @{ Authorization="Bearer $key" } -ContentType 'application/json' -Body $body
```

Expect a JSON response with `choices[0].message.content = "OK"`.

---

## Notes / gotchas

- **Endpoint must be the full path** including `/chat/completions`, and the
  **international** host `dashscope-intl.aliyuncs.com` (the key is invalid on the
  Beijing endpoint). `switch-llm.ps1` sets this for you.
- **Qwen model choice:** `qwen3.5-122b-a10b` (capable, reliable tool calls, free
  quota). Avoid `qwen-max` / `qwen3-max` / `qwen-plus` / `qwen-turbo` — their free
  tier is exhausted (HTTP 403 `FreeTierOnly`) and qwen-max garbles tool output.
  `qwen3.5-flash` is the cheap fallback (free quota, "nearly out").
- **OpenAI side needs quota** — the saved OpenAI key was returning HTTP 429
  `insufficient_quota`; top up the account before `switch-llm.ps1 openai` will work.
- **qwen3.5 is a thinking model** — it spends some `reasoning_tokens` per reply;
  Atria's `max_tokens=8192` leaves plenty of room.
- `.env` is git-ignored; both API keys live only there (in the key vault comments).
