export type Role = "ops_manager" | "pod_lead" | "employee";

export interface Actor {
  role: Role;
  name: string;
  podId?: string;
  employeeId?: string;
}

let actor: Actor = { role: "ops_manager", name: "Operations manager" };

export function setActor(next: Actor) {
  actor = next;
}

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json", "X-Role": actor.role, "X-Actor-Name": actor.name };
  if (actor.podId) h["X-Pod-Id"] = actor.podId;
  if (actor.employeeId) h["X-Employee-Id"] = actor.employeeId;
  return h;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers: headers(), body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("The server could not be reached. Check your connection and try again.", 0);
  }
  if (!res.ok) {
    let message = `The server returned an error (${res.status}). Try again.`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) message = String(data.detail[0].msg);
    } catch {
      if (res.status === 504) message = "The server took too long and stopped. Try again, or lower SOLVER_TIME_LIMIT.";
    }
    throw new ApiError(message, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  patch: <T,>(path: string, body: unknown) => request<T>("PATCH", path, body),
  put: <T,>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: <T,>(path: string) => request<T>("DELETE", path),
};

// ------------------------------------------------------------ data types
export interface Pod { id: string; name: string; lead_employee_id: string | null }
export interface Employee {
  id: string; name: string; title: string; pod_id: string | null; weekly_off_policy: "solver" | "fixed" | "rotating";
  fixed_off_weekdays: number[]; rotation_weekdays: number[]; offs_per_week: number; max_consecutive_days: number;
  stretch_limit: number; active: boolean;
}
export interface Brand { id: string; name: string; pod_id: string | null; notes: string; active: boolean }
export interface Process { id: string; code: string; name: string }
export interface Shift { id: string; name: string; start_time: string; end_time: string }
export interface Holiday { id: string; date: string; name: string; kind: string }
export interface BrandProcess {
  id: string; brand_id: string; process_id: string; calendar_type: string; weekday_mask: number[];
  holidays_closed: boolean; shift_id: string; active: boolean;
}
export interface CoverageRule { id: string; brand_process_id: string; rule_type: string; weekday: number | null; date: string | null; min_staff: number; note: string }
export interface Allocation { id: string; employee_id: string; brand_process_id: string; role: string; workload_share: number; effective_from: string | null; effective_to: string | null }
export interface Leave { id: string; employee_id: string; leave_type: string; status: string; start_date: string; end_date: string; reason: string; decided_by: string | null }
export interface Preference { id: string; employee_id: string; pref_type: string; weekday: number | null; date: string | null; shift_id: string | null; weight: number }
export interface LedgerEntry { id: number; employee_id: string; delta: number; entry_date: string; reason: string }

export interface Bootstrap {
  pods: Pod[]; employees: Employee[]; brands: Brand[]; processes: Process[]; shifts: Shift[]; public_holidays: Holiday[];
  brand_processes: BrandProcess[]; coverage_rules: CoverageRule[]; allocations: Allocation[]; preferences: Preference[];
  leaves: Leave[]; settings: Record<string, number>; comp_off_balances: Record<string, number>; comp_off_ledger: LedgerEntry[];
}

export interface Metrics {
  coverage_pct: number; required_slots: number; covered_slots: number; gap_slots: number; blockers: number; warnings: number;
  backup_days: number; peak_backup_days: number; stretch_days: number; preferences_honoured_pct: number;
  sunday_holiday_spread: number; sunday_holiday_low: number; sunday_holiday_high: number; working_days: number; weekly_offs: number; score: number;
}
export interface RosterRow {
  id: string; month: string; version: number; status: string; plan_label: string; parent_id: string | null; score: number | null;
  metrics: Metrics; solver: { status?: string; seconds?: number; fewest_gaps_proved?: boolean; uncovered_slots?: number };
  summary: string; created_by: string; created_at: string; published_at: string | null;
}
export interface RosterDay { employee_id: string; date: string; status: string; source: string; locked: boolean; note: string }
export interface Assignment { employee_id: string; brand_process_id: string; date: string; shift_id: string; is_cover: boolean; share: number }
export interface CoverageCell { brand_process_id: string; date: string; required: number; staffed: number; employees: string[] }
export interface IssueFacts { causes?: string[]; holiday?: string | null; allocated_people?: { name: string; role: string; reason: string; status: string }[]; [key: string]: unknown }
export interface Issue {
  key: string; code: string; severity: "blocker" | "warning" | "info"; category: string; date: string | null; employee_id: string | null;
  brand_process_id: string | null; brand_id?: string | null; message: string; suggestion: string; facts: IssueFacts;
  override_reason?: string | null; overridden_by?: string | null;
}
export interface Approval { id: number; stage: string; pod_id: string | null; actor: string; decision: string; note: string; created_at: string }
export interface RosterDetail {
  roster: RosterRow; days: RosterDay[]; assignments: Assignment[]; coverage: CoverageCell[]; issues: Issue[]; approvals: Approval[];
  holidays: { date: string; name: string }[]; days_in_month: string[];
}
export interface Change {
  employee_id: string; employee: string; date: string; from_status: string | null; to_status: string | null;
  from_processes: string[]; to_processes: string[]; from_labels: string[]; to_labels: string[];
}
export interface Edit { employee_id: string; date: string; status: string; bp_ids: string[]; add_backup_allocation?: string | null }
export interface Preview { resolved: Issue[]; introduced: Issue[]; blockers_before: number; blockers_after: number; earns_comp_off: string[] }
export interface CoverOption {
  employee_id: string; name: string; title: string; tier: number; status: string; current_load: number; load_after: number; spare_capacity: number;
  same_pod: boolean; cover_days_this_month: number; needs_allocation: boolean; fixes_gap: boolean; valid: boolean;
  new_blockers: string[]; new_warnings: string[]; notes: string[]; edit: Edit;
}
export interface Swap { employee_id: string; name: string; from_date: string; to_date: string; description: string; new_warnings: string[]; edits: Edit[] }
export interface Recommendation { process: string; brand_process_id: string; date: string; required: number; staffed: number; options: CoverOption[]; swaps: Swap[]; summary: string }
export interface AbsenceImpact {
  roster_id: string; version: number; status: string; employee: string; gap_count: number; brands_affected: string[]; gaps: Issue[];
  other_new_issues: Issue[]; coverage_still_met: { process: string; date: string; required: number; staffed: number }[];
}
export interface Notification { id: number; roster_id: string | null; employee_id: string | null; kind: string; title: string; body: string; read_at: string | null; created_at: string }
export interface AuditEntry { id: number; actor: string; role: string; action: string; entity: string; entity_id: string | null; details: Record<string, unknown>; created_at: string }
export interface PlanResult { roster_id: string; plan: string; label: string; description: string; metrics: Metrics; summary: string }
