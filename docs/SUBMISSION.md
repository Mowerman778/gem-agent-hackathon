# SynapseNode — DevPost submission pack

Category: **Collaborative Partner** · Started 19 Aug 2026 · Google SDK: **GenAI SDK** (`google-genai`)
Live: https://synapse-api-304818356745.us-central1.run.app
Repo: https://github.com/Mowerman778/gem-agent-hackathon

---

# Part 1 — Written description

## Inspiration

Every productivity tool ever built optimises throughput. Point one at a tired
person with five chores and it returns the optimal subset — correct, and quietly
corrosive, because it has no concept of the person doing the work.

I wanted to find out what happens if you build that optimiser properly, and then
deliberately put a second agent in front of it whose job is to disagree with it.

## What it does

SynapseNode takes an unstructured brain-dump of domestic tasks, parses them into
a dependency DAG, scores them, and measures how much uncertainty the queue
carries. It tracks two live signals about the person: energy capacity in hours,
and receptivity on a 0–1 scale where lower means closer to overload.

The **Collaborative Partner** — Gemini 3.5 Flash, reading that state through
function calling — then talks it through with you. It decides *with* you rather
than for you, treats rest as a first-class priority, and is willing to recommend
doing nothing at all.

The proof is the same question in two states.

Depleted (1.5h capacity, receptivity 0.25, three tasks of 5–8h each):

> I'd strongly recommend taking the evening completely off to rest and recharge.
> But if you really want to do a little something: 1. Spend just 15 minutes
> gathering your tax documents into one pile, then stop. 2. Do absolutely nothing
> productive. Which of those sounds better to you?

Rested (7h capacity, receptivity 0.9), same queue, same question:

> **Sort tax paperwork (5h)** — it has a deadline, so getting this out of the way
> might bring the most peace of mind. **Fix the leaking tap (5h)** — a satisfying,
> hands-on project. **Take the evening off** — you don't have to spend a free
> evening on massive chores. What feels right for you tonight?

It proposes real work when there is capacity for it. It is balanced, not a
rest-bot — and it is grounded, because it calls tools before it says anything.

The Task Master ILP solver is still there at `POST /api/solve`. It represents the
lone-ranger approach the Partner exists to counterbalance.

## How I built it

| Layer | Technology |
|---|---|
| Model | **Gemini 3.5 Flash** via **Vertex AI**, called with the **Google GenAI SDK** |
| Compute | **Cloud Run** — private-capable, scales to zero, capped at 3 instances |
| State | **Firestore**, with a local JSON fallback for offline runs |
| Events | **Pub/Sub** — asynchronous behavioural nudges |
| Build | **Cloud Build** → **Artifact Registry** |
| Optimiser | PuLP / CBC — 0–1 ILP under an energy-capacity constraint |
| API | FastAPI, 12 endpoints, plus a `synapse` CLI |
| IDE | **Antigravity** |

The agent has two tools, `list_open_tasks` and `get_wellbeing_signals`, and the
system instruction requires it to call them before proposing anything. It runs on
a least-privilege service account holding exactly `aiplatform.user`,
`datastore.user`, `pubsub.publisher` and `pubsub.subscriber`.

Behavioural nudges pass a cognitive-load boundary before they are sent:

```
B(t) = θ( R_user(t) − K_th · (1 + ρ_density) )
```

where `ρ_density` is nudges per minute over a five-minute window. It is
anti-fatigue logic first, and because a suppressed nudge never reaches the model,
it doubles as a cost control.

## Data sources

No external datasets. All state is user-generated — the task brain-dump, and the
energy and receptivity readings — persisted in Firestore. Task effort, priority,
and queue entropy are computed from that input.

## Challenges and what I learned

**Gemini 3.x is not served from `us-central1`.** Every 3.x model returned 404
there; the region tops out at 2.5, below the entry bar. They serve from the
`global` endpoint. Cloud Run still deploys to `us-central1` — the two settings are
unrelated, which is exactly why it was confusing.

**Thinking tokens count against `max_output_tokens`.** A one-line nudge capped at
120 tokens spent 111 of them reasoning and returned five tokens of truncated
text. Setting `thinking_budget: 0` fixed it and cut ~381 reasoning tokens per
nudge to zero. The Partner keeps thinking on, because weighing trade-offs is its
actual job.

**Credential detection is easy to get wrong.** `gcloud auth application-default
login` writes a file and sets no environment variable, so an env-var check misses
it — the model is never called and the fallback path serves silently, looking
fine. `google.auth.default()` is the check that covers env vars, the ADC file,
and the Cloud Run metadata server together.

**A grounded agent needs its tools to actually work.** One tool read a key that
didn't exist and substituted a default of 6.0 hours. The agent then advised
confidently on a number nobody had ever measured. It read perfectly. An agent
that guesses at your energy level and then advises you on your evening is worse
than no agent — so every number it cites now comes from a tool call.

**Failing safe matters more than failing loudly.** Without credentials the app
still runs: nudges fall back to templates, the Partner reports itself
unavailable. Nothing crashes, and nothing pretends.

## What's next

Longitudinal receptivity — learning someone's real energy curve over weeks rather
than trusting a self-reported slider — and letting the Partner negotiate
deadlines with the solver directly instead of only reading its output.

---

# Part 2 — Demo video script

**Target: 95 seconds.** Record in short clips so any one can be redone.
Start already logged in. Paste commands, never type live. Jump-cut every pause.

### Shot 1 — 0:00–0:14 · The agent working, immediately

Terminal, already open, command pasted and run:

```bash
synapse chat "I've got a free evening. What should I get done tonight?"
```

Let the real response render:

> Partner · gemini-3.5-flash · via Cloud Run
> I'd strongly recommend taking the evening completely off to rest and recharge…

On-screen text: **"It told me to stop."**

No intro, no title card, no narration yet. The first thing on screen is the
product doing the one thing that makes it different.

### Shot 2 — 0:14–0:30 · The turn

Voiceover: *"Every task app optimises throughput. SynapseNode has that optimiser
— a real integer program. And then it puts an agent in front of it whose job is
to argue with it, on your behalf."*

Cut to `synapse tasks` showing the queue: three tasks, 5–8 hours each.
On-screen text: **"1.5h capacity · receptivity 0.25"**

### Shot 3 — 0:30–0:52 · The contrast — this is the money shot

```bash
synapse state --energy 7 --receptivity 0.9
synapse chat "I've got a free evening. What should I get done tonight?"
```

Same question. Same queue. Different answer:

> **Sort tax paperwork (5h)** — it has a deadline… **Take the evening off** —
> you don't have to spend a free evening on massive chores.

Voiceover: *"Same question, same tasks. What changed is me. It proposes real work
when there's capacity for it — it isn't just a rest button."*

On-screen text: **"7h capacity · receptivity 0.9"**

### Shot 4 — 0:52–1:12 · Grounded, not guessing

Cut to the two tool definitions in the IDE — `list_open_tasks`,
`get_wellbeing_signals` — then the system instruction line:

> *"Do not invent tasks or numbers."*

Voiceover: *"It calls tools before it answers. An agent that guesses at your
energy and then advises you on your evening is worse than no agent."*

### Shot 5 — 1:12–1:30 · Proof it runs on Google Cloud

Split screen or quick cuts:

```bash
gcloud run services describe synapse-api --region us-central1 \
  --format="value(status.url,status.latestReadyRevisionName)"
curl -s $URL/api/status | jq
```

Show the Cloud Run console page with the service green.

Voiceover: *"Gemini 3.5 Flash through Vertex AI, on Cloud Run, with Firestore and
Pub/Sub. Least-privilege service account, capped at three instances."*

On-screen text: **"Gemini 3.5 Flash · Vertex AI · Cloud Run · Firestore · Pub/Sub"**

### Shot 6 — 1:30–1:35 · Close

Back to the depleted reply on screen. One line:

*"Most agents help you do more. This one helps you do the right amount."*

### Cut these if you run long
Shot 4 first, then the second half of Shot 5. Shots 1 and 3 are the submission —
protect them.

### Checklist
- [ ] Public, under 4 minutes
- [ ] Agent visibly working in the first 15 seconds
- [ ] Proof the backend runs on Google Cloud
- [ ] No sign-up, setup, or loading footage
- [ ] No live typing
