import { useState } from "react";
import { api, type Bootstrap } from "../api";
import { useAction, useApp } from "../state";
import { CALENDAR_LABEL, WEEKDAYS, cx, formatDay, type Names } from "../lib";
import { PageHeader } from "../components/Layout";

type Row = Record<string, unknown> & { id: string };
type Field =
  | { name: string; label: string; type: "text" | "date" | "time" | "number"; min?: number; max?: number; required?: boolean; showIf?: (v: Row) => boolean }
  | { name: string; label: string; type: "select"; options: (b: Bootstrap, n: Names) => [string, string][]; empty?: string; required?: boolean; showIf?: (v: Row) => boolean; number?: boolean }
  | { name: string; label: string; type: "days"; showIf?: (v: Row) => boolean; ordered?: boolean }
  | { name: string; label: string; type: "bool"; showIf?: (v: Row) => boolean };

interface Entity {
  id: keyof Bootstrap;
  api: string;
  label: string;
  singular: string;
  help: string;
  fields: Field[];
  columns: { label: string; value: (r: Row, b: Bootstrap, n: Names) => string }[];
  defaults: Record<string, unknown>;
}

const weekdayOptions = (): [string, string][] => WEEKDAYS.map((w, i) => [String(i), w]);
const pods = (b: Bootstrap): [string, string][] => b.pods.map((p) => [p.id, p.name]);
const employees = (b: Bootstrap): [string, string][] => b.employees.map((e) => [e.id, e.name]);
const brands = (b: Bootstrap): [string, string][] => b.brands.map((e) => [e.id, e.name]);
const processes = (b: Bootstrap): [string, string][] => b.processes.map((e) => [e.id, `${e.code}: ${e.name}`]);
const shifts = (b: Bootstrap): [string, string][] => b.shifts.map((e) => [e.id, e.name]);
const brandProcesses = (b: Bootstrap, n: Names): [string, string][] =>
  b.brand_processes.map((x): [string, string] => [x.id, n.process(x.id)]).sort((p, q) => p[1].localeCompare(q[1]));
const days = (value: unknown) => ((value as number[]) ?? []).map((d) => WEEKDAYS[d].slice(0, 3)).join(", ");

const ENTITIES: Entity[] = [
  {
    id: "employees", api: "employees", label: "Employees", singular: "employee",
    help: "Each person's weekly off pattern and limits. Different people on one brand can follow different patterns.",
    defaults: { name: "", title: "Associate", weekly_off_policy: "solver", fixed_off_weekdays: [], rotation_weekdays: [], offs_per_week: 1, max_consecutive_days: 6, stretch_limit: 125, active: true },
    fields: [
      { name: "name", label: "Name", type: "text", required: true },
      { name: "title", label: "Title", type: "text" },
      { name: "pod_id", label: "Pod", type: "select", options: pods, empty: "No pod" },
      { name: "weekly_off_policy", label: "Weekly off", type: "select", options: () => [["solver", "Chosen by the solver"], ["fixed", "Fixed weekdays"], ["rotating", "Rotating weekdays"]] },
      { name: "fixed_off_weekdays", label: "Fixed off days", type: "days", showIf: (v) => v.weekly_off_policy === "fixed" },
      { name: "rotation_weekdays", label: "Rotation, one per week in order", type: "days", ordered: true, showIf: (v) => v.weekly_off_policy === "rotating" },
      { name: "offs_per_week", label: "Offs per week", type: "number", min: 0, max: 3 },
      { name: "max_consecutive_days", label: "Most consecutive days", type: "number", min: 1, max: 14 },
      { name: "stretch_limit", label: "Workload limit on cover days, %", type: "number", min: 100, max: 200 },
      { name: "active", label: "Active", type: "bool" },
    ],
    columns: [
      { label: "Name", value: (r) => String(r.name) },
      { label: "Title", value: (r) => String(r.title) },
      { label: "Pod", value: (r, _, n) => n.pod(r.pod_id as string) },
      { label: "Weekly off", value: (r) => (r.weekly_off_policy === "fixed" ? `Fixed: ${days(r.fixed_off_weekdays)}` : r.weekly_off_policy === "rotating" ? `Rotating: ${days(r.rotation_weekdays)}` : "Solver") },
      { label: "Limits", value: (r) => `${r.offs_per_week} off/week, ${r.max_consecutive_days} days in a row, ${r.stretch_limit}%` },
      { label: "Active", value: (r) => (r.active ? "Yes" : "No") },
    ],
  },
  {
    id: "pods", api: "pods", label: "Pods", singular: "pod", help: "Operational groups, each overseen by a pod lead.", defaults: { name: "" },
    fields: [
      { name: "name", label: "Name", type: "text", required: true },
      { name: "lead_employee_id", label: "Pod lead", type: "select", options: employees, empty: "None" },
    ],
    columns: [
      { label: "Name", value: (r) => String(r.name) },
      { label: "Pod lead", value: (r, _, n) => n.employee(r.lead_employee_id as string) || "None" },
      { label: "People", value: (r, b) => String(b.employees.filter((e) => e.pod_id === r.id).length) },
      { label: "Brands", value: (r, b) => String(b.brands.filter((e) => e.pod_id === r.id).length) },
    ],
  },
  {
    id: "brands", api: "brands", label: "Brands", singular: "brand", help: "Client brands. Add their processes under Brand processes.", defaults: { name: "", notes: "", active: true },
    fields: [
      { name: "name", label: "Name", type: "text", required: true },
      { name: "pod_id", label: "Pod", type: "select", options: pods, empty: "No pod" },
      { name: "notes", label: "Notes", type: "text" },
      { name: "active", label: "Active", type: "bool" },
    ],
    columns: [
      { label: "Name", value: (r) => String(r.name) },
      { label: "Pod", value: (r, _, n) => n.pod(r.pod_id as string) },
      { label: "Processes", value: (r, b, n) => b.brand_processes.filter((x) => x.brand_id === r.id).map((x) => n.processCode(x.id)).join(", ") },
      { label: "People", value: (r, b) => {
        const ids = new Set(b.brand_processes.filter((x) => x.brand_id === r.id).map((x) => x.id));
        const people = new Set(b.allocations.filter((a) => a.role !== "backup" && ids.has(a.brand_process_id)).map((a) => a.employee_id));
        return String(people.size);
      } },
      { label: "Active", value: (r) => (r.active ? "Yes" : "No") },
    ],
  },
  {
    id: "brand_processes", api: "brand_processes", label: "Brand processes", singular: "brand process",
    help: "A process at a brand, with its own operating calendar and shift. This is the brand's calendar, separate from any employee's schedule.",
    defaults: { calendar_type: "daily_except_holidays", weekday_mask: [0, 1, 2, 3, 4, 5, 6], holidays_closed: true, active: true },
    fields: [
      { name: "brand_id", label: "Brand", type: "select", options: brands, required: true },
      { name: "process_id", label: "Process", type: "select", options: processes, required: true },
      { name: "calendar_type", label: "Operating calendar", type: "select", options: () => Object.entries(CALENDAR_LABEL) as [string, string][] },
      { name: "weekday_mask", label: "Open on", type: "days", showIf: (v) => v.calendar_type === "custom" },
      { name: "holidays_closed", label: "Closed on public holidays", type: "bool", showIf: (v) => v.calendar_type === "custom" },
      { name: "shift_id", label: "Shift", type: "select", options: shifts, required: true },
      { name: "active", label: "Active", type: "bool" },
    ],
    columns: [
      { label: "Brand process", value: (r, _, n) => n.process(r.id) },
      { label: "Operating calendar", value: (r) => (r.calendar_type === "custom" ? `Custom: ${days(r.weekday_mask)}` : CALENDAR_LABEL[r.calendar_type as string]) },
      { label: "Shift", value: (r, _, n) => n.shift(r.shift_id as string) },
      { label: "Minimum staff", value: (r, b) => {
        const rules = b.coverage_rules.filter((c) => c.brand_process_id === r.id);
        const base = rules.find((c) => c.rule_type === "default")?.min_staff ?? 1;
        return rules.some((c) => c.rule_type !== "default") ? `${base}, with exceptions` : String(base);
      } },
    ],
  },
  {
    id: "coverage_rules", api: "coverage_rules", label: "Staffing rules", singular: "staffing rule",
    help: "Minimum staff for a process. A date rule beats a weekday rule, which beats the default. Without a rule, the minimum is 1. A date rule can open a process on a closed day, and minimum 0 closes it.",
    defaults: { rule_type: "date", min_staff: 1, note: "" },
    fields: [
      { name: "brand_process_id", label: "Brand process", type: "select", options: brandProcesses, required: true },
      { name: "rule_type", label: "Applies to", type: "select", options: () => [["default", "All open days"], ["weekday", "A weekday"], ["date", "A specific date"]] },
      { name: "weekday", label: "Weekday", type: "select", number: true, options: weekdayOptions, showIf: (v) => v.rule_type === "weekday", required: true },
      { name: "date", label: "Date", type: "date", showIf: (v) => v.rule_type === "date", required: true },
      { name: "min_staff", label: "Minimum staff", type: "number", min: 0, max: 50 },
      { name: "note", label: "Why", type: "text" },
    ],
    columns: [
      { label: "Brand process", value: (r, _, n) => n.process(r.brand_process_id as string) },
      { label: "Applies to", value: (r) => (r.rule_type === "date" ? formatDay(r.date as string) : r.rule_type === "weekday" ? `Every ${WEEKDAYS[r.weekday as number]}` : "All open days") },
      { label: "Minimum staff", value: (r) => String(r.min_staff) },
      { label: "Why", value: (r) => String(r.note ?? "") },
    ],
  },
  {
    id: "allocations", api: "allocations", label: "Allocations", singular: "allocation",
    help: "Who can work what. Primary and secondary people work it as regular duty. Backups are used only to fill a gap. Workload is the share of a person's day.",
    defaults: { role: "primary", workload_share: 100 },
    fields: [
      { name: "employee_id", label: "Employee", type: "select", options: employees, required: true },
      { name: "brand_process_id", label: "Brand process", type: "select", options: brandProcesses, required: true },
      { name: "role", label: "Role", type: "select", options: () => [["primary", "Primary"], ["secondary", "Secondary"], ["backup", "Backup"]] },
      { name: "workload_share", label: "Workload, % of a day", type: "number", min: 1, max: 200 },
      { name: "effective_from", label: "From, optional", type: "date" },
      { name: "effective_to", label: "To, optional", type: "date" },
    ],
    columns: [
      { label: "Employee", value: (r, _, n) => n.employee(r.employee_id as string) },
      { label: "Brand process", value: (r, _, n) => n.process(r.brand_process_id as string) },
      { label: "Role", value: (r) => String(r.role) },
      { label: "Workload", value: (r) => `${r.workload_share}%` },
      { label: "Dates", value: (r) => (r.effective_from || r.effective_to ? `${r.effective_from ?? "start"} to ${r.effective_to ?? "open"}` : "Always") },
    ],
  },
  {
    id: "preferences", api: "preferences", label: "Preferences", singular: "preference",
    help: "Wishes the solver tries to honour. Required client coverage always comes first. Weight runs from 1 (mild) to 5 (strong).",
    defaults: { pref_type: "off_weekday", weight: 3 },
    fields: [
      { name: "employee_id", label: "Employee", type: "select", options: employees, required: true },
      { name: "pref_type", label: "Preference", type: "select", options: () => [["off_weekday", "Prefers a weekday off"], ["off_date", "Wants a date off"], ["avoid_shift", "Avoids a shift"]] },
      { name: "weekday", label: "Weekday", type: "select", number: true, options: weekdayOptions, showIf: (v) => v.pref_type === "off_weekday", required: true },
      { name: "date", label: "Date", type: "date", showIf: (v) => v.pref_type === "off_date", required: true },
      { name: "shift_id", label: "Shift", type: "select", options: shifts, showIf: (v) => v.pref_type === "avoid_shift", required: true },
      { name: "weight", label: "Weight", type: "number", min: 1, max: 5 },
    ],
    columns: [
      { label: "Employee", value: (r, _, n) => n.employee(r.employee_id as string) },
      { label: "Preference", value: (r, _, n) => (r.pref_type === "off_weekday" ? `${WEEKDAYS[r.weekday as number]}s off` : r.pref_type === "off_date" ? `${formatDay(r.date as string)} off` : `Avoid ${n.shift(r.shift_id as string)} shift`) },
      { label: "Weight", value: (r) => String(r.weight) },
    ],
  },
  {
    id: "processes", api: "processes", label: "Processes", singular: "process", help: "Types of work, such as Customer Support or Abandoned Cart Conversions.", defaults: { code: "", name: "" },
    fields: [
      { name: "code", label: "Short code", type: "text", required: true },
      { name: "name", label: "Name", type: "text", required: true },
    ],
    columns: [
      { label: "Code", value: (r) => String(r.code) },
      { label: "Name", value: (r) => String(r.name) },
      { label: "Used at", value: (r, b) => `${b.brand_processes.filter((x) => x.process_id === r.id).length} brand(s)` },
    ],
  },
  {
    id: "shifts", api: "shifts", label: "Shifts", singular: "shift", help: "Working hours. The system uses these to find overlapping shifts and too little rest between days.", defaults: { name: "", start_time: "10:00", end_time: "19:00" },
    fields: [
      { name: "name", label: "Name", type: "text", required: true },
      { name: "start_time", label: "Starts", type: "time", required: true },
      { name: "end_time", label: "Ends", type: "time", required: true },
    ],
    columns: [
      { label: "Name", value: (r) => String(r.name) },
      { label: "Hours", value: (r) => `${String(r.start_time).slice(0, 5)} to ${String(r.end_time).slice(0, 5)}` },
    ],
  },
  {
    id: "public_holidays", api: "public_holidays", label: "Holidays", singular: "holiday", help: "Applies to every brand whose calendar closes on public holidays. Processes running 365 days stay open, and anyone working earns a comp-off.", defaults: { name: "", kind: "public" },
    fields: [
      { name: "date", label: "Date", type: "date", required: true },
      { name: "name", label: "Name", type: "text", required: true },
      { name: "kind", label: "Kind", type: "select", options: () => [["public", "Public holiday"], ["company", "Company holiday"]] },
    ],
    columns: [
      { label: "Date", value: (r) => formatDay(r.date as string) },
      { label: "Name", value: (r) => String(r.name) },
      { label: "Kind", value: (r) => (r.kind === "company" ? "Company holiday" : "Public holiday") },
    ],
  },
];

function DayPicker({ value, onChange, ordered, label }: { value: number[]; onChange: (v: number[]) => void; ordered?: boolean; label: string }) {
  return (
    <div className="stack" style={{ gap: 3 }}>
      <div className="daychips" role="group" aria-label={label}>
        {WEEKDAYS.map((w, i) => (
          <button type="button" key={w} aria-pressed={value.includes(i)} onClick={() => onChange(value.includes(i) ? value.filter((x) => x !== i) : [...value, i])}>{w.slice(0, 2)}</button>
        ))}
      </div>
      {ordered && value.length > 0 && <span className="faint">Order: {value.map((d) => WEEKDAYS[d].slice(0, 3)).join(", ")}</span>}
    </div>
  );
}

function EntityForm({ entity, initial, onDone }: { entity: Entity; initial: Row | null; onDone: () => void }) {
  const { setup, names, say } = useApp();
  const [values, setValues] = useState<Row>((initial ?? { id: "", ...entity.defaults }) as Row);
  const set = (name: string, value: unknown) => setValues((v) => ({ ...v, [name]: value }));
  const save = useAction((payload: Record<string, unknown>) => (initial ? api.patch(`/setup/${entity.api}/${initial.id}`, payload) : api.post(`/setup/${entity.api}`, payload)), {
    success: `${entity.singular[0].toUpperCase()}${entity.singular.slice(1)} saved. Rosters recheck against this straight away.`,
    onDone,
  });
  const visible = entity.fields.filter((f) => !f.showIf || f.showIf(values));

  function submit() {
    const payload: Record<string, unknown> = {};
    for (const f of entity.fields) {
      const shown = visible.includes(f);
      const raw = values[f.name];
      if (!shown) continue;
      if ("required" in f && f.required && (raw === undefined || raw === null || raw === "")) {
        say(`${f.label} is required.`, "error");
        return;
      }
      if (f.type === "number") payload[f.name] = Number(raw);
      else if (f.type === "select" && f.number) payload[f.name] = raw === undefined || raw === "" ? null : Number(raw);
      else if ((f.type === "select" || f.type === "date") && raw === "") payload[f.name] = null;
      else if (raw !== undefined) payload[f.name] = raw;
    }
    save.mutate(payload);
  }

  return (
    <form className="panel stack" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <h3>{initial ? `Edit ${entity.singular}` : `Add ${entity.singular}`}</h3>
      <div className="formgrid">
        {visible.map((f) => (
          <div key={f.name} className="field">
            {f.type === "bool" ? (
              <label className="check"><input type="checkbox" checked={!!values[f.name]} onChange={(e) => set(f.name, e.target.checked)} />{f.label}</label>
            ) : f.type === "days" ? (
              <>
                <span>{f.label}</span>
                <DayPicker label={f.label} ordered={f.ordered} value={(values[f.name] as number[]) ?? []} onChange={(v) => set(f.name, v)} />
              </>
            ) : f.type === "select" ? (
              <label className="field"><span>{f.label}</span>
                <select value={values[f.name] === null || values[f.name] === undefined ? "" : String(values[f.name])} onChange={(e) => set(f.name, e.target.value)}>
                  {(f.empty !== undefined || f.required) && <option value="">{f.empty ?? "Choose"}</option>}
                  {f.options(setup!, names!).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                </select>
              </label>
            ) : (
              <label className="field"><span>{f.label}</span>
                <input type={f.type} min={f.type === "number" ? f.min : undefined} max={f.type === "number" ? f.max : undefined}
                  value={values[f.name] === null || values[f.name] === undefined ? "" : f.type === "time" ? String(values[f.name]).slice(0, 5) : String(values[f.name])}
                  onChange={(e) => set(f.name, e.target.value)} />
              </label>
            )}
          </div>
        ))}
      </div>
      <div className="row">
        <button className="btn primary" type="submit" disabled={save.isPending}>Save {entity.singular}</button>
        <button className="btn" type="button" onClick={onDone}>Cancel</button>
      </div>
    </form>
  );
}

function Settings() {
  const { setup, isOps } = useApp();
  const [rest, setRest] = useState(String((setup!.settings.min_rest_minutes ?? 660) / 60));
  const [spread, setSpread] = useState(String(setup!.settings.fairness_spread_warning ?? 3));
  const save = useAction(() => api.put("/settings", { min_rest_minutes: Math.round(Number(rest) * 60), fairness_spread_warning: Number(spread) }), { success: "Settings saved." });
  return (
    <section className="panel stack">
      <p className="muted small">Rules that apply to the whole company. Changing them rechecks every roster.</p>
      <div className="formgrid">
        <label className="field"><span>Minimum rest between shifts, hours</span><input type="number" min={0} max={24} step={0.5} value={rest} onChange={(e) => setRest(e.target.value)} /></label>
        <label className="field"><span>Warn when Sunday and holiday work differs by, days</span><input type="number" min={1} max={31} value={spread} onChange={(e) => setSpread(e.target.value)} /></label>
        {isOps && <button className="btn primary" onClick={() => save.mutate(undefined)}>Save settings</button>}
      </div>
    </section>
  );
}

export function SetupPage() {
  const { setup, names, isOps, say } = useApp();
  const [tab, setTab] = useState<string>("employees");
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const [filter, setFilter] = useState("");
  const remove = useAction((input: { api: string; id: string }) => api.del(`/setup/${input.api}/${input.id}`), { success: "Removed." });
  const entity = ENTITIES.find((e) => e.id === tab);
  const rows = entity ? ((setup![entity.id] as unknown) as Row[]) : [];
  const text = filter.trim().toLowerCase();
  const shown = entity ? rows.filter((r) => !text || entity.columns.some((c) => c.value(r, setup!, names!).toLowerCase().includes(text))) : [];

  return (
    <div className="stack">
      <PageHeader
        title="Setup"
        intro="Everything the roster is built from. Adding a brand, pod, process, person or rule takes effect on the next check, with no code change."
      />
      <div className="tabs" role="tablist" aria-label="Setup lists">
        {ENTITIES.map((e) => <button key={e.id} role="tab" aria-selected={tab === e.id} onClick={() => { setTab(e.id); setEditing(null); setFilter(""); }}>{e.label}</button>)}
        <button role="tab" aria-selected={tab === "settings"} onClick={() => { setTab("settings"); setEditing(null); }}>Company rules</button>
      </div>
      {tab === "settings" && <Settings />}
      {entity && (
        <>
          <p className="muted small" style={{ maxWidth: "80ch" }}>{entity.help}</p>
          <div className="spread">
            <input type="text" aria-label={`Search ${entity.label}`} placeholder={`Search ${entity.label.toLowerCase()}`} value={filter} onChange={(e) => setFilter(e.target.value)} />
            {isOps || entity.id === "preferences"
              ? <button className="btn primary" onClick={() => setEditing("new")}>Add {entity.singular}</button>
              : <span className="faint">Switch role to operations manager to make changes.</span>}
          </div>
          {editing && <EntityForm key={editing === "new" ? "new" : editing.id} entity={entity} initial={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
          <div className="tablewrap" style={{ maxHeight: "60vh" }}>
            <table className="data">
              <thead><tr>{entity.columns.map((c) => <th key={c.label}>{c.label}</th>)}<th /></tr></thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} className={cx(editing !== "new" && editing?.id === r.id && "best")}>
                    {entity.columns.map((c) => <td key={c.label}>{c.value(r, setup!, names!)}</td>)}
                    <td>
                      {(isOps || entity.id === "preferences") && (
                        <span className="row" style={{ flexWrap: "nowrap" }}>
                          <button className="btn tiny" onClick={() => setEditing(r)}>Edit</button>
                          <button className="btn tiny" onClick={() => {
                            if (window.confirm(`Remove this ${entity.singular}?`)) remove.mutate({ api: entity.api, id: r.id });
                            else say("Nothing was removed.");
                          }}>Remove</button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
                {shown.length === 0 && <tr><td colSpan={entity.columns.length + 1} className="muted small">Nothing matches. Clear the search or add a {entity.singular}.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
