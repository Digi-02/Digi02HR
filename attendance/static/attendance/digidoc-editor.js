(() => {
  'use strict';
  const root = document.getElementById('digidoc');
  if (!root) return;
  const sheet = document.getElementById('dd-sheet');
  const status = document.getElementById('dd-status');
  const title = document.getElementById('dd-title');
  const letterheadFirst = document.getElementById('dd-letterhead-first');
  const letterheadOther = document.getElementById('dd-letterhead-other');
  const initial = JSON.parse(document.getElementById('dd-initial').textContent);
  const allowedTags = {P:'paragraph', H1:'heading', H2:'heading', H3:'heading', UL:'bulletList', OL:'orderedList', LI:'listItem', TABLE:'table', TBODY:'table', TR:'tableRow', TD:'tableCell', TH:'tableCell', BR:'hardBreak', HR:'horizontalRule', IMG:'image'};
  function makeImageFrame(assetId, alt, src, attrs={}) {
    const width=Math.min(100,Math.max(10,Number(attrs.width_percent)||100));
    const alignment=['left','center','right'].includes(attrs.align)?attrs.align:'center';
    const crop=['none','square','landscape','portrait'].includes(attrs.crop)?attrs.crop:'none';
    const frame=document.createElement('div');frame.className='dd-image-frame';frame.contentEditable='false';frame.dataset.widthPercent=String(width);frame.dataset.imageAlign=alignment;frame.dataset.crop=crop;frame.style.width=`${width}%`;frame.style.setProperty('--dd-image-ratio',({square:'1 / 1',landscape:'16 / 9',portrait:'3 / 4'})[crop]||'auto');frame.style.marginLeft=alignment==='right'?'auto':alignment==='center'?'auto':'0';frame.style.marginRight=alignment==='left'?'auto':alignment==='center'?'auto':'0';
    const img=document.createElement('img');img.dataset.assetId=assetId;img.alt=alt||'';img.src=src;img.className='dd-inline-image';img.draggable=false;img.style.objectFit=crop==='none'?'contain':'cover';frame.append(img);return frame;
  }
  function renderNode(node, parent) {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'image') {
      const frame=makeImageFrame(node.attrs.asset_id,node.attrs.alt,'/digidoc/images/'+encodeURIComponent(node.attrs.asset_id)+'/',node.attrs);parent.append(frame);return;
    }
    if (node.type === 'text') {
      const text = document.createTextNode(node.text || '');
      let current = text;
      (node.marks || []).forEach(mark => {
        const tag = {bold:'strong', italic:'em', underline:'u', strike:'s', link:'a'}[mark.type];
        if (['fontFamily','fontSize','textColor','highlight'].includes(mark.type)) {
          const wrapper = document.createElement(mark.type === 'highlight' ? 'mark' : 'span');
          const key = {fontFamily:'ddFontFamily',fontSize:'ddFontSize',textColor:'ddTextColor',highlight:'ddHighlight'}[mark.type];
          const value = mark.attrs.value || mark.attrs.color;
          wrapper.dataset[key] = String(value);
          if (mark.type === 'fontFamily') wrapper.style.fontFamily = ({'Helvetica':'Arial,sans-serif','Times-Roman':'"Times New Roman",serif','Courier':'"Courier New",monospace'})[value] || '"'+value+'"';
          if (mark.type === 'fontSize') wrapper.style.fontSize = `${value}pt`;
          if (mark.type === 'textColor') wrapper.style.color = value;
          if (mark.type === 'highlight') wrapper.style.backgroundColor = value;
          wrapper.append(current); current = wrapper; return;
        }
        if (!tag) return;
        const el = document.createElement(tag);
        if (tag === 'a') { try { const u = new URL(mark.attrs.href); if (!['http:','https:','mailto:'].includes(u.protocol)) return; el.href = u.href; el.rel = 'noopener noreferrer'; } catch (_) { return; } }
        el.append(current); current = el;
      });
      parent.append(current); return;
    }
    const tag = {doc:'div', paragraph:'p', heading:`h${node.level || 1}`, bulletList:'ul', orderedList:'ol', listItem:'li', table:'table', tableRow:'tr', tableCell:'td', hardBreak:'p', horizontalRule:'hr'}[node.type];
    if (!tag) return;
    const el = document.createElement(tag);
    if (node.type === 'hardBreak') { el.dataset.pageBreak='true';el.className='dd-page-break-marker';el.contentEditable='false';el.textContent='Page break';parent.append(el);return; }
    if (node.type === 'horizontalRule') { parent.append(el); return; }
    if (node.attrs && node.attrs.align) el.dataset.align = node.attrs.align;
    if (node.attrs && node.attrs.indent) el.dataset.indent = node.attrs.indent;
    if (node.attrs && node.attrs.line_spacing) el.dataset.lineSpacing = node.attrs.line_spacing;
    if (node.type === 'bulletList' && node.attrs && node.attrs.list_style === 'checklist') el.dataset.checklist = 'true';
    (node.content || []).forEach(child => renderNode(child, el));
    if (node.type === 'paragraph' && !el.childNodes.length) el.append(document.createElement('br'));
    parent.append(el);
  }
  function createPage(after) {
    const page = document.createElement('div');
    page.className = 'dd-page';
    page.dataset.pageNumber = String(sheet.querySelectorAll('.dd-page').length + 1);
    const zones=document.createElement('div');zones.className='dd-page-zones';zones.contentEditable='false';zones.setAttribute('aria-hidden','true');page.append(zones);
    if (after && after.nextSibling) sheet.insertBefore(page, after.nextSibling);
    else sheet.append(page);
    return page;
  }
  function syncLetterheadPages() {
    const enabled = document.getElementById('dd-letterhead').checked;
    sheet.classList.toggle('dd-letterhead', enabled);
    sheet.dataset.letterheadFirst = letterheadFirst.value;
    sheet.dataset.letterheadOther = letterheadOther.value;
    sheet.querySelectorAll(':scope > .dd-page').forEach((page, index) => {
      const slot = index === 0 ? letterheadFirst.value : letterheadOther.value;
      if (enabled && slot !== 'none') page.dataset.letterheadSlot = slot;
      else delete page.dataset.letterheadSlot;
    });
  }
  const letterheadGuides = document.getElementById('dd-letterhead-guides');
  letterheadGuides.addEventListener('click', () => {
    const hidden = sheet.classList.toggle('dd-guides-hidden');
    letterheadGuides.setAttribute('aria-pressed', String(!hidden));
    letterheadGuides.textContent = hidden ? 'Show guides' : 'Hide guides';
  });
  function activePage() {
    const selection = window.getSelection();
    const anchor = selection && selection.anchorNode;
    const anchorElement = anchor && (anchor.nodeType === Node.ELEMENT_NODE ? anchor : anchor.parentElement);
    return (anchorElement && anchorElement.closest('.dd-page')) || sheet.querySelector(':scope > .dd-page:last-child') || createPage();
  }
  function moveBefore(nodes, targetPage) {
    const reference = targetPage.firstChild;
    nodes.forEach(node => targetPage.insertBefore(node, reference));
  }
  let firstPage = createPage();
  (initial.content || []).forEach(node => renderNode(node, firstPage));
  if (!firstPage.childNodes.length) firstPage.append(document.createElement('p'));

  function rangePoint(points, index) {
    for (const point of points) {
      if (index <= point.start + point.node.length) return {node:point.node, offset:Math.max(0, index - point.start)};
    }
    const last = points[points.length - 1];
    return {node:last.node, offset:last.node.length};
  }
  function splitOversizedTextBlock(block, page, contentBottom) {
    if (!block || !['P', 'H1', 'H2', 'H3'].includes(block.tagName)) return null;
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
    const points = [];
    let total = 0, text = '', current;
    while ((current = walker.nextNode())) {
      points.push({node:current, start:total});
      total += current.length;
      text += current.nodeValue;
    }
    if (!total) return null;
    const first = points[0].node;
    function fits(end) {
      const endPoint = rangePoint(points, end);
      const range = document.createRange();
      range.setStart(first, 0);
      range.setEnd(endPoint.node, endPoint.offset);
      return range.getBoundingClientRect().bottom <= contentBottom;
    }
    let low = 0, high = total;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (fits(middle)) low = middle;
      else high = middle - 1;
    }
    let cut = low;
    const whitespace = text.lastIndexOf(' ', cut);
    if (whitespace > Math.max(0, cut - 160)) cut = whitespace + 1;
    if (cut <= 0 || cut >= total) return null;
    const selection = window.getSelection();
    const anchorText = selection && points.find(point => point.node === selection.anchorNode);
    const focusText = selection && points.find(point => point.node === selection.focusNode);
    const anchorIndex = anchorText ? anchorText.start + selection.anchorOffset : null;
    const focusIndex = focusText ? focusText.start + selection.focusOffset : null;
    const startPoint = rangePoint(points, cut);
    const endPoint = rangePoint(points, total);
    const tailRange = document.createRange();
    tailRange.setStart(startPoint.node, startPoint.offset);
    tailRange.setEnd(endPoint.node, endPoint.offset);
    const continuation = block.cloneNode(false);
    continuation.dataset.autoContinuation = 'true';
    continuation.append(tailRange.extractContents());
    if (selection && anchorIndex !== null && focusIndex !== null && anchorIndex >= cut && focusIndex >= cut) {
      function continuationPoint(index) {
        let remaining = index - cut;
        const tailWalker = document.createTreeWalker(continuation, NodeFilter.SHOW_TEXT);
        let tailText, lastText = null;
        while ((tailText = tailWalker.nextNode())) {
          lastText = tailText;
          if (remaining <= tailText.length) return {node:tailText, offset:remaining};
          remaining -= tailText.length;
        }
        return lastText ? {node:lastText, offset:lastText.length} : null;
      }
      const anchor = continuationPoint(anchorIndex), focus = continuationPoint(focusIndex);
      if (anchor && focus && selection.setBaseAndExtent) selection.setBaseAndExtent(anchor.node, anchor.offset, focus.node, focus.offset);
    }
    return continuation;
  }
  function paginate() {
    let paginationChanged = false;
    const selection = window.getSelection();
    const activeSelection = selection && selection.anchorNode && sheet.contains(selection.anchorNode)
      ? {
          anchor: selectionOffset(selection.anchorNode, selection.anchorOffset),
          focus: selectionOffset(selection.focusNode, selection.focusOffset),
        }
      : null;
    let pages = Array.from(sheet.querySelectorAll(':scope > .dd-page'));
    if (!pages.length) pages = [createPage()];
    // Pull content out of any accidental root-level nodes created by browser
    // editing, while preserving the content and active selection.
    const stray = Array.from(sheet.childNodes).filter(node => !(node.nodeType === Node.ELEMENT_NODE && node.classList.contains('dd-page')));
    if (stray.length) { pages[pages.length - 1].append(...stray); paginationChanged = true; }
    for (let pageIndex = 0; pageIndex < pages.length; pageIndex++) {
      const page = pages[pageIndex];
      const pageRect = page.getBoundingClientRect();
      const style = getComputedStyle(page);
      const contentBottom = pageRect.bottom - (parseFloat(style.paddingBottom) || 0);
      const nodes = Array.from(page.childNodes).filter(node => !(node.nodeType === Node.ELEMENT_NODE && node.classList.contains('dd-page-zones')));
      for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
        const node = nodes[nodeIndex];
        if (node.parentNode !== page) continue;
        if (node.nodeType === Node.ELEMENT_NODE && node.dataset.pageBreak === 'true') {
          if (nodeIndex < nodes.length - 1) {
            let next = pages[pageIndex + 1];
            if (!next) { next = createPage(page); pages.push(next); }
            moveBefore(nodes.slice(nodeIndex + 1), next);
            paginationChanged = true;
            break;
          }
          continue;
        }
        if (node.getBoundingClientRect().bottom <= contentBottom + 1) continue;
        if (nodeIndex > 0) {
          let next = pages[pageIndex + 1];
          if (!next) { next = createPage(page); pages.push(next); }
          moveBefore(nodes.slice(nodeIndex), next);
          paginationChanged = true;
          break;
        }
        const continuation = splitOversizedTextBlock(node, page, contentBottom);
        if (continuation) {
          let next = pages[pageIndex + 1];
          if (!next) { next = createPage(page); pages.push(next); }
          next.insertBefore(continuation, next.firstChild);
          paginationChanged = true;
        }
      }
    }
    pages = Array.from(sheet.querySelectorAll(':scope > .dd-page'));
    while (pages.length > 1 && !Array.from(pages[pages.length - 1].childNodes).some(node => !(node.nodeType === Node.ELEMENT_NODE && node.classList.contains('dd-page-zones')))) {
      pages.pop().remove(); paginationChanged = true;
    }
    pages.forEach((page, index) => { page.dataset.pageNumber = String(index + 1); });
    if (paginationChanged && activeSelection && activeSelection.anchor !== null && activeSelection.focus !== null && selection.setBaseAndExtent) {
      const anchor = historyPointAt(activeSelection.anchor);
      const focus = historyPointAt(activeSelection.focus);
      if (anchor && focus) selection.setBaseAndExtent(anchor.node, anchor.offset, focus.node, focus.offset);
    }
    syncLetterheadPages();
  }
  paginate();
  let timer = 0, saving = false, dirty = false;
  function serializeInline(node) {
    if (node.nodeType === Node.TEXT_NODE) return [{type:'text',text:node.nodeValue.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g,'')}];
    if (node.nodeType !== Node.ELEMENT_NODE) return [];
    const marks = [];
    const chain = [];
    for (let el=node; el && el !== sheet; el=el.parentElement) chain.unshift(el);
    for (const el of chain) {
      if (el.tagName === 'B' || el.tagName === 'STRONG') marks.push({type:'bold'});
      else if (el.tagName === 'I' || el.tagName === 'EM') marks.push({type:'italic'});
      else if (el.tagName === 'U') marks.push({type:'underline'});
      else if (el.tagName === 'S' || el.tagName === 'STRIKE' || el.tagName === 'DEL') marks.push({type:'strike'});
      else if (el.tagName === 'A') { try { const u=new URL(el.href); if(['https:','http:','mailto:'].includes(u.protocol)) marks.push({type:'link',attrs:{href:u.href}}); } catch (_) {} }
      if (el.dataset.ddFontFamily) marks.push({type:'fontFamily',attrs:{value:el.dataset.ddFontFamily}});
      if (el.dataset.ddFontSize) marks.push({type:'fontSize',attrs:{value:Number(el.dataset.ddFontSize)}});
      if (el.dataset.ddTextColor) marks.push({type:'textColor',attrs:{color:el.dataset.ddTextColor}});
      if (el.dataset.ddHighlight) marks.push({type:'highlight',attrs:{color:el.dataset.ddHighlight}});
    }
    const uniqueMarks=[];
    marks.forEach(mark=>{const existing=uniqueMarks.findIndex(item=>item.type===mark.type);if(existing>=0)uniqueMarks.splice(existing,1);uniqueMarks.push(mark);});
    if (node.tagName === 'BR') return [{type:'text',text:'\n',...(uniqueMarks.length?{marks:uniqueMarks}: {})}];
    return Array.from(node.childNodes).flatMap(serializeInline).map(n => n.type === 'text' && uniqueMarks.length ? ({...n,marks:[...uniqueMarks,...(n.marks||[])]}) : n);
  }
  function serializeBlock(el) {
    if (el.nodeType === Node.TEXT_NODE) return el.nodeValue.trim() ? [{type:'paragraph',content:[{type:'text',text:el.nodeValue}]}] : [];
    if (el.nodeType !== Node.ELEMENT_NODE) return [];
    if (el.classList.contains('dd-page-zones')) return [];
    const tag=el.tagName; let type=allowedTags[tag];
    if (!type) return Array.from(el.childNodes).flatMap(serializeBlock);
    if (type === 'hardBreak') return el.dataset.pageBreak === 'true' ? [{type}] : [];
    if (type === 'horizontalRule') return [{type}];
    if (tag === 'IMG') { const frame=el.closest('.dd-image-frame');return [{type:'image',attrs:{asset_id:el.dataset.assetId||'',alt:(el.alt||'').slice(0,300),width_percent:Math.min(100,Math.max(10,Number(frame&&frame.dataset.widthPercent)||100)),align:frame&&frame.dataset.imageAlign||'center',crop:frame&&frame.dataset.crop||'none'}}]; }
    if (tag === 'P' && el.dataset.pageBreak === 'true') return [{type:'hardBreak'}];
    if (tag === 'TABLE') return [{type:'table',content:Array.from(el.rows).map(row=>({type:'tableRow',content:Array.from(row.cells).map(cell=>({type:'tableCell',content:Array.from(cell.childNodes).flatMap(serializeInline)}))}))}];
    if (type === 'heading') return [{type,level:Number(tag.slice(1)),...(el.dataset.align?{attrs:{align:el.dataset.align}}:{}),content:Array.from(el.childNodes).flatMap(serializeInline),...(el.dataset.autoContinuation === 'true' ? {_autoContinuation:true} : {})}];
    if ((type === 'bulletList' && el.dataset.checklist === 'true') || type === 'orderedList') {
      const attrs = type === 'bulletList' && el.dataset.checklist === 'true' ? {list_style:'checklist'} : {};
      return [{type,...(Object.keys(attrs).length ? {attrs} : {}),content:Array.from(el.children).flatMap(serializeBlock)}];
    }
    if (type === 'paragraph' || type === 'tableCell') {
      const content=Array.from(el.childNodes).flatMap(serializeInline);
      const attrs={}; const align=el.dataset.align || (el.style.textAlign || '');
      if (['left','right','center','justify'].includes(align)) attrs.align=align;
      const indent = Number(el.dataset.indent || 0);
      if (Number.isInteger(indent) && indent > 0 && indent <= 4) attrs.indent=indent;
      if (['single','1.15','1.5','double'].includes(el.dataset.lineSpacing)) attrs.line_spacing=el.dataset.lineSpacing;
      return [{type,...(Object.keys(attrs).length?{attrs}:{}),content,...(el.dataset.autoContinuation === 'true' ? {_autoContinuation:true} : {})}];
    }
    return [{type,content:Array.from(el.children).flatMap(serializeBlock)}];
  }
  function payload() {
    const content=Array.from(sheet.childNodes).flatMap(serializeBlock);
    const joined=[];
    content.forEach(node=>{
      if(node._autoContinuation && joined.length && joined[joined.length-1].type===node.type){
        joined[joined.length-1].content.push(...(node.content||[]));
        delete node._autoContinuation;
      }else{
        delete node._autoContinuation;
        joined.push(node);
      }
    });
    return {title:title.value,content:{type:'doc',content:joined.length?joined:[{type:'paragraph',content:[]}]},letterhead_enabled:document.getElementById('dd-letterhead').checked,letterhead_page_mode:letterheadOther.value==='none'?'first':'every',letterhead_first_slot:letterheadFirst.value,letterhead_other_slot:letterheadOther.value,version:Number(root.dataset.version)};
  }
  let historyCurrent=null,historyRestoring=false;
  const undoHistory=[],redoHistory=[];
  const historyLimit=150;
  function selectionOffset(container,offset){
    if(!container||!sheet.contains(container))return null;
    try{const range=document.createRange();range.selectNodeContents(sheet);range.setEnd(container,offset);return range.toString().length;}catch(_){return null;}
  }
  function historySnapshot(){
    const state=payload();delete state.version;
    const selection=window.getSelection();
    const savedSelection=selection&&selection.rangeCount?{anchor:selectionOffset(selection.anchorNode,selection.anchorOffset),focus:selectionOffset(selection.focusNode,selection.focusOffset)}:null;
    return JSON.stringify({state,selection:savedSelection});
  }
  function updateHistoryButtons(){
    const undo=document.getElementById('dd-undo'),redo=document.getElementById('dd-redo');
    undo.disabled=undoHistory.length===0;redo.disabled=redoHistory.length===0;
    undo.setAttribute('aria-disabled',String(undo.disabled));redo.setAttribute('aria-disabled',String(redo.disabled));
  }
  function historyPointAt(offset){
    const walker=document.createTreeWalker(sheet,NodeFilter.SHOW_TEXT);let node,remaining=Math.max(0,Number(offset)||0),last=null;
    while((node=walker.nextNode())){last=node;if(remaining<=node.length)return {node,offset:remaining};remaining-=node.length;}
    return last?{node:last,offset:last.length}:null;
  }
  function restoreHistory(snapshot){
    const saved=JSON.parse(snapshot),state=saved.state;
    historyRestoring=true;
    title.value=state.title||'';
    const fileTitle=document.getElementById('dd-file-title');if(fileTitle)fileTitle.value=title.value;
    document.getElementById('dd-letterhead').checked=Boolean(state.letterhead_enabled);
    letterheadFirst.value=state.letterhead_first_slot||'1';letterheadOther.value=state.letterhead_other_slot||'none';
    sheet.replaceChildren();const page=createPage();
    ((state.content&&state.content.content)||[]).forEach(node=>renderNode(node,page));
    if(!page.children.length)page.append(document.createElement('p'));
    paginate();historyRestoring=false;
    const pointA=saved.selection&&historyPointAt(saved.selection.anchor),pointF=saved.selection&&historyPointAt(saved.selection.focus),selection=window.getSelection();
    if(pointA&&pointF&&selection&&selection.setBaseAndExtent)selection.setBaseAndExtent(pointA.node,pointA.offset,pointF.node,pointF.offset);
    else if(selection){const first=sheet.querySelector('.dd-page p');if(first){const range=document.createRange();range.selectNodeContents(first);range.collapse(true);selection.removeAllRanges();selection.addRange(range);}}
    historyCurrent=historySnapshot();
    dirty=true;status.textContent='Unsaved changes';clearTimeout(timer);timer=setTimeout(save,800);updateHistoryButtons();
  }
  function undo(){if(!undoHistory.length)return;redoHistory.push(historySnapshot());restoreHistory(undoHistory.pop());}
  function redo(){if(!redoHistory.length)return;undoHistory.push(historySnapshot());restoreHistory(redoHistory.pop());}
  historyCurrent=historySnapshot();updateHistoryButtons();
  document.getElementById('dd-undo').addEventListener('mousedown',event=>event.preventDefault());
  document.getElementById('dd-redo').addEventListener('mousedown',event=>event.preventDefault());
  document.getElementById('dd-undo').addEventListener('click',undo);
  document.getElementById('dd-redo').addEventListener('click',redo);
  document.addEventListener('keydown',event=>{
    if(!(event.ctrlKey||event.metaKey))return;
    const key=event.key.toLowerCase();
    const selection=window.getSelection();
    const editorSelection=!!(selection&&selection.anchorNode&&sheet.contains(selection.anchorNode));
    const editorActive=sheet.contains(document.activeElement)||editorSelection;
    if(!editorActive)return;
    if(key==='z'){event.preventDefault();event.shiftKey?redo():undo();}
    else if(key==='y'){event.preventDefault();redo();}
    else if(key==='s'){event.preventDefault();root.dispatchEvent(new Event('digidoc:save'));}
    else if(key==='k'){event.preventDefault();document.getElementById('dd-link').click();}
    else if(key==='enter'){event.preventDefault();document.getElementById('dd-break').click();}
  });
  async function save() {
    if (saving || !dirty) return;
    saving=true; dirty=false; status.textContent='Saving…';
    try {
      const response=await fetch(root.dataset.saveUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':getCookie('csrftoken')},body:JSON.stringify(payload())});
      const result=await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save');
      root.dataset.version=result.version; status.textContent=`Saved ${result.updated_at}`;
    } catch(e) { dirty=true; status.textContent=e.message || 'Save failed'; }
    finally { saving=false; if(dirty) schedule(); }
  }
  root.addEventListener('digidoc:save',()=>{dirty=true;save();});
  document.getElementById('dd-save-now').addEventListener('click',()=>root.dispatchEvent(new Event('digidoc:save')));
  async function flushSave() {
    const deadline=Date.now()+15000;
    while(Date.now()<deadline){
      if(!saving&&dirty){clearTimeout(timer);const saved=await save();if(saved===false)return false;}
      else if(!saving&&!dirty)return true;
      await new Promise(resolve=>window.setTimeout(resolve,100));
      if(!saving&&dirty&&status.textContent!=='Unsaved changes'&&status.textContent!=='Saving...'&&!status.textContent.startsWith('Saved '))return false;
    }
    return !saving&&!dirty;
  }
  document.getElementById('dd-preview').addEventListener('click',async event=>{
    event.preventDefault();
    const previewUrl=event.currentTarget.href;
    const previewWindow=window.open('about:blank','_blank');
    if(!previewWindow){status.textContent='Allow pop-ups to open the preview.';return;}
    status.textContent='Saving before preview...';
    if(!(await flushSave())){previewWindow.close();status.textContent='Save failed. Preview was not opened.';return;}
    previewWindow.location.href=previewUrl;
  });
  function getCookie(name) { const found=document.cookie.split('; ').find(row=>row.startsWith(name+'=')); return found?decodeURIComponent(found.split('=').slice(1).join('=')):''; }
  function schedule() { paginate(); if(!historyRestoring){const current=historySnapshot();if(historyCurrent!==null&&current!==historyCurrent){undoHistory.push(historyCurrent);if(undoHistory.length>historyLimit)undoHistory.shift();redoHistory.length=0;historyCurrent=current;updateHistoryButtons();}} dirty=true; status.textContent='Unsaved changes'; clearTimeout(timer); timer=setTimeout(save,800); }
  sheet.addEventListener('input',schedule); title.addEventListener('input',schedule);
  ['dd-letterhead','dd-letterhead-first','dd-letterhead-other'].forEach(id=>document.getElementById(id).addEventListener('change',()=>{syncLetterheadPages();schedule();}));
  document.querySelectorAll('[data-command]').forEach(button=>button.addEventListener('click',()=>{sheet.focus();document.execCommand(button.dataset.command,false,null);schedule();}));
  function runBlock(value){sheet.focus();document.execCommand('formatBlock',false,value);schedule();}
  function currentBlock(){const selection=window.getSelection();let node=selection&&selection.anchorNode;if(node&&node.nodeType===Node.TEXT_NODE)node=node.parentElement;const block=node&&node.closest('p,h1,h2,h3,td,th');return block&&sheet.contains(block)?block:null;}
  function selectedBlocks(){
    const selection=window.getSelection();let blocks=[];
    if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode)){
      const range=selection.getRangeAt(0);
      if(range.collapsed){const block=currentBlock();if(block)blocks=[block];}
      else blocks=Array.from(sheet.querySelectorAll('.dd-page p,.dd-page h1,.dd-page h2,.dd-page h3,.dd-page td,.dd-page th')).filter(block=>{try{return range.intersectsNode(block);}catch(_){return false;}});
    }
    if(!blocks.length){const block=currentBlock();if(block)blocks=[block];}
    return blocks;
  }
  function runAlign(value){
    if(!['left','right','center','justify'].includes(value))return;
    const blocks=selectedBlocks();if(!blocks.length)return;
    blocks.forEach(block=>{block.dataset.align=value;block.style.textAlign='';});
    schedule();
  }
  document.getElementById('dd-block').addEventListener('change',e=>runBlock(e.target.value));
  document.getElementById('dd-block-toolbar').addEventListener('change',e=>runBlock(e.target.value));
  document.getElementById('dd-align').addEventListener('change',e=>runAlign(e.target.value));
  const alignmentLabels={left:'Align left',center:'Centre',right:'Align right',justify:'Justify'};
  const alignmentIcons={left:'M4 6h16M4 10h11M4 14h16M4 18h11',center:'M4 6h16M7 10h10M4 14h16M7 18h10',right:'M4 6h16M9 10h11M4 14h16M9 18h11',justify:'M4 6h16M4 10h16M4 14h16M4 18h16'};
  const alignAction=document.getElementById('dd-align-action');
  const alignToggle=document.getElementById('dd-align-menu-toggle');
  const alignMenu=document.getElementById('dd-align-menu');
  function setAlignment(value){
    const select=document.getElementById('dd-align');select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));
    alignAction.querySelector('path').setAttribute('d',alignmentIcons[value]);alignAction.title=alignmentLabels[value];alignAction.setAttribute('aria-label',alignmentLabels[value]);
    alignMenu.querySelectorAll('[data-align-choice]').forEach(option=>option.setAttribute('aria-checked',String(option.dataset.alignChoice===value)));
  }
  alignAction.addEventListener('mousedown',e=>e.preventDefault());
  alignAction.addEventListener('click',()=>setAlignment('left'));
  alignToggle.addEventListener('mousedown',e=>e.preventDefault());
  alignToggle.addEventListener('click',()=>{const open=alignMenu.hidden;if(open){const rect=alignToggle.getBoundingClientRect();alignMenu.style.top=`${rect.bottom+5}px`;alignMenu.style.left=`${rect.left}px`;}alignMenu.hidden=!open;alignToggle.setAttribute('aria-expanded',String(open));});
  alignMenu.querySelectorAll('[data-align-choice]').forEach(option=>{
    option.addEventListener('mousedown',e=>e.preventDefault());
    option.addEventListener('click',()=>{setAlignment(option.dataset.alignChoice);alignMenu.hidden=true;alignToggle.setAttribute('aria-expanded','false');alignToggle.focus();});
  });
  document.getElementById('dd-align-toolbar').addEventListener('change',e=>runAlign(e.target.value));
  function setParagraphAttr(name,value){sheet.focus();const blocks=selectedBlocks();if(!blocks.length)return;blocks.forEach(block=>{if(value===null)delete block.dataset[name];else block.dataset[name]=value;});schedule();}
  ['dd-indent-in','dd-indent-out','dd-break','dd-table'].forEach(id=>document.getElementById(id).addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();}));
  document.querySelectorAll('[data-command]:not(:disabled)').forEach(button=>button.addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();}));
  function adjustIndent(direction){const blocks=selectedBlocks();if(!blocks.length)return;blocks.forEach(block=>{const next=Math.max(0,Math.min(4,Number(block.dataset.indent||0)+direction));if(next)block.dataset.indent=String(next);else delete block.dataset.indent;});schedule();}
  document.getElementById('dd-indent-in').addEventListener('click',()=>adjustIndent(1));
  document.getElementById('dd-indent-out').addEventListener('click',()=>adjustIndent(-1));
  document.getElementById('dd-line-spacing').addEventListener('change',e=>setParagraphAttr('lineSpacing',e.target.value));
  const spacingAction=document.getElementById('dd-line-spacing-action');
  const spacingToggle=document.getElementById('dd-spacing-menu-toggle');
  const spacingMenu=document.getElementById('dd-spacing-menu');
  function setSpacing(value){
    const select=document.getElementById('dd-line-spacing');select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));
    const labels={single:'Single', '1.15':'1.15', '1.5':'1.5', double:'Double'};
    spacingAction.title='Apply '+labels[value]+' line spacing';spacingAction.setAttribute('aria-label',spacingAction.title);
    spacingMenu.querySelectorAll('[data-spacing-choice]').forEach(option=>option.setAttribute('aria-checked',String(option.dataset.spacingChoice===value)));
  }
  spacingAction.addEventListener('mousedown',e=>e.preventDefault());
  spacingAction.addEventListener('click',()=>setSpacing('single'));
  spacingToggle.addEventListener('mousedown',e=>e.preventDefault());
  spacingToggle.addEventListener('click',()=>{const open=spacingMenu.hidden;if(open){const rect=spacingToggle.getBoundingClientRect();spacingMenu.style.top=`${rect.bottom+5}px`;spacingMenu.style.left=`${rect.left}px`;}spacingMenu.hidden=!open;spacingToggle.setAttribute('aria-expanded',String(open));});
  spacingMenu.querySelectorAll('[data-spacing-choice]').forEach(option=>{
    option.addEventListener('mousedown',e=>e.preventDefault());
    option.addEventListener('click',()=>{setSpacing(option.dataset.spacingChoice);spacingMenu.hidden=true;spacingToggle.setAttribute('aria-expanded','false');spacingToggle.focus();});
  });
  document.addEventListener('click',event=>{
    if(!event.target.closest('#dd-align-menu-toggle, #dd-align-menu')){alignMenu.hidden=true;alignToggle.setAttribute('aria-expanded','false');}
    if(!event.target.closest('#dd-spacing-menu-toggle, #dd-spacing-menu')){spacingMenu.hidden=true;spacingToggle.setAttribute('aria-expanded','false');}
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'){
      if(!alignMenu.hidden){alignMenu.hidden=true;alignToggle.setAttribute('aria-expanded','false');alignToggle.focus();}
      if(!spacingMenu.hidden){spacingMenu.hidden=true;spacingToggle.setAttribute('aria-expanded','false');spacingToggle.focus();}
    }
  });
  document.getElementById('dd-checklist').addEventListener('mousedown',e=>e.preventDefault());
  document.getElementById('dd-checklist').addEventListener('click',()=>{
    sheet.focus();
    const selection=window.getSelection();let node=selection&&selection.anchorNode;if(node&&node.nodeType===Node.TEXT_NODE)node=node.parentElement;
    const list=node&&node.closest('ul');
    if(list&&sheet.contains(list)){if(list.dataset.checklist==='true')delete list.dataset.checklist;else list.dataset.checklist='true';schedule();return;}
    document.execCommand('insertUnorderedList',false,null);
    const next=window.getSelection();let current=next&&next.anchorNode;if(current&&current.nodeType===Node.TEXT_NODE)current=current.parentElement;
    const created=current&&current.closest('ul');if(created&&sheet.contains(created))created.dataset.checklist='true';schedule();
  });
  document.getElementById('dd-indent-in-menu').addEventListener('click',()=>document.getElementById('dd-indent-in').click());
  document.getElementById('dd-indent-out-menu').addEventListener('click',()=>document.getElementById('dd-indent-out').click());
  document.getElementById('dd-line-spacing-menu').addEventListener('change',e=>{document.getElementById('dd-line-spacing').value=e.target.value;setParagraphAttr('lineSpacing',e.target.value);});
  let savedRange=null;
  document.addEventListener('selectionchange',()=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();});
  function applyInlineMark(datasetKey,value){
    sheet.focus();const selection=window.getSelection();
    if(savedRange&&selection){selection.removeAllRanges();selection.addRange(savedRange);}
    if(!selection||selection.isCollapsed||!selection.rangeCount)return;
    const range=selection.getRangeAt(0);if(!sheet.contains(range.commonAncestorContainer))return;
    const attrName={ddFontFamily:'data-dd-font-family',ddFontSize:'data-dd-font-size',ddTextColor:'data-dd-text-color',ddHighlight:'data-dd-highlight'}[datasetKey];
    if(!attrName)return;
    const styleName={ddFontFamily:'font-family',ddFontSize:'font-size',ddTextColor:'color',ddHighlight:'background-color'}[datasetKey];
    let ancestor=range.commonAncestorContainer.nodeType===Node.ELEMENT_NODE?range.commonAncestorContainer:range.commonAncestorContainer.parentElement;
    while(ancestor&&ancestor!==sheet){
      if(ancestor.hasAttribute(attrName)){
        const contents=document.createRange();contents.selectNodeContents(ancestor);
        const coversWholeMark=range.compareBoundaryPoints(Range.START_TO_START,contents)<=0&&range.compareBoundaryPoints(Range.END_TO_END,contents)>=0;
        if(coversWholeMark){ancestor.removeAttribute(attrName);ancestor.style.removeProperty(styleName);}
      }
      ancestor=ancestor.parentElement;
    }
    const fragment=range.extractContents();
    fragment.querySelectorAll(`[${attrName}]`).forEach(previous=>{
      const parent=previous.parentNode;if(!parent)return;
      while(previous.firstChild)parent.insertBefore(previous.firstChild,previous);
      previous.remove();
    });
    const wrapper=document.createElement(datasetKey==='ddHighlight'?'mark':'span');wrapper.dataset[datasetKey]=value;
    const styleValue=datasetKey==='ddFontFamily'?(({'Helvetica':'Arial,sans-serif','Times-Roman':'"Times New Roman",serif','Courier':'"Courier New",monospace'})[value]||'"'+value+'"'):datasetKey==='ddFontSize'?`${value}pt`:value;
    if(datasetKey==='ddFontFamily')wrapper.style.fontFamily=styleValue;
    else if(datasetKey==='ddFontSize')wrapper.style.fontSize=styleValue;
    else if(datasetKey==='ddTextColor')wrapper.style.color=styleValue;
    else wrapper.style.backgroundColor=styleValue;
    wrapper.append(fragment);range.insertNode(wrapper);
    selection.removeAllRanges();const next=document.createRange();next.selectNodeContents(wrapper);selection.addRange(next);savedRange=next.cloneRange();schedule();
  }
  ['dd-font-family','dd-font-size','dd-text-color','dd-highlight-color'].forEach(id=>document.getElementById(id).addEventListener('mousedown',()=>{const selection=window.getSelection();if(selection&&selection.rangeCount)savedRange=selection.getRangeAt(0).cloneRange();}));
  document.getElementById('dd-font-family').addEventListener('change',e=>applyInlineMark('ddFontFamily',e.target.value));
  document.getElementById('dd-font-size').addEventListener('change',e=>applyInlineMark('ddFontSize',String(Number(e.target.value))));
  function stepFontSize(direction){const control=document.getElementById('dd-font-size');const sizes=[8,9,10,11,12,14,16,18,24,36,48];const current=Number(control.value)||10;const index=sizes.indexOf(current);const next=sizes[Math.max(0,Math.min(sizes.length-1,index+direction))];control.value=String(next);applyInlineMark('ddFontSize',String(next));}
  document.getElementById('dd-grow-font').addEventListener('mousedown',e=>e.preventDefault());document.getElementById('dd-shrink-font').addEventListener('mousedown',e=>e.preventDefault());
  document.getElementById('dd-grow-font').addEventListener('click',()=>stepFontSize(1));document.getElementById('dd-shrink-font').addEventListener('click',()=>stepFontSize(-1));
  document.getElementById('dd-text-color').addEventListener('change',e=>applyInlineMark('ddTextColor',e.target.value.toUpperCase()));
  document.getElementById('dd-highlight-color').addEventListener('change',e=>applyInlineMark('ddHighlight',e.target.value.toUpperCase()));
  function insertTable(){sheet.focus();document.execCommand('insertHTML',false,'<table><tbody><tr><td><br></td><td><br></td></tr><tr><td><br></td><td><br></td></tr></tbody></table><p><br></p>');schedule();}
  document.getElementById('dd-table').addEventListener('click',insertTable);
  document.getElementById('dd-table-toolbar').addEventListener('click',insertTable);
  function insertBreak(){
    const selection=window.getSelection();
    if(savedRange&&sheet.contains(savedRange.commonAncestorContainer)&&selection){selection.removeAllRanges();selection.addRange(savedRange);}
    let range=selection&&selection.rangeCount?selection.getRangeAt(0):null;
    if(!range||!sheet.contains(range.startContainer)){const page=activePage();const paragraph=document.createElement('p');paragraph.append(document.createElement('br'));page.append(paragraph);range=document.createRange();range.selectNodeContents(paragraph);range.collapse(true);selection.removeAllRanges();selection.addRange(range);}
    if(!range.collapsed)range.deleteContents();
    let start=range.startContainer;if(start.nodeType===Node.TEXT_NODE)start=start.parentElement;
    const block=start&&start.closest('p,h1,h2,h3');
    const marker=document.createElement('p');marker.dataset.pageBreak='true';marker.className='dd-page-break-marker';marker.contentEditable='false';marker.textContent='Page break';
    let continuation;
    if(block&&sheet.contains(block)){
      const tail=document.createRange();tail.selectNodeContents(block);tail.setStart(range.startContainer,range.startOffset);
      const contents=tail.extractContents();continuation=block.cloneNode(false);continuation.removeAttribute('data-page-break');continuation.append(contents);
      if(!continuation.childNodes.length)continuation.append(document.createElement('br'));
      block.after(marker,continuation);
    }else{
      continuation=document.createElement('p');continuation.append(document.createElement('br'));const page=activePage();page.append(marker,continuation);
    }
    const caret=document.createRange();caret.selectNodeContents(continuation);caret.collapse(true);selection.removeAllRanges();selection.addRange(caret);savedRange=caret.cloneRange();schedule();
  }
  document.getElementById('dd-break').addEventListener('click',insertBreak);
  document.getElementById('dd-break-toolbar').addEventListener('click',insertBreak);
  const lh=document.getElementById('dd-letterhead');
  syncLetterheadPages();
  lh.addEventListener('change',()=>{syncLetterheadPages();schedule();});
  document.getElementById('dd-rename').addEventListener('click',()=>{title.focus();title.select();});
  document.getElementById('dd-select-all').addEventListener('click',()=>{sheet.focus();document.execCommand('selectAll');});
  function clearFormatting(){sheet.focus();document.execCommand('removeFormat');document.execCommand('formatBlock',false,'p');schedule();}
  document.getElementById('dd-clear').addEventListener('click',clearFormatting);document.getElementById('dd-clear-format').addEventListener('click',clearFormatting);
  document.getElementById('dd-zoom').addEventListener('change',e=>{sheet.classList.forEach(name=>{if(name.startsWith('dd-zoom-'))sheet.classList.remove(name);});sheet.classList.add('dd-zoom-'+e.target.value);syncLetterheadPages();});
  const linkButton=document.getElementById('dd-link');
  linkButton.addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount)savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();});
  linkButton.addEventListener('click',()=>{
    const url=window.prompt('Enter a web or email link');
    if(url&&/^(https?:\/\/|mailto:)/i.test(url)){
      sheet.focus();const selection=window.getSelection();
      if(savedRange&&selection){selection.removeAllRanges();selection.addRange(savedRange);}
      const range=selection&&selection.rangeCount?selection.getRangeAt(0):null;
      if(!range||!sheet.contains(range.commonAncestorContainer))return;
      const link=document.createElement('a');link.href=url;link.rel='noopener noreferrer';
      if(range.collapsed)link.textContent=url;else link.append(range.extractContents());
      range.insertNode(link);selection.removeAllRanges();const next=document.createRange();next.selectNodeContents(link);selection.addRange(next);savedRange=next.cloneRange();schedule();
    }
  });
  document.getElementById('dd-print').addEventListener('click',()=>window.print());
  document.getElementById('dd-line').addEventListener('click',()=>{sheet.focus();const line=document.createElement('hr');activePage().append(line,document.createElement('p'));schedule();});
  document.getElementById('dd-insert-image').addEventListener('click',()=>{
    const picker=document.createElement('input');picker.type='file';picker.accept='image/png,image/jpeg';
    picker.addEventListener('change',async()=>{const file=picker.files&&picker.files[0];if(!file)return;const data=new FormData();data.append('image',file);status.textContent='Uploading image…';
      try{const response=await fetch('/digidoc/images/upload/',{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':getCookie('csrftoken')},body:data});const result=await response.json();if(!response.ok)throw new Error(result.error||'Image upload failed');const frame=makeImageFrame(result.id,'',result.url);activePage().append(frame,document.createElement('p'));frame.querySelector('img').addEventListener('load',schedule,{once:true});selectImage(frame);schedule();}
      catch(err){status.textContent=err.message||'Image upload failed';}
    });picker.click();
  });
  const imageTools=document.getElementById('dd-image-tools');
  const imageControls={width:document.getElementById('dd-image-width'),align:document.getElementById('dd-image-align'),crop:document.getElementById('dd-image-crop')};
  let selectedImage=null;
  function syncImageControls(frame){
    const enabled=Boolean(frame&&sheet.contains(frame));
    Object.values(imageControls).forEach(control=>control.disabled=!enabled);
    ['dd-image-move','dd-image-remove'].forEach(id=>document.getElementById(id).disabled=!enabled);
    if(!enabled){imageTools.hidden=true;selectedImage=null;return;}
    selectedImage=frame;imageTools.hidden=false;imageControls.width.value=frame.dataset.widthPercent||'100';document.getElementById('dd-image-width-value').textContent=`${imageControls.width.value}%`;imageControls.align.value=frame.dataset.imageAlign||'center';imageControls.crop.value=frame.dataset.crop||'none';
  }
  function selectImage(frame){sheet.querySelectorAll('.dd-image-frame.is-selected').forEach(item=>item.classList.remove('is-selected'));if(frame)frame.classList.add('is-selected');syncImageControls(frame);}
  sheet.addEventListener('click',event=>{const frame=event.target.closest('.dd-image-frame');if(frame)selectImage(frame);else if(!event.target.closest('#dd-image-tools'))selectImage(null);});
  function updateImage(){
    if(!selectedImage||!sheet.contains(selectedImage))return;
    selectedImage.dataset.widthPercent=imageControls.width.value;selectedImage.style.width=`${imageControls.width.value}%`;document.getElementById('dd-image-width-value').textContent=`${imageControls.width.value}%`;
    selectedImage.dataset.imageAlign=imageControls.align.value;selectedImage.style.marginLeft=imageControls.align.value==='right'?'auto':imageControls.align.value==='center'?'auto':'0';selectedImage.style.marginRight=imageControls.align.value==='left'?'auto':imageControls.align.value==='center'?'auto':'0';
    selectedImage.dataset.crop=imageControls.crop.value;selectedImage.style.setProperty('--dd-image-ratio',({square:'1 / 1',landscape:'16 / 9',portrait:'3 / 4'})[imageControls.crop.value]||'auto');selectedImage.querySelector('img').style.objectFit=imageControls.crop.value==='none'?'contain':'cover';schedule();
  }
  Object.values(imageControls).forEach(control=>control.addEventListener(control.type==='range'?'input':'change',updateImage));
  document.getElementById('dd-image-remove').addEventListener('click',()=>{if(selectedImage){const parent=selectedImage.parentElement;selectedImage.remove();selectImage(null);if(parent&&!parent.querySelector(':scope > *'))parent.append(document.createElement('p'));schedule();}});
  document.getElementById('dd-image-move').addEventListener('click',()=>{if(selectedImage)status.textContent='Drag the selected image to a new position on the page.';});
  let pointerStart=null;
  sheet.addEventListener('pointerdown',event=>{const frame=event.target.closest('.dd-image-frame');if(!frame||event.button!==0)return;selectImage(frame);pointerStart={frame,x:event.clientX,y:event.clientY,moved:false};});
  document.addEventListener('pointermove',event=>{if(!pointerStart)return;if(!pointerStart.moved&&Math.hypot(event.clientX-pointerStart.x,event.clientY-pointerStart.y)>6){pointerStart.moved=true;pointerStart.frame.classList.add('is-dragging');}});
  document.addEventListener('pointerup',event=>{
    if(!pointerStart)return;const drag=pointerStart;pointerStart=null;drag.frame.classList.remove('is-dragging');if(!drag.moved)return;
    let range=null;if(document.caretRangeFromPoint)range=document.caretRangeFromPoint(event.clientX,event.clientY);else if(document.caretPositionFromPoint){const point=document.caretPositionFromPoint(event.clientX,event.clientY);if(point){range=document.createRange();range.setStart(point.offsetNode,point.offset);range.collapse(true);}}
    const element=range&&(range.startContainer.nodeType===Node.ELEMENT_NODE?range.startContainer:range.startContainer.parentElement);const page=element&&element.closest('.dd-page');if(!page||!sheet.contains(page))return;
    let target=element.closest('p,h1,h2,h3,ul,ol,table,.dd-image-frame');if(target===drag.frame)target=null;
    if(target){const rect=target.getBoundingClientRect();if(event.clientY>rect.top+rect.height/2)target.after(drag.frame);else target.before(drag.frame);}else page.append(drag.frame);
    selectImage(drag.frame);schedule();
  });
  function wordCount(){const text=(sheet.innerText||'').trim();const words=text?text.split(/\s+/).filter(Boolean).length:0;document.getElementById('dd-word-count').textContent=words+' '+(words===1?'word':'words');const statusCount=document.getElementById('dd-status-word-count');if(statusCount)statusCount.textContent=words+' '+(words===1?'word':'words');const total=sheet.querySelectorAll(':scope > .dd-page').length||1;const totalNode=document.getElementById('dd-page-total');if(totalNode)totalNode.textContent=String(total);const selection=window.getSelection();const anchor=selection&&selection.anchorNode;const element=anchor&&(anchor.nodeType===Node.ELEMENT_NODE?anchor:anchor.parentElement);const page=element&&element.closest('.dd-page');const current=document.getElementById('dd-current-page');if(current)current.textContent=page?.dataset.pageNumber||'1';}
  sheet.addEventListener('input',wordCount);wordCount();
  document.querySelectorAll('a[href*="/digidoc/"]').forEach(link=>link.addEventListener('click',async event=>{
    const href=link.href;
    if(!href.includes('/download.pdf')&&!href.includes('/preview/'))return;
    if(!dirty&&!saving)return;
    event.preventDefault();
    clearTimeout(timer);
    if(dirty)await save();
    while(saving)await new Promise(resolve=>setTimeout(resolve,50));
    if(!dirty)window.open(href,'_blank','noopener');
  }));
  function markdownInline(text) {
    const fragment=document.createDocumentFragment();
    const token=/(\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|\*[^*\n]+\*|_[^_\n]+_)/g;
    let start=0,match;
    while((match=token.exec(text))){
      fragment.append(document.createTextNode(text.slice(start,match.index)));
      const raw=match[0];let tag='strong',value=raw.slice(2,-2);
      if(raw.startsWith('~~')){tag='s';value=raw.slice(2,-2);}
      else if(raw.startsWith('__')){value=raw.slice(2,-2);}
      else if(raw.startsWith('*')){tag='em';value=raw.slice(1,-1);if(raw.startsWith('**')){tag='strong';value=raw.slice(2,-2);}}
      else if(raw.startsWith('_')){tag='em';value=raw.slice(1,-1);}
      const mark=document.createElement(tag);mark.textContent=value;fragment.append(mark);start=token.lastIndex;
    }
    fragment.append(document.createTextNode(text.slice(start)));
    const wrapper=document.createElement('span');wrapper.append(fragment);return wrapper.innerHTML;
  }
  function markdownBlocks(text) {
    const lines=text.replace(/\r\n?/g,'\n').split('\n'),rootNode=document.createElement('div');
    let index=0;
    const appendParagraph=(parts,tag='p')=>{const block=document.createElement(tag);block.dataset.align='left';parts.forEach((line,lineIndex)=>{if(lineIndex)block.append(document.createElement('br'));const inline=document.createElement('span');inline.innerHTML=markdownInline(line);block.append(...Array.from(inline.childNodes));});rootNode.append(block);};
    while(index<lines.length){
      if(!lines[index].trim()){index++;continue;}
      const heading=lines[index].match(/^\s{0,3}(#{1,3})\s+(.+?)\s*#*\s*$/);
      if(heading){appendParagraph([heading[2]],`h${heading[1].length}`);index++;continue;}
      const listMatch=lines[index].match(/^\s*([-+*]|\d+[.)])\s+(.+)$/);
      if(listMatch){
        const ordered=/^\d/.test(listMatch[1]),list=document.createElement(ordered?'ol':'ul');list.style.textAlign='left';
        while(index<lines.length){const item=lines[index].match(/^\s*([-+*]|\d+[.)])\s+(.+)$/);if(!item||/^\d/.test(item[1])!==ordered)break;const li=document.createElement('li'),inline=document.createElement('span');inline.innerHTML=markdownInline(item[2]);li.append(...Array.from(inline.childNodes));list.append(li);index++;}
        rootNode.append(list);continue;
      }
      const paragraph=[];
      while(index<lines.length&&lines[index].trim()&&!/^\s{0,3}#{1,3}\s+/.test(lines[index])&&!/^\s*([-+*]|\d+[.)])\s+/.test(lines[index]))paragraph.push(lines[index++]);
      appendParagraph(paragraph);
    }
    return rootNode.innerHTML;
  }
  sheet.addEventListener('paste',e=>{
    e.preventDefault();const text=(e.clipboardData||window.clipboardData).getData('text/plain');
    const hasMarkdown=/(^|\n)\s{0,3}#{1,3}\s|(^|\n)\s*([-+*]|\d+[.)])\s+|\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~/.test(text);
    if(hasMarkdown)document.execCommand('insertHTML',false,markdownBlocks(text));
    else document.execCommand('insertText',false,text);
    schedule();
  });
  window.addEventListener('beforeunload',e=>{if(dirty||saving){e.preventDefault();e.returnValue='';}});
})();
