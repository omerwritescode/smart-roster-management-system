import { useState } from "react";
import { api, type Metrics, type PlanResult, type RosterRow } from "../api";
import { useAction, useApp } from "../state";
import { PLAN_LABEL, ROSTER_STATUS, formatTime, monthLabel } from "../lib";
import { PageHeader } from "../components/Layout";

type Metric = { key: keyof Metrics; label: string; better: "high" | "low"; suffix?: string; help: string };
const ROWS: Metric[] = [
  { key: "coverage_pct", label: "Required slots covered", better: "high", suffix: "%", help: "Mandatory. Every plan aims for the same maximum." },
  { key: "gap_slots", label: "Uncovered slots", better: "low", help: "Staffing slots nobody can fill." },
  { key: "blockers", label: "Blockers", better: "low", help: "Must be fixed or overridden before publishing." },
  { key: "preferences_honoured_pct", label: "Preferred days off honoured", better: "high", suffix: "%", help: "Share of requested days off that were given." },
  { key: "sunday_holiday_spread", label: "Sunday and holiday gap between people", better: "low", suffix: " days", help: "Most loaded person minus least loaded person." },
  { key: "backup_days", label: "Backup days used", better: "low", help: "Person-days of cover duty." },
  { key: "peak_backup_days", label: "Most backup days for one person", better: "low", help: "How concentrated cover duty is." },
  { key: "stretch_days", label: "Days above 100% workload", better: "low", help: "Days someone is stretched to cover." },
  { key: "warnings", label: "Warnings", better: "low", help: "Preferences or fairness aims that were missed." },
];

export function PlansPage() {
  const { month, rosters, isOps, openRoster, go } = useApp();
  const [picked, setPicked] = useState<string[] | null>(null);
  const compare = useAction(() => api.post<PlanResult[]>("/rosters/compare", { month }), {
    success: "Three plans generated and saved as drafts.",
    onDone: (r) => setPicked(r.map((x) => x.roster_id)),
  });

  const fallback = rosters.slice(0, 3).map((r) => r.id);
  const selected: RosterRow[] = (picked ?? fallback).map((id) => rosters.find((r) => r.id === id)).filter((r): r is RosterRow => !!r);

  function best(metric: Metric) {
    const values = selected.map((r) => Number(r.metrics?.[metric.key] ?? 0));
    if (values.length < 2 || new Set(values).size < 2) return null;
    return metric.better === "high" ? Math.max(...values) : Math.min(...values);
  }

  return (
    <div className="stack">
      <PageHeader
        title={`Compare plans for ${monthLabel(month)}`}
        intro="Every plan keeps the same mandatory rules and fills the same number of required slots. They differ in how they use the freedom left over: fairness, preferences or backup use. The best value in each row is highlighted."
        actions={isOps && (
          <button className="btn primary" disabled={compare.isPending} onClick={() => compare.mutate(undefined)}>
            {compare.isPending ? <><span className="spinner" />Solving three plans, about 40 seconds</> : "Generate all three plans"}
          </button>
        )}
      />

      {selected.length === 0 ? (
        <div className="panel empty">
          <h2>No plans to compare yet</h2>
          <p className="muted">{isOps ? "Generate all three plans to see them side by side." : "Switch role to operations manager to generate plans."}</p>
        </div>
      ) : (
        <div className="tablewrap">
          <table className="data">
            <thead>
              <tr>
                <th>Measure</th>
                {selected.map((r) => <th key={r.id}>{PLAN_LABEL[r.plan_label] ?? r.plan_label}<br /><span className="faint">Version {r.version}, {ROSTER_STATUS[r.status]}</span></th>)}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((metric) => {
                const top = best(metric);
                return (
                  <tr key={metric.key}>
                    <td title={metric.help}>{metric.label}<br /><span className="faint">{metric.help}</span></td>
                    {selected.map((r) => {
                      const value = Number(r.metrics?.[metric.key] ?? 0);
                      return <td key={r.id} className={top !== null && value === top ? "bestcell" : ""}>{value}{metric.suffix ?? ""}</td>;
                    })}
                  </tr>
                );
              })}
              <tr>
                <td>Overall score<br /><span className="faint">70% coverage, 10% each for preferences, fairness and stretch.</span></td>
                {selected.map((r) => <td key={r.id}><b>{r.metrics?.score}</b></td>)}
              </tr>
              <tr>
                <td />
                {selected.map((r) => <td key={r.id}><button className="btn tiny" onClick={() => { openRoster(r.id); go("board"); }}>Open this plan</button></td>)}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {rosters.length > 0 && (
        <div className="stack">
          <h2>All versions this month</h2>
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Compare</th><th>Version</th><th>Plan</th><th>Status</th><th>Coverage</th><th>Blockers</th><th>Created</th><th>Note</th></tr></thead>
              <tbody>
                {rosters.map((r) => {
                  const current = picked ?? fallback;
                  return (
                    <tr key={r.id}>
                      <td><input type="checkbox" aria-label={`Compare version ${r.version}`} checked={current.includes(r.id)}
                        onChange={() => setPicked(current.includes(r.id) ? current.filter((x) => x !== r.id) : [...current, r.id].slice(-4))} /></td>
                      <td className="tnum">{r.version}</td>
                      <td>{PLAN_LABEL[r.plan_label] ?? r.plan_label}</td>
                      <td>{ROSTER_STATUS[r.status]}</td>
                      <td>{r.metrics?.coverage_pct}%</td>
                      <td className="tnum">{r.metrics?.blockers}</td>
                      <td className="small">{formatTime(r.created_at)}</td>
                      <td className="small">{r.summary}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
