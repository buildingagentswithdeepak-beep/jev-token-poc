# Technical & Functional Specification

## POC: Measuring Frontier-Model Token Reduction via Jev-Delegated Decisioning

| | |
|---|---|
| **Document status** | Draft v1.1 — Copilot provider amendment applied |
| **Experiment type** | Controlled A/B token-consumption comparison (CLI, no UI) |
| **Architectures under test** | V1: Copilot model-only (baseline) vs. V2: Jev + Copilot model (optimized) |
| **Primary metric** | Total Copilot effective-model tokens (input + output) over an identical fixed workload |
| **Stance** | Hypothesis-testing, not claim-proving. The experiment reports whatever it measures. |

### Provider Amendment — 2026-10-20 (supersedes Claude/Anthropic access details below)

The direct Anthropic quota is exhausted. By user decision, frontier-model generation now
uses the official GitHub Copilot SDK with `COPILOT_MODEL=auto`; this Enterprise policy does
not expose an explicit Claude model. Therefore:

- “Claude” in the original experiment design is operationally replaced by the **Copilot
  frontier model** for both V1 and V2. The architecture comparison remains identical.
- Every call records the effective model from Copilot `assistant.usage`; the verified smoke
  run reported `gpt-6-luna`. The system MUST NOT attribute `auto` output to Claude.
- Input/output token totals remain measured, never estimated.
- Copilot does not expose temperature or a per-call output-token cap through this SDK path;
  temperature is recorded as N/A and the output budget is included as a prompt constraint.
- Copilot is subscription/prompt-accounted, not direct per-token billed. Generation USD and
  net USD delta are reported as N/A; measured Jev cost and token reduction remain reportable.
- An explicit future `COPILOT_MODEL` MUST fail closed if the usage event reports substitution.

This amendment changes provider access and cost accounting only; dataset, routing, gates,
quality guardrails, one-Jev-call/four-decisions behavior, and compatibility rules remain.

---

## 1. Executive Summary

This POC is a command-line experiment that tests one hypothesis:

> *Decision-oriented operations (classification, routing, prioritization, selection among
> predefined outcomes) do not require a generative frontier model. If a typed decision model
> (Jev, by TypeSafe AI) handles those operations, Claude is invoked only for genuinely
> generative work — potentially reducing Claude calls and total Claude token consumption.*

Two implementations of the **same application** — a customer-support ticket triage and
response pipeline — process the **same frozen dataset of 100 tickets**:

- **V1 (Baseline):** Claude performs every AI operation — classification, priority scoring,
  escalation decisions, response-strategy selection, and reply generation.
- **V2 (Optimized):** Jev performs all typed decisions; deterministic application code performs
  routing and template filling; Claude is invoked *only* when a ticket genuinely requires a
  custom-generated reply.

Every Claude API call's real `usage.input_tokens` / `usage.output_tokens` metadata is recorded
(never estimated). The CLI prints a side-by-side comparison: calls, input/output/total tokens,
absolute savings, and percentage reduction — **computed from measured execution, not assumed**.

A quality guardrail runs in parallel: both architectures' decisions are scored against
gold-labeled ground truth, and routing/outcome agreement between the two versions is reported.
If V2 saves tokens but degrades decision accuracy or outcome quality, the report makes that
visible rather than hiding it.

**Explicitly out of scope:** UI, persistence beyond run artifacts, authentication,
multi-tenancy, production hardening. This is an instrumented experiment, not a product.

**API grounding:** Jev's API is publicly documented (`POST /v1/systemone`, question primitives
`Choice`/`Score`/`Noul`, per-response usage metadata, published pricing). The spec's Jev
integration (§6) is written against that documented surface; the `DecisionProvider` adapter
remains as an implementation seam (and hosts the mock), not as an assumption shield. The
formerly open assumptions A1–A6 are resolved — see the table in §17. A notable consequence:
**Jev's own token usage and dollar cost are measured directly**, so "token reduction ≠ cost
reduction" is answered with a number, not a disclaimer.

---

## 2. Recommended Demo Use Case

### Customer-Support Ticket Triage & Response Pipeline

A CLI application ingests raw support tickets (free-text subject + body + lightweight customer
metadata) and, for each ticket, must:

| # | Operation | Nature |
|---|-----------|--------|
| O1 | **Classify intent** into one of 6 categories: `PASSWORD_RESET`, `ORDER_STATUS`, `BILLING_DISPUTE`, `BUG_REPORT`, `CANCELLATION`, `GENERAL_INQUIRY` | Decision (closed set) |
| O2 | **Score priority**: `LOW` / `MEDIUM` / `HIGH` / `URGENT` | Decision (closed set) |
| O3 | **Decide escalation**: should this go to a human agent queue? (boolean + queue id) | Decision (closed set) |
| O4 | **Select response strategy**: `TEMPLATE_REPLY` (use a predefined canned response), `AUTO_RESOLVE` (deterministic data lookup + template), or `CUSTOM_REPLY` (needs generated text) | Decision (closed set) |
| O5 | **Generate the reply** — only when strategy = `CUSTOM_REPLY` (e.g., billing disputes, nuanced complaints, ambiguous multi-issue tickets) | **Generative** |

Final output per ticket: a routing record (category, priority, escalation, strategy) plus a
customer-facing reply (templated or generated).

### Why this use case (rationale required by Step 1)

1. **Natural mix of decision and generation.** O1–O4 are selections among predefined outcomes —
   exactly what a typed, non-generative decision model claims to do. O5 is irreducibly
   generative (a billing-dispute reply must reference the customer's specific situation in
   natural language). Nothing is moved to Jev artificially; the split falls out of the domain.
2. **Repeated decisions dominate the workload.** Every ticket requires 4 decisions but only a
   *subset* requires generation. In real support operations a large fraction of tickets are
   routine (password resets, order-status checks) and resolvable by template. This repetition is
   what makes token-consumption differences measurable rather than noise.
3. **Trivially CLI-runnable.** Input = JSONL file of tickets; output = JSONL results + printed
   report. No UI, no state, no services to stand up.
4. **Identical inputs through both architectures.** The frozen dataset is a file; both versions
   read the same file in the same order with temperature 0 — a true apples-to-apples comparison.
5. **Jev's role is instantly understandable.** "Jev decides *which bucket*; Claude writes *the
   words*" explains itself in one sentence — ideal for a demo.
6. **Honest-failure surface exists.** If Jev misclassifies, templates get sent for tickets that
   needed custom replies (or vice versa). The gold-label quality check (§13) will expose this —
   the experiment can genuinely fail, which is what makes it an experiment.

---

## 3. Why This Use Case Demonstrates Token Reduction (Mechanism, Not Prediction)

This section explains the *mechanism* by which savings **could** occur. It is not a prediction
of magnitude; the measured result may be large, small, or negative.

Three distinct token-saving mechanisms are testable here:

1. **Call elimination.** In V1, tickets resolvable by template still require Claude calls for
   classification. In V2 those tickets may consume **zero** Claude tokens end-to-end
   (Jev decides → app code fills template).
2. **Decision-prompt elimination.** Classification prompts carry fixed overhead every time:
   system instructions, category definitions, output-format schema, few-shot examples, plus the
   ticket text — repeated for all N tickets. V2 sends none of this to Claude.
3. **Output-token elimination on decisions.** Even tightly constrained, a Claude classification
   response costs output tokens (JSON structure, labels). Jev returns a typed result with zero
   Claude output tokens.

Counter-forces the experiment must also surface honestly:

- Per-generation input tokens are **symmetric by design**: both versions feed the same decision
  context (category, priority) into the same O5 prompt (§14 "same generation prompt"), so there
  is no systematic V2 input-token penalty per generation. The real per-generation token
  difference is **routing-driven**: if Jev routes *more* tickets to `CUSTOM_REPLY` than Claude's
  baseline judgment did — or the confidence fallback fires often — V2's generation-call count,
  and therefore its tokens, could exceed expectations or even the baseline.
- Jev inference has its own cost (not Claude tokens, but not free). Jev returns its own
  `usage.input_tokens`/`usage.output_tokens` on every response, and its pricing is published
  ($0.042/1M input, $0.00/1M output), so the report includes a **measured** Jev token/cost line
  and a net-cost delta (§10, §12) — total-cost implications are a number, not a caveat.

---

## 4. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | The application SHALL process a frozen JSONL ticket dataset through V1 and V2 independently, in identical order. |
| FR-2 | For each ticket, both versions SHALL produce: category, priority, escalation decision (+ queue), response strategy, and a final reply text (templated or generated). |
| FR-3 | V1 SHALL perform all AI operations (O1–O5) via Claude API calls. |
| FR-4 | V2 SHALL perform O1–O4 via the Jev `DecisionProvider`, routing via deterministic code, and O5 via Claude only when strategy = `CUSTOM_REPLY`. |
| FR-5 | Every Claude call SHALL record actual `usage.input_tokens` and `usage.output_tokens` from the API response. Estimation is prohibited where API metadata exists. |
| FR-6 | Every Jev invocation SHALL be logged with each question's typed answer (choice/score/noul), per-option probabilities, derived confidence (where the primitive provides one — Noul does not), and **Jev's own `usage.input_tokens`/`usage.output_tokens` from the API response**, enabling a measured Jev cost line in the report. |
| FR-7 | The CLI SHALL support: `run baseline`, `run optimized`, `run comparison`, each writing a timestamped JSON results artifact. |
| FR-8 | `run comparison` SHALL compute and print: calls per component, input/output/total Claude tokens per version, absolute token savings, and percentage reduction — from the measured artifacts only. |
| FR-9 | The application SHALL score both versions' decisions (O1–O4) against gold labels in the dataset and print accuracy per operation per version. |
| FR-10 | The application SHALL report routing-agreement (% of tickets where V1 and V2 chose the same strategy) and flag every disagreement in the per-request log. |
| FR-11 | A `--verbose` flag SHALL emit per-request logs in the format of §12. |
| FR-12 | All Claude calls SHALL use `temperature=0` and a pinned model ID; the dataset SHALL be version-controlled; a run SHALL be reproducible from the command line with only an API key. |
| FR-13 | If the Jev API is unavailable, the application SHALL run V2 against the mock `DecisionProvider` (§16) and the report SHALL be clearly watermarked `JEV=MOCK — token MEASUREMENTS valid; token TOTALS/SAVINGS depend on mock routing and are NOT representative of live Jev; decision quality NOT representative of Jev`. Rationale: V2's Claude consumption is driven almost entirely by how many tickets the provider routes to `CUSTOM_REPLY` (+ fallbacks). In mock mode that routing is the mock's behavior, so the headline savings figure is a property of the mock, not of Jev — a mock that over-routes to templates manufactures savings; one that over-fallbacks erases them. Mock-mode savings figures SHALL be rendered with the suffix `(mock-routed)` everywhere they appear and MUST NOT be quoted as experimental results. |

Non-functional (POC-scope): single process, synchronous, sequential execution (determinism and
rate-limit friendliness beat speed here); total runtime target < 15 min for 100 tickets; retry
with exponential backoff on 429/5xx (max 3; a ticket that fails after retries is marked
`ERROR`). **Error reconciliation (FR-14):** because `run comparison` may compare two artifacts
produced at different times, V1 and V2 errors are independent events. The comparison SHALL
compute the excluded set as the **union of ERROR ticket_ids from both runs** and recompute both
versions' aggregates over the **intersection of successful tickets** — never over each run's own
success set. The report SHALL print the excluded ticket_ids and the effective N used for all
totals, savings, and accuracy figures. This preserves apples-to-apples even when errors differ
between runs.

**Comparison compatibility guard (FR-15):** before computing any comparison, `run comparison`
SHALL assert that the two run artifacts match on: dataset file hash, Claude model id, shared
prompt hashes (at minimum the O5 generation prompt), and `--limit`/ticket-id set. On any
mismatch it SHALL abort with exit code 2 and print the differing fields — no partial or
"best-effort" comparison is permitted. Each run's `summary.json` SHALL persist these fields to
make the assertion possible.

---

## 5. Baseline: Claude-Only Architecture (V1)

```
Ticket (JSONL record)
    │
    ▼
┌───────────────────────────────┐
│ Claude Call A — TRIAGE        │  decision-oriented (forced through a generative model)
│ classify + priority +         │
│ escalation + strategy         │
│ (one combined structured call)│
└───────────────┬───────────────┘
                ▼
        strategy == CUSTOM_REPLY ?
          │ no                │ yes
          ▼                   ▼
   App code fills      ┌─────────────────────────┐
   template /          │ Claude Call B — REPLY   │  generative
   auto-resolve        │ generate customer reply │
          │            └───────────┬─────────────┘
          ▼                        ▼
            Final output (routing record + reply)
```

**Design note (fairness):** V1 uses **one combined triage call** (not four separate calls for
O1–O4). This is the *strongest reasonable baseline* — splitting into four Claude calls would
inflate baseline tokens and manufacture savings. We deliberately compare V2 against the most
token-efficient sane Claude-only design. This decision must be stated in the final report.

### Claude Invocation A — Triage (every ticket, N = 100)

| Aspect | Specification |
|---|---|
| Purpose | Produce category, priority, escalation (+ queue), response strategy in one structured JSON response |
| Input | System prompt: role, the 6 category definitions, priority rubric, escalation rules, strategy rules, JSON output schema, 3 few-shot examples. User turn: ticket subject + body + customer metadata |
| Output | Strict JSON: `{"category": ..., "priority": ..., "escalate": bool, "queue": ..., "strategy": ...}` (enforced via tool-use / structured output; `max_tokens` capped at **256** — Stage 3 gate includes verifying the worst-case schema instance (longest queue string + all fields) fits with headroom, so truncation-triggered repair retries reflect model verbosity, not an artificially tight cap) |
| Nature | **Decision-oriented** — closed-set selection; generation capability is unused |
| Tokens captured | `usage.input_tokens`, `usage.output_tokens`, call latency, model id, per-ticket id |

### Claude Invocation B — Reply Generation (conditional: strategy = CUSTOM_REPLY)

| Aspect | Specification |
|---|---|
| Purpose | Generate the customer-facing reply for tickets that templates cannot serve |
| Input | System prompt: brand voice, constraints, structure requirements. User turn: ticket text + the triage decisions from Call A (category/priority) + relevant account facts from the mock data store |
| Output | Natural-language reply, `max_tokens` 500 |
| Nature | **Generative** — legitimately requires a frontier model in both architectures |
| Tokens captured | Same fields as Call A |

**Baseline token profile (structure, not numbers):**
`Total_V1 = Σ_N (A_in + A_out) + Σ_{custom} (B_in + B_out)` — Call A fires N times; Call B fires
once per `CUSTOM_REPLY` ticket as judged by Claude itself.

---

## 6. Optimized: Jev + Claude Architecture (V2)

```
Ticket (JSONL record)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Jev — SINGLE CALL per ticket (POST /v1/systemone)           │
│ one `state` (ticket text + customer metadata), FOUR         │
│ questions evaluated in parallel:                            │
│   q_intent    : Choice  — 6 categories (criteria map)       │
│   q_priority  : Score   — LOW…URGENT ordinal spectrum       │
│   q_escalate  : Noul    — yes/no escalation                 │
│   q_strategy  : Choice  — TEMPLATE / AUTO_RESOLVE / CUSTOM  │
│ (queue selection: Choice, asked only when q_escalate fires —│
│  resolved deterministically from intent where policy allows)│
└───────────────────────────┬─────────────────────────────────┘
                            ▼
     Deterministic application routing (pure code, zero AI)
      │ TEMPLATE_REPLY     │ AUTO_RESOLVE          │ CUSTOM_REPLY
      ▼                    ▼                       ▼
  Fill canned         Lookup order/account   ┌──────────────────────┐
  template            data store, fill       │ Claude — REPLY GEN   │  generative
  (0 Claude tokens)   template (0 tokens)    │ (same prompt shape   │
      │                    │                 │  as V1 Call B)       │
      ▼                    ▼                 └──────────┬───────────┘
            Final output (routing record + reply)
```

**One Jev call per ticket, four logical decisions.** The Jev API evaluates a `questions` map in
parallel against a single `state` in one POST — splitting O1–O4 into sequential calls would be
unfaithful to the API's design and would triple Jev input-token cost by resending the ticket
state. Counting convention everywhere in this spec and the report: **Jev Calls = N (one per
ticket); Jev Decisions = 4 × N (logical question results)** — both rows appear in §12 so neither
can be mistaken for the other.

**Primitive-per-operation mapping (not generic "typed decisions"):**

- **O1 intent → `Choice`** — unordered 6-option set; `criteria` is an option→description map
  (descriptions materially affect accuracy and are versioned with the prompts, §14).
- **O2 priority → `Score`** — LOW/MEDIUM/HIGH/URGENT is ordinal, and the docs are explicit:
  Choice for unordered sets, Score for a position on a spectrum. Score returns a float plus
  per-level probabilities + confidence; the app maps the float to the four levels by fixed,
  versioned cut-points.
- **O3 escalation → `Noul`** (yes/no; returns a `noul` probability, **no confidence field**);
  **queue → `Choice`**, asked only when escalation fires and only where deterministic policy
  (intent→queue table) doesn't already decide it.
- **O4 strategy → `Choice`** — 3 unordered strategies.

**Low-confidence fallback — quantity disambiguated.** Jev's `confidence` for a Choice is NOT the
top probability; it is derived as `(n·p_max − 1)/(n − 1)`, so a 0.70 confidence on the 6-option
intent Choice is a far higher bar than p_max = 0.70, and p_max's meaning shifts with option
count. Therefore the fallback gates are defined **per question, each naming its exact quantity**:

| Question | Gated quantity | Default threshold | Below threshold ⇒ |
|---|---|---|---|
| q_intent (Choice) | derived `confidence` | 0.50 | route CUSTOM_REPLY → Claude |
| q_strategy (Choice) | derived `confidence` | 0.60 | route CUSTOM_REPLY → Claude |
| q_escalate (Noul) | `noul` probability distance from 0.5 (|p − 0.5|) | 0.15 (i.e. unsure band 0.35–0.65) | escalate = true (conservative) |
| q_priority (Score) | — no gate (see asymmetry below) | — | — |

All thresholds are config values, tuned on a held-out slice in Stage 4 and frozen before the
measured runs (pre-registration discipline, §13). The report counts fallback firings per gate.

**Deliberate asymmetry — priority (Score) has no fallback.** Intent and strategy confidence gate
*routing*: a misroute changes which component answers the customer. Priority affects only queue
ordering metadata — a wrong priority never changes the reply the customer receives, and routing
to Claude would not improve the priority label anyway (V2's Claude is used for generation, not
re-decisioning). The escalation Noul gets a conservative unsure-band rule instead, because a
missed escalation has customer-visible consequences. The cost of the priority choice is fully
visible in §13's priority-accuracy metric; if measured priority accuracy is unacceptable,
extending the gate (e.g. unsure Score ⇒ bump one level and flag for human review) is a
pre-identified follow-up, not a hidden gap.

### Operation-by-operation disposition (required by Step 3)

| Op | V1 executor | V2 executor | Why this executor is appropriate — not token-motivated rationalization |
|----|------------|-------------|---|
| O1 Intent classification | Claude (Call A) | **Jev `Choice`** | Closed-set, 6-option classification with per-option probabilities — the canonical System-One decision task Jev is designed for. No text is generated; nothing generative is lost. |
| O2 Priority scoring | Claude (Call A) | **Jev `Score`** | Ordinal position on a LOW→URGENT spectrum — exactly the Score primitive's purpose (Choice is for unordered sets). A scoring decision, not reasoning-to-text. |
| O3 Escalation + queue | Claude (Call A) | **Jev `Noul`** (escalation) + **Jev `Choice`** (queue, only when policy table doesn't decide it) + deterministic policy overrides in code, e.g. "tier=ENTERPRISE ∧ URGENT ⇒ always escalate" | Yes/no and selection among predefined queues. Hard business rules belong in code, not in any model — V2 is honest about that too. |
| O4 Response strategy | Claude (Call A) | **Jev `Choice`** | 3-way routing decision over fixed strategies. This is *the* routing primitive from the hypothesis. |
| Template filling / data lookup | App code | **App code** | Deterministic in both versions. Never was an AI task; kept identical so it cannot confound the comparison. |
| O5 Reply generation | Claude (Call B) | **Claude** | Requires fluent, situation-specific natural language. Jev is non-generative by definition; this stays with the frontier model in both architectures. |

**Optimized token profile:**
`Total_V2_Claude = Σ_{custom∪fallback} (B_in + B_out)` — Claude fires only for `CUSTOM_REPLY`
tickets (as routed by Jev) plus fallbacks. Jev: **N calls** (1 per ticket), 4 × N logical
decisions, zero Claude tokens — but Jev reports its **own** `usage.input_tokens` /
`usage.output_tokens` on every response, which the harness captures and prices
($0.042 / 1M input, $0.00 / 1M output — jev-1.12 pricing, dated 2026-09; re-verify at run time)
so total cost is **measured, not caveated** (§10, §12).

### Jev integration contract — grounded in published API documentation

Jev's API is now publicly documented (endpoint `POST https://api.typesafe.ai/v1/systemone`,
`Authorization` bearer auth, official SDKs, 429/529 backoff semantics). The former assumptions
A1–A6 are resolved (table in §17). V2 codes against a thin adapter whose shape mirrors the real
request/response — one call, a questions map with per-primitive tagged types:

```python
class JevQuestion:                    # tagged union, one per primitive
    ...

@dataclass
class ChoiceQ(JevQuestion):
    criteria: dict[str, str]          # option → description map (max 255 options;
                                      # descriptions materially affect accuracy — versioned)

@dataclass
class ScoreQ(JevQuestion):
    spectrum: ...                     # ordinal scale definition per docs

@dataclass
class NoulQ(JevQuestion):
    question: str                     # yes/no

class DecisionProvider(Protocol):
    def evaluate(self,
                 state: str | dict,                    # ticket text + structured metadata
                 questions: dict[str, JevQuestion]     # evaluated in parallel, ONE call
                 ) -> JevResponse: ...

@dataclass
class JevResponse:
    answers: dict[str, ChoiceR | ScoreR | NoulR]
    usage: JevUsage                   # input_tokens, output_tokens — captured per call
    latency_ms: float
    provider: str                     # "jev" | "mock"

@dataclass
class ChoiceR:
    choice: str
    probabilities: dict[str, float]   # sums to 1
    confidence: float                 # derived: (n·p_max − 1)/(n − 1)

@dataclass
class ScoreR:
    score: float                      # position on spectrum (e.g. 1.86)
    probabilities: dict[str, float]   # per-level
    confidence: float

@dataclass
class NoulR:
    noul: float                       # P(yes); NO confidence field — threshold on |p − 0.5|
```

Implementation notes grounded in the docs: `state` may be a string or structured object/array
(no audio/video); English is primary (CJK accuracy is lower — our dataset is English-only, a
stated scope condition, §17); questions are defined inline per request — **zero-shot, no task
pre-registration or training**; retry/backoff on 429/529 mirrors the Claude client's policy.
The `MockDecisionProvider` implements the same `evaluate` contract (including fake `usage`
figures clearly zeroed or flagged) so the harness is identical in both modes.

---

## 7. Responsibility Matrix

| Responsibility | Jev | Claude | Deterministic code |
|---|:-:|:-:|:-:|
| Intent classification (V2) | ✅ | — | — |
| Priority scoring (V2) | ✅ | — | — |
| Escalation & strategy decisions (V2) | ✅ | — | — |
| Hard business-rule overrides | — | — | ✅ |
| Routing on decided strategy | — | — | ✅ |
| Template selection & variable filling | — | — | ✅ |
| Order/account data lookup (mock store) | — | — | ✅ |
| Custom reply generation (both versions) | — | ✅ | — |
| All AI ops in V1 (O1–O4 + O5) | — | ✅ | — |
| Token capture, aggregation, reporting | — | — | ✅ |
| Gold-label scoring & agreement analysis | — | — | ✅ |

---

## 8. Request Processing Flow

**V1 (per ticket):** read ticket → Claude Call A (triage JSON) → validate/parse (1 repair
retry on malformed JSON; retry tokens ARE counted — malformed structured output is a real cost
of using a generative model for decisions) → if strategy ∈ {TEMPLATE_REPLY, AUTO_RESOLVE}:
deterministic fill → else Claude Call B → emit result record with all token fields.

**V2 (per ticket):** read ticket → ONE Jev call: `evaluate(state, {q_intent: Choice, q_priority:
Score, q_escalate: Noul, q_strategy: Choice})` (+ queue Choice when needed) → capture Jev usage
tokens → apply rule overrides → apply per-question gates (§6: Choice gates on derived
`confidence`, Noul gate on |p − 0.5|) ⇒ low-confidence routing forces CUSTOM_REPLY / escalation
(flag `fallback=<gate>`) → route: template/auto-resolve (0 Claude tokens) or Claude reply
generation → emit result record.

Both flows write one JSON line per ticket to `results/<run_id>/requests.jsonl` and a run-level
summary to `results/<run_id>/summary.json`.

---

## 9. Test Dataset / Test Scenarios

`dataset/tickets.jsonl` — **100 synthetic tickets, frozen and committed to the repo** (generated
once, offline, before any experiment runs; never regenerated between runs).

Record schema:

```json
{
  "id": "T-042",
  "subject": "Charged twice for March invoice",
  "body": "...free text...",
  "customer": {"tier": "PRO", "account_age_days": 412, "prior_tickets": 3},
  "gold": {
    "category": "BILLING_DISPUTE",
    "priority": "HIGH",
    "escalate": true,
    "queue": "billing-agents",
    "strategy": "CUSTOM_REPLY"
  }
}
```

Composition (mirrors Step 4's scenario classes; exact counts committed with the dataset):

| Scenario class | ~Count | Purpose |
|---|---:|---|
| Simple template-resolvable (password reset, how-do-I) | 30 | Tests call-elimination mechanism |
| Auto-resolve via data lookup (order status) | 20 | Tests decision + deterministic completion |
| Clear generation-required (billing disputes, nuanced complaints) | 25 | Tests that generative work is preserved, not dodged |
| Ambiguous / borderline (vague wording, mixed signals) | 15 | Tests Jev confidence fallback & misrouting risk |
| Complex multi-issue (two intents in one ticket) | 10 | Stress case; gold label picks the dominant intent; expected to be hardest for both versions |

Gold labels are authored by a human (or human-reviewed) during dataset creation and define
ground truth for §13. Both versions consume the identical file in identical order — satisfying
Step 4's apples-to-apples mandate.

---

## 10. Token Instrumentation Requirements

**Source of truth:** the `usage` object on every Anthropic Messages API response
(`usage.input_tokens`, `usage.output_tokens`). The POC MUST NOT use client-side tokenizer
estimates when this metadata exists (FR-5). If a response lacks usage metadata (abnormal), the
ticket is marked `ERROR` per §4.

Captured per Claude call: run_id, version (V1/V2), ticket_id, call_role (TRIAGE/REPLY/REPAIR),
model_id, input_tokens, output_tokens, latency_ms, timestamp.
Captured per Jev call (one per ticket): run_id, ticket_id, per-question answers (choice/score/
noul + probabilities + derived confidence where applicable), gate outcomes, **Jev
usage.input_tokens / usage.output_tokens**, latency_ms, provider (jev|mock).

Run-level aggregates (computed, never hand-entered):

```
Baseline Copilot Model Tokens   = Σ baseline input + Σ baseline output
Optimized Copilot Model Tokens  = Σ optimized input + Σ optimized output
Token Savings            = Baseline − Optimized
Token Reduction %        = Token Savings / Baseline × 100

Jev Tokens (V2 only)     = Σ jev input + Σ jev output          (measured from API usage)
Jev Cost                 = jev input × $0.042/1M + jev output × $0.00/1M
Copilot Generation Cost  = N/A (subscription/prompt-accounted)
Net Cost Delta           = N/A (no token-based Copilot USD rate)
```

Copilot model-token savings and measured Jev dollar cost are reported as separate lines. The
report MUST NOT manufacture a Copilot token-priced dollar cost or net dollar delta.
Pricing constants live in config with their as-of date (jev-1.12, 2026-09) and are printed in
the report footer; stale pricing changes cost lines, never token lines.

Plus: Copilot model call counts per version, Jev call count (N) and logical decision count (4 × N),
requests processed, per-ticket handler attribution (which component resolved each ticket),
fallback-trigger count per gate, repair-retry count (V1), ERROR count, and — for comparisons —
the excluded ticket_id union and effective N (FR-14). **Negative savings are printed as
measured** — the harness has no floor at zero and no assumption of direction (Acceptance
Criterion 10).

Terminology note: **"Jev Calls" = API invocations (1 per ticket, N total); "Jev Decisions" =
logical question results (4 per call, 4 × N total).** The report prints both rows with these
exact labels so neither can be mistaken for the other.

---

## 11. CLI Requirements

Single entry point (Python, Typer): `python -m tokenpoc <command>`

| Command | Behavior |
|---|---|
| `run baseline [--limit N] [--verbose]` | Execute V1 over the dataset → `results/<run_id>/` |
| `run optimized [--limit N] [--verbose] [--jev-mode live\|mock] [--gate-intent 0.50] [--gate-strategy 0.60] [--gate-escalate-band 0.15]` | Execute V2 → `results/<run_id>/`. Per-question fallback gates per §6 (Choice gates read derived `confidence`, the Noul gate reads \|p − 0.5\|) |
| `run comparison [--baseline RUN] [--optimized RUN]` | Default: executes both fresh, then compares; or compares two prior run artifacts. Enforces the FR-15 compatibility guard (abort exit 2 on dataset-hash / model-id / prompt-hash / ticket-set mismatch) and FR-14 error-union reconciliation before any math. Prints §12 report + writes `comparison.json` |
| `report <run_id>` | Re-print a stored run's summary |
| `validate-dataset` | Schema-check tickets.jsonl + gold-label completeness |

Config via env/.env: `MODEL_PROVIDER=github-copilot`, `COPILOT_MODEL=auto`,
`JEV_API_KEY` (if live), `JEV_MODE`. Copilot authentication is provided by `copilot login`.
Exit codes: 0 success, 1 run error,
2 config or comparison-compatibility error (FR-15) — scriptable in CI.

---

## 12. Example Command-Prompt Output

**All numbers below are ILLUSTRATIVE PLACEHOLDERS (shown as X/•) — the real report prints only
measured values.** The template:

```
TOKEN CONSUMPTION COMPARISON          run: 2026-10-14T10:32Z   model: claude-sonnet-4-5
  dataset: tickets.jsonl (100)        jev: LIVE | MOCK*        temperature: 0
===================================================================

                              Claude Only      Jev + Claude
Requests Processed                    100               100
Claude Calls                            •                 •
  └─ triage calls                       •                 0
  └─ reply-generation calls             •                 •
  └─ JSON-repair retries                •                 0
Jev Calls (1/ticket)                    0                 •
Jev Decisions (4/call)                  0                 •
Fallback firings (intent/strategy/esc)  —             •/•/•

Claude Input Tokens                     •                 •
Claude Output Tokens                    •                 •
-------------------------------------------------------------------
Total Claude Tokens                     •                 •

Tokens Saved                                              •   [suffix "(mock-routed)" if JEV=MOCK]
Token Reduction                                           •.••%
   (sign as measured — may be negative)

COST (measured; pricing as-of in footer)
Jev Tokens (in/out)                     —             • / •
Jev Cost                                —            $•.••••
Claude Cost                          $•.••            $•.••
Total Cost                           $•.••            $•.••
Net Cost Delta                                       $•.••  (sign as measured)

QUALITY GUARDRAIL                 Claude Only      Jev + Claude
Category accuracy (vs gold)             •.•%              •.•%
Priority accuracy                       •.•%              •.•%
Escalation accuracy †                   •.•%              •.•%
Strategy accuracy †                     •.•%              •.•%
Task completion                         •.•%              •.•%
Strategy agreement V1↔V2                        •.•%  (• disagreements, listed below)
Quality gate (§13)                         PASS | FAIL   [suffix "(mock — apparatus check only)" if JEV=MOCK]
===================================================================
Pricing: jev-1.12 $0.042/1M in, $0.00/1M out (2026-09); claude: <pinned model rates, as-of date>
* JEV=MOCK runs are watermarked: token measurements valid; token totals/savings AND cost lines
  depend on mock routing — rendered as "N (mock-routed)" — and are NOT representative of live
  Jev; decision quality not representative of Jev.
† In V2, escalation (Noul) and strategy (Choice) are answered in the same Jev call against the
  same state — these two columns are correlated, not independent evidence.
```

Per-request verbose log (template):

```
Request T-018  [password reset]
  Jev: intent=PASSWORD_RESET (conf 0.88) · priority score 0.9→LOW · noul(escalate)=0.08
       strategy=TEMPLATE_REPLY (conf 0.82)        [1 call, 4 decisions, jev tokens: •/•]
  Handled by: Jev → template engine
  Claude invoked: No          Claude tokens: 0

Request T-019  [billing dispute]
  Jev: intent=BILLING_DISPUTE (conf 0.79) · priority score 2.9→HIGH · noul(escalate)=0.91
       → queue Choice: billing-agents · strategy=CUSTOM_REPLY (conf 0.84)
  Handled by: Jev → Claude
  Claude invoked: Yes         Input: •••   Output: •••

Request T-057  [ambiguous]
  Jev: intent=GENERAL_INQUIRY (conf 0.45 < gate 0.50) → FALLBACK CUSTOM_REPLY
  Handled by: Jev (low confidence) → Claude
  Claude invoked: Yes         Input: •••   Output: •••
```

---

## 13. Quality and Accuracy Measurement

Token reduction with broken quality is a failed experiment. Three layers:

1. **Decision accuracy vs gold labels (objective, automatic).** For both versions, per-operation
   accuracy on category, priority, escalation, strategy — plus a confusion matrix per operation
   in `comparison.json`. This directly answers "is Jev's decisioning as good as Claude's?"
2. **Routing agreement & consequence analysis.** % of tickets where V1 and V2 chose the same
   strategy; every disagreement listed with both choices and the gold label (so a disagreement
   where *V2* matches gold is credited correctly, not assumed to be V2's error).
3. **Task completion & reply acceptability.**
   - *Completion (objective):* ticket produced a valid routing record + non-empty reply with all
     template variables resolved.
   - *Reply quality (bounded subjectivity):* for `CUSTOM_REPLY` tickets, both versions call the
     same Claude prompt, so quality should be near-identical; differences arise from routing. The
     primary quality signal is therefore *routing correctness* (did a ticket needing a custom
     reply get a template?). **Optional extension:** LLM-as-judge pairwise scoring of replies —
     explicitly labeled optional, and its judge tokens are reported separately, never mixed into
     the comparison totals.

**Pre-registered quality gate (declared before running, to prevent post-hoc rationalization):**
the headline token-reduction claim is only reported as "achieved at acceptable quality" if V2's
strategy accuracy is within **5 percentage points** of V1's and completion = 100%. Otherwise the
report leads with the quality regression. The 5-pt threshold is an experiment-design parameter,
adjustable *before* runs, never after. **In JEV=MOCK mode the quality-gate verdict validates the
gate's wiring, not Jev's decision quality** — the verdict line is rendered as
`PASS/FAIL (mock — apparatus check only)` and carries the FR-13 watermark, so a mock-mode "PASS"
cannot be quoted as evidence about Jev.

---

## 14. Comparison Methodology

- **Identical frozen workload**, identical order, both versions (Step 4). When comparing
  independently produced run artifacts, the FR-15 compatibility guard (same dataset hash, model
  id, shared prompt hashes, ticket set) must pass, and FR-14 recomputes both aggregates over the
  intersection of successful tickets (union of ERROR ticket_ids excluded from both sides).
- **temperature=0**, pinned model ID, pinned prompt text (prompts are versioned files; any
  prompt edit invalidates prior runs — run_id embeds a prompt-hash).
- **Strong baseline:** V1 uses one combined triage call (§5) — savings are measured against the
  efficient Claude-only design, not a strawman.
- **Same generation prompt** in both versions for O5, so generation tokens differ only through
  routing differences, which are themselves reported.
- **3 repetitions** of the full comparison; report mean and min–max spread of Token Reduction %
  (generation output length varies slightly even at temperature 0). Headline = mean.
- **Direction-agnostic reporting:** the harness computes savings as a signed number. If V2
  consumes more Claude tokens (e.g., excessive fallbacks), that is the result.
- **Separation of measured vs. assumed:** the report's footer lists active assumptions
  (Jev mock vs live, thresholds) on every output, so no artifact can be quoted out of context.

---

## 15. Acceptance Criteria

The POC is complete when all of the following are demonstrated:

1. ✅ Both architectures process the identical 100-ticket frozen dataset; cross-run comparisons pass the FR-15 compatibility guard and apply FR-14 error-union reconciliation (aggregates computed over the intersection of successful tickets, excluded ids printed).
2. ✅ All Claude token figures come from actual API `usage` metadata (verifiable in raw per-call logs).
3. ✅ Baseline and optimized Claude calls are separately identifiable (version + call_role tags on every record).
4. ✅ Every Jev decision is observable in logs with its typed answer (choice/score/noul), per-option probabilities, and derived confidence where the primitive provides one (Choice/Score yes; Noul logs its `noul` probability and the |p − 0.5| gate outcome instead).
5. ✅ Total Claude input/output tokens computed for both versions.
6. ✅ Absolute token savings computed (signed).
7. ✅ Percentage token reduction computed (signed).
8. ✅ Quality deltas measured: per-operation accuracy, agreement, completion; quality gate verdict printed (watermarked per §13 in JEV=MOCK mode).
9. ✅ `python -m tokenpoc run comparison` reproduces the full experiment from a clean checkout + API keys.
10. ✅ No directional assumption anywhere in code or report copy: the harness prints measured results, including negative savings, and example outputs are watermarked illustrative.
11. ✅ Jev token usage captured from the API `usage` object per call and priced at the configured rates; Jev cost, Claude cost per version, and the signed net-cost delta computed and printed with the pricing as-of dates in the report footer.

---

## 16. Suggested Implementation Components

| Component | Choice | Justification |
|---|---|---|
| Language/runtime | Python 3.11+ | Fastest POC velocity; first-class Anthropic SDK |
| CLI framework | Typer | Typed commands, auto `--help`, minimal boilerplate |
| Claude SDK | `anthropic` (official) | Native `usage` metadata on every response; structured output via tool-use |
| Jev adapter | `DecisionProvider.evaluate()` protocol (§6) mirroring the documented `/v1/systemone` request/response (tagged Choice/Score/Noul types, usage capture), with `JevProvider` (live) and `MockDecisionProvider` | Single seam for live/mock swap; shape is grounded in published docs, so Stage 6 is a smoke test, not discovery |
| Mock decision provider | Deterministic rules + keyword/regex scoring over the dataset's feature space, with injectable noise rate for fallback testing | Lets the entire harness, instrumentation, and report be built and verified before Jev access exists; always watermarked (FR-13) — its routing drives V2 Claude totals, so mock-mode savings are apparatus-verification numbers only |
| Data | JSONL files + `pydantic` models | Schema validation of tickets, gold labels, results |
| Results store | `results/<run_id>/{requests.jsonl, summary.json, comparison.json}` | Plain files; diffable; feeds `report` command |
| Report rendering | `rich` tables | The §12 report with zero UI work |
| Mock order/account store | In-repo JSON fixture | Deterministic AUTO_RESOLVE lookups |
| Testing | `pytest`: unit (aggregation math incl. negative savings, FR-14 error-union reconciliation over mismatched error sets, FR-15 compatibility-guard abort paths, template engine, threshold logic), golden-file test for report formatting incl. mock-routed watermarking, integration test with both AI providers mocked | Token math must be provably correct — it *is* the experiment |

Project layout:

```
tokenpoc/
  cli.py                # Typer app: run/report/validate-dataset
  pipeline_v1.py        # Claude-only flow
  pipeline_v2.py        # Jev + Claude flow
  providers/claude.py   # calls + usage capture
  providers/jev.py      # documented /v1/systemone adapter (Choice/Score/Noul + usage capture)
  providers/mock_jev.py # watermark-enforced mock
  routing.py            # deterministic rules, templates, data lookup
  metrics.py            # aggregation, savings math, quality scoring
  report.py             # rich-rendered comparison
  dataset/tickets.jsonl # frozen, gold-labeled
  prompts/              # versioned prompt files (hash → run_id)
  tests/
```

---

## 17. Risks, Assumptions, and Limitations

**Formerly open assumptions A1–A6 — now RESOLVED from published Jev documentation:**

| # | Was assumed | Resolution (from public docs) |
|---|---|---|
| A1 | Closed label set | ✅ `Choice.criteria` is an option→description map, max 255 options |
| A2 | Probabilities/confidence | ✅ Choice returns `choice`, `probabilities` (sum to 1), derived `confidence` = (n·p_max−1)/(n−1); Score returns float + per-level probabilities + confidence; **Noul returns `noul` probability only — no confidence field** |
| A3 | Input modality | ✅ `state` = string or structured object/array; no audio/video; English primary, CJK lower accuracy (our dataset is English-only) |
| A4 | Registration vs zero-shot | ✅ Zero-shot — questions defined inline per request; no pre-registration/training |
| A5 | Auth/endpoint | ✅ `POST https://api.typesafe.ai/v1/systemone`, bearer auth, official SDKs, 429/529 + backoff |
| A6 | Pricing | ✅ $0.042 / 1M input, $0.00 / 1M output (jev-1.12, 2026-09) — enables the measured cost lines in §10/§12 |

Residual verification (not assumptions): a 5-ticket live smoke test (Stage 6) confirms the
adapter matches the documented contract, and pricing/doc claims are re-checked at run time
(docs can change between spec and execution; the as-of dates print in the report footer).

**Risks:**

| Risk | Impact | Mitigation |
|---|---|---|
| Jev decision quality below Claude's on this domain | Savings achieved at unacceptable accuracy cost | Gold-label scoring + pre-registered quality gate (§13); result reported either way |
| Jev routes too many tickets to CUSTOM_REPLY (or fallback threshold too conservative) | Savings shrink or go negative | Signed reporting; fallback counter; threshold is a visible config, sensitivity-checkable |
| Mock provider overstates/understates Jev quality **and mock routing drives V2's Claude totals, so mock-mode savings figures are a property of the mock, not Jev** | Misleading quality AND savings conclusions | Hard watermark + "(mock-routed)" suffix on all mock-mode savings figures (FR-13); mock results never quoted as Jev results |
| Baseline design choices skew the comparison | Manufactured savings | Strongest-sane-baseline rule (§5) documented in the report itself |
| Non-determinism in generation lengths | Noisy reduction % | temperature 0 + 3 repetitions + spread reporting |
| Synthetic dataset unrepresentative of production traffic mix | External validity limited | Stated limitation; composition table published with results; rerunnable on any JSONL in the same schema |

**Limitations (stated, not hidden):** (1) Token reduction and cost reduction are reported as
**separate measured lines** — Jev's own token usage is captured per call and priced at published
rates, with a net-cost delta in the report (§10, §12); the remaining caveat is only that pricing
constants carry an as-of date. (2) 100 tickets demonstrates the mechanism; statistical
confidence for production claims needs larger, real-traffic datasets. (3) Results are specific
to this use case's decision/generation mix; the ratio is the dominant variable in any
extrapolation. (4) Dataset is English-only, matching Jev's primary-language strength — results
do not generalize to CJK or mixed-language traffic.

---

## 18. Implementation Plan

Staged gates — each stage has a runnable verification before the next begins:

| Stage | Deliverable | Gate (evidence required) |
|---|---|---|
| **1. Harness & dataset** (≈1 day) | Repo scaffold, pydantic schemas, frozen gold-labeled dataset, `validate-dataset` | Dataset validates; composition counts match §9 |
| **2. Instrumentation core** (≈1 day) | `metrics.py`, results artifacts, report renderer, FR-14/FR-15 comparison guards | pytest green on savings math incl. negative-savings case, error-union reconciliation, and compatibility-guard abort; golden-file report test incl. mock-routed watermark |
| **3. V1 pipeline** (≈1 day) | Claude triage + generation with usage capture, JSON-repair retry | `run baseline --limit 10` produces real usage-metadata tokens; raw per-call log inspected |
| **4. Mock Jev + V2 pipeline** (≈1–2 days) | `DecisionProvider`, mock provider, routing/templates, fallback logic | `run optimized --limit 10 --jev-mode mock` runs end-to-end, watermarked |
| **5. Full mock-mode comparison** (≈0.5 day) | `run comparison` over all 100 × 3 reps | Report prints measured numbers + quality tables; AC-1→11 checklist pass (quality AND savings/cost figures watermarked MOCK/mock-routed, quality-gate verdict rendered "(mock — apparatus check only)" — this stage proves the apparatus, not the hypothesis) |
| **6. Jev live smoke test** (small, external only for API access/key) | `JevProvider` implemented against the documented `/v1/systemone` contract | 5-ticket live run: response shapes match adapter types (Choice/Score/Noul, usage fields present); 429/529 backoff exercised or stubbed |
| **7. Live experiment & writeup** (≈1 day) | 3 full live comparisons; final results document separating measured results from assumptions | All acceptance criteria met with JEV=LIVE |

Critical path risk: Stage 6 needs only an API key, since the contract is documented — it is a
smoke test, not discovery. Stages 1–5 still prove the entire experiment apparatus correct
(including the no-predetermined-outcome property) before any live Jev spend.

---

*End of specification. All example figures herein are illustrative; no token-reduction
percentage is claimed until measured per §14.*
