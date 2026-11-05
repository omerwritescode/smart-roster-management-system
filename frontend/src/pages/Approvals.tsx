import { useState } from "react";
import { api, type Pod } from "../api";
import { useAction, useApp, useRoster } from "../state";
import { PLAN_LABEL, ROSTER_STATUS, formatTime, monthLabel } from "../lib";

function PodRow({ pod, rosterId, decision, inReview }: { pod: Pod; rosterId: string; decision?: { decision: string; actor: string; note: string }; inReview: boolean }) {
  const { actor, names, canManage } = useApp();
  const [note, setNote] = useState("");
  const decide = useAction((approve: boolean) => api.post(`/rosters/${rosterId}/pod-decision`, { pod_id: pod.id, approve, note }), {
    success: "Decision recorded.", onDone: () => setNote(""),
  });
  const mine = actor.role === "pod_lead" && actor.podId === pod.id;
  const behalf = actor.role === "ops_manager";
  const can = inReview && canManage && (mine || behalf);
  return (
    <tr>
      <td><b>{pod.name}</b><br /><span className="faint">{names!.employee(pod.lead_employee_id) || "No pod lead set"}</span></td>
      <td>
        {decision ? <span className={`tag ${decision.decision === "approved" ? "good" : "blocker"}`}>{decision.decision}</span> : <span className="muted small">Not decided</span>}
        {decision?.note && <p className="small muted">{decision.note}</p>}
        {decision && <p className="faint">{decision.actor}</p>}
      </td>
      <td>
        {can && decision?.decision !== "approved" && (
          <div className="stack">
            <input type="text" aria-label={`Note for ${pod.name}`} placeholder={behalf ? "Note required when approving for a pod lead" : "Note, required to request changes"} value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="row">
              <button className="btn tiny primary" disabled={decide.isPending} onClick={() => decide.mutate(true)}>{behalf ? "Approve for this pod lead" : "Approve"}</button>
              <button className="btn tiny" disabled={decide.isPending} onClick={() => decide.mutate(false)}>Request changes</button>
            </div>
          </div>
        )}
      </td>
    </tr>
  );
}

export function ApprovalsPage() {
  const { rosterId, setup, month, isOps, go, rosters, openRoster } = useApp();
  const roster = useRoster(rosterId);
  const [note, setNote] = useState("");
  const submit = useAction((id: string) => api.post(`/rosters/${id}/submit`), { success: "Sent to pod leads for review." });
  const publish = useAction((id: string) => api.post<{ changes: number; comp_offs_earned: number }>(`/rosters/${id}/publish`), {
    success: (r) => `Published. ${r.comp_offs_earned} comp-off(s) earned${r.changes ? ` and ${r.changes} day(s) changed from the last version` : ""}.`,
  });
  const reject = useAction((id: string) => api.post(`/rosters/${id}/ops-reject`, { note }), { success: "Sent back as a draft.", onDone: () => setNote("") });

  const detail = roster.data;
  if (!rosterId) {
    return (
      <div className="panel empty">
        <h2>No roster for {monthLabel(month)} yet</h2>
        <button className="btn primary" onClick={() => go("board")}>Go to the roster</button>
      </div>
    );
  }
  if (!detail) return <div className="loading"><span className="spinner" />Loading the roster</div>;

  const r = detail.roster;
  const blockers = detail.issues.filter((i) => i.severity === "blocker");
  const open = blockers.filter((i) => !i.override_reason);
  const decisions = new Map(detail.approvals.filter((a) => a.stage === "pod_review" && a.pod_id).map((a) => [a.pod_id!, a]));

  return (
    <div className="stack">
      <div className="spread">
        <div>
          <h1>Approve {monthLabel(month)}</h1>
          <p className="muted">Version {r.version}, {PLAN_LABEL[r.plan_label] ?? r.plan_label}. Status: {ROSTER_STATUS[r.status]}.</p>
        </div>
        <label className="field"><span>Version</span>
          <select value={rosterId} onChange={(e) => openRoster(e.target.value)}>
            {rosters.map((x) => <option key={x.id} value={x.id}>Version {x.version}: {ROSTER_STATUS[x.status]}</option>)}
          </select>
        </label>
      </div>

      <section className="panel stack">
        <h2>1. Clear the blockers</h2>
        {blockers.length === 0 && <div className="notice good"><b>No blockers.</b> Coverage and mandatory rules are met.</div>}
        {blockers.length > 0 && open.length === 0 && <div className="notice good"><b>All {blockers.length} blockers have a written override.</b> The reasons are kept on the record.</div>}
        {open.length > 0 && (
          <div className="notice error">
            <b>{open.length} of {blockers.length} blockers are still open.</b> Fix each one or record an override with a reason. Publishing stays locked until then.
            <div style={{ marginTop: 6 }}><button className="btn tiny" onClick={() => go("board")}>Open the roster to fix them</button></div>
          </div>
        )}
      </section>

      <section className="panel stack">
        <div className="spread">
          <h2>2. Pod lead review</h2>
          {r.status === "draft" && isOps && <button className="btn primary" disabled={submit.isPending} onClick={() => submit.mutate(r.id)}>Send to pod leads</button>}
        </div>
        {r.status === "draft" && !isOps && <p className="muted small">The operations manager sends this for review.</p>}
        <div className="tablewrap">
          <table className="data">
            <thead><tr><th>Pod</th><th>Decision</th><th /></tr></thead>
            <tbody>
              {setup!.pods.map((p) => <PodRow key={p.id} pod={p} rosterId={r.id} decision={decisions.get(p.id)} inReview={r.status === "pod_review"} />)}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel stack">
        <h2>3. Operations approval and publishing</h2>
        {r.status === "published" && <div className="notice good"><b>This roster is live.</b> Published {r.published_at ? formatTime(r.published_at) : ""}. Any later edit creates a new version, and this one stays live until that is published.</div>}
        {r.status === "superseded" && <div className="notice">A later version replaced this one.</div>}
        {!["ops_review", "published", "superseded"].includes(r.status) && <p className="muted small">Available after every pod lead approves.</p>}
        {r.status === "ops_review" && !isOps && <p className="muted small">Waiting for the operations manager.</p>}
        {r.status === "ops_review" && isOps && (
          <div className="stack">
            <div className="row">
              <button className="btn primary" disabled={open.length > 0 || publish.isPending} onClick={() => publish.mutate(r.id)}>
                {publish.isPending ? "Publishing" : "Approve and publish"}
              </button>
              {open.length > 0 && <span className="small" style={{ color: "var(--gap)" }}>Locked: {open.length} blocker(s) still open.</span>}
            </div>
            <label className="field"><span>Or send it back, saying what needs to change</span>
              <input type="text" value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <div><button className="btn tiny" disabled={reject.isPending} onClick={() => reject.mutate(r.id)}>Send back to draft</button></div>
          </div>
        )}
      </section>

      <section className="stack">
        <h2>History for this version</h2>
        <div className="tablewrap">
          <table className="data">
            <thead><tr><th>When</th><th>Stage</th><th>Who</th><th>Decision</th><th>Note</th></tr></thead>
            <tbody>
              {detail.approvals.map((a) => (
                <tr key={a.id}><td className="small">{formatTime(a.created_at)}</td><td className="small">{a.stage.replace("_", " ")}</td><td>{a.actor}</td><td>{a.decision}</td><td className="small">{a.note}</td></tr>
              ))}
              {detail.approvals.length === 0 && <tr><td colSpan={5} className="muted small">Nothing yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
