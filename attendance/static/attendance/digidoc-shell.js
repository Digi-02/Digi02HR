(() => {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('dd-backdrop');
  const toggle = document.getElementById('dd-nav-toggle');
  const close = document.getElementById('sidebarClose');
  const collapse = document.getElementById('dd-collapse-toggle');
  const desktop = window.matchMedia('(min-width: 1001px)');
  const RAIL_KEY = 'digi02hr.nav.rail.v2';

  function set(open) {
    document.body.classList.toggle('dd-nav-open', open);
    if (toggle) toggle.setAttribute('aria-expanded', String(open));
  }

  function syncCollapse() {
    const collapsed = document.body.classList.contains('dd-collapsed');
    if (collapse) {
      const label = collapsed ? 'Expand navigation' : 'Collapse navigation';
      collapse.setAttribute('aria-label', label);
      collapse.title = label;
    }
    document.querySelectorAll('.app-nav__link[data-label]').forEach(a => {
      if (collapsed) a.title = a.dataset.label;
      else a.removeAttribute('title');
    });
  }

  // Follow the rail preference saved by the main app so opening a document
  // never swaps in a different navigation style.
  function applyStoredRail() {
    if (!desktop.matches) {
      document.body.classList.remove('dd-collapsed');
      syncCollapse();
      return;
    }
    let expanded = false;
    try { expanded = window.localStorage.getItem(RAIL_KEY) === '0'; } catch (error) {}
    document.body.classList.toggle('dd-collapsed', !expanded);
    syncCollapse();
  }

  if (toggle) toggle.addEventListener('click', () => set(!document.body.classList.contains('dd-nav-open')));
  if (close) close.addEventListener('click', () => set(false));
  if (backdrop) backdrop.addEventListener('click', () => set(false));
  if (sidebar) sidebar.addEventListener('click', e => { if (e.target.closest('a')) set(false); });
  if (collapse) {
    collapse.addEventListener('click', () => {
      const collapsed = document.body.classList.toggle('dd-collapsed');
      try { window.localStorage.setItem(RAIL_KEY, collapsed ? '1' : '0'); } catch (error) {}
      syncCollapse();
    });
  }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
  if (desktop.addEventListener) desktop.addEventListener('change', applyStoredRail);
  applyStoredRail();
})();
