# Design Write-up

## Agent design

I started with the obvious single-feed agents and worked up to the cross-feed ones.

**account_intelligence** was the first agent I got working end-to-end. It listens on the market feed for `expansion_announcement` and `regulatory_funding` events, calls the LLM once to extract the account ID and estimate the deal size, and writes the result. The blast class is always `medium` because even a soft external signal implies eventual contact — I didn't want the system auto-acting on that without a rep in the loop.

**sales_continuity** turned out to be simpler than I expected — no LLM needed at all. When an `owner_changed` event fires I just check whether the previous owner is departing (tracked in a set) and if so emit a coverage-gap action. The handoff brief is a template, not an LLM call. I initially wired LLM in for the brief but cut it because the output was inconsistent and the template does the job.

**fastflow_quote** has two paths. Consumables (v1) are a pure catalogue lookup — zero LLM, emitted autonomously. Capital equipment (v2) goes through the LLM once to parse the RFQ and configure the quote. I drew the line there because capital quotes have actual financial risk; consumables don't.

**cross_sell_engine** uses a hard-coded affinity table rather than LLM-driven matching. The reason: affinity is a product-domain decision that doesn't change per event — it's stable enough to encode. I call the LLM only for accounts where the estimated cross-sell value is over €500K because those need a personalised brief; smaller ones get a template rationale.

**buyer_movement** is where the LLM earns its token budget. Executive changes are genuinely ambiguous — a CFO departure at an NHS trust could mean a budget freeze or a green-field restart depending on who's coming in. The LLM classifies it as threat or opportunity and produces recommended outreach. High blast if external action is recommended.

**deal_velocity** was the trickiest to tune. The 30-day stall threshold is a business judgement call, not a technical one — I hardcoded it as a named constant so it's obvious to whoever maintains this. The LLM generates the unstick action (exec escalation, discount trigger, etc.) based on deal stage and competitor activity, but the stall detection itself is just arithmetic.

**supply_delivery** is mostly rule-based for the feasibility check — I calculate whether a committed delivery date can still be met given the updated lead time. The LLM only drafts the customer communication if the answer is "no". That separation keeps costs down and the critical decision auditable without inspecting an LLM response.

**data_quality** is fully rules-based, no LLM at all. Four checks: duplicate accounts, stale contacts (>90 days no activity), mislabelled stage (closed-won with no contract field), orphaned rep (owner not in territory table). These are deterministic enough that adding LLM would just introduce variance. All four fire as `act` — they're safe to auto-fix.

**correlator** runs in the background and is the part I'm most uncertain about. It polls WorldState every 30 seconds looking for accounts with multiple overlapping risk signals. When it finds a compound pattern it calls the LLM to synthesise them into a single recommended escalation. I went `high` blast on all correlator actions because by the time three signals overlap on one account, a manager definitely needs to know.

---

## Prompt strategy

I kept prompts short. Each agent gets only the fields it actually needs — not the full WorldState. This was partly a cost decision and partly because I found the LLM would hallucinate plausible-but-wrong values when given too much irrelevant context.

The pattern I settled on:

```
[system]  You are <specific role>. Return JSON: { schema }.
          Use only what's in the event. If uncertain, set confidence below 0.5.
[user]    <event payload>
```

All agents request `json_mode=True`. The LLM client falls back to prompt-based JSON extraction for models that don't support `response_format=json_object` (the Gemma models on Groq don't). I added `_extract_json()` after hitting that the first time.

One thing I changed during development: I stopped including the account's full opportunity list in the prompt for `buyer_movement`. It was pushing the system message over 2K tokens and the model wasn't using the opportunity data anyway. Stripping it to just the account name, territory, and incumbent contacts made the responses noticeably more consistent.

---

## Cost-awareness

The main lever is `cost_router.py`. Rather than passing every event to the LLM and letting the model decide what's interesting, I maintain two blocklists:

- ~20 routine CRM types (`activity_logged`, `stage_tick`, `task_completed`, etc.) — handled by rules or ignored
- ~5 routine supply types (`inventory_snapshot`, `allocation_confirmed`) — same

Only 8 event types actually require inference. In a 36-event instant run, roughly 28 are routine and never reach the LLM. The rest hit the model once each.

FastFlow v1 (consumables) is zero-LLM by design. Consumable quotes are a catalogue lookup; there's no reasoning involved. This matters at scale because high-frequency quote volume would otherwise eat the token budget fast.

---

## Blast-radius gating

The logic in `blast_radius.py` maps four inputs to a class and then to an autonomy level:

- **low** → `act` (system acts on its own)
- **medium** → `recommend` (rep sees it as a recommendation)
- **high** → `escalate` (goes to a manager, system doesn't proceed)

The four inputs are: deal value, number of accounts affected (reach), whether the action is reversible, and whether it touches the customer externally. External + irreversible always escalates. I kept the thresholds conservative — €200K for medium, €2M+ external for high — because in medical imaging a wrong quote or a premature customer communication is a serious relationship risk, not just a financial one.

One thing I'd revisit: the `reach` threshold of 10 for `high` was picked somewhat arbitrarily. In a real deployment you'd want that calibrated against the actual account portfolio size.

---

## What I'd do differently

- The correlator polling interval (30s) is too coarse for a real-time system. I'd change it to event-driven: subscribe to WorldState changes rather than polling.
- The affinity table in `cross_sell_engine` is hardcoded. It should load from a config file or the `/meta` endpoint so it can be updated without a code change.
- The 30-day stall threshold in `deal_velocity` should come from account territory configuration — some markets (NHS procurement) have inherently longer cycles.
