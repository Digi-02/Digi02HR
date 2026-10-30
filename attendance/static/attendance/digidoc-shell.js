(() => {
  const sidebar=document.getElementById('sidebar');
  const backdrop=document.getElementById('dd-backdrop');
  const toggle=document.getElementById('dd-nav-toggle');
  const close=document.getElementById('sidebarClose');
  const collapse=document.getElementById('dd-collapse-toggle');
  function set(open){document.body.classList.toggle('dd-nav-open',open);if(toggle)toggle.setAttribute('aria-expanded',String(open));}
  if(toggle)toggle.addEventListener('click',()=>set(!document.body.classList.contains('dd-nav-open')));
  if(close)close.addEventListener('click',()=>set(false));
  if(backdrop)backdrop.addEventListener('click',()=>set(false));
  if(sidebar){sidebar.addEventListener('click',e=>{if(e.target.closest('a'))set(false);});}
  if(collapse){collapse.addEventListener('click',()=>{const on=document.body.classList.toggle('dd-collapsed');collapse.setAttribute('aria-label',on?'Expand navigation':'Collapse navigation');collapse.title=on?'Expand navigation':'Collapse navigation';document.querySelectorAll('.app-nav__link[data-label]').forEach(a=>a.title=on?a.dataset.label:'');});}
  document.addEventListener('keydown',e=>{if(e.key==='Escape')set(false);});
})();
