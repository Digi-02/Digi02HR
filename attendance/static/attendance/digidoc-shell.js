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
  const downloads=document.getElementById('dd-download');
  const downloadToggle=document.getElementById('dd-download-toggle');
  const downloadMenu=document.getElementById('dd-download-menu');
  function positionDownloadMenu(){
    if(!downloads||!downloads.open||!downloadMenu)return;
    const anchor=downloadToggle.getBoundingClientRect();
    const maxWidth=Math.max(1,window.innerWidth-16);
    downloadMenu.style.maxWidth=`${maxWidth}px`;
    downloadMenu.style.maxHeight=`${Math.max(1,window.innerHeight-16)}px`;
    const menu=downloadMenu.getBoundingClientRect();
    const left=Math.max(8,Math.min(anchor.right-menu.width,window.innerWidth-menu.width-8));
    const below=window.innerHeight-anchor.bottom-8;
    const above=anchor.top-8;
    let top;
    if(menu.height<=below)top=anchor.bottom+6;
    else if(menu.height<=above)top=anchor.top-menu.height-6;
    else top=Math.max(8,Math.min(anchor.bottom+6,window.innerHeight-menu.height-8));
    downloadMenu.style.left=`${left}px`;
    downloadMenu.style.top=`${top}px`;
    downloadMenu.style.right='auto';
  }
  if(downloads&&downloadToggle&&downloadMenu){
    const items=()=>Array.from(downloadMenu.querySelectorAll('[role="menuitem"]'));
    downloads.addEventListener('toggle',()=>{
      downloadToggle.setAttribute('aria-expanded',String(downloads.open));
      if(downloads.open){downloadMenu.style.left='';downloadMenu.style.top='';downloadMenu.style.right='8px';requestAnimationFrame(positionDownloadMenu);}
    });
    downloadToggle.addEventListener('keydown',event=>{
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){
        event.preventDefault();
        if(!downloads.open)downloads.open=true;
        requestAnimationFrame(()=>items()[event.key==='ArrowDown'?0:items().length-1]?.focus());
      }
    });
    downloadMenu.addEventListener('keydown',event=>{
      const choices=items();const index=choices.indexOf(document.activeElement);
      let target=null;
      if(event.key==='ArrowDown')target=choices[(index+1)%choices.length];
      else if(event.key==='ArrowUp')target=choices[(index-1+choices.length)%choices.length];
      else if(event.key==='Home')target=choices[0];
      else if(event.key==='End')target=choices[choices.length-1];
      if(target){event.preventDefault();target.focus();}
    });
    document.addEventListener('click',event=>{
      if(downloads.open&&!downloads.contains(event.target))downloads.open=false;
    });
    document.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&downloads.open){downloads.open=false;downloadToggle.focus();}
    });
    window.addEventListener('resize',positionDownloadMenu);
    window.addEventListener('scroll',positionDownloadMenu,true);
  }
  document.addEventListener('keydown',e=>{if(e.key==='Escape')set(false);});
})();
