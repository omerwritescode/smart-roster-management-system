import { useQuery } from "@tanstack/react-query";
import { api, type AuditEntry, type Notification } from "../api";
import { useAction, useApp } from "../state";
import { formatTime } from "../lib";

export function ActivityPage() {
  const { actor, names, isOps } = useApp();
  const person = actor.employeeId;
  const notes = useQuery({
    queryKey: ["notifications", person ?? "all"],
    queryFn: () => api.get<Notification[]>(`/notifications${person ? `?employee_id=${person}` : ""}`),
  });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<AuditEntry[]>("/audit"), enabled: isOps });
  const markRead = useAction(() => api.post(`/notifications/read${person ? `?employee_id=${person}` : ""}`), { success: "Marked as read." });

  return (
    <div className="stack">
      <div className="spread">
        <h1>{person ? `Notifications for ${names!.employee(person)}` : "Notifications"}</h1>
        <button className="btn" onClick={() => markRead.mutate(undefined)}>Mark all as read</button>
      </div>
      <p className="muted small" style={{ maxWidth: "75ch" }}>
        When a published roster changes, everyone affected sees what changed here. An optional webhook sends the same event to tools such as n8n.
      </p>
      <div className="panel" style={{ padding: 0 }}>
        {(notes.data ?? []).length === 0 && <p className="muted small" style={{ padding: 14 }}>Nothing yet. Notifications appear when a roster is sent for review or published.</p>}
        {(notes.data ?? []).map((n) => (
          <div className="issue" key={n.id} style={n.read_at ? undefined : { borderLeftColor: "var(--focus)" }}>
            <div className="spread">
              <b>{n.title}</b>
              <span className="faint">{formatTime(n.created_at)}</span>
            </div>
            {n.employee_id && !person && <p className="faint">To {names!.employee(n.employee_id)}</p>}
            {n.body && <p className="small">{n.body}</p>}
          </div>
        ))}
      </div>
      {isOps && (
        <>
          <h2>Activity log</h2>
          <div className="tablewrap" style={{ maxHeight: 460 }}>
            <table className="data">
              <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Details</th></tr></thead>
              <tbody>
                {(audit.data ?? []).map((a) => (
                  <tr key={a.id}>
                    <td className="small">{formatTime(a.created_at)}</td>
                    <td className="small">{a.actor}</td>
                    <td className="small">{a.action.replace(/_/g, " ")}</td>
                    <td className="small">{typeof a.details?.reason === "string" && a.details.reason ? `Reason: ${a.details.reason}` : Array.isArray(a.details?.changes) ? `${a.details.changes.length} day(s) changed` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
