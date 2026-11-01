# Model Context and Token Budgeting

## Runtime provider

AI Service and the background worker compose the exact registered provider/model
pair `ollama` / `llama3.2:3b`. Application composition has no OpenAI or other
paid-provider fallback. The Ollama adapter sends the two assembled chat messages
and, when present, the Pydantic JSON schema to `/api/chat`. Automated tests use
in-process HTTP fakes and do not contact Ollama.

The local Ollama version and installed tag names were reported by the user from
their Windows PowerShell. The repository does not pin the local model digest.
Ollama's published `llama3.2:3b` metadata reports an architecture context of
131,072 tokens, but that is not the effective `num_ctx` configured for the
running Ollama process. The application's effective limit is therefore unknown.
The model's local output ceiling is also not configured or verified.

## Finite output contracts (not a token budget)

Agent output contracts now impose finite item and string-length limits:

| Output | Maximums |
| --- | --- |
| Summary | 8,000 characters; 20 topics of at most 120 characters |
| Tasks | 100 tasks; title 300, description 2,000, assignee 200 characters |
| Decisions | 100 decisions; statement 1,000, context 2,000, 50 participants of at most 200 characters |
| Follow-ups | 20 drafts; subject 200, body HTML 8,000, 20 recipients; name 200 and email 254 characters |
| Insights | 50 insights; title 300 and description 2,000 characters |
| Cross-meeting answer | Existing 8,000-character answer; at most 100 evidence IDs of at most 64 characters |

These are application output-contract caps intended to bound response shape and
reject oversized results consistently. They are not token counts, do not establish
that a complete valid response fits a chosen output reserve, and do not authorize
generation. In particular, character length cannot be substituted for tokenizer
accounting. An explicit `num_predict` policy still requires product acceptance of
the per-operation response limits and a verified model/runtime budget.

The initial caps allow substantial per-meeting material while limiting pathological
collections and very long fields. If a generated result exceeds a cap, validation
rejects that operation; the application does not truncate it. Revisit these limits
using real product usage before treating them as durable product guarantees.

## Budget status and enforcement

`llm.token_budget.TokenBudgetService` has a per-agent policy interface for
summary, task, decision, follow-up, and insight requests. Its policy records
require output reserves and safety margins. The request counter interface must
count the complete provider request, including the rendered Ollama chat template,
message framing, transcript JSON/metadata, structured-output schema effects, and
any other request context.

No production request counter is registered. No character count, guessed ratio,
or unrelated tokenizer is used. The registry distinguishes the published model
architecture limit from the unverified runtime context, tokenizer, and output
limit. Consequently every real Ollama request currently assesses as
`unverified` and `OllamaModelProvider` rejects it **before making an HTTP call**.
The assessment never labels an unverified request as within budget. Once verified,
the adapter will pass the assessed context limit as Ollama `num_ctx` and the
per-agent output reserve as `num_predict`, so generation cannot silently use a
different context default or unlimited output. This is a deliberate enforcement
block, not a claim that token budgeting is complete.

No transcript is truncated, reordered, chunked, or discarded. Hierarchical
chunking is outside this block.

## Non-generation prompt rendering evidence

Ollama 0.40.12 source defines `/api/chat` `_debug_render_only` and returns the
rendered template before invoking model completion. It can be used locally with
the exact application system/user messages and JSON Schema to verify template
rendering without generation. The rendered prompt and a vocabulary-only tokenizer
still require parity validation against the exact installed model blob and the
Ollama `b11901` runtime. No local render was claimed from this development
environment, which cannot access the user's Ollama endpoint.

Run the local, non-generation probe from the repository root with:

```powershell
& .\.venv\Scripts\python.exe backend\scripts\ollama_prompt_render_check.py
```

It requires Ollama 0.40.12 and the locally reported model ID, uses synthetic
transcript text with the actual five agent request builders plus the cross-meeting
builder, and prints only rendered-prompt hashes and character lengths. It does
not send `num_ctx` or `num_predict`, because neither is verified. The debug route
may load the model into Ollama while rendering; no completion is requested.

## Evidence required to enable generation

Before registering a production counter and effective limit, verify the exact
installed Ollama model digest, actual runtime `num_ctx`, and model-specific
tokenizer. The counter must count the same rendered chat request and structured
output mode sent by the adapter. Then define and test per-agent output reserves
and safety margins against a verified model output ceiling. Until all of those
inputs exist, generation remains blocked by the budget gate.
