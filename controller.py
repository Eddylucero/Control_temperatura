import json
from flask import Flask, request, jsonify, render_template_string, flash, redirect, url_for, session
import mysql.connector
from datetime import datetime, timedelta
from collections import deque
import requests
import threading
from decimal import Decimal

# --- Configuración y Variables Globales ---
app = Flask(__name__)
app.secret_key = "tu_clave_secreta_muy_segura"

INVERNADEROS = {}
ALERT_TEMP = 25
DESTINATION_WHATSAPP = "593983388182"


USUARIOS = {
    "admin": "12345", 
    "usuario": "pass456"
}

def estado_suelo(humedad):
    """Determina el estado del suelo basado en el porcentaje de humedad."""
    if humedad is None:
        return "Sin datos"
    if humedad < 60:
        return "Seco"
    else:
        return "Húmedo"

def get_db():
    """Establece y retorna una conexión a la base de datos MySQL."""
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="admin",
        database="db_invernadero"
    )

def actualizar_invernaderos():
    """
    Actualiza la lista global de invernaderos desde la base de datos
    y sincroniza las estructuras de datos asociadas.
    """
    global INVERNADEROS, ultimas_lecturas, ultimos_estados, ultimas_alertas_temp
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, nombre FROM invernaderos ORDER BY id")
        invernaderos_db = cursor.fetchall()

        nuevos_invernaderos = {row['id']: row['nombre'] for row in invernaderos_db}

        nuevos_ids = set(nuevos_invernaderos.keys())
        ids_actuales = set(INVERNADEROS.keys())

        # Añadir nuevos invernaderos a las estructuras de seguimiento
        for id_nuevo in nuevos_ids - ids_actuales:
            ultimas_lecturas[id_nuevo] = None
            ultimos_estados[id_nuevo] = None
            ultimas_alertas_temp[id_nuevo] = False

        # Eliminar invernaderos que ya no existen en la DB
        for id_eliminar in ids_actuales - nuevos_ids:
            ultimas_lecturas.pop(id_eliminar, None)
            ultimos_estados.pop(id_eliminar, None)
            ultimas_alertas_temp.pop(id_eliminar, None)

        INVERNADEROS = nuevos_invernaderos

        print(f"INVERNADEROS actualizados: {INVERNADEROS}")

    except Exception as e:
        print(f"Error al actualizar INVERNADEROS desde la DB: {str(e)}")
        # En caso de error, inicializar vacías para evitar problemas
        INVERNADEROS = {}
        ultimas_lecturas = {}
        ultimos_estados = {}
        ultimas_alertas_temp = {}
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

lecturas_sensor = []
asignacion_activa = None
ultimas_lecturas = {}
ultimos_estados = {}
ultimas_alertas_temp = {}

# Inicializar los invernaderos al iniciar la aplicación
actualizar_invernaderos()

# --- Plantilla HTML Base ---
BASE_HTML = """
<!doctype html>
<html>
<head>
  <title>{{ title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
  <style>
    /* Estilos generales para la visualización en pantalla */
    body {
        font-family: 'Inter', sans-serif;
        background-color: #f8f9fa;
    }
    .dashboard-card {
      transition: all 0.3s;
      height: 100%;
    }
    .dashboard-card:hover {
      transform: scale(1.02);
      box-shadow: 0 0 15px rgba(0,0,0,0.2);
    }
    .card-title {
      font-size: 1.2rem;
      font-weight: bold;
    }
    .alert-row {
      transition: all 0.3s;
    }
    .alert-row:hover {
      background-color: #f8f9fa;
    }
    .critical-temp {
      color: #dc3545;
      font-weight: bold;
    }
    .chart-container {
      position: relative;
      height: 300px;
      width: 100%;
    }
    .text-danger { color: #dc3545; }
    .text-warning { color: #ffc107; }
    .text-primary { color: #0d6efd; }
    .text-success { color: #198754; }
    .badge.bg-danger { background-color: #dc3545; }
    .table-responsive {
      overflow-x: auto;
      max-height: 400px;
    }
    #tabla-lecturas tbody tr:first-child {
      background-color: rgba(13, 110, 253, 0.1);
    }
    .badge {
      font-size: 0.8rem;
    }

    #btn-actualizar:disabled {
      opacity: 0.6;
    }

    #tabla-lecturas tbody tr:first-child {
      background-color: rgba(13, 110, 253, 0.1);
      animation: fadeIn 0.5s ease-in;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    .card {
        border-radius: 0.75rem;
        border: none;
    }
    .card-header {
        border-bottom: 1px solid #e9ecef;
        background-color: #fff;
        border-top-left-radius: 0.75rem;
        border-top-right-radius: 0.75rem;
    }
    .table-hover tbody tr:hover {
        background-color: #f1f3f5;
    }
    .badge {
        padding: 0.5em 0.75em;
        font-size: 0.85em;
    }
    .avatar {
        width: 36px;
        height: 36px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.9em;
        font-weight: 600;
    }
    .avatar-initial {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .decision-tree {
        font-family: Arial, sans-serif;
        margin: 20px 0;
    }

    .node {
        display: flex;
        flex-direction: column;
        align-items: center;
        position: relative;
        margin: 0 10px;
    }

    .node-content {
        padding: 10px 15px;
        border-radius: 5px;
        margin-bottom: 10px;
        text-align: center;
        min-width: 200px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        transition: all 0.3s ease;
    }

    .node-content:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }

    .children {
        display: flex;
        justify-content: center;
        padding-top: 20px;
        position: relative;
    }

    .branch {
        display: flex;
        flex-direction: column;
        align-items: center;
        position: relative;
        padding: 0 20px;
    }

    .branch:before {
        content: '';
        position: absolute;
        top: 0;
        height: 20px;
        width: 1px;
        background-color: #ccc;
    }

    .leaf .node-content {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
    }

    .node.root {
        margin-top: 0;
    }

    .node.root .node-content {
        font-weight: bold;
        font-size: 1.1em;
    }

    /* Animaciones para el árbol */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .node {
        animation: fadeIn 0.5s ease-out;
    }

    /* Estilos para el modal */
    .modal-header {
        border-bottom: none;
        padding-bottom: 0;
    }

    .modal-body h5 {
        color: #0d6efd;
        margin-top: 1rem;
    }

    .modal-body ul, .modal-body ol {
        padding-left: 1.5rem;
    }

    .modal-body li {
        margin-bottom: 0.5rem;
    }

    .table-sm th, .table-sm td {
        padding: 0.5rem;
    }

    /* --- Estilos específicos para impresión (A4) --- */
    @media print {
        body {
            margin: 0;
            padding: 0;
            font-size: 10pt; /* Tamaño de fuente más pequeño para que quepa más contenido */
            -webkit-print-color-adjust: exact; /* Para imprimir colores de fondo */
            print-color-adjust: exact;
        }

        /* Ocultar elementos no esenciales para la impresión */
        .navbar, .btn, .carousel, .hero-section, .action-card,
        #btn-actualizar, .text-center a.btn-outline-primary,
        .modal-footer, .modal-header .btn-close,
        .d-flex.justify-content-between.align-items-center.mb-4 > div:last-child {
            display: none !important;
        }

        /* Mostrar títulos de sección que podrían estar ocultos en pantalla */
        h1, h2, h3, h4, h5 {
            page-break-after: avoid; /* Evita que los títulos se corten */
            margin-top: 1em;
            margin-bottom: 0.5em;
        }

        /* Asegurar que las tablas se ajusten y no se corten */
        table {
            width: 100%;
            border-collapse: collapse;
            page-break-inside: auto; /* Permite que las tablas se dividan entre páginas */
            margin-bottom: 1em;
        }
        thead {
            display: table-header-group; /* Repite el encabezado de la tabla en cada página */
        }
        tr {
            page-break-inside: avoid; /* Evita que las filas se dividan si es posible */
            page-break-after: auto;
        }
        td, th {
            border: 1px solid #dee2e6;
            padding: 5px; /* Reducir padding para más espacio */
            font-size: 9pt;
        }
        .table-responsive {
            overflow: visible !important; /* Asegurar que la tabla no tenga scroll en impresión */
            max-height: none !important;
        }

        /* Reducir márgenes y rellenos de las tarjetas y contenedores */
        .container-fluid, .container {
            width: 100% !important;
            max-width: none !important;
            padding: 0.5cm !important; /* Márgenes para impresión */
            margin: 0 !important;
        }
        .card {
            border: 1px solid #dee2e6 !important; /* Mantener bordes sutiles para estructura */
            box-shadow: none !important; /* Eliminar sombras para ahorrar tinta */
            margin-bottom: 1em !important;
            page-break-inside: avoid; /* Evita que las tarjetas se corten */
            border-radius: 0 !important; /* Eliminar bordes redondeados */
        }
        .card-header {
            background-color: #f0f0f0 !important; /* Fondo gris claro para encabezados */
            border-bottom: 1px solid #dee2e6 !important;
            border-radius: 0 !important;
        }
        .card-body {
            padding: 10px !important; /* Reducir padding */
        }

        /* Ajustar tamaño de gráficos (canvas) para impresión */
        canvas {
            max-width: 100% !important;
            height: auto !important; /* Permitir que la altura se ajuste al contenido */
            display: block;
            margin-left: auto;
            margin-right: auto;
        }
        .chart-container {
            height: auto !important;
        }

        /* Eliminar colores de fondo y ajustar colores de texto para legibilidad */
        .bg-light, .bg-primary, .bg-opacity-10, .bg-white, .bg-dark,
        .bg-success, .bg-warning, .bg-danger, .bg-info, .bg-secondary {
            background-color: transparent !important;
            color: #000 !important; /* Convertir colores a negro para mejor legibilidad */
        }
        .text-primary, .text-success, .text-warning, .text-danger, .text-info, .text-muted {
            color: #000 !important;
        }
        .critical-temp {
            color: #dc3545 !important; /* Mantener color para alertas críticas si se desea */
        }
        .badge {
            border: 1px solid #000; /* Añadir borde a los badges para que sean visibles */
            color: #000 !important;
            background-color: transparent !important;
            padding: 0.2em 0.5em;
            font-size: 8pt;
        }
        .list-group-item {
            border: 1px solid #dee2e6 !important;
            background-color: transparent !important;
            padding: 5px 10px;
            font-size: 9pt;
        }
        ul, ol {
            padding-left: 15px;
        }
        li {
            margin-bottom: 3px;
        }
    }
  </style>

</head>
<body class="bg-light">
  <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
    <div class="container">
      <a class="navbar-brand" href="/">
        <i class="bi bi-house-door-fill me-2"></i>
        Monitoreo Invernaderos
      </a>
    </div>
  </nav>

  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
        <div class="alert alert-info alert-dismissible fade show">
          {{ message }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    {{ content|safe }}
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    // Variables globales
    let tempChart, humChart;
    let lastHistorialUpdate = 0;
    const updateInterval = 120000; // 2 minutos
    const historialSyncInterval = 60000; // 60 segundos
    let isUpdating = false;

    // Función para determinar estado del suelo
    function determinarEstado(humedad) {
      if (humedad === undefined || humedad === null) return "Sin datos";
      if (humedad < 60) return "Seco";
      return "Húmedo";
    }

    // Función para obtener clase CSS del estado
    function getEstadoClass(estado) {
      if (estado.includes("Seco")) return "text-warning";
      return "text-primary";
    }

    // Función para actualizar el indicador de estado
    function actualizarEstado(conectado) {
      const indicator = document.getElementById('status-indicator');
      if (indicator) {
        if (conectado) {
          indicator.className = 'badge bg-success me-2';
          indicator.textContent = 'Conectado';
        } else {
          indicator.className = 'badge bg-danger me-2';
          indicator.textContent = 'Desconectado';
        }
      }
    }

    // Función para actualizar la tabla
    function actualizarTabla(datos) {
      const tbody = document.querySelector('#tabla-lecturas tbody');
      if (!tbody || !datos) return;

      const estado = determinarEstado(datos.humedad);
      const estadoClass = getEstadoClass(estado);
      const tempClass = datos.temperatura > {{ ALERT_TEMP }} ? 'critical-temp' : '';

      const newRow = document.createElement('tr');
      newRow.innerHTML = `
        <td>${datos.fecha}</td>
        <td class="${tempClass}">${datos.temperatura}</td>
        <td>${datos.humedad}</td>
        <td class="${estadoClass}">${estado}</td>
      `;

      tbody.insertBefore(newRow, tbody.firstChild);

      // Mantener máximo 10 filas
      if (tbody.children.length > 10) {
        tbody.removeChild(tbody.lastChild);
      }
    }

    // Función para actualizar gráficos
    function actualizarGraficos(nuevosDatos) {
      if (!nuevosDatos) return;

      const hora = nuevosDatos.fecha.split(' ')[1];

      // Actualizar gráfico de temperatura
      if (tempChart) {
        tempChart.data.labels.push(hora);
        tempChart.data.datasets[0].data.push(nuevosDatos.temperatura);

        if (tempChart.data.labels.length > 20) {
          tempChart.data.labels.shift();
          tempChart.data.datasets[0].data.shift();
        }
        tempChart.update('none'); // Animación más rápida
      }

      // Actualizar gráfico de humedad
      if (humChart) {
        humChart.data.labels.push(hora);
        humChart.data.datasets[0].data.push(nuevosDatos.humedad);

        if (humChart.data.labels.length > 20) {
          humChart.data.labels.shift();
          humChart.data.datasets[0].data.shift();
        }
        humChart.update('none'); // Animación más rápida
      }
    }

    // Función para cargar datos iniciales del historial
    async function cargarHistorialInicial() {
        try {
            // Obtener el ID del invernadero de la URL de manera más robusta
            const pathParts = window.location.pathname.split('/');
            const invernaderoId = pathParts[pathParts.length - 1];

            const response = await fetch(`/api/lecturas_historial/${invernaderoId}`);
            const data = await response.json();

            if (data && !data.error) {
                // Actualizar gráficos con datos históricos
                if (tempChart) {
                    tempChart.data.labels = data.labels.map(label => label.split(' ')[1]);
                    tempChart.data.datasets[0].data = data.temperatura;
                    tempChart.update('none');
                }

                if (humChart) {
                    humChart.data.labels = data.labels.map(label => label.split(' ')[1]);
                    humChart.data.datasets[0].data = data.humedad;
                    humChart.update('none');
                }
            }
        } catch (error) {
            console.error('Error al cargar historial:', error);
            actualizarEstado(false);
        }
    }

    // Función principal para obtener datos en tiempo real
    async function obtenerDatosRealtime() {
        if (isUpdating) return;
        isUpdating = true;

        try {
            // Obtener el ID del invernadero de la URL de manera más robusta
            const pathParts = window.location.pathname.split('/');
            const invernaderoId = pathParts[pathParts.length - 1];

            const response = await fetch(`/api/lecturas_realtime/${invernaderoId}`);
            const data = await response.json();

            if (data && !data.error) {
                actualizarTabla(data);
                actualizarGraficos(data);
                actualizarEstado(true);
            }

            // Sincronizar con historial completo periódicamente
            if (Date.now() - lastHistorialUpdate > historialSyncInterval) {
                await cargarHistorialInicial();
                lastHistorialUpdate = Date.now();
            }
        } catch (error) {
            console.error('Error al obtener datos:', error);
            actualizarEstado(false);
        } finally {
            isUpdating = false;
        }
    }

    // Inicialización de la página
    document.addEventListener('DOMContentLoaded', function() {
        // Obtener el ID del invernadero de la URL
        const pathParts = window.location.pathname.split('/');
        const invernaderoId = pathParts[pathParts.length - 1];

        // Verificar que estamos en una página de detalles de invernadero
        if (window.location.pathname.startsWith('/invernadero/') && invernaderoId) {
            // Inicializar gráficos si existen en la página
            const tempCtx = document.getElementById('tempChart')?.getContext('2d');
            const humCtx = document.getElementById('humChart')?.getContext('2d');

            if (tempCtx) {
                tempChart = new Chart(tempCtx, {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            label: 'Temperatura (°C)',
                            data: [],
                            borderColor: 'rgb(255, 99, 132)',
                            backgroundColor: 'rgba(255, 99, 132, 0.1)',
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: {
                            duration: 0
                        },
                        interaction: {
                            intersect: false,
                            mode: 'index'
                        },
                        scales: {
                            y: {
                                title: { display: true, text: 'Temperatura (°C)' }
                            }
                        }
                    }
                });
            }

            if (humCtx) {
                humChart = new Chart(humCtx, {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            label: 'Humedad (%)',
                            data: [],
                            borderColor: 'rgb(54, 162, 235)',
                            backgroundColor: 'rgba(54, 162, 235, 0.1)',
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: {
                            duration: 0
                        },
                        interaction: {
                            intersect: false,
                            mode: 'index'
                        },
                        scales: {
                            y: {
                                min: 0,
                                max: 100,
                                title: { display: true, text: 'Humedad (%)' }
                            }
                        }
                    }
                });
            }

            // Cargar datos iniciales y configurar actualización periódica
            cargarHistorialInicial();

            // Actualizar cada segundo
            setInterval(obtenerDatosRealtime, updateInterval);

            // Configurar evento para actualizar manualmente
            const btnActualizar = document.getElementById('btn-actualizar');
            if (btnActualizar) {
                btnActualizar.addEventListener('click', async () => {
                    btnActualizar.disabled = true;
                    btnActualizar.textContent = 'Actualizando...';

                    await obtenerDatosRealtime();
                    await cargarHistorialInicial();

                    btnActualizar.disabled = false;
                    btnActualizar.textContent = 'Actualizar Ahora';
                });
            }
        }
    });
    // Función para actualizar el listado de invernaderos
    function actualizarListadoInvernaderos() {
      const filas = document.querySelectorAll('tr[data-invernadero-id]');

      filas.forEach(async (fila) => {
        const invernaderoId = fila.getAttribute('data-invernadero-id');
        try {
          const response = await fetch(`/api/estado_invernadero/${invernaderoId}`);
          const data = await response.json();

          if (data && !data.error) {
            const tempCell = fila.querySelector('.temp-cell');
            const humCell = fila.querySelector('.hum-cell');
            const fechaCell = fila.querySelector('.fecha-cell');

            if (tempCell) {
              tempCell.textContent = `${data.temperatura} °C`;
              tempCell.className = data.alerta_temp ? 'temp-cell critical-temp' : 'temp-cell';
            }
            if (humCell) humCell.textContent = `${data.humedad} %`;
            if (fechaCell) fechaCell.textContent = data.fecha;
          }
        } catch (error) {
          console.error(`Error actualizando invernadero ${invernaderoId}:`, error);
        }
      });
    }

    // Inicializar actualización del listado si estamos en la página de invernaderos
    if (window.location.pathname === '/invernaderos') {
      setInterval(actualizarListadoInvernaderos, 5000); // Actualizar cada 5 segundos
    }
  </script>
</body>
</html>
"""

@app.route('/api/lectura', methods=['POST'])
def recibir_lectura():
    """
    Endpoint para recibir lecturas de sensores.
    Guarda la lectura y, si hay una asignación activa, la procesa.
    """
    global lecturas_sensor

    data = request.get_json()
    print("Datos recibidos del sensor:", data)

    if not all(k in data for k in ['temperatura', 'humedad_suelo']):
        return jsonify({"error": "Datos incompletos"}), 400

    nueva_lectura = {
        'fecha': datetime.now(),
        'temperatura': float(data['temperatura']),
        'humedad': int(data['humedad_suelo'])
    }

    lecturas_sensor.append(nueva_lectura)

    if asignacion_activa:
        asignar_lectura_automatica(asignacion_activa, nueva_lectura)

    return jsonify({"status": "success"}), 200

@app.route('/api/lecturas_historial/<int:invernadero_id>')
def lecturas_historial(invernadero_id):
    """
    Retorna las últimas 20 lecturas históricas para un invernadero específico.
    Utilizado para inicializar los gráficos al cargar la página de detalle.
    """
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT fecha, temperatura, humedad_suelo as humedad
            FROM lecturas
            WHERE invernadero_id = %s
            ORDER BY fecha DESC
            LIMIT 20
        """, (invernadero_id,))

        lecturas = cursor.fetchall()

        lecturas.reverse()

        return jsonify({
            'labels': [lectura['fecha'].strftime('%Y-%m-%d %H:%M') for lectura in lecturas],
            'temperatura': [lectura['temperatura'] for lectura in lecturas],
            'humedad': [lectura['humedad'] for lectura in lecturas]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

@app.route('/api/estado_invernadero/<int:invernadero_id>')
def estado_invernadero(invernadero_id):
    """
    Retorna la última lectura y el estado actual de un invernadero.
    Utilizado para actualizar el listado de invernaderos en tiempo real.
    """
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT temperatura, humedad_suelo as humedad, fecha
            FROM lecturas
            WHERE invernadero_id = %s
            ORDER BY fecha DESC LIMIT 1
        """, (invernadero_id,))

        resultado = cursor.fetchone()
        if resultado:
            return jsonify({
                'temperatura': float(resultado['temperatura']),
                'humedad': int(resultado['humedad']),
                'fecha': resultado['fecha'].strftime('%Y-%m-%d %H:%M'),
                'estado': estado_suelo(resultado['humedad']),
                'alerta_temp': resultado['temperatura'] > ALERT_TEMP
            })
        else:
            return jsonify({'error': 'No hay datos para este invernadero'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

@app.route('/')
def home():
    """Renderiza la página principal con las últimas alertas."""
    alertas_db = []
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT a.invernadero_id, a.tipo, a.descripcion, a.fecha,
                   i.nombre as nombre_invernadero, i.encargado
            FROM alertas a
            JOIN invernaderos i ON a.invernadero_id = i.id
            ORDER BY a.fecha DESC
            LIMIT 2
        """)
        alertas_db = cursor.fetchall()

    except Exception as e:
        flash(f"Error al obtener alertas: {str(e)}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    alertas_html = ""
    for alerta in alertas_db:
        if "TEMP" in alerta['tipo']:
            alert_class = "alert-warning"
            icon = "bi-thermometer-high"
            tipo_text = "Temperatura alta"
            unidad = "°C"
        else:
            alert_class = "alert-danger"
            icon = "bi-droplet-fill"
            tipo_text = "Suelo seco"
            unidad = "%"

        fecha_alerta = alerta['fecha']
        tiempo_transcurrido = datetime.now() - fecha_alerta
        minutos = int(tiempo_transcurrido.total_seconds() / 60)
        horas = int(minutos / 60)

        if horas > 24:
            dias = int(horas / 24)
            tiempo_text = f"Hace {dias} día{'s' if dias > 1 else ''}"
        elif horas > 0:
            tiempo_text = f"Hace {horas} hora{'s' if horas > 1 else ''}"
        else:
            tiempo_text = f"Hace {minutos} minuto{'s' if minutos > 1 else ''}"

        import re
        valor = re.search(r"(\d+\.?\d*)", alerta['descripcion'])
        valor_text = valor.group(1) if valor else "N/A"

        alertas_html += f"""
            <div class="alert {alert_class} d-flex align-items-center mb-3">
                <i class="bi {icon} me-3" style="font-size: 1.5rem;"></i>
                <div class="w-100">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <strong>{tipo_text} detectada</strong> en {alerta['nombre_invernadero']} (ID: {alerta['invernadero_id']}) - {valor_text}{unidad}
                        </div>
                        <span class="badge bg-dark ms-2">
                            <i class="bi bi-person-fill me-1"></i>{alerta['encargado']}
                        </span>
                    </div>
                    <div class="small text-muted">{tiempo_text}</div>
                </div>
            </div>
        """

    content = f"""
    <!-- Hero Section -->
    <div class="hero-section bg-primary text-white py-5 mb-5 rounded-3" style="
        background: linear-gradient(135deg, #0d6efd 0%, #0b5ed7 100%);
        box-shadow: 0 4px 20px rgba(13, 110, 253, 0.3);
    ">
        <div class="container py-4">
            <div class="row align-items-center">
                <div class="col-lg-7">
                    <h1 class="display-4 fw-bold mb-3">🌱 Monitoreo de Invernaderos Inteligente</h1>
                    <p class="lead mb-4">Sistema de monitoreo en tiempo real para optimizar el crecimiento de tus cultivos</p>
                    <div class="d-flex gap-3">
                        <a href="/invernaderos" class="btn btn-light btn-lg px-4">
                            <i class="bi bi-speedometer2 me-2"></i>Ver Invernaderos
                        </a>
                        <a href="/alertas" class="btn btn-outline-light btn-lg px-4">
                            <i class="bi bi-exclamation-triangle me-2"></i>Ver Alertas
                        </a>
                    </div>
                </div>

                <!-- Carrusel en lugar de imagen estática -->
                <div class="col-lg-5 d-none d-lg-block">
                    <div id="carouselInvernaderos" class="carousel slide" data-bs-ride="carousel">
                        <div class="carousel-inner rounded shadow">
                            <div class="carousel-item active">
                                <img src="static/img/image-1.png" class="d-block w-100" alt="Imagen 1" style="max-height: 250px; object-fit: cover;">
                            </div>
                            <div class="carousel-item">
                                <img src="static/img/home.png" class="d-block w-100" alt="Imagen 2" style="max-height: 250px; object-fit: cover;">
                            </div>
                            <div class="carousel-item">
                                <img src="static/img/image.png" class="d-block w-100" alt="Imagen 3" style="max-height: 250px; object-fit: cover;">
                            </div>
                            <div class="carousel-item">
                                <img src="static/img/image-2.png" class="d-block w-100" alt="Imagen 4" style="max-height: 250px; object-fit: cover;">
                            </div>
                            <div class="carousel-item">
                                <img src="static/img/image-3.png" class="d-block w-100" alt="Imagen 5" style="max-height: 250px; object-fit: cover;">
                            </div>
                            <div class="carousel-item">
                                <img src="static/img/image-4.png" class="d-block w-100" alt="Imagen 6" style="max-height: 250px; object-fit: cover;">
                            </div>
                            <div class="carousel-item">
                                <img src="static/img/image-5.png" class="d-block w-100" alt="Imagen 7" style="max-height: 250px; object-fit: cover;">
                            </div>
                        </div>
                        <!-- Controles opcionales -->
                        <button class="carousel-control-prev" type="button" data-bs-target="#carouselInvernaderos" data-bs-slide="prev">
                            <span class="carousel-control-prev-icon" aria-hidden="true"></span>
                            <span class="visually-hidden">Anterior</span>
                        </button>
                        <button class="carousel-control-next" type="button" data-bs-target="#carouselInvernaderos" data-bs-slide="next">
                            <span class="carousel-control-next-icon" aria-hidden="true"></span>
                            <span class="visually-hidden">Siguiente</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Stats Cards -->
    <div class="row mb-5 g-4">
        <div class="col-md-4">
            <div class="card border-0 shadow-sm h-100">
                <div class="card-body text-center p-4">
                    <div class="bg-primary bg-opacity-10 rounded-circle p-3 mb-3 mx-auto" style="width: 70px; height: 70px;">
                        <i class="bi bi-thermometer-half text-primary" style="font-size: 1.8rem;"></i>
                    </div>
                    <h3 class="h5">Monitoreo en Tiempo Real</h3>
                    <p class="text-muted mb-0">Datos precisos de temperatura y humedad actualizados cada minuto</p>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card border-0 shadow-sm h-100">
                <div class="card-body text-center p-4">
                    <div class="bg-warning bg-opacity-10 rounded-circle p-3 mb-3 mx-auto" style="width: 70px; height: 70px;">
                        <i class="bi bi-bell-fill text-warning" style="font-size: 1.8rem;"></i>
                    </div>
                    <h3 class="h5">Alertas Inmediatas</h3>
                    <p class="text-muted mb-0">Notificaciones instantáneas cuando los parámetros salen de rango</p>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card border-0 shadow-sm h-100">
                <div class="card-body text-center p-4">
                    <div class="bg-success bg-opacity-10 rounded-circle p-3 mb-3 mx-auto" style="width: 70px; height: 70px;">
                        <i class="bi bi-graph-up-arrow text-success" style="font-size: 1.8rem;"></i>
                    </div>
                    <h3 class="h5">Histórico de Datos</h3>
                    <p class="text-muted mb-0">Acceso a gráficos históricos para análisis de tendencias</p>
                </div>
            </div>
        </div>
    </div>

    <!-- Quick Actions -->
    <div class="card shadow-sm mb-5">
        <div class="card-header bg-white border-bottom-0 pb-0">
            <h2 class="h4 mb-0">Acciones Rápidas</h2>
        </div>
        <div class="card-body pt-0">
            <div class="row g-3">
                <div class="col-md-3">
                    <a href="/invernaderos" class="card action-card h-100 text-decoration-none">
                        <div class="card-body text-center">
                            <i class="bi bi-house-door text-primary mb-2" style="font-size: 2rem;"></i>
                            <h5 class="mb-1">Invernaderos</h5>
                            <p class="text-muted small mb-0">Ver todos los invernaderos</p>
                        </div>
                    </a>
                </div>
                <div class="col-md-3">
                    <a href="/alertas" class="card action-card h-100 text-decoration-none">
                        <div class="card-body text-center">
                            <i class="bi bi-exclamation-octagon text-danger mb-2" style="font-size: 2rem;"></i>
                            <h5 class="mb-1">Alertas</h5>
                            <p class="text-muted small mb-0">Ver alertas recientes</p>
                        </div>
                    </a>
                </div>
                <div class="col-md-3">
                    <a href="/analisis-comparativo" class="card action-card h-100 text-decoration-none">
                        <div class="card-body text-center">
                            <i class="bi bi-file-earmark-bar-graph text-info mb-2" style="font-size: 2rem;"></i>
                            <h5 class="mb-1">Reportes</h5>
                            <p class="text-muted small mb-0">Generar reportes</p>
                        </div>
                    </a>
                </div>
                <div class="col-md-3">
                    <a href="/login" class="card action-card h-100 text-decoration-none">
                        <div class="card-body text-center">
                            <i class="bi bi-gear text-secondary mb-2" style="font-size: 2rem;"></i>
                            <h5 class="mb-1">Configuración</h5>
                            <p class="text-muted small mb-0">Ajustes del sistema</p>
                        </div>
                    </a>
                </div>
            </div>
        </div>
    </div>

    <!-- Recent Alerts from DB -->
    <div class="card shadow-sm">
        <div class="card-header bg-white">
            <h2 class="h4 mb-0">Últimas Alertas</h2>
        </div>
        <div class="card-body">
            {alertas_html if alertas_db else '<div class="alert alert-info">No hay alertas recientes</div>'}
            <div class="text-center">
                <a href="/alertas" class="btn btn-outline-primary">Ver todas las alertas</a>
            </div>
        </div>
    </div>

    <style>
        .hero-section {{
            position: relative;
            overflow: hidden;
        }}

        .hero-section::after {{
            content: "";
            position: absolute;
            top: -50%;
            right: -50%;
            width: 100%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 70%);
            transform: rotate(30deg);
        }}

        .action-card {{
            transition: all 0.3s ease;
            border: 1px solid rgba(0,0,0,0.05);
        }}

        .action-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        }}

        .dashboard-card {{
            transition: all 0.3s;
            height: 100%;
        }}

        .dashboard-card:hover {{
            transform: scale(1.02);
            box-shadow: 0 0 15px rgba(0,0,0,0.2);
        }}

        .alert .badge {{
            font-size: 0.8rem;
            padding: 0.35em 0.65em;
        }}
    </style>
    """
    return render_template_string(BASE_HTML, title="Panel Principal", content=content)

@app.route('/invernaderos')
def listar_invernaderos():
    """Renderiza la página que lista todos los invernaderos con sus datos más recientes."""
    def get_color_from_id(invernadero_id):
        colors = [
            'primary', 'secondary', 'success', 'danger', 'warning', 'info',
            'dark', 'primary', 'secondary', 'success', 'danger', 'warning'
        ]
        return colors[invernadero_id % len(colors)]

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT i.id, i.nombre, i.cantidad_claveles, i.encargado,
                   (SELECT temperatura FROM lecturas WHERE invernadero_id = i.id ORDER BY fecha DESC LIMIT 1) as temperatura,
                   (SELECT humedad_suelo FROM lecturas WHERE invernadero_id = i.id ORDER BY fecha DESC LIMIT 1) as humedad,
                   (SELECT fecha FROM lecturas WHERE invernadero_id = i.id ORDER BY fecha DESC LIMIT 1) as fecha
            FROM invernaderos i
            ORDER BY i.id
        """)

        invernaderos_db = cursor.fetchall()

        if not invernaderos_db:
            flash("No hay invernaderos registrados", "info")
            return render_template_string(BASE_HTML, title="Invernaderos", content="<div class='alert alert-info'>No hay invernaderos registrados</div>")

        ultimos_datos = {}
        for invernadero in invernaderos_db:
            invernadero_id = invernadero['id']

            ultimos_datos[invernadero_id] = {
                "nombre": invernadero['nombre'],
                "temperatura": float(invernadero['temperatura']) if invernadero['temperatura'] is not None else None,
                "humedad": int(invernadero['humedad']) if invernadero['humedad'] is not None else None,
                "fecha": invernadero['fecha'].strftime('%Y-%m-%d %H:%M') if invernadero['fecha'] else "Sin datos",
                "estado": estado_suelo(invernadero['humedad']) if invernadero['humedad'] is not None else "Sin datos",
                "cantidad_claveles": invernadero['cantidad_claveles'] if invernadero['cantidad_claveles'] is not None else 0,
                "encargado": invernadero['encargado'] if invernadero['encargado'] else "No asignado"
            }

    except Exception as e:
        flash(f"Error al obtener datos: {str(e)}", "danger")
        return render_template_string(BASE_HTML, title="Error", content=f"<div class='alert alert-danger'>Error al cargar los datos: {str(e)}</div>")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    cards = """
    <div class="card mb-4">
      <div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">
        <h3 class="mb-0">Listado de Invernaderos</h3>
        <span class="badge bg-light text-dark">Total: {}</span>
      </div>
      <div class="card-body">
        <div class="row row-cols-1 row-cols-md-2 row-cols-lg-3 g-4">
    """.format(len(ultimos_datos))

    for invernadero_id, datos in ultimos_datos.items():
        color_badge = get_color_from_id(invernadero_id)
        temp = datos.get('temperatura')
        hum = datos.get('humedad')

        temp_class = 'text-danger' if temp is not None and temp > ALERT_TEMP else 'text-dark'
        hum_class = 'text-warning' if datos.get('estado') == "Seco" else 'text-success'
        card_border = 'border-danger' if temp is not None and temp > ALERT_TEMP else ''

        temp_icon = 'bi-thermometer-high' if temp is not None and temp > ALERT_TEMP else 'bi-thermometer-half'
        hum_icon = 'bi-droplet' if datos.get('estado') == "Húmedo" else 'bi-droplet-fill'

        temp_display = f"{temp} °C" if temp is not None else 'N/A'
        hum_display = f"{hum} %" if hum is not None else 'N/A'
        estado_display = datos.get('estado', 'Sin datos')
        claveles_display = "{:,}".format(datos.get('cantidad_claveles', 0)).replace(",", ".")
        encargado_display = datos.get('encargado', 'No asignado')
        nombre_invernadero = datos.get('nombre', f"Invernadero {invernadero_id}")

        cards += f"""
          <div class="col" data-invernadero-id="{invernadero_id}">
            <div class="card dashboard-card h-100 {card_border}">
              <div class="card-header bg-light">
                <h5 class="card-title mb-0 d-flex justify-content-between">
                  <span>{nombre_invernadero}</span>
                  <span class="badge bg-{color_badge}"> {invernadero_id}</span>
                </h5>
              </div>
              <div class="card-body">
                <h4 class="card-title text-center mb-4">Invernadero {invernadero_id}</h4>

                <div class="row mb-3">
                  <div class="col-md-6">
                    <div class="d-flex align-items-center mb-2">
                      <i class="bi bi-person-fill me-2 text-secondary"></i>
                      <span class="text-muted">Encargado:</span>
                    </div>
                    <p class="ms-4">{encargado_display}</p>
                  </div>
                  <div class="col-md-6">
                    <div class="d-flex align-items-center mb-2">
                      <i class="bi bi-flower1 me-2 text-success"></i>
                      <span class="text-muted">Claveles:</span>
                    </div>
                    <p class="ms-4">{claveles_display} plantas</p>
                  </div>
                </div>

                <hr>

                <div class="d-flex justify-content-between mb-3">
                  <div>
                    <i class="bi {temp_icon} me-2 {temp_class}"></i>
                    <span class="{temp_class}">{temp_display}</span>
                  </div>
                  <div>
                    <span class="text-muted">Última lectura:</span>
                    <span class="ms-2">{datos.get('fecha', 'Sin datos')}</span>
                  </div>
                </div>

                <div class="progress mb-3" style="height: 10px;">
                  <div class="progress-bar bg-danger" role="progressbar"
                       style="width: {min(100, (temp/40)*100) if temp is not None else 0}%"
                       aria-valuenow="{temp if temp is not None else 0}"
                       aria-valuemin="0"
                       aria-valuemax="40"></div>
                </div>

                <div class="d-flex justify-content-between mb-3">
                  <div>
                    <i class="bi {hum_icon} me-2 {hum_class}"></i>
                    <span class="{hum_class}">{hum_display}</span>
                  </div>
                  <div>
                    <span class="text-muted">Estado:</span>
                    <span class="ms-2 badge {hum_class.replace('text-', 'bg-')}">{estado_display}</span>
                  </div>
                </div>

                <div class="progress mb-4" style="height: 10px;">
                  <div class="progress-bar bg-info" role="progressbar"
                       style="width: {hum if hum is not None else 0}%"
                       aria-valuenow="{hum if hum is not None else 0}"
                       aria-valuemin="0"
                       aria-valuemax="100"></div>
                </div>

                <div class="text-center">
                  <a href="/invernadero/{invernadero_id}" class="btn btn-outline-primary stretched-link">
                    <i class="bi bi-speedometer2 me-2"> Monitorear</i>
                  </a>
                </div>
              </div>
            </div>
          </div>
        """

    cards += """
        </div>
      </div>
    </div>

    <style>
      .card-title {
        position: relative;
      }
      .stretched-link::after {
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        left: 0;
        z-index: 1;
        content: "";
      }
      .progress {
        border-radius: 10px;
        background-color: #e9ecef;
      }
      .progress-bar {
        border-radius: 10px;
      }
      .dashboard-card {
        transition: transform 0.3s, box-shadow 0.3s;
      }
      .dashboard-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 10px 20px rgba(0,0,0,0.1);
      }
    </style>
    """

    return render_template_string(
        BASE_HTML,
        title="Invernaderos",
        content=cards
    )

@app.route('/invernadero/<int:invernadero_id>')
def detalle_invernadero(invernadero_id):
    """
    Renderiza la página de detalle de un invernadero específico,
    mostrando lecturas recientes y gráficos en tiempo real.
    """
    global asignacion_activa

    if invernadero_id not in INVERNADEROS:
        flash("Invernadero no encontrado")
        return redirect(url_for('listar_invernaderos'))

    asignacion_activa = invernadero_id
    print(f"Asignación automática activada para {INVERNADEROS[invernadero_id]}")

    lecturas = []
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT fecha, temperatura, humedad_suelo as humedad
            FROM lecturas
            WHERE invernadero_id = %s
            ORDER BY fecha DESC
            LIMIT 10
        """, (invernadero_id,))
        lecturas = cursor.fetchall()
    except Exception as e:
        flash(f"Error al obtener datos: {str(e)}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    tabla_lecturas = f"""
    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h3 class="mb-0">Lecturas Recientes - {INVERNADEROS.get(invernadero_id, f"Invernadero {invernadero_id}")} ({invernadero_id})</h3>
        <button id="btn-actualizar" class="btn btn-sm btn-outline-primary">Actualizar Ahora</button>
      </div>
      <div class="card-body">
        <div class="table-responsive">
          <table id="tabla-lecturas" class="table table-hover">
            <thead>
              <tr>
                <th>Fecha/Hora</th>
                <th>Temperatura (°C)</th>
                <th>Humedad (%)</th>
                <th>Estado del suelo</th>
              </tr>
            </thead>
            <tbody>
    """

    for lectura in lecturas:
        temp_class = 'critical-temp' if lectura['temperatura'] > ALERT_TEMP else ''
        estado = estado_suelo(lectura['humedad'])
        estado_class = 'text-warning' if estado == "Seco" else 'text-primary'

        tabla_lecturas += f"""
              <tr>
                <td>{lectura['fecha'].strftime('%Y-%m-%d %H:%M')}</td>
                <td class="{temp_class}">{lectura['temperatura']}</td>
                <td>{lectura['humedad']}</td>
                <td class="{estado_class}">{estado}</td>
              </tr>
        """

    tabla_lecturas += """
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """

    exit_script = """
    <script>
    window.addEventListener('beforeunload', function() {
        fetch('/api/desactivar_asignacion', {
            method: 'POST'
        });
    });
    </script>
    """

    content = f"""
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2>{INVERNADEROS.get(invernadero_id, f"Invernadero {invernadero_id}")} ({invernadero_id})</h2>
      <div>
        <span id="status-indicator" class="badge bg-success me-2">Conectado</span>
        <a href="/invernaderos" class="btn btn-outline-secondary"> <i class="bi bi-arrow-left">Volver</i></a>
      </div>
    </div>

    <div class="row mb-4">
      <div class="col-md-6">
        <div class="card">
          <div class="card-header">
            <h4 class="mb-0">Temperatura</h4>
          </div>
          <div class="card-body">
            <div class="chart-container">
              <canvas id="tempChart"></canvas>
            </div>
          </div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="card">
          <div class="card-header">
            <h4 class="mb-0">Humedad del Suelo</h4>
          </div>
          <div class="card-body">
            <div class="chart-container">
              <canvas id="humChart"></canvas>
            </div>
          </div>
        </div>
      </div>
    </div>

    {tabla_lecturas}
    {exit_script}
    """

    return render_template_string(
        BASE_HTML,
        title=f"Detalles - {INVERNADEROS.get(invernadero_id, f'Invernadero {invernadero_id}')}",
        content=content,
        ALERT_TEMP=ALERT_TEMP
    )

@app.route('/api/desactivar_asignacion', methods=['POST'])
def desactivar_asignacion():
    """Desactiva la asignación automática de lecturas a un invernadero."""
    global asignacion_activa
    asignacion_activa = None
    print("Asignación automática desactivada")
    return jsonify({"status": "success"}), 200

@app.route('/api/lecturas_realtime/<int:invernadero_id>')
def lecturas_realtime(invernadero_id):
    """
    Retorna la última lectura de un invernadero para actualizaciones en tiempo real.
    """
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT fecha, temperatura, humedad_suelo as humedad
            FROM lecturas
            WHERE invernadero_id = %s
            ORDER BY fecha DESC
            LIMIT 1
        """, (invernadero_id,))

        resultado = cursor.fetchone()
        if resultado:
            ultimas_lecturas[invernadero_id] = {
                'fecha': resultado['fecha'],
                'temperatura': float(resultado['temperatura']),
                'humedad': int(resultado['humedad'])
            }

            return jsonify({
                'fecha': resultado['fecha'].strftime('%Y-%m-%d %H:%M'),
                'temperatura': float(resultado['temperatura']),
                'humedad': int(resultado['humedad']),
                'estado': estado_suelo(resultado['humedad'])
            })
        else:
            return jsonify({'error': 'No hay datos disponibles para este invernadero'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

@app.route('/alertas')
def alertas():
    """Renderiza la página que muestra un listado de alertas recientes."""
    alertas_db = []
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT invernadero_id, tipo, descripcion, fecha
            FROM alertas
            ORDER BY fecha DESC
            LIMIT 50
        """)
        alertas_db = cursor.fetchall()

    except Exception as e:
        flash(f"Error al obtener alertas: {str(e)}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    tabla = """
    <div class="card mb-4">
      <div class="card-header bg-danger text-white">
        <h3 class="mb-0">Alertas Recientes</h3>
      </div>
      <div class="card-body">
        <div class="table-responsive">
          <table class="table table-hover">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Invernadero</th>
                <th>Tipo</th>
                <th>Descripción</th>
              </tr>
            </thead>
            <tbody>
    """

    for alerta in alertas_db:
        nombre_invernadero = INVERNADEROS.get(alerta['invernadero_id'], f"Invernadero {alerta['invernadero_id']}")
        tabla += f"""
              <tr>
                <td>{alerta['fecha'].strftime('%Y-%m-%d %H:%M')}</td>
                <td>{nombre_invernadero}</td>
                <td><span class="badge bg-danger">{alerta['tipo']}</span></td>
                <td>{alerta['descripcion']}</td>
              </tr>
        """
    tabla += """
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """

    return render_template_string(
        BASE_HTML,
        title="Alertas",
        content=tabla
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Maneja el inicio de sesión de usuarios administradores."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username in USUARIOS and USUARIOS[username] == password:
            session['logged_in'] = True
            flash('Inicio de sesión exitoso', 'success')
            return redirect(url_for('gestion_invernaderos'))
        else:
            flash('Credenciales inválidas. Inténtalo de nuevo.', 'danger')

    content = """
    <div class="container-fluid px-4">
        <div class="row justify-content-center mt-5">
            <div class="col-md-5">
                <div class="card shadow-lg border-0 rounded-lg mt-5">
                    <div class="card-header bg-success text-white text-center py-4">
                        <h3 class="fw-light my-0">
                            Bienvenido Admin
                        </h3>
                    </div>
                    <div class="card-body p-4">
                        <div class="text-center mb-4">
                            <img src="static/img/icon-log.png" alt="Invernadero" class="img-fluid border rounded" style="max-height: 250px;">
                        </div>

                        <form method="POST">
                            <div class="form-floating mb-3">
                                <input class="form-control" id="inputUsername" type="text" name="username" placeholder="Usuario" required />
                                <label for="inputUsername">Usuario</label>
                            </div>
                            <div class="form-floating mb-3">
                                <input class="form-control" id="inputPassword" type="password" name="password" placeholder="Contraseña" required />
                                <label for="inputPassword">Contraseña</label>
                            </div>
                            <div class="d-flex align-items-center justify-content-between mt-4 mb-0">
                                <button type="submit" class="btn btn-primary btn-lg w-100">
                                    <i class="bi bi-box-arrow-in-right me-2"></i>Iniciar Sesión
                                </button>
                            </div>
                        </form>
                    </div>
                    <div class="card-footer text-center py-3">
                        <div class="small">
                            <a href="/">Volver a la página principal</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <style>
        .card-header {
            border-bottom: 0;
            border-top-left-radius: 0.75rem;
            border-top-right-radius: 0.75rem;
        }
        .form-floating > label {
            padding: 1rem 1.25rem;
        }
        .form-control {
            padding: 1rem 1.25rem;
            border-radius: 0.5rem;
        }
        img.img-fluid.border.rounded {
            border: 2px solid #dee2e6;
            border-radius: 1rem;
        }
    </style>
    """
    return render_template_string(BASE_HTML, title="Iniciar Sesión", content=content)

@app.route('/logout')
def logout():
    """Cierra la sesión del usuario."""
    session.pop('logged_in', None)
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('home'))

@app.route('/gestion-invernaderos')
def gestion_invernaderos():
    """
    Renderiza la página de gestión de invernaderos,
    permitiendo ver, editar y eliminar invernaderos.
    Requiere inicio de sesión.
    """
    if not session.get('logged_in'):
        flash('Debes iniciar sesión para acceder a esta página.', 'warning')
        return redirect(url_for('login'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM invernaderos ORDER BY id")
        invernaderos = cursor.fetchall()

    except Exception as e:
        flash(f"Error al obtener invernaderos: {str(e)}", "danger")
        invernaderos = []
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    tabla_html = """
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

    <div class="container-fluid px-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mt-4"></i>Gestión de Invernaderos</h1>
            <a href="/agregar-invernadero" class="btn btn-outline-primary shadow-sm">
                <i class="bi bi-plus-circle me-2"></i>Nuevo Invernadero
            </a>
        </div>

        <div class="card shadow-sm border-0">
            <div class="card-body p-0">
    """

    if not invernaderos:
        tabla_html += """
                <div class="text-center py-5">
                    <i class="bi bi-building text-muted" style="font-size: 5rem;"></i>
                    <h3 class="mt-3">No hay invernaderos registrados</h3>
                    <p class="text-muted">Comienza agregando tu primer invernadero</p>
                    <a href="/agregar-invernadero" class="btn btn-primary px-4">
                        <i class="bi bi-plus-circle me-2"></i>Agregar Invernadero
                    </a>
                </div>
        """
    else:
        tabla_html += """
                <div class="table-responsive">
                    <table class="table table-hover align-middle">
                        <thead class="table-light">
                            <tr>
                                <th style="width: 80px;">ID</th>
                                <th>Invernadero</th>
                                <th class="text-center">Claveles</th>
                                <th>Encargado</th>
                                <th class="text-center">Acciones</th>
                            </tr>
                        </thead>
                        <tbody>
        """

        for inv in invernaderos:
            tabla_html += f"""
                            <tr>
                                <td>
                                    <span class="badge rounded-pill bg-primary bg-opacity-10 text-primary fs-6">
                                        {inv['id']}
                                    </span>
                                </td>
                                <td>
                                    <div class="d-flex align-items-center">
                                        <div>
                                            <h6 class="mb-0">{inv['nombre']}</h6>
                                        </div>
                                    </div>
                                </td>
                                <td class="text-center">
                                    <span class="badge bg-success bg-opacity-10 text-success">
                                        <i class="bi bi-flower1 me-1"></i>
                                        {inv['cantidad_claveles']:,}
                                    </span>
                                </td>
                                <td>
                                    <div class="d-flex align-items-center">
                                        <span>{inv['encargado'] or 'No asignado'}</span>
                                    </div>
                                </td>
                                <td class="text-center">
                                    <div class="d-flex justify-content-center gap-2">
                                        <a href="/editar-invernadero/{inv['id']}" class="btn btn-sm btn-outline-secondary rounded-pill"
                                           data-bs-toggle="tooltip" data-bs-title="Editar">
                                            <i class="bi bi-pencil-square"></i>
                                        </a>
                                        <button class="btn btn-sm btn-outline-danger rounded-pill"
                                                onclick="confirmarEliminacion({inv['id']}, '{inv['nombre']}')"
                                                data-bs-toggle="tooltip" data-bs-title="Eliminar">
                                            <i class="bi bi-trash"></i>
                                        </button>
                                    </div>
                                </td>
                            </tr>
            """

        tabla_html += """
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    """

    tabla_html += """
    </div>

    <!-- Modal de confirmación -->
    <div class="modal fade" id="confirmModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow">
                <div class="modal-header border-0">
                    <h5 class="modal-title text-danger"><i class="bi bi-exclamation-triangle-fill me-2"></i>Confirmar Eliminación</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body py-4">
                    <div class="d-flex flex-column align-items-center text-center">
                        <i class="bi bi-trash-fill text-danger mb-3" style="font-size: 3rem;"></i>
                        <h5 id="modalMessage">¿Estás seguro de eliminar este invernadero?</h5>
                        <p class="text-muted">Esta acción no se puede deshacer.</p>
                    </div>
                </div>
                <div class="modal-footer border-0 justify-content-center">
                    <button type="button" class="btn btn-outline-secondary px-4 rounded-pill" data-bs-dismiss="modal">Cancelar</button>
                    <a id="deleteBtn" href="#" class="btn btn-outline-danger px-4 rounded-pill">
                        <i class="bi bi-trash-fill me-2"></i>Eliminar
                    </a>
                </div>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
            const tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
                return new bootstrap.Tooltip(tooltipTriggerEl)
            })
        })

        function confirmarEliminacion(id, nombre) {
            document.getElementById('modalMessage').innerHTML = `¿Estás seguro de eliminar el invernadero <strong>${nombre}</strong>?`
            document.getElementById('deleteBtn').href = '/eliminar-invernadero/' + id
            const modal = new bootstrap.Modal(document.getElementById('confirmModal'))
            modal.show()
        }
    </script>

    <style>
        .table td, .table th {
            vertical-align: middle;
            padding: 12px;
        }
        .badge {
            padding: 5px 10px;
            font-weight: 500;
        }
        .card {
            border-radius: 12px;
            overflow: hidden;
        }
        .btn {
            transition: all 0.2s;
        }
        .btn-sm {
            padding: 0.35rem 0.75rem;
        }
        .rounded-pill {
            border-radius: 50px !important;
        }
    </style>
    """

    return render_template_string(
        BASE_HTML,
        title="Gestión de Invernaderos",
        content=tabla_html
    )

@app.route('/agregar-invernadero', methods=['GET', 'POST'])
def agregar_invernadero():
    """
    Maneja la adición de un nuevo invernadero a la base de datos.
    Requiere inicio de sesión.
    """
    if not session.get('logged_in'):
        flash('Debes iniciar sesión para acceder a esta página.', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            nombre = request.form['nombre']
            cantidad_claveles = request.form['cantidad_claveles']
            encargado = request.form['encargado']

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO invernaderos (nombre, cantidad_claveles, encargado)
                VALUES (%s, %s, %s)
            """, (nombre, cantidad_claveles, encargado))

            conn.commit()
            actualizar_invernaderos() # Actualizar la lista global de invernaderos
            flash("Invernadero agregado correctamente", "success")
            return redirect('/gestion-invernaderos')

        except Exception as e:
            flash(f"Error al agregar invernadero: {str(e)}", "danger")
        finally:
            if 'conn' in locals() and conn.is_connected():
                conn.close()

    form_html = """
    <div class="container-fluid px-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mt-4"></i>Agregar Invernadero</h1>
            <a href="/gestion-invernaderos" class="btn btn-outline-secondary">
                <i class="bi bi-arrow-left me-2"></i>Volver
            </a>
        </div>

        <div class="card shadow-sm border-0">
            <div class="card-body p-4">
                <form method="POST">
                    <div class="row g-3">
                        <div class="col-md-6">
                            <div class="form-floating mb-3">
                                <input type="text" class="form-control" id="nombre" name="nombre"
                                       placeholder="Nombre del invernadero" required>
                                <label for="nombre">Nombre del Invernadero</label>
                            </div>
                        </div>

                        <div class="col-md-6">
                            <div class="form-floating mb-3">
                                <input type="number" class="form-control" id="cantidad_claveles" name="cantidad_claveles"
                                       placeholder="Cantidad de claveles" min="0" required>
                                <label for="cantidad_claveles">Cantidad de Claveles</label>
                            </div>
                        </div>

                        <div class="col-12">
                            <div class="form-floating mb-4">
                                <input type="text" class="form-control" id="encargado" name="encargado"
                                       placeholder="Nombre del encargado" required>
                                <label for="encargado">Encargado</label>
                            </div>
                        </div>

                        <div class="col-12">
                            <div class="d-flex justify-content-end gap-3 pt-2">
                                <a href="/gestion-invernaderos" class="btn btn-outline-secondary px-4">
                                    <i class="bi bi-x-lg me-2"></i>Cancelar
                                </a>
                                <button type="submit" class="btn btn-outline-primary px-4">
                                    <i class="bi bi-check-lg me-2"></i>Guardar Invernadero
                                </button>
                            </div>
                        </div>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <style>
        .form-floating>label {
            padding: 1rem 1.25rem;
        }
        .form-control {
            padding: 1rem 1.25rem;
            border-radius: 8px;
        }
        .form-control:focus {
            box-shadow: 0 0 0 0.25rem rgba(13, 110, 253, 0.15);
        }
    </style>
    """

    return render_template_string(BASE_HTML, title="Agregar Invernadero", content=form_html)

@app.route('/editar-invernadero/<int:id>', methods=['GET', 'POST'])
def editar_invernadero(id):
    """
    Maneja la edición de un invernadero existente.
    Requiere inicio de sesión.
    """
    if not session.get('logged_in'):
        flash('Debes iniciar sesión para acceder a esta página.', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            nombre = request.form['nombre']
            cantidad_claveles = request.form['cantidad_claveles']
            encargado = request.form['encargado']

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE invernaderos
                SET nombre = %s, cantidad_claveles = %s, encargado = %s
                WHERE id = %s
            """, (nombre, cantidad_claveles, encargado, id))

            conn.commit()
            actualizar_invernaderos() # Actualizar la lista global de invernaderos
            flash("Invernadero actualizado correctamente", "success")
            return redirect('/gestion-invernaderos')

        except Exception as e:
            flash(f"Error al actualizar invernadero: {str(e)}", "danger")
        finally:
            if 'conn' in locals() and conn.is_connected():
                conn.close()

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM invernaderos WHERE id = %s", (id,))
        invernadero = cursor.fetchone()

        if not invernadero:
            flash("Invernadero no encontrado", "danger")
            return redirect('/gestion-invernaderos')

    except Exception as e:
        flash(f"Error al obtener datos del invernadero: {str(e)}", "danger")
        return redirect('/gestion-invernaderos')
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    form_html = f"""
    <div class="container-fluid px-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mt-4">
                <i class="bi bi-building me-2"></i>
                Editar Invernadero <span class="text-primary">#{invernadero['id']}</span>
            </h1>
            <a href="/gestion-invernaderos" class="btn btn-outline-secondary">
                <i class="bi bi-arrow-left me-2"></i>Volver
            </a>
        </div>

        <div class="card shadow-sm border-0">
            <div class="card-header bg-white border-0 py-3">
                <div class="d-flex align-items-center">
                    <div class="avatar avatar-lg me-3">
                        <span class="avatar-initial rounded-circle bg-primary bg-opacity-10 text-primary fs-4">
                            <i class="bi bi-building"></i>
                        </span>
                    </div>
                    <div>
                        <h5 class="mb-0">{invernadero['nombre']}</h5>
                    </div>
                </div>
            </div>

            <div class="card-body p-4">
                <form method="POST">
                    <div class="row g-3">
                        <div class="col-md-6">
                            <div class="form-floating mb-3">
                                <input type="text" class="form-control" id="nombre" name="nombre"
                                       value="{invernadero['nombre']}" placeholder="Nombre del invernadero" required>
                                <label for="nombre">Nombre del Invernadero</label>
                            </div>
                        </div>

                        <div class="col-md-6">
                            <div class="form-floating mb-3">
                                <input type="number" class="form-control" id="cantidad_claveles" name="cantidad_claveles"
                                       value="{invernadero['cantidad_claveles']}" placeholder="Cantidad de claveles" min="0" required>
                                <label for="cantidad_claveles">Cantidad de Claveles</label>
                            </div>
                        </div>

                        <div class="col-12">
                            <div class="form-floating mb-4">
                                <input type="text" class="form-control" id="encargado" name="encargado"
                                       value="{invernadero['encargado']}" placeholder="Nombre del encargado" required>
                                <label for="encargado">Encargado</label>
                            </div>
                        </div>

                        <div class="col-12">
                            <div class="d-flex justify-content-end gap-3 pt-2">
                                <a href="/gestion-invernaderos" class="btn btn-outline-secondary px-4">
                                    <i class="bi bi-x-lg me-2"></i>Cancelar
                                </a>
                                <button type="submit" class="btn btn-outline-primary px-4">
                                    <i class="bi bi-check-lg me-2"></i>Guardar Cambios
                                </button>
                            </div>
                        </div>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """

    return render_template_string(BASE_HTML, title=f"Editar Invernadero #{id}", content=form_html)

@app.route('/eliminar-invernadero/<int:id>')
def eliminar_invernadero(id):
    """
    Maneja la eliminación de un invernadero.
    Requiere inicio de sesión.
    """
    if not session.get('logged_in'):
        flash('Debes iniciar sesión para acceder a esta página.', 'warning')
        return redirect(url_for('login'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT nombre FROM invernaderos WHERE id = %s", (id,))
        invernadero = cursor.fetchone()

        if not invernadero:
            flash("Invernadero no encontrado", "danger")
            return redirect('/gestion-invernaderos')

        cursor.execute("DELETE FROM invernaderos WHERE id = %s", (id,))
        conn.commit()
        actualizar_invernaderos() # Actualizar la lista global de invernaderos

        flash(f"Invernadero '{invernadero['nombre']}' eliminado correctamente", "success")

    except Exception as e:
        flash(f"Error al eliminar invernadero: {str(e)}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    return redirect('/gestion-invernaderos')

@app.route('/analisis-comparativo')
def analisis_comparativo():
    """
    Renderiza la página de análisis comparativo de invernaderos,
    mostrando estadísticas, tendencias y un árbol de decisiones.
    """
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre FROM invernaderos ORDER BY id")
        invernaderos = cursor.fetchall()

        cursor.execute("SELECT MIN(DATE(fecha)) as min_date, MAX(DATE(fecha)) as max_date FROM lecturas")
        fechas_limite = cursor.fetchone()
        fecha_minima = fechas_limite['min_date'].strftime('%Y-%m-%d') if fechas_limite['min_date'] else datetime.now().strftime('%Y-%m-%d')
        fecha_maxima = fechas_limite['max_date'].strftime('%Y-%m-%d') if fechas_limite['max_date'] else datetime.now().strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT
                i.id as invernadero_id,
                i.nombre,
                i.encargado,
                AVG(l.temperatura) as temp_promedio,
                AVG(l.humedad_suelo) as humedad_promedio,
                MAX(l.temperatura) as temp_max,
                MIN(l.temperatura) as temp_min,
                MAX(l.humedad_suelo) as humedad_max,
                MIN(l.humedad_suelo) as humedad_min,
                COUNT(l.id) as total_lecturas
            FROM invernaderos i
            LEFT JOIN lecturas l ON i.id = l.invernadero_id
            GROUP BY i.id
            ORDER BY i.id
        """)
        estadisticas = cursor.fetchall()

        cursor.execute("""
            SELECT
                invernadero_id,
                AVG(temperatura) as temp_reciente,
                AVG(humedad_suelo) as humedad_reciente,
                CASE
                    WHEN COUNT(*) > 0 THEN
                        AVG(temperatura) - (
                            SELECT AVG(temperatura)
                            FROM lecturas
                            WHERE fecha >= DATE_SUB(NOW(), INTERVAL 48 HOUR)
                            AND fecha < DATE_SUB(NOW(), INTERVAL 24 HOUR)
                            AND invernadero_id = l.invernadero_id
                        )
                    ELSE NULL
                END as temp_tendencia,
                CASE
                    WHEN COUNT(*) > 0 THEN
                        AVG(humedad_suelo) - (
                            SELECT AVG(humedad_suelo)
                            FROM lecturas
                            WHERE fecha >= DATE_SUB(NOW(), INTERVAL 48 HOUR)
                            AND fecha < DATE_SUB(NOW(), INTERVAL 24 HOUR)
                            AND invernadero_id = l.invernadero_id
                        )
                    ELSE NULL
                END as humedad_tendencia
            FROM lecturas l
            WHERE fecha >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            GROUP BY invernadero_id
        """)
        tendencias = {t['invernadero_id']: t for t in cursor.fetchall()}

    except Exception as e:
        flash(f"Error al obtener datos: {str(e)}", "danger")
        return redirect('/')
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    def convert_decimals(obj):
        """Convierte objetos Decimal a float para JSON serialización."""
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_decimals(v) for v in obj]
        return obj

    analisis = []
    for inv in estadisticas:
        invernadero_id = inv['invernadero_id']
        tendencia = tendencias.get(invernadero_id, {})

        inv = convert_decimals(inv)
        tendencia = convert_decimals(tendencia)

        temp_promedio = inv['temp_promedio'] if inv['temp_promedio'] is not None else None
        humedad_promedio = inv['humedad_promedio'] if inv['humedad_promedio'] is not None else None
        temp_tendencia = tendencia.get('temp_tendencia', None)
        humedad_tendencia = tendencia.get('humedad_tendencia', None)

        estado = "SIN DATOS"
        recomendaciones = []
        prioridad = 0

        if temp_promedio is not None:
            if temp_promedio > 28:
                estado = "CRÍTICO"
                prioridad = 3
                recomendaciones.append("🚨 Reducir temperatura inmediatamente")
                recomendaciones.append("💨 Activar ventilación máxima")
            elif temp_promedio > 25:
                if prioridad < 2:
                    estado = "ALERTA"
                    prioridad = 2
                recomendaciones.append("⚠️ Ventilar invernadero")
            else:
                if prioridad < 1:
                    estado = "ÓPTIMO"
                    prioridad = 1
        else:
            recomendaciones.append("❓ No hay datos de temperatura")

        if humedad_promedio is not None:
            if humedad_promedio < 30:
                estado = "CRÍTICO"
                prioridad = 3
                recomendaciones.append("🚨 Aumentar riego urgentemente")
                recomendaciones.append("💧 Revisar sistema de irrigación")
            elif humedad_promedio < 50:
                if prioridad < 2:
                    estado = "ALERTA"
                    prioridad = 2
                recomendaciones.append("⚠️ Monitorear humedad de cerca")
                recomendaciones.append("💧 Considerar riego adicional")
            else:
                if prioridad < 1:
                    estado = "ÓPTIMO"
                    prioridad = 1
        else:
            recomendaciones.append("❓ No hay datos de humedad")

        if temp_promedio is not None and humedad_promedio is not None:
            if temp_promedio > 26 and humedad_promedio < 40:
                estado = "CRÍTICO"
                prioridad = 3
                recomendaciones.append("🔥 Condición crítica: Alta temperatura + Baja humedad")
                recomendaciones.append("🏃‍♂️ Acción inmediata requerida")

        if temp_tendencia is not None:
            if temp_tendencia > 2:
                recomendaciones.append("📈 Temperatura subiendo rápidamente")
                if prioridad < 2:
                    estado = "ALERTA"
                    prioridad = 2
            elif temp_tendencia < -2:
                recomendaciones.append("📉 Temperatura bajando rápidamente")

        if humedad_tendencia is not None:
            if humedad_tendencia > 2:
                recomendaciones.append("📈 Humedad subiendo rápidamente")
            elif humedad_tendencia < -2:
                recomendaciones.append("📉 Humedad bajando rápidamente")
                if prioridad < 2:
                    estado = "ALERTA"
                    prioridad = 2

        if not recomendaciones:
            recomendaciones.append("✅ Condiciones estables - Mantener operación")
        elif estado == "ÓPTIMO" and len(recomendaciones) == 0:
            recomendaciones.append("✅ Condiciones óptimas - Continuar monitoreo")

        clase_estado = "bg-secondary"
        if estado == "ÓPTIMO":
            clase_estado = "bg-success"
        elif estado == "ALERTA":
            clase_estado = "bg-warning"
        elif estado == "CRÍTICO":
            clase_estado = "bg-danger"

        temp_tendencia_icon = (
            "bi-arrow-up text-danger" if temp_tendencia is not None and temp_tendencia > 0
            else "bi-arrow-down text-primary" if temp_tendencia is not None and temp_tendencia < 0
            else "bi-dash text-secondary"
        )
        humedad_tendencia_icon = (
            "bi-arrow-up text-primary" if humedad_tendencia is not None and humedad_tendencia > 0
            else "bi-arrow-down text-danger" if humedad_tendencia is not None and humedad_tendencia < 0
            else "bi-dash text-secondary"
        )

        temp_promedio_display = f"{temp_promedio:.1f}°C" if temp_promedio is not None else "N/A"
        humedad_promedio_display = f"{humedad_promedio:.1f}%" if humedad_promedio is not None else "N/A"
        temp_min_display = f"{inv['temp_min']:.1f}°C" if inv['temp_min'] is not None else "N/A"
        temp_max_display = f"{inv['temp_max']:.1f}°C" if inv['temp_max'] is not None else "N/A"
        humedad_min_display = f"{inv['humedad_min']:.1f}%" if inv['humedad_min'] is not None else "N/A"
        humedad_max_display = f"{inv['humedad_max']:.1f}%" if inv['humedad_max'] is not None else "N/A"
        temp_tendencia_display = f"{abs(temp_tendencia):.1f}°C" if temp_tendencia is not None else "N/A"
        humedad_tendencia_display = f"{abs(humedad_tendencia):.1f}%" if humedad_tendencia is not None else "N/A"

        analisis.append({
            **inv,
            **tendencia,
            'estado': estado,
            'recomendaciones': recomendaciones,
            'clase_estado': clase_estado,
            'temp_promedio_display': temp_promedio_display,
            'humedad_promedio_display': humedad_promedio_display,
            'temp_min_display': temp_min_display,
            'temp_max_display': temp_max_display,
            'humedad_min_display': humedad_min_display,
            'humedad_max_display': humedad_max_display,
            'temp_tendencia_display': temp_tendencia_display,
            'humedad_tendencia_display': humedad_tendencia_display,
            'temp_tendencia_icon': temp_tendencia_icon,
            'humedad_tendencia_icon': humedad_tendencia_icon
        })

    analisis_json = json.dumps(analisis)

    content = f"""
    <div class="container-fluid px-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mt-4"><i class="bi bi-diagram-3 me-2"></i>Análisis Comparativo</h1>
            <div>
                <button class="btn btn-outline-success me-2" data-bs-toggle="modal" data-bs-target="#reporteModal">
                    <i class="bi bi-file-earmark-pdf me-2"></i>Generar Reporte
                </button>
                <a href="/seleccionar-invernadero-diario" class="btn btn-outline-primary">
                    <i class="bi bi-file-earmark-text me-2"></i>Reporte Diario
                </a>
                <a href="/" class="btn btn-outline-secondary">
                    <i class="bi bi-arrow-left me-2"></i>Volver
                </a>
            </div>
        </div>

        <!-- Modal para generar reporte -->
        <div class="modal fade" id="reporteModal" tabindex="-1" aria-labelledby="reporteModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header bg-primary text-white">
                        <h5 class="modal-title" id="reporteModalLabel">
                            <i class="bi bi-file-earmark-pdf me-2"></i>Generar Reporte Personalizado
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <form id="reporteForm" action="/generar-reporte" method="POST">
                            <div class="row mb-4">
                                <div class="col-md-12">
                                    <label class="form-label">Seleccionar Invernaderos</label>
                                    <select class="form-select" name="invernaderos" multiple size="5" required>
                                        {"".join([f'<option value="{inv["id"]}">{inv["nombre"]} (ID: {inv["id"]})</option>' for inv in invernaderos])}
                                    </select>
                                    <small class="text-muted">Mantén presionado Ctrl para seleccionar múltiples</small>
                                </div>
                            </div>

                            <div class="row">
                                <div class="col-md-6">
                                    <label class="form-label">Fecha de Inicio</label>
                                    <input type="date" class="form-control" name="fecha_inicio"
                                           min="{fecha_minima}" max="{fecha_maxima}"
                                           value="{fecha_minima}" required>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Fecha de Fin</label>
                                    <input type="date" class="form-control" name="fecha_fin"
                                           min="{fecha_minima}" max="{fecha_maxima}"
                                           value="{fecha_maxima}" required>
                                </div>
                            </div>

                            <div class="mt-4">
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" name="incluir_prediccion" id="incluirPrediccion" checked>
                                    <label class="form-check-label" for="incluirPrediccion">
                                        Incluir predicción de plagas/enfermedades
                                    </label>
                                </div>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-outline-danger" data-bs-dismiss="modal">Cancelar</button>
                        <button type="submit" form="reporteForm" class="btn btn-outline-primary">
                            <i class="bi bi-file-earmark-pdf me-2"></i>Generar Reporte
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Mensaje si no hay datos suficientes -->
        {f'<div class="alert alert-info mb-4">No hay suficientes datos históricos para comparar tendencias. Se mostrarán solo los datos disponibles.</div>'
         if all(t.get('temp_tendencia') is None and t.get('humedad_tendencia') is None for t in tendencias.values())
         else ''}

        <div class="row mb-4">
            <div class="col-md-6">
                <div class="card shadow-sm h-100">
                    <div class="card-header bg-white">
                        <h5 class="mb-0"><i class="bi bi-thermometer-half me-2"></i>Distribución de Temperaturas</h5>
                    </div>
                    <div class="card-body">
                        <canvas id="tempChart" height="300"></canvas>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card shadow-sm h-100">
                    <div class="card-header bg-white">
                        <h5 class="mb-0"><i class="bi bi-droplet me-2"></i>Distribución de Humedad</h5>
                    </div>
                    <div class="card-body">
                        <canvas id="humedadChart" height="300"></canvas>
                    </div>
                </div>
            </div>
        </div>

        <div class="card shadow-sm mb-4">
            <div class="card-header bg-white">
                <h5 class="mb-0"><i class="bi bi-clipboard2-data me-2"></i>Resumen Comparativo</h5>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover align-middle mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Invernadero</th>
                                <th class="text-center">Temperatura</th>
                                <th class="text-center">Humedad</th>
                                <th class="text-center">Tendencias</th>
                                <th class="text-center">Estado</th>
                                <th>Recomendaciones</th>
                            </tr>
                        </thead>
                        <tbody>
    """

    for inv in analisis:
        content += f"""
                            <tr>
                                <td>
                                    <div class="d-flex align-items-center">
                                        <div class="avatar avatar-sm me-3">
                                            <span class="avatar-initial rounded-circle bg-primary bg-opacity-10 text-primary">
                                                {inv['invernadero_id']}
                                            </span>
                                        </div>
                                        <div>
                                            <h6 class="mb-0">{inv['nombre']}</h6>
                                            <small class="text-muted">{inv['encargado']}</small>
                                        </div>
                                    </div>
                                </td>
                                <td class="text-center">
                                    <div class="d-flex flex-column">
                                        <span class="fw-bold">{inv['temp_promedio_display']}</span>
                                        <small class="text-muted">{inv['temp_min_display']}-{inv['temp_max_display']}</small>
                                    </div>
                                </td>
                                <td class="text-center">
                                    <div class="d-flex flex-column">
                                        <span class="fw-bold">{inv['humedad_promedio_display']}</span>
                                        <small class="text-muted">{inv['humedad_min_display']}-{inv['humedad_max_display']}</small>
                                    </div>
                                </td>
                                <td class="text-center">
                                    <div class="d-flex justify-content-center gap-3">
                                        <div class="text-center">
                                            <i class="bi {inv['temp_tendencia_icon']}"></i>
                                            <small class="d-block">{inv['temp_tendencia_display']}</small>
                                        </div>
                                        <div class="text-center">
                                            <i class="bi {inv['humedad_tendencia_icon']}"></i>
                                            <small class="d-block">{inv['humedad_tendencia_display']}</small>
                                        </div>
                                    </div>
                                </td>
                                <td class="text-center">
                                    <span class="badge {inv['clase_estado']} rounded-pill">{inv['estado']}</span>
                                </td>
                                <td>
                                    <ul class="mb-0" style="padding-left: 1rem;">
        """

        for rec in inv['recomendaciones']:
            content += f"""
                                        <li>{rec}</li>
            """

        content += """
                                    </ul>
                                </td>
                            </tr>
        """

    content += f"""
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="card shadow-sm">
            <div class="card-header bg-white d-flex justify-content-between align-items-center">
                <h5 class="mb-0"><i class="bi bi-diagram-3 me-2"></i>Árbol de Decisiones</h5>
                <button class="btn btn-outline-primary btn-sm" data-bs-toggle="modal" data-bs-target="#arbolModal">
                    <i class="bi bi-info-circle me-1"></i> Explicación
                </button>
            </div>
            <div class="card-body">
                <div class="decision-tree">
                    <div class="node root">
                        <div class="node-content bg-primary text-white">
                            <i class="bi bi-question-circle me-2"></i>Condiciones del Invernadero
                        </div>
                        <div class="children">
                            <div class="branch">
                                <div class="node">
                                    <div class="node-content bg-success text-white">
                                        <i class="bi bi-check-circle me-2"></i>Temperatura ≤ 25°C
                                    </div>
                                    <div class="children">
                                        <div class="node leaf">
                                            <div class="node-content bg-light">
                                                <i class="bi bi-check2-all me-2 text-success"></i>Condiciones óptimas
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="branch">
                                <div class="node">
                                    <div class="node-content bg-warning text-dark">
                                        <i class="bi bi-exclamation-triangle me-2"></i>Temperatura > 25°C
                                    </div>
                                    <div class="children">
                                        <div class="node">
                                            <div class="node-content bg-light">
                                                <i class="bi bi-droplet me-2 text-info"></i>Humedad ≥ 50%
                                            </div>
                                            <div class="children">
                                                <div class="node leaf">
                                                    <div class="node-content bg-light">
                                                        <i class="bi bi-lightbulb me-2 text-warning"></i>Ventilar invernadero
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="node">
                                            <div class="node-content bg-light">
                                                <i class="bi bi-droplet me-2 text-danger"></i>Humedad < 50%
                                            </div>
                                            <div class="children">
                                                <div class="node leaf">
                                                    <div class="node-content bg-light">
                                                        <i class="bi bi-lightbulb me-2 text-danger"></i>Aumentar riego y ventilar
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="branch">
                                <div class="node">
                                    <div class="node-content bg-danger text-white">
                                        <i class="bi bi-exclamation-octagon me-2"></i>Temperatura > 28°C
                                    </div>
                                    <div class="children">
                                        <div class="node leaf">
                                            <div class="node-content bg-light">
                                                <i class="bi bi-lightbulb me-2 text-danger"></i>Acción inmediata requerida
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal de explicación del árbol -->
    <div class="modal fade" id="arbolModal" tabindex="-1" aria-labelledby="arbolModalLabel" aria-hidden="true">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header bg-primary text-white">
                    <h5 class="modal-title" id="arbolModalLabel">
                        <i class="bi bi-info-circle me-2"></i>Explicación del Árbol de Decisiones
                    </h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h5><i class="bi bi-diagram-3 me-2"></i>¿Cómo funciona?</h5>
                            <p>Este árbol de decisiones analiza automáticamente las condiciones de tus invernaderos basándose en:</p>
                            <ol class="mb-4">
                                <li><strong>Temperatura actual</strong> vs rangos óptimos</li>
                                <li><strong>Humedad del suelo</strong> y su relación con la temperatura</li>
                                <li><strong>Tendencias recientes</strong> para predecir problemas</li>
                            </ol>

                            <h5><i class="bi bi-lightbulb me-2"></i>Recomendaciones</h5>
                            <p>Las acciones sugeridas se generan automáticamente basadas en estas reglas lógicas:</p>
                            <ul>
                                <li><span class="badge bg-success">ÓPTIMO</span> - Condiciones dentro de rangos normales</li>
                                <li><span class="badge bg-warning">ALERTA</span> - Condiciones cercanas a límites críticos</li>
                                <li><span class="badge bg-danger">CRÍTICO</span> - Requiere acción inmediata</li>
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <div class="card bg-light border-0 h-100">
                                <div class="card-body">
                                    <h5><i class="bi bi-thermometer-half me-2"></i>Rangos de Referencia</h5>
                                    <div class="table-responsive">
                                        <table class="table table-sm">
                                            <thead>
                                                <tr>
                                                    <th>Parámetro</th>
                                                    <th>Óptimo</th>
                                                    <th>Alerta</th>
                                                    <th>Crítico</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                <tr>
                                                    <td>Temperatura (°C)</td>
                                                    <td class="text-success">≤ 25</td>
                                                    <td class="text-warning">25-28</td>
                                                    <td class="text-danger">> 28</td>
                                                </tr>
                                                <tr>
                                                    <td>Humedad (%)</td>
                                                    <td class="text-success">≥ 50</td>
                                                    <td class="text-warning">30-50</td>
                                                    <td class="text-danger">< 30</td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    </div>
                                    <hr>
                                    <h5><i class="bi bi-graph-up me-2"></i>Tendencias</h5>
                                    <p>El sistema también considera cambios bruscos en los últimos valores:</p>
                                    <ul>
                                        <li><i class="bi bi-arrow-up text-danger me-1"></i> Aumento rápido de temperatura</li>
                                        <li><i class="bi bi-arrow-down text-primary me-1"></i> Disminución rápida de temperatura</li>
                                        <li><i class="bi bi-arrow-up text-primary me-1"></i> Aumento rápido de humedad</li>
                                        <li><i class="bi bi-arrow-down text-danger me-1"></i> Disminución rápida de humedad</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline-primary" data-bs-dismiss="modal">Entendido</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
    const analisisData = JSON.parse('{analisis_json}');

    const tempData = {{
        labels: [],
        minTemp: [],
        avgTemp: [],
        maxTemp: []
    }};

    const humedadData = {{
        labels: [],
        minHum: [],
        avgHum: [],
        maxHum: []
    }};

    analisisData.forEach(inv => {{
        tempData.labels.push(`Invernadero ${{inv.invernadero_id}}`);
        tempData.minTemp.push(inv.temp_min !== null ? inv.temp_min : null);
        tempData.avgTemp.push(inv.temp_promedio !== null ? inv.temp_promedio : null);
        tempData.maxTemp.push(inv.temp_max !== null ? inv.temp_max : null);

        humedadData.labels.push(`Invernadero ${{inv.invernadero_id}}`);
        humedadData.minHum.push(inv.humedad_min !== null ? inv.humedad_min : null);
        humedadData.avgHum.push(inv.humedad_promedio !== null ? inv.humedad_promedio : null);
        humedadData.maxHum.push(inv.humedad_max !== null ? inv.humedad_max : null);
    }});

    const tempCtx = document.getElementById('tempChart').getContext('2d');
    const tempChart = new Chart(tempCtx, {{
        type: 'bar',
        data: {{
            labels: tempData.labels,
            datasets: [
                {{
                    label: 'Temp. Mínima',
                    data: tempData.minTemp,
                    backgroundColor: 'rgba(54, 162, 235, 0.7)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1
                }},
                {{
                    label: 'Temp. Promedio',
                    data: tempData.avgTemp,
                    backgroundColor: 'rgba(255, 159, 64, 0.7)',
                    borderColor: 'rgba(255, 159, 64, 1)',
                    borderWidth: 1
                }},
                {{
                    label: 'Temp. Máxima',
                    data: tempData.maxTemp,
                    backgroundColor: 'rgba(255, 99, 132, 0.7)',
                    borderColor: 'rgba(255, 99, 132, 1)',
                    borderWidth: 1
                }}
            ]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                title: {{
                    display: true,
                    text: 'Comparación de Temperaturas'
                }},
                tooltip: {{
                    callbacks: {{
                        label: function(context) {{
                            let value = context.raw;
                            return context.dataset.label + ': ' +
                                (value !== null ? value.toFixed(1) + '°C' : 'N/A');
                        }}
                    }}
                }}
            }},
            scales: {{
                y: {{
                    title: {{
                        display: true,
                        text: 'Temperatura (°C)'
                    }},
                    beginAtZero: false
                }}
            }}
        }}
    }});

    const humedadCtx = document.getElementById('humedadChart').getContext('2d');
    const humedadChart = new Chart(humedadCtx, {{
        type: 'bar',
        data: {{
            labels: humedadData.labels,
            datasets: [
                {{
                    label: 'Humedad Mínima',
                    data: humedadData.minHum,
                    backgroundColor: 'rgba(75, 192, 192, 0.7)',
                    borderColor: 'rgba(75, 192, 192, 1)',
                    borderWidth: 1
                }},
                {{
                    label: 'Humedad Promedio',
                    data: humedadData.avgHum,
                    backgroundColor: 'rgba(153, 102, 255, 0.7)',
                    borderColor: 'rgba(153, 102, 255, 1)',
                    borderWidth: 1
                }},
                {{
                    label: 'Humedad Máxima',
                    data: humedadData.maxHum,
                    backgroundColor: 'rgba(255, 205, 86, 0.7)',
                    borderColor: 'rgba(255, 205, 86, 1)',
                    borderWidth: 1
                }}
            ]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                title: {{
                    display: true,
                    text: 'Comparación de Humedad'
                }},
                tooltip: {{
                    callbacks: {{
                        label: function(context) {{
                            let value = context.raw;
                            return context.dataset.label + ': ' +
                                (value !== null ? value.toFixed(1) + '%' : 'N/A');
                        }}
                    }}
                }}
            }},
            scales: {{
                y: {{
                    title: {{
                        display: true,
                        text: 'Humedad (%)'
                    }},
                    min: 0,
                    max: 100
                }}
            }}
        }}
    }});
    </script>

    <style>
        .decision-tree {{
            font-family: Arial, sans-serif;
            margin: 20px 0;
        }}

        .node {{
            display: flex;
            flex-direction: column;
            align-items: center;
            position: relative;
            margin: 0 10px;
        }}

        .node-content {{
            padding: 10px 15px;
            border-radius: 5px;
            margin-bottom: 10px;
            text-align: center;
            min-width: 200px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
        }}

        .node-content:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }}

        .children {{
            display: flex;
            justify-content: center;
            padding-top: 20px;
            position: relative;
        }}

        .branch {{
            display: flex;
            flex-direction: column;
            align-items: center;
            position: relative;
            padding: 0 20px;
        }}

        .branch:before {{
            content: '';
            position: absolute;
            top: 0;
            height: 20px;
            width: 1px;
            background-color: #ccc;
        }}

        .leaf .node-content {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
        }}

        .node.root {{
            margin-top: 0;
        }}

        .node.root .node-content {{
            font-weight: bold;
            font-size: 1.1em;
        }}

        /* Animaciones para el árbol */
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .node {{
            animation: fadeIn 0.5s ease-out;
        }}

        /* Estilos para el modal */
        .modal-header {{
            border-bottom: none;
            padding-bottom: 0;
        }}

        .modal-body h5 {{
            color: #0d6efd;
            margin-top: 1rem;
        }}

        .modal-body ul, .modal-body ol {{
            padding-left: 1.5rem;
        }}

        .modal-body li {{
            margin-bottom: 0.5rem;
        }}

        .table-sm th, .table-sm td {{
            padding: 0.5rem;
        }}

        /* Estilos para el select múltiple */
        .form-select[multiple] {{
            height: auto;
            min-height: 120px;
        }}
    </style>
    """

    return render_template_string(BASE_HTML, title="Análisis Comparativo", content=content)

@app.route('/generar-reporte', methods=['POST'])
def generar_reporte():
    """
    Genera un reporte personalizado de invernaderos basado en las fechas y selección.
    Incluye gráficos de evolución y una sección opcional de predicción de plagas.
    """
    try:
        invernaderos_seleccionados = request.form.getlist('invernaderos')
        fecha_inicio = request.form['fecha_inicio']
        fecha_fin = request.form['fecha_fin']
        incluir_prediccion = 'incluir_prediccion' in request.form

        if not invernaderos_seleccionados:
            flash("Debes seleccionar al menos un invernadero", "danger")
            return redirect('/analisis-comparativo')

        fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d')

        if fecha_fin_dt < fecha_inicio_dt:
            flash("La fecha de fin no puede ser anterior a la fecha de inicio", "danger")
            return redirect('/analisis-comparativo')

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        placeholders = ','.join(['%s'] * len(invernaderos_seleccionados))
        cursor.execute(f"SELECT id, nombre FROM invernaderos WHERE id IN ({placeholders})", tuple(invernaderos_seleccionados))
        nombres_invernaderos = {inv['id']: inv['nombre'] for inv in cursor.fetchall()}

        query = f"""
            SELECT
                i.id as invernadero_id,
                i.nombre,
                DATE(l.fecha) as fecha,
                AVG(l.temperatura) as temp_promedio,
                AVG(l.humedad_suelo) as humedad_promedio,
                MAX(l.temperatura) as temp_max,
                MIN(l.temperatura) as temp_min,
                MAX(l.humedad_suelo) as humedad_max,
                MIN(l.humedad_suelo) as humedad_min
            FROM invernaderos i
            JOIN lecturas l ON i.id = l.invernadero_id
            WHERE i.id IN ({placeholders})
            AND DATE(l.fecha) BETWEEN %s AND %s
            GROUP BY i.id, DATE(l.fecha)
            ORDER BY i.id, DATE(l.fecha)
        """
        cursor.execute(query, tuple(invernaderos_seleccionados + [fecha_inicio, fecha_fin]))
        datos_historicos = cursor.fetchall()

        if not datos_historicos:
            flash("No hay datos disponibles para los criterios seleccionados", "warning")
            return redirect('/analisis-comparativo')

        datos_por_invernadero = {}
        fechas = set()

        for dato in datos_historicos:
            invernadero_id = dato['invernadero_id']
            if invernadero_id not in datos_por_invernadero:
                datos_por_invernadero[invernadero_id] = {
                    'nombre': dato['nombre'],
                    'fechas': [],
                    'temp_promedio': [],
                    'humedad_promedio': []
                }

            fecha_str = dato['fecha'].strftime('%Y-%m-%d')
            fechas.add(fecha_str)
            datos_por_invernadero[invernadero_id]['fechas'].append(fecha_str)
            datos_por_invernadero[invernadero_id]['temp_promedio'].append(float(dato['temp_promedio']))
            datos_por_invernadero[invernadero_id]['humedad_promedio'].append(float(dato['humedad_promedio']))

        fechas = sorted(fechas)

        predicciones = []
        if incluir_prediccion:
            for invernadero_id, datos in datos_por_invernadero.items():
                # Calcular promedios para la predicción sobre el rango seleccionado
                temp_prom = sum(datos['temp_promedio']) / len(datos['temp_promedio'])
                humedad_prom = sum(datos['humedad_promedio']) / len(datos['humedad_promedio'])

                riesgo = "Bajo"
                problemas = []
                posibles_plagas = []

                if temp_prom > 28 and humedad_prom < 40:
                    riesgo = "Alto"
                    problemas.append("Condiciones extremas: Alta temperatura y baja humedad")
                    posibles_plagas.extend(["Ácaros", "Araña roja", "Trips"])
                elif temp_prom > 25 and humedad_prom > 70:
                    riesgo = "Alto"
                    problemas.append("Condiciones favorables para hongos")
                    posibles_plagas.extend(["Botrytis", "Mildiu", "Oídio"])
                elif temp_prom > 25:
                    riesgo = "Moderado"
                    problemas.append("Temperatura elevada puede favorecer plagas")
                    posibles_plagas.extend(["Mosca blanca", "Pulgón"])
                elif humedad_prom > 80:
                    riesgo = "Moderado" if riesgo == "Bajo" else riesgo # Si ya es alto, se mantiene
                    problemas.append("Humedad muy alta favorece enfermedades")
                    posibles_plagas.extend(["Rhizoctonia", "Pythium"])

                posibles_plagas = list(set(posibles_plagas)) # Eliminar duplicados

                if not problemas:
                    problemas.append("Condiciones dentro de rangos normales - riesgo mínimo")

                if not posibles_plagas:
                    posibles_plagas.append("Ninguna plaga específica identificada")

                predicciones.append({
                    'invernadero_id': invernadero_id,
                    'nombre': datos['nombre'],
                    'riesgo': riesgo,
                    'problemas': problemas,
                    'posibles_plagas': posibles_plagas,
                    'temp_promedio': temp_prom,
                    'humedad_promedio': humedad_prom
                })

        content = f"""
        <div class="container-fluid px-4">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h1 class="mt-4"><i class="bi bi-file-earmark-text me-2"></i>Reporte de Invernaderos</h1>
                <div>
                    <button class="btn btn-outline-primary me-2" onclick="window.print()">
                        <i class="bi bi-printer me-2"></i>Imprimir Reporte
                    </button>
                    <a href="/analisis-comparativo" class="btn btn-outline-secondary">
                        <i class="bi bi-arrow-left me-2"></i>Volver
                    </a>
                </div>
            </div>

            <div class="card shadow-sm mb-4">
                <div class="card-header bg-white">
                    <h5 class="mb-0"><i class="bi bi-info-circle me-2"></i>Parámetros del Reporte</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <p><strong>Invernaderos:</strong> {', '.join([nombres_invernaderos[int(id)] for id in invernaderos_seleccionados])}</p>
                            <p><strong>Fecha de inicio:</strong> {fecha_inicio}</p>
                        </div>
                        <div class="col-md-6">
                            <p><strong>Fecha de fin:</strong> {fecha_fin}</p>
                            <p><strong>Generado el:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Gráficas comparativas -->
            <div class="row mb-4">
                <div class="col-md-6">
                    <div class="card shadow-sm h-100">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-thermometer-half me-2"></i>Evolución de Temperatura</h5>
                        </div>
                        <div class="card-body">
                            <canvas id="tempChart" height="200"></canvas>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card shadow-sm h-100">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-droplet me-2"></i>Evolución de Humedad</h5>
                        </div>
                        <div class="card-body">
                            <canvas id="humedadChart" height="200"></canvas>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Resumen estadístico -->
            <div class="card shadow-sm mb-4">
                <div class="card-header bg-white">
                    <h5 class="mb-0"><i class="bi bi-clipboard-data me-2"></i>Resumen Estadístico</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-bordered">
                            <thead class="table-light">
                                <tr>
                                    <th>Invernadero</th>
                                    <th>Temperatura Promedio</th>
                                    <th>Temperatura Máxima</th>
                                    <th>Temperatura Mínima</th>
                                    <th>Humedad Promedio</th>
                                    <th>Humedad Máxima</th>
                                    <th>Humedad Mínima</th>
                                </tr>
                            </thead>
                            <tbody>
        """

        for invernadero_id, datos in datos_por_invernadero.items():
            temp_prom = sum(datos['temp_promedio']) / len(datos['temp_promedio'])
            temp_max = max(datos['temp_promedio'])
            temp_min = min(datos['temp_promedio'])
            humedad_prom = sum(datos['humedad_promedio']) / len(datos['humedad_promedio'])
            humedad_max = max(datos['humedad_promedio'])
            humedad_min = min(datos['humedad_promedio'])

            content += f"""
                                <tr>
                                    <td>{datos['nombre']} (ID: {invernadero_id})</td>
                                    <td>{temp_prom:.1f}°C</td>
                                    <td>{temp_max:.1f}°C</td>
                                    <td>{temp_min:.1f}°C</td>
                                    <td>{humedad_prom:.1f}%</td>
                                    <td>{humedad_max:.1f}%</td>
                                    <td>{humedad_min:.1f}%</td>
                                </tr>
            """

        content += """
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        """

        if incluir_prediccion and predicciones:
            content += """
            <div class="card shadow-sm mb-4">
                <div class="card-header bg-white">
                    <h5 class="mb-0"><i class="bi bi-bug me-2"></i>Predicción de Plagas/Enfermedades</h5>
                </div>
                <div class="card-body">
                    <div class="row">
            """

            for pred in predicciones:
                riesgo_color = "success" if pred['riesgo'] == "Bajo" else "warning" if pred['riesgo'] == "Moderado" else "danger"

                content += f"""
                        <div class="col-md-6 mb-4">
                            <div class="card h-100 border-{riesgo_color}">
                                <div class="card-header bg-{riesgo_color} bg-opacity-10 d-flex justify-content-between align-items-center">
                                    <h5 class="mb-0">{pred['nombre']} (ID: {pred['invernadero_id']})</h5>
                                    <span class="badge bg-{riesgo_color}">Riesgo: {pred['riesgo']}</span>
                                </div>
                                <div class="card-body">
                                    <div class="mb-3">
                                        <p class="mb-1"><strong>Condiciones promedio:</strong></p>
                                        <p class="mb-0">Temperatura: {pred['temp_promedio']:.1f}°C | Humedad: {pred['humedad_promedio']:.1f}%</p>
                                    </div>

                                    <div class="mb-3">
                                        <p class="mb-1"><strong>Problemas detectados:</strong></p>
                                        <ul class="mb-2">
                """

                for problema in pred['problemas']:
                    content += f"""
                                            <li>{problema}</li>
                    """

                content += f"""
                                        </ul>
                                    </div>

                                    <div>
                                        <p class="mb-1"><strong>Posibles plagas/enfermedades:</strong></p>
                                        <div class="d-flex flex-wrap gap-2">
                        """

                for plaga in pred['posibles_plagas']:
                    content += f"""
                                            <span class="badge bg-secondary">{plaga}</span>
                    """

                content += """
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                """

            content += """
                    </div>

                    <div class="alert alert-info mt-3">
                        <h5><i class="bi bi-lightbulb me-2"></i>Recomendaciones Generales</h5>
                        <ul class="mb-0">
                            <li>Monitorear regularmente los cultivos para detección temprana de plagas</li>
                            <li>Mantener un registro de las condiciones ambientales y aparición de plagas</li>
                            <li>Implementar medidas preventivas según el nivel de riesgo identificado</li>
                            <li>Consultar con un agrónomo para recomendaciones específicas</li>
                        </ul>
                    </div>
                </div>
            </div>
            """

        content += """
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
            document.addEventListener('DOMContentLoaded', function() {
                const fechas = """ + json.dumps(fechas) + """;
                const datasetsTemp = [];
                const datasetsHum = [];

                const colores = [
                    'rgb(255, 99, 132)',
                    'rgb(54, 162, 235)',
                    'rgb(255, 159, 64)',
                    'rgb(75, 192, 192)',
                    'rgb(153, 102, 255)',
                    'rgb(255, 205, 86)'
                ];

                const datosInvernaderos = """ + json.dumps(datos_por_invernadero) + """;

                let colorIndex = 0;
                for (const [id, datos] of Object.entries(datosInvernaderos)) {
                    const color = colores[colorIndex % colores.length];
                    colorIndex++;

                    datasetsTemp.push({
                        label: `${datos.nombre} (ID: ${id})`,
                        data: datos.temp_promedio,
                        borderColor: color,
                        backgroundColor: color.replace(')', ', 0.2)'),
                        tension: 0.1,
                        fill: false
                    });

                    datasetsHum.push({
                        label: `${datos.nombre} (ID: ${id})`,
                        data: datos.humedad_promedio,
                        borderColor: color,
                        backgroundColor: color.replace(')', ', 0.2)'),
                        tension: 0.1,
                        fill: false
                    });
                }

                const tempCtx = document.getElementById('tempChart').getContext('2d');
                new Chart(tempCtx, {
                    type: 'line',
                    data: {
                        labels: fechas,
                        datasets: datasetsTemp
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            title: {
                                display: true,
                                text: 'Comparación de Temperaturas'
                            },
                            tooltip: {
                                callbacks: {
                                    label: function(context) {
                                        return `${context.dataset.label}: ${context.raw.toFixed(1)}°C`;
                                    }
                                }
                            }
                        },
                        scales: {
                            y: {
                                title: {
                                    display: true,
                                    text: 'Temperatura (°C)'
                                }
                            }
                        }
                    }
                });

                const humCtx = document.getElementById('humedadChart').getContext('2d');
                new Chart(humCtx, {
                    type: 'line',
                    data: {
                        labels: fechas,
                        datasets: datasetsHum
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            title: {
                                display: true,
                                text: 'Comparación de Humedad'
                            },
                            tooltip: {
                                callbacks: {
                                    label: function(context) {
                                        return `${context.dataset.label}: ${context.raw.toFixed(1)}%`;
                                    }
                                }
                            }
                        },
                        scales: {
                            y: {
                                title: {
                                    display: true,
                                    text: 'Humedad (%)'
                                },
                                min: 0,
                                max: 100
                            }
                        }
                    }
                });
            });
        </script>

        <style>
            /* Estos estilos ya están en el BASE_HTML para @media print */
            /* Se repiten aquí solo para claridad sobre qué afecta el reporte */
            @media print {
                .navbar, button, a {
                    display: none !important;
                }

                body {
                    padding: 0;
                    font-size: 12pt;
                }

                .card {
                    border: 1px solid #ddd;
                    page-break-inside: avoid;
                }

                .table {
                    font-size: 10pt;
                }

                h1, h2, h3, h4, h5 {
                    page-break-after: avoid;
                }

                .badge {
                    color: #000 !important;
                    border: 1px solid #000;
                }
            }

            .card-header {
                background-color: #f8f9fa !important;
            }

            .flex-wrap {
                display: flex;
                flex-wrap: wrap;
            }

            .gap-2 {
                gap: 0.5rem;
            }
        </style>
        """

        return render_template_string(BASE_HTML, title="Reporte de Invernaderos", content=content)

    except Exception as e:
        flash(f"Error al generar el reporte: {str(e)}", "danger")
        return redirect('/analisis-comparativo')
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

@app.route('/seleccionar-invernadero-diario', methods=['GET'])
def seleccionar_invernadero_diario():
    """
    Renderiza un formulario para seleccionar un solo invernadero para el reporte diario.
    """
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre FROM invernaderos ORDER BY id")
        invernaderos = cursor.fetchall()
    except Exception as e:
        flash(f"Error al cargar invernaderos: {str(e)}", "danger")
        invernaderos = []
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    content = f"""
    <div class="container-fluid px-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mt-4"><i class="bi bi-file-earmark-text me-2"></i>Generar Reporte Diario por Invernadero</h1>
            <a href="/analisis-comparativo" class="btn btn-outline-secondary">
                <i class="bi bi-arrow-left me-2"></i>Volver a Análisis Comparativo
            </a>
        </div>

        <div class="card shadow-sm border-0">
            <div class="card-body p-4">
                <form action="/generar-reporte-diario" method="POST">
                    <div class="mb-4">
                        <label for="invernadero_id" class="form-label">Seleccionar Invernadero</label>
                        <select class="form-select" id="invernadero_id" name="invernadero_id" required>
                            <option value="">-- Seleccione un invernadero --</option>
                            {"".join([f'<option value="{inv["id"]}">{inv["nombre"]} (ID: {inv["id"]})</option>' for inv in invernaderos])}
                        </select>
                    </div>
                    <div class="d-flex justify-content-end">
                        <button type="submit" class="btn btn-outline-primary">
                            <i class="bi bi-file-earmark-text me-2"></i>Generar Reporte Diario
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """
    return render_template_string(BASE_HTML, title="Seleccionar Invernadero", content=content)


@app.route('/generar-reporte-diario', methods=['POST'])
def generar_reporte_diario():
    """
    Genera un reporte diario detallado para un invernadero específico,
    incluyendo gráficos por intervalo de 10 minutos y un resumen de predicción.
    """
    try:
        invernadero_id = request.form.get('invernadero_id')
        if not invernadero_id:
            flash("Debes seleccionar un invernadero para generar el reporte diario.", "danger")
            return redirect('/seleccionar-invernadero-diario')

        invernadero_id = int(invernadero_id) # Convertir a entero

        # Obtener el nombre del invernadero seleccionado
        nombre_invernadero = INVERNADEROS.get(invernadero_id, f"Invernadero {invernadero_id}")

        fecha_actual = datetime.now().strftime('%Y-%m-%d')

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Modificación: Consulta para agrupar datos en intervalos de 10 minutos para un invernadero específico
        query = """
            SELECT
                DATE_FORMAT(
                    FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(fecha) / (10 * 60)) * (10 * 60)),
                    '%H:%i'
                ) as hora_intervalo,
                AVG(temperatura) as temp_promedio,
                AVG(humedad_suelo) as humedad_promedio,
                MAX(temperatura) as temp_max,
                MIN(temperatura) as temp_min,
                MAX(humedad_suelo) as humedad_max,
                MIN(humedad_suelo) as humedad_min
            FROM lecturas
            WHERE invernadero_id = %s
            AND DATE(fecha) = %s
            GROUP BY hora_intervalo
            ORDER BY hora_intervalo
        """

        cursor.execute(query, (invernadero_id, fecha_actual))
        datos_diarios = cursor.fetchall()

        if not datos_diarios:
            flash(f"No hay datos disponibles para el invernadero {nombre_invernadero} ({invernadero_id}) el día {fecha_actual}", "warning")
            return redirect('/seleccionar-invernadero-diario')

        # Procesar datos para gráficas y tabla
        horas_labels = []
        temp_promedio_data = []
        humedad_promedio_data = []
        temp_max_data = []
        temp_min_data = []
        humedad_max_data = []
        humedad_min_data = []

        for dato in datos_diarios:
            horas_labels.append(dato['hora_intervalo'])
            temp_promedio_data.append(float(dato['temp_promedio']))
            humedad_promedio_data.append(float(dato['humedad_promedio']))
            temp_max_data.append(float(dato['temp_max']))
            temp_min_data.append(float(dato['temp_min']))
            humedad_max_data.append(float(dato['humedad_max']))
            humedad_min_data.append(float(dato['humedad_min']))

        # Calcular promedios y extremos del día para el resumen
        temp_prom_dia = sum(temp_promedio_data) / len(temp_promedio_data) if temp_promedio_data else 0
        temp_max_dia = max(temp_max_data) if temp_max_data else 0
        temp_min_dia = min(temp_min_data) if temp_min_data else 0
        humedad_prom_dia = sum(humedad_promedio_data) / len(humedad_promedio_data) if humedad_promedio_data else 0
        humedad_max_dia = max(humedad_max_data) if humedad_max_data else 0
        humedad_min_dia = min(humedad_min_data) if humedad_min_data else 0

        # Identificar hora pico para temperatura y humedad (si hay datos)
        hora_temp_max = horas_labels[temp_max_data.index(temp_max_dia)] if temp_max_data else "N/A"
        hora_temp_min = horas_labels[temp_min_data.index(temp_min_dia)] if temp_min_data else "N/A"
        hora_humedad_max = horas_labels[humedad_max_data.index(humedad_max_dia)] if humedad_max_data else "N/A"
        hora_humedad_min = horas_labels[humedad_min_data.index(humedad_min_dia)] if humedad_min_data else "N/A"

        # --- Lógica de Predicción de Plagas/Enfermedades para el reporte diario ---
        riesgo_prediccion = "Bajo"
        problemas_prediccion = []
        posibles_plagas_prediccion = []

        if temp_prom_dia > 28 and humedad_prom_dia < 40:
            riesgo_prediccion = "Alto"
            problemas_prediccion.append("Condiciones extremas: Alta temperatura y baja humedad")
            posibles_plagas_prediccion.extend(["Ácaros", "Araña roja", "Trips"])
        elif temp_prom_dia > 25 and humedad_prom_dia > 70:
            riesgo_prediccion = "Alto"
            problemas_prediccion.append("Condiciones favorables para hongos")
            posibles_plagas_prediccion.extend(["Botrytis", "Mildiu", "Oídio"])
        elif temp_prom_dia > 25:
            riesgo_prediccion = "Moderado"
            problemas_prediccion.append("Temperatura elevada puede favorecer plagas")
            posibles_plagas_prediccion.extend(["Mosca blanca", "Pulgón"])
        elif humedad_prom_dia > 80:
            riesgo_prediccion = "Moderado" if riesgo_prediccion == "Bajo" else riesgo_prediccion
            problemas_prediccion.append("Humedad muy alta favorece enfermedades")
            posibles_plagas_prediccion.extend(["Rhizoctonia", "Pythium"])

        posibles_plagas_prediccion = list(set(posibles_plagas_prediccion)) # Eliminar duplicados

        if not problemas_prediccion:
            problemas_prediccion.append("Condiciones dentro de rangos normales - riesgo mínimo")

        if not posibles_plagas_prediccion:
            posibles_plagas_prediccion.append("Ninguna plaga específica identificada")

        riesgo_color_clase = "success" if riesgo_prediccion == "Bajo" else "warning" if riesgo_prediccion == "Moderado" else "danger"


        content = f"""
        <div class="container-fluid px-4">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h1 class="mt-4"><i class="bi bi-file-earmark-text me-2"></i>Reporte Diario - {nombre_invernadero} (ID: {invernadero_id})</h1>
                <div>
                    <button class="btn btn-outline-primary me-2" onclick="window.print()">
                        <i class="bi bi-printer me-2"></i>Imprimir Reporte
                    </button>
                    <a href="/seleccionar-invernadero-diario" class="btn btn-outline-secondary">
                        <i class="bi bi-arrow-left me-2"></i>Volver a Selección
                    </a>
                </div>
            </div>

            <div class="card shadow-sm mb-4">
                <div class="card-header bg-white">
                    <h5 class="mb-0"><i class="bi bi-info-circle me-2"></i>Parámetros del Reporte</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <p><strong>Invernadero:</strong> {nombre_invernadero} (ID: {invernadero_id})</p>
                            <p><strong>Fecha:</strong> {fecha_actual}</p>
                        </div>
                        <div class="col-md-6">
                            <p><strong>Generado el:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Gráficas diarias -->
            <div class="row mb-4">
                <div class="col-md-6">
                    <div class="card shadow-sm h-100">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-thermometer-half me-2"></i>Temperatura por Intervalo de 10 Minutos</h5>
                        </div>
                        <div class="card-body">
                            <canvas id="tempChart" height="200"></canvas>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card shadow-sm h-100">
                        <div class="card-header bg-white">
                            <h5 class="mb-0"><i class="bi bi-droplet me-2"></i>Humedad por Intervalo de 10 Minutos</h5>
                        </div>
                        <div class="card-body">
                            <canvas id="humedadChart" height="200"></canvas>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Resumen estadístico por invernadero -->
            <div class="card shadow-sm mb-4">
                <div class="card-header bg-white">
                    <h5 class="mb-0"><i class="bi bi-clipboard-data me-2"></i>Resumen Diario</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h5><i class="bi bi-thermometer-half me-2"></i>Temperatura</h5>
                            <ul class="list-group mb-3">
                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                    Promedio
                                    <span class="badge bg-primary rounded-pill">{temp_prom_dia:.1f}°C</span>
                                </li>
                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                    Máxima ({hora_temp_max})
                                    <span class="badge bg-danger rounded-pill">{temp_max_dia:.1f}°C</span>
                                </li>
                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                    Mínima ({hora_temp_min})
                                    <span class="badge bg-info rounded-pill">{temp_min_dia:.1f}°C</span>
                                </li>
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <h5><i class="bi bi-droplet me-2"></i>Humedad</h5>
                            <ul class="list-group mb-3">
                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                    Promedio
                                    <span class="badge bg-primary rounded-pill">{humedad_prom_dia:.1f}%</span>
                                </li>
                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                    Máxima ({hora_humedad_max})
                                    <span class="badge bg-success rounded-pill">{humedad_max_dia:.1f}%</span>
                                </li>
                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                    Mínima ({hora_humedad_min})
                                    <span class="badge bg-warning rounded-pill">{humedad_min_dia:.1f}%</span>
                                </li>
                            </ul>
                        </div>
                    </div>

                    <div class="mt-3">
                        <h5><i class="bi bi-graph-up me-2"></i>Variación por Intervalo de 10 Minutos</h5>
                        <div class="table-responsive">
                            <table class="table table-sm table-bordered">
                                <thead class="table-light">
                                    <tr>
                                        <th>Hora</th>
                                        <th>Temp. Prom.</th>
                                        <th>Temp. Máx.</th>
                                        <th>Temp. Mín.</th>
                                        <th>Hum. Prom.</th>
                                        <th>Hum. Máx.</th>
                                        <th>Hum. Mín.</th>
                                    </tr>
                                </thead>
                                <tbody>
        """

        for i in range(len(horas_labels)):
            content += f"""
                                    <tr>
                                        <td>{horas_labels[i]}</td>
                                        <td>{temp_promedio_data[i]:.1f}°C</td>
                                        <td>{temp_max_data[i]:.1f}°C</td>
                                        <td>{temp_min_data[i]:.1f}°C</td>
                                        <td>{humedad_promedio_data[i]:.1f}%</td>
                                        <td>{humedad_max_data[i]:.1f}%</td>
                                        <td>{humedad_min_data[i]:.1f}%</td>
                                    </tr>
            """

        content += """
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sección de Predicción de Plagas/Enfermedades para reporte diario -->
            <div class="card shadow-sm mb-4 border-{riesgo_color_clase}">
                <div class="card-header bg-{riesgo_color_clase} bg-opacity-10">
                    <h5 class="mb-0"><i class="bi bi-bug me-2"></i>Predicción de Plagas/Enfermedades</h5>
                </div>
                <div class="card-body">
                    <p><strong>Riesgo General:</strong> <span class="badge bg-{riesgo_color_clase}">{riesgo_prediccion}</span></p>

                    <h6 class="mt-3"><i class="bi bi-exclamation-triangle me-2"></i>Problemas Potenciales:</h6>
                    <ul class="mb-2">
            """
        for problema in problemas_prediccion:
            content += f"""
                        <li>{problema}</li>
            """
        content += """
                    </ul>

                    <h6 class="mt-3"><i class="bi bi-bug-fill me-2"></i>Posibles Plagas/Enfermedades:</h6>
                    <div class="d-flex flex-wrap gap-2">
            """
        for plaga in posibles_plagas_prediccion:
            content += f"""
                        <span class="badge bg-secondary">{plaga}</span>
            """
        content += """
                    </div>

                    <div class="alert alert-info mt-4">
                        <h5><i class="bi bi-lightbulb me-2"></i>Recomendaciones Adicionales:</h5>
                        <ul>
                            <li>Monitorear visualmente los cultivos diariamente.</li>
                            <li>Ajustar sistemas de riego y ventilación según las predicciones.</li>
                            <li>Consultar a un especialista si el riesgo es alto o persistente.</li>
                        </ul>
                    </div>
                </div>
            </div>

            <!-- Recomendaciones generales -->
            <div class="card shadow-sm mb-4 border-primary">
                <div class="card-header bg-primary bg-opacity-10">
                    <h5 class="mb-0"><i class="bi bi-lightbulb me-2"></i>Recomendaciones Generales</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h6><i class="bi bi-thermometer-sun me-2"></i>Sobre Temperatura</h6>
                            <ul>
                                <li>Verificar que los sistemas de ventilación estén funcionando correctamente</li>
                                <li>Considerar implementar sombreado si las temperaturas máximas superan los 30°C</li>
                                <li>Revisar sistemas de calefacción si las mínimas son muy bajas</li>
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <h6><i class="bi bi-droplet-fill me-2"></i>Sobre Humedad</h6>
                            <ul>
                                <li>Asegurar que los sistemas de riego estén funcionando adecuadamente</li>
                                <li>Verificar drenaje si la humedad se mantiene constantemente alta</li>
                                <li>Considerar ventilación adicional si hay exceso de humedad</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>

            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <script>
                document.addEventListener('DOMContentLoaded', function() {
                    const horas = """ + json.dumps(horas_labels) + """;
                    const tempPromedio = """ + json.dumps(temp_promedio_data) + """;
                    const humedadPromedio = """ + json.dumps(humedad_promedio_data) + """;

                    const colores = [
                        'rgb(255, 99, 132)',
                        'rgb(54, 162, 235)'
                    ];

                    // Gráfica de temperatura
                    const tempCtx = document.getElementById('tempChart').getContext('2d');
                    new Chart(tempCtx, {
                        type: 'line',
                        data: {
                            labels: horas,
                            datasets: [{
                                label: 'Temperatura Promedio (°C)',
                                data: tempPromedio,
                                borderColor: colores[0],
                                backgroundColor: colores[0].replace(')', ', 0.2)'),
                                tension: 0.1,
                                fill: false
                            }]
                        },
                        options: {
                            responsive: true,
                            plugins: {
                                title: {
                                    display: true,
                                    text: 'Temperatura por Intervalo de 10 Minutos'
                                },
                                tooltip: {
                                    callbacks: {
                                        label: function(context) {
                                            return `${context.dataset.label}: ${context.raw.toFixed(1)}°C`;
                                        }
                                    }
                                }
                            },
                            scales: {
                                y: {
                                    title: {
                                        display: true,
                                        text: 'Temperatura (°C)'
                                    }
                                }
                            }
                        }
                    });

                    // Gráfica de humedad
                    const humCtx = document.getElementById('humedadChart').getContext('2d');
                    new Chart(humCtx, {
                        type: 'line',
                        data: {
                            labels: horas,
                            datasets: [{
                                label: 'Humedad Promedio (%)',
                                data: humedadPromedio,
                                borderColor: colores[1],
                                backgroundColor: colores[1].replace(')', ', 0.2)'),
                                tension: 0.1,
                                fill: false
                            }]
                        },
                        options: {
                            responsive: true,
                            plugins: {
                                title: {
                                    display: true,
                                    text: 'Humedad por Intervalo de 10 Minutos'
                                },
                                tooltip: {
                                    callbacks: {
                                        label: function(context) {
                                            return `${context.dataset.label}: ${context.raw.toFixed(1)}%`;
                                        }
                                    }
                                }
                            },
                            scales: {
                                y: {
                                    title: {
                                        display: true,
                                        text: 'Humedad (%)'
                                    },
                                    min: 0,
                                    max: 100
                                }
                            }
                        }
                    });
                });
            </script>
        </div>
        """

        return render_template_string(BASE_HTML, title="Reporte Diario", content=content)

    except Exception as e:
        flash(f"Error al generar el reporte diario: {str(e)}", "danger")
        return redirect('/')
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

def enviar_alerta_whatsapp(mensaje):
    """Envía un mensaje de alerta a través de WhatsApp de forma asíncrona."""
    def enviar():
        try:
            instance_id = "instance130350" # Reemplaza con tu ID de instancia de UltraMsg
            token = "2gy4bgmwpj4a7uy7" # Reemplaza con tu token de UltraMsg
            to = DESTINATION_WHATSAPP

            mensaje_codificado = requests.utils.quote(mensaje)

            url = f"https://api.ultramsg.com/{instance_id}/messages/chat?token={token}&to={to}&body={mensaje_codificado}"

            response = requests.get(url)

            if response.status_code == 200:
                print(f"Alerta enviada. Respuesta: {response.json()}")
            else:
                print(f"Error. Código: {response.status_code}, Respuesta: {response.text}")

        except Exception as e:
            print(f"Error al enviar WhatsApp: {str(e)}")

    thread = threading.Thread(target=enviar)
    thread.start()

def asignar_lectura_automatica(invernadero_id, lectura):
    """
    Guarda una lectura en la base de datos para un invernadero específico
    y genera alertas si las condiciones son críticas.
    """
    global ultimas_alertas_temp

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO lecturas (invernadero_id, temperatura, humedad_suelo, fecha)
            VALUES (%s, %s, %s, %s)
        """, (invernadero_id, lectura['temperatura'], lectura['humedad'], lectura['fecha']))

        # Lógica de alerta por temperatura
        if lectura['temperatura'] > ALERT_TEMP:
            if not ultimas_alertas_temp.get(invernadero_id, False): # Evitar alertas repetidas
                nombre_invernadero = INVERNADEROS.get(invernadero_id, f"Invernadero {invernadero_id}")
                mensaje_temp = f"Temperatura crítica: {lectura['temperatura']}°C en {nombre_invernadero}"

                cursor.execute("""
                    INSERT INTO alertas (invernadero_id, tipo, descripcion, fecha)
                    VALUES (%s, %s, %s, %s)
                """, (invernadero_id, "TEMP_ALTA", mensaje_temp, lectura['fecha']))

                mensaje_whatsapp = f"""🌡️ *ALERTA DEL INVERNADERO NÚMERO {invernadero_id}*
*Invernadero*: {nombre_invernadero}
*Tipo*: Temperatura Alta
*Descripción*: {mensaje_temp}
*Fecha*: {lectura['fecha'].strftime('%Y-%m-%d %H:%M:%S')}"""
                enviar_alerta_whatsapp(mensaje_whatsapp)

                ultimas_alertas_temp[invernadero_id] = True
        else:
            ultimas_alertas_temp[invernadero_id] = False

        # Lógica de alerta por humedad del suelo
        estado_actual = estado_suelo(lectura['humedad'])
        estado_anterior = ultimos_estados.get(invernadero_id)

        if estado_actual != estado_anterior and estado_actual in ["Seco"]:
            nombre_invernadero = INVERNADEROS.get(invernadero_id, f"Invernadero {invernadero_id}")
            mensaje_suelo_db = f"Suelo seco detectado: {lectura['humedad']}% en {nombre_invernadero}"

            cursor.execute("""
                INSERT INTO alertas (invernadero_id, tipo, descripcion, fecha)
                VALUES (%s, %s, %s, %s)
            """, (invernadero_id, "SUELO_SECO", mensaje_suelo_db, lectura['fecha']))

            if estado_actual == "Seco":
                mensaje_suelo_whatsapp = f"""💧 *ALERTA DEL INVERNADERO NÚMERO {invernadero_id}*
*Invernadero*: {nombre_invernadero}
*Tipo*: Suelo Seco
*Descripción*: {mensaje_suelo_db}
*Fecha*: {lectura['fecha'].strftime('%Y-%m-%d %H:%M:%S')}"""
                enviar_alerta_whatsapp(mensaje_suelo_whatsapp)

        ultimos_estados[invernadero_id] = estado_actual
        conn.commit()

    except Exception as e:
        print(f"Error al guardar lectura automática: {str(e)}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
