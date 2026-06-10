/* ── MyGate Theme Manager ──────────────────────────────────────────── */
// Applies and persists the user's light/dark preference.
// Called early (before body renders) to avoid flash of wrong theme.

(function () {
  var saved = localStorage.getItem('mg_theme') || 'light';
  document.documentElement.setAttribute('data-theme', saved);
})();

function _applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('mg_theme', theme);
  document.querySelectorAll('.theme-toggle-btn').forEach(function (btn) {
    btn.textContent = theme === 'dark' ? '☀️' : '🌙';
    btn.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    btn.setAttribute('aria-label', btn.title);
  });
}

function toggleTheme() {
  var current = document.documentElement.getAttribute('data-theme') || 'light';
  _applyTheme(current === 'dark' ? 'light' : 'dark');
}

function initTheme() {
  var saved = localStorage.getItem('mg_theme') || 'light';
  _applyTheme(saved);
}
