import { useState } from "react";
import { api, type Issue, type RosterDetail } from "../api";
import { useAction, useApp } from "../state";
import { ISSUE_TITLE, cx, formatDay } from "../lib";
import type { SheetState } from "./Sheets";

const CAUSE_TAG: Record<string, string> = { weekly_off: "Weekly off clash", leave: "Leave clash", capacity: "No capacity", shift_clash: "Incompatible shifts" };

function IssueRow({ issue, detail, setSheet }: { issue: Issue; detail: RosterDetail; setSheet: (s: SheetState) => void }) {
  const { isOps, say } = useApp();
  const [overriding, setOverriding] = useState(false);
  const [reason, setReason] = useState("");
  const [explanation, setExplanation] = useState<{ text: string; source: string } | null>(null);
  const explain = useAction((key: string) => api.post<{ text: string; source: string }>(`/rosters/${detail.roster.id}/explain`, { key }), { onDone: setExplanation });
  const override = useAction((input: { key: string; reason: string }) => api.post(`/rosters/${detail.roster.id}/override`, input), {
    success: "Override recorded with your reason.",
    onDone: () => { setOverriding(false); setReason(""); },
  });
  const undo = useAction((key: string) => api.post(`/rosters/${detail.roster.id}/override/remove`, { key }), { success: "Override removed." });
  const date = issue.date?.slice(0, 10);
  const bp = issue.brand_process_id;

  return (
    <div className={cx("issue", issue.severity, issue.override_reason && "overridden")}>
      <div className="row" style={{ marginBottom: 2 }}>
        {date && <b className="issue-date">{formatDay(date)}</b>}
        {issue.override_reason && <span className="tag">Overridden</span>}
      </div>
      <p>{issue.message}</p>
      {issue.suggestion && !issue.override_reason && <p className="faint">{issue.suggestion}</p>}
      {issue.override_reason && <p className="faint">Reason: {issue.override_reason} ({issue.overridden_by})</p>}
      {explanation && (
        <div className="explain small">
          {explanation.text}
          <p className="faint">{explanation.source === "gemini" ? "Worded by Gemini from the validator's facts." : "Built from the validator's facts."}</p>
        </div>
      )}
      {overriding && (
        <div className="stack" style={{ marginTop: 6 }}>
          <label className="field"><span>Why is it acceptable to publish with this?</span>
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: client agreed to pause this process on this day" />
          </label>
          <div className="row">
            <button className="btn tiny primary" disabled={override.isPending} onClick={() => {
              if (reason.trim().length < 5) { say("Write a reason of at least 5 characters.", "error"); return; }
              override.mutate({ key: issue.key, reason });
            }}>Record override</button>
            <button className="btn tiny" onClick={() => setOverriding(false)}>Cancel</button>
          </div>
        </div>
      )}
      <div className="actions">
        {bp && date && <button className="btn link small" onClick={() => setSheet({ kind: "process", brandProcessId: bp, date })}>{issue.category === "coverage" ? "Find cover" : "Open process"}</button>}
        {!bp && issue.employee_id && date && <button className="btn link small" onClick={() => setSheet({ kind: "employee", employeeId: issue.employee_id!, date })}>Open this day</button>}
        {!explanation && <button className="btn link small" disabled={explain.isPending} onClick={() => explain.mutate(issue.key)}>{explain.isPending ? "Explaining" : "Explain"}</button>}
        {issue.severity === "blocker" && isOps && !issue.override_reason && !overriding && <button className="btn link small" onClick={() => setOverriding(true)}>Override</button>}
        {issue.override_reason && isOps && <button className="btn link small" onClick={() => undo.mutate(issue.key)}>Remove override</button>}
      </div>
    </div>
  );
}

export type Severity = "blocker" | "warning" | "info";

interface Group { key: string; title: string; issues: Issue[]; causes: string[]; first: string }

function groupIssues(issues: Issue[], names: NonNullable<ReturnType<typeof useApp>["names"]>): Group[] {
  const groups = new Map<string, Group>();
  for (const i of issues) {
    const byProcess = i.category === "coverage" && i.brand_process_id && i.code !== "MULTI_BRAND_IMPACT";
    const key = byProcess ? `bp:${i.brand_process_id}` : `code:${i.code}`;
    const title = byProcess ? names.process(i.brand_process_id!) : ISSUE_TITLE[i.code] ?? i.code.replace(/_/g, " ").toLowerCase();
    const g = groups.get(key) ?? { key, title, issues: [], causes: [], first: i.date ?? "9999" };
    g.issues.push(i);
    for (const c of i.facts.causes ?? []) if (!g.causes.includes(c)) g.causes.push(c);
    if ((i.date ?? "9999") < g.first) g.first = i.date ?? "9999";
    groups.set(key, g);
  }
  return [...groups.values()].sort((a, b) => a.first.localeCompare(b.first) || a.title.localeCompare(b.title));
}

function IssueGroup({ group, detail, setSheet, open }: { group: Group; detail: RosterDetail; setSheet: (s: SheetState) => void; open: boolean }) {
  const overridden = group.issues.filter((i) => i.override_reason).length;
  const isGap = group.key.startsWith("bp:");
  const count = group.issues.length;
  return (
    <details className="igroup" open={open}>
      <summary>
        <span className="igroup-title">{group.title}</span>
        <span className="igroup-meta">
          {isGap ? `short on ${count} day${count === 1 ? "" : "s"}` : `${count}`}
          {overridden > 0 && `, ${overridden} overridden`}
        </span>
        {group.causes.length > 0 && (
          <span className="igroup-tags">{group.causes.map((c) => <span className="tag blocker" key={c}>{CAUSE_TAG[c] ?? c}</span>)}</span>
        )}
      </summary>
      {group.issues.slice(0, 60).map((i) => <IssueRow key={i.key} issue={i} detail={detail} setSheet={setSheet} />)}
      {count > 60 && <p className="faint" style={{ padding: "6px 12px" }}>And {count - 60} more of the same kind.</p>}
    </details>
  );
}

export function IssuesPanel({ detail, scope, setSheet, filter, setFilter, onHide }: {
  detail: RosterDetail; scope: { employeeId?: string; podId?: string; brandId?: string }; setSheet: (s: SheetState) => void;
  filter: Severity; setFilter: (f: Severity) => void; onHide: () => void;
}) {
  const { setup, names } = useApp();
  const employeesInPod = new Set(setup!.employees.filter((e) => e.pod_id === scope.podId).map((e) => e.id));
  const bpOf = new Map(setup!.brand_processes.map((b) => [b.id, b.brand_id]));
  const brandPod = new Map(setup!.brands.map((b) => [b.id, b.pod_id]));
  const inScope = (i: Issue) => {
    const brand = i.brand_id ?? (i.brand_process_id ? bpOf.get(i.brand_process_id) : undefined);
    if (scope.employeeId) {
      if (i.employee_id === scope.employeeId) return true;
      return (i.facts.allocated_people ?? []).some((p) => (p as unknown as { employee_id: string }).employee_id === scope.employeeId);
    }
    if (scope.brandId) return brand === scope.brandId;
    if (scope.podId) return (i.employee_id && employeesInPod.has(i.employee_id)) || (!!brand && brandPod.get(brand) === scope.podId);
    return true;
  };
  const scoped = detail.issues.filter(inScope);
  const overriddenCount = scoped.filter((i) => i.severity === "blocker" && i.override_reason).length;
  const counts = {
    blocker: scoped.filter((i) => i.severity === "blocker" && !i.override_reason).length,
    warning: scoped.filter((i) => i.severity === "warning").length,
    info: scoped.filter((i) => i.severity === "info").length,
  };
  const groups = groupIssues(scoped.filter((i) => i.severity === filter), names!);
  const filters: [Severity, string, number][] = [["blocker", "Blockers", counts.blocker], ["warning", "Warnings", counts.warning], ["info", "Notes", counts.info]];
  const scoped_note = scope.employeeId || scope.podId || scope.brandId ? "Showing only what affects the current view." : null;
  const help: Record<Severity, string> = {
    blocker: "These stop publishing. Find cover, or override with a written reason.",
    warning: "Worth a look, but they do not stop publishing.",
    info: "Context only. Nothing to do.",
  };
  return (
    <section className="panel issues" aria-label="Issues to review">
      <div className="issues-head">
        <div className="spread">
          <h2>To review</h2>
          <button className="btn tiny" onClick={onHide} title="Give the roster the full width">Hide</button>
        </div>
        <div className="seg" role="tablist" aria-label="Issue severity">
          {filters.map(([id, label, n]) => (
            <button key={id} role="tab" aria-selected={filter === id} className={id} onClick={() => setFilter(id)}>
              {label} <b>{n}</b>
            </button>
          ))}
        </div>
        <p className="faint">
          {help[filter]}
          {filter === "blocker" && overriddenCount > 0 && ` ${overriddenCount} more already have an override and are listed for the record.`}
          {scoped_note && ` ${scoped_note}`}
        </p>
      </div>
      {groups.length === 0 && (
        <p className="muted small" style={{ padding: 14 }}>
          {filter === "blocker" ? "Nothing blocks publishing here." : "Nothing here."}
        </p>
      )}
      {groups.map((g, n) => <IssueGroup key={g.key} group={g} detail={detail} setSheet={setSheet} open={groups.length <= 3 || n === 0} />)}
    </section>
  );
}
