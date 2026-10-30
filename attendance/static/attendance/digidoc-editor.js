(() => {
  'use strict';
  const root = document.getElementById('digidoc');
  if (!root) return;
  const sheet = document.getElementById('dd-sheet');
  const status = document.getElementById('dd-status');
  const title = document.getElementById('dd-title');
  const letterheadMode = document.getElementById('dd-letterhead-mode');
  const initial = JSON.parse(document.getElementById('dd-initial').textContent);
  const allowedTags = {P:'paragraph', H1:'heading', H2:'heading', H3:'heading', UL:'bulletList', OL:'orderedList', LI:'listItem', TABLE:'table', TBODY:'table', TR:'tableRow', TD:'tableCell', TH:'tableCell', BR:'hardBreak', HR:'horizontalRule', IMG:'image'};
  function renderNode(node, parent) {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'image') {
      const img=document.createElement('img'); img.dataset.assetId=node.attrs.asset_id; img.alt=node.attrs.alt||''; img.src='/digidoc/images/'+encodeURIComponent(node.attrs.asset_id)+'/'; img.className='dd-inline-image'; parent.append(img); return;
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
          if (mark.type === 'fontFamily') wrapper.style.fontFamily = ({'Helvetica':'Arial,sans-serif','Times-Roman':'"Times New Roman",serif','Courier':'"Courier New",monospace'})[value];
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
    if (node.type === 'hardBreak') { el.dataset.pageBreak='true'; el.textContent='Page break'; parent.append(el); return; }
    if (node.type === 'horizontalRule') { parent.append(el); return; }
    if (node.attrs && node.attrs.align) el.dataset.align = node.attrs.align;
    if (node.attrs && node.attrs.indent) el.dataset.indent = node.attrs.indent;
    if (node.attrs && node.attrs.line_spacing) el.dataset.lineSpacing = node.attrs.line_spacing;
    (node.content || []).forEach(child => renderNode(child, el));
    if (node.type === 'paragraph' && !el.childNodes.length) el.append(document.createElement('br'));
    parent.append(el);
  }
  function createPage(after) {
    const page = document.createElement('div');
    page.className = 'dd-page';
    page.dataset.pageNumber = String(sheet.querySelectorAll('.dd-page').length + 1);
    if (after && after.nextSibling) sheet.insertBefore(page, after.nextSibling);
    else sheet.append(page);
    return page;
  }
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
    let pages = Array.from(sheet.querySelectorAll(':scope > .dd-page'));
    if (!pages.length) pages = [createPage()];
    // Pull content out of any accidental root-level nodes created by browser
    // editing, while preserving the content and active selection.
    const stray = Array.from(sheet.childNodes).filter(node => !(node.nodeType === Node.ELEMENT_NODE && node.classList.contains('dd-page')));
    if (stray.length) pages[pages.length - 1].append(...stray);
    for (let pageIndex = 0; pageIndex < pages.length; pageIndex++) {
      const page = pages[pageIndex];
      const pageRect = page.getBoundingClientRect();
      const style = getComputedStyle(page);
      const contentBottom = pageRect.bottom - (parseFloat(style.paddingBottom) || 0);
      const nodes = Array.from(page.childNodes);
      for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
        const node = nodes[nodeIndex];
        if (node.parentNode !== page) continue;
        if (node.nodeType === Node.ELEMENT_NODE && node.dataset.pageBreak === 'true') {
          if (nodeIndex < nodes.length - 1) {
            let next = pages[pageIndex + 1];
            if (!next) { next = createPage(page); pages.push(next); }
            moveBefore(nodes.slice(nodeIndex + 1), next);
            break;
          }
          continue;
        }
        if (node.getBoundingClientRect().bottom <= contentBottom + 1) continue;
        if (nodeIndex > 0) {
          let next = pages[pageIndex + 1];
          if (!next) { next = createPage(page); pages.push(next); }
          moveBefore(nodes.slice(nodeIndex), next);
          break;
        }
        const continuation = splitOversizedTextBlock(node, page, contentBottom);
        if (continuation) {
          let next = pages[pageIndex + 1];
          if (!next) { next = createPage(page); pages.push(next); }
          next.insertBefore(continuation, next.firstChild);
        }
      }
    }
    pages = Array.from(sheet.querySelectorAll(':scope > .dd-page'));
    while (pages.length > 1 && !pages[pages.length - 1].childNodes.length) {
      pages.pop().remove();
    }
    pages.forEach((page, index) => { page.dataset.pageNumber = String(index + 1); });
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
    if (node.tagName === 'BR') return [{type:'text',text:'\n',...(marks.length?{marks}: {})}];
    return Array.from(node.childNodes).flatMap(serializeInline).map(n => n.type === 'text' && marks.length ? ({...n,marks:[...marks,...(n.marks||[])]}) : n);
  }
  function serializeBlock(el) {
    if (el.nodeType === Node.TEXT_NODE) return el.nodeValue.trim() ? [{type:'paragraph',content:[{type:'text',text:el.nodeValue}]}] : [];
    if (el.nodeType !== Node.ELEMENT_NODE) return [];
    const tag=el.tagName; let type=allowedTags[tag];
    if (!type) return Array.from(el.childNodes).flatMap(serializeBlock);
    if (type === 'hardBreak') return el.dataset.pageBreak === 'true' ? [{type}] : [];
    if (type === 'horizontalRule') return [{type}];
    if (tag === 'IMG') return [{type:'image',attrs:{asset_id:el.dataset.assetId||'',alt:(el.alt||'').slice(0,300)}}];
    if (tag === 'P' && el.dataset.pageBreak === 'true') return [{type:'hardBreak'}];
    if (tag === 'TABLE') return [{type:'table',content:Array.from(el.rows).map(row=>({type:'tableRow',content:Array.from(row.cells).map(cell=>({type:'tableCell',content:Array.from(cell.childNodes).flatMap(serializeInline)}))}))}];
    if (type === 'heading') return [{type,level:Number(tag.slice(1)),content:Array.from(el.childNodes).flatMap(serializeInline),...(el.dataset.autoContinuation === 'true' ? {_autoContinuation:true} : {})}];
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
    return {title:title.value,content:{type:'doc',content:joined.length?joined:[{type:'paragraph',content:[]}]},letterhead_enabled:document.getElementById('dd-letterhead').checked,letterhead_page_mode:document.getElementById('dd-letterhead-mode').value,version:Number(root.dataset.version)};
  }
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
  function getCookie(name) { const found=document.cookie.split('; ').find(row=>row.startsWith(name+'=')); return found?decodeURIComponent(found.split('=').slice(1).join('=')):''; }
  function schedule() { paginate(); dirty=true; status.textContent='Unsaved changes'; clearTimeout(timer); timer=setTimeout(save,800); }
  sheet.addEventListener('input',schedule); title.addEventListener('input',schedule);
  ['dd-letterhead','dd-letterhead-mode'].forEach(id=>document.getElementById(id).addEventListener('change',schedule));
  document.querySelectorAll('[data-command]').forEach(button=>button.addEventListener('click',()=>{sheet.focus();document.execCommand(button.dataset.command,false,null);schedule();}));
  function runBlock(value){sheet.focus();document.execCommand('formatBlock',false,value);schedule();}
  function currentBlock(){const selection=window.getSelection();let node=selection&&selection.anchorNode;if(node&&node.nodeType===Node.TEXT_NODE)node=node.parentElement;const block=node&&node.closest('p,h1,h2,h3,td,th');return block&&sheet.contains(block)?block:null;}
  function runAlign(value){sheet.focus();const block=currentBlock();if(block&&['left','right','center','justify'].includes(value)){block.dataset.align=value;block.style.textAlign='';schedule();}}
  document.getElementById('dd-block').addEventListener('change',e=>runBlock(e.target.value));
  document.getElementById('dd-block-toolbar').addEventListener('change',e=>runBlock(e.target.value));
  document.getElementById('dd-align').addEventListener('change',e=>runAlign(e.target.value));
  document.getElementById('dd-align-toolbar').addEventListener('change',e=>runAlign(e.target.value));
  function setParagraphAttr(name,value){sheet.focus();const block=currentBlock();if(!block)return;if(value===null)delete block.dataset[name];else block.dataset[name]=value;schedule();}
  document.getElementById('dd-indent-in').addEventListener('click',()=>{const block=currentBlock();if(block)setParagraphAttr('indent',Math.min(4,Number(block.dataset.indent||0)+1));});
  document.getElementById('dd-indent-out').addEventListener('click',()=>{const block=currentBlock();if(block)setParagraphAttr('indent',Math.max(0,Number(block.dataset.indent||0)-1)||null);});
  document.getElementById('dd-line-spacing').addEventListener('change',e=>setParagraphAttr('lineSpacing',e.target.value));
  document.getElementById('dd-indent-in-menu').addEventListener('click',()=>document.getElementById('dd-indent-in').click());
  document.getElementById('dd-indent-out-menu').addEventListener('click',()=>document.getElementById('dd-indent-out').click());
  document.getElementById('dd-line-spacing-menu').addEventListener('change',e=>{document.getElementById('dd-line-spacing').value=e.target.value;setParagraphAttr('lineSpacing',e.target.value);});
  let savedRange=null;
  document.addEventListener('selectionchange',()=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();});
  function applyInlineMark(datasetKey,value){sheet.focus();const selection=window.getSelection();if(savedRange&&selection){selection.removeAllRanges();selection.addRange(savedRange);}if(!selection||selection.isCollapsed||!selection.rangeCount)return;const range=selection.getRangeAt(0);if(!sheet.contains(range.commonAncestorContainer))return;const wrapper=document.createElement(datasetKey==='ddHighlight'?'mark':'span');wrapper.dataset[datasetKey]=value;const styleValue=datasetKey==='ddFontFamily'?({'Helvetica':'Arial,sans-serif','Times-Roman':'"Times New Roman",serif','Courier':'"Courier New",monospace'})[value]:datasetKey==='ddFontSize'?`${value}pt`:value;if(datasetKey==='ddFontFamily')wrapper.style.fontFamily=styleValue;else if(datasetKey==='ddFontSize')wrapper.style.fontSize=styleValue;else if(datasetKey==='ddTextColor')wrapper.style.color=styleValue;else wrapper.style.backgroundColor=styleValue;wrapper.append(range.extractContents());range.insertNode(wrapper);selection.removeAllRanges();const next=document.createRange();next.selectNodeContents(wrapper);selection.addRange(next);savedRange=next.cloneRange();schedule();}
  ['dd-font-family','dd-font-size','dd-text-color','dd-highlight-color'].forEach(id=>document.getElementById(id).addEventListener('mousedown',()=>{const selection=window.getSelection();if(selection&&selection.rangeCount)savedRange=selection.getRangeAt(0).cloneRange();}));
  document.getElementById('dd-font-family').addEventListener('change',e=>applyInlineMark('ddFontFamily',e.target.value));
  document.getElementById('dd-font-size').addEventListener('change',e=>applyInlineMark('ddFontSize',String(Number(e.target.value))));
  document.getElementById('dd-text-color').addEventListener('change',e=>applyInlineMark('ddTextColor',e.target.value.toUpperCase()));
  document.getElementById('dd-highlight-color').addEventListener('change',e=>applyInlineMark('ddHighlight',e.target.value.toUpperCase()));
  function insertTable(){sheet.focus();document.execCommand('insertHTML',false,'<table><tbody><tr><td><br></td><td><br></td></tr><tr><td><br></td><td><br></td></tr></tbody></table><p><br></p>');schedule();}
  document.getElementById('dd-table').addEventListener('click',insertTable);
  document.getElementById('dd-table-toolbar').addEventListener('click',insertTable);
  function insertBreak(){sheet.focus();const p=document.createElement('p');p.dataset.pageBreak='true';p.textContent='Page break';activePage().append(p);schedule();}
  document.getElementById('dd-break').addEventListener('click',insertBreak);
  document.getElementById('dd-break-toolbar').addEventListener('click',insertBreak);
  const lh=document.getElementById('dd-letterhead');
  sheet.dataset.letterheadMode=letterheadMode.value;
  if(lh.checked)sheet.classList.add('dd-letterhead');
  lh.addEventListener('change',()=>{sheet.classList.toggle('dd-letterhead',lh.checked);schedule();});
  letterheadMode.addEventListener('change',()=>{sheet.dataset.letterheadMode=letterheadMode.value;});
  document.getElementById('dd-letterhead-menu').addEventListener('click',()=>{if(lh.disabled){window.location.href='/settings/branding/';return;}lh.checked=!lh.checked;lh.dispatchEvent(new Event('change'));});
  document.getElementById('dd-rename').addEventListener('click',()=>{title.focus();title.select();});
  document.getElementById('dd-select-all').addEventListener('click',()=>{sheet.focus();document.execCommand('selectAll');});
  function clearFormatting(){sheet.focus();document.execCommand('removeFormat');document.execCommand('formatBlock',false,'p');schedule();}
  document.getElementById('dd-clear').addEventListener('click',clearFormatting);document.getElementById('dd-clear-format').addEventListener('click',clearFormatting);
  document.getElementById('dd-zoom').addEventListener('change',e=>{sheet.className='dd-sheet'+(lh.checked?' dd-letterhead':'')+' dd-zoom-'+e.target.value;});
  document.getElementById('dd-link').addEventListener('click',()=>{const url=window.prompt('Enter a web or email link');if(url && /^(https?:\/\/|mailto:)/i.test(url)){sheet.focus();document.execCommand('createLink',false,url);schedule();}});
  document.getElementById('dd-print').addEventListener('click',()=>window.print());
  document.getElementById('dd-line').addEventListener('click',()=>{sheet.focus();const line=document.createElement('hr');activePage().append(line,document.createElement('p'));schedule();});
  document.getElementById('dd-insert-image').addEventListener('click',()=>{
    const picker=document.createElement('input');picker.type='file';picker.accept='image/png,image/jpeg';
    picker.addEventListener('change',async()=>{const file=picker.files&&picker.files[0];if(!file)return;const data=new FormData();data.append('image',file);status.textContent='Uploading image…';
      try{const response=await fetch('/digidoc/images/upload/',{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':getCookie('csrftoken')},body:data});const result=await response.json();if(!response.ok)throw new Error(result.error||'Image upload failed');const img=document.createElement('img');img.dataset.assetId=result.id;img.alt='';img.src=result.url;img.className='dd-inline-image';activePage().append(img,document.createElement('p'));img.addEventListener('load',schedule,{once:true});schedule();}
      catch(err){status.textContent=err.message||'Image upload failed';}
    });picker.click();
  });
  function wordCount(){const words=(sheet.innerText||'').trim().split(/\s+/).filter(Boolean).length;document.getElementById('dd-word-count').textContent=words+' words';}
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
  sheet.addEventListener('paste',e=>{e.preventDefault();const text=(e.clipboardData||window.clipboardData).getData('text/plain');document.execCommand('insertText',false,text);schedule();});
  window.addEventListener('beforeunload',e=>{if(dirty||saving){e.preventDefault();e.returnValue='';}});
})();
