# Vasooli Bhai

**Aap kaam karo. Follow-up hum karenge.**

A Hinglish voice assistant that follows up on unpaid freelance invoices, built for the Sarvam AI Buildathon. It's warm and witty, and gets firmer when a commitment is missed. The invoice card updates live as the conversation happens.

Live demo: https://vasooli-bhai-tau.vercel.app

## How it works

- **Voice:** Sarvam speech-to-text (`saaras:v3`, codemix mode) → `sarvam-105b-conversations` with tool calling → Sarvam text-to-speech (`bulbul:v3`).
- **Tools:** plain local Python functions in `api/_tools.py` (not MCP): `get_invoice`, `record_payment_commitment`, `prepare_demo_payment_link`, `flag_payment_for_verification`, `record_dispute`, `record_payment_proposal`, `pause_contact`. Every call validates its arguments before changing the invoice and is written to the on-screen event log. The UI shows only tool results, never claims taken from the model's text.
- **Stateless server:** the browser holds the demo state and sends it with each request, so it runs on Vercel serverless functions. The Sarvam key stays on the server.
- **No key?** The app falls back to a clearly labelled scripted text demo mode that drives the same tools.

All invoice data, payment links and reminders are demo-only. Nothing is sent, charged or verified.

## Conversation rules

| Client says | Agent does | Invoice status |
|---|---|---|
| A date ("Friday ko kar dunga") | Reads back the full date and asks to confirm; saves only after a yes | Payment promised + reminder |
| "I already paid" | Asks for a reference or payment date; never marks it paid | Verification needed, reminders paused |
| "The amount is wrong" | Asks one clarifying question; never negotiates | Disputed, reminders paused |
| "Can't pay right now" | Offers a new date or partial payment for Aman to approve | Proposal pending |
| "Forgot" | Offers a demo payment link | Unchanged |
| "Stop contacting me" | Ends politely | Contact paused |

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env        # then paste your Sarvam key into .env
python3 server.py           # http://localhost:8000
```

`python3 chat.py` makes a single test chat call to check your key.

## Deploy to Vercel

```bash
npx vercel --prod
```

Then add `SARVAM_API_KEY` under Project → Settings → Environment Variables (Production) and redeploy.

## Files

```
index.html          UI: transcript, invoice card, event log, voice loop
api/index.py        Vercel function: /api/config, reset, start, turn, stt, tts
api/_agent.py       Sarvam LLM agent + scripted demo agent
api/_tools.py       Invoice tools with argument validation
server.py           Local dev server (reuses api/index.py)
chat.py             One-call Sarvam key check
vercel.json         Function timeout + /api rewrite
```
