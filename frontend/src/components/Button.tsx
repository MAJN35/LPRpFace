// Shared button: icon + label, press/ripple feedback, busy spinner, and a success/error mark that appears only after
// the operation it belongs to has finished (useActions). Icon-only buttons get an accessible name and a tooltip.
// All motion is CSS (tokens.css: --dur*, --ease) and is switched off under prefers-reduced-motion.
import { AlertCircle, Check, Loader2, LucideIcon } from "lucide-react";
import { ButtonHTMLAttributes, PointerEvent, ReactNode, forwardRef, useCallback, useRef, useState } from "react";

export type ActionState = "idle" | "busy" | "done" | "error";
export type Variant = "default" | "primary" | "danger" | "ghost";

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  icon?: LucideIcon; children?: ReactNode; variant?: Variant; state?: ActionState;
  iconOnly?: boolean; label?: string;            // label: accessible name + tooltip (required for iconOnly)
  spin?: boolean;                                // rotate the icon (refresh in progress)
  flipRtl?: boolean;                             // directional icon (chevrons/arrows): mirrored in RTL
  tip?: string;                                  // tooltip for a button with a visible label
};

export const ICON = 18;

export const Btn = forwardRef<HTMLButtonElement, Props>(function Btn(
  { icon: Icon, children, variant = "default", state = "idle", iconOnly, label, spin, flipRtl, tip, className = "",
    disabled, onPointerDown, type = "button", ...rest }, ref) {
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number }[]>([]);
  const next = useRef(0);
  const busy = state === "busy";
  function down(e: PointerEvent<HTMLButtonElement>) {
    // ripple from the pointer position (physical coordinates, so it is direction-independent)
    const r = e.currentTarget.getBoundingClientRect();
    const id = ++next.current;
    setRipples((rs) => [...rs.slice(-2), { id, x: e.clientX - r.left, y: e.clientY - r.top }]);
    window.setTimeout(() => setRipples((rs) => rs.filter((p) => p.id !== id)), 600);
    onPointerDown?.(e);
  }
  const Shown = busy ? Loader2 : state === "done" ? Check : state === "error" ? AlertCircle : Icon;
  const tooltip = iconOnly ? label : tip;
  return (
    <button ref={ref} type={type} {...rest} disabled={disabled || busy} aria-busy={busy || undefined}
      aria-label={iconOnly ? label : rest["aria-label"]} data-tip={tooltip} data-state={state}
      className={`btn-x v-${variant}${iconOnly ? " icon-only" : ""}${tooltip ? " has-tip" : ""} ${className}`.trim()}
      onPointerDown={down}>
      {Shown && (
        <span className={`btn-icon${busy || spin ? " spinning" : ""}${state === "done" || state === "error" ? " pop" : ""}${flipRtl ? " flip-rtl" : ""}`}
          aria-hidden="true" key={busy ? "busy" : state}>
          <Shown size={ICON} strokeWidth={2} />
        </span>
      )}
      {!iconOnly && children != null && <span className="btn-label">{children}</span>}
      <span className="ripple-box" aria-hidden="true">
        {ripples.map((p) => <span key={p.id} className="ripple" style={{ left: p.x, top: p.y }} />)}
      </span>
    </button>
  );
});

// Per-key action state for async operations: one run at a time per key (no duplicate submissions), "done" only after
// the promise resolves (the backend confirmed), "error" if it rejects; both fade back to idle.
export function useActions() {
  const [states, setStates] = useState<Record<string, ActionState>>({});
  const running = useRef(new Set<string>());
  const set = (k: string, s: ActionState) => setStates((m) => ({ ...m, [k]: s }));
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>): Promise<T | undefined> => {
    if (running.current.has(key)) return undefined;
    running.current.add(key);
    set(key, "busy");
    try {
      const r = await fn();
      set(key, "done");
      window.setTimeout(() => set(key, "idle"), 1400);
      return r;
    } catch (e) {
      set(key, "error");
      window.setTimeout(() => set(key, "idle"), 2400);
      throw e;
    } finally {
      running.current.delete(key);
    }
  }, []);
  const state = (key: string): ActionState => states[key] ?? "idle";
  return { run, state };
}
