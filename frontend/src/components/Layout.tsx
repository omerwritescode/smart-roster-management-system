import { useEffect, useRef, type ReactNode } from "react";

/** The same heading block on every page: what this page is for, and its main actions. */
export function PageHeader({ title, intro, actions, children }: { title: ReactNode; intro?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <header className="pagehead">
      <div className="pagehead-text">
        <h1>{title}</h1>
        {intro && <p className="muted">{intro}</p>}
        {children}
      </div>
      {actions && <div className="pagehead-actions">{actions}</div>}
    </header>
  );
}

/** A button that opens a small panel. Closes on outside click, Escape, or when an item calls close(). */
export function Menu({ label, align = "right", primary, children }: { label: ReactNode; align?: "left" | "right"; primary?: boolean; children: (close: () => void) => ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const close = () => ref.current?.removeAttribute("open");
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (ref.current?.open && !ref.current.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && ref.current?.open) { close(); ref.current.querySelector("summary")?.focus(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, []);
  return (
    <details className={`menu ${align}`} ref={ref}>
      <summary className={`btn${primary ? " primary" : ""}`}>{label}<span className="caret" aria-hidden="true" /></summary>
      <div className="menu-panel">{children(close)}</div>
    </details>
  );
}
