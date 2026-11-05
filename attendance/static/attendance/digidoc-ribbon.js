(() => {
  'use strict';
  const editor = document.getElementById('digidoc');
  if (!editor) return;
  const tabs = Array.from(editor.querySelectorAll('.dd-tabs [role="tab"]'));
  const ribbon = document.getElementById('dd-ribbon');
  const filePanel = document.getElementById('dd-panel-file');
  const workspace = document.querySelector('.dd-workspace');
  const sheet = document.getElementById('dd-sheet');
  const title = document.getElementById('dd-title');
  const slider = document.getElementById('dd-zoom-slider');
  const zoomOutput = document.getElementById('dd-zoom-output');
  const statusSlider = document.getElementById('dd-status-zoom');
  const statusOutput = document.getElementById('dd-status-zoom-output');
  let activeTab = 'home';

  function setTab(name, focus = false) {
    activeTab = name;
    const isFile = name === 'file';
    filePanel.hidden = !isFile;
    workspace.hidden = isFile;
    document.getElementById('dd-ruler-wrap').hidden = isFile;
    ribbon.hidden = isFile;
    tabs.forEach(tab => {
      const selected = tab.dataset.tab === name;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      const panel = document.querySelector(`[data-panel="${tab.dataset.tab}"]`);
      if (panel) panel.hidden = !selected || isFile;
    });
    if (focus) tabs.find(tab => tab.dataset.tab === name)?.focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => setTab(tab.dataset.tab));
    tab.addEventListener('dblclick', () => { if (tab.dataset.tab !== 'file') toggleRibbon(); });
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      setTab(tabs[nextIndex].dataset.tab, true);
    });
  });
  document.getElementById('dd-file-back').addEventListener('click', () => setTab('home'));
  document.getElementById('dd-file-return').addEventListener('click', () => setTab('home'));
  function toggleRibbon() {
    const collapsed = ribbon.classList.toggle('is-collapsed');
    editor.classList.toggle('dd-ribbon-collapsed', collapsed);
    const button = document.getElementById('dd-ribbon-toggle');
    button.setAttribute('aria-expanded', String(!collapsed));
    button.setAttribute('aria-label', collapsed ? 'Expand ribbon' : 'Collapse ribbon');
    button.title = collapsed ? 'Expand ribbon' : 'Collapse ribbon';
  }
  document.getElementById('dd-ribbon-toggle').addEventListener('click', toggleRibbon);

  function setZoom(value) {
    const zoom = Math.min(200, Math.max(50, Math.round(Number(value) / 10) * 10));
    slider.value = String(zoom);
    statusSlider.value = String(zoom);
    document.getElementById('dd-zoom').value = String(zoom);
    zoomOutput.value = `${zoom}%`;
    zoomOutput.textContent = `${zoom}%`;
    statusOutput.value = `${zoom}%`;
    statusOutput.textContent = `${zoom}%`;
    sheet.classList.forEach(name => { if (name.startsWith('dd-zoom-')) sheet.classList.remove(name); });
    sheet.classList.add(`dd-zoom-${zoom}`);
    sheet.style.zoom = String(zoom / 100);
    document.getElementById('dd-ruler-wrap').style.zoom = String(zoom / 100);
  }
  slider.addEventListener('input', () => setZoom(slider.value));
  statusSlider.addEventListener('input', () => setZoom(statusSlider.value));
  document.getElementById('dd-zoom-minus').addEventListener('click', () => setZoom(Number(slider.value) - 10));
  document.getElementById('dd-zoom-plus').addEventListener('click', () => setZoom(Number(slider.value) + 10));
  function fitPage() {
    const available = Math.max(100, workspace.clientWidth - 44);
    setZoom(Math.max(50, Math.min(200, Math.floor(available / 794 * 100 / 10) * 10)));
  }
  document.getElementById('dd-fit-page').addEventListener('click', fitPage);
  document.getElementById('dd-status-fit').addEventListener('click', fitPage);
  setZoom(100);

  document.getElementById('dd-ruler-toggle').addEventListener('change', event => {
    document.getElementById('dd-ruler-wrap').hidden = !event.target.checked;
  });
  document.getElementById('dd-save-now').addEventListener('click', () => editor.dispatchEvent(new Event('digidoc:save')));
  title.addEventListener('input', () => { document.getElementById('dd-file-title').value = title.value; });

  const letterheadToggle = document.getElementById('dd-letterhead-menu');
  letterheadToggle.addEventListener('click', () => {
    const checkbox = document.getElementById('dd-letterhead');
    if (checkbox.disabled) return;
    checkbox.checked = !checkbox.checked;
    letterheadToggle.textContent = checkbox.checked ? 'Remove letterhead' : 'Letterhead';
    checkbox.dispatchEvent(new Event('change', { bubbles: true }));
  });
  document.getElementById('dd-letterhead').addEventListener('change', event => {
    letterheadToggle.textContent = event.target.checked ? 'Remove letterhead' : 'Letterhead';
  });

  function updateCurrentPage() {
    const selection = window.getSelection();
    const anchor = selection && selection.anchorNode;
    const element = anchor && (anchor.nodeType === Node.ELEMENT_NODE ? anchor : anchor.parentElement);
    const page = element && element.closest('.dd-page');
    document.getElementById('dd-current-page').textContent = page?.dataset.pageNumber || '1';
    document.getElementById('dd-page-total').textContent = String(sheet.querySelectorAll(':scope > .dd-page').length || 1);
    const text = (sheet.innerText || '').trim();
    const words = text ? text.split(/\s+/).filter(Boolean).length : 0;
    document.getElementById('dd-status-word-count').textContent = `${words} ${words === 1 ? 'word' : 'words'}`;
    document.getElementById('dd-word-count').textContent = `${words} ${words === 1 ? 'word' : 'words'}`;
  }
  document.addEventListener('selectionchange', updateCurrentPage);
  sheet.addEventListener('input', () => requestAnimationFrame(updateCurrentPage));
  new MutationObserver(updateCurrentPage).observe(sheet, { childList: true, subtree: true });
  function updateFormatStates() {
    editor.querySelectorAll('.dd-group-controls [data-command]').forEach(button => {
      const command = button.dataset.command;
      if (!['bold', 'italic', 'underline', 'strikeThrough', 'insertUnorderedList', 'insertOrderedList'].includes(command)) return;
      const active = document.queryCommandState(command);
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
    });
  }
  document.addEventListener('selectionchange', updateFormatStates);
  sheet.addEventListener('keyup', updateFormatStates);
  sheet.addEventListener('mouseup', updateFormatStates);
  window.addEventListener('resize', updateCurrentPage);
  updateCurrentPage();
})();
