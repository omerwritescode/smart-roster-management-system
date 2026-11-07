import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AbsenceImpact, type Change, type Leave, type LedgerEntry } from "../api";
import { useAction, useApp } from "../state";
import { LEAVE_LABEL, STATUS_LABEL, formatDay, monthLabel } from "../lib";
import { Sheet } from "../components/Sheets";
import { PageHeader } from "../components/Layout";

interface Decision { status: string; regenerated: boolean; roster_id?: string; summary?: string; changes?: Change[]; based_on_version?: number }

export function ChangeList({ changes }: { changes: Change[] }) {
  if (changes.length === 0) return <p className="muted small">No days changed.</p>;
  const describe = (status: string | null, labels: string[]) => (status === "work" ? labels.join(", ") || "Working" : STATUS_LABEL[status ?? ""] ?? "Nothing");
  return (
    <div className="tablewrap">
      <table className="data">
        <thead><tr><th>Employee</th><th>Date</th><th>From</th><th>To</th></tr></thead>
        <tbody>
          {changes.map((c) => (
            <tr key={`${c.employee_id}${c.date}`}>
              <td>{c.employee}</td>
              <td className="tnum">{formatDay(c.date)}</td>
              <td className="small">{describe(c.from_status, c.from_labels)}</td>
              <td className="small">{describe(c.to_status, c.to_labels)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WhatIf() {
  const { setup, month, canManage, actor, openRoster, go, rosterId } = useApp();
  const employees = setup!.employees.filter((e) => e.active);
  const [employee, setEmployee] = useState(employees[0]?.id ?? "");
  const [start, setStart] = useState(`${month}-17`);
  const [end, setEnd] = useState(`${month}-17`);
  const [type, setType] = useState("unavailable");
  const [asked, setAsked] = useState<string | null>(null);
  const [result, setResult] = useState<Decision | null>(null);
  const query = `/impact/absence?employee_id=${employee}&start=${start}&end=${end}&leave_type=${type}${rosterId ? `&roster_id=${rosterId}` : ""}`;
  const impact = useQuery({ queryKey: ["impact", asked], queryFn: () => api.get<AbsenceImpact>(asked!), enabled: !!asked });
  const apply = useAction(async () => {
    const leave = await api.post<Leave>("/leaves", { employee_id: employee, leave_type: type, start_date: start, end_date: end, reason: "Recorded from the impact check" });
    return api.post<Decision>(`/leaves/${leave.id}/decision`, { status: "approved", regenerate: true, roster_id: rosterId });
  }, { onDone: (r) => { setResult(r); setAsked(null); } });
  const data = impact.data;
  const person = employees.find((e) => e.id === employee)?.name;

  return (
    <section className="panel stack">
      <div>
        <h2>Test an absence</h2>
        <p className="muted small">See what happens to every brand before anything changes. This uses the roster version open on the Roster page.</p>
      </div>
      <div className="formgrid">
        <label className="field"><span>Employee</span>
          <select value={employee} onChange={(e) => { setEmployee(e.target.value); setAsked(null); }}>{employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
        </label>
        <label className="field"><span>From</span><input type="date" value={start} onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); setAsked(null); }} /></label>
        <label className="field"><span>To</span><input type="date" value={end} min={start} onChange={(e) => { setEnd(e.target.value); setAsked(null); }} /></label>
        <label className="field"><span>Type</span>
          <select value={type} onChange={(e) => { setType(e.target.value); setAsked(null); }}>{Object.entries(LEAVE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </label>
        <button className="btn primary" onClick={() => { setResult(null); setAsked(query); }}>Check impact</button>
      </div>
      {impact.isFetching && <p className="muted small"><span className="spinner" />Rechecking every rule without {person}</p>}
      {impact.error && <div className="notice error small">{(impact.error as Error).message}</div>}
      {data && !impact.isFetching && asked && (
        <div className="stack">
          {data.gap_count > 0 ? (
            <div className="notice error">
              <b>{data.employee} being away leaves {data.gap_count} gap(s) at {data.brands_affected.length} brand(s): {data.brands_affected.join(", ")}.</b>
              {data.gaps.slice(0, 10).map((g) => <p className="small" key={g.key}>{g.message}</p>)}
            </div>
          ) : (
            <div className="notice good"><b>{data.employee} can be away. Every brand keeps its required coverage.</b></div>
          )}
          {data.coverage_still_met.length > 0 && (
            <div className="notice good small">
              <b>Still covered without {data.employee}:</b>
              {data.coverage_still_met.slice(0, 8).map((c) => <p key={c.process + c.date}>{c.process}, {formatDay(c.date)}: {c.staffed} of {c.required} staffed by the others.</p>)}
            </div>
          )}
          {data.other_new_issues.length > 0 && (
            <div className="notice warn small"><b>Also worth a look:</b>{data.other_new_issues.slice(0, 5).map((i) => <p key={i.key}>{i.message}</p>)}</div>
          )}
          {canManage && (
            <div className="row">
              <button className="btn primary" disabled={apply.isPending} onClick={() => apply.mutate(undefined)}>
                {apply.isPending ? <><span className="spinner" />Regenerating</> : "Record this absence and regenerate"}
              </button>
              <span className="faint">Approves the absence as {actor.name} and builds a new draft with as few changes as possible. Nothing is published.</span>
            </div>
          )}
        </div>
      )}
      {result?.regenerated && <RegeneratedPanel result={result} onOpen={() => { openRoster(result.roster_id!); go("board"); }} />}
      {result && !result.regenerated && <div className="notice">Saved. There is no roster for that month to regenerate yet.</div>}
    </section>
  );
}

function RegeneratedPanel({ result, onOpen }: { result: Decision; onOpen: () => void }) {
  return (
    <div className="stack">
      <div className="notice good">
        <b>New draft ready.</b> {result.summary}
        <div style={{ marginTop: 6 }}><button className="btn tiny" onClick={onOpen}>Open the draft</button></div>
      </div>
      <h3>What changed from version {result.based_on_version}</h3>
      <ChangeList changes={result.changes ?? []} />
    </div>
  );
}

export function AvailabilityPage() {
  const { setup, names, canManage, actor, month, go, openRoster, rosterId } = useApp();
  const [form, setForm] = useState({ employee_id: actor.employeeId ?? setup!.employees[0]?.id ?? "", leave_type: "planned", start_date: `${month}-10`, end_date: `${month}-10`, reason: "" });
  const [decision, setDecision] = useState<Decision | null>(null);
  const [ledgerFor, setLedgerFor] = useState<string | null>(null);
  const create = useAction((input: typeof form) => api.post("/leaves", input), { success: "Request added as pending. It changes nothing until approved." });
  const decide = useAction((input: { id: string; status: string }) => api.post<Decision>(`/leaves/${input.id}/decision`, { status: input.status, regenerate: true, roster_id: rosterId }), {
    success: (r) => (r.regenerated ? "Decision saved and a new draft was built." : `Request marked ${r.status}.`),
    onDone: (r) => { if (r.regenerated) setDecision(r); },
  });
  const remove = useAction((id: string) => api.del(`/leaves/${id}`), { success: "Request deleted." });
  const ledger = useQuery({ queryKey: ["ledger", ledgerFor], queryFn: () => api.get<LedgerEntry[]>(`/comp-offs/${ledgerFor}`), enabled: !!ledgerFor });

  const visible = actor.role === "employee" ? setup!.leaves.filter((l) => l.employee_id === actor.employeeId) : setup!.leaves;
  const pending = visible.filter((l) => l.status === "pending");
  const others = visible.filter((l) => l.status !== "pending");
  const balances = setup!.employees.filter((e) => (setup!.comp_off_balances[e.id] ?? 0) !== 0);

  const row = (l: Leave) => (
    <tr key={l.id}>
      <td>{names!.employee(l.employee_id)}</td>
      <td>{LEAVE_LABEL[l.leave_type]}</td>
      <td className="tnum">{formatDay(l.start_date)}{l.end_date !== l.start_date ? ` to ${formatDay(l.end_date)}` : ""}</td>
      <td className="small">{l.reason}</td>
      <td><span className={`tag ${l.status === "approved" ? "good" : l.status === "rejected" ? "" : "warning"}`}>{l.status}</span></td>
      <td>
        {canManage && (
          <span className="row">
            {l.status !== "approved" && <button className="btn tiny" disabled={decide.isPending} onClick={() => decide.mutate({ id: l.id, status: "approved" })}>Approve</button>}
            {l.status === "pending" && <button className="btn tiny" disabled={decide.isPending} onClick={() => decide.mutate({ id: l.id, status: "rejected" })}>Reject</button>}
            {l.status === "approved" && <button className="btn tiny" disabled={decide.isPending} onClick={() => decide.mutate({ id: l.id, status: "rejected" })}>Cancel leave</button>}
            <button className="btn tiny" onClick={() => { if (window.confirm("Delete this request?")) remove.mutate(l.id); }}>Delete</button>
          </span>
        )}
      </td>
    </tr>
  );

  return (
    <div className="stack">
      <PageHeader
        title={`Availability for ${monthLabel(month)}`}
        intro="Test what an absence would do before deciding, then approve or reject requests. Approving leave builds a new draft roster with as few changes as possible; nothing goes live until it is published."
      />
      {decide.isPending && <div className="notice"><span className="spinner" />Saving the decision and regenerating the roster, up to 20 seconds</div>}
      <div className="cols">
      <div className="stack">
      {canManage && <WhatIf />}

      <section className="panel stack">
        <h2>Request time off</h2>
        <div className="formgrid">
          <label className="field"><span>Employee</span>
            <select value={form.employee_id} disabled={actor.role === "employee"} onChange={(e) => setForm({ ...form, employee_id: e.target.value })}>
              {setup!.employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </label>
          <label className="field"><span>Type</span>
            <select value={form.leave_type} onChange={(e) => setForm({ ...form, leave_type: e.target.value })}>{Object.entries(LEAVE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          </label>
          <label className="field"><span>From</span><input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value, end_date: e.target.value > form.end_date ? e.target.value : form.end_date })} /></label>
          <label className="field"><span>To</span><input type="date" value={form.end_date} min={form.start_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></label>
          <label className="field"><span>Reason</span><input type="text" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
          <button className="btn primary" disabled={create.isPending} onClick={() => create.mutate(form)}>Add request</button>
        </div>
      </section>
      </div>

      <div className="stack">
      <section className="stack">
        <h2>Waiting for a decision ({pending.length})</h2>
        {pending.length === 0 ? <p className="muted small">No requests are waiting.</p> : (
          <div className="tablewrap"><table className="data">
            <thead><tr><th>Employee</th><th>Type</th><th>Dates</th><th>Reason</th><th>Status</th><th>Decide</th></tr></thead>
            <tbody>{pending.map(row)}</tbody>
          </table></div>
        )}
      </section>

      <section className="stack">
        <h2>Decided</h2>
        <div className="tablewrap"><table className="data">
          <thead><tr><th>Employee</th><th>Type</th><th>Dates</th><th>Reason</th><th>Status</th><th>Change</th></tr></thead>
          <tbody>{others.map(row)}</tbody>
        </table></div>
      </section>

      <section className="stack">
        <h2>Comp-off balances</h2>
        <p className="muted small">Working a public holiday or through a weekly off earns one when the roster is published. Taking one spends it.</p>
        <div className="row">
          {balances.length === 0 && <span className="muted small">Nobody has a balance yet.</span>}
          {balances.map((e) => (
            <button className="btn tiny" key={e.id} onClick={() => setLedgerFor(e.id)}>{e.name}: {setup!.comp_off_balances[e.id]}</button>
          ))}
        </div>
      </section>
      </div>
      </div>

      {decision?.regenerated && (
        <Sheet title="New draft ready" subtitle={decision.summary} onClose={() => setDecision(null)} foot={
          <button className="btn primary" onClick={() => { openRoster(decision.roster_id!); setDecision(null); go("board"); }}>Open the draft</button>
        }>
          <p className="small muted">The system proposes this change. It stays a draft until someone approves and publishes it.</p>
          <h3>What changed from version {decision.based_on_version}</h3>
          <ChangeList changes={decision.changes ?? []} />
        </Sheet>
      )}
      {ledgerFor && (
        <Sheet title={`Comp-off history: ${names!.employee(ledgerFor)}`} onClose={() => setLedgerFor(null)}>
          {(ledger.data ?? []).map((l) => (
            <div className="personrow" key={l.id}><span>{formatDay(l.entry_date)}: {l.reason}</span><b className="tnum">{l.delta > 0 ? `+${l.delta}` : l.delta}</b></div>
          ))}
        </Sheet>
      )}
    </div>
  );
}
