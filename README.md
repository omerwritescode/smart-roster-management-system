# Smart Roster Management System

A working roster tool for an operations team running support and operations for many D2C brands. An operations manager picks a month, generates a roster, sees every coverage gap by name, fixes or overrides each one, sends it through pod lead review, and publishes it. When someone becomes unavailable afterwards, the system shows the impact, ranks who can cover, and builds a new draft with as few changes as possible.

**Live app:** `ADD YOUR VERCEL URL`  
**Demo video:** `ADD YOUR VIDEO LINK`  
**Approach note:** [docs/approach-note.md](docs/approach-note.md)

There is no login. Use **View as** at the top right to switch between operations manager, pod lead and employee. **Reset demo data** restores the sample data at any time.

## What it does

| Brief | How it works here |
|---|---|
| Central database | Employees, pods, brands, processes, shifts, holidays, allocations and rules are all edited under **Setup**, with no code change |
| Working rules | 365-day, daily except holidays, Sundays and holidays off, or custom weekdays, set per process. Minimum staff by default, weekday or date |
| Monthly generation | Google OR-Tools CP-SAT. Up to 18 seconds a month |
| Conflict detection | A separate validator checks solver output and manual edits with the same rules |
| Five views | Company, pod, brand, process and employee. Click any date for who is working that day |
| Manual editing | Click a cell and see what the change would fix or break before saving |
| Handling change | Test an absence, approve it, get a minimal-change draft with a diff, and a ranked list of backups |
| All 10 optional features | Fair offs, preferences, automatic regeneration, backup recommendations, plan comparison, approvals, change notifications, CSV and Excel export, AI explanations, dynamic brands, pods and processes |

## Architecture

```text
Browser (React, TypeScript, Vite, TanStack Query)
   |  JSON over /api only. Database and Gemini keys stay on the server.
FastAPI on one Vercel Python function
   |-- backend/services   workflow, notifications, exports, AI
   |-- backend/engine     pure scheduling logic with no web or database code
   |     |-- calendar.py    operating days and rule definitions
   |     |-- solver.py      CP-SAT model, the only module that knows about OR-Tools
   |     |-- validator.py   the single source of truth, which never imports the solver
   |     |-- repair.py      edits, diffs, minimal-change regeneration
   |     |-- advisor.py     backup ranking, every option tested in the validator
   |     `-- plans.py       alternative plans and metrics
   `-- backend/db         Postgres access and sample data
Supabase Postgres (free tier). Row level security blocks its public API; only the server connects.
```

OR-Tools stays in because it fits: the function bundle measured about 215 MB against Vercel's 500 MB Python limit. The solver sits behind one module, so HiGHS could replace it if that changed.

## Run it locally

You need Python 3.13, Node 22 and any Postgres 14 or later.

```bash
cp .env.example .env                      # set DATABASE_URL
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
set -a; source .env; set +a
python -m backend.db.migrate              # creates tables and loads the sample data
uvicorn backend.app:app --port 8000

cd frontend && npm ci && npm run dev      # http://localhost:5173
```

## Deploy for free

No card is needed on any of these.

1. **Supabase:** create a free project in the South Asia (Mumbai) region, using a password with only letters and numbers. In the SQL editor, run `supabase/migrations/0001_schema.sql`, then `supabase/seed.sql`. Click **Connect**, choose **Transaction pooler** (port 6543), copy the string and put your password in it. The direct connection is IPv6 only and may not work from Vercel.
2. **Gemini (optional):** create a key in Google AI Studio. Do not link a billing account. Without a key, the app uses template explanations.
3. **GitHub:** push this folder to a public repository.
4. **Vercel:** import the repository on the Hobby plan. `vercel.json` sets everything else, so leave the framework preset as Other. Add these environment variables, then deploy:
   - `DATABASE_URL`: the pooler string
   - `CRON_SECRET`: any long random text. Vercel sends it to the daily keep-alive route
   - `GEMINI_API_KEY` and `GEMINI_MODEL`, if you made a key

`vercel.json` runs the API in Mumbai (`bom1`) to sit next to the database, because each screen makes several queries. If your Supabase project is elsewhere, change that value to match. A daily Vercel cron queries the database so the free Supabase project is not paused.

## Tests

```bash
pytest tests/test_validator.py tests/test_solver.py tests/test_changes.py   # about 2 minutes
pytest tests/test_random.py                                                 # about 1 minute
TEST_DATABASE_URL=postgresql://... pytest tests/test_api.py                 # about 2 minutes; wipes that database
```

- **Validator tests** check each rule against hand-built rosters, with no solver involved.
- **Randomised tests** (Hypothesis) generate nearly 200 unusual companies. Solver output goes through the validator, which must find no hard-rule break and exactly the gaps the solver admits to.
- **API tests** run the brief's scenarios and the whole workflow against real Postgres.

## Tell us how you think

### 1. How did you model employees, brands, processes, pods, and their relationships?

A **pod** has employees and one lead. A **brand** belongs to a pod. A **process** is a type of work such as CS or NDR. The central record is **brand process**: one process at one brand, with its own operating calendar and shift. That is what lets Customer Support run 7 days while ACC at the same brand closes on Sundays.

An **allocation** links an employee to a brand process, with a role (primary, secondary or backup), a workload share of their day, and optional dates. Being allocated is what makes someone qualified, so one person can hold several brands, and several people can share one process.

**Coverage rules** set minimum staff by default, weekday or date, and the most specific wins. A date rule can open a process on a closed day, or close it with a minimum of 0.

The roster keeps two separate tables. `roster_days` holds each employee's status per date, and `roster_assignments` holds who works which process. Together with brand calendars, this is how the system keeps a brand's operating calendar apart from a person's schedule.

### 2. How does your system generate a roster and determine whether it satisfies the required constraints?

Generation and checking are deliberately separate.

**Generating:** a constraint model decides each person's weekly offs and assignments. Hard constraints are approved leave, allocation, workload limit, overlapping shifts, rest between shifts, weekly offs and maximum consecutive days, including the last days of the previous published month. It then solves in two phases. Phase 1 finds the fewest coverage gaps any roster can have. Phase 2 fixes that number and optimises preferences, fairness and backup use, so a preference can never buy a gap.

**Checking:** a separate validator module, which never imports the solver, reads the finished roster and reports issues. Manual edits go through the same code, and it re-runs whenever a rule changes, so an existing roster shows new problems straight away. Randomised tests hold the two against each other.

### 3. How did you handle the difference between single-resource brands and brands with multiple employees?

Both use the same model, with no special case. The difference appears in the arithmetic: one person cannot cover seven days and also take a weekly off. So **backups are part of the core model**, not an extra.

- **Single-resource brand with a backup:** on the person's off day the backup steps in, stretching up to a limit on cover days if needed.
- **Single-resource brand without one:** the system reports a named gap and a "no backup configured" warning. It does not remove the weekly off. Tara Toys in the sample data shows this.
- **Separate processes:** Saffron Thread has three people on three processes, so losing one leaves that process exposed and the others untouched.
- **Shared processes:** Ember Candles CS is shared, so losing one person keeps it at its minimum. It needs 2 on Saturdays, so the same absence on a Saturday leaves it short until its backup steps in.

### 4. What happens when an employee manages all processes for a brand but is unavailable on a required working day?

Under **Availability**, the manager tests the absence first. Nothing changes yet. The system removes the person from those days, re-runs the validator, and names the gaps, the brands affected, and anything still covered.

From there the manager has two routes:

- **Find cover** ranks people by whether they are already allocated, then spare capacity, pod, and how much cover they have already done. Every option is tested in the validator first, so each one is labelled "passes every rule" or says what it would break. People who do the same process at another brand also appear, marked as needing to be added as backup. Where a weekly off could move within the week to close the gap, that is offered too.
- **Record the absence and regenerate** approves it and re-solves from that date. Earlier days and manual edits stay locked, changes are penalised, and the result is a new draft with its changes listed and outlined. It stays a draft until a person publishes it.

If a published roster is involved, it stays live until the new version is approved. Everyone affected then gets a notification of what changed.

### 5. How does your system handle conflicting requirements or insufficient staffing?

Rules have three tiers:

| Tier | Rules | If it cannot be met |
|---|---|---|
| Never broken | Approved leave, allocation, workload limit, shift clashes, rest, weekly offs, consecutive days | The solver cannot produce it. A manual edit that does is flagged as a blocker |
| Mandatory | Minimum coverage | A named gap that blocks publishing |
| Preferences | Preferred offs, fair Sundays and holidays, less backup use, fewer changes | Allowed, shown as a warning |

Coverage uses a slack variable, so the solver always returns a roster and can say exactly which day and process failed. When Phase 1 finishes, the app can state that the solver proved no roster has fewer gaps, which tells the manager that the fix must be a staffing decision and not more shuffling.

Each gap names its cause (weekly off, leave, incompatible shifts or no capacity) and what each allocated person is doing that day. One absence causing gaps at several brands gets its own warning. Blockers stop publishing unless a person records a written reason, which stays on the record.

### 6. Which parts of the process did you automate, and which did you leave under human control? Why?

**Automated:** building the roster, checking every rule, finding the fewest possible gaps, testing every backup option, regenerating a draft after approved leave, earning comp-offs, and notifying people of changes. These are large, repetitive, and easy for people to get wrong.

**Left to people:** approving leave, accepting a gap, overriding a rule, working someone through a weekly off, approving and publishing. These are judgement calls involving a client relationship or someone's rest day, and someone should own them.

The principle is that **the system proposes and a person approves**. AI explanations follow it too: Gemini only rewords facts the validator has already established, and it makes no scheduling decision. If it fails or hits a limit, the app shows a template explanation built from the same facts.

### 7. If the company doubled its team and brand count, what would you change about your solution?

The model itself holds up. I tested a doubled company of 68 employees and 50 brands on one CPU core: it broke no hard rules and proved the minimum number of gaps (exactly double, 28). The validator took about 26 ms. What suffers is the optimisation step: in the same 18 seconds, preferences honoured fell noticeably, so the roster is valid but less polished.

So I would change, in this order:

1. **Run solves as background jobs** with a progress display, instead of holding a web request open, and allow a longer solve.
2. **Solve pod by pod** and then join them with cross-pod cover, since most cover stays within a pod.
3. **Add real login and row-level permissions**, because a larger company cannot rely on a role switcher.
4. **Add bulk import** of allocations and leave, since editing rows by hand stops being practical.

Finally, the free tiers would no longer fit, so hosting would move to paid plans.

### 8. If you had one additional week to work on this, what would you improve first?

**Real login and per-person access**, because the role switcher is the weakest part for real use: anyone with the link can change anything. Next, employee self-service for leave requests and shift swaps with the manager approving, then Google Sheets export and real message delivery through n8n using the webhook that already exists.

## Assumptions

- **Weekly offs:** one per Monday-Sunday week by default, configurable per employee. Patterns are fixed, rotating or chosen by the solver.
- **Part-weeks:** the part-week closing a month needs no off, because it can fall next month. The opening part-week counts if last month's roster is known, or if it has 4 or more days.
- **A week with no available day** (entirely on leave) needs no weekly off.
- **Maximum consecutive working days:** 6 by default. A day marked Spare (on duty with no assignment) breaks the run. If someone's pattern would exceed the limit, the solver gives them a spare day, so a rotating pattern can show one between offs.
- **Minimum rest between shifts:** 11 hours, editable. Late then Early (9 hours) is blocked.
- **Workload:** each allocation is a share of a person's day. The limit is 100%, or up to 125% on a day with cover work, per employee. A stretch day shows as a warning.
- **Minimum staff is a headcount.** With no rule, it is 1 on every open day.
- **Regular staff work whenever their process is open and they are on duty,** even above the minimum, except on holidays, which are staffed to the minimum only.
- **Comp-offs:** working a public holiday, or working through a weekly off, earns one when the roster is published. Moving an off within the same week earns nothing. Balances follow the latest published roster.
- **Holidays** apply company-wide. Regional holidays would need a holiday-to-pod link.
- **Pending leave** does not change the roster, but it shows a warning when it clashes with work.
- **Fictional data:** all brands and people are invented. Christmas Day on 25 December 2026 was checked against published 2026 Indian holiday lists. Founders' Day is an invented company holiday.
- **Previous month:** the first roster has no history. After a month is published, the next month reads its last days.
- **Cover share:** someone newly added as backup from the recommendations takes 25% of a day.

## Known limits

- **No login.** The role switcher makes review instant, but it is not security, and anyone with the link can change or reset the demo data. Database keys stay on the server, and row level security blocks Supabase's public API, so the risk is limited to this sample data. A production version needs real sign-in.
- **The solver stops at a time limit,** so preferences and fairness are good but not proven optimal. The coverage minimum normally is proven, and the app says so when it is.
- **Google Sheets:** the brief says CSV, Excel or Google Sheets. Direct integration needs Google sign-in, so this exports Excel files, which open in Sheets.
- **Free-tier Gemini** data may be used by Google and read by reviewers, so only fictional data should pass through it.
- **Limits on a public demo:** each solve uses about 18 seconds of Vercel's 4 hours of monthly active CPU.

## Use of AI tools

Built with Claude as a coding assistant. The approach, the rule tiers and the trade-offs above were decided and reviewed by the author.
