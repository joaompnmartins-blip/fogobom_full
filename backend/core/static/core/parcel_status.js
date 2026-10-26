// Parcel status colours/labels shared by the Leaflet maps (parcels list, detail, form).
const PARCEL_STATUS = {
  proposta:            { label: 'Proposta',                color: '#cbd5e1' },
  em_avaliacao:        { label: 'Em avaliação',            color: '#eab308' },
  apta:                { label: 'Apta',                    color: '#22c55e' },
  apta_condicionantes: { label: 'Apta c/ condicionantes',  color: '#f97316' },
  nao_apta:            { label: 'Não apta',                color: '#ef4444' },
};

function parcelStatusColor(status) {
  return (PARCEL_STATUS[status] || { color: '#94a3b8' }).color;
}

function parcelStatusLabel(status) {
  return (PARCEL_STATUS[status] || { label: status || '—' }).label;
}

// Leaflet legend control listing every status
function parcelStatusLegend(position) {
  const legend = L.control({ position: position || 'bottomleft' });
  legend.onAdd = function () {
    const div = L.DomUtil.create('div', 'map-legend');
    div.innerHTML = '<div class="legend-title">Estado da parcela</div>' +
      Object.values(PARCEL_STATUS).map(s =>
        `<div><span class="legend-dot" style="background:${s.color}"></span>${s.label}</div>`).join('');
    return div;
  };
  return legend;
}
