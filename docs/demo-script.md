# Demo script (3 to 5 minutes)

Before recording: click **Reset demo data**. Keep the view as operations manager. Exact names, dates and counts can vary a little between solves, so do one practice run first.

If you dismissed the **How to read this roster** box during practice, click **How to read this** above the grid to bring it back for the recording.

## 1. The problem and the data (30 seconds)

Open **Setup > Brand processes**. Point out that Customer Support at Nimbu Naturals runs 365 days, while its ACC has Sundays and holidays off. Open **Allocations**, and say that 20 of the 25 brands have one dedicated person.

Say: "A person on a 7-day process cannot also take a weekly off, so this is a constraint problem and not a calendar."

## 2. Generate and see different schedules (45 seconds)

On **Roster**, the empty month explains the three plans. Leave **Coverage first** selected and click **Generate December 2026**. While it solves, read the on-screen note: it finds the fewest possible gaps first, then balances preferences and fairness.

- **The progress strip** at the top shows the four steps: Generate, Clear blockers, Pod lead review, Publish. Read its message: how many blockers stop publishing, and that the solver proved no roster can do better.
- **How to read this roster:** point at the red numbers under the dates, then click **Got it**.
- **Company view:** different people have offs on different days, including fixed and rotating patterns.
- **Brand view:** coverage per process per day. Click **Colour key** and show a process hatched as closed on Sundays beside one staffed all week.
- Click a date heading: who is working and who is off that day.
- **Employee view:** one person's month.

## 3. Conflict detection (45 seconds)

In **To review** on the right, blockers are grouped by process, each tagged with its cause:

- **Tara Toys CS:** a 7-day brand with one person and no backup, tagged **Weekly off clash**. Say: "It reports the gap. It never removes her weekly off."
- **Jute Junction RET:** tagged **Incompatible shifts**. A Late shift overlaps Rhea's General shift on Saturdays.
- Switch to **Warnings** and open **One absence, several brands**: one person's leave affects Kulfi Club and Sattva Snacks.

Click **Explain** on one issue.

Click **Show the first blocker** in the progress strip, or **Find cover** on a Tara Toys gap: ranked people, each tested against every rule.

## 4. Handling a change (75 seconds)

**Scenario A: the only person on a brand becomes unavailable.**

1. Go to **Availability**. Under **Test an absence**, choose Karan Bhatia, 17 December, Unavailable. Click **Check impact**.
2. Haldi House loses CS and RET. Nothing has changed yet.
3. Click **Record this absence and regenerate**. Show the short list of changes.
4. Click **Open the draft**. The line under the month says how many days changed, and they are outlined in orange. A backup now covers CS, and RET is still a named gap, because it has no backup.

**Scenario B: one of three people is unavailable.**

Test Riya Chawla on the same date. Ember Candles CS stays covered by Kabir ("still covered"), and only NDR is exposed. Say: "The system works out whether the others can keep coverage."

## 5. Manual edit with live validation (20 seconds)

Back on **Roster**, click any working cell and change the status to Unavailable. The panel shows which gaps it would create before anything is saved. Click **Cancel**.

## 6. Compare, approve, publish, notify, export (45 seconds)

1. Go to **Compare plans** and generate all three, or show an earlier run. Coverage is equal, and fairness and preferences differ. Pause the recording while it solves (about 40 seconds).
2. On **Roster**, click **Override** on one gap and record a reason. Pause the recording, override the rest, and resume. The progress strip moves to **Pod lead review**.
3. Click **Send to pod leads** in the progress strip.
4. Switch **View as** to a pod lead, go to **Approvals**, and approve one pod. Say that a pod lead can only decide for their own pod.
5. Switch back to operations manager and approve the others with a note.
6. Click **Approve and publish**. On **Roster**, all four steps now show as done.
7. If time allows: edit a day on the published roster. It creates a new draft version, and the published one stays live. Publish it, then show **Activity**: who changed and what. If you are near 5 minutes, say this instead of showing it.
8. Open **Export** and choose **Excel**.

## Close (15 seconds)

"The solver proposes, the validator checks, and a person decides. It runs entirely on free tiers, and the README explains the assumptions and trade-offs."
