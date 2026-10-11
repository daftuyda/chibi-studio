// Apply the saved appearance before the stylesheet paints the page.
(() => {
  const key = 'chibi-ui-theme-v1';
  const system = matchMedia('(prefers-color-scheme: dark)');
  let choice;
  try { choice = localStorage.getItem(key); } catch { }
  if (!['light', 'dark'].includes(choice)) choice = null;

  function apply() {
    const dark = (choice || (system.matches ? 'dark' : 'light')) === 'dark';
    document.documentElement.dataset.uiTheme = dark ? 'dark' : 'light';
    const button = document.getElementById('ui-theme-toggle');
    if (!button) return;
    const next = dark ? 'light' : 'dark';
    button.setAttribute('aria-label', `Switch to ${next} mode`);
    button.title = `Switch to ${next} mode`;
    document.getElementById('ui-theme-label').textContent = dark ? 'Light mode' : 'Dark mode';
  }

  apply();
  system.addEventListener('change', () => { if (!choice) apply(); });
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.getElementById('ui-theme-toggle').addEventListener('click', () => {
      choice = document.documentElement.dataset.uiTheme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(key, choice); } catch { }
      apply();
    });
  });
})();
