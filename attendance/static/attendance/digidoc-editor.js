(() => {
  'use strict';
  const root = document.getElementById('digidoc');
  if (!root) return;
  const sheet = document.getElementById('dd-sheet');
  if (root.dataset.readOnly === 'true') {
    sheet.contentEditable = 'false';
    root.querySelectorAll('button, input, select, textarea').forEach(control => {
      if (!control.hasAttribute('disabled')) control.disabled = true;
    });
  }
  const status = document.getElementById('dd-status');
  const title = document.getElementById('dd-title');
  const letterheadFirst = document.getElementById('dd-letterhead-first');
  const letterheadOther = document.getElementById('dd-letterhead-other');
  const letterheadSource = document.getElementById('dd-letterhead-source');
  const personalLetterheadSelect = document.getElementById('dd-personal-letterhead');
  const initial = JSON.parse(document.getElementById('dd-initial').textContent);
  const pageSizeMm={A4:[210,297],A5:[148,210],A3:[297,420],Letter:[215.9,279.4],Legal:[215.9,355.6]};
  const marginPresets={Normal:{top_cm:2.5,right_cm:2.5,bottom_cm:2.5,left_cm:2.5},Narrow:{top_cm:1.27,right_cm:1.27,bottom_cm:1.27,left_cm:1.27},Moderate:{top_cm:2.5,right_cm:1.91,bottom_cm:2.5,left_cm:1.91},Wide:{top_cm:2.5,right_cm:5.08,bottom_cm:2.5,left_cm:5.08}};
  const savedLayout=initial.attrs||{};
  const layoutState={page_size:savedLayout.page_size||'A4',orientation:savedLayout.orientation||'portrait',margins:{...marginPresets.Normal,...(savedLayout.margins||{})},header:savedLayout.header||'',footer:savedLayout.footer||'',page_numbers:Boolean(savedLayout.page_numbers)};
  const pageSizeControl=document.getElementById('dd-page-size');
  const orientationControl=document.getElementById('dd-orientation');
  const marginPresetControl=document.getElementById('dd-margin-preset');
  const marginControls={top_cm:document.getElementById('dd-margin-top'),right_cm:document.getElementById('dd-margin-right'),bottom_cm:document.getElementById('dd-margin-bottom'),left_cm:document.getElementById('dd-margin-left')};
  const headerControl=document.getElementById('dd-header-text'),footerControl=document.getElementById('dd-footer-text'),pageNumbersControl=document.getElementById('dd-page-numbers');
  if(headerControl)headerControl.value=layoutState.header;if(footerControl)footerControl.value=layoutState.footer;if(pageNumbersControl)pageNumbersControl.checked=layoutState.page_numbers;
  const letterheadLayoutNote=document.getElementById('dd-letterhead-layout-note');
  const dynamicPageStyle=document.createElement('style');dynamicPageStyle.id='dd-dynamic-page-style';document.head.append(dynamicPageStyle);
  const allowedTags = {P:'paragraph', H1:'heading', H2:'heading', H3:'heading', UL:'bulletList', OL:'orderedList', LI:'listItem', TABLE:'table', TBODY:'table', TR:'tableRow', TD:'tableCell', TH:'tableCell', BR:'hardBreak', HR:'horizontalRule', IMG:'image'};
  function rgbToHex(value){const match=String(value||'').match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);return match?'#'+match.slice(1,4).map(part=>Number(part).toString(16).padStart(2,'0')).join('').toUpperCase():value;}
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
    if(node.type==='table'){
      const attrs=node.attrs||{},width=Math.min(100,Math.max(10,Number(attrs.width_percent)||100));
      el.style.width=width+'%';el.style.tableLayout='fixed';el.dataset.widthPercent=String(width);
      el.dataset.borderColor=attrs.border_color||'#aab1ba';el.dataset.borderWidth=String(Number.isInteger(attrs.border_width)?attrs.border_width:1);
      el.style.borderColor=el.dataset.borderColor;
      const count=Math.max(1,...(node.content||[]).map(row=>(row.content||[]).reduce((sum,cell)=>sum+Number(cell.attrs&&cell.attrs.colspan||1),0)));
      let widths=Array.isArray(attrs.column_widths)&&attrs.column_widths.length===count?attrs.column_widths:null;
      if(!widths){const base=Math.floor(100/count),remainder=100%count;widths=Array.from({length:count},(_,i)=>base+(i<remainder?1:0));}
      const colgroup=document.createElement('colgroup');widths.forEach(value=>{const col=document.createElement('col');col.style.width=value+'%';colgroup.append(col);});el.append(colgroup);
    }
    if(node.type==='tableCell'){
      const attrs=node.attrs||{};if(attrs.colspan>1)el.colSpan=attrs.colspan;if(attrs.rowspan>1)el.rowSpan=attrs.rowspan;
      if(attrs.shading)el.style.backgroundColor=attrs.shading;
      if(parent.closest&&parent.closest('table')){const table=parent.closest('table');el.style.borderColor=table.dataset.borderColor||'#aab1ba';el.style.borderWidth=(table.dataset.borderWidth||1)+'px';}
    }
    if (node.attrs && node.attrs.align) el.dataset.align = node.attrs.align;
    if(node.attrs&&node.attrs.style){el.dataset.docStyle=node.attrs.style;}
    if (node.attrs && node.attrs.indent) el.dataset.indent = node.attrs.indent;
    if (node.attrs && node.attrs.line_spacing) el.dataset.lineSpacing = node.attrs.line_spacing;
    if(node.type==='orderedList'&&node.attrs&&node.attrs.start)el.setAttribute('start',String(node.attrs.start));
    if((node.type==='bulletList'||node.type==='orderedList')&&node.attrs&&node.attrs.list_style){el.dataset.listStyle=node.attrs.list_style;if(node.type==='bulletList')el.style.listStyleType=node.attrs.list_style;else el.setAttribute('type',({'lower-alpha':'a','upper-alpha':'A','lower-roman':'i','upper-roman':'I'})[node.attrs.list_style]||'1');}
    if(node.attrs){
      for(const [key,field,styleName,unit] of [['space_before_pt','spaceBeforePt','marginTop','pt'],['space_after_pt','spaceAfterPt','marginBottom','pt'],['left_indent_cm','indentLeftCm','marginLeft','cm'],['right_indent_cm','indentRightCm','marginRight','cm'],['first_line_indent_cm','indentFirstLineCm','textIndent','cm']]){
        if(Object.prototype.hasOwnProperty.call(node.attrs,key)){el.dataset[field]=String(node.attrs[key]);el.style[styleName]=`${node.attrs[key]}${unit}`;}
      }
    }
    if (node.type === 'bulletList' && node.attrs && node.attrs.list_style === 'checklist') el.dataset.checklist = 'true';
    (node.content || []).forEach(child => renderNode(child, el));
    if (node.type === 'paragraph' && !el.childNodes.length) el.append(document.createElement('br'));
    if (node.type === 'tableCell' && !el.childNodes.length) el.append(document.createElement('br'));
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
    const enabled = document.getElementById('dd-letterhead').checked&&layoutState.page_size==='A4'&&layoutState.orientation==='portrait';
    let firstUrl = root.dataset.companyLetterheadUrl, secondUrl = root.dataset.companyLetterheadSecondUrl;
    if (letterheadSource.value === 'personal') {
      const selected = personalLetterheadSelect.value;
      firstUrl = selected ? `/settings/my-letterhead/${encodeURIComponent(selected)}/image/` : root.dataset.activePersonalLetterheadUrl;
      secondUrl = firstUrl;
    } else if (root.dataset.preserveCompanySnapshot === 'true' && root.dataset.activeCompanyLetterheadUrl) {
      firstUrl = root.dataset.activeCompanyLetterheadUrl;
      secondUrl = firstUrl;
    }
    if (firstUrl) sheet.style.setProperty('--dd-letterhead-image-1', `url('${firstUrl}')`);
    if (secondUrl) sheet.style.setProperty('--dd-letterhead-image-2', `url('${secondUrl}')`);
    sheet.classList.toggle('dd-letterhead', enabled);
    sheet.dataset.letterheadFirst = letterheadFirst.value;
    sheet.dataset.letterheadOther = letterheadOther.value;
    sheet.querySelectorAll(':scope > .dd-page').forEach((page, index) => {
      const slot = index === 0 ? letterheadFirst.value : letterheadOther.value;
      if (enabled && slot !== 'none') page.dataset.letterheadSlot = slot;
      else delete page.dataset.letterheadSlot;
    });
  }
  function pageSupportsLetterhead(layout=layoutState){return layout.page_size==='A4'&&layout.orientation==='portrait';}
  function syncLetterheadAvailability(){
    const available=pageSupportsLetterhead();
    if(letterheadLayoutNote){letterheadLayoutNote.hidden=available;letterheadLayoutNote.textContent=available?'':'Letterheads require A4 portrait. Switch back to A4 portrait to insert one.';}
    const checkbox=document.getElementById('dd-letterhead');
    const companyButton=document.getElementById('dd-letterhead-menu');
    const companyAvailable=companyButton?.dataset.letterheadAvailable==='true';
    if(companyButton){companyButton.disabled=!available||!companyAvailable||root.dataset.readOnly==='true';if(!available)companyButton.title='Letterheads are available on A4 portrait pages only.';}
    ['dd-letterhead-first','dd-letterhead-other','dd-letterhead'].forEach(id=>{const control=document.getElementById(id);if(control)control.disabled=!available||(!companyAvailable&&letterheadSource.value==='company')||root.dataset.readOnly==='true';});
    const personalSelect=document.getElementById('dd-personal-letterhead');
    const personalButton=document.getElementById('dd-use-personal-letterhead');
    const personalAvailable=personalButton?.dataset.letterheadAvailable==='true';
    if(personalSelect)personalSelect.disabled=!available||!personalAvailable||root.dataset.readOnly==='true';
    if(personalButton){personalButton.disabled=!available||!personalAvailable||root.dataset.readOnly==='true';if(!available)personalButton.title='Letterheads are available on A4 portrait pages only.';}
  }
  function applyPageLayout(){
    let [widthMm,heightMm]=pageSizeMm[layoutState.page_size]||pageSizeMm.A4;
    if(layoutState.orientation==='landscape')[widthMm,heightMm]=[heightMm,widthMm];
    const naturalWidth=widthMm*96/25.4,naturalHeight=heightMm*96/25.4;
    const scale=window.innerWidth<=700?Math.min(1,Math.max(.1,(window.innerWidth-20)/naturalWidth)):1;
    let margins={...layoutState.margins};
    if(document.getElementById('dd-letterhead').checked&&pageSupportsLetterhead()){
      const css=getComputedStyle(sheet);
      for(const [field,cssName] of [['top_cm','--dd-letterhead-header-guide'],['bottom_cm','--dd-letterhead-footer-guide'],['left_cm','--dd-letterhead-left-zone'],['right_cm','--dd-letterhead-right-zone']]){
        const guide=parseFloat(css.getPropertyValue(cssName));if(Number.isFinite(guide))margins[field]=Math.max(margins[field],guide/10+(field==='top_cm'||field==='bottom_cm'?.4:0));
      }
    }
    sheet.style.setProperty('--dd-page-width-print',`${widthMm}mm`);sheet.style.setProperty('--dd-page-height-print',`${heightMm}mm`);
    sheet.querySelectorAll(':scope > .dd-page').forEach(page=>{
      page.style.width=`${naturalWidth*scale}px`;page.style.height=`${naturalHeight*scale}px`;
      page.style.padding=`${margins.top_cm*96/2.54*scale}px ${margins.right_cm*96/2.54*scale}px ${margins.bottom_cm*96/2.54*scale}px ${margins.left_cm*96/2.54*scale}px`;
    });
    dynamicPageStyle.textContent=`@page{size:${widthMm}mm ${heightMm}mm;margin:0}@media print{.dd-page{width:${widthMm}mm!important;height:${heightMm}mm!important;padding:${margins.top_cm}cm ${margins.right_cm}cm ${margins.bottom_cm}cm ${margins.left_cm}cm!important}}`;
    syncLetterheadAvailability();syncLetterheadPages();
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
  function pageChrome(node){return node&&node.nodeType===Node.ELEMENT_NODE&&(node.classList.contains('dd-page-header')||node.classList.contains('dd-page-footer'));}
  function syncPageDecorations(){
    const pages=Array.from(sheet.querySelectorAll(':scope > .dd-page')),count=pages.length||1;
    pages.forEach((page,index)=>{
      let header=page.querySelector(':scope > .dd-page-header'),footer=page.querySelector(':scope > .dd-page-footer');
      if(!layoutState.header.trim()&&!layoutState.page_numbers){header?.remove();header=null;}
      else {if(!header){header=document.createElement('div');header.className='dd-page-header';header.contentEditable='false';header.setAttribute('aria-label','Page header');page.append(header);}header.textContent=layoutState.header;header.style.top=Math.max(4,(parseFloat(page.style.paddingTop)||96)-22)+'px';}
      if(!layoutState.footer.trim()&&!layoutState.page_numbers){footer?.remove();footer=null;}
      else {if(!footer){footer=document.createElement('div');footer.className='dd-page-footer';footer.contentEditable='false';footer.setAttribute('aria-label','Page footer');page.append(footer);}footer.textContent=layoutState.footer+(layoutState.page_numbers?(layoutState.footer?' · ':'')+'Page '+(index+1)+' of '+count:'');footer.style.bottom=Math.max(4,(parseFloat(page.style.paddingBottom)||96)-22)+'px';}
    });
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
    if (!block || !['P', 'H1', 'H2', 'H3'].includes(block.tagName) || block.querySelector('.dd-image-frame')) return null;
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
      const nodes = Array.from(page.childNodes).filter(node => !(node.nodeType === Node.ELEMENT_NODE && node.classList.contains('dd-page-zones'))&&!pageChrome(node));
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
        const continuation = splitOversizedTextBlock(node, page, contentBottom);
        if (continuation) {
          let next = pages[pageIndex + 1];
          if (!next) { next = createPage(page); pages.push(next); }
          next.insertBefore(continuation, next.firstChild);
          paginationChanged = true;
          break;
        }
        if (nodeIndex > 0) {
          let next = pages[pageIndex + 1];
          if (!next) { next = createPage(page); pages.push(next); }
          moveBefore(nodes.slice(nodeIndex), next);
          paginationChanged = true;
          break;
        }
      }
    }
    pages = Array.from(sheet.querySelectorAll(':scope > .dd-page'));
    function hasPageContent(page) {
      return Array.from(page.childNodes).some(node => {
        if (node.nodeType === Node.COMMENT_NODE) return false;
        if (node.nodeType === Node.TEXT_NODE) return Boolean(node.textContent.trim());
        if (node.nodeType !== Node.ELEMENT_NODE || node.classList.contains('dd-page-zones')||pageChrome(node)) return false;
        if (node.dataset.pageBreak === 'true') return false;
        if (node.matches('p,h1,h2,h3,li,td,th')) {
          return Boolean(node.textContent.trim() || node.querySelector('img,.dd-image-frame,table,hr'));
        }
        return Boolean(node.textContent.trim() || node.querySelector('img,.dd-image-frame,table,hr'));
      });
    }
    function endsWithExplicitPageBreak(page) {
      const contentNodes = Array.from(page.childNodes).filter(node =>
        !(node.nodeType === Node.ELEMENT_NODE && node.classList.contains('dd-page-zones'))&&!pageChrome(node)
      );
      return contentNodes[contentNodes.length - 1]?.nodeType === Node.ELEMENT_NODE
        && contentNodes[contentNodes.length - 1].dataset.pageBreak === 'true';
    }
    while (pages.length > 1 && !hasPageContent(pages[pages.length - 1]) && !endsWithExplicitPageBreak(pages[pages.length - 2])) {
      pages.pop().remove(); paginationChanged = true;
    }
    pages.forEach((page, index) => { page.dataset.pageNumber = String(index + 1); });
    syncPageDecorations();
    if (paginationChanged && activeSelection && activeSelection.anchor !== null && activeSelection.focus !== null && selection.setBaseAndExtent) {
      const anchor = historyPointAt(activeSelection.anchor);
      const focus = historyPointAt(activeSelection.focus);
      if (anchor && focus) selection.setBaseAndExtent(anchor.node, anchor.offset, focus.node, focus.offset);
    }
    syncLetterheadPages();
  }
  applyPageLayout();
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
      else if (el.tagName === 'SUP') marks.push({type:'superscript'});
      else if (el.tagName === 'SUB') marks.push({type:'subscript'});
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
    if (pageChrome(el)) return [];
    const tag=el.tagName; let type=allowedTags[tag];
    if (!type) return Array.from(el.childNodes).flatMap(serializeBlock);
    if (type === 'hardBreak') return el.dataset.pageBreak === 'true' ? [{type}] : [];
    if (type === 'horizontalRule') return [{type}];
    if (tag === 'IMG') { const frame=el.closest('.dd-image-frame');return [{type:'image',attrs:{asset_id:el.dataset.assetId||'',alt:(el.alt||'').slice(0,300),width_percent:Math.min(100,Math.max(10,Number(frame&&frame.dataset.widthPercent)||100)),align:frame&&frame.dataset.imageAlign||'center',crop:frame&&frame.dataset.crop||'none'}}]; }
    if (tag === 'P' && el.dataset.pageBreak === 'true') return [{type:'hardBreak'}];
    if (tag === 'TABLE') {
      let columns=Array.from(el.querySelectorAll(':scope > colgroup > col'));
      let widths=columns.map(col=>Math.round(parseFloat(col.style.width)||0));
      if(!widths.length){const count=Math.max(1,...Array.from(el.rows,row=>Array.from(row.cells).reduce((sum,cell)=>sum+(cell.colSpan||1),0)));const base=Math.floor(100/count),remainder=100%count;widths=Array.from({length:count},(_,index)=>base+(index<remainder?1:0));}
      if(widths.length&&widths.reduce((a,b)=>a+b,0)!==100)widths[widths.length-1]+=100-widths.reduce((a,b)=>a+b,0);
      return [{type:'table',attrs:{width_percent:Math.min(100,Math.max(10,Number(el.dataset.widthPercent)||100)),column_widths:widths,border_color:el.dataset.borderColor||'#aab1ba',border_width:Math.min(8,Math.max(0,Number(el.dataset.borderWidth)||0))},content:Array.from(el.rows).map(row=>({type:'tableRow',content:Array.from(row.cells).map(cell=>({type:'tableCell',...(cell.colSpan>1||cell.rowSpan>1||cell.style.backgroundColor?{attrs:{...(cell.colSpan>1?{colspan:cell.colSpan}:{}),...(cell.rowSpan>1?{rowspan:cell.rowSpan}:{}),...(cell.style.backgroundColor?{shading:rgbToHex(cell.style.backgroundColor)}:{})}}:{}),content:Array.from(cell.childNodes).flatMap(serializeInline)}))}))}];
    }
    if (type === 'heading') {const attrs={};if(el.dataset.docStyle==='title')attrs.style='title';if(el.dataset.align)attrs.align=el.dataset.align;for(const [field,key] of [['spaceBeforePt','space_before_pt'],['spaceAfterPt','space_after_pt']]){const value=Number(el.dataset[field]);if(Number.isInteger(value)&&value>=0&&value<=200)attrs[key]=value;}for(const [field,key,low] of [['indentLeftCm','left_indent_cm',0],['indentRightCm','right_indent_cm',0],['indentFirstLineCm','first_line_indent_cm',-2.54]]){const value=Number(el.dataset[field]);if(Number.isFinite(value)&&value>=low&&value<=10)attrs[key]=Math.round(value*100)/100;}return [{type,level:Number(tag.slice(1)),...(Object.keys(attrs).length?{attrs}:{}),content:Array.from(el.childNodes).flatMap(serializeInline),...(el.dataset.autoContinuation === 'true' ? {_autoContinuation:true} : {})}];}
    if (type === 'bulletList' || type === 'orderedList') {
      const attrs = el.dataset.listStyle ? {list_style:el.dataset.listStyle} : type === 'bulletList' && el.dataset.checklist === 'true' ? {list_style:'checklist'} : {};
      if(type==='orderedList'&&el.hasAttribute('start')){const start=Number(el.getAttribute('start'));if(Number.isInteger(start)&&start>=1&&start<=9999)attrs.start=start;}
      return [{type,...(Object.keys(attrs).length ? {attrs} : {}),content:Array.from(el.children).flatMap(serializeBlock)}];
    }
    if(type==='paragraph'&&Array.from(el.children).some(child=>child.matches('ul,ol,table,hr'))){
      return Array.from(el.childNodes).flatMap(child=>{
        if(child.nodeType===Node.ELEMENT_NODE&&child.matches('ul,ol,table,hr'))return serializeBlock(child);
        const inline=serializeInline(child);return inline.length?[{type:'paragraph',content:inline}]:[];
      });
    }
    if (type === 'paragraph' || type === 'tableCell') {
      const content=Array.from(el.childNodes).flatMap(serializeInline);
      const attrs={}; const align=el.dataset.align || (el.style.textAlign || '');
      if (['left','right','center','justify'].includes(align)) attrs.align=align;
      const indent = Number(el.dataset.indent || 0);
      if (Number.isInteger(indent) && indent > 0 && indent <= 4) attrs.indent=indent;
      if (['single','1.15','1.5','double'].includes(el.dataset.lineSpacing)) attrs.line_spacing=el.dataset.lineSpacing;
      if(el.dataset.docStyle==='subtitle')attrs.style='subtitle';
      for(const [field,key] of [['spaceBeforePt','space_before_pt'],['spaceAfterPt','space_after_pt']]){const value=Number(el.dataset[field]);if(Number.isInteger(value)&&value>=0&&value<=200)attrs[key]=value;}
      for(const [field,key,low] of [['indentLeftCm','left_indent_cm',0],['indentRightCm','right_indent_cm',0],['indentFirstLineCm','first_line_indent_cm',-2.54]]){const value=Number(el.dataset[field]);if(Number.isFinite(value)&&value>=low&&value<=10)attrs[key]=Math.round(value*100)/100;}
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
    return {title:title.value,content:{type:'doc',attrs:{page_size:layoutState.page_size,orientation:layoutState.orientation,margins:{...layoutState.margins},header:layoutState.header,footer:layoutState.footer,page_numbers:layoutState.page_numbers},content:joined.length?joined:[{type:'paragraph',content:[]}]},letterhead_enabled:document.getElementById('dd-letterhead').checked,letterhead_page_mode:letterheadOther.value==='none'?'first':'every',letterhead_first_slot:letterheadFirst.value,letterhead_other_slot:letterheadOther.value,letterhead_source:letterheadSource.value,personal_letterhead_id:personalLetterheadSelect.value||null,version:Number(root.dataset.version)};
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
    letterheadSource.value=state.letterhead_source||'company';personalLetterheadSelect.value=state.personal_letterhead_id||'';
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
  [headerControl,footerControl].filter(Boolean).forEach((control,index)=>control.addEventListener('input',()=>{layoutState[index?'footer':'header']=control.value.slice(0,1000);syncPageDecorations();scheduleFormatting();}));
  if(pageNumbersControl)pageNumbersControl.addEventListener('change',()=>{layoutState.page_numbers=pageNumbersControl.checked;syncPageDecorations();scheduleFormatting();});
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
    if(key==='/'){event.preventDefault();document.getElementById('dd-shortcut-dialog').showModal();return;}
    if(key==='f'){event.preventDefault();openFind(false);return;}
    if(key==='h'){event.preventDefault();openFind(true);return;}
    if(!editorActive)return;
    if(key==='z'){
      if(!event.shiftKey&&typeof corrections!=='undefined'&&corrections.length&&editorSelection){event.preventDefault();restoreCorrection(corrections.pop());schedule();return;}
      event.preventDefault();event.shiftKey?redo():undo();
    }
    else if(key==='y'){event.preventDefault();redo();}
    else if(key==='s'){event.preventDefault();root.dispatchEvent(new Event('digidoc:save'));}
    else if(key==='k'){event.preventDefault();document.getElementById('dd-link').click();}
    else if(key==='enter'){event.preventDefault();document.getElementById('dd-break').click();}
    else if(key==='v'&&event.shiftKey){event.preventDefault();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();navigator.clipboard.readText().then(insertTextAtSaved).catch(()=>{status.textContent='Clipboard access was blocked.';});}
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
  function schedule() { paginate(); if(!historyRestoring){const current=historySnapshot();if(historyCurrent!==null&&current!==historyCurrent){undoHistory.push(historyCurrent);if(undoHistory.length>historyLimit)undoHistory.shift();redoHistory.length=0;historyCurrent=current;updateHistoryButtons();}} markDirty(); }
  function markDirty(){dirty=true;status.textContent='Unsaved changes';clearTimeout(timer);timer=setTimeout(save,800);}
  // Inline marks do not change page geometry. Defer pagination and history snapshots
  // until the next structural edit or history action, while keeping autosave debounced.
  function scheduleFormatting(){markDirty();}
  const writingSettings=JSON.parse(document.getElementById('dd-writing-settings').textContent);
  const corrections=[];
  const correctionMap=new Map((writingSettings.rules||[]).map(rule=>[String(rule.from).toLocaleLowerCase(),String(rule.to)]));
  const skipCapitalization=/^(?:Mr|Mrs|Ms|Dr|Prof|St|Jr|Sr|vs|etc|e\.g|i\.e|No|Fig|Inc|Ltd|Co|U\.S|U\.K)\.$/i;
  sheet.spellcheck=!!writingSettings.spellcheck_enabled;
  document.documentElement.lang=writingSettings.language||'en-GB';
  function restoreCorrection(entry){
    if(!entry||!entry.node.isConnected)return false;
    const selection=window.getSelection();if(!selection)return false;
    entry.node.replaceData(entry.start,entry.end-entry.start,entry.before);
    const caret=document.createRange();caret.setStart(entry.node,entry.start+entry.before.length);caret.collapse(true);selection.removeAllRanges();selection.addRange(caret);return true;
  }
  function applyTypingCorrection(event){
    if(event.isComposing||event.inputType==='insertCompositionText')return;
    const selection=window.getSelection();if(!selection||!selection.isCollapsed)return;
    const node=selection.anchorNode,offset=selection.anchorOffset;
    if(!node||node.nodeType!==Node.TEXT_NODE||!sheet.contains(node))return;
    const block=node.parentElement&&node.parentElement.closest('p,h1,h2,h3,li,td,th');
    if(!block||block.closest('pre,code,a'))return;
    let before=node.nodeValue.slice(0,offset),trigger=event.data||'';
    const token=before.match(/[^\s]*$/u)?.[0]||'';
    if(/^(?:https?:\/\/|www\.|[^\s@]+@|[\p{L}\p{N}_-]+\.[a-z]{2,}(?:[\/?#:]|$))/iu.test(token))return;
    const record=(start,end,original)=>corrections.push({node,start,end,before:original});
    if(writingSettings.autocorrect_enabled&&/[\s.,!?;:]$/.test(before)){
      const phrase=before.match(/(\(c\)|1\/2|--|[\p{L}'\u2019-]+)(?=[\s.,!?;:]$)/iu);
      if(phrase){
        const original=phrase[1],replacement=correctionMap.get(original.toLocaleLowerCase())||({'(c)':'\u00a9','1/2':'\u00bd','--':'\u2014'}[original.toLocaleLowerCase()]);
        if(replacement){const start=phrase.index;node.replaceData(start,original.length,replacement);const caret=start+replacement.length+1;const range=document.createRange();range.setStart(node,caret);range.collapse(true);selection.removeAllRanges();selection.addRange(range);record(start,start+replacement.length,original);before=node.nodeValue.slice(0,caret);}
      }
      let pos=selection.anchorOffset,text=node.nodeValue;
      if(text.slice(Math.max(0,pos-2),pos)==='  '){node.replaceData(pos-1,1,'');pos-=1;const range=document.createRange();range.setStart(node,pos);range.collapse(true);selection.removeAllRanges();selection.addRange(range);record(pos,pos+1,' ');}
      if(trigger==='"'||trigger==="'"){
        pos=selection.anchorOffset;text=node.nodeValue;const opening=pos<=1||/[\s([{]$/.test(text.slice(0,pos-1));const curly=trigger==='"'?(opening?'\u201c':'\u201d'):(opening?'\u2018':'\u2019');
        node.replaceData(pos-1,1,curly);record(pos-1,pos,trigger);
      }
    }
    if(writingSettings.autocapitalize_enabled){
      const caret=selection.anchorOffset,updated=node.nodeValue,letter=updated.slice(0,caret).match(/([\p{L}])$/u);
      if(letter){const wordStart=caret-1,prefix=updated.slice(0,wordStart),firstLetter=!prefix.trim()||/[.!?]\s+$/.test(prefix),prior=prefix.match(/(\S+\.)\s+$/),skip=prior&&skipCapitalization.test(prior[1]);
        if(firstLetter&&!skip&&letter[1]===letter[1].toLocaleLowerCase()){node.replaceData(wordStart,1,letter[1].toLocaleUpperCase());record(wordStart,wordStart+1,letter[1]);}
      }
    }
  }
  sheet.addEventListener('input',event=>{applyTypingCorrection(event);schedule();});
  sheet.addEventListener('keydown',event=>{
    if(event.key==='Backspace'&&corrections.length){const last=corrections[corrections.length-1],sel=window.getSelection();if(sel&&sel.isCollapsed&&sel.anchorNode===last.node&&(sel.anchorOffset===last.end||sel.anchorOffset===last.end+1&&/\s/.test(last.node.nodeValue[last.end]||''))){event.preventDefault();if(sel.anchorOffset===last.end+1)last.node.deleteData(last.end,1);corrections.pop();restoreCorrection(last);schedule();return;}}
  },true);
  document.getElementById('dd-autocapitalize').addEventListener('change',e=>{writingSettings.autocapitalize_enabled=e.target.checked;});
  document.getElementById('dd-autocorrect').addEventListener('change',e=>{writingSettings.autocorrect_enabled=e.target.checked;});
  document.getElementById('dd-language').addEventListener('change',e=>{writingSettings.language=e.target.value;document.documentElement.lang=e.target.value;sheet.spellcheck=!!writingSettings.spellcheck_enabled;});
  document.getElementById('dd-formatting-marks').addEventListener('change',e=>document.documentElement.classList.toggle('dd-show-formatting-marks',e.target.checked));
  const shortcutDialog=document.getElementById('dd-shortcut-dialog');
  document.getElementById('dd-shortcut-help').addEventListener('click',()=>shortcutDialog.showModal());
  document.getElementById('dd-shortcut-close').addEventListener('click',()=>shortcutDialog.close());
  let findCursor=null;
  const findDialog=document.getElementById('dd-find-dialog'),findQuery=document.getElementById('dd-find-query'),replaceQuery=document.getElementById('dd-replace-query'),matchCase=document.getElementById('dd-match-case'),findResult=document.getElementById('dd-find-result');
  function openFind(replace){document.getElementById('dd-replace-label').hidden=!replace;findDialog.showModal();findQuery.focus();findQuery.select();}
  function textNodes(){const walker=document.createTreeWalker(sheet,NodeFilter.SHOW_TEXT);const nodes=[];while(walker.nextNode()){const node=walker.currentNode;if(node.parentElement.closest('.dd-page-zones,[contenteditable="false"]'))continue;nodes.push(node);}return nodes;}
  function findNext(){
    const query=findQuery.value;if(!query){findResult.textContent='Enter text to find.';return null;}
    const nodes=textNodes(),needle=matchCase.checked?query:query.toLocaleLowerCase();let startIndex=0,startOffset=0;
    const selection=window.getSelection(),anchor=selection&&selection.anchorNode;
    if(anchor&&nodes.includes(anchor)){startIndex=nodes.indexOf(anchor);startOffset=selection.anchorOffset;}
    else if(findCursor&&nodes.includes(findCursor.node)){startIndex=nodes.indexOf(findCursor.node);startOffset=findCursor.offset;}
    for(let step=0;step<nodes.length;step++){
      const index=(startIndex+step)%nodes.length,node=nodes[index],text=node.nodeValue||'',haystack=matchCase.checked?text:text.toLocaleLowerCase(),from=step===0?startOffset:0,at=haystack.indexOf(needle,from);
      if(at>=0){const range=document.createRange();range.setStart(node,at);range.setEnd(node,at+query.length);selection.removeAllRanges();selection.addRange(range);savedRange=range.cloneRange();findCursor={node,offset:at+query.length};node.parentElement.scrollIntoView({block:'nearest'});findResult.textContent='Match found.';return range;}
    }
    findResult.textContent='No more matches.';findCursor=null;return null;
  }
  document.getElementById('dd-find').addEventListener('click',()=>openFind(false));
  document.getElementById('dd-replace').addEventListener('click',()=>openFind(true));
  document.getElementById('dd-find-next').addEventListener('click',findNext);
  document.getElementById('dd-find-query').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();findNext();}});
  document.getElementById('dd-replace-one').addEventListener('click',()=>{const selection=window.getSelection();if(!selection||selection.isCollapsed||!findQuery.value)return;const found=selection.toString(),query=findQuery.value;if((matchCase.checked?found===query:found.toLocaleLowerCase()===query.toLocaleLowerCase())){document.execCommand('insertText',false,replaceQuery.value);schedule();}findNext();});
  document.getElementById('dd-replace-all').addEventListener('click',()=>{const query=findQuery.value;if(!query)return;const nodes=textNodes();let count=0;for(const node of nodes){const source=node.nodeValue||'',haystack=matchCase.checked?source:source.toLocaleLowerCase(),needle=matchCase.checked?query:query.toLocaleLowerCase();let at=0,output='',next,local=0;while((next=haystack.indexOf(needle,at))>=0){output+=source.slice(at,next)+replaceQuery.value;at=next+query.length;local++;}if(local){output+=source.slice(at);node.nodeValue=output;count+=local;}}findResult.textContent=count+' replacement'+(count===1?'':'s')+' made.';if(count){schedule();wordCount();}});
  document.getElementById('dd-find-close').addEventListener('click',()=>findDialog.close());
  function insertTextAtSaved(value){sheet.focus();const selection=window.getSelection();if(savedRange&&selection){selection.removeAllRanges();selection.addRange(savedRange);}const range=selection&&selection.rangeCount?selection.getRangeAt(0):null;if(!range||!sheet.contains(range.commonAncestorContainer))return;range.deleteContents();const text=document.createTextNode(value);range.insertNode(text);range.setStartAfter(text);range.collapse(true);selection.removeAllRanges();selection.addRange(range);savedRange=range.cloneRange();schedule();}
  const specialPanel=document.getElementById('dd-special-panel'),specialButton=document.getElementById('dd-special-characters');
  for(const character of ['©','®','™','€','£','¥','§','¶','•','–','—','…','“','”','‘','’','°','±','×','÷','←','→','↑','↓','✓','★']){const button=document.createElement('button');button.type='button';button.textContent=character;button.setAttribute('aria-label','Insert '+character);button.addEventListener('mousedown',event=>event.preventDefault());button.addEventListener('click',()=>{insertTextAtSaved(character);specialPanel.hidden=true;});specialPanel.append(button);}
  specialButton.addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount)savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();});
  specialButton.addEventListener('click',()=>{specialPanel.hidden=!specialPanel.hidden;});
  document.getElementById('dd-insert-date').addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount)savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();});
  document.getElementById('dd-insert-date').addEventListener('click',()=>insertTextAtSaved(new Intl.DateTimeFormat(document.documentElement.lang||'en-GB',{dateStyle:'long'}).format(new Date())));
  document.getElementById('dd-paste').addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();});
  document.getElementById('dd-paste').addEventListener('click',async()=>{try{insertTextAtSaved(await navigator.clipboard.readText());}catch(_){status.textContent='Clipboard access was blocked. Use Ctrl+V inside the document.';}});
  sheet.addEventListener('input',schedule); title.addEventListener('input',schedule);
  ['dd-letterhead','dd-letterhead-first','dd-letterhead-other'].forEach(id=>document.getElementById(id).addEventListener('change',()=>{syncLetterheadPages();schedule();}));
  function restoreSavedSelection(){const selection=window.getSelection();if(savedRange&&selection&&sheet.contains(savedRange.commonAncestorContainer)){selection.removeAllRanges();selection.addRange(savedRange);return selection;}return selection;}
  document.querySelectorAll('[data-command]').forEach(button=>{button.addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();});button.addEventListener('click',()=>{sheet.focus();restoreSavedSelection();document.execCommand(button.dataset.command,false,null);scheduleFormatting();});});
  function runBlock(value){sheet.focus();const style=value.toLowerCase();const mapped=style==='title'?'h1':style==='subtitle'?'p':style.startsWith('heading')?'h'+style.slice(-1):value;document.execCommand('formatBlock',false,mapped);const block=currentBlock();if(block){if(style==='title')block.dataset.docStyle='title';else if(style==='subtitle')block.dataset.docStyle='subtitle';else delete block.dataset.docStyle;}schedule();}
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
  function syncPageLayoutControls(){
    pageSizeControl.value=layoutState.page_size;orientationControl.value=layoutState.orientation;
    Object.entries(marginControls).forEach(([field,control])=>control.value=String(layoutState.margins[field]));
    const preset=Object.keys(marginPresets).find(name=>Object.keys(marginPresets[name]).every(key=>marginPresets[name][key]===layoutState.margins[key]));
    marginPresetControl.value=preset||'Custom';
  }
  syncPageLayoutControls();
  function changePageLayout(){
    const next={page_size:pageSizeControl.value,orientation:orientationControl.value,margins:{...layoutState.margins}};
    if(!pageSizeMm[next.page_size]||!['portrait','landscape'].includes(next.orientation)){syncPageLayoutControls();return;}
    const letterheadEnabled=document.getElementById('dd-letterhead').checked;
    if(letterheadEnabled&&!pageSupportsLetterhead(next)){
      const remove=window.confirm('Letterheads work on A4 portrait pages only. Remove the letterhead and apply this page size or orientation?');
      if(!remove){syncPageLayoutControls();return;}
      document.getElementById('dd-letterhead').checked=false;
    }
    layoutState.page_size=next.page_size;layoutState.orientation=next.orientation;
    applyPageLayout();schedule();
  }
  pageSizeControl.addEventListener('change',changePageLayout);orientationControl.addEventListener('change',changePageLayout);
  marginPresetControl.addEventListener('change',()=>{
    const preset=marginPresetControl.value;
    if(marginPresets[preset]){layoutState.margins={...marginPresets[preset]};syncPageLayoutControls();applyPageLayout();schedule();}
  });
  Object.entries(marginControls).forEach(([field,control])=>control.addEventListener('change',()=>{
    if(!control.checkValidity()){control.reportValidity();return;}
    const value=Number(control.value);if(!Number.isFinite(value)||value<.5||value>5.5){control.reportValidity();return;}
    layoutState.margins[field]=Math.round(value*100)/100;marginPresetControl.value='Custom';applyPageLayout();schedule();
  }));
  window.addEventListener('resize',applyPageLayout);
  const paragraphLayoutFields={
    'dd-space-before':['spaceBeforePt','space_before_pt',0,200,'pt','marginTop'],
    'dd-space-after':['spaceAfterPt','space_after_pt',0,200,'pt','marginBottom'],
    'dd-indent-left-cm':['indentLeftCm','left_indent_cm',0,10,'cm','marginLeft'],
    'dd-indent-right-cm':['indentRightCm','right_indent_cm',0,10,'cm','marginRight'],
    'dd-indent-first-line-cm':['indentFirstLineCm','first_line_indent_cm',-2.54,10,'cm','textIndent'],
  };
  function setParagraphAttr(name,value){
    const selection=window.getSelection();
    if(savedRange&&selection){selection.removeAllRanges();selection.addRange(savedRange);sheet.focus();}
    else sheet.focus();
    const blocks=selectedBlocks();if(!blocks.length)return;
    blocks.forEach(block=>{
      if(value===null||value===0){delete block.dataset[name];if(paragraphStyleNames[name])block.style[paragraphStyleNames[name]]='';}
      else {block.dataset[name]=String(value);if(paragraphStyleNames[name])block.style[paragraphStyleNames[name]]=`${value}${paragraphStyleUnits[name]}`;}
    });schedule();
  }
  const paragraphStyleNames={spaceBeforePt:'marginTop',spaceAfterPt:'marginBottom',indentLeftCm:'marginLeft',indentRightCm:'marginRight',indentFirstLineCm:'textIndent'};
  const paragraphStyleUnits={spaceBeforePt:'pt',spaceAfterPt:'pt',indentLeftCm:'cm',indentRightCm:'cm',indentFirstLineCm:'cm'};
  function syncParagraphLayoutControls(){
    const block=selectedBlocks()[0];if(!block)return;
    for(const [id,[key]] of Object.entries(paragraphLayoutFields)){const control=document.getElementById(id);control.value=block.dataset[key]||'0';}
  }
  Object.entries(paragraphLayoutFields).forEach(([id,[key,_attr,min,max]])=>{
    const control=document.getElementById(id);
    control.addEventListener('mousedown',()=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();});
    control.addEventListener('change',()=>{
      if(!control.checkValidity()){control.reportValidity();return;}
      const value=Number(control.value);if(!Number.isFinite(value)||value<min||value>max){control.reportValidity();return;}
      setParagraphAttr(key,value);
    });
  });
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
    const selection=restoreSavedSelection();let node=selection&&selection.anchorNode;if(node&&node.nodeType===Node.TEXT_NODE)node=node.parentElement;
    const list=node&&node.closest('ul');
    if(list&&sheet.contains(list)){if(list.dataset.checklist==='true')delete list.dataset.checklist;else list.dataset.checklist='true';schedule();return;}
    document.execCommand('insertUnorderedList',false,null);
    const next=window.getSelection();let current=next&&next.anchorNode;if(current&&current.nodeType===Node.TEXT_NODE)current=current.parentElement;
    const created=current&&current.closest('ul');if(created&&sheet.contains(created))created.dataset.checklist='true';schedule();
  });
  document.getElementById('dd-list-style').addEventListener('change',event=>{
    const style=event.target.value;sheet.focus();let selection=restoreSavedSelection(),node=selection&&selection.anchorNode;if(node&&node.nodeType===Node.TEXT_NODE)node=node.parentElement;
    let list=node&&node.closest('ul,ol');
    if(!list||!sheet.contains(list)){document.execCommand(style==='checklist'||['disc','circle','square'].includes(style)?'insertUnorderedList':'insertOrderedList',false,null);selection=window.getSelection();node=selection&&selection.anchorNode;if(node&&node.nodeType===Node.TEXT_NODE)node=node.parentElement;list=node&&node.closest('ul,ol');}
    if(list&&sheet.contains(list)){list.dataset.listStyle=style;if(list.tagName==='UL'){list.dataset.checklist=String(style==='checklist');list.style.listStyleType=style==='checklist'?'none':style;}else{delete list.dataset.checklist;list.setAttribute('type',({'lower-alpha':'a','upper-alpha':'A','lower-roman':'i','upper-roman':'I'})[style]||'1');}schedule();}
  });
  document.getElementById('dd-restart-numbering').addEventListener('click',()=>{let node=window.getSelection()?.anchorNode;if(node&&node.nodeType===Node.TEXT_NODE)node=node.parentElement;const list=node&&node.closest('ol');if(list&&sheet.contains(list)){const start=Number(window.prompt('Restart numbering at',list.getAttribute('start')||'1'));if(Number.isInteger(start)&&start>=1&&start<=9999){list.setAttribute('start',String(start));schedule();}}});
  document.querySelectorAll('[data-mark-command]').forEach(button=>{button.addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();});button.addEventListener('click',()=>{sheet.focus();restoreSavedSelection();document.execCommand(button.dataset.markCommand,false,null);scheduleFormatting();});});
  document.getElementById('dd-indent-in-menu').addEventListener('click',()=>document.getElementById('dd-indent-in').click());
  document.getElementById('dd-indent-out-menu').addEventListener('click',()=>document.getElementById('dd-indent-out').click());
  document.getElementById('dd-line-spacing-menu').addEventListener('change',e=>{document.getElementById('dd-line-spacing').value=e.target.value;setParagraphAttr('lineSpacing',e.target.value);});
  let savedRange=null;
  document.addEventListener('selectionchange',()=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode)){savedRange=selection.getRangeAt(0).cloneRange();syncParagraphLayoutControls();}});
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
  const fontSelect=document.getElementById('dd-font-family'),fontSearch=document.getElementById('dd-font-search');
  const recentFontGroup=document.createElement('optgroup');recentFontGroup.label='Recently used';recentFontGroup.dataset.recent='true';fontSelect.insertBefore(recentFontGroup,fontSelect.firstChild);
  const fontOptions=()=>Array.from(fontSelect.querySelectorAll('option')).filter(option=>option.value&&option.parentElement!==recentFontGroup);
  function loadRecentFonts(){let recent=[];try{recent=JSON.parse(localStorage.getItem('digidoc.recentFonts')||'[]');}catch(_){}recent.filter(name=>fontOptions().some(option=>option.value===name)).slice(0,5).forEach(name=>recentFontGroup.append(new Option(name,name)));recentFontGroup.hidden=!recentFontGroup.children.length;}
  function rememberFont(name){let recent=[];try{recent=JSON.parse(localStorage.getItem('digidoc.recentFonts')||'[]');}catch(_){}recent=[name,...recent.filter(item=>item!==name)].slice(0,5);try{localStorage.setItem('digidoc.recentFonts',JSON.stringify(recent));}catch(_){}recentFontGroup.replaceChildren(...recent.map(item=>new Option(item,item)));recentFontGroup.hidden=false;}
  function previewFont(){const name=fontSelect.value;const aliases={'Helvetica':'Arial,sans-serif','Times-Roman':'"Times New Roman",serif','Courier':'"Courier New",monospace'};fontSelect.style.fontFamily=aliases[name]||'"'+name+'",sans-serif';}
  fontSearch.addEventListener('input',()=>{const query=fontSearch.value.trim().toLocaleLowerCase();for(const option of fontOptions())option.hidden=!!query&&!option.textContent.toLocaleLowerCase().includes(query);for(const group of fontSelect.querySelectorAll('optgroup')){if(group===recentFontGroup){for(const option of group.children)option.hidden=!!query&&!option.textContent.toLocaleLowerCase().includes(query);}group.hidden=Array.from(group.children).every(option=>option.hidden);}});
  loadRecentFonts();previewFont();fontSelect.addEventListener('change',()=>{previewFont();rememberFont(fontSelect.value);applyInlineMark('ddFontFamily',fontSelect.value);});
  document.getElementById('dd-font-size').addEventListener('change',e=>{const value=Number(e.target.value);if(!Number.isInteger(value)||value<8||value>96){e.target.value='10';return;}applyInlineMark('ddFontSize',String(value));});
  function stepFontSize(direction){const control=document.getElementById('dd-font-size');const next=Math.max(8,Math.min(96,(Number(control.value)||10)+direction));control.value=String(next);applyInlineMark('ddFontSize',String(next));}
  document.getElementById('dd-grow-font').addEventListener('mousedown',e=>e.preventDefault());document.getElementById('dd-shrink-font').addEventListener('mousedown',e=>e.preventDefault());
  document.getElementById('dd-grow-font').addEventListener('click',()=>stepFontSize(1));document.getElementById('dd-shrink-font').addEventListener('click',()=>stepFontSize(-1));
  document.getElementById('dd-text-color').addEventListener('change',e=>applyInlineMark('ddTextColor',e.target.value.toUpperCase()));
  document.getElementById('dd-highlight-color').addEventListener('change',e=>applyInlineMark('ddHighlight',e.target.value.toUpperCase()));
  const tableGrid=document.getElementById('dd-table-grid'),tableButton=document.getElementById('dd-table'),tableToolbar=document.getElementById('dd-table-toolbar');
  let activeTableCell=null;
  for(let row=1;row<=10;row++)for(let col=1;col<=10;col++){const option=document.createElement('button');option.type='button';option.className='dd-table-grid-cell';option.dataset.rows=String(row);option.dataset.columns=String(col);option.setAttribute('aria-label',row+' rows by '+col+' columns');option.title=row+' × '+col;tableGrid.append(option);}
  function insertTable(rows,columns){
    sheet.focus();const table=document.createElement('table');table.style.width='100%';table.style.tableLayout='fixed';table.dataset.widthPercent='100';table.dataset.borderColor='#aab1ba';table.dataset.borderWidth='1';
    const colgroup=document.createElement('colgroup');for(let col=0;col<columns;col++){const el=document.createElement('col');el.style.width=(100/columns)+'%';colgroup.append(el);}table.append(colgroup);
    const body=document.createElement('tbody');for(let row=0;row<rows;row++){const tr=document.createElement('tr');for(let col=0;col<columns;col++){const td=document.createElement('td');td.append(document.createElement('br'));tr.append(td);}body.append(tr);}table.append(body);
    const selection=window.getSelection(),range=savedRange||(selection&&selection.rangeCount?selection.getRangeAt(0).cloneRange():null);
    if(range&&sheet.contains(range.startContainer)){range.deleteContents();const element=range.startContainer.nodeType===Node.ELEMENT_NODE?range.startContainer:range.startContainer.parentElement,block=element.closest('p,h1,h2,h3'),listItem=element.closest('li');if(block){block.after(table);}else if(listItem){listItem.append(table);}else range.insertNode(table);}else sheet.append(table);
    const after=document.createElement('p');after.append(document.createElement('br'));table.after(after);
    tableGrid.hidden=true;tableButton.setAttribute('aria-expanded','false');schedule();
    const firstCell=table.querySelector('td,th');
    if(firstCell){
      sheet.focus();
      const caret=document.createRange();caret.selectNodeContents(firstCell);caret.collapse(true);
      selection.removeAllRanges();selection.addRange(caret);savedRange=caret.cloneRange();
      syncTableToolbar(firstCell);
      if(typeof historySnapshot==='function')historyCurrent=historySnapshot();
    }
  }
  function positionTableGrid(){const rect=tableButton.getBoundingClientRect(),width=tableGrid.offsetWidth||225;tableGrid.style.top=`${rect.bottom+6}px`;tableGrid.style.left=`${Math.max(8,Math.min(rect.left,window.innerWidth-width-8))}px`;}
  function closeTableGrid(){tableGrid.hidden=true;tableButton.setAttribute('aria-expanded','false');}
  tableButton.addEventListener('click',event=>{event.stopPropagation();const open=tableGrid.hidden;if(open){tableGrid.hidden=false;positionTableGrid();}else tableGrid.hidden=true;tableButton.setAttribute('aria-expanded',String(open));});
  document.addEventListener('click',event=>{if(tableGrid.hidden||tableGrid.contains(event.target)||tableButton.contains(event.target))return;closeTableGrid();});
  window.addEventListener('resize',()=>{if(!tableGrid.hidden)positionTableGrid();});
  document.addEventListener('scroll',()=>{if(!tableGrid.hidden)positionTableGrid();},true);
  tableGrid.addEventListener('click',event=>{const option=event.target.closest('[data-rows]');if(option)insertTable(Number(option.dataset.rows),Number(option.dataset.columns));});
  function syncTableToolbar(cell){activeTableCell=cell;const table=cell&&cell.closest('table');tableToolbar.hidden=!table;if(!table)return;document.getElementById('dd-table-width').value=table.dataset.widthPercent||'100';document.getElementById('dd-table-border-color').value=table.dataset.borderColor||'#aab1ba';document.getElementById('dd-table-border-width').value=table.dataset.borderWidth||'1';}
  sheet.addEventListener('focusin',event=>{const cell=event.target.closest&&event.target.closest('td,th');syncTableToolbar(cell&&sheet.contains(cell)?cell:null);});
  sheet.addEventListener('click',event=>{const cell=event.target.closest&&event.target.closest('td,th');syncTableToolbar(cell&&sheet.contains(cell)?cell:null);});
  document.addEventListener('selectionchange',()=>{const selection=window.getSelection(),node=selection&&selection.anchorNode,element=node&&(node.nodeType===Node.ELEMENT_NODE?node:node.parentElement),cell=element&&element.closest('td,th');if(cell&&sheet.contains(cell))syncTableToolbar(cell);});
  function normalizeColumnWidths(table){const cols=Array.from(table.querySelectorAll(':scope > colgroup > col')),count=Math.max(1,table.rows[0]?.cells.length||cols.length);while(cols.length<count){const col=document.createElement('col');table.querySelector('colgroup').append(col);cols.push(col);}const base=Math.floor(100/count),remainder=100%count;cols.slice(0,count).forEach((col,index)=>col.style.width=(base+(index<remainder?1:0))+'%');cols.slice(count).forEach(col=>col.remove());}
  tableToolbar.addEventListener('click',event=>{
    const action=event.target.closest('[data-table-action]')?.dataset.tableAction;if(!action||!activeTableCell)return;
    const cell=activeTableCell,row=cell.parentElement,table=cell.closest('table'),cellIndex=Array.prototype.indexOf.call(row.cells,cell),rowIndex=Array.prototype.indexOf.call(table.rows,row);
    if(action==='row-before'||action==='row-after'){const newRow=table.insertRow(rowIndex+(action==='row-after'?1:0));for(let i=0;i<Math.max(1,row.cells.length);i++){const td=newRow.insertCell();td.append(document.createElement('br'));}}
    if(action==='row-delete'){if(table.rows.length<=1)table.remove();else table.deleteRow(rowIndex);activeTableCell=null;}
    if(action==='col-before'||action==='col-after'){for(const tr of table.rows){const td=tr.insertCell(Math.min(tr.cells.length,cellIndex+(action==='col-after'?1:0)));td.append(document.createElement('br'));}normalizeColumnWidths(table);}
    if(action==='col-delete'){if(row.cells.length<=1){table.remove();activeTableCell=null;}else{for(const tr of table.rows)if(tr.cells[cellIndex])tr.deleteCell(cellIndex);normalizeColumnWidths(table);}}
    if(action==='merge'){
      const selection=window.getSelection(),range=selection&&selection.rangeCount?selection.getRangeAt(0):null;
      const start=range&&(range.startContainer.nodeType===Node.ELEMENT_NODE?range.startContainer:range.startContainer.parentElement).closest('td,th');
      const end=range&&(range.endContainer.nodeType===Node.ELEMENT_NODE?range.endContainer:range.endContainer.parentElement).closest('td,th');
      if(start&&end&&start.parentElement===end.parentElement&&start!==end){const cells=Array.from(start.parentElement.cells),a=cells.indexOf(start),b=cells.indexOf(end),first=Math.min(a,b),last=Math.max(a,b),target=cells[first];for(let i=first+1;i<=last;i++){target.append(document.createTextNode(' '),...Array.from(cells[i].childNodes));cells[i].remove();}target.colSpan=(target.colSpan||1)+(last-first);syncTableToolbar(target);}
    }
    if(action==='split'&&cell.colSpan>1){const span=cell.colSpan;cell.colSpan=1;for(let i=1;i<span;i++){const td=row.insertCell(cellIndex+i);td.append(document.createElement('br'));}normalizeColumnWidths(table);}
    if(activeTableCell&&activeTableCell.isConnected){activeTableCell.closest('table').dataset.borderColor=document.getElementById('dd-table-border-color').value;activeTableCell.closest('table').dataset.borderWidth=document.getElementById('dd-table-border-width').value;}
    schedule();
  });
  document.getElementById('dd-table-shading').addEventListener('input',event=>{if(activeTableCell){activeTableCell.style.backgroundColor=event.target.value;schedule();}});
  document.getElementById('dd-table-border-color').addEventListener('input',event=>{if(activeTableCell){const table=activeTableCell.closest('table');table.dataset.borderColor=event.target.value;table.style.borderColor=event.target.value;table.querySelectorAll('td,th').forEach(cell=>cell.style.borderColor=event.target.value);schedule();}});
  document.getElementById('dd-table-border-width').addEventListener('change',event=>{if(activeTableCell){const table=activeTableCell.closest('table'),width=Math.max(0,Math.min(8,Number(event.target.value)||0));table.dataset.borderWidth=String(width);table.querySelectorAll('td,th').forEach(cell=>cell.style.borderWidth=width+'px');schedule();}});
  document.getElementById('dd-table-width').addEventListener('change',event=>{if(activeTableCell){const table=activeTableCell.closest('table'),width=Math.max(10,Math.min(100,Number(event.target.value)||100));table.dataset.widthPercent=String(width);table.style.width=width+'%';schedule();}});
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
  const painter=document.getElementById('dd-format-painter');let paintMarks=null;
  painter.addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount)savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();});
  painter.addEventListener('click',()=>{
    const selection=window.getSelection();if(savedRange&&selection){selection.removeAllRanges();selection.addRange(savedRange);}
    const range=selection&&selection.rangeCount?selection.getRangeAt(0):null;if(!range||!sheet.contains(range.commonAncestorContainer))return;
    if(!paintMarks){const fragment=range.cloneContents(),walker=document.createTreeWalker(fragment,NodeFilter.SHOW_TEXT),text=walker.nextNode();if(!text)return;paintMarks=(serializeInline(text.parentElement)[0]?.marks||[]).filter(mark=>mark.type!=='link');painter.setAttribute('aria-pressed','true');painter.title='Select text, then click Format painter to apply. Press Escape to cancel.';return;}
    if(range.collapsed)return;
    let contents=range.extractContents();
    for(const mark of paintMarks){const tag={bold:'strong',italic:'em',underline:'u',strike:'s',superscript:'sup',subscript:'sub',highlight:'mark'}[mark.type]||'span';const wrapper=document.createElement(tag);if(mark.type==='fontFamily'){wrapper.dataset.ddFontFamily=mark.attrs.value;wrapper.style.fontFamily='"'+mark.attrs.value+'"';}else if(mark.type==='fontSize'){wrapper.dataset.ddFontSize=String(mark.attrs.value);wrapper.style.fontSize=mark.attrs.value+'pt';}else if(mark.type==='textColor'){wrapper.dataset.ddTextColor=mark.attrs.color;wrapper.style.color=mark.attrs.color;}else if(mark.type==='highlight'){wrapper.dataset.ddHighlight=mark.attrs.color;wrapper.style.backgroundColor=mark.attrs.color;}wrapper.append(contents);contents=wrapper;}
    range.insertNode(contents);paintMarks=null;painter.setAttribute('aria-pressed','false');painter.title='Copy formatting, then select text to apply';savedRange=null;scheduleFormatting();
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&paintMarks){paintMarks=null;painter.setAttribute('aria-pressed','false');painter.title='Copy formatting, then select text to apply';}});
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
  document.getElementById('dd-line').addEventListener('mousedown',event=>{const selection=window.getSelection();if(selection&&selection.rangeCount&&sheet.contains(selection.anchorNode))savedRange=selection.getRangeAt(0).cloneRange();event.preventDefault();});
  document.getElementById('dd-line').addEventListener('click',()=>{const selection=window.getSelection();if(savedRange&&selection){selection.removeAllRanges();selection.addRange(savedRange);}const range=selection&&selection.rangeCount?selection.getRangeAt(0):null;if(!range||!sheet.contains(range.commonAncestorContainer))return;range.deleteContents();const line=document.createElement('hr'),next=document.createElement('p');range.insertNode(line);line.after(next);const caret=document.createRange();caret.selectNodeContents(next);caret.collapse(true);selection.removeAllRanges();selection.addRange(caret);savedRange=caret.cloneRange();schedule();});
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
    document.getElementById('dd-image-remove').disabled=!enabled;
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
  function wordCount(){const text=Array.from(sheet.querySelectorAll(':scope > .dd-page')).flatMap(page=>Array.from(page.children).filter(node=>!node.matches('.dd-page-zones,.dd-page-header,.dd-page-footer,.dd-page-break-marker')).map(node=>node.innerText||node.textContent||'')).join(' ').trim(),words=text?text.split(/\s+/).filter(Boolean).length:0,separator='\u00b7',summary=words+' '+(words===1?'word':'words')+' '+separator+' '+text.length+' characters';document.getElementById('dd-word-count').textContent=summary;const statusCount=document.getElementById('dd-status-word-count');if(statusCount)statusCount.textContent=summary;const selection=window.getSelection(),selected=selection&&selection.toString()||'',selectedWords=selected.trim()?selected.trim().split(/\s+/).length:0,selectionCount=document.getElementById('dd-selection-count');if(selectionCount)selectionCount.textContent=selected?selectedWords+' '+(selectedWords===1?'word':'words')+' '+separator+' '+selected.length+' characters selected':'';const total=sheet.querySelectorAll(':scope > .dd-page').length||1;const totalNode=document.getElementById('dd-page-total');if(totalNode)totalNode.textContent=String(total);const anchor=selection&&selection.anchorNode,element=anchor&&(anchor.nodeType===Node.ELEMENT_NODE?anchor:anchor.parentElement),page=element&&element.closest('.dd-page'),current=document.getElementById('dd-current-page');if(current)current.textContent=page?.dataset.pageNumber||'1';}
  sheet.addEventListener('input',wordCount);document.addEventListener('selectionchange',wordCount);wordCount();
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
