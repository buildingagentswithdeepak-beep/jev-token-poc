# tokenpoc — Jev vs Copilot Frontier-Model Token-Reduction POC

Controlled A/B token-consumption experiment per `SPEC.md` (Draft v1.0): a
customer-support ticket triage & response pipeline implemented twice —
**V1** (Copilot model-only) vs **V2** (Jev-decisioned + Copilot-generative) — over the
same frozen 100-ticket gold-labeled dataset.

## Setup

```powershell
cd C:\Users\v-deegarg\jev-token-poc
.\.venv\Scripts\activate
pip install -e .
gh auth token | copilot login --with-token
if (-not (Test-Path .env)) { Copy-Item .env.example .env }  # never overwrite existing Jev key
```

## Commands (SPEC §11)

```powershell
python -m tokenpoc validate-dataset
python -m tokenpoc run baseline  --limit 10 --verbose          # V1 (real Copilot model calls)
python -m tokenpoc run optimized --limit 10 --jev-mode mock    # V2 (watermarked mock Jev)
python -m tokenpoc run optimized --limit 10 --jev-mode live    # V2 against live Jev (needs JEV_API_KEY)
python -m tokenpoc run comparison                              # both fresh + §12 report
python -m tokenpoc run comparison --baseline <run_id> --optimized <run_id>
python -m tokenpoc report <run_id>
```

V2 fallback gates (per-question, SPEC §6 — tune in Stage 4, freeze before measured runs):
`--gate-intent 0.50` (Choice derived confidence), `--gate-strategy 0.60` (Choice derived
confidence), `--gate-escalate-band 0.15` (Noul |p−0.5| unsure band). Priority (Score) has
no gate by design.

Exit codes: `0` success · `1` run error · `2` config / FR-15 comparison-compatibility error.

Artifacts: `results/<run_id>/requests.jsonl` (per-ticket raw records incl. every
Copilot model call's real `assistant.usage` tokens and effective model), `results/<run_id>/summary.json` (FR-15
compatibility fields + aggregates), `results/comparison-*.json`.

## Offline verification (no API key)

```powershell
python -m pytest                                 # fully offline provider/pipeline tests
python scripts\offline_apparatus_check.py        # full 100-ticket apparatus check, fake model
```

**Mock-mode warning (FR-13):** any run with `--jev-mode mock` is watermarked —
token *measurements* are valid, but totals/savings depend on mock routing and
are rendered `(mock-routed)`. They are apparatus-verification numbers, never
experimental results. The fake-model apparatus check's token numbers are not
real Copilot usage at all.

## Status vs SPEC §18 stages

- Stages 1–5 (harness, dataset, instrumentation, V1, mock-V2, mock comparison): **implemented & verified offline**. Live generation uses the official `github-copilot-sdk`; no Anthropic API key is required.
- This Enterprise account currently exposes only `COPILOT_MODEL=auto`; each call records
  the **effective** model reported by `assistant.usage` (currently `gpt-6-luna`). The code
  never labels auto-routed output as Claude. An explicit model ID fails closed if Copilot
  silently substitutes another model.
- Stage 6 (live Jev smoke test): `JevProvider` is implemented against the **published
  Jev docs** (https://jevstation.com/docs): request = `{state, questions:{id:{type,
  instructions, criteria}}}`, response = house envelope `{code, message, data}` with
  typed answers, `usage.input_tokens/output_tokens`, credits and model version; errors
  401/400/402/413/404 fail fast, 429 honours `retry-after`, 529/5xx get exponential
  backoff; client-side limits enforced (≤12 questions, instructions ≤600 chars, state
  ≤24,000 chars). Live mode runs a FREE key preflight (`GET /v1/systemone`) before
  spending credits. Get a key at https://jevstation.com/settings/apikeys and run
  `run optimized --limit 5 --jev-mode live` as the smoke test before full runs.
- Jev cost is **measured**: Jev's own `usage` tokens are captured per call and priced
  ($0.042/1M in, $0.00/1M out — jev-1.12, 2026-09). Copilot is subscription/prompt-
  accounted, not direct token-priced, so Copilot and net USD cost are reported as N/A;
  input/output token reduction remains measured from SDK usage events.
- §14's 3-repetition protocol: run `run comparison` three times and report mean/min–max of Token Reduction % (manual per spec; repetitions are separate run artifacts).

## Dataset

`dataset/tickets.jsonl` — 100 frozen synthetic tickets (generated once by
`scripts/generate_dataset.py`; **never regenerate between runs** — the dataset
hash is part of the FR-15 comparison guard). Composition per §9:
30 template-resolvable / 20 auto-resolve / 25 clear-generative / 15 ambiguous /
10 multi-issue (strategy mix 30/20/50).
