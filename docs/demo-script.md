# Demo script (3 to 5 minutes)

Before recording: click **Reset demo data**. Keep the view as operations manager. Exact names and dates in the roster can vary a little between solves, so check a run first.

## 1. The problem and the data (30 seconds)

Open **Setup > Brand processes**. Point out that Customer Support at Nimbu Naturals runs 365 days, while its ACC has Sundays and holidays off. Open **Allocations**, and say that 20 of the 25 brands have one dedicated person.

Say: "A person on a 7-day process cannot also take a weekly off, so this is a constraint problem and not a calendar."

## 2. Generate and see different schedules (45 seconds)

On **Roster**, click **Generate December 2026** and wait up to 20 seconds.

- Read the summary: the blockers count, and that the solver proved no roster can have fewer.
- **Company view:** different people have offs on different days, including fixed and rotating patterns.
- **Brand view:** coverage per process per day. Show a process hatched as closed on Sundays beside one staffed all week.
- Click a date heading: who is working and who is off that day.
- **Employee view:** one person's month.

## 3. Conflict detection (45 seconds)

In **Before publishing**, show:

- **Tara Toys CS:** a 7-day brand with one person and no backup. Weekly off clash. Say: "It reports the gap. It never removes her weekly off."
- **Jute Junction RET:** incompatible shifts. A Late shift overlaps Rhea's General shift on Saturdays.
- **Kulfi Club and Sattva Snacks:** one person's leave affects two brands. Show the warning under **Warnings**.

Click **Explain** on one.

Click **Find cover** on a Tara Toys gap: ranked people, each tested against every rule.

## 4. Handling a change (75 seconds)

**Scenario A: the only person on a brand becomes unavailable.**

1. Go to **Availability > Test an absence**. Choose Karan Bhatia, 17 December, Unavailable. Click **Check impact**.
2. Haldi House loses CS and RET. Nothing has changed yet.
3. Click **Record this absence and regenerate**. Show the short list of changes.
4. Click **Open the draft**. Changed days are outlined in orange. A backup now covers CS, and RET is still a named gap, because it has no backup.

**Scenario B: one of three people is unavailable.**

Test Riya Chawla on the same date. Ember Candles CS stays covered by Kabir ("still covered"), and only NDR is exposed. Say: "The system works out whether the others can keep coverage."

## 5. Manual edit with live validation (20 seconds)

Back on **Roster**, click any working cell and change the status to Unavailable. The panel shows which gaps it would create before anything is saved. Click **Cancel**.

## 6. Compare, approve, publish, notify, export (45 seconds)

1. Go to **Compare plans** and generate all three, or show an earlier run. Coverage is equal, and fairness and preferences differ.
2. On **Roster**, record an override with a reason on a gap.
3. Go to **Approvals**. Publishing is locked while blockers are open. Send to pod leads.
4. Switch **View as** to a pod lead and approve one pod. Say that a pod lead can only decide for their own pod.
5. Switch back to show the rest. To save time, approve the others with a note.
6. After clearing the blockers, publish.
7. Edit a day on the published roster. It creates a new draft version, and the published one stays live. Publish it, then show **Activity**: who changed and what.
8. Click **Export Excel**.

## Close (15 seconds)

"The solver proposes, the validator checks, and a person decides. It runs entirely on free tiers, and the README explains the assumptions and trade-offs."
