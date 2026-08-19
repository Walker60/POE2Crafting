import { useState, type ReactNode } from 'react';

interface Props {
  title: string;
  defaultOpen?: boolean;
  // Fired every time this section opens (not just the first time) -- the
  // caller is responsible for guarding against re-fetching already-loaded
  // data, e.g. "cost spread" lazy-loads on first expand.
  onOpen?: () => void;
  children: ReactNode;
}

export function Collapsible({ title, defaultOpen = false, onOpen, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  function toggle() {
    // Deliberately not the `setOpen(prev => ...)` functional-updater form --
    // React may invoke that updater outside a normal event-handler context
    // (e.g. StrictMode's double-invoke), and calling another component's
    // state setter (via onOpen) from inside it is exactly what produced a
    // real "Cannot update a component while rendering a different component"
    // warning. Reading `open` from the closure and calling onOpen here, as a
    // plain statement in the click handler, keeps the state update pure.
    const next = !open;
    setOpen(next);
    if (next) onOpen?.();
  }

  return (
    <div className={`collapsible ${open ? 'is-open' : ''}`}>
      <button type="button" className="collapsible-header" onClick={toggle}>
        <span className="collapsible-chevron" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        <span className="collapsible-title">{title}</span>
      </button>
      {open && <div className="collapsible-body">{children}</div>}
    </div>
  );
}
