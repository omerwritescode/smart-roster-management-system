import type { ReactNode } from "react";
import { api, type RosterDetail } from "../api";
import { useAction, useApp } from "../state";
import { cx, formatTime } from "../lib";

const STEPS = ["Generate", "Clear blockers", "Pod lead review", "Publish"];

interface Props {
  detail: RosterDetail;
  unresolved: number;
  onFirstBlocker: () => void;
  onShowIssues: (severity: "blocker" | "warning") => void;
}

/** One place that says where this roster is in its journey, and what to do next. */
export function NextStep({ detail, unresolved, onFirstBlocker, onShowIssues }: Props) {
  const { isOps, canManage, go, setup, rosters, openRoster, changeActor } = useApp();
  const r = detail.roster;
  const m = r.metrics;
  const submit = useAction((id: string) => api.post(`/rosters/${id}/submit`), { success: "Sent to pod leads for review." });
  const pods = setup!.pods;
  const approved = new Set(detail.approvals.filter((a) => a.stage === "pod_review" && a.decision === "approved" && a.pod_id).map((a) => a.pod_id));
  const waitingFor = pods.filter((p) => !approved.has(p.id)).map((p) => p.name);
  const latest = rosters.find((x) => ["draft", "pod_review", "ops_review"].includes(x.status)) ?? rosters.find((x) => x.status === "published");

  let current = 1;
  let text: ReactNode = null;
  let action: ReactNode = null;
  const opsOnly = !isOps && (
    <button className="btn" onClick={() => changeActor({ role: "ops_manager", name: "Operations manager" })}>Switch to operations manager</button>
  );

  if (r.status === "superseded") {
    current = 4;
    text = <>A newer version replaced this one. It stays here for the record.</>;
    action = latest && latest.id !== r.id && <button className="btn primary" onClick={() => openRoster(latest.id)}>Open version {latest.version}</button>;
  } else if (r.status === "published") {
    current = 4;
    text = <>This roster is live{r.published_at ? ` since ${formatTime(r.published_at)}` : ""}. Changing any day creates a new draft version, and this one stays live until that is published.</>;
    action = <a className="btn" href={`/api/rosters/${r.id}/export.xlsx`}>Export Excel</a>;
  } else if (r.status === "ops_review") {
    current = 3;
    text = <>Every pod lead has approved. The operations manager publishes it to make it live.</>;
    action = isOps ? <button className="btn primary" onClick={() => go("approvals")}>Go to publishing</button> : opsOnly;
  } else if (r.status === "pod_review") {
    current = 2;
    text = <>{approved.size} of {pods.length} pod leads have approved. Waiting for {waitingFor.join(", ") || "nobody"}.</>;
    action = <button className="btn primary" onClick={() => go("approvals")}>Open pod lead review</button>;
  } else if (unresolved > 0) {
    current = 1;
    const proved = r.solver?.fewest_gaps_proved && m.gap_slots > 0;
    text = (
      <>
        <b>{unresolved} {unresolved === 1 ? "blocker stops" : "blockers stop"} publishing.</b>{" "}
        {canManage ? "Fix each one by finding cover, or override it with a written reason." : "The operations manager is clearing these before the roster goes for review."}
        {proved && <> The solver proved no roster can do better, so the {m.gap_slots} unfilled slot(s) need a staffing decision.</>}
      </>
    );
    action = canManage ? (
      <>
        <button className="btn primary" onClick={onFirstBlocker}>Show the first blocker</button>
        <button className="btn" onClick={() => onShowIssues("blocker")}>See all {unresolved}</button>
      </>
    ) : (
      <button className="btn" onClick={() => onShowIssues("blocker")}>See what is blocking it</button>
    );
  } else {
    current = 2;
    text = <>Nothing blocks publishing. Send it to the pod leads to review their part.</>;
    action = isOps
      ? <button className="btn primary" disabled={submit.isPending} onClick={() => submit.mutate(r.id)}>Send to pod leads</button>
      : opsOnly;
  }

  const allDone = r.status === "published" || r.status === "superseded";
  return (
    <section className="nextstep" aria-label="Where this roster is and what to do next">
      <ol className="rail">
        {STEPS.map((label, i) => {
          const done = allDone || i < current;
          const now = !allDone && i === current;
          return (
            <li key={label} className={cx(done && "done", now && "now")} aria-current={now ? "step" : undefined}>
              <span className="dot" aria-hidden="true">{done ? "✓" : i + 1}</span>
              <span>{label}{i === 1 && !done && unresolved > 0 ? ` (${unresolved})` : ""}</span>
            </li>
          );
        })}
      </ol>
      <div className="nextstep-body">
        <p className="nextstep-text">{text}</p>
        <div className="row">{action}</div>
      </div>
      <dl className="stats">
        <div className={m.gap_slots > 0 ? "bad" : "ok"}><dt>Covered</dt><dd>{m.coverage_pct}%</dd></div>
        <div className={unresolved > 0 ? "bad" : "ok"}>
          <dt>Blockers</dt>
          <dd><button className="statbtn" onClick={() => onShowIssues("blocker")} title="Show blockers">{unresolved}</button></dd>
        </div>
        <div>
          <dt>Warnings</dt>
          <dd><button className="statbtn" onClick={() => onShowIssues("warning")} title="Show warnings">{m.warnings}</button></dd>
        </div>
        <div><dt>Backup days</dt><dd>{m.backup_days}</dd></div>
      </dl>
    </section>
  );
}
