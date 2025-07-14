from flask import Flask, request, jsonify, render_template_string, flash, redirect, url_for
import mysql.connector
from datetime import datetime, timedelta
from collections import deque
import requests
import threading
from decimal import Decimal
import json

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

DESTINATION_WHATSAPP = "593979111576"

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

def actualizar_invernaderos():
    global INVERNADEROS, ultimas_lecturas, ultimos_estados, ultimas_alertas_temp
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT id, nombre FROM invernaderos ORDER BY id")
        invernaderos_db = cursor.fetchall()
        
        # Actualizar el diccionario INVERNADEROS
        nuevos_invernaderos = {row['id']: row['nombre'] for row in invernaderos_db}
        
        # Actualizar variables dependientes
        nuevos_ids = set(nuevos_invernaderos.keys())
        ids_actuales = set(INVERNADEROS.keys())
        
        # Agregar nuevos invernaderos a las variables de estado
        for id_nuevo in nuevos_ids - ids_actuales:
            ultimas_lecturas[id_nuevo] = None
            ultimos_estados[id_nuevo] = None
            ultimas_alertas_temp[id_nuevo] = False
        
        # Eliminar invernaderos removidos
        for id_eliminar in ids_actuales - nuevos_ids:
            ultimas_lecturas.pop(id_eliminar, None)
            ultimos_estados.pop(id_eliminar, None)
            ultimas_alertas_temp.pop(id_eliminar, None)
        
        INVERNADEROS = nuevos_invernaderos
        
    except Exception as e:
        print(f"Error al actualizar INVERNADEROS: {str(e)}")
        # Mantener valores por defecto si hay error
        INVERNADEROS = {
            1: "Invernadero de Claveles",
            2: "Invernadero de Claveles", 
            3: "Invernadero de Claveles",
            4: "Invernadero de Claveles",
            5: "Invernadero de Claveles"
        }
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()


# Variables globales para almacenar lecturas
lecturas_sensor = []  # Lista para almacenar todas las lecturas del sensor
asignacion_activa = None  # Almacena el ID del invernadero activo
ultimas_lecturas = {invernadero_id: None for invernadero_id in INVERNADEROS.keys()} 
ultimos_estados = {invernadero_id: None for invernadero_id in INVERNADEROS.keys()}  # Para seguimiento de estados
ultimas_alertas_temp = {invernadero_id: False for invernadero_id in INVERNADEROS.keys()}

# Al final de las definiciones globales, antes de las rutas
actualizar_invernaderos()


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
                    <img src="static/img/image-1.png" alt="Invernadero" class="img-fluid" style="max-height: 250px;">
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
    # Función para generar color único basado en ID
    def get_color_from_id(invernadero_id):
        # Lista de colores Bootstrap que combinan bien
        colors = [
            'primary', 'secondary', 'success', 'danger', 'warning', 'info',
            'dark', 'primary', 'secondary', 'success', 'danger', 'warning'
        ]
        return colors[invernadero_id % len(colors)]

    # Obtener todos los invernaderos de la base de datos
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Obtener la lista de todos los invernaderos con sus datos completos
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
        
        # Procesar los datos de cada invernadero
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
        color_badge = get_color_from_id(invernadero_id)
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
    <!-- Incluir CDN de Bootstrap Icons -->
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
        // Inicializar tooltips
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
    if request.method == 'POST':
        try:
            nombre = request.form['nombre']
            cantidad_claveles = request.form['cantidad_claveles']
            encargado = request.form['encargado']
            
            conn = get_db()
            cursor = conn.cursor()
            
            # Consulta modificada (sin incluir el ID)
            cursor.execute("""
                INSERT INTO invernaderos (nombre, cantidad_claveles, encargado)
                VALUES (%s, %s, %s)
            """, (nombre, cantidad_claveles, encargado))
            
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
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Obtener nombre del invernadero para el mensaje flash
        cursor.execute("SELECT nombre FROM invernaderos WHERE id = %s", (id,))
        invernadero = cursor.fetchone()
        
        if not invernadero:
            flash("Invernadero no encontrado", "danger")
            return redirect('/gestion-invernaderos')
        
        # Eliminar el invernadero
        cursor.execute("DELETE FROM invernaderos WHERE id = %s", (id,))
        conn.commit()
        
        flash(f"Invernadero '{invernadero['nombre']}' eliminado correctamente", "success")
        
    except Exception as e:
        flash(f"Error al eliminar invernadero: {str(e)}", "danger")
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()
    
    return redirect('/gestion-invernaderos')


@app.route('/analisis-comparativo')
def analisis_comparativo():
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Obtener datos históricos de todos los invernaderos
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
        
        # Obtener tendencias recientes (últimas 24 horas) con manejo de NULL
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
    
    # Función para convertir Decimal a float
    def convert_decimals(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_decimals(v) for v in obj]
        return obj
    
    # Procesar datos para el árbol de decisiones
    analisis = []
    for inv in estadisticas:
        invernadero_id = inv['invernadero_id']
        tendencia = tendencias.get(invernadero_id, {})
        
        # Convertir Decimal a float
        inv = convert_decimals(inv)
        tendencia = convert_decimals(tendencia)
        
        # Manejo seguro de valores None
        temp_promedio = inv['temp_promedio'] if inv['temp_promedio'] is not None else None
        humedad_promedio = inv['humedad_promedio'] if inv['humedad_promedio'] is not None else None
        temp_tendencia = tendencia.get('temp_tendencia', None)
        humedad_tendencia = tendencia.get('humedad_tendencia', None)
        
        # Reglas de decisión (Árbol de decisiones) - MEJORADAS
        estado = "SIN DATOS"
        recomendaciones = []
        prioridad = 0  # 0=SIN DATOS, 1=ÓPTIMO, 2=ALERTA, 3=CRÍTICO

        # Análisis de temperatura
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

        # Análisis de humedad
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

        # Análisis combinado (condiciones críticas)
        if temp_promedio is not None and humedad_promedio is not None:
            if temp_promedio > 26 and humedad_promedio < 40:
                estado = "CRÍTICO"
                prioridad = 3
                recomendaciones.append("🔥 Condición crítica: Alta temperatura + Baja humedad")
                recomendaciones.append("🏃‍♂️ Acción inmediata requerida")

        # Análisis de tendencias
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

        # Recomendaciones por defecto
        if not recomendaciones:
            recomendaciones.append("✅ Condiciones estables - Mantener operación")
        elif estado == "ÓPTIMO" and len(recomendaciones) == 0:
            recomendaciones.append("✅ Condiciones óptimas - Continuar monitoreo")
        
        # Determinar clase CSS para el estado
        clase_estado = "bg-secondary"  # Por defecto (sin datos)
        if estado == "ÓPTIMO":
            clase_estado = "bg-success"
        elif estado == "ALERTA":
            clase_estado = "bg-warning"
        elif estado == "CRÍTICO":
            clase_estado = "bg-danger"
        
        # Determinar iconos de tendencia (manejo de None)
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
        
        # Formatear valores para mostrar
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
    
    # Convertir el objeto analisis a una cadena JSON para pasar a JavaScript
    analisis_json = json.dumps(analisis)

    # Generar HTML
    content = f"""
    <div class="container-fluid px-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mt-4"><i class="bi bi-diagram-3 me-2"></i>Análisis Comparativo</h1>
            <div class="dropdown">
                <button class="btn btn-outline-secondary dropdown-toggle" type="button" 
                        data-bs-toggle="dropdown" aria-expanded="false">
                    <i class="bi bi-funnel me-2"></i>Filtrar
                </button>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="#">Todos los invernaderos</a></li>
                    <li><a class="dropdown-item" href="#">Solo críticos</a></li>
                    <li><a class="dropdown-item" href="#">Solo alertas</a></li>
                </ul>
            </div>
        </div>
        
        <!-- Mensaje si no hay datos suficientes -->
        {f'<div class="alert alert-info mb-4">No hay suficientes datos históricos para comparar tendencias. Se mostrarán solo los datos disponibles.</div>' 
         if all(t.get('temp_tendencia') is None and t.get('humedad_tendencia') is None for t in tendencias.values()) 
         else ''}

        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        
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
                    <button type="button" class="btn btn-primary" data-bs-dismiss="modal">Entendido</button>
                </div>
            </div>
        </div>
    </div>
    
    <script>
    // Datos procesados desde el servidor
    const analisisData = JSON.parse('{analisis_json}');
    
    // Procesar datos para las gráficas
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
    
    // Llenar los datos desde el análisis
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

    // Gráfico de temperaturas
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
    
    // Gráfico de humedad
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
    </style>
    """
    
    return render_template_string(BASE_HTML, title="Análisis Comparativo", content=content)

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