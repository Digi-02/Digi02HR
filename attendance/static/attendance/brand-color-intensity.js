(() => {
  'use strict';

  function withSaturation(hex, intensity) {
    const match = /^#([\da-f]{6})$/i.exec(hex || '');
    if (!match) return hex;
    const digits = match[1];
    const rgb = [0, 2, 4].map(offset => parseInt(digits.slice(offset, offset + 2), 16) / 255);
    const max = Math.max(...rgb), min = Math.min(...rgb), light = (max + min) / 2;
    let hue = 0;
    let saturation = max === min ? 0 : (max - min) / (1 - Math.abs(2 * light - 1));
    saturation *= Math.min(100, Math.max(0, Number(intensity))) / 100;
    if (max !== min) {
      if (max === rgb[0]) hue = ((rgb[1] - rgb[2]) / (max - min)) % 6;
      else if (max === rgb[1]) hue = (rgb[2] - rgb[0]) / (max - min) + 2;
      else hue = (rgb[0] - rgb[1]) / (max - min) + 4;
      hue = (hue * 60 + 360) % 360;
    }
    const chroma = (1 - Math.abs(2 * light - 1)) * saturation;
    const x = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
    const offset = light - chroma / 2;
    const triplet = hue < 60 ? [chroma, x, 0] : hue < 120 ? [x, chroma, 0] : hue < 180 ? [0, chroma, x] : hue < 240 ? [0, x, chroma] : hue < 300 ? [x, 0, chroma] : [chroma, 0, x];
    return '#' + triplet.map(channel => Math.round((channel + offset) * 255).toString(16).padStart(2, '0')).join('').toUpperCase();
  }

  function attachIntensity(picker, hexInput, slider, output) {
    if (!picker || !hexInput || !slider || !output) return null;
    let sourceHex = picker.value.toUpperCase();
    let applying = false;
    function apply() {
      const value = Number(slider.value);
      const adjusted = withSaturation(sourceHex, value);
      slider.setAttribute('aria-valuenow', String(value));
      output.value = `${value}%`;
      output.textContent = `${value}%`;
      picker.value = adjusted;
      hexInput.value = adjusted;
      applying = true;
      hexInput.dispatchEvent(new Event('input', { bubbles: true }));
      applying = false;
    }
    picker.addEventListener('input', () => {
      if (applying) return;
      sourceHex = picker.value.toUpperCase();
      apply();
    });
    hexInput.addEventListener('input', () => {
      if (applying || !/^#[\da-f]{6}$/i.test(hexInput.value)) return;
      sourceHex = hexInput.value.toUpperCase();
      apply();
    });
    slider.addEventListener('input', apply);
    apply();
    return {
      get sourceHex() { return sourceHex; },
      set sourceHex(value) { sourceHex = value; },
      apply
    };
  }

  const brandPicker = document.getElementById('brandPicker');
  const brand = attachIntensity(
    brandPicker,
    document.getElementById('id_brand_color'),
    document.getElementById('brandIntensity'),
    document.getElementById('brandIntensityValue')
  );
  const highlight = attachIntensity(
    document.querySelector('[data-color-picker-for="id_nav_highlight_color"]'),
    document.getElementById('id_nav_highlight_color'),
    document.getElementById('navHighlightIntensity'),
    document.getElementById('navHighlightIntensityValue')
  );

  const suggested = document.getElementById('suggestedColour');
  if (suggested) suggested.addEventListener('click', () => {
    if (brand && brandPicker && /^#[\da-f]{6}$/i.test(brandPicker.value)) {
      brand.sourceHex = brandPicker.value.toUpperCase();
      brand.apply();
    }
  });
  const eyedropper = document.getElementById('eyeBtn');
  if (eyedropper) eyedropper.addEventListener('click', () => {
    window.setTimeout(() => {
      if (brand && brandPicker && /^#[\da-f]{6}$/i.test(brandPicker.value)) {
        brand.sourceHex = brandPicker.value.toUpperCase();
        brand.apply();
      }
    }, 0);
  });
})();
