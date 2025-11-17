/**
 * Dashboard de entrenamiento de IA en tiempo real
 */

const endpoints = {
  estado: '/ai/api/estado/',
  topEstrategias: '/ai/api/top-estrategias/',
  tradesRecientes: '/ai/api/trades-recientes/',
};

let intervaloActualizacion = null;

const formatoMoneda = new Intl.NumberFormat('es-CO', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
});

const formatoDecimal = new Intl.NumberFormat('es-CO', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const formatoPorcentaje = new Intl.NumberFormat('es-CO', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function setValor(id, valor) {
  const elemento = document.getElementById(id);
  if (elemento) {
    elemento.textContent = valor ?? '--';
  }
}

function formatearMoneda(valor) {
  const num = Number(valor);
  return isFinite(num) ? formatoMoneda.format(num) : '--';
}

function formatearPorcentaje(valor) {
  const num = Number(valor);
  return isFinite(num) ? formatoPorcentaje.format(num) + '%' : '--';
}

function formatearDecimal(valor) {
  const num = Number(valor);
  return isFinite(num) ? formatoDecimal.format(num) : '--';
}

async function obtenerJSON(url) {
  try {
    const respuesta = await fetch(url);
    if (!respuesta.ok) throw new Error(`Error: ${respuesta.status}`);
    return await respuesta.json();
  } catch (error) {
    console.error(`Error al obtener ${url}:`, error);
    return null;
  }
}

async function actualizarEstado() {
  const estado = await obtenerJSON(endpoints.estado);
  if (!estado) return;

  setValor('total-estrategias', estado.total_estrategias);
  setValor('mejor-fitness', formatearDecimal(estado.mejor_estrategia.fitness));
  setValor('winrate-global', formatearPorcentaje(estado.winrate_global));
  setValor('trades-totales', estado.trades_totales);

  // Mejor estrategia
  const mejorDetalle = document.getElementById('mejor-estrategia-detalle');
  if (mejorDetalle && estado.mejor_estrategia.id) {
    mejorDetalle.innerHTML = `
      <p><strong>${estado.mejor_estrategia.nombre}</strong></p>
      <p>Fitness: ${formatearDecimal(estado.mejor_estrategia.fitness)}</p>
      <p>Winrate: ${formatearPorcentaje(estado.mejor_estrategia.winrate)}</p>
      <p>Operaciones: ${estado.mejor_estrategia.operaciones_evaluadas}</p>
    `;
  }
}

async function actualizarTopEstrategias() {
  const data = await obtenerJSON(endpoints.topEstrategias);
  if (!data || !data.estrategias) return;

  const tbody = document.getElementById('tabla-estrategias');
  if (!tbody) return;

  if (data.estrategias.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6">No hay estrategias activas</td></tr>';
    return;
  }

  tbody.innerHTML = data.estrategias.map(e => `
    <tr>
      <td>${e.nombre}</td>
      <td>${e.generacion}</td>
      <td>${formatearDecimal(e.fitness)}</td>
      <td>${formatearPorcentaje(e.winrate)}</td>
      <td>${e.operaciones_evaluadas}</td>
      <td>${formatearMoneda(e.beneficio_total)}</td>
    </tr>
  `).join('');
}

async function actualizarTradesRecientes() {
  const data = await obtenerJSON(endpoints.tradesRecientes);
  if (!data || !data.trades) return;

  const tbody = document.getElementById('tabla-trades');
  if (!tbody) return;

  if (data.trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7">No hay trades registrados</td></tr>';
    return;
  }

  tbody.innerHTML = data.trades.map(t => {
    const resultadoClass = t.resultado === 'win' ? 'ganado' : t.resultado === 'loss' ? 'perdido' : 'pendiente';
    const rewardClass = t.reward > 0 ? 'reward-positivo' : t.reward < 0 ? 'reward-negativo' : '';
    const fecha = new Date(t.hora_inicio);
    
    return `
      <tr>
        <td>${t.estrategia}</td>
        <td>${t.activo}</td>
        <td>${t.direccion}</td>
        <td class="${resultadoClass}">${t.resultado.toUpperCase()}</td>
        <td>${formatearMoneda(t.beneficio)}</td>
        <td class="${rewardClass}">${formatearDecimal(t.reward)}</td>
        <td>${fecha.toLocaleTimeString('es-CO')}</td>
      </tr>
    `;
  }).join('');
}

async function actualizarTodo() {
  await Promise.all([
    actualizarEstado(),
    actualizarTopEstrategias(),
    actualizarTradesRecientes(),
  ]);
}

// Inicializar
document.addEventListener('DOMContentLoaded', () => {
  actualizarTodo();
  
  // Actualizar cada 5 segundos
  intervaloActualizacion = setInterval(actualizarTodo, 5000);
});

// Limpiar intervalo al salir
window.addEventListener('beforeunload', () => {
  if (intervaloActualizacion) {
    clearInterval(intervaloActualizacion);
  }
});

