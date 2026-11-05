import { useState } from "react";
import { api, type Issue, type RosterDetail } from "../api";
import { useAction, useApp } from "../state";
import { cx } from "../lib";
import type { SheetState } from "./Sheets";

const CAUSE_TAG: Record<string, string> = { weekly_off: "Weekly off clash", leave: "Leave clash", capacity: "No capacity", shift_clash: "Incompatible shifts" };
type Filter = "blocker" | "warning" | "info";

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
        {(issue.facts.causes ?? []).map((c) => <span className="tag blocker" key={c}>{CAUSE_TAG[c] ?? c}</span>)}
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

export function IssuesPanel({ detail, scope, setSheet }: { detail: RosterDetail; scope: { employeeId?: string; podId?: string; brandId?: string }; setSheet: (s: SheetState) => void }) {
  const { setup } = useApp();
  const [filter, setFilter] = useState<Filter>("blocker");
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
  const counts = {
    blocker: scoped.filter((i) => i.severity === "blocker").length,
    warning: scoped.filter((i) => i.severity === "warning").length,
    info: scoped.filter((i) => i.severity === "info").length,
  };
  const shown = scoped.filter((i) => i.severity === filter);
  const filters: [Filter, string][] = [["blocker", `Blockers ${counts.blocker}`], ["warning", `Warnings ${counts.warning}`], ["info", `Notes ${counts.info}`]];
  return (
    <section className="panel issues" style={{ padding: 0 }} aria-label="Issues to review">
      <div className="issues-head">
        <h2>Before publishing</h2>
        <div className="tabs" role="tablist" aria-label="Issue severity">
          {filters.map(([id, label]) => <button key={id} role="tab" aria-selected={filter === id} onClick={() => setFilter(id)}>{label}</button>)}
        </div>
      </div>
      {shown.length === 0 && (
        <p className="muted small" style={{ padding: 12 }}>
          {filter === "blocker" ? "No blockers here. Coverage and mandatory rules are met." : "Nothing to review here."}
        </p>
      )}
      {shown.slice(0, 120).map((i) => <IssueRow key={i.key} issue={i} detail={detail} setSheet={setSheet} />)}
    </section>
  );
}
