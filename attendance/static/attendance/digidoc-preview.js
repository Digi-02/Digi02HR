(() => {
  'use strict';
  const stage=document.getElementById('preview-stage');
  if(!stage)return;
  const pages=Array.from(document.querySelectorAll('.preview-page'));
  const zoomLevels=[50,75,100,125,150];
  const zoomOutput=document.getElementById('preview-zoom-value');
  const pageOutput=document.getElementById('preview-current-page');
  const previous=document.getElementById('preview-previous');
  const next=document.getElementById('preview-next');
  const guides=document.getElementById('preview-guides');
  let zoom=100,current=0;

  function updatePage(index){
    current=Math.max(0,Math.min(pages.length-1,index));
    pageOutput.textContent=String(current+1);
    previous.disabled=current===0;
    next.disabled=current>=pages.length-1;
  }
  function setZoom(value,fit=false){
    zoom=value;stage.dataset.zoom=String(value);stage.dataset.fit=fit?'true':'false';
    zoomOutput.textContent=`${value}%`;
    document.getElementById('preview-zoom-out').disabled=value===zoomLevels[0];
    document.getElementById('preview-zoom-in').disabled=value===zoomLevels[zoomLevels.length-1];
  }
  previous.addEventListener('click',()=>{updatePage(current-1);pages[current]?.scrollIntoView({behavior:'smooth',block:'start'});});
  next.addEventListener('click',()=>{updatePage(current+1);pages[current]?.scrollIntoView({behavior:'smooth',block:'start'});});
  document.getElementById('preview-zoom-out').addEventListener('click',()=>{const index=zoomLevels.indexOf(zoom);setZoom(zoomLevels[Math.max(0,index-1)]);});
  document.getElementById('preview-zoom-in').addEventListener('click',()=>{const index=zoomLevels.indexOf(zoom);setZoom(zoomLevels[Math.min(zoomLevels.length-1,index+1)]);});
  document.getElementById('preview-fit').addEventListener('click',()=>setZoom(100,true));
  guides.addEventListener('click',()=>{
    const hidden=stage.classList.toggle('preview-guides-hidden');
    guides.setAttribute('aria-pressed',String(!hidden));
    guides.textContent=hidden?'Show guides':'Hide guides';
  });
  document.getElementById('preview-print').addEventListener('click',()=>window.print());
  if('IntersectionObserver' in window){
    const observer=new IntersectionObserver(entries=>{
      const visible=entries.filter(entry=>entry.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];
      if(visible)updatePage(pages.indexOf(visible.target));
    },{root:stage,threshold:[0.25,0.5,0.75]});
    pages.forEach(page=>observer.observe(page));
  }
  setZoom(100,true);updatePage(0);
})();
