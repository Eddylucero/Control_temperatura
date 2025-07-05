from flask import Flask, request, jsonify, render_template_string, flash, redirect, url_for
import mysql.connector
from datetime import datetime
from collections import deque

app = Flask(__name__)
app.secret_key = "tu_clave_secreta"

# Configuración
INVERNADEROS = {
    1: "Invernadero de Rosas",
    2: "Invernadero de Claveles", 
    3: "Invernadero de Hortensias",
    4: "Invernadero de Tulipanes",
    5: "Invernadero de Geranios"
}

ALERT_TEMP = 40  # Umbral de temperatura para alertas

ultimas_lecturas = {invernadero_id: None for invernadero_id in INVERNADEROS.keys()}

def estado_suelo(humedad):
    if humedad is None:
        return "Sin datos"
    if humedad < 30:
        return "Muy seco"
    elif humedad < 60:
        return "Seco"
    elif humedad < 80:
        return "Húmedo"
    else:
        return "Muy húmedo"

# Conexión a la base de datos
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="admin",
        database="db_invernadero"
    )

# HTML Base
BASE_HTML = """
<!doctype html>
<html>
<head>
  <title>{{ title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
      <a class="navbar-brand" href="/">Monitoreo Invernaderos</a>
      <div class="navbar-nav">
        <a class="nav-link" href="/invernaderos">Invernaderos</a>
        <a class="nav-link" href="/alertas">Alertas</a>
      </div>
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
    const updateInterval = 2000; // 2 segundo
    const historialSyncInterval = 30000; // 30 segundos
    let isUpdating = false;

    // Función para determinar estado del suelo
    function determinarEstado(humedad) {
      if (humedad === undefined || humedad === null) return "Sin datos";
      if (humedad < 30) return "Muy seco";
      if (humedad < 60) return "Seco";
      if (humedad < 80) return "Húmedo";
      return "Muy húmedo";
    }

    // Función para obtener clase CSS del estado
    function getEstadoClass(estado) {
      if (estado.includes("Muy seco")) return "text-danger";
      if (estado.includes("Seco")) return "text-warning";
      if (estado.includes("Húmedo")) return "text-primary";
      return "text-success";
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

# Endpoint API para recibir datos del ESP32
@app.route('/api/lectura', methods=['POST'])
def recibir_lectura():
    data = request.get_json()
    
    if not all(k in data for k in ['invernadero_id', 'temperatura', 'humedad']):
        return jsonify({"error": "Datos incompletos"}), 400
    
    invernadero_id = int(data['invernadero_id'])
    temperatura = float(data['temperatura'])
    humedad = int(data['humedad'])
    fecha = datetime.now()

    # Actualizar última lectura en memoria
    global ultimas_lecturas
    ultimas_lecturas[invernadero_id] = {
        'fecha': fecha,
        'temperatura': temperatura,
        'humedad': humedad
    }

    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Insertar lectura en la base de datos
        cursor.execute("""
            INSERT INTO lecturas (invernadero_id, temperatura, humedad_suelo, fecha)
            VALUES (%s, %s, %s, %s)
        """, (invernadero_id, temperatura, humedad, fecha))

        # Registrar alerta si es necesario
        if temperatura > ALERT_TEMP:
            cursor.execute("""
                INSERT INTO alertas (invernadero_id, tipo, descripcion, fecha)
                VALUES (%s, %s, %s, %s)
            """, (invernadero_id, "TEMP_ALTA", 
                 f"Temperatura crítica: {temperatura}°C en {INVERNADEROS[invernadero_id]}", 
                 fecha))

        conn.commit()
        return jsonify({"status": "success"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

# Modifica el endpoint de tiempo real para usar la variable global
@app.route('/api/lecturas_realtime/<int:invernadero_id>')
def lecturas_realtime(invernadero_id):
    ultima_lectura = ultimas_lecturas.get(invernadero_id)
    
    if ultima_lectura:
        return jsonify({
            'fecha': ultima_lectura['fecha'].strftime('%Y-%m-%d %H:%M'),
            'temperatura': ultima_lectura['temperatura'],
            'humedad': ultima_lectura['humedad'],
            'estado': estado_suelo(ultima_lectura['humedad'])
        })
    else:
        return jsonify({'error': 'No hay datos disponibles'}), 404

# Añade esta función para obtener el historial rápido
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

@app.route('/api/estado_invernadero/<int:invernadero_id>')
def estado_invernadero(invernadero_id):
    """Obtiene el estado actual resumido de un invernadero"""
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
            return jsonify({'error': 'No hay datos'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

# Página principal
@app.route('/')
def home():
    content = """
    <div class="row text-center">
      <div class="col-md-6 mb-4">
        <div class="card dashboard-card">
          <div class="card-body">
            <h2 class="card-title">Invernaderos</h2>
            <p class="card-text">Monitoreo en tiempo real de todos los invernaderos</p>
            <a href="/invernaderos" class="btn btn-primary">Ver Invernaderos</a>
          </div>
        </div>
      </div>
      <div class="col-md-6 mb-4">
        <div class="card dashboard-card">
          <div class="card-body">
            <h2 class="card-title">Alertas</h2>
            <p class="card-text">Registro de alertas y eventos críticos</p>
            <a href="/alertas" class="btn btn-danger">Ver Alertas</a>
          </div>
        </div>
      </div>
    </div>
    """
    return render_template_string(BASE_HTML, title="Panel Principal", content=content)

# Página de invernaderos
@app.route('/invernaderos')
def listar_invernaderos():
    # Obtener últimos datos de cada invernadero
    ultimos_datos = {}
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        for invernadero_id in INVERNADEROS:
            cursor.execute("""
                SELECT temperatura, humedad_suelo as humedad, fecha
                FROM lecturas 
                WHERE invernadero_id = %s
                ORDER BY fecha DESC LIMIT 1
            """, (invernadero_id,))
            
            resultado = cursor.fetchone()
            if resultado:
                ultimos_datos[invernadero_id] = {
                    "temperatura": float(resultado['temperatura']) if resultado['temperatura'] is not None else None,
                    "humedad": int(resultado['humedad']) if resultado['humedad'] is not None else None,
                    "fecha": resultado['fecha'].strftime('%Y-%m-%d %H:%M') if resultado['fecha'] else "Sin datos"
                }
            else:
                ultimos_datos[invernadero_id] = {
                    "temperatura": None,
                    "humedad": None,
                    "fecha": "Sin datos"
                }

    except Exception as e:
        flash(f"Error al obtener datos: {str(e)}")
        ultimos_datos = {id: {
            "temperatura": None,
            "humedad": None,
            "fecha": "Error"
        } for id in INVERNADEROS}
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()

    # Generar tabla
    tabla = """
    <div class="card mb-4">
      <div class="card-header bg-primary text-white">
        <h3 class="mb-0">Listado de Invernaderos</h3>
      </div>
      <div class="card-body">
        <div class="table-responsive">
          <table class="table table-hover">
            <thead class="table-light">
              <tr>
                <th>Invernadero</th>
                <th>Temperatura</th>
                <th>Humedad</th>
                <th>Última Lectura</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
    """

    for id, nombre in INVERNADEROS.items():
        datos = ultimos_datos.get(id, {})
        temp = datos.get('temperatura')
        temp_class = 'critical-temp' if temp is not None and temp > ALERT_TEMP else ''
        
        # Formatear valores para mostrar
        temp_display = f"{temp} °C" if temp is not None else 'N/A'
        hum_display = f"{datos.get('humedad')} %" if datos.get('humedad') is not None else 'N/A'
        
        tabla += f"""
              <tr class="alert-row" data-invernadero-id="{id}">
                <td>{nombre}</td>
                <td class="temp-cell {temp_class}">{temp_display}</td>
                <td class="hum-cell">{hum_display}</td>
                <td class="fecha-cell">{datos.get('fecha', 'Sin datos')}</td>
                <td>
                  <a href="/invernadero/{id}" class="btn btn-sm btn-outline-primary">Ver Detalles</a>
                </td>
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
        title="Invernaderos",
        content=tabla
    )

# Detalle de invernadero
@app.route('/invernadero/<int:invernadero_id>')
def detalle_invernadero(invernadero_id):
    if invernadero_id not in INVERNADEROS:
        flash("Invernadero no encontrado")
        return redirect(url_for('listar_invernaderos'))
    
    # Obtener datos históricos iniciales
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

    # Generar tabla de lecturas recientes
    tabla_lecturas = f"""
    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h3 class="mb-0">Lecturas Recientes - {INVERNADEROS[invernadero_id]}</h3>
        <button id="btn-actualizar" class="btn btn-sm btn-primary">Actualizar Ahora</button>
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
        estado_class = ''
        
        if "Muy seco" in estado:
            estado_class = 'text-danger'
        elif "Seco" in estado:
            estado_class = 'text-warning'
        elif "Húmedo" in estado:
            estado_class = 'text-primary'
        else:
            estado_class = 'text-success'
        
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

    # Contenido completo con gráficas separadas
    content = f"""
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2>{INVERNADEROS[invernadero_id]}</h2>
      <div>
        <span id="status-indicator" class="badge bg-success me-2">Conectado</span>
        <a href="/invernaderos" class="btn btn-secondary">Volver</a>
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
    """

    return render_template_string(
        BASE_HTML,
        title=f"Detalles - {INVERNADEROS[invernadero_id]}",
        content=content,
        ALERT_TEMP=ALERT_TEMP
    )

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)