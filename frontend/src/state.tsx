import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setActor, type Actor, type Bootstrap, type RosterDetail, type RosterRow } from "./api";
import { makeNames, type Names } from "./lib";

export type Page = "board" | "plans" | "availability" | "approvals" | "setup" | "activity";

function read(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private window: the choice simply is not remembered */
  }
}

interface AppState {
  page: Page;
  go: (page: Page) => void;
  month: string;
  setMonth: (month: string) => void;
  rosterId: string | null;
  openRoster: (id: string | null) => void;
  actor: Actor;
  changeActor: (actor: Actor) => void;
  canManage: boolean;
  isOps: boolean;
  toast: { text: string; kind: "ok" | "error" } | null;
  say: (text: string, kind?: "ok" | "error") => void;
  setup: Bootstrap | undefined;
  names: Names | null;
  setupError: Error | null;
  rosters: RosterRow[];
  refreshAll: () => void;
}

const Ctx = createContext<AppState | null>(null);

export function useApp() {
  const value = useContext(Ctx);
  if (!value) throw new Error("useApp used outside its provider");
  return value;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [page, setPage] = useState<Page>(() => (window.location.hash.slice(2) as Page) || "board");
  const [month, setMonthRaw] = useState(() => read("roster.month", "2026-12"));
  const [rosterId, setRosterId] = useState<string | null>(null);
  const [actor, setActorState] = useState<Actor>({ role: "ops_manager", name: "Operations manager" });
  const [toast, setToast] = useState<AppState["toast"]>(null);

  useEffect(() => {
    const onHash = () => setPage((window.location.hash.slice(2) as Page) || "board");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), toast.kind === "error" ? 8000 : 4500);
    return () => clearTimeout(t);
  }, [toast]);

  const setupQuery = useQuery({ queryKey: ["bootstrap"], queryFn: () => api.get<Bootstrap>("/bootstrap") });
  const rostersQuery = useQuery({ queryKey: ["rosters", month], queryFn: () => api.get<RosterRow[]>(`/rosters?month=${month}`) });
  const rosters = useMemo(() => rostersQuery.data ?? [], [rostersQuery.data]);

  // Open the newest version that is still in play whenever the month's list changes.
  useEffect(() => {
    if (!rostersQuery.data || rostersQuery.isFetching) return; // a just-created version may not be listed yet
    if (rosterId && rosters.some((r) => r.id === rosterId)) return;
    const live = rosters.find((r) => ["draft", "pod_review", "ops_review"].includes(r.status)) ?? rosters.find((r) => r.status === "published") ?? rosters[0];
    setRosterId(live?.id ?? null);
  }, [rosters, rosterId, rostersQuery.data, rostersQuery.isFetching]);

  const value = useMemo<AppState>(() => ({
    page,
    go: (p) => { window.location.hash = `#/${p}`; setPage(p); },
    month,
    setMonth: (m) => { setMonthRaw(m); write("roster.month", m); setRosterId(null); },
    rosterId,
    openRoster: setRosterId,
    actor,
    changeActor: (a) => { setActor(a); setActorState(a); },
    canManage: actor.role !== "employee",
    isOps: actor.role === "ops_manager",
    toast,
    say: (text, kind = "ok") => setToast({ text, kind }),
    setup: setupQuery.data,
    names: setupQuery.data ? makeNames(setupQuery.data) : null,
    setupError: setupQuery.error,
    rosters,
    refreshAll: () => { client.invalidateQueries(); },
  }), [page, month, rosterId, actor, toast, setupQuery.data, setupQuery.error, rosters, client]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRoster(id: string | null) {
  return useQuery({
    queryKey: ["roster", id],
    queryFn: () => api.get<RosterDetail>(`/rosters/${id}`),
    enabled: !!id,
  });
}

/** A mutation that reports failures to the toast and refreshes every screen on success. */
export function useAction<TInput, TResult>(fn: (input: TInput) => Promise<TResult>, options?: { success?: string | ((r: TResult) => string); onDone?: (r: TResult) => void }) {
  const app = useApp();
  const { say, refreshAll } = app;
  const onError = useCallback((e: Error) => say(e.message, "error"), [say]);
  return useMutation({
    mutationFn: fn,
    onError,
    onSuccess: (result) => {
      options?.onDone?.(result); // first, so a screen stops asking for a version that was just replaced
      refreshAll();
      if (options?.success) say(typeof options.success === "function" ? options.success(result) : options.success);
    },
  });
}
