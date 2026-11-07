import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Assignment, type Change, type CoverageCell, type Issue, type RosterDetail, type RosterDay } from "../api";
import { useAction, useApp, useRoster } from "../state";
import { STATUS_LABEL, STATUS_SHORT, ROSTER_STATUS, PLAN_LABEL, PLAN_DESCRIPTION, WEEKDAYS, cx, dayNumber, formatDay, monthLabel, monthOptions, readPref, weekdayIndex, writePref } from "../lib";
import { DaySheet, EmployeeDaySheet, ProcessDaySheet, type SheetState } from "../components/Sheets";
import { IssuesPanel, type Severity } from "../components/Issues";
import { Menu, PageHeader } from "../components/Layout";
import { NextStep } from "../components/NextStep";

type View = "company" | "pod" | "brand" | "process" | "employee";
const VIEWS: { id: View; label: string }[] = [
  { id: "company", label: "Company" },
  { id: "pod", label: "Pod" },
  { id: "brand", label: "Brand" },
  { id: "process", label: "Process" },
  { id: "employee", label: "Employee" },
];
function Legend() {
  return (
    <div className="legend">
      <span><i style={{ background: "var(--duty-tint)" }} />Working</span>
      <span><i style={{ background: "var(--cover-tint)" }} />Covering as backup</span>
      <span><i style={{ background: "repeating-linear-gradient(135deg, var(--off), var(--off) 3px, #f2f5f8 3px, #f2f5f8 6px)" }} />Weekly off</span>
      <span><i style={{ background: "var(--holiday-tint)" }} />Holiday</span>
      <span><i style={{ background: "var(--leave-tint)" }} />Leave or comp-off</span>
      <span><i style={{ background: "var(--gap-tint)" }} />Unavailable</span>
      <span><i style={{ background: "#fff" }} />Spare</span>
      <span><i style={{ background: "var(--gap)" }} />Coverage gap</span>
      <span><i style={{ background: "repeating-linear-gradient(90deg, #f4f7f9, #f4f7f9 2px, #fff 2px, #fff 5px)" }} />Process closed</span>
      <span><i style={{ background: "#fff", boxShadow: "inset 0 0 0 2px #f08c00" }} />Changed from last version</span>
    </div>
  );
}

interface Index {
  day: Map<string, RosterDay>;
  items: Map<string, Assignment[]>;
  coverage: Map<string, CoverageCell>;
  shortByDay: Map<string, number>;
  issuesByCell: Map<string, Issue[]>;
  changed: Set<string>;
}

function buildIndex(detail: RosterDetail, changes: Change[]): Index {
  const day = new Map(detail.days.map((d) => [`${d.employee_id}|${d.date}`, d]));
  const items = new Map<string, Assignment[]>();
  for (const a of detail.assignments) {
    const key = `${a.employee_id}|${a.date}`;
    items.set(key, [...(items.get(key) ?? []), a]);
  }
  const coverage = new Map(detail.coverage.map((c) => [`${c.brand_process_id}|${c.date}`, c]));
  const shortByDay = new Map<string, number>();
  for (const c of detail.coverage) {
    if (c.staffed < c.required) shortByDay.set(c.date, (shortByDay.get(c.date) ?? 0) + (c.required - c.staffed));
  }
  const issuesByCell = new Map<string, Issue[]>();
  for (const i of detail.issues) {
    if (i.severity === "info" || !i.date || !i.employee_id) continue;
    const key = `${i.employee_id}|${i.date.slice(0, 10)}`;
    issuesByCell.set(key, [...(issuesByCell.get(key) ?? []), i]);
  }
  return { day, items, coverage, shortByDay, issuesByCell, changed: new Set(changes.map((c) => `${c.employee_id}|${c.date}`)) };
}

function DayHeader({ iso, short, holiday, onOpen }: { iso: string; short: number; holiday?: string; onOpen: () => void }) {
  const wd = weekdayIndex(iso);
  return (
    <th scope="col">
      <button className={cx("dayhead", wd >= 5 && "weekend", holiday && "holiday")} title={`${formatDay(iso)}${holiday ? `: ${holiday}` : ""}. Show who is working.`} onClick={onOpen}>
        <small>{WEEKDAYS[wd].slice(0, 2)}</small>
        {dayNumber(iso)}
        <span className={cx("ribbon", short > 0 && "short")} aria-label={short > 0 ? `${short} short` : "covered"}>{short > 0 ? `-${short}` : ""}</span>
      </button>
    </th>
  );
}

function PeopleGrid({ detail, index, employeeIds, groups, setSheet }: {
  detail: RosterDetail; index: Index; employeeIds: string[]; groups?: { title: string; subtitle?: string; ids: string[] }[]; setSheet: (s: SheetState) => void;
}) {
  const { names, setup } = useApp();
  const holidays = new Map(detail.holidays.map((h) => [h.date, h.name]));
  const titleOf = new Map(setup!.employees.map((e) => [e.id, e.title]));
  const rows = groups ?? [{ title: "", ids: employeeIds }];
  return (
    <div className="gridwrap" tabIndex={0} aria-label="Employee roster grid">
      <table className="duty">
        <thead>
          <tr>
            <th className="who" scope="col">Employee</th>
            {detail.days_in_month.map((iso) => (
              <DayHeader key={iso} iso={iso} short={index.shortByDay.get(iso) ?? 0} holiday={holidays.get(iso)} onOpen={() => setSheet({ kind: "day", date: iso })} />
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((group) => (
            <GroupRows key={group.title || "all"} group={group} detail={detail} index={index} setSheet={setSheet} names={names!} titleOf={titleOf} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ group, detail, index, setSheet, names, titleOf }: {
  group: { title: string; subtitle?: string; ids: string[] }; detail: RosterDetail; index: Index; setSheet: (s: SheetState) => void;
  names: NonNullable<ReturnType<typeof useApp>["names"]>; titleOf: Map<string, string>;
}) {
  return (
    <>
      {group.title && (
        <tr className="grouprow"><th colSpan={detail.days_in_month.length + 1}>{group.title}{group.subtitle && <span>{group.subtitle}</span>}</th></tr>
      )}
      {group.ids.map((id) => (
        <tr key={id}>
          <th className="who" scope="row">{names.employee(id)}<small>{titleOf.get(id)}</small></th>
          {detail.days_in_month.map((iso) => {
            const key = `${id}|${iso}`;
            const rec = index.day.get(key);
            const items = index.items.get(key) ?? [];
            const covers = items.filter((a) => a.is_cover).length;
            const status = rec?.status ?? "idle";
            const kind = status === "work" ? (covers === items.length ? "cover" : covers > 0 ? "mixed" : "work") : status;
            const codes = items.map((a) => names.processCode(a.brand_process_id));
            const label = status === "work" ? (codes.length > 2 ? `${codes[0]}+${codes.length - 1}` : codes.join(" ")) : STATUS_SHORT[status] ?? "";
            const hasIssue = (index.issuesByCell.get(key) ?? []).some((i) => i.severity === "blocker");
            const detailText = status === "work" ? items.map((a) => `${names.process(a.brand_process_id)}${a.is_cover ? " (cover)" : ""}`).join(", ") : STATUS_LABEL[status];
            return (
              <td key={iso}>
                <button className={cx("cell", kind, index.changed.has(key) && "changed")} title={`${names.employee(id)}, ${formatDay(iso)}: ${detailText}${rec?.locked ? " (locked by a manual edit)" : ""}`}
                  aria-label={`${names.employee(id)}, ${formatDay(iso)}: ${detailText}`}
                  onClick={() => setSheet({ kind: "employee", employeeId: id, date: iso })}>
                  {label}
                  {(hasIssue || rec?.locked) && <span className="mark" style={hasIssue ? { background: "var(--gap)" } : undefined} />}
                </button>
              </td>
            );
          })}
        </tr>
      ))}
    </>
  );
}

function ProcessGrid({ detail, index, groups, setSheet }: {
  detail: RosterDetail; index: Index; groups: { title: string; subtitle?: string; bpIds: string[] }[]; setSheet: (s: SheetState) => void;
}) {
  const { names, setup } = useApp();
  const holidays = new Map(detail.holidays.map((h) => [h.date, h.name]));
  const staff = useMemo(() => {
    const out = new Map<string, string[]>();
    for (const a of setup!.allocations) {
      if (a.role === "backup") continue;
      out.set(a.brand_process_id, [...(out.get(a.brand_process_id) ?? []), a.employee_id]);
    }
    return out;
  }, [setup]);
  return (
    <div className="gridwrap" tabIndex={0} aria-label="Coverage grid by process">
      <table className="duty">
        <thead>
          <tr>
            <th className="who" scope="col">Process</th>
            {detail.days_in_month.map((iso) => (
              <DayHeader key={iso} iso={iso} short={index.shortByDay.get(iso) ?? 0} holiday={holidays.get(iso)} onOpen={() => setSheet({ kind: "day", date: iso })} />
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <GroupedProcessRows key={group.title} group={group} detail={detail} index={index} setSheet={setSheet} staff={staff} names={names!} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupedProcessRows({ group, detail, index, setSheet, staff, names }: {
  group: { title: string; subtitle?: string; bpIds: string[] }; detail: RosterDetail; index: Index; setSheet: (s: SheetState) => void;
  staff: Map<string, string[]>; names: NonNullable<ReturnType<typeof useApp>["names"]>;
}) {
  return (
    <>
      <tr className="grouprow"><th colSpan={detail.days_in_month.length + 1}>{group.title}{group.subtitle && <span>{group.subtitle}</span>}</th></tr>
      {group.bpIds.map((bp) => (
        <tr key={bp}>
          <th className="who" scope="row">
            {names.process(bp)}
            <small>{(staff.get(bp) ?? []).map((e) => names.employee(e).split(" ")[0]).join(", ") || "Nobody allocated"}</small>
          </th>
          {detail.days_in_month.map((iso) => {
            const c = index.coverage.get(`${bp}|${iso}`);
            const required = c?.required ?? 0;
            const staffed = c?.staffed ?? 0;
            const peopleText = (c?.employees ?? []).map((e) => names.employee(e)).join(", ");
            const closed = required === 0 && staffed === 0;
            const short = staffed < required;
            const coverOnly = !closed && !short && (c?.employees ?? []).every((e) => (index.items.get(`${e}|${iso}`) ?? []).some((a) => a.brand_process_id === bp && a.is_cover));
            const text = closed ? "Closed" : `${staffed} of ${required} staffed${peopleText ? `: ${peopleText}` : ""}`;
            return (
              <td key={iso}>
                <button className={cx("cell", closed && "closed", short && "gapcell", !closed && !short && (coverOnly ? "cover" : "covered"))} title={`${names.process(bp)}, ${formatDay(iso)}: ${text}`}
                  aria-label={`${names.process(bp)}, ${formatDay(iso)}: ${text}`} onClick={() => setSheet({ kind: "process", brandProcessId: bp, date: iso })}>
                  {closed ? "" : `${staffed}/${required}`}
                </button>
              </td>
            );
          })}
        </tr>
      ))}
    </>
  );
}

function EmployeeCalendar({ detail, index, employeeId, setSheet }: { detail: RosterDetail; index: Index; employeeId: string; setSheet: (s: SheetState) => void }) {
  const { names, setup } = useApp();
  const person = setup!.employees.find((e) => e.id === employeeId);
  const holidays = new Map(detail.holidays.map((h) => [h.date, h.name]));
  const first = weekdayIndex(detail.days_in_month[0]);
  const counts: Record<string, number> = {};
  let coverDays = 0;
  for (const iso of detail.days_in_month) {
    const rec = index.day.get(`${employeeId}|${iso}`);
    if (rec) counts[rec.status] = (counts[rec.status] ?? 0) + 1;
    if ((index.items.get(`${employeeId}|${iso}`) ?? []).some((a) => a.is_cover)) coverDays += 1;
  }
  const allocations = setup!.allocations.filter((a) => a.employee_id === employeeId);
  const issues = detail.issues.filter((i) => i.employee_id === employeeId && i.severity !== "info");
  const policy = person?.weekly_off_policy === "fixed"
    ? `Fixed: ${person.fixed_off_weekdays.map((d) => WEEKDAYS[d]).join(", ")}`
    : person?.weekly_off_policy === "rotating" ? `Rotating: ${person.rotation_weekdays.map((d) => WEEKDAYS[d].slice(0, 3)).join(", ")}` : "Chosen by the solver";
  return (
    <div className="panel stack">
      <div className="spread">
        <div>
          <h2>{names!.employee(employeeId)}</h2>
          <p className="muted small">{person?.title}, {names!.pod(person?.pod_id)} pod. Weekly off: {policy}.</p>
        </div>
        <div className="summary small">
          <span className="figure"><b>{counts.work ?? 0}</b><span>working</span></span>
          <span className="figure"><b>{counts.weekly_off ?? 0}</b><span>weekly offs</span></span>
          <span className="figure"><b>{counts.holiday ?? 0}</b><span>holidays</span></span>
          <span className="figure"><b>{(counts.leave ?? 0) + (counts.comp_off ?? 0) + (counts.unavailable ?? 0)}</b><span>away</span></span>
          <span className="figure"><b>{coverDays}</b><span>cover days</span></span>
          <span className="figure"><b>{setup!.comp_off_balances[employeeId] ?? 0}</b><span>comp-offs banked</span></span>
        </div>
      </div>
      <div className="calendar" style={{ overflow: "hidden" }}>
        {WEEKDAYS.map((w) => <div key={w} className="calhead">{w.slice(0, 3)}</div>)}
        {Array.from({ length: first }).map((_, i) => <div key={`blank-${i}`} />)}
        {detail.days_in_month.map((iso) => {
          const key = `${employeeId}|${iso}`;
          const rec = index.day.get(key);
          const items = index.items.get(key) ?? [];
          const status = rec?.status ?? "idle";
          const allCover = items.length > 0 && items.every((a) => a.is_cover);
          return (
            <button key={iso} className={cx("calday", status === "work" && allCover ? "cover" : status)} onClick={() => setSheet({ kind: "employee", employeeId, date: iso })}
              aria-label={`${formatDay(iso)}: ${STATUS_LABEL[status]}`}>
              <b>{dayNumber(iso)}{holidays.get(iso) ? ` ${holidays.get(iso)}` : ""}</b>
              {status === "work"
                ? items.map((a) => <span key={a.brand_process_id}>{names!.process(a.brand_process_id)}{a.is_cover ? " (cover)" : ""}</span>)
                : <span>{STATUS_LABEL[status]}</span>}
            </button>
          );
        })}
      </div>
      <div className="row small muted">
        <b>Allocated to:</b>
        {allocations.map((a) => <span key={a.id} className={cx("tag", a.role === "backup" && "cover")}>{names!.process(a.brand_process_id)}{a.role === "backup" ? " (backup)" : ""}</span>)}
        {allocations.length === 0 && <span>nothing yet</span>}
      </div>
      {issues.length > 0 && <p className="small"><b>{issues.length} item(s) to review</b> for this person are in the list beside this calendar.</p>}
    </div>
  );
}

function StartHere({ onDismiss }: { onDismiss: () => void }) {
  return (
    <section className="starthere" aria-label="How to use this roster">
      <div className="spread">
        <h2>How to read this roster</h2>
        <button className="btn tiny" onClick={onDismiss}>Got it</button>
      </div>
      <ul>
        <li><i className="sw gap" aria-hidden="true" /><span><b>Red numbers under a date</b> are staffing gaps. Click the date to see who is working that day.</span></li>
        <li><i className="sw work" aria-hidden="true" /><span><b>Click anyone's day</b> to change it. The impact shows before you save.</span></li>
        <li><i className="sw cover" aria-hidden="true" /><span><b>Blue days</b> are backups covering for someone. Brand and Process views show coverage per process.</span></li>
        <li><i className="sw off" aria-hidden="true" /><span><b>Testing an absence</b> is on the Availability page. Nothing changes until you confirm.</span></li>
      </ul>
    </section>
  );
}

function NewVersionMenu({ month, detail, onCreated }: { month: string; detail?: RosterDetail; onCreated: (id: string) => void }) {
  const [plan, setPlan] = useState("coverage_first");
  const [from, setFrom] = useState("");
  const generate = useAction((input: { month: string; plan: string }) => api.post<{ roster_id: string; summary: string }>("/rosters/generate", input), {
    success: (r) => `New version generated. ${r.summary}`,
    onDone: (r) => onCreated(r.roster_id),
  });
  const repair = useAction((input: { id: string; change_from: string | null }) => api.post<{ roster_id: string; summary: string }>(`/rosters/${input.id}/repair`, { change_from: input.change_from }), {
    success: (r) => r.summary,
    onDone: (r) => onCreated(r.roster_id),
  });
  const busy = generate.isPending || repair.isPending;
  return (
    <Menu label={busy ? <><span className="spinner" />Solving, up to 20 seconds</> : "New version"}>
      {(close) => (
        <div className="stack" style={{ width: "min(360px, 86vw)" }}>
          <div className="stack" style={{ gap: 6 }}>
            <h3>Generate the month from scratch</h3>
            {Object.entries(PLAN_LABEL).map(([id, label]) => (
              <label key={id} className={cx("planpick", plan === id && "on")}>
                <input type="radio" name="plan" checked={plan === id} onChange={() => setPlan(id)} />
                <span><b>{label}</b><br /><span className="faint">{PLAN_DESCRIPTION[id]}</span></span>
              </label>
            ))}
            <button className="btn primary" disabled={busy} onClick={() => { close(); generate.mutate({ month, plan }); }}>Generate {monthLabel(month)}</button>
          </div>
          {detail && (
            <div className="stack" style={{ gap: 6, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
              <h3>Regenerate from a date</h3>
              <p className="faint">Keeps earlier days and manual edits, and changes as little as possible. Saved as a new draft.</p>
              <div className="row">
                <input type="date" aria-label="Regenerate from this date" value={from} min={detail.days_in_month[0]} max={detail.days_in_month[detail.days_in_month.length - 1]} onChange={(e) => setFrom(e.target.value)} />
                <button className="btn" disabled={busy} onClick={() => { close(); repair.mutate({ id: detail.roster.id, change_from: from || null }); }}>Regenerate</button>
              </div>
            </div>
          )}
        </div>
      )}
    </Menu>
  );
}

function EmptyMonth({ month, onCreated }: { month: string; onCreated: (id: string) => void }) {
  const { isOps, changeActor } = useApp();
  const [plan, setPlan] = useState("coverage_first");
  const generate = useAction((input: { month: string; plan: string }) => api.post<{ roster_id: string; summary: string }>("/rosters/generate", input), {
    success: (r) => `Roster generated. ${r.summary}`,
    onDone: (r) => onCreated(r.roster_id),
  });
  if (generate.isPending) {
    return (
      <section className="panel empty">
        <h2><span className="spinner" />Building the {monthLabel(month)} roster</h2>
        <p className="muted" style={{ maxWidth: "56ch" }}>
          First the solver finds the fewest gaps any roster can have without breaking a rule. Then it balances preferences, fairness and backup use. This takes up to 20 seconds.
        </p>
      </section>
    );
  }
  return (
    <section className="panel empty">
      <h2>No roster for {monthLabel(month)} yet</h2>
      <p className="muted" style={{ maxWidth: "60ch" }}>
        The solver decides everyone's weekly offs and duties for the month, then lists anything it cannot cover. Nothing goes live until a person approves it.
      </p>
      {isOps ? (
        <>
          <div className="planrow" role="radiogroup" aria-label="Plan">
            {Object.entries(PLAN_LABEL).map(([id, label]) => (
              <label key={id} className={cx("planpick", plan === id && "on")}>
                <input type="radio" name="emptyplan" checked={plan === id} onChange={() => setPlan(id)} />
                <span><b>{label}</b><br /><span className="faint">{PLAN_DESCRIPTION[id]}</span></span>
              </label>
            ))}
          </div>
          <button className="btn primary big" onClick={() => generate.mutate({ month, plan })}>Generate {monthLabel(month)}</button>
        </>
      ) : (
        <button className="btn primary" onClick={() => changeActor({ role: "ops_manager", name: "Operations manager" })}>Switch to operations manager to generate</button>
      )}
    </section>
  );
}

export function BoardPage() {
  const app = useApp();
  const { month, setMonth, rosterId, openRoster, rosters, isOps, setup, names, actor } = app;
  const roster = useRoster(rosterId);
  const [view, setView] = useState<View>("company");
  const [pod, setPod] = useState(setup!.pods[0]?.id ?? "");
  const [brand, setBrand] = useState("all");
  const [processId, setProcessId] = useState("all");
  const [employee, setEmployee] = useState(setup!.employees[0]?.id ?? "");
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const [filter, setFilter] = useState<Severity>("blocker");
  const [issuesOpen, setIssuesOpen] = useState(() => readPref("roster.issues", "open") === "open");
  const [keyOpen, setKeyOpen] = useState(false);
  const [guide, setGuide] = useState(() => readPref("roster.guide", "show") === "show");

  useEffect(() => {
    if (actor.role === "employee" && actor.employeeId) { setView("employee"); setEmployee(actor.employeeId); }
    if (actor.role === "pod_lead" && actor.podId) { setView("pod"); setPod(actor.podId); }
  }, [actor]);

  const detail = roster.data;
  const parent = detail?.roster.parent_id;
  const diff = useQuery({
    queryKey: ["diff", rosterId, parent],
    queryFn: () => api.get<Change[]>(`/rosters/${rosterId}/diff/${parent}`),
    enabled: !!rosterId && !!parent,
  });
  const index = useMemo(() => (detail ? buildIndex(detail, diff.data ?? []) : null), [detail, diff.data]);

  const pods = setup!.pods;
  const activeEmployees = setup!.employees.filter((e) => e.active);
  const podGroups = (only?: string) => pods.filter((p) => !only || p.id === only).map((p) => {
    const lead = p.lead_employee_id;
    const others = activeEmployees.filter((e) => e.pod_id === p.id && e.id !== lead).map((e) => e.id);
    return { title: p.name, subtitle: lead ? `Pod lead: ${names!.employee(lead)}` : "No pod lead set", ids: lead && activeEmployees.some((e) => e.id === lead) ? [lead, ...others] : others };
  });
  const unpodded = activeEmployees.filter((e) => !e.pod_id).map((e) => e.id);

  const activeBps = setup!.brand_processes.filter((b) => b.active);
  const brandGroups = setup!.brands.filter((b) => b.active && (brand === "all" || b.id === brand)).map((b) => ({
    title: b.name,
    subtitle: `${names!.pod(b.pod_id)} pod`,
    bpIds: activeBps.filter((x) => x.brand_id === b.id).map((x) => x.id),
  })).filter((g) => g.bpIds.length > 0);
  const processGroups = setup!.processes.filter((p) => processId === "all" || p.id === processId).map((p) => ({
    title: `${p.code}: ${p.name}`,
    bpIds: activeBps.filter((x) => x.process_id === p.id).map((x) => x.id),
  })).filter((g) => g.bpIds.length > 0);

  const blockers = detail ? detail.issues.filter((i) => i.severity === "blocker" && !i.override_reason) : [];
  const showIssues = (severity: Severity) => { setFilter(severity); setIssuesOpen(true); writePref("roster.issues", "open"); };
  const hideIssues = () => { setIssuesOpen(false); writePref("roster.issues", "closed"); };
  const firstBlocker = () => {
    const b = blockers[0];
    if (!b) return;
    const date = b.date?.slice(0, 10);
    if (b.brand_process_id && date) setSheet({ kind: "process", brandProcessId: b.brand_process_id, date });
    else if (b.employee_id && date) setSheet({ kind: "employee", employeeId: b.employee_id, date });
    else showIssues("blocker");
  };
  const versionLabel = (r: { version: number; plan_label: string; status: string }) => `Version ${r.version}, ${PLAN_LABEL[r.plan_label] ?? r.plan_label}, ${ROSTER_STATUS[r.status]?.toLowerCase()}`;

  return (
    <>
      <PageHeader
        title={
          <label className="titlepick">
            <span className="sr-only">Month</span>
            <select value={month} onChange={(e) => setMonth(e.target.value)}>
              {monthOptions().map((x) => <option key={x} value={x}>{monthLabel(x)}</option>)}
            </select>
          </label>
        }
        actions={
          <>
            {isOps && <NewVersionMenu month={month} detail={detail} onCreated={openRoster} />}
            {detail && (
              <Menu label="Export">
                {(close) => (
                  <div className="menu-list">
                    <a href={`/api/rosters/${detail.roster.id}/export.xlsx`} onClick={close}>Excel, formatted with three sheets</a>
                    <a href={`/api/rosters/${detail.roster.id}/export.csv`} onClick={close}>CSV, one row per person per day</a>
                  </div>
                )}
              </Menu>
            )}
          </>
        }
      >
        {rosters.length > 0 && (
          <div className="row small versionline">
            <label className="row" style={{ gap: 6 }}>
              <span className="muted">Showing</span>
              <select value={rosterId ?? ""} onChange={(e) => openRoster(e.target.value)} aria-label="Version">
                {rosters.map((r) => <option key={r.id} value={r.id}>{versionLabel(r)}</option>)}
              </select>
            </label>
            {diff.data && parent && diff.data.length > 0 && (
              <span className="muted"><i className="sw changed" aria-hidden="true" />{diff.data.length} day(s) changed from the version before, outlined in orange</span>
            )}
          </div>
        )}
      </PageHeader>

      {!rosterId && <EmptyMonth month={month} onCreated={openRoster} />}
      {roster.error && <div className="notice error">{(roster.error as Error).message}</div>}
      {rosterId && !detail && !roster.error && <div className="loading"><span className="spinner" />Loading the roster</div>}

      {detail && index && (
        <>
          <NextStep detail={detail} unresolved={blockers.length} onFirstBlocker={firstBlocker} onShowIssues={showIssues} />
          {guide && <StartHere onDismiss={() => { setGuide(false); writePref("roster.guide", "hide"); }} />}

          <div className={cx("board", !issuesOpen && "wide")}>
            <div className="stack" style={{ minWidth: 0, gap: 8 }}>
              <div className="toolbar">
                <div className="seg" role="tablist" aria-label="Roster view">
                  {VIEWS.map((v) => <button key={v.id} role="tab" aria-selected={view === v.id} onClick={() => setView(v.id)}>{v.label}</button>)}
                </div>
                {view === "pod" && <select aria-label="Pod" value={pod} onChange={(e) => setPod(e.target.value)}>{pods.map((p) => <option key={p.id} value={p.id}>{p.name} pod</option>)}</select>}
                {view === "brand" && <select aria-label="Brand" value={brand} onChange={(e) => setBrand(e.target.value)}><option value="all">All brands</option>{setup!.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}
                {view === "process" && <select aria-label="Process" value={processId} onChange={(e) => setProcessId(e.target.value)}><option value="all">All processes</option>{setup!.processes.map((p) => <option key={p.id} value={p.id}>{p.code}: {p.name}</option>)}</select>}
                {view === "employee" && <select aria-label="Employee" value={employee} onChange={(e) => setEmployee(e.target.value)}>{activeEmployees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>}
                <span className="toolbar-gap" />
                {view !== "employee" && <button className="btn tiny" aria-expanded={keyOpen} onClick={() => setKeyOpen(!keyOpen)}>{keyOpen ? "Hide colour key" : "Colour key"}</button>}
                {!guide && <button className="btn tiny" onClick={() => { setGuide(true); writePref("roster.guide", "show"); }}>How to read this</button>}
                {!issuesOpen && <button className="btn tiny" onClick={() => showIssues(filter)}>Show issues ({blockers.length} blockers)</button>}
              </div>
              {keyOpen && view !== "employee" && <Legend />}
              {view === "company" && (
                <PeopleGrid detail={detail} index={index} employeeIds={[]} setSheet={setSheet}
                  groups={[...podGroups(), ...(unpodded.length ? [{ title: "No pod", ids: unpodded }] : [])]} />
              )}
              {view === "pod" && <PeopleGrid detail={detail} index={index} employeeIds={[]} setSheet={setSheet} groups={podGroups(pod)} />}
              {view === "brand" && <ProcessGrid detail={detail} index={index} setSheet={setSheet} groups={brandGroups} />}
              {view === "process" && <ProcessGrid detail={detail} index={index} setSheet={setSheet} groups={processGroups} />}
              {view === "employee" && <EmployeeCalendar detail={detail} index={index} employeeId={employee} setSheet={setSheet} />}
            </div>
            {issuesOpen && (
              <IssuesPanel detail={detail} filter={filter} setFilter={setFilter} onHide={hideIssues}
                scope={view === "employee" ? { employeeId: employee } : view === "pod" ? { podId: pod } : view === "brand" && brand !== "all" ? { brandId: brand } : {}} setSheet={setSheet} />
            )}
          </div>
        </>
      )}

      {sheet && detail && sheet.kind === "day" && <DaySheet detail={detail} date={sheet.date} onClose={() => setSheet(null)} setSheet={setSheet} />}
      {sheet && detail && sheet.kind === "employee" && <EmployeeDaySheet detail={detail} employeeId={sheet.employeeId} date={sheet.date} onClose={() => setSheet(null)} />}
      {sheet && detail && sheet.kind === "process" && <ProcessDaySheet detail={detail} brandProcessId={sheet.brandProcessId} date={sheet.date} onClose={() => setSheet(null)} setSheet={setSheet} />}
    </>
  );
}
