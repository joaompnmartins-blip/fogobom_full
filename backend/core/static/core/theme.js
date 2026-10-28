// Light theme by default; the choice is remembered in this browser. Loaded in <head> to avoid a flash.
(function () {
  var t = 'light';
  try { t = localStorage.getItem('fb-theme') || 'light'; } catch (e) { /* storage blocked */ }
  document.documentElement.setAttribute('data-theme', t);
})();

function toggleTheme() {
  var t = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('fb-theme', t); } catch (e) { /* storage blocked */ }
  document.querySelectorAll('.theme-toggle').forEach(function (b) { b.textContent = themeLabel(); });
}

function themeLabel() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? '☀️ Tema claro' : '🌙 Tema escuro';
}

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.theme-toggle').forEach(function (b) {
    b.textContent = themeLabel();
    b.addEventListener('click', toggleTheme);
  });
});
