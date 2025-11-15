const endpoints = {
  estadoBot: "/api/trading/estado/",
  winrate: "/api/dashboard/winrate/",
  balance: "/api/dashboard/balance/",
  operaciones: "/api/dashboard/historicos/",
  estadisticas: "/api/dashboard/estadisticas-call-put/",
  temporizador: "/api/dashboard/temporizador/",
  simulacion: "/api/simulacion/resultados/",
};

const formatoMoneda = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
});
const formatoDecimal = new Intl.NumberFormat("es-CO", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const formatoEntero = new Intl.NumberFormat("es-CO");
const formatoHora = new Intl.DateTimeFormat("es-CO", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});
const formatoFechaCorta = new Intl.DateTimeFormat("es-CO", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

let socketConexion = null;
let socketDashboard = null;  // Nueva conexión para el dashboard
let refrescoEnCurso = false;
let refrescoPendiente = false;
let temporizadorIntervalo = null;
let ultimoBalance = null;

const temporizadorEstado = {
  pausado: false,
  tiempoDetencion: null,
  tiempoRestante: null,
  reactivacion: null,
};

async function obtenerJSON(url) {
  const respuesta = await fetch(url);
  if (!respuesta.ok) {
    throw new Error(`Error al consultar ${url}`);
  }
  return respuesta.json();
}

function setValor(id, valor) {
  const elemento = document.getElementById(id);
  if (!elemento) return;
  const nuevoTexto = valor ?? "--";
  if (elemento.textContent !== nuevoTexto) {
    elemento.textContent = nuevoTexto;
    elemento.classList.add("pulse");
    elemento.addEventListener(
      "animationend",
      () => elemento.classList.remove("pulse"),
      { once: true }
    );
  }
}

function convertirNumero(valor) {
  const numero = Number(valor);
  return Number.isFinite(numero) ? numero : null;
}

function formatearMoneda(valor) {
  const numero = convertirNumero(valor);
  return numero === null ? "--" : formatoMoneda.format(numero);
}

function formatearPorcentaje(valor) {
  const numero = convertirNumero(valor);
  return numero === null ? "--" : formatoDecimal.format(numero);
}

function formatearEntero(valor) {
  const numero = convertirNumero(valor);
  return numero === null ? "--" : formatoEntero.format(numero);
}

function actualizarChipCabecera(estado) {
  const chip = document.getElementById("chip-estado");
  const badge = document.getElementById("badge-estado");
  const estadoNormalizado = estado ? estado.toUpperCase() : "--";

  if (chip) {
    chip.textContent = estadoNormalizado;
  }
  if (badge) {
    badge.textContent = estadoNormalizado;
    badge.classList.remove(
      "panel__status-badge--operando",
      "panel__status-badge--pausado"
    );
    if (estado === "operando") {
      badge.classList.add("panel__status-badge--operando");
    } else if (estado === "pausado") {
      badge.classList.add("panel__status-badge--pausado");
    }
  }
}

function actualizarSelloTemporal(fecha = new Date()) {
  setValor("marca-tiempo", formatoHora.format(fecha));
  setValor("marca-tiempo-pie", formatoFechaCorta.format(fecha));
}

function actualizarVariacionBalance(nuevoBalance) {
  const elemento = document.getElementById("variacion-balance");
  if (!elemento || nuevoBalance === null) {
    if (elemento) elemento.textContent = "Sin variaciones registradas";
    return;
  }

  if (ultimoBalance === null) {
    ultimoBalance = nuevoBalance;
    elemento.textContent = "Esperando histórico";
    elemento.classList.remove("positivo", "negativo");
    return;
  }

  const diferencia = nuevoBalance - ultimoBalance;
  if (Math.abs(diferencia) < 0.0001) {
    elemento.textContent = "Sin variaciones";
    elemento.classList.remove("positivo", "negativo");
    return;
  }

  const porcentaje = ultimoBalance === 0 ? 0 : (diferencia / ultimoBalance) * 100;
  const texto = `${diferencia > 0 ? "+" : ""}${formatoMoneda.format(diferencia)} (${formatoDecimal.format(porcentaje)}%)`;
  elemento.textContent = texto;
  elemento.classList.toggle("positivo", diferencia > 0);
  elemento.classList.toggle("negativo", diferencia < 0);
  ultimoBalance = nuevoBalance;
}

function actualizarEstadoBot(data) {
  const estado = data.estado || "--";
  const balance = convertirNumero(data.balance_actual);
  const meta = convertirNumero(data.meta_actual);
  const stopLoss = convertirNumero(data.stop_loss_actual);
  const ganancia = convertirNumero(data.ganancia_acumulada);
  const perdida = convertirNumero(data.perdida_acumulada);
  const neto = (ganancia ?? 0) - (perdida ?? 0);

  setValor("estado-bot", estado.toUpperCase());
  setValor("balance-actual", formatearMoneda(balance));
  setValor("meta-actual", formatearMoneda(meta));
  setValor("stop-loss-actual", formatearMoneda(stopLoss));
  setValor("perdida-acumulada", formatearMoneda(perdida));

  const netoElemento = document.getElementById("ganancia-acumulada");
  if (netoElemento) {
    netoElemento.textContent = formatearMoneda(neto);
    netoElemento.classList.toggle("valor-positivo", neto >= 0);
    netoElemento.classList.toggle("valor-negativo", neto < 0);
  }

  actualizarChipCabecera(estado);
  actualizarVariacionBalance(balance);
}

function actualizarWinrate(data) {
  setValor("total-operaciones", formatearEntero(data.total_operaciones));
  setValor("operaciones-ganadas", formatearEntero(data.ganadas));
  setValor("winrate", formatearPorcentaje(data.winrate));
}

function actualizarEstadisticas(data) {
  setValor("ganadas-call", formatearEntero(data.ganadas_call));
  setValor("perdidas-call", formatearEntero(data.perdidas_call));
  setValor("ganadas-put", formatearEntero(data.ganadas_put));
  setValor("perdidas-put", formatearEntero(data.perdidas_put));
}

function renderTablaOperaciones(tbodyId, datos, mensajeVacio) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!datos.length) {
    const columnas = tbody.parentElement
      ?.querySelector("thead th")
      ?.parentElement?.childElementCount;
    const span = columnas || 6;
    tbody.innerHTML = `<tr><td colspan="${span}">${mensajeVacio}</td></tr>`;
    return;
  }

  datos.forEach((operacion) => {
    const fila = document.createElement("tr");
    const celdas = [
      operacion.numero_contrato,
      operacion.activo,
      operacion.direccion,
      operacion.resultado,
      operacion.beneficio,
      operacion.hora_inicio
        ? new Date(operacion.hora_inicio).toLocaleString()
        : "--",
    ];

    celdas.forEach((valor, indice) => {
      const celda = document.createElement("td");
      if (indice === 4) {
        const numero = convertirNumero(valor);
        celda.textContent =
          numero === null ? valor ?? "--" : formatearMoneda(numero);
        celda.classList.add(
          numero !== null && numero >= 0 ? "positivo" : "negativo"
        );
      } else {
        celda.textContent = valor ?? "--";
      }
      fila.appendChild(celda);
    });
    tbody.appendChild(fila);
  });
}

function actualizarOperaciones(data) {
  renderTablaOperaciones(
    "tabla-operaciones",
    data,
    "Sin operaciones registradas"
  );
}

function detenerTemporizador() {
  if (temporizadorIntervalo) {
    clearInterval(temporizadorIntervalo);
    temporizadorIntervalo = null;
  }
}

function formatearDuracion(segundos) {
  if (segundos == null || Number.isNaN(segundos) || segundos < 0) {
    return "--";
  }
  const horas = Math.floor(segundos / 3600);
  const minutos = Math.floor((segundos % 3600) / 60);
  const segundosRestantes = Math.floor(segundos % 60);
  return `${horas}h ${minutos}m ${segundosRestantes}s`;
}

function renderTemporizador() {
  if (!temporizadorEstado.pausado) {
    setValor("pausado-desde", "--");
    setValor("reactivacion-programada", "--");
    setValor("tiempo-restante", "--");
    return;
  }

  setValor(
    "pausado-desde",
    formatearDuracion(temporizadorEstado.tiempoDetencion)
  );

  if (temporizadorEstado.reactivacion) {
    setValor(
      "reactivacion-programada",
      temporizadorEstado.reactivacion.toLocaleString()
    );
  } else {
    setValor("reactivacion-programada", "--");
  }

  setValor(
    "tiempo-restante",
    formatearDuracion(temporizadorEstado.tiempoRestante)
  );
}

function iniciarTemporizador() {
  detenerTemporizador();
  renderTemporizador();
  temporizadorIntervalo = setInterval(() => {
    if (!temporizadorEstado.pausado) {
      detenerTemporizador();
      return;
    }
    if (temporizadorEstado.tiempoDetencion != null) {
      temporizadorEstado.tiempoDetencion += 1;
    }
    if (
      temporizadorEstado.tiempoRestante != null &&
      temporizadorEstado.tiempoRestante > 0
    ) {
      temporizadorEstado.tiempoRestante -= 1;
    }
    renderTemporizador();
  }, 1000);
}

function actualizarTemporizador(data) {
  temporizadorEstado.pausado = Boolean(data.pausado);
  temporizadorEstado.tiempoDetencion =
    data.tiempo_detencion != null ? Math.round(Number(data.tiempo_detencion)) : null;
  temporizadorEstado.tiempoRestante =
    data.tiempo_restante != null ? Math.round(Number(data.tiempo_restante)) : null;
  temporizadorEstado.reactivacion = data.reactivacion
    ? new Date(data.reactivacion)
    : null;

  if (!temporizadorEstado.pausado) {
    detenerTemporizador();
    renderTemporizador();
    return;
  }

  if (temporizadorEstado.tiempoDetencion == null) {
    temporizadorEstado.tiempoDetencion = 0;
  }

  iniciarTemporizador();
}

function actualizarSimulacionResumen(resumen) {
  const tbody = document.getElementById("tabla-simulacion-resumen");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!resumen.length) {
    tbody.innerHTML =
      '<tr><td colspan="5">Sin datos de simulación</td></tr>';
    return;
  }

  resumen.forEach((fila) => {
    const tr = document.createElement("tr");
    const columnas = [
      fila.activo,
      fila.hora_inicio,
      formatearEntero(fila.total_operaciones),
      formatearEntero(fila.operaciones_ganadas),
      formatearEntero(fila.operaciones_perdidas),
      formatearPorcentaje(fila.winrate),
    ];
    columnas.forEach((valor) => {
      const td = document.createElement("td");
      td.textContent = valor ?? "--";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function actualizarSimulacionOperaciones(operaciones) {
  renderTablaOperaciones(
    "tabla-simulacion-operaciones",
    operaciones,
    "Sin operaciones simuladas"
  );
}

function actualizarSimulacion(data) {
  const resumen = data?.resumen ?? [];
  const operaciones = data?.operaciones ?? [];
  actualizarSimulacionResumen(resumen);
  actualizarSimulacionOperaciones(operaciones);
}

async function refrescarPanel() {
  if (refrescoEnCurso) {
    refrescoPendiente = true;
    return;
  }
  refrescoEnCurso = true;
  try {
    const [
      estadoBot,
      winrate,
      estadisticas,
      temporizador,
      operaciones,
      simulacion,
    ] = await Promise.all([
      obtenerJSON(endpoints.estadoBot),
      obtenerJSON(endpoints.winrate),
      obtenerJSON(endpoints.estadisticas),
      obtenerJSON(endpoints.temporizador),
      obtenerJSON(endpoints.operaciones),
      obtenerJSON(endpoints.simulacion),
    ]);
    actualizarEstadoBot(estadoBot);
    actualizarWinrate(winrate);
    actualizarEstadisticas(estadisticas);
    actualizarTemporizador(temporizador);
    actualizarOperaciones(operaciones);
    actualizarSimulacion(simulacion);
    actualizarSelloTemporal();
  } catch (error) {
    console.error(error);
  } finally {
    refrescoEnCurso = false;
    if (refrescoPendiente) {
      refrescoPendiente = false;
      refrescarPanel();
    }
  }
}

function manejarMensajeTiempoReal(data) {
  if (!data) return;
  if (data.tipo === "operacion" && data.actualizar_panel) {
    refrescarPanel();
  } else if (data.tipo === "error") {
    console.error("[Tiempo real]", data.mensaje ?? data.error);
  } else if (data.actualizar_panel) {
    refrescarPanel();
  }
}

function manejarActualizacionDashboard(data) {
  if (!data || data.tipo !== "actualizacion_completa") return;
  
  console.log("[Dashboard] Actualización recibida:", data.timestamp);
  
  // Actualizar estado del bot
  if (data.estado) {
    actualizarEstadoBot(data.estado);
  }
  
  // Actualizar winrate
  if (data.winrate) {
    actualizarWinrate(data.winrate);
  }
  
  // Actualizar estadísticas
  if (data.estadisticas) {
    actualizarEstadisticas(data.estadisticas);
  }
  
  // Actualizar operaciones
  if (data.operaciones) {
    actualizarOperaciones(data.operaciones);
  }
  
  // Actualizar temporizador
  if (data.temporizador) {
    actualizarTemporizador(data.temporizador);
  }
  
  // Actualizar sello temporal
  actualizarSelloTemporal();
}

function iniciarSocket() {
  const protocolo = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${protocolo}://${window.location.host}/ws/deriv/estado/`;

  socketConexion = new WebSocket(url);

  socketConexion.onopen = () => {
    console.info("[Tiempo real] Conectado al canal de estado.");
  };

  socketConexion.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      manejarMensajeTiempoReal(data);
    } catch (error) {
      console.error("Error procesando mensaje en tiempo real:", error);
    }
  };

  socketConexion.onclose = () => {
    console.warn("[Tiempo real] Conexión cerrada. Reintentando en 5s...");
    setTimeout(iniciarSocket, 5000);
  };

  socketConexion.onerror = (error) => {
    console.error("[Tiempo real] Error en la conexión:", error);
    socketConexion.close();
  };
}

function iniciarSocketDashboard() {
  const protocolo = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${protocolo}://${window.location.host}/ws/dashboard/`;

  socketDashboard = new WebSocket(url);

  socketDashboard.onopen = () => {
    console.info("[Dashboard] Conectado al canal de actualizaciones en tiempo real.");
  };

  socketDashboard.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.tipo === "conexion") {
        console.info("[Dashboard]", data.mensaje);
      } else {
        manejarActualizacionDashboard(data);
      }
    } catch (error) {
      console.error("[Dashboard] Error procesando mensaje:", error);
    }
  };

  socketDashboard.onclose = () => {
    console.warn("[Dashboard] Conexión cerrada. Reintentando en 5s...");
    setTimeout(iniciarSocketDashboard, 5000);
  };

  socketDashboard.onerror = (error) => {
    console.error("[Dashboard] Error en la conexión:", error);
    socketDashboard.close();
  };
}

function inicializarParticulas() {
  const canvas = document.getElementById("fondo-particulas");
  if (!canvas || !canvas.getContext) return;

  const ctx = canvas.getContext("2d");
  let particulas = [];

  function crearParticulas() {
    const cantidad = Math.min(160, Math.floor((canvas.width + canvas.height) / 20));
    particulas = Array.from({ length: cantidad }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      radio: Math.random() * 1.8 + 0.6,
      velocidadX: (Math.random() - 0.5) * 0.6,
      velocidadY: (Math.random() - 0.5) * 0.6,
      alpha: Math.random() * 0.4 + 0.1,
    }));
  }

  function redimensionar() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    crearParticulas();
  }

  function animar() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    particulas.forEach((p) => {
      p.x += p.velocidadX;
      p.y += p.velocidadY;

      if (p.x <= 0 || p.x >= canvas.width) p.velocidadX *= -1;
      if (p.y <= 0 || p.y >= canvas.height) p.velocidadY *= -1;

      ctx.beginPath();
      const gradiente = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.radio * 4);
      gradiente.addColorStop(0, `rgba(99, 245, 189, ${p.alpha})`);
      gradiente.addColorStop(1, "rgba(99, 245, 189, 0)");
      ctx.fillStyle = gradiente;
      ctx.arc(p.x, p.y, p.radio * 4, 0, Math.PI * 2);
      ctx.fill();
    });

    requestAnimationFrame(animar);
  }

  window.addEventListener("resize", redimensionar);
  redimensionar();
  animar();
}

function iniciarReloj() {
  actualizarSelloTemporal();
  setInterval(() => actualizarSelloTemporal(), 1000);
}

document.addEventListener("DOMContentLoaded", () => {
  inicializarParticulas();
  iniciarSocket();
  iniciarSocketDashboard();  // Nueva conexión para actualizaciones del dashboard
  iniciarReloj();
  refrescarPanel();  // Carga inicial
  // Reducir intervalo de refresco manual a 30 segundos como respaldo
  // Las actualizaciones principales vienen por WebSocket cada 10 segundos
  setInterval(refrescarPanel, 30_000);
});

