# Approach note: Smart Roster Management System

## The problem

The hard part is not drawing a calendar. It is that one person on a 7-day process cannot also take a weekly off, and one person's absence can reach several clients. I treated this as a constraint problem with honest failure: when requirements cannot all be met, the system names what failed and leaves the decision to a person.

## The solution

- **Data model:** the central record is a *brand process*, which is one process at one brand with its own calendar and shift. An *allocation* links a person to it with a role and a workload share. Backups are part of the core model, because single-employee brands need them.
- **Solver:** Google OR-Tools CP-SAT, in two phases. The first finds the fewest coverage gaps possible under the hard rules. The second fixes that number and optimises preferences, fairness and backup use, so a preference can never buy a gap.
- **Validator:** a separate module and the single source of truth. Solver output and manual edits pass through the same checks, so the solver never marks its own work.
- **Repair:** changes re-solve with past days and manual edits locked and each change penalised, producing a draft with a diff for approval.
- **Human control:** the system proposes and a person approves. Publishing requires pod lead review, operations approval, and a written reason for any blocker left open.

## Architecture

React, TypeScript and Vite call a FastAPI backend on one Vercel Python function, backed by Supabase Postgres. The engine has no web or database code, so it can be tested and swapped on its own. Gemini's free tier only rewords validator facts, with a template fallback. The whole project runs on free tiers.

## Key decisions

| Decision | Why | Trade-off |
|---|---|---|
| Constraint solver instead of rules or an LLM | Can prove a minimum and never invents an invalid roster | Needs an 18-second solve inside a web request |
| Two-phase solve instead of one weighted score | Coverage can never be traded for a preference | A little more solve time |
| Separate validator | An independent check, reused for manual edits | Rules are expressed twice, which randomised tests hold together |
| Never remove a weekly off to hide a gap | An honest gap is more useful than an invalid roster | The sample month shows real blockers, by design |
| No login, role switcher instead | Reviewers can test every role instantly | Not secure for real use; documented |
| Excel instead of direct Google Sheets | Avoids Google sign-in, and Excel files open in Sheets | No live sync |

## How it was checked

Each rule has hand-built validator tests. Randomised tests generate nearly 200 unusual companies and require that the solver breaks no hard rule, and that the validator finds exactly the gaps the solver admits. API tests run the brief's scenarios and the whole approval workflow against real Postgres. A doubled company of 68 employees and 50 brands broke no hard rules on one CPU core.

## What I would do next

Real login first, then employee self-service for leave and swaps, then background solving so larger teams get longer solves.
