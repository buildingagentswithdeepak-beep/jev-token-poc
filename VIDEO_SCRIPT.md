# VIDEO SCRIPT — "I Stopped My AI Model From Making Decisions. Then I Measured Every Token"

Structure: MYSTERY HOOK → evidence builds → measured reveal in Scene 5 (the climax).
The reduction % is never spoken or shown before the live comparison table prints on camera.

Target length: ~7:15 · Repo: `C:\Users\v-deegarg\jev-token-poc` · All commands PowerShell, venv activated.

---

## ⚠️ PRE-PRODUCTION BLOCKERS (read first)

The mystery structure means no percentage appears in the title, thumbnail, or hook — so
nothing is claimed before it's measured. But Scene 5 IS the on-camera reveal, so the live
comparison must exist before you record it:

**Provider fact:** generation now runs through the official GitHub Copilot SDK with
`COPILOT_MODEL=auto`. The effective model must be read from each live artifact. The verified
Copilot smoke runs reported `gpt-6-luna`, not Claude. Never infer “Claude” from `auto`.

**Evidence status before recording:**

1. ✅ **Fresh live V2 smoke run after the Copilot migration completed:** 5 requests, 0 errors,
   5 Jev calls / 20 decisions, 2 Copilot reply calls, effective model `gpt-6-luna`.
2. SPEC §14 requires **three repetitions** of the complete 100-ticket comparison, with the
   mean and min–max spread reported. That consumes 300 Jev evaluations. The completed `--limit 40` run
   processes the first ordered slice, under-samples later ticket classes, and must be labeled
   a partial slice—not a 100-ticket result.

```powershell
cd C:\Users\v-deegarg\jev-token-poc
.\.venv\Scripts\Activate.ps1

# Fresh post-migration smoke footage (spends 5 Jev credits):
python -m tokenpoc run optimized --limit 5 --jev-mode live --verbose

# Publication-grade protocol (3 × 100 tickets; spends 300 Jev credits):
1..3 | ForEach-Object { python -m tokenpoc run comparison --jev-mode live }

# Completed exploratory comparison—presented as a biased 40-ticket slice:
python -m tokenpoc run comparison --jev-mode live --limit 40
```

**Verified live V2 smoke result — apparatus proof, not a savings comparison:**

| Metric | Actual |
|---|---:|
| Requests / errors | 5 / 0 |
| Effective Copilot model | `gpt-6-luna` |
| Copilot calls (triage / reply / repair) | 2 (0 / 2 / 0) |
| Tickets with no Copilot call | 3 of 5 |
| Copilot tokens (input / output / total) | 601 / 475 / 1,076 |
| Jev calls / decisions | 5 / 20 |
| Jev tokens (input / output / total) | 4,255 / 780 / 5,035 |
| Gates fired (intent / strategy / escalation) | 0 / 2 / 1 |

Do **not** derive a token-reduction percentage from this table: it has no matching live V1
baseline over the same five tickets.

Scene 5 below is now filled from the saved 40-ticket live comparison artifact. Treat it as
an exploratory result. The mystery structure is still result-proof: the reveal includes both
the measured token reduction and the failed quality gate.

**Title options (no spoiler, no unverified claim):**
1. "I Stopped My AI Model From Making Decisions. Then I Measured Every Token" ← primary
2. "Model Tokens: Zero — The Architecture That Stops Spending LLM Tokens on Decisions"
3. "Jev Decides, Copilot Writes: I Measured What Happened to Token Usage"

**Thumbnail:** screenshot of the real terminal line
`Copilot model invoked: No   model tokens: 0`, with the overlay text **MODEL TOKENS: 0**.
This is intriguing without attributing `auto` to a model family it did not use.

---

## 1. OPENING HOOKS (Hook A is the chosen M1 mystery hook; B and C are fallbacks)

**HOOK A — M1 (CHOSEN — the zero, mystery reveal):**
> "Copilot model invoked: no. Model tokens: **zero**. That's a real log line from a support
> ticket that got classified, prioritized, routed, and answered — and the frontier model
> never woke up. I rebuilt this pipeline so the Copilot model does only one thing. At the end of this
> video, I'll show you exactly what that did to token usage — measured, not estimated."

**HOOK B (fallback — the absurdity angle):**
> "Every time your AI agent picks an option from a list — route A or route B, urgent or not —
> your frontier model is generating *text*, just so you can throw the text away and keep one
> word. I built an experiment to measure how many model tokens that habit consumes. The
> number comes at the end — and I'll show you where it comes from first."

**HOOK C (fallback — one-sentence rule):**
> "I added one rule to my AI pipeline: the Copilot model is never allowed to make a decision. Not
> categories, not priorities, not routing — it only writes. Everything else goes to a model
> that can't generate text at all. Sounds like it should break everything. Stick around —
> the final number comes straight from the provider usage logs."

---

## 2. TIMESTAMPED SCRIPT + SCENE-BY-SCENE PLAN

### SCENE 1 — Cold Open (0:00–0:20)
- **Narration:** Hook A (M1) verbatim — use the selected zero-token mystery hook above.
- **On-screen:** Full-screen terminal, dark theme, ONE zero-call log block from the verified
  five-ticket live run. Replace bracketed fields with a verbatim block from that artifact:
  ```text
  Request [ZERO-CALL TICKET ID]
    [PASTE THE ACTUAL JEV DECISION LINE]
    Handled by: Jev → [ACTUAL DETERMINISTIC HANDLER]
    Copilot model invoked: No   model tokens: 0
  ```
  Typewriter-reveal the block line by line in sync with the narration; on "zero", the
  `model tokens: 0` fragment zooms ~140% with a subtle glow. On "one thing", flash the
  tagline card: "The frontier model only writes." On "measured, not estimated", a small lock icon +
  "reveal at 5:00" chip appears bottom-right (optional but boosts retention).
- **Footage status:** ✅ The fresh post-migration five-ticket live run exists. Capture one of
  its three zero-Copilot-call request blocks verbatim; do not reconstruct the confidence values.
  No comparison numbers anywhere in this scene.
- **Animation:** Terminal typewriter + single zoom. No token counters yet — the meter
  visual debuts in Scene 2 so the cold open stays stark.
- **Edit note:** No intro, no logo. Hard cut on "measured, not estimated" straight to
  Scene 2. SFX: one soft keyboard tick per revealed line, single low "thud" on the zoom.

### SCENE 2 — The Problem (0:20–1:15)
- **Narration:**
  > "Here's a customer-support pipeline. Every ticket needs five things: what category is
  > this? How urgent? Should a human see it? Which reply strategy? And — only sometimes —
  > an actual written reply. Four of those five are *decisions*. Closed sets. Pick one of
  > six categories. Pick one of four priorities. Yes or no. One of three strategies.
  > The standard way to build this is: send everything to the LLM. And that means every
  > single ticket — even 'I forgot my password' — pays for a system prompt with category
  > definitions, a rubric, few-shot examples... hundreds of input tokens before the ticket
  > is even classified, to receive back values you already defined. It's like hiring a
  > novelist to tick checkboxes. The novelist is great. That's not the point."
- **On-screen text:** "O1 classify · O2 priority · O3 escalate · O4 strategy = DECISIONS" /
  "O5 write the reply = GENERATION"
- **Animation:** Ticket icon flows to a Copilot model node; a token meter fills on EVERY hop.
  Use the actual live V1 usage shown later—782 input and 161 output tokens in the verified
  one-ticket smoke artifact—rather than an estimated counter.
- **Footage:** Open `tokenpoc/prompts/triage_system.txt` in editor — slow scroll over the
  category definitions + few-shot examples while narrating "hundreds of tokens of overhead".

### SCENE 3 — Introduce Jev (1:15–2:00)
- **Narration:**
  > "Enter Jev, by TypeSafe. Jev is not a chat model — it never writes text. You send it a
  > *state* — the ticket — plus typed questions, and it returns typed answers with
  > probability distributions. Three primitives: **Choice** — pick from options you define.
  > **Score** — place the state on an ordered scale. **Noul** — a yes/no probability.
  > So the new architecture is one sentence: *Jev picks the bucket; the frontier model writes the words.*
  > One Jev call per ticket answers all four decisions in parallel. Deterministic code does
  > the routing and fills templates. The Copilot model is invoked only when a ticket genuinely needs a
  > custom-written reply — billing disputes, nuanced complaints. For a password reset?
  > Zero Copilot model tokens. The call never happens."
- **On-screen text:** "Jev picks the bucket. The frontier model writes the words."
- **Animation (before/after, the key visual):**
  - BEFORE: ticket → Copilot model (TRIAGE, meter uses live usage) → branch → sometimes Copilot model (REPLY).
  - AFTER: ticket → Jev node (4 small typed chips pop out: Choice/Score/Noul/Choice) →
    deterministic router (gears icon, meter stays at 0) → 3 lanes: template (0 tokens),
    data lookup (0 tokens), Copilot model REPLY (meter fills only here).
  - Keep the Copilot model REPLY node in BOTH diagrams — generation is never eliminated, only decisions.
- **Footage:** `tokenpoc/prompts/jev_questions.json` on screen; point at `q_intent` criteria map.

### SCENE 4 — Live Code Demo (2:00–5:00)

**4a (2:00–2:40) — The baseline, V1.**
- **Do on screen:** Open `tokenpoc/pipeline_v1.py`. Highlight `_triage()` → the
  `client.complete(system=..., max_tokens=TRIAGE_MAX_TOKENS)` call and the JSON repair-retry
  block (`result.repair_retries += 1`). Then open `tokenpoc/providers/copilot.py` and point
  to `AssistantUsageData`, effective-model capture, and the missing-usage failure.
- **Say:** "V1 is the *strongest* sane baseline — one combined triage call, not four. If
  the Copilot model returns malformed JSON we retry once, and those retry tokens are counted.
  The token numbers come from Copilot's usage event, not from counting words. And because the
  account exposes `auto`, the artifact records the model Copilot actually used."
- **Run:** `python -m tokenpoc run baseline --limit 5 --verbose`
- **Highlight in output:** every ticket shows TRIAGE tokens; the real `usage` numbers.

**4b (2:40–3:30) — The Jev call, V2.**
- **Do on screen:** Open `tokenpoc/pipeline_v2.py`. Highlight the single
  `provider.evaluate(state, questions)` call, then the gate block:
  `intent_a.confidence < gate_intent`, `abs(escalate_a.noul - 0.5) < gate_escalate_band`.
- **Say:** "One POST to Jev's systemone endpoint. Four questions evaluated in parallel
  against the same state. And here's the safety valve: per-question confidence gates. If
  Jev isn't sure about intent or strategy, we don't guess — we fall back to Copilot model. That
  trades tokens for quality, and the report counts every firing."
- **Then open** `tokenpoc/providers/jev.py` briefly: point at the documented error table
  and `usage` capture — "Jev reports its own token usage, so its cost is measured, not hand-waved."

**4c (3:30–4:30) — Run it live.**
- **Run:** `python -m tokenpoc run optimized --limit 5 --jev-mode live --verbose`
- **Highlight the actual summary first:**
  ```text
  provider                        github-copilot
  requested model                 auto
  effective model(s)              gpt-6-luna
  dataset                         tickets.jsonl [213b0704bfc03035]
  requests processed              5
  errors                          0
  Copilot model calls             2
    triage / reply / repair       0 / 2 / 0
  Jev Calls (1/ticket)            5
  Jev Decisions (4/call)          20
  fallbacks (intent/strategy/esc) 0 / 2 / 1
  Jev tokens (in/out)             4,255 / 780
  Copilot model input tokens      601
  Copilot model output tokens     475
  Total Copilot model tokens      1,076
  ```
- **Then scroll to one of the three zero-call request blocks and zoom on:**
  ```text
  Copilot model invoked: No   model tokens: 0
  ```
- **Say:** "Here's the live receipt: five tickets, zero errors. Jev made exactly five API
  calls and returned twenty typed decisions—four per call. The Copilot model woke up only
  twice, both times to write replies. It used 601 input tokens and 475 output tokens: 1,076
  total. The effective model reported by Copilot was `gpt-6-luna`. Three of the five tickets
  completed without any Copilot call. The strategy gate fired twice; the escalation
  uncertainty gate fired once. This proves the mechanism works—but it is not a savings
  percentage, because I have not compared it with a matching live baseline yet."
- **Then show:** the fresh JevStation ledger screenshot captured after this run.
  Say: "Five tickets, five Jev API calls, four decisions per call. The provider ledger and
  my harness agree on call count. Token usage comes from each provider's usage metadata."

**4d (4:30–5:00) — The comparison run.**
- **Run shown on screen:**
  `python -m tokenpoc run comparison --jev-mode live --limit 40`
- **Screen:** Show the first-ticket progress, but cut away before the table prints so the
  measured result and quality verdict land together in Scene 5.
- **Say:** "This is an exploratory comparison over the first forty records in the frozen
  dataset—not the full benchmark. Both architectures process the identical ticket IDs with
  the same Copilot provider setting, and the compatibility guard checks the effective model.
  The harness uses provider usage metadata and signed savings, so the number can be positive
  or negative. More importantly, it scores quality against the same gold labels. A lower
  token count with a failed quality gate is still a failed configuration. Let's see both."
- **Edit note:** Hold the suspense on the token figure, but do not hide the quality verdict:
  both appear in the Scene 5 reveal.

### SCENE 5 — THE REVEAL: 40-Ticket Exploratory Result (5:00–6:00) ← CLIMAX
- **Staging:** Let the comparison table print on camera. Pause on `Token Reduction: 93.01%`,
  then immediately reveal the failed quality gate—both are part of the result.
- **On-screen result card (all values from the saved live artifact):**

  | Field | Actual result |
  |---|---:|
  | Scope | 40 effective tickets (`T-001`–`T-040`) |
  | Slice composition | 30 template + 10 auto-resolve + 0 custom-reply |
  | Baseline Copilot calls / tokens | 40 / 33,723 |
  | Optimized Copilot calls / tokens | 4 / 2,357 |
  | Tokens saved | 31,366 |
  | Token reduction | **93.01%** |
  | Jev calls / decisions | 40 / 160 |
  | Jev tokens (input / output / total) | 33,888 / 6,264 / 40,152 |
  | Jev cost | **$0.001423296** |
  | Effective Copilot model | `gpt-6-luna` |
  | Strategy accuracy | V1 100% → V2 90% |
  | Quality gate | **FAILED — 10-point drop; maximum allowed: 5** |

- **Narration:**
  > "...and there it is." (beat) "On this ordered forty-ticket slice, the baseline made
  > forty Copilot model calls and used 33,723 model tokens. The optimized pipeline made four
  > calls and used 2,357. That's 31,366 tokens removed—a measured reduction of **93.01
  > percent**. But stop there, because the quality result is part of the receipt. Strategy
  > accuracy fell from 100 percent to 90: a ten-point drop, twice the pre-registered limit.
  > Priority accuracy fell from 87.5 to 65, and escalation accuracy from 90 to 55. So this
  > configuration failed the quality gate. And this slice is unusually favorable to call
  > elimination: thirty template tickets, ten auto-resolve tickets, and zero gold custom-reply
  > tickets. Jev used 33,888 input tokens and 6,264 output tokens—40,152 total—at a measured
  > cost of about $0.001423. Copilot reported `gpt-6-luna`; its subscription cost cannot be
  > converted into a defensible per-token dollar saving. The honest result is: **93.01 percent
  > fewer model tokens on this limited slice, with an unacceptable quality regression.**"
- **Animation:** Show the raw table first. Stamp `93.01% FEWER MODEL TOKENS`, then—without a
  celebratory cut—place a red `QUALITY GATE FAILED` badge beside it. Follow with three paired
  accuracy bars: strategy `100 → 90`, priority `87.5 → 65`, escalation `90 → 55`.
- **Persistent caveat:** `Exploratory ordered slice: 40/100 tickets · 30 template · 10
  auto-resolve · 0 custom-reply · not representative of the full workload.`
- **Publishing rule:** Keep `93.01%` out of the title and thumbnail. It may be quoted only
  together with the failed quality gate and limited-slice caveat.

### SCENE 6 — Limitations & Trade-offs (6:00–6:45)
- **Narration:**
  > "This is why token reduction alone is the wrong scoreboard. The mechanism worked: Jev
  > handled 160 typed decisions, and the Copilot model was called only four times. But the
  > current questions and gates did not preserve quality. Four template tickets were routed
  > to custom replies; priority has no fallback gate; and escalation accuracy dropped by
  > thirty-five points. The first forty records are also an ordered, decision-heavy slice
  > with no gold custom-reply tickets, so they structurally inflate call elimination. The next
  > step is not to celebrate 93 percent. It is to tune the decision criteria and gates, rerun
  > the quality checks, and then execute the full three-repetition protocol. Until quality
  > passes, this is a mechanism demonstration—not a production result."
- **On-screen text:** `TOKENS ↓ 93.01%` beside `QUALITY GATE: FAILED` and
  `Scope: ordered 40-ticket slice`.
- **Footage:** Open the saved comparison artifact. Highlight `quality_gate.passed: false`,
  `strategy_acc_delta_pts: 10.0`, and the V1/V2 accuracy blocks before showing `metrics.py`.

### SCENE 7 — Conclusion & CTA (6:45–7:15)
- **Narration:**
  > "The takeaway fits on a sticky note: **don't spend frontier-model tokens deciding
  > things a typed model or ordinary code can decide reliably.** Audit your agent: every
  > place it picks from a list you already wrote down is a candidate. The full harness —
  > dataset, both pipelines, the measurement code — is linked below. If you've cut tokens
  > a different way, tell me in the comments. And if you want more measured — not
  > marketed — AI engineering, subscribe."
- **On-screen:** Sticky-note card with the takeaway; repo link; end card.

---

## 3. ASSET CHECKLIST (before editing)

- [x] Exploratory 40-ticket live comparison integrated from
  `comparison-v1-20261020T192353Z-p058caaef-vs-v2-live-20261020T192703Z-p058caaef.json`
- [ ] Three full live comparisons and mean/min–max remain required before presenting the
  result as the specification-grade full-workload benchmark
- [x] Fresh post-migration V2 smoke summary integrated: 5 requests, 0 errors, 2 Copilot
  reply calls, 5 Jev calls / 20 decisions, effective model `gpt-6-luna`
- [ ] Scene 1 asset: select and paste one of the three zero-Copilot-call request blocks from
  the verified verbose run; do not reconstruct its ticket ID or confidence values
- [ ] Scene 4d suspense edit: `--limit 40` comparison starts without the final table visible
- [ ] Fresh JevStation ledger screenshot captured immediately after the live V2 recording
- [ ] Editor captures: `pipeline_v1.py` (_triage + repair), `pipeline_v2.py` (evaluate + gates),
  `providers/copilot.py` (usage + effective model), `prompts/triage_system.txt`,
  `prompts/jev_questions.json`, `providers/jev.py`, and `metrics.py` (signed savings)
- [ ] Thumbnail: real `Copilot model invoked: No   model tokens: 0` terminal line +
  **MODEL TOKENS: 0** overlay
- [ ] Before/after architecture animation (Scene 3 spec)
- [ ] Token bar chart + red quality-failure panel (Scene 5)
- [ ] Credits check immediately before comparison: the remaining §14 protocol needs 300 Jev
  evaluations; if unavailable, explicitly reframe any limited result as exploratory

## 4. FACT-CHECK CHECKLIST (verify before publishing)

- [ ] Every token number on screen comes from a `summary.json` / `requests.jsonl` of a **live** run (never the apparatus check — its Copilot model numbers are fake-client)
- [x] Five-ticket V2 smoke values copied from the actual successful live output; no reduction
  percentage derived from this optimized-only run
- [ ] All terminal footage was recorded after the Copilot migration; no direct-Anthropic-era
  artifact or Jev ledger screenshot is presented as a current Copilot run
- [ ] NO percentage appears in title, thumbnail, hook, or Scenes 1–4 (mystery held until Scene 5)
- [x] Scene 5 values read from the saved live comparison artifact, not memory
- [x] `93.01%` kept out of title/thumbnail and paired with the failed quality gate
- [x] Effective model named as `gpt-6-luna`; `auto` is not described as Claude
- [ ] Mock-mode artifacts, if shown at all, visibly carry the `(mock-routed)` watermark
- [ ] "One combined triage call" baseline claim stated (fairness note, SPEC §5)
- [x] Jev cost line shown — no claim of "free decisions"
- [x] Quality regression leads the interpretation: strategy dropped 10 points and the gate failed
- [ ] No claim that generation was eliminated — only decisions moved
- [x] Scope caveat uses exact effective N=40; the ordered slice is not described as
  representative of the full 100-ticket dataset
- [ ] Jev described accurately: typed questions (Choice/Score/Noul), probabilities, no text generation, one call per ticket / four decisions per call
- [x] The `--limit 40` slice is identified as 30 template + 10 auto-resolve + 0 custom-reply
