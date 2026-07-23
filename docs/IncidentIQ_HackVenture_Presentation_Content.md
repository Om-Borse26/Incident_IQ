# IncidentIQ — HackVenture 2026 Presentation Package (v2)
*Fits the official 7-slide template exactly. Slides are light — most of the story lives in the 7-minute script below.*

---

## What changed from v1
- **No new slides.** Everything now fits inside the original 7: Title, Problem, What We Aim to Solve, Solution Overview, Architecture/Flow, USP & Business Model, Demo Link. UI/UX and Scalability are now one line each, folded into existing slides.
- **Slides got shorter.** 3–4 short bullets max per slide. The explaining happens when you talk, not on the screen.
- **Script trimmed to ~7 minutes** (roughly 950 words spoken at a natural pace), and de-jargoned — technical terms are named once, explained in plain words, and not repeated three different ways.
- **Two claims corrected** based on what you flagged — see the callouts below. Both were fixable, and the corrected versions are honestly stronger.
- **Open-source PR mentions** moved to a small footnote on the Architecture slide + a ready one-liner for the script/Q&A, instead of taking up story time.

---

## Correction 1 — PagerDuty comparison
Your friend's read is right for PagerDuty's *core* alerting product — a human does the investigating. But PagerDuty now sells a paid AI add-on (PagerDuty Advance / SRE Agent) that drafts summaries and suggests causes, so don't say PagerDuty has *no* diagnosis capability anywhere — that's checkable and wrong.

**Use this instead:**
> "On the plan most teams actually run, PagerDuty's job ends the moment it wakes someone up — the person on call still has to dig in themselves. Some vendors sell AI diagnosis as a separate paid add-on bolted onto that alerting core. IncidentIQ was built diagnosis-first from day one, using free and open tooling, not as an expensive afterthought."

## Correction 2 — "no one does auto-remediation" for future scope
Checked this directly: AWS's DevOps Agent and Microsoft's Azure SRE Agent both launched in March 2026 doing exactly this — investigate, sandbox-test a fix, propose it, human approves. A smaller vendor (Aurora SRE) does the same with a published safety-gate design. So don't claim this is untouched ground.

**Use this instead (this is actually a better line than the original):**
> "This is exactly the direction AWS and Microsoft just pointed their own SRE agents in — sandbox-test a fix, propose it, human approves. That's the roadmap we want to build IncidentIQ toward next: not just suggesting the fix, but proving it works in a safe copy of the system before a human signs off."

---

## Verified stats — use exactly as framed

| Stat | Source | Note |
|---|---|---|
| **Over 90%** of mid/large enterprises say **one hour of IT downtime costs $300,000+**; 41% say **$1M–$5M+** | ITIC, *2024 Hourly Cost of Downtime Survey* | Your headline number — IT-specific, not manufacturing. |
| July 2024 CrowdStrike update crashed **8.5 million Windows devices**; insurers estimated **$5.4B** in Fortune 500 losses | Microsoft, CISA, insurer estimates | Concrete, recognizable, well-documented. |
| Elite engineering teams restore service in **under an hour**; low performers take **a week to a month** | DORA / Accelerate State of DevOps research | I dropped the earlier "60–80% of MTTR is diagnosis" line — couldn't verify it's actually in a DORA report. This framing doesn't need that number. |
| Opsgenie: sales stopped June 2025, **full shutdown April 5, 2027** | Atlassian official docs | Correct current date. |

*(Dropped the Siemens $1.4T figure from the headline slot — it's a manufacturing/industrial downtime study, not software, and using it for a server-outage story would be misleading.)*

---

## Slide-by-slide content (7 slides, template unchanged)

### Slide 1 — Title
```
Team Name / Domain: Artificial Intelligence / Project Title: IncidentIQ
College: Vishwakarma Institute of Technology, Pune
```
*Optional one-line tagline under the project title, if the template has room:* `An AI reliability copilot that turns past incidents into faster future recoveries.`

### Slide 2 — The Problem
```
◦ 90%+ of companies say 1 hour of downtime costs $300,000+
  (41% say $1M-5M+) — ITIC, 2024
◦ Knowledge of past fixes lives in people's heads and old
  chat threads, not anywhere searchable
◦ CrowdStrike, July 2024: 8.5M devices down, $5.4B in
  losses — a global proof of how costly slow diagnosis is
```
*Small footer, 8–9pt gray text at the bottom of this slide:* `Sources: ITIC 2024 Hourly Cost of Downtime Survey; Microsoft/CISA CrowdStrike incident reports (2024)`

### Slide 3 — What We Aim to Solve
```
◦ Cut the time spent figuring out WHAT broke, not just
  fixing it
◦ Turn one engineer's memory into knowledge the whole
  team can query
◦ Every resolved incident makes the next one faster
```

### Slide 4 — Solution Overview
```
◦ Answers are labeled by confidence — documented fix,
  AI suggestion, or "we don't know yet, here's live data"
◦ Searches previous incidents and structured runbooks
  together — organizational memory, combined with live
  production telemetry
◦ Pulls live production telemetry from connected systems
  at the same time — one combined answer
◦ Simple chat interface, live streaming answers, one
  click to approve new knowledge
```

### Slide 5 — Architecture / Flow Diagram
Keep the visual simple — a judge should follow it in five seconds:
```
 Engineer asks a question
          │
          ▼
   What kind of question is this?
          │
   ┌──────┴──────┐
   ▼             ▼
Check live      Search past
systems         incidents
(2 methods, nothing lost)
   └──────┬──────┘
          ▼
   One combined, labeled answer
          │
          ▼
   New kind of issue? → draft a
   postmortem → human approves →
   becomes permanent knowledge
```
```
◦ Combines semantic search with structured document
  reasoning, not just a plain keyword or vector lookup
◦ Runs as a clear, traceable sequence of steps — every
  decision is visible, not a black box
◦ Self-healing containers (verified 65-second recovery
  from a crash) + an SQS queue that buffers traffic bursts
```
*Tiny footnote at the bottom of this slide, small font:* `Team has contributed fixes to LlamaIndex and OpenAI's Agents SDK (merged PRs)` — visible if someone looks closely, doesn't cost you story time.

### Slide 6 — USP & Business Model
```
◦ Combines incident history + live production telemetry
  in one answer — most tools do only one of the two
◦ Two-path search means exact details never get lost
◦ Nothing becomes "permanent knowledge" without a human
  approving it first
◦ Free tier for small teams; paid tier for larger teams
  needing private data + integrations
◦ Saving 15-20 minutes on one major incident can cover
  a long time of using the tool
```

### Slide 7 — Demo Link
```
Live Platform: [your URL]
GitHub: [your repo]
Demo Video: [90-120 sec backup recording]
```

---

## Full script — short, punchy, conversational (~5 min talking, rest for demo + breathing room)

Don't read these word for word — they're talking points, not a script to memorize. Glance, then say it in your own words. That's what makes it sound natural instead of recited.

**Slide 1 & 2 — Hook + Problem (~1–1.5 min)**
- "Imagine you're the on-call engineer. It's 2 AM. Your server just crashed. Customers are furious."
- "Now you have to dig through logs, debug the issue, maybe untangle a dependency conflict — and here's the thing: maybe you fixed this exact issue five months ago. But you don't remember. There's no record you can search."
- "That's the real problem. It's not that engineers don't know how to fix things — it's that they have no memory of what already worked."
- "And that gap costs real money: one hour of downtime costs a mid-to-large company over $300,000. In July 2024, one bad update crashed 8.5 million machines worldwide — a huge part of that cost was just how long it took anyone to figure out what had happened."

**Slide 3 — What We Aim to Solve (~30 sec)**
- "That's exactly where IncidentIQ comes in. A quick prompt, and it does the heavy lifting for you — searching your historical data and your live logs — to propose a clear, accurate fix."
- "What used to take hours of manual digging becomes a conversation."

**Slide 4 — How It Works (~1 min)**
- "Four things it does. One — dual retrieval: it searches structured runbooks and past incidents two different ways, so nothing useful ever gets lost."
- "Two — it pulls live data straight from the actual servers, so it's not just guessing off old records."
- "Three — safety. Every answer is clearly labeled: proven fact, or AI suggestion. At 3 AM, that distinction matters."
- "Four — its knowledge actually grows. Engineers can upload documented fixes directly, and when it solves something new live, it drafts a report that only becomes permanent knowledge once a human approves it."

**Slide 5 — Architecture (~30–40 sec)**
- "Under the hood, it's not just one prompt to ChatGPT — it's a clear, step-by-step process, so every decision is visible, not a black box."
- "It's live on AWS right now. It's self-healing — we actually crashed it on purpose, and it fully recovered in 65 seconds with zero manual work."
- "And it uses a queue system, so a flood of traffic gets absorbed instead of crashing the app."
- *(Optional, only if time allows: "We also contributed fixes back to LlamaIndex and OpenAI's Agents SDK while building this — both merged.")*

**Slide 6 — Why We're Different (~45 sec)**
- "Most traditional alerting tools do one job well — they wake someone up when something breaks. They don't tell you *why* it broke."
- "IncidentIQ is built diagnosis-first — it doesn't just alert you, it tries to tell you what's actually wrong and why."
- "If it saves a team even fifteen or twenty minutes during one major outage, it's already paid for itself."

**Slide 7 — Demo (~1.5–2 min)**
- *[open the live app]* "Let's see it live."
- *[ask a realistic question]* "Watch it separate 'this is documented' from 'this is the AI's best guess.'"
- *[ask a natural follow-up]* "It remembers the conversation, so no re-explaining."
- *[approve a postmortem]* "One click, and that becomes permanent team knowledge."

**Closing (~20–30 sec)**
- "This isn't just slides — it's a real, working system, live right now, that turns hours of confusion into minutes of clarity. Thank you."

*(Talking-point word count is roughly 450–500 words, which naturally expands to about 4.5–5 minutes when spoken conversationally instead of read — leaving a real 2+ minutes for the demo and slide transitions inside your 7-minute limit.)*

---

## Q&A prep — short, plainspoken answers

**Why not just use ChatGPT for this?**
> "ChatGPT doesn't know your team's history, your runbooks, or what your servers are doing right now. Ours does — because it's built on your own data."

**What about tools like PagerDuty or Opsgenie?**
> "Traditional alerting tools are great at waking someone up. They don't diagnose the problem for you — a human still has to dig in from there. We're built diagnosis-first, not alert-first."
>
> *(Notice this doesn't name a specific product's exact feature set — it's a true statement about the category, so it holds up whether the judge knows that tool well or not at all.)*

**What if the AI gets it wrong?**
> "Every AI-generated answer is clearly labeled as unverified, kept separate from proven facts. And nothing becomes permanent knowledge without a human clicking approve first."

**Could you eventually auto-fix things, not just suggest fixes?**
> "That's actually the direction the big cloud providers are heading too — sandbox-test a fix, then a human approves it. That's our natural next step."

**How does this scale for a big company?**
> "Right now it's one small container on a free-tier setup, so we didn't build auto-scaling — wasn't the point of this build. What is real: it self-heals in 65 seconds, verified, and a queue absorbs traffic bursts so it never crashes under load. Auto-scaling later is a known next step, not a redesign."

**Tell me about your open-source work.**
> "We found and fixed real bugs in two well-known AI frameworks — LlamaIndex and OpenAI's Agents SDK — both fixes got merged. We used the same discipline in our own system."

**What are the current limitations?**
> "It's built for one team right now — supporting multiple organizations is next. And it only has live access to the services we've actually connected it to so far."

---

## Technical deep-dive — for Q&A only, not the main script

This is everything you wrote out — it's genuinely good material, it just doesn't fit inside 7 minutes of spoken narrative. Use it when a judge asks a follow-up question. Having crisp, precise answers ready here is exactly what the 5-mark Q&A category rewards.

**"Walk me through the request flow."**
> "A query comes in, and a classification step figures out three things: is this a brand-new question, a follow-up that needs another database lookup, or a follow-up we can answer from conversation memory alone? Then it's routed as chitchat, a historical question, or a live incident. Historical and live queries both go through our dual retrieval — vector plus structural search — and live queries also pull real-time data through our diagnostics layer. Everything gets combined and handed to the model to generate the answer. Each conversation gets a thread ID, and we persist that in SQLite mounted on our EC2 instance — fast, and the right call for a project at this budget stage."

**"What about performance and caching?"**
> "We cache repeated queries so identical questions get answered instantly instead of re-running the full pipeline — saves both latency and API cost."

**"What security measures are in place?"**
> "Authentication, rate limiting, duplicate-file detection on ingestion, and explicit defenses against prompt injection and jailbreak attempts — anything inside an uploaded document or a retrieved log is always treated as data, never as an instruction to the model."

**"What happens if the model or a service fails mid-request?"**
> "We built fallback paths so the user experience doesn't just break — if a generation step fails, the system degrades gracefully instead of throwing a dead end at the engineer."

**"Tell me about your open-source contributions, precisely."**
> "In OpenAI's Agents SDK, we found and fixed a bug where the wrong schema could get passed between agents, silently producing bad output. In LlamaIndex, we fixed silent exception swallowing — the pipeline would keep running even when it failed to get required data from an upstream step, with no warning. Both fixes were merged. We applied the same lesson to our own system: if a component doesn't get what it needs, it throws an explicit error instead of quietly continuing with bad data."

**"How does ingestion and knowledge-base growth actually work?"**
> "Two ways. An engineer can upload a document — an issue, its symptoms, and its fix — directly. Or, when the system resolves a brand-new live incident on its own, it drafts a postmortem and waits for a human to approve it before that becomes permanent knowledge. On the upload side, we also run a duplicate check and a completeness check — the system verifies the document actually contains enough information to be useful before accepting it."

**"How does the MCP layer scale?"**
> "It's designed so a company can connect as many live diagnostic nodes as they need — it's not capped to a fixed number of servers."

### Corrected competitor comparison (verified where noted)

| Tool | What's accurate to say |
|---|---|
| **PagerDuty** | Alerting/escalation-first. Pricing across current sources ranges roughly $21–50/user/month depending on tier and add-ons — don't quote a single fixed number, it varies by source. Higher tiers do offer a paid AI add-on that drafts summaries from the *current* incident's own signals — but it's a bolt-on, not built-in, and it's not cross-referencing a dedicated historical incident knowledge base the way our dual retrieval does. |
| **Opsgenie** | Confirmed: sales stopped mid-2025, full shutdown April 5, 2027 (Atlassian's own docs). Safe to state as fact. |
| **Rootly** | Strong at incident coordination/workflow. **I haven't independently verified** whether it lacks RAG-based historical retrieval — don't state that as fact unless you've checked yourself. Safer: describe it by what it's known for (coordination/workflow automation) rather than what it supposedly lacks. |
| **Datadog** | Excellent at real-time anomaly detection — that's its core strength. Fair to say its focus is live monitoring, not retrieving and reasoning over historical incident data — that's a capability difference, not a knock. |
| **ChatGPT / Copilot** | Safe and true: no built-in access to your team's specific incident history, runbooks, or live telemetry unless someone builds that integration — which is essentially what IncidentIQ is. |

### On the business model question

I'd hold off on inventing a specific price per user — here's why, and what I'd do instead.

The costs you listed are real and the right ones to think about: paid LLM API usage that scales with traffic, ECS/EC2/ECR compute, a managed vector database (pgvector or similar), SQS, a load balancer if you outgrow a single instance, a domain, and possibly a more production-grade frontend host as usage grows. But turning that into an actual $/user number requires knowing your real unit economics — API cost per query, expected query volume per engineer per month — numbers neither of us has measured yet. A judge with any finance background will ask "how did you calculate that," and an invented number won't survive that question.

**What I'd do instead, which is what the current Business Model slide already does:** stay qualitative. Name the *shape* of a plausible model — a free tier for small teams, a paid tier for larger teams needing private data and integrations — and lean on the ROI framing you already have ("saves 15–20 minutes on one major incident, which already outweighs typical tool costs given what downtime costs today"). That's a real, defensible claim without needing invented pricing. If a judge pushes for a specific number, "we haven't finalized pricing — it'd depend on real usage data we don't have yet, but the free/paid-tier shape is the direction" is an honest, confident answer.

**On frontend hosting:** don't change this before submission. Vercel is legitimate production infrastructure — plenty of real companies run on it — so it's not a weakness to defend, and rebuilding infra with about a day left before deadline is much higher risk than upside. If you want, "moving to a dedicated production host as usage grows" can be one more line in your existing roadmap bullet, but it's future scope, not something to act on tonight.

---

## One last thing
Record a 90–120 second backup demo before presentation day. If the live app is cold-starting when your turn comes, a smooth recording beats a frozen screen — and it keeps you inside the 7-minute window no matter what the network does.
