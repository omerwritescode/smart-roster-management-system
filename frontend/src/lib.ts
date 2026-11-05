import type { Bootstrap } from "./api";

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export const STATUS_LABEL: Record<string, string> = {
  work: "Working", weekly_off: "Weekly off", holiday: "Holiday", leave: "Leave", comp_off: "Comp-off",
  unavailable: "Unavailable", idle: "Spare",
};
export const STATUS_SHORT: Record<string, string> = {
  weekly_off: "Off", holiday: "Hol", leave: "Lv", comp_off: "CO", unavailable: "NA", idle: "",
};
export const CALENDAR_LABEL: Record<string, string> = {
  all_days: "365 days, including Sundays and holidays",
  daily_except_holidays: "Daily, public holidays off",
  sundays_holidays_off: "Sundays and public holidays off",
  custom: "Custom weekdays",
};
export const LEAVE_LABEL: Record<string, string> = { planned: "Planned leave", sick: "Sick leave", comp_off: "Comp-off", unavailable: "Unavailable" };
export const PLAN_LABEL: Record<string, string> = { coverage_first: "Coverage first", fairness_first: "Fairness first", preference_first: "Preference first" };
export const ROSTER_STATUS: Record<string, string> = {
  draft: "Draft", pod_review: "Pod lead review", ops_review: "Operations approval", published: "Published", superseded: "Replaced", rejected: "Rejected",
};

/** ISO dates are parsed by hand so a browser's time zone can never shift a roster day. */
export function parseDay(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}
export function weekdayIndex(iso: string) {
  return (parseDay(iso).getDay() + 6) % 7;
}
export function dayNumber(iso: string) {
  return Number(iso.slice(8, 10));
}
export function formatDay(iso: string) {
  return parseDay(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}
export function formatLongDay(iso: string) {
  return parseDay(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}
export function monthLabel(month: string) {
  return parseDay(`${month.slice(0, 7)}-01`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}
export function formatTime(iso: string) {
  return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
export function shiftHours(start: string, end: string) {
  return `${start.slice(0, 5)} to ${end.slice(0, 5)}`;
}

export function monthOptions() {
  const out: string[] = [];
  for (let i = 0; i < 6; i++) {
    const d = new Date(2026, 10 + i, 1);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

export interface Names {
  employee: (id: string | null | undefined) => string;
  brand: (id: string | null | undefined) => string;
  pod: (id: string | null | undefined) => string;
  process: (bpId: string) => string;
  processCode: (bpId: string) => string;
  shift: (id: string | null | undefined) => string;
}

export function makeNames(b: Bootstrap): Names {
  const emp = new Map(b.employees.map((x) => [x.id, x.name]));
  const brand = new Map(b.brands.map((x) => [x.id, x.name]));
  const pod = new Map(b.pods.map((x) => [x.id, x.name]));
  const proc = new Map(b.processes.map((x) => [x.id, x.code]));
  const bp = new Map(b.brand_processes.map((x) => [x.id, x]));
  const shift = new Map(b.shifts.map((x) => [x.id, x.name]));
  return {
    employee: (id) => (id ? (emp.get(id) ?? "Removed employee") : ""),
    brand: (id) => (id ? (brand.get(id) ?? "Removed brand") : ""),
    pod: (id) => (id ? (pod.get(id) ?? "Removed pod") : "No pod"),
    process: (id) => {
      const x = bp.get(id);
      return x ? `${brand.get(x.brand_id) ?? "Removed brand"} ${proc.get(x.process_id) ?? ""}` : "Removed process";
    },
    processCode: (id) => {
      const x = bp.get(id);
      return x ? (proc.get(x.process_id) ?? "?") : "?";
    },
    shift: (id) => (id ? (shift.get(id) ?? "") : ""),
  };
}

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}
