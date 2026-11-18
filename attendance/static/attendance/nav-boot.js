// Runs synchronously right after <body> so the saved navigation state is in
// place before the sidebar paints. Kept as an external file because the
// DigiDoc editor's Content-Security-Policy only allows scripts from 'self'.
(function () {
  try {
    if (window.matchMedia('(min-width: 1024px)').matches &&
        window.localStorage.getItem('digi02hr.nav.rail.v2') === '0') {
      document.body.classList.remove('rail');
    }
  } catch (error) { /* storage can be unavailable */ }
})();
