import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type CoverOption, type Edit, type Preview, type Recommendation, type RosterDetail } from "../api";
import { useAction, useApp } from "../state";
import { CALENDAR_LABEL, STATUS_LABEL, cx, formatDay, formatLongDay, shiftHours } from "../lib";

export type SheetState =
  | { kind: "day"; date: string }
  | { kind: "employee"; employeeId: string; date: string }
  | { kind: "process"; brandProcessId: string; date: string };

export function Sheet({ title, subtitle, onClose, children, foot }: { title: string; subtitle?: string; onClose: () => void; children: ReactNode; foot?: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div className="sheet-back" onClick={onClose} />
      <aside className="sheet" role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <div><h2>{title}</h2>{subtitle && <p className="muted small">{subtitle}</p>}</div>
          <button className="btn tiny" onClick={onClose} autoFocus>Close</button>
        </header>
        <div className="body">{children}</div>
        {foot && <div className="foot">{foot}</div>}
      </aside>
    </>
  );
}

export function useSaveEdits(detail: RosterDetail, onDone: () => void) {
  const { openRoster, say } = useApp();
  return useAction((input: { edits: Edit[]; reason?: string }) =>
    api.post<{ roster_id: string; new_version: boolean; changes: unknown[] }>(`/rosters/${detail.roster.id}/edit`, input), {
    onDone: (r) => {
      if (r.new_version) {
        openRoster(r.roster_id);
        say("Saved as a new draft version. The published roster stays live until this one is approved.");
      } else {
        say(`Saved. ${r.changes.length} day(s) changed and rechecked.`);
      }
      onDone();
    },
  });
}

function ImpactList({ preview }: { preview: Preview }) {
  const clean = preview.introduced.length === 0 && preview.resolved.length === 0;
  return (
    <div className="stack small">
      {clean && <p className="muted">This change adds no new issues and clears none.</p>}
      {preview.resolved.length > 0 && (
        <div className="notice good"><b>This fixes {preview.resolved.length}:</b>
          {preview.resolved.slice(0, 6).map((i) => <p key={i.key}>{i.message}</p>)}
        </div>
      )}
      {preview.introduced.filter((i) => i.severity === "blocker").length > 0 && (
        <div className="notice error"><b>This creates {preview.introduced.filter((i) => i.severity === "blocker").length} blocker(s):</b>
          {preview.introduced.filter((i) => i.severity === "blocker").slice(0, 8).map((i) => <p key={i.key}>{i.message}</p>)}
        </div>
      )}
      {preview.introduced.filter((i) => i.severity === "warning").length > 0 && (
        <div className="notice warn"><b>And {preview.introduced.filter((i) => i.severity === "warning").length} warning(s):</b>
          {preview.introduced.filter((i) => i.severity === "warning").slice(0, 6).map((i) => <p key={i.key}>{i.message}</p>)}
        </div>
      )}
      {preview.earns_comp_off.length > 0 && <div className="notice"><b>Comp-off:</b> working through this weekly off earns a comp-off when the roster is published.</div>}
      <p className="faint">Blockers on this roster: {preview.blockers_before} now, {preview.blockers_after} after this change.</p>
    </div>
  );
}

export function EmployeeDaySheet({ detail, employeeId, date, onClose }: { detail: RosterDetail; employeeId: string; date: string; onClose: () => void }) {
  const { names, setup, canManage, go } = useApp();
  const day = detail.days.find((d) => d.employee_id === employeeId && d.date === date);
  const current = detail.assignments.filter((a) => a.employee_id === employeeId && a.date === date);
  const allocations = setup!.allocations.filter((a) => a.employee_id === employeeId);
  const [status, setStatus] = useState(day?.status ?? "idle");
  const [selected, setSelected] = useState<string[]>(current.map((a) => a.brand_process_id));
  const [reason, setReason] = useState("");
  const save = useSaveEdits(detail, onClose);
  const editable = canManage && detail.roster.status !== "superseded";

  const effective = status === "work" ? (selected.length ? "work" : "idle") : status;
  const edit: Edit = { employee_id: employeeId, date, status: effective, bp_ids: effective === "work" ? selected : [] };
  const changed = effective !== day?.status || [...edit.bp_ids].sort().join() !== current.map((a) => a.brand_process_id).sort().join();
  const previewQuery = useQuery({
    queryKey: ["preview", detail.roster.id, edit],
    queryFn: () => api.post<Preview>(`/rosters/${detail.roster.id}/preview`, { edits: [edit] }),
    enabled: changed && editable,
  });

  const toggle = (bp: string) => {
    setSelected((s) => (s.includes(bp) ? s.filter((x) => x !== bp) : [...s, bp]));
    setStatus("work");
  };
  const required = (bp: string) => detail.coverage.find((c) => c.brand_process_id === bp && c.date === date)?.required ?? 0;
  const dayIssues = detail.issues.filter((i) => i.employee_id === employeeId && i.date?.slice(0, 10) === date && i.severity !== "info");

  return (
    <Sheet title={names!.employee(employeeId)} subtitle={formatLongDay(date)} onClose={onClose} foot={editable && (
      <>
        {detail.roster.status === "published" && <span className="faint">Saving creates a new draft version.</span>}
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={!changed || save.isPending} onClick={() => save.mutate({ edits: [edit], reason })}>{save.isPending ? "Saving" : "Save change"}</button>
      </>
    )}>
      {day?.locked && <div className="notice">A person set this day by hand, so regenerating will keep it.</div>}
      {dayIssues.length > 0 && <div className="notice warn small">{dayIssues.map((i) => <p key={i.key}>{i.message}</p>)}</div>}
      <label className="field"><span>Status</span>
        <select value={status} disabled={!editable} onChange={(e) => setStatus(e.target.value)}>
          {Object.entries(STATUS_LABEL).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <div className="stack">
        <h3>Processes this person can work</h3>
        {allocations.length === 0 && <p className="muted small">Not allocated to anything yet. Add an allocation in Setup.</p>}
        {allocations.map((a) => {
          const bp = setup!.brand_processes.find((x) => x.id === a.brand_process_id);
          const need = required(a.brand_process_id);
          return (
            <label className="check" key={a.id}>
              <input type="checkbox" disabled={!editable} checked={status === "work" && selected.includes(a.brand_process_id)} onChange={() => toggle(a.brand_process_id)} />
              <span>
                {names!.process(a.brand_process_id)} <span className={cx("tag", a.role === "backup" && "cover")}>{a.role}</span>
                <br /><span className="faint">{a.workload_share}% of a day, {names!.shift(bp?.shift_id)} shift, {need > 0 ? `needs ${need} today` : "closed today"}</span>
              </span>
            </label>
          );
        })}
      </div>
      {editable && (
        <div className="stack">
          <h3>What this change does</h3>
          {!changed && <p className="muted small">Change the status or processes above to see the impact before saving.</p>}
          {changed && previewQuery.isFetching && <p className="muted small"><span className="spinner" />Checking against every rule</p>}
          {changed && previewQuery.error && <div className="notice error small">{(previewQuery.error as Error).message}</div>}
          {changed && previewQuery.data && !previewQuery.isFetching && <ImpactList preview={previewQuery.data} />}
          {changed && (
            <label className="field"><span>Reason (kept in the activity log)</span>
              <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional" />
            </label>
          )}
        </div>
      )}
      <div className="row small">
        <button className="btn link" onClick={() => go("availability")}>Test this person being unavailable</button>
      </div>
    </Sheet>
  );
}

function OptionCard({ option, best, onApply, disabled }: { option: CoverOption; best: boolean; onApply: () => void; disabled: boolean }) {
  return (
    <div className={cx("option", best && "best", !option.valid && "broken")}>
      <div className="spread">
        <div><b>{option.name}</b> <span className="faint">{option.title}</span></div>
        {option.valid ? <span className="tag good">Passes every rule</span> : <span className="tag blocker">Breaks a rule</span>}
      </div>
      <p className="small muted">
        {STATUS_LABEL[option.status]} that day. Load {option.current_load}% to {option.load_after}%. {option.cover_days_this_month} cover day(s) this month.
      </p>
      {option.notes.map((n) => <p key={n} className="small">{n}</p>)}
      {option.new_blockers.map((n) => <p key={n} className="small" style={{ color: "var(--gap)" }}>{n}</p>)}
      {option.new_warnings.slice(0, 2).map((n) => <p key={n} className="small" style={{ color: "var(--warn)" }}>{n}</p>)}
      <div>
        <button className="btn tiny" disabled={disabled} onClick={onApply}>{option.valid ? `Assign ${option.name.split(" ")[0]}` : "Assign anyway"}</button>
      </div>
    </div>
  );
}

export function ProcessDaySheet({ detail, brandProcessId, date, onClose, setSheet }: { detail: RosterDetail; brandProcessId: string; date: string; onClose: () => void; setSheet: (s: SheetState) => void }) {
  const { names, setup, canManage } = useApp();
  const bp = setup!.brand_processes.find((b) => b.id === brandProcessId);
  const cell = detail.coverage.find((c) => c.brand_process_id === brandProcessId && c.date === date);
  const required = cell?.required ?? 0;
  const staffed = cell?.staffed ?? 0;
  const short = staffed < required;
  const shift = setup!.shifts.find((s) => s.id === bp?.shift_id);
  const allocations = setup!.allocations.filter((a) => a.brand_process_id === brandProcessId);
  const statusOf = (id: string) => detail.days.find((d) => d.employee_id === id && d.date === date)?.status ?? "idle";
  const isAssigned = (id: string) => (cell?.employees ?? []).includes(id);
  const rules = setup!.coverage_rules.filter((r) => r.brand_process_id === brandProcessId);
  const [wantAdvice, setWantAdvice] = useState(short);
  const advice = useQuery({
    queryKey: ["recommend", detail.roster.id, brandProcessId, date],
    queryFn: () => api.get<Recommendation>(`/rosters/${detail.roster.id}/recommend?brand_process_id=${brandProcessId}&date=${date}`),
    enabled: wantAdvice,
  });
  const save = useSaveEdits(detail, onClose);
  const gapIssue = detail.issues.find((i) => i.brand_process_id === brandProcessId && i.date?.slice(0, 10) === date && i.category === "coverage");

  return (
    <Sheet title={names!.process(brandProcessId)} subtitle={formatLongDay(date)} onClose={onClose}>
      <div className={cx("notice", short ? "error" : required === 0 ? "" : "good")}>
        {required === 0 && staffed === 0 && <b>Closed on this day.</b>}
        {required > 0 && <b>{staffed} of {required} required staffed.</b>}
        {gapIssue?.override_reason && <p className="small">Overridden: {gapIssue.override_reason}</p>}
      </div>
      <div className="stack small">
        <p><b>Operating calendar:</b> {CALENDAR_LABEL[bp?.calendar_type ?? ""] ?? bp?.calendar_type}</p>
        <p><b>Shift:</b> {shift ? `${shift.name}, ${shiftHours(shift.start_time, shift.end_time)}` : "Not set"}</p>
        {rules.map((r) => (
          <p key={r.id}><b>Staffing rule:</b> {r.min_staff} on {r.rule_type === "date" ? formatDay(r.date!) : r.rule_type === "weekday" ? `every ${["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][r.weekday!]}` : "all open days"}{r.note ? `. ${r.note}` : ""}</p>
        ))}
      </div>
      <div className="stack">
        <h3>Allocated people</h3>
        {allocations.length === 0 && <p className="muted small">Nobody is allocated. Add someone in Setup.</p>}
        {allocations.map((a) => (
          <div className="personrow" key={a.id}>
            <button className="btn link" onClick={() => setSheet({ kind: "employee", employeeId: a.employee_id, date })}>{names!.employee(a.employee_id)}</button>
            <span className="small">
              <span className={cx("tag", a.role === "backup" && "cover")}>{a.role}</span>
              {isAssigned(a.employee_id) ? <span className="tag good">Assigned</span> : <span className="muted">{STATUS_LABEL[statusOf(a.employee_id)]}</span>}
            </span>
          </div>
        ))}
      </div>
      {required > 0 && canManage && (
        <div className="stack">
          <div className="spread">
            <h3>Who can cover this</h3>
            {!wantAdvice && <button className="btn tiny" onClick={() => setWantAdvice(true)}>Show backup options</button>}
          </div>
          {advice.isFetching && <p className="muted small"><span className="spinner" />Testing each person against every rule</p>}
          {advice.error && <div className="notice error small">{(advice.error as Error).message}</div>}
          {advice.data && !advice.isFetching && (
            <>
              <p className="small"><b>{advice.data.summary}</b></p>
              {advice.data.swaps.map((s) => (
                <div className="option" key={`${s.employee_id}${s.to_date}`}>
                  <b>{s.description}</b>
                  {s.new_warnings.slice(0, 2).map((n) => <p key={n} className="small" style={{ color: "var(--warn)" }}>{n}</p>)}
                  <div><button className="btn tiny" disabled={save.isPending} onClick={() => save.mutate({ edits: s.edits, reason: `Weekly off moved to cover ${names!.process(brandProcessId)}` })}>Move the weekly off</button></div>
                </div>
              ))}
              {advice.data.options.map((o, i) => (
                <OptionCard key={o.employee_id} option={o} best={i === 0 && o.valid} disabled={save.isPending}
                  onApply={() => save.mutate({ edits: [o.edit], reason: `Cover for ${names!.process(brandProcessId)} on ${formatDay(date)}` })} />
              ))}
            </>
          )}
        </div>
      )}
    </Sheet>
  );
}

export function DaySheet({ detail, date, onClose, setSheet }: { detail: RosterDetail; date: string; onClose: () => void; setSheet: (s: SheetState) => void }) {
  const { names, setup } = useApp();
  const holiday = detail.holidays.find((h) => h.date === date);
  const cells = detail.coverage.filter((c) => c.date === date && c.required > 0);
  const short = cells.filter((c) => c.staffed < c.required);
  const days = detail.days.filter((d) => d.date === date);
  const byStatus = (s: string) => days.filter((d) => d.status === s).map((d) => d.employee_id);
  const groups = [["weekly_off", "On weekly off"], ["leave", "On leave"], ["comp_off", "On comp-off"], ["unavailable", "Unavailable"], ["holiday", "On holiday"], ["idle", "Spare"]] as const;
  const brands = setup!.brands.filter((b) => cells.some((c) => setup!.brand_processes.find((x) => x.id === c.brand_process_id)?.brand_id === b.id));
  return (
    <Sheet title={formatLongDay(date)} subtitle={holiday ? holiday.name : `${byStatus("work").length} people working`} onClose={onClose}>
      {short.length > 0 ? (
        <div className="notice error"><b>{short.length} process(es) short today</b>
          {short.map((c) => (
            <p key={c.brand_process_id}><button className="btn link" onClick={() => setSheet({ kind: "process", brandProcessId: c.brand_process_id, date })}>{names!.process(c.brand_process_id)}</button>: {c.staffed} of {c.required}</p>
          ))}
        </div>
      ) : <div className="notice good"><b>All {cells.length} open processes meet their minimum.</b></div>}
      <div className="stack">
        <h3>Who is working, by brand</h3>
        {brands.map((b) => (
          <div key={b.id} className="small">
            <b>{b.name}</b>
            {cells.filter((c) => setup!.brand_processes.find((x) => x.id === c.brand_process_id)?.brand_id === b.id).map((c) => (
              <div className="personrow" key={c.brand_process_id}>
                <button className="btn link" onClick={() => setSheet({ kind: "process", brandProcessId: c.brand_process_id, date })}>{names!.processCode(c.brand_process_id)}</button>
                <span style={c.staffed < c.required ? { color: "var(--gap)", fontWeight: 700 } : undefined}>
                  {c.employees.map((e) => names!.employee(e)).join(", ") || "Nobody"} ({c.staffed}/{c.required})
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="stack small">
        <h3>Not working</h3>
        {groups.map(([id, label]) => byStatus(id).length > 0 && (
          <p key={id}><b>{label}:</b> {byStatus(id).map((e) => names!.employee(e)).join(", ")}</p>
        ))}
      </div>
    </Sheet>
  );
}
