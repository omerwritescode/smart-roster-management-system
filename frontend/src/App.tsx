import { useQuery } from "@tanstack/react-query";
import { api, type Notification, type Role } from "./api";
import { useAction, useApp, type Page } from "./state";
import { BoardPage } from "./pages/Board";
import { PlansPage } from "./pages/Plans";
import { AvailabilityPage } from "./pages/Availability";
import { ApprovalsPage } from "./pages/Approvals";
import { SetupPage } from "./pages/Setup";
import { ActivityPage } from "./pages/Activity";

const NAV: { id: Page; label: string }[] = [
  { id: "board", label: "Roster" },
  { id: "plans", label: "Compare plans" },
  { id: "availability", label: "Availability" },
  { id: "approvals", label: "Approvals" },
  { id: "setup", label: "Setup" },
  { id: "activity", label: "Activity" },
];

function RoleSwitcher() {
  const { actor, changeActor, setup, say, openRoster } = useApp();
  const reset = useAction(() => api.post("/demo/reset"), {
    success: "Demo data restored. Generate a roster to begin.",
    onDone: () => openRoster(null),
  });
  const pods = setup?.pods ?? [];
  const employees = setup?.employees ?? [];

  function choose(role: Role) {
    if (role === "ops_manager") changeActor({ role, name: "Operations manager" });
    if (role === "pod_lead") {
      const pod = pods[0];
      const lead = employees.find((e) => e.id === pod?.lead_employee_id);
      changeActor({ role, name: lead?.name ?? "Pod lead", podId: pod?.id });
    }
    if (role === "employee") {
      const person = employees[0];
      changeActor({ role, name: person?.name ?? "Employee", employeeId: person?.id });
    }
    say(`Now viewing as ${role === "ops_manager" ? "the operations manager" : role === "pod_lead" ? "a pod lead" : "an employee"}.`);
  }

  return (
    <div className="roleswitch">
      <label htmlFor="role">View as</label>
      <select id="role" value={actor.role} onChange={(e) => choose(e.target.value as Role)}>
        <option value="ops_manager">Operations manager</option>
        <option value="pod_lead">Pod lead</option>
        <option value="employee">Employee</option>
      </select>
      {actor.role === "pod_lead" && (
        <select aria-label="Pod" value={actor.podId} onChange={(e) => {
          const pod = pods.find((p) => p.id === e.target.value);
          changeActor({ role: "pod_lead", podId: pod?.id, name: employees.find((x) => x.id === pod?.lead_employee_id)?.name ?? "Pod lead" });
        }}>
          {pods.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      )}
      {actor.role === "employee" && (
        <select aria-label="Employee" value={actor.employeeId} onChange={(e) => {
          changeActor({ role: "employee", employeeId: e.target.value, name: employees.find((x) => x.id === e.target.value)?.name ?? "Employee" });
        }}>
          {employees.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      )}
      <button className="btn tiny" style={{ background: "transparent", color: "#fff", borderColor: "#3e556e" }} disabled={reset.isPending}
        onClick={() => { if (window.confirm("Replace all data with the original sample data? Rosters and changes will be lost.")) reset.mutate(undefined); }}>
        {reset.isPending ? "Resetting" : "Reset demo data"}
      </button>
    </div>
  );
}

export function App() {
  const { page, go, toast, setupError, setup, actor } = useApp();
  const notes = useQuery({
    queryKey: ["notifications", actor.employeeId ?? "all"],
    queryFn: () => api.get<Notification[]>(`/notifications${actor.employeeId ? `?employee_id=${actor.employeeId}` : ""}`),
  });
  const unread = (notes.data ?? []).filter((n) => !n.read_at).length;

  return (
    <>
      <div className="topbar">
        <div className="brandmark">
          <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
            <rect x="1" y="1" width="6" height="6" fill="#2fb89f" /><rect x="9" y="1" width="6" height="6" fill="#2fb89f" />
            <rect x="1" y="9" width="6" height="6" fill="#2fb89f" /><rect x="9" y="9" width="6" height="6" fill="#ff5a6e" />
          </svg>
          Roster Board
        </div>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <button key={n.id} aria-current={page === n.id ? "page" : undefined} onClick={() => go(n.id)}>
              {n.label}
              {n.id === "activity" && unread > 0 && <span className="count">{unread}</span>}
            </button>
          ))}
        </nav>
        <RoleSwitcher />
      </div>
      <main className="page">
        {setupError && (
          <div className="notice error">
            <b>The app could not load its data.</b> {setupError.message}
          </div>
        )}
        {!setup && !setupError && <div className="loading"><span className="spinner" />Loading the team and brands</div>}
        {setup && page === "board" && <BoardPage />}
        {setup && page === "plans" && <PlansPage />}
        {setup && page === "availability" && <AvailabilityPage />}
        {setup && page === "approvals" && <ApprovalsPage />}
        {setup && page === "setup" && <SetupPage />}
        {setup && page === "activity" && <ActivityPage />}
      </main>
      {toast && <div className={`toast ${toast.kind === "error" ? "error" : ""}`} role="status">{toast.text}</div>}
    </>
  );
}
