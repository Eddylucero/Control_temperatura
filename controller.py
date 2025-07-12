from flask import Flask, request, jsonify, render_template_string, flash, redirect, url_for
import mysql.connector
from datetime import datetime, timedelta
from collections import deque
import requests
import threading

app = Flask(__name__)
app.secret_key = "tu_clave_secreta"

# Configuración
INVERNADEROS = {
    1: "Invernadero de Claveles",
    2: "Invernadero de Claveles", 
    3: "Invernadero de Claveles",
    4: "Invernadero de Claveles",
    5: "Invernadero de Claveles"
}

ALERT_TEMP =  30 # Umbral de temperatura para alertas

DESTINATION_WHATSAPP = "593979111576"   # Número destino (sin "+" o "whatsapp:")

# Variables globales para almacenar lecturas
lecturas_sensor = []  # Lista para almacenar todas las lecturas del sensor
asignacion_activa = None  # Almacena el ID del invernadero activo
ultimas_lecturas = {invernadero_id: None for invernadero_id in INVERNADEROS.keys()} 
ultimos_estados = {invernadero_id: None for invernadero_id in INVERNADEROS.keys()}  # Para seguimiento de estados
ultimas_alertas_temp = {invernadero_id: False for invernadero_id in INVERNADEROS.keys()}


def estado_suelo(humedad):
    if humedad is None:
        return "Sin datos"
    if humedad < 60:  # Umbral único para "Seco"
        return "Seco"
    else:              # Todo lo demás es "Húmedo"
        return "Húmedo"


# Conexión a la base de datos
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="admin",
        database="db_invernaderos"
    )


# HTML Base
BASE_HTML = """
<!doctype html>
<html>
<head>
  <title>{{ title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
  <style>
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
  
  <script>
    // Variables globales
    let tempChart, humChart;
    let lastHistorialUpdate = 0;
    const updateInterval = 5000; // 5 segundos
    const historialSyncInterval = 30000; // 30 segundos
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
    global lecturas_sensor
    
    data = request.get_json()
    print("Datos recibidos del sensor:", data)

    if not all(k in data for k in ['temperatura', 'humedad_suelo']):
        return jsonify({"error": "Datos incompletos"}), 400

    # Guardamos la lectura en la lista
    nueva_lectura = {
        'fecha': datetime.now(),
        'temperatura': float(data['temperatura']),
        'humedad': int(data['humedad_suelo'])
    }
    
    lecturas_sensor.append(nueva_lectura)
    
    # Si hay un invernadero activo, asignamos automáticamente
    if asignacion_activa:
        asignar_lectura_automatica(asignacion_activa, nueva_lectura)
    
    return jsonify({"status": "success"}), 200

# Endpoint para obtener historial de lecturas
@app.route('/api/lecturas_historial/<int:invernadero_id>')
def lecturas_historial(invernadero_id):
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
        
        # Invertir el orden para que los más recientes estén al final (para los gráficos)
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

# Endpoint para obtener estado actual de un invernadero
@app.route('/api/estado_invernadero/<int:invernadero_id>')
def estado_invernadero(invernadero_id):
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

# Página principal
@app.route('/')
def home():
    # Obtener alertas recientes desde la base de datos
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

    # Generar HTML para las alertas
    alertas_html = ""
    for alerta in alertas_db:
        # Determinar clase CSS según el tipo de alerta
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
        
        # Calcular tiempo transcurrido
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
        
        # Extraer valor numérico de la descripción
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

    # Contenido completo de la página
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
                <div class="col-lg-5 d-none d-lg-block">
                    <img src="https://cdn-icons-png.flaticon.com/512/3050/3050226.png" alt="Invernadero" class="img-fluid" style="max-height: 250px;">
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
                    <a href="#" class="card action-card h-100 text-decoration-none">
                        <div class="card-body text-center">
                            <i class="bi bi-file-earmark-bar-graph text-info mb-2" style="font-size: 2rem;"></i>
                            <h5 class="mb-1">Reportes</h5>
                            <p class="text-muted small mb-0">Generar reportes</p>
                        </div>
                    </a>
                </div>
                <div class="col-md-3">
                    <a href="/gestion-invernaderos" class="card action-card h-100 text-decoration-none">
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

# Página de listado de invernaderos
@app.route('/invernaderos')
def listar_invernaderos():
    # Obtener todos los invernaderos de la base de datos
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Obtener la lista de todos los invernaderos
        cursor.execute("SELECT id, nombre FROM invernaderos ORDER BY id")
        invernaderos_db = cursor.fetchall()
        
        if not invernaderos_db:
            flash("No hay invernaderos registrados", "info")
            return render_template_string(BASE_HTML, title="Invernaderos", content="<div class='alert alert-info'>No hay invernaderos registrados</div>")
        
        # Obtener últimos datos de cada invernadero
        ultimos_datos = {}
        for invernadero in invernaderos_db:
            invernadero_id = invernadero['id']
            
            # Obtener datos del sensor
            cursor.execute("""
                SELECT temperatura, humedad_suelo as humedad, fecha
                FROM lecturas 
                WHERE invernadero_id = %s
                ORDER BY fecha DESC LIMIT 1
            """, (invernadero_id,))
            
            resultado = cursor.fetchone()
            
            # Obtener información completa del invernadero
            cursor.execute("""
                SELECT nombre, cantidad_claveles, encargado
                FROM invernaderos
                WHERE id = %s
            """, (invernadero_id,))
            
            info_invernadero = cursor.fetchone()
            
            if resultado and info_invernadero:
                ultimos_datos[invernadero_id] = {
                    "nombre": info_invernadero['nombre'],
                    "temperatura": float(resultado['temperatura']) if resultado['temperatura'] is not None else None,
                    "humedad": int(resultado['humedad']) if resultado['humedad'] is not None else None,
                    "fecha": resultado['fecha'].strftime('%Y-%m-%d %H:%M') if resultado['fecha'] else "Sin datos",
                    "estado": estado_suelo(resultado['humedad']) if resultado['humedad'] is not None else "Sin datos",
                    "cantidad_claveles": info_invernadero['cantidad_claveles'],
                    "encargado": info_invernadero['encargado']
                }
            else:
                ultimos_datos[invernadero_id] = {
                    "nombre": invernadero['nombre'],
                    "temperatura": None,
                    "humedad": None,
                    "fecha": "Sin datos",
                    "estado": "Sin datos",
                    "cantidad_claveles": 0,
                    "encargado": "No asignado"
                }

    except Exception as e:
        flash(f"Error al obtener datos: {str(e)}", "danger")
        return render_template_string(BASE_HTML, title="Error", content=f"<div class='alert alert-danger'>Error al cargar los datos: {str(e)}</div>")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    # Generar tarjetas para cada invernadero
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
        temp = datos.get('temperatura')
        hum = datos.get('humedad')
        
        # Determinar clases CSS según los valores
        temp_class = 'text-danger' if temp is not None and temp > ALERT_TEMP else 'text-dark'
        hum_class = 'text-warning' if datos.get('estado') == "Seco" else 'text-success'
        card_border = 'border-danger' if temp is not None and temp > ALERT_TEMP else ''
        
        # Iconos según estado
        temp_icon = 'bi-thermometer-high' if temp is not None and temp > ALERT_TEMP else 'bi-thermometer-half'
        hum_icon = 'bi-droplet' if datos.get('estado') == "Húmedo" else 'bi-droplet-fill'
        
        # Formatear valores para mostrar
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
                  <span class="badge bg-primary">ID: {invernadero_id}</span>
                </h5>
              </div>
              <div class="card-body">
                <h4 class="card-title text-center mb-4">Invernadero #{invernadero_id}</h4>
                
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
    global asignacion_activa
    
    if invernadero_id not in INVERNADEROS:
        flash("Invernadero no encontrado")
        return redirect(url_for('listar_invernaderos'))
    
    asignacion_activa = invernadero_id
    print(f"Asignación automática activada para {INVERNADEROS[invernadero_id]}")

    # Obtener datos históricos
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

    # Generar tabla de lecturas
    tabla_lecturas = f"""
    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h3 class="mb-0">Lecturas Recientes - {INVERNADEROS[invernadero_id]} ({invernadero_id})</h3>
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

    # Contenido completo con gráficas separadas
    content = f"""
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2>{INVERNADEROS[invernadero_id]} ({invernadero_id})</h2>
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
        title=f"Detalles - {INVERNADEROS[invernadero_id]}",
        content=content,
        ALERT_TEMP=ALERT_TEMP
    )

# Nuevo endpoint para desactivar la asignación automática
@app.route('/api/desactivar_asignacion', methods=['POST'])
def desactivar_asignacion():
    global asignacion_activa
    asignacion_activa = None
    print("Asignación automática desactivada")
    return jsonify({"status": "success"}), 200

# Modificación en el endpoint de tiempo real para actualizar las últimas lecturas
@app.route('/api/lecturas_realtime/<int:invernadero_id>')
def lecturas_realtime(invernadero_id):
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


# Página de alertas
@app.route('/alertas')
def alertas():
    # Obtener alertas recientes
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

    # Generar tabla de alertas
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

@app.route('/gestion-invernaderos')
def gestion_invernaderos():
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Obtener todos los invernaderos
        cursor.execute("SELECT * FROM invernaderos ORDER BY id")
        invernaderos = cursor.fetchall()
        
    except Exception as e:
        flash(f"Error al obtener invernaderos: {str(e)}", "danger")
        invernaderos = []
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()
    
    # Generar tabla HTML
    tabla_html = """
    <!-- Incluir CDN de Bootstrap JS (si no está en tu BASE_HTML) -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    
    <div class="card shadow-sm">
        <div class="card-header bg-white d-flex justify-content-between align-items-center">
            <h3 class="mb-0">Gestión de Invernaderos</h3>
            <a href="/agregar-invernadero" class="btn btn-primary">
                <i class="bi bi-plus-circle me-2"></i>Agregar Invernadero
            </a>
        </div>
        <div class="card-body">
    """
    
    if not invernaderos:
        tabla_html += """
            <div class="alert alert-info">
                No hay invernaderos registrados. <a href="/agregar-invernadero" class="alert-link">Agregar uno nuevo</a>
            </div>
        """
    else:
        tabla_html += """
            <div class="table-responsive">
                <table class="table table-hover table-striped">
                    <thead class="table-light">
                        <tr>
                            <th>ID</th>
                            <th>Nombre</th>
                            <th>Cantidad de Claveles</th>
                            <th>Encargado</th>
                            <th>Acciones</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for inv in invernaderos:
            tabla_html += f"""
                        <tr>
                            <td>{inv['id']}</td>
                            <td>{inv['nombre']}</td>
                            <td>{inv['cantidad_claveles']:,}</td>
                            <td>{inv['encargado']}</td>
                            <td>
                                <div class="d-flex gap-2">
                                    <a href="/editar-invernadero/{inv['id']}" class="btn btn-sm btn-outline-primary">
                                        <i class="bi bi-pencil-square"></i>
                                    </a>
                                    <button class="btn btn-sm btn-outline-danger" 
                                            onclick="confirmarEliminacion({inv['id']})">
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
        """
    
    tabla_html += """
        </div>
    </div>

    <!-- Modal de confirmación -->
    <div class="modal fade" id="confirmModal" tabindex="-1" aria-labelledby="confirmModalLabel" aria-hidden="true">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="confirmModalLabel">Confirmar Eliminación</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    ¿Estás seguro que deseas eliminar este invernadero? Esta acción no se puede deshacer.
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                    <a id="deleteBtn" href="#" class="btn btn-danger">Eliminar</a>
                </div>
            </div>
        </div>
    </div>

    <script>
        function confirmarEliminacion(id) {
            document.getElementById('deleteBtn').href = '/eliminar-invernadero/' + id;
            var modal = new bootstrap.Modal(document.getElementById('confirmModal'));
            modal.show();
        }
    </script>
    """
    
    return render_template_string(
        BASE_HTML,
        title="Gestión de Invernaderos",
        content=tabla_html
    )

@app.route('/agregar-invernadero', methods=['GET', 'POST'])
def agregar_invernadero():
    if request.method == 'POST':
        try:
            id = request.form['id']
            nombre = request.form['nombre']
            cantidad_claveles = request.form['cantidad_claveles']
            encargado = request.form['encargado']
            
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO invernaderos (id, nombre, cantidad_claveles, encargado)
                VALUES (%s, %s, %s, %s)
            """, (id, nombre, cantidad_claveles, encargado))
            
            conn.commit()
            flash("Invernadero agregado correctamente", "success")
            return redirect('/gestion-invernaderos')
            
        except Exception as e:
            flash(f"Error al agregar invernadero: {str(e)}", "danger")
        finally:
            if 'conn' in locals() and conn.is_connected():
                conn.close()
    
    # Generar formulario HTML
    form_html = """
    <div class="card shadow-sm">
        <div class="card-header bg-white">
            <h3 class="mb-0">Agregar Nuevo Invernadero</h3>
        </div>
        <div class="card-body">
            <form method="POST">
                <div class="mb-3">
                    <label for="id" class="form-label">ID del Invernadero</label>
                    <input type="number" class="form-control" id="id" name="id" required>
                </div>
                <div class="mb-3">
                    <label for="nombre" class="form-label">Nombre</label>
                    <input type="text" class="form-control" id="nombre" name="nombre" required>
                </div>
                <div class="mb-3">
                    <label for="cantidad_claveles" class="form-label">Cantidad de Claveles</label>
                    <input type="number" class="form-control" id="cantidad_claveles" name="cantidad_claveles" required>
                </div>
                <div class="mb-3">
                    <label for="encargado" class="form-label">Encargado</label>
                    <input type="text" class="form-control" id="encargado" name="encargado" required>
                </div>
                <div class="d-flex justify-content-end gap-2">
                    <a href="/gestion-invernaderos" class="btn btn-secondary">Cancelar</a>
                    <button type="submit" class="btn btn-primary">Guardar</button>
                </div>
            </form>
        </div>
    </div>
    """
    
    return render_template_string(BASE_HTML, title="Agregar Invernadero", content=form_html)

@app.route('/editar-invernadero/<int:id>', methods=['GET', 'POST'])
def editar_invernadero(id):
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
            flash("Invernadero actualizado correctamente", "success")
            return redirect('/gestion-invernaderos')
            
        except Exception as e:
            flash(f"Error al actualizar invernadero: {str(e)}", "danger")
        finally:
            if 'conn' in locals() and conn.is_connected():
                conn.close()
    
    # Obtener datos del invernadero
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
    
    # Generar formulario HTML
    form_html = f"""
    <div class="card shadow-sm">
        <div class="card-header bg-white">
            <h3 class="mb-0">Editar Invernadero #{invernadero['id']}</h3>
        </div>
        <div class="card-body">
            <form method="POST">
                <div class="mb-3">
                    <label for="nombre" class="form-label">Nombre</label>
                    <input type="text" class="form-control" id="nombre" name="nombre" 
                           value="{invernadero['nombre']}" required>
                </div>
                <div class="mb-3">
                    <label for="cantidad_claveles" class="form-label">Cantidad de Claveles</label>
                    <input type="number" class="form-control" id="cantidad_claveles" name="cantidad_claveles" 
                           value="{invernadero['cantidad_claveles']}" required>
                </div>
                <div class="mb-3">
                    <label for="encargado" class="form-label">Encargado</label>
                    <input type="text" class="form-control" id="encargado" name="encargado" 
                           value="{invernadero['encargado']}" required>
                </div>
                <div class="d-flex justify-content-end gap-2">
                    <a href="/gestion-invernaderos" class="btn btn-secondary">Cancelar</a>
                    <button type="submit" class="btn btn-primary">Guardar Cambios</button>
                </div>
            </form>
        </div>
    </div>
    """
    
    return render_template_string(BASE_HTML, title=f"Editar Invernadero #{id}", content=form_html)

@app.route('/eliminar-invernadero/<int:id>')
def eliminar_invernadero(id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Verificar si el invernadero existe
        cursor.execute("SELECT id FROM invernaderos WHERE id = %s", (id,))
        if not cursor.fetchone():
            flash("Invernadero no encontrado", "danger")
            return redirect('/gestion-invernaderos')
        
        # Eliminar el invernadero
        cursor.execute("DELETE FROM invernaderos WHERE id = %s", (id,))
        conn.commit()
        
        flash("Invernadero eliminado correctamente", "success")
        
    except Exception as e:
        flash(f"Error al eliminar invernadero: {str(e)}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()
    
    return redirect('/gestion-invernaderos')

def enviar_alerta_whatsapp(mensaje):
    def enviar():
        try:            
            instance_id = "instance130350"
            token = "2gy4bgmwpj4a7uy7"
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
    global ultimas_alertas_temp
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Insertar la lectura en la base de datos
        cursor.execute("""
            INSERT INTO lecturas (invernadero_id, temperatura, humedad_suelo, fecha)
            VALUES (%s, %s, %s, %s)
        """, (invernadero_id, lectura['temperatura'], lectura['humedad'], lectura['fecha']))

        # Verificar temperatura alta
        if lectura['temperatura'] > ALERT_TEMP:
            if not ultimas_alertas_temp[invernadero_id]:
                # Mensaje simple para la base de datos
                mensaje_temp = f"Temperatura crítica: {lectura['temperatura']}°C en {INVERNADEROS[invernadero_id]}"
                
                cursor.execute("""
                    INSERT INTO alertas (invernadero_id, tipo, descripcion, fecha)
                    VALUES (%s, %s, %s, %s)
                """, (invernadero_id, "TEMP_ALTA", mensaje_temp, lectura['fecha']))
                
                # Mensaje detallado para WhatsApp
                mensaje_whatsapp = f"""🌡️ *ALERTA DEL INVERNADERO NÚMERO {invernadero_id}*
*Invernadero*: {INVERNADEROS[invernadero_id]}
*Tipo*: Temperatura Alta
*Descripción*: {mensaje_temp}
*Fecha*: {lectura['fecha'].strftime('%Y-%m-%d %H:%M:%S')}"""
                enviar_alerta_whatsapp(mensaje_whatsapp)
                
                ultimas_alertas_temp[invernadero_id] = True
        else:
            # Temperatura bajó del umbral, resetear el estado
            ultimas_alertas_temp[invernadero_id] = False

        # Manejo de humedad del suelo (formato similar al de temperatura)
        estado_actual = estado_suelo(lectura['humedad'])
        estado_anterior = ultimos_estados[invernadero_id]
        
        if estado_actual != estado_anterior and estado_actual in ["Seco"]:
            # Mensaje simple para la base de datos
            mensaje_suelo_db = f"Suelo seco detectado: {lectura['humedad']}% en {INVERNADEROS[invernadero_id]}"
            
            cursor.execute("""
                INSERT INTO alertas (invernadero_id, tipo, descripcion, fecha)
                VALUES (%s, %s, %s, %s)
            """, (invernadero_id, "SUELO_SECO", mensaje_suelo_db, lectura['fecha']))
            
            if estado_actual == "Seco":
                # Mensaje detallado para WhatsApp
                mensaje_suelo_whatsapp = f"""💧 *ALERTA DEL INVERNADERO NÚMERO {invernadero_id}*
*Invernadero*: {INVERNADEROS[invernadero_id]}
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