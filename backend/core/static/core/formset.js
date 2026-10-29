// Inline formsets: add rows without saving, remove rows with a button.
// Markup: <tbody data-formset="PREFIX">, rows with class "fs-row", a <template id="PREFIX-empty">
// holding the empty form row (__prefix__), and a button data-add-row="PREFIX".
(function () {
  function removeRow(row) {
    const del = row.querySelector('input[name$="-DELETE"]');
    if (del && row.dataset.saved === '1') {   // saved row: mark for deletion on save
      del.checked = true;
      row.style.display = 'none';
    } else {                                  // new row: clear it so it is ignored on save
      row.querySelectorAll('input, select, textarea').forEach(el => {
        if (el.type === 'hidden' || el.type === 'checkbox') return;
        el.value = '';
      });
      row.style.display = 'none';
    }
  }

  function wire(row) {
    const btn = row.querySelector('.fs-remove');
    if (btn) btn.addEventListener('click', () => removeRow(row));
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('tbody[data-formset]').forEach(body => {
      const prefix = body.dataset.formset;
      const total = document.querySelector(`input[name="${prefix}-TOTAL_FORMS"]`);
      const tpl = document.getElementById(`${prefix}-empty`);
      body.querySelectorAll('tr.fs-row').forEach(wire);
      document.querySelectorAll(`[data-add-row="${prefix}"]`).forEach(btn => btn.addEventListener('click', () => {
        const n = parseInt(total.value, 10);
        const holder = document.createElement('tbody');
        holder.innerHTML = tpl.innerHTML.replace(/__prefix__/g, n);
        const row = holder.querySelector('tr');
        body.appendChild(row);
        wire(row);
        total.value = n + 1;
        const first = row.querySelector('input:not([type=hidden]), select');
        if (first) first.focus();
      }));
    });
  });
})();
