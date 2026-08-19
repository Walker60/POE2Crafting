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
    setOpen((wasOpen) => {
      const next = !wasOpen;
      if (next) onOpen?.();
      return next;
    });
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
