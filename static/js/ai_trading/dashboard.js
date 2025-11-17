/**
 * Dashboard de entrenamiento de IA en tiempo real con WebSocket y gráficos
 */

const endpoints = {
  estado: '/ai/api/estado/',
  topEstrategias: '/ai/api/top-estrategias/',
  tradesRecientes: '/ai/api/trades-recientes/',
  controlEntrenamiento: '/ai/api/control-entrenamiento/',
};

// Variables globales
let intervaloActualizacion = null;
let socketEntrenamiento = null;
let chartFitness = null;
let chartEvolucion = null;
let datosFitness = {
  generaciones: [],
  promedio: [],
  mejor: [],
  peor: [],
};

// Formateadores
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

// WebSocket
function conectarWebSocket() {
  const protocolo = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const url = `${protocolo}//${host}/ws/ai/entrenamiento/`;
  
  socketEntrenamiento = new WebSocket(url);
  
  socketEntrenamiento.onopen = () => {
    console.log('WebSocket conectado al entrenamiento de IA');
  };
  
  socketEntrenamiento.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      procesarMensajeWebSocket(data);
    } catch (error) {
      console.error('Error al procesar mensaje WebSocket:', error);
    }
  };
  
  socketEntrenamiento.onerror = (error) => {
    console.error('Error en WebSocket:', error);
  };
  
  socketEntrenamiento.onclose = () => {
    console.log('WebSocket desconectado. Reintentando en 5 segundos...');
    setTimeout(conectarWebSocket, 5000);
  };
}

function procesarMensajeWebSocket(data) {
  switch (data.tipo) {
    case 'conexion':
      console.log('Conectado:', data.mensaje);
      break;
    
    case 'progreso_generacion':
      actualizarProgresoGeneracion(data);
      break;
    
    case 'evaluacion_estrategia':
      actualizarEvaluacionEstrategia(data);
      break;
    
    case 'estado_entrenamiento':
      actualizarEstadoEntrenamiento(data);
      break;
    
    case 'nuevo_trade':
      // Actualizar tabla de trades
      actualizarTradesRecientes();
      break;
  }
}

function actualizarProgresoGeneracion(data) {
  // Actualizar gráficos
  datosFitness.generaciones.push(data.generacion);
  datosFitness.promedio.push(data.fitness_promedio);
  datosFitness.mejor.push(data.fitness_mejor);
  datosFitness.peor.push(data.fitness_peor);
  
  if (chartFitness) {
    chartFitness.data.labels = datosFitness.generaciones;
    chartFitness.data.datasets[0].data = datosFitness.promedio;
    chartFitness.data.datasets[1].data = datosFitness.mejor;
    chartFitness.data.datasets[2].data = datosFitness.peor;
    chartFitness.update('none');
  }
  
  if (chartEvolucion) {
    chartEvolucion.data.labels = datosFitness.generaciones;
    chartEvolucion.data.datasets[0].data = datosFitness.mejor;
    chartEvolucion.update('none');
  }
  
  // Actualizar texto de progreso
  const progresoTexto = `Generación ${data.generacion}/${data.total_generaciones} | ` +
    `Fitness Promedio: ${formatearDecimal(data.fitness_promedio)} | ` +
    `Mejor: ${formatearDecimal(data.fitness_mejor)} | ` +
    `Tiempo: ${formatearTiempo(data.tiempo_transcurrido)}`;
  setValor('progreso-texto', progresoTexto);
}

function actualizarEvaluacionEstrategia(data) {
  const progresoTexto = `Evaluando estrategia ${data.estrategia_numero}/${data.total_estrategias}: ${data.estrategia_nombre} | Fitness: ${formatearDecimal(data.fitness)}`;
  setValor('progreso-texto', progresoTexto);
}

function actualizarEstadoEntrenamiento(data) {
  const badge = document.getElementById('badge-estado');
  if (badge) {
    badge.textContent = data.estado.toUpperCase();
    badge.className = 'ai-estado-badge ai-estado-badge--' + data.estado;
  }
  
  if (data.estado === 'en_curso') {
    document.getElementById('btn-iniciar').disabled = true;
    document.getElementById('btn-detener').disabled = false;
  } else {
    document.getElementById('btn-iniciar').disabled = false;
    document.getElementById('btn-detener').disabled = true;
  }
}

function formatearTiempo(segundos) {
  if (!segundos) return '0s';
  const horas = Math.floor(segundos / 3600);
  const minutos = Math.floor((segundos % 3600) / 60);
  const segs = Math.floor(segundos % 60);
  
  if (horas > 0) {
    return `${horas}h ${minutos}m ${segs}s`;
  } else if (minutos > 0) {
    return `${minutos}m ${segs}s`;
  } else {
    return `${segs}s`;
  }
}

// Inicializar gráficos
function inicializarGraficos() {
  // Gráfico de Fitness por Generación
  const ctxFitness = document.getElementById('grafico-fitness');
  if (ctxFitness) {
    chartFitness = new Chart(ctxFitness, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Fitness Promedio',
            data: [],
            borderColor: 'rgb(75, 192, 192)',
            backgroundColor: 'rgba(75, 192, 192, 0.2)',
            tension: 0.1,
          },
          {
            label: 'Fitness Mejor',
            data: [],
            borderColor: 'rgb(54, 162, 235)',
            backgroundColor: 'rgba(54, 162, 235, 0.2)',
            tension: 0.1,
          },
          {
            label: 'Fitness Peor',
            data: [],
            borderColor: 'rgb(255, 99, 132)',
            backgroundColor: 'rgba(255, 99, 132, 0.2)',
            tension: 0.1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
          },
        },
        animation: {
          duration: 0,
        },
      },
    });
  }
  
  // Gráfico de Evolución
  const ctxEvolucion = document.getElementById('grafico-evolucion');
  if (ctxEvolucion) {
    chartEvolucion = new Chart(ctxEvolucion, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Mejor Fitness',
            data: [],
            borderColor: 'rgb(54, 162, 235)',
            backgroundColor: 'rgba(54, 162, 235, 0.2)',
            fill: true,
            tension: 0.4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
          },
        },
        animation: {
          duration: 0,
        },
      },
    });
  }
}

// Control de entrenamiento
async function iniciarEntrenamiento() {
  const datos = {
    accion: 'iniciar',
    generaciones: parseInt(document.getElementById('input-generaciones').value),
    poblacion: parseInt(document.getElementById('input-poblacion').value),
    tasa_mutacion: parseFloat(document.getElementById('input-mutacion').value),
    tasa_crossover: parseFloat(document.getElementById('input-crossover').value),
    elite_size: parseInt(document.getElementById('input-elite').value),
    dias_datos: parseInt(document.getElementById('input-dias').value),
  };
  
  try {
    const respuesta = await fetch(endpoints.controlEntrenamiento, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      body: JSON.stringify(datos),
    });
    
    const resultado = await respuesta.json();
    
    if (resultado.success) {
      alert('Entrenamiento iniciado exitosamente');
      // Limpiar gráficos
      datosFitness = { generaciones: [], promedio: [], mejor: [], peor: [] };
      if (chartFitness) {
        chartFitness.data.labels = [];
        chartFitness.data.datasets.forEach(ds => ds.data = []);
        chartFitness.update();
      }
      if (chartEvolucion) {
        chartEvolucion.data.labels = [];
        chartEvolucion.data.datasets.forEach(ds => ds.data = []);
        chartEvolucion.update();
      }
    } else {
      alert('Error: ' + resultado.error);
    }
  } catch (error) {
    console.error('Error al iniciar entrenamiento:', error);
    alert('Error al iniciar entrenamiento');
  }
}

async function detenerEntrenamiento() {
  try {
    const respuesta = await fetch(endpoints.controlEntrenamiento, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      body: JSON.stringify({ accion: 'detener' }),
    });
    
    const resultado = await respuesta.json();
    
    if (resultado.success) {
      alert('Entrenamiento detenido');
    } else {
      alert('Error: ' + resultado.error);
    }
  } catch (error) {
    console.error('Error al detener entrenamiento:', error);
    alert('Error al detener entrenamiento');
  }
}

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

// Funciones de actualización de datos
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

// Verificar estado del entrenamiento
async function verificarEstadoEntrenamiento() {
  try {
    const respuesta = await fetch(endpoints.controlEntrenamiento);
    const resultado = await respuesta.json();
    
    if (resultado.success && resultado.estado) {
      actualizarEstadoEntrenamiento({
        estado: resultado.estado.estado,
        mensaje: resultado.estado.nombre,
      });
    }
  } catch (error) {
    console.error('Error al verificar estado:', error);
  }
}

// Inicializar
document.addEventListener('DOMContentLoaded', () => {
  // Inicializar gráficos
  inicializarGraficos();
  
  // Conectar WebSocket
  conectarWebSocket();
  
  // Cargar datos iniciales
  actualizarTodo();
  verificarEstadoEntrenamiento();
  
  // Event listeners
  document.getElementById('btn-iniciar').addEventListener('click', iniciarEntrenamiento);
  document.getElementById('btn-detener').addEventListener('click', detenerEntrenamiento);
  
  // Actualizar cada 5 segundos
  intervaloActualizacion = setInterval(actualizarTodo, 5000);
});

// Limpiar al salir
window.addEventListener('beforeunload', () => {
  if (intervaloActualizacion) {
    clearInterval(intervaloActualizacion);
  }
  if (socketEntrenamiento) {
    socketEntrenamiento.close();
  }
});
