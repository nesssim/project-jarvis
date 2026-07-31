# Suggestions for Schedule Updates

> **Decision deferred (2026-07-31).** The bulk of this proposal — adopting a
> cloud LLM as the default provider, dropping Phase 6 (robotics), re-spreading
> Phase 7, and re-estimating every phase — is a major planning restructure and
> is **not implemented**. Blockers: `create_llm_client()` in
> `services/orchestrator/src/orchestrator/clients/llm.py` raises
> `NotImplementedError` for `groq`/`gemini` and has no `openrouter`/`cloudflare`
> case; `LLMConfig.provider` in `shared/src/shared/config.py` is typed as
> `Literal["ollama", "groq", "gemini"]` and the required `OpenRouterConfig` /
> `CloudflareConfig` models do not exist. Re-evaluate after a Groq client is
> implemented.
>
> **Partially adopted:** placeholder env stubs `OPENROUTER_API_KEY`,
> `CLOUDFLARE_API_KEY`, `CLOUDFLARE_ACCOUNT_ID` were added to `.env.example`
> (harmless, self-contained). No `settings.yaml` provider routing was changed.
>
> ---
>
> Based on architectural review of `schedule.md` (2026-07-30).  
> You already have API keys for: **Groq**, **OpenRouter**, **Cloudflare Workers AI**.

---

## 1. Adopt Cloud LLM as Primary — Changes Everything

**Current assumption:** Ollama + Qwen2.5-8B on CPU-only laptop.
**Reality:** 8B model on CPU gives 2-5s first token (warm), 8-20s (cold). Voice-to-voice target of <1.5s is physically impossible.

**You have three cloud providers already keyed.** This single change transforms the schedule:

| Provider | Free Tier | Typical TTFT | Best For |
|----------|-----------|-------------|----------|
| **Groq** | 30 req/min, 1440/day | <500ms | Primary reasoning (Llama 3.3-70B) |
| **OpenRouter** | Pay-as-you-go, many models | 500ms-2s | Fallback, diverse model selection |
| **Cloudflare Workers AI** | 10k req/day free | 1-3s | Offline-capable edge, good for simple queries |

**What to update in the schedule:**

- **Phase 1** drops from 25h → 15h (no Ollama Docker setup, no CPU optimization, no cold-start warmup)
- **Phase 3** drops from 80h → 50h (latency targets trivially achievable, no CPU yak-shaving)
- **Phase 5** works on first try (70B models are actually good at function calling — 7-8B models are unreliable)
- First "feels conversational" milestone moves from week 16 → **week 10-12**

**Trade-off:** Internet required. Privacy boundary: Groq/OpenRouter see your text (not audio if STT stays local). For many use cases this is acceptable; keep Ollama as offline fallback.

**Suggested model routing (add to settings.yaml):**

```yaml
llm:
  provider: "groq"              # default
  router:
    simple: "cloudflare"        # greetings, short queries → fast/cheap
    complex: "groq"             # reasoning, tool calls → smart
    fallback: "ollama"          # offline mode → local
```

---

## 2. Re-Estimate Phase 3 (Real-Time Streaming)

**Scheduled:** 70-90h, 5.5 weeks.
**Reality with cloud LLM:** ~50-60h foundational work — testing + tuning still needed but no CPU firefighting.

| Task | Current (h) | Cloud-LLM (h) | Why |
|------|-------------|---------------|-----|
| 3.1 FSM | 10 | 15 | Test matrix is real regardless |
| 3.2 Wake word | 5 | 5 | Unchanged |
| 3.3 Chunked TTS | 6 | 6 | Unchanged |
| 3.4 Barge-in | 6 | 8 | Still hard UX problem |
| 3.5 Concurrent I/O | 6 | 6 | Unchanged |
| 3.6 Cold-start warmup | 2 | **0** | Not needed with cloud LLM |
| 3.7-3.12 (prompt/sliding/etc) | 14.5 | 10 | Less tuning needed |
| 3.13 Latency tests | 4 | 2 | Target is easy to hit |
| 3.14 Integration tests | 6 | 12 | Still need thorough coverage |
| 3.15-3.20 (tuning, CLI) | 18 | 12 | Less tuning iteration |
| CI debugging (missing) | 0 | 8 | Still need this |
| **Total** | **75.5** | **~84** | Similar hours, but far lower risk |

**The key difference:** Without cloud LLM, Phase 3 is a desperate optimization sprint against physics. With cloud LLM, it's a well-scoped feature build. Same hours, completely different stress level.

**Recommendation:** Split Phase 3 into 3a (core FSM + pipeline, ~50h) and 3b (barge-in + polish, ~30h) with a milestone in between.

---

## 3. Defer Phase 6 (Robotics) Entirely

**Scheduled:** 55-70h. **Realistic:** 120-180h.

**Why it's not ready:**
- ROS2 learning curve is 15-20h for someone who hasn't used it
- Dockerizing ROS2 is painful (DDS multicast through containers)
- Safety-critical code needs exhaustive testing
- You don't have a robot yet (presumably)

**Recommendation:** Move Phase 6 to a separate "v2" milestone. Implement the **ReAct agentic loop** (20-30h) as part of Phase 5 — it's valuable on its own and has nothing to do with robots.

**Savings:** 90-150h removed from the critical path. This alone drops total project from ~42 weeks → ~30 weeks.

---

## 4. Start Phase 7 Deployment Work Early

**Scheduled:** Weeks 21-27 (after everything else).  
**Better:** Spread across weeks 4-16 as parallel low-effort tasks.

| Task | Start Week | Hours | Dependency |
|------|-----------|-------|------------|
| Docker hardening | 4 | 4 | None |
| Production compose | 5 | 3 | None |
| Auth layer | 7 | 4 | Phase 2 WS auth patterns |
| Prometheus metrics | 6 | 4 | None |
| Structured logging audit | 4 | 2 | Already structlog |
| Redis persistence | 5 | 2 | None |
| systemd service | 12 | 2 | Only needs running stack |
| Health monitor | 13 | 3 | Any service running |

**Savings:** Removes 6 weeks of end-of-project crunch. Calendar passes same total hours but the feeling of progress is much better.

---

## 5. Add Buffer Weeks

**Current:** Zero buffer. **Need:** 3-4 explicit buffer weeks.

| After Phase | Buffer | Purpose |
|-------------|--------|---------|
| Phase 2 | 1 wk | Integration debugging, real-life catch-up |
| Phase 3 | 1 wk | Latency validation, UX tuning |
| Phase 5 | 1 wk | Agentic integration testing |
| Final | 1 wk | Full system E2E, docs, polish |

---

## 6. What to Update in the Config & Code

### Add OpenRouter + Cloudflare to settings.yaml

```yaml
llm:
  provider: "groq"  # default
  ollama:
    url: "http://ollama:11434"
    model: "qwen2.5:8b"
    keep_alive: -1
  groq:
    api_key: "${GROQ_API_KEY}"
    model: "llama-3.3-70b-versatile"
  openrouter:
    api_key: "${OPENROUTER_API_KEY}"
    model: "mistralai/mixtral-8x22b-instruct"  # or any OpenRouter model
    base_url: "https://openrouter.ai/api/v1"
  cloudflare:
    api_key: "${CLOUDFLARE_API_KEY}"
    account_id: "${CLOUDFLARE_ACCOUNT_ID}"
    model: "@cf/meta/llama-3.1-8b-instruct"
    base_url: "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"
  router:
    enabled: false  # Phase 3+ feature
    simple_provider: "cloudflare"
    complex_provider: "groq"
    fallback_provider: "ollama"
```

### Add to .env.example

```env
# --- Cloud LLM Providers (you have keys) ---
OPENROUTER_API_KEY=
CLOUDFLARE_API_KEY=
CLOUDFLARE_ACCOUNT_ID=
```

### Add to shared/config.py `LLMConfig`

The `provider` Literal needs `"openrouter"` and `"cloudflare"` added. New config models `OpenRouterConfig` and `CloudflareConfig` needed.

---

## 7. Recommended Realistic Schedule

| Phase | Original (h) | Revised (h) | Original (wk) | Revised (wk) |
|-------|-------------|-------------|---------------|--------------|
| Phase 0 | 40 | 40 | 2.5 | 2.5 |
| Phase 0.5 | 20 | 20 | 1.5 | 1.5 |
| Phase 1 | 25 | 15 | 1.5 | 1 |
| Phase 2 | 40 | 40 | 2.5 | 2.5 |
| Phase 2.5 | 35 | 35 | 2.5 | 2.5 |
| Phase 3 | 80 | 84 | 5.5 | 5.5 |
| Phase 4 | 40 | 40 | 2.5 | 2.5 |
| Phase 5 | 35 | 50 | 2.5 | 3.5 |
| Phase 6 | 60 | **0** | 4.0 | **0** |
| Phase 7 | 30 | 30 | 2.0 | 2.0 |
| Buffer | 0 | 20 | 0 | 2 |
| **Total** | **405** | **~374** | **27** | **~25** |

**Key differences from original:**
- Phase 6 removed entirely (robotics deferred to v2, ReAct folded into Phase 5)
- Phase 1 faster (no Ollama optimization, Groq/Cloudflare from day one)
- Phase 5 larger (ReAct agentic loop added)
- Buffer weeks added (previously zero — unrealistic for solo project)
- Phase 7 shifted left (weeks 4-16 instead of 21-27)
- **Result: conversational assistant by week 10-12, full system by week 25**

---

## 8. Immediate Next Steps (Do This Week)

1. **Add cloud provider configs** — OpenRouter + Cloudflare to `settings.yaml`, `.env.example`, and `shared/config.py`
2. **Implement Groq client** — pattern already exists in `llm.py`, `case "groq"` raises `NotImplementedError`. Implement streaming OpenAI-compatible chat completions (Groq API is OpenAI-compatible). Should be ~4h.
3. **Set default provider to Groq** — one line change `config/settings.yaml: provider: "groq"`
4. **Keep Ollama as fallback** — works unchanged. Revert to it when offline.
5. **Drop Phase 6 from schedule** — move to `suggestions_for_updates_in_schedule.md` as "v2 deferred"
6. **Respread Phase 7 tasks** into weeks 4-16 on the work plan
7. **Add 3-4 buffer weeks** to the timeline at bottom of schedule.md

---

*This document captures the key changes. Update `schedule.md` and `jarvis_blueprint.md` when you decide which recommendations to adopt.*
