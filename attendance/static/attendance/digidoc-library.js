(() => {
  'use strict';
  const filters = document.querySelector('.dd-library-toolbar');
  if (filters) {
    filters.querySelectorAll('select').forEach(select => {
      select.addEventListener('change', () => filters.requestSubmit());
    });
  }

  document.querySelectorAll('.dd-document-preview img').forEach(image => {
    const showPlaceholder = () => {
      image.hidden = true;
      const placeholder = image.nextElementSibling;
      if (placeholder) placeholder.hidden = false;
    };
    image.addEventListener('error', showPlaceholder, {once: true});
    if (image.complete && !image.naturalWidth) showPlaceholder();
  });

  document.querySelectorAll('.dd-document-delete-form').forEach(form => {
    form.addEventListener('submit', event => {
      if (!window.confirm('Delete this document?')) event.preventDefault();
    });
  });

  document.addEventListener('click', event => {
    document.querySelectorAll('.dd-document-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
})();
