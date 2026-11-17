import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router';
import { navigation } from './navigation';
import './navigation.css';

export function SiteHeader() {
  const [open, setOpen] = useState<string>();
  const header = useRef<HTMLElement>(null);
  const location = useLocation();
  useEffect(() => { setOpen(undefined); }, [location.key]);
  useEffect(() => {
    const outside = (event:PointerEvent) => {
      if (!header.current?.contains(event.target as Node)) setOpen(undefined);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, []);
  return <header ref={header} className="site-header atlas-header" onKeyDown={event => {
    if (event.key === 'Escape' && open) {
      header.current?.querySelector<HTMLButtonElement>(`button[data-section="${open}"]`)?.focus();
      setOpen(undefined);
    }
  }}>
    <Link className="brand" to="/" aria-label="Electoral Atlas home"><span className="brand-mark" aria-hidden="true">E/A</span><span>Electoral Atlas</span></Link>
    <nav className="atlas-navigation" aria-label="Primary navigation">
      {navigation.map(group => <div className={`nav-section${group.label === 'Search' ? ' nav-section-search' : ''}`} key={group.label}>
        <button className="nav-trigger" data-section={group.label} aria-expanded={open === group.label}
          aria-controls={`nav-${group.label}`} onClick={() => setOpen(open === group.label ? undefined : group.label)}>
          {group.label}
        </button>
        {open === group.label && <div id={`nav-${group.label}`} className="nav-dropdown" onBlur={event => {
          if (!event.currentTarget.parentElement?.contains(event.relatedTarget as Node | null)) setOpen(undefined);
        }}><p>{group.label === 'Search' ? 'Explore the atlas' : group.label}</p>
          {group.items.map(item => <Link key={item.to} to={item.to}>
            <span>{item.label}</span>{item.planned && <small>Coming soon</small>}
          </Link>)}
        </div>}
      </div>)}
    </nav>
  </header>;
}
