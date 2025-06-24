from flask import Flask, request, render_template_string, redirect, url_for, flash, jsonify
import mysql.connector
from datetime import datetime
import serial
import serial.tools.list_ports
import threading
import time
from collections import deque
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "tu_clave_secreta"


WHATSAPP_NUMBER = "593979111576"
MAX_TEMP = 30  
SERIAL_PORT = None  
SERIAL_BAUDRATE = 9600


lecturas_activas = False
temp_history = deque(maxlen=6)
hum_history = deque(maxlen=6)
soil_moisture_history = deque(maxlen=6)
lecturas_realtime = deque(maxlen=6)


def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="admin",
        database="db_invernadero"
    )


BASE_HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>{{ titulo }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@3.7.0/dist/chart.min.js"></script>
  <style>
    .card {
      margin-bottom: 20px;
      box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .card-header {
      font-weight: bold;
    }
    .table-responsive {
      overflow-x: auto;
    }
    .alert-temperature {
      color: #dc3545;
      font-weight: bold;
    }
    .soil-dry {
      color: #dc3545; /* Rojo para suelo seco */
    }
    .soil-moist {
      color: #ffc107; /* Amarillo para suelo húmedo */
    }
    .soil-wet {
      color: #198754; /* Verde para suelo mojado */
    }
  </style>
</head>
<body class="bg-light">
  <div class="container mt-4">
    <h1 class="mb-4 text-center">{{ titulo }}</h1>
    {{ contenido|safe }}
    <a href="/" class="btn btn-secondary mt-4">Volver al Inicio</a>
  </div>

  <script>
    // Función para confirmación antes de eliminar
    function confirmDelete(id, tipo) {
      Swal.fire({
        title: 'CONFIRMACIÓN',
        text: '¿Está seguro de eliminar este ' + tipo + '?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#d33',
        confirmButtonText: 'Sí, eliminar',
        cancelButtonText: 'Cancelar'
      }).then((result) => {
        if (result.isConfirmed) {
          window.location.href = '/eliminar_' + tipo.toLowerCase() + '/' + id;
        }
      });
    }

    // Función para enviar alerta por WhatsApp
    function enviarAlerta(id) {
      Swal.fire({
        title: 'CONFIRMACIÓN',
        text: '¿Está seguro que desea enviar esta alerta por WhatsApp?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#d33',
        confirmButtonText: 'Sí, enviar',
        cancelButtonText: 'Cancelar'
      }).then((result) => {
        if (result.isConfirmed) {
          Swal.fire({
            title: 'Enviando...',
            text: 'Preparando el mensaje para WhatsApp',
            allowOutsideClick: false,
            didOpen: () => { Swal.showLoading(); }
          });
          
          fetch('/generar_enlace_whatsapp/' + id)
            .then(response => response.json())
            .then(data => {
              if (data.error) {
                Swal.fire('Error', data.error, 'error');
                return;
              }
              
              Swal.close();
              const newWindow = window.open(data.url, '_blank');
              
              if (!newWindow) {
                Swal.fire('Error', 'No se pudo abrir WhatsApp. Por favor, permite ventanas emergentes.', 'error');
              } else {
                Swal.fire({
                  title: 'Éxito',
                  text: 'El mensaje se ha abierto en WhatsApp',
                  icon: 'success',
                  timer: 2000,
                  showConfirmButton: false
                });
                setTimeout(() => location.reload(), 2000);
              }
            })
            .catch(error => {
              Swal.fire('Error', 'No se pudo generar el enlace de WhatsApp', 'error');
            });
        }
      });
    }

    // Mostrar alertas flash
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          Swal.fire({
            title: 'Éxito',
            text: "{{ message }}",
            icon: 'success',
            timer: 2000,
            showConfirmButton: false
          });
        {% endfor %}
      {% endif %}
    {% endwith %}
  </script>

  {% if titulo == "Monitoreo en Tiempo Real" %}
  <script>
    let tempChart, humChart;

    // Función para determinar la clase CSS según el valor de humedad del suelo
    function getSoilMoistureClass(value) {
      if (value > 800) return 'soil-dry';
      if (value > 400) return 'soil-moist';
      return 'soil-wet';
    }

    // Función para interpretar el estado del suelo
    function interpretSoilMoisture(value) {
      if (value > 800) return 'SECO';
      if (value > 400) return 'HÚMEDO';
      return 'MOJADO';
    }

    function crearGraficas(fechas, temperaturas, humedadesSuelo) {
      const ctxTemp = document.getElementById('tempChart').getContext('2d');
      const ctxHum = document.getElementById('humChart').getContext('2d');

      if (tempChart) tempChart.destroy();
      if (humChart) humChart.destroy();

      // Gráfica de temperatura (se mantiene igual)
      tempChart = new Chart(ctxTemp, {
        type: 'line',
        data: {
          labels: fechas,
          datasets: [{
            label: 'Temperatura (°C)',
            data: temperaturas,
            borderColor: 'rgb(255, 99, 132)',
            backgroundColor: 'rgba(255, 99, 132, 0.1)',
            tension: 0.1,
            fill: true
          }]
        },
        options: {
          responsive: true,
          scales: {
            y: {
              title: { display: true, text: 'Temperatura (°C)' }
            },
            x: {
              title: { display: true, text: 'Hora' },
              ticks: { maxRotation: 45, minRotation: 45 }
            }
          }
        }
      });

      // Nueva gráfica para humedad del suelo
      humChart = new Chart(ctxHum, {
        type: 'line',
        data: {
          labels: fechas,
          datasets: [{
            label: 'Humedad del Suelo (raw)',
            data: humedadesSuelo,
            borderColor: 'rgb(75, 192, 192)',
            backgroundColor: 'rgba(75, 192, 192, 0.1)',
            tension: 0.1,
            fill: true
          }]
        },
        options: {
          responsive: true,
          scales: {
            y: {
              min: 0,
              max: 1023,
              title: { display: true, text: 'Humedad Suelo (raw 0-1023)' },
              ticks: {
                callback: function(value) {
                  // Mostrar el estado interpretado en los ticks
                  if (value === 0) return '0 (MOJADO)';
                  if (value === 400) return '400 (HÚMEDO)';
                  if (value === 800) return '800 (SECO)';
                  if (value === 1023) return '1023 (MUY SECO)';
                  return value;
                }
              }
            },
            x: {
              title: { display: true, text: 'Hora' },
              ticks: { maxRotation: 45, minRotation: 45 }
            }
          },
          plugins: {
            tooltip: {
              callbacks: {
                afterLabel: function(context) {
                  const value = context.raw;
                  return `Estado: ${interpretSoilMoisture(value)}`;
                }
              }
            }
          }
        }
      });
    }

    function actualizarTablaYGraficas() {
      fetch('/api/lecturas_realtime')
        .then(response => response.json())
        .then(data => {
          // Actualizar tabla
          const tbody = document.querySelector('#tabla-realtime tbody');
          tbody.innerHTML = '';
          data.slice().reverse().forEach(lectura => {
            const tr = document.createElement('tr');
            const tempClass = lectura.temperatura > {{ MAX_TEMP }} ? 'alert-temperature' : '';
            const soilClass = getSoilMoistureClass(lectura.humedad_suelo);
            const soilStatus = interpretSoilMoisture(lectura.humedad_suelo);
            
            tr.innerHTML = `
              <td>${lectura.fecha}</td>
              <td class="${tempClass}">${lectura.temperatura}</td>
              <td class="${soilClass}" title="${soilStatus}">${lectura.humedad_suelo}</td>
            `;
            tbody.appendChild(tr);
          });

          // Preparar datos para gráficas
          const fechas = data.map(l => l.fecha);
          const temperaturas = data.map(l => l.temperatura);
          const humedadesSuelo = data.map(l => l.humedad_suelo);

          crearGraficas(fechas, temperaturas, humedadesSuelo);
        })
        .catch(err => {
          console.error('Error al obtener lecturas en tiempo real:', err);
        });
    }

    // Actualizar cada 5 segundos
    actualizarTablaYGraficas();
    setInterval(actualizarTablaYGraficas, 5000);
  </script>
  {% endif %}
</body>
</html>
"""

def leer_arduino():
    global SERIAL_PORT, lecturas_activas, lecturas_realtime, alerta_enviada

    alerta_enviada = False

    while True:
        try:
            if not lecturas_activas:
                time.sleep(1)
                continue

            if SERIAL_PORT is None or not SERIAL_PORT.is_open:
                ports = serial.tools.list_ports.comports()
                for port in ports:
                    if 'Arduino' in port.description or 'USB' in port.device:
                        try:
                            SERIAL_PORT = serial.Serial(port.device, SERIAL_BAUDRATE, timeout=2)
                            print(f"[CONEXIÓN] Conectado a {port.device}")
                            time.sleep(2)
                            break
                        except Exception as e:
                            print(f"[ERROR] No se pudo conectar a {port.device}: {e}")
                time.sleep(2)
                continue

            if SERIAL_PORT.in_waiting > 0:
                line = SERIAL_PORT.readline().decode('utf-8', errors='ignore').strip()
                if line and "Temperatura:" in line and "Humedad Ambiental:" in line and "Humedad del Suelo (raw):" in line:
                    try:
                        temp = float(line.split("Temperatura:")[1].split("°C")[0].strip())
                        humedad_raw_str = line.split("Humedad del Suelo (raw):")[1].split(",")[0].strip()
                        humedad_suelo = int(humedad_raw_str)

                        
                        if humedad_suelo > 800:
                            estado_suelo = "SECO"
                        elif humedad_suelo > 400:
                            estado_suelo = "HÚMEDO"
                        else:
                            estado_suelo = "MOJADO"

                        
                        lecturas_realtime.append({
                            "fecha": datetime.now(),
                            "temperatura": temp,
                            "humedad_suelo": humedad_suelo,
                            "estado_suelo": estado_suelo
                        })

                        conn = get_db_connection()
                        cursor = conn.cursor()

                        registrar_alerta = False
                        tipo_alerta = ""
                        descripcion_alerta = ""

                        
                        if not alerta_enviada:
                            if temp > MAX_TEMP:
                                tipo_alerta = "Temperatura Alta"
                                descripcion_alerta = f"Temperatura crítica: {temp}°C, Suelo: {humedad_suelo} ({estado_suelo})"
                                registrar_alerta = True
                            elif humedad_suelo > 800:
                                tipo_alerta = "Suelo Seco"
                                descripcion_alerta = f"Suelo seco detectado: {humedad_suelo} ({estado_suelo})"
                                registrar_alerta = True

                        if registrar_alerta:
                            
                            cursor.execute("""
                                INSERT INTO lecturas (id_sensor, temperatura, humedad_suelo)
                                VALUES (%s, %s, %s)
                            """, (1, temp, humedad_suelo))

                            
                            cursor.execute("""
                                INSERT INTO alertas (id_sensor, tipo_alerta, descripcion)
                                VALUES (%s, %s, %s)
                            """, (1, tipo_alerta, descripcion_alerta))

                            conn.commit()
                            alerta_enviada = True
                            print(f"[ALERTA] {descripcion_alerta}")

                        
                        elif alerta_enviada and temp <= MAX_TEMP and humedad_suelo <= 800:
                            print("[INFO] Valores normalizados. Se puede registrar nueva alerta.")
                            alerta_enviada = False

                    except Exception as e:
                        print(f"[ERROR] Procesando datos: {e}")
                    finally:
                        if cursor:
                            cursor.close()
                        if conn:
                            conn.close()

        except serial.SerialException as e:
            print(f"[ERROR] Serial: {e}")
            if SERIAL_PORT:
                SERIAL_PORT.close()
            SERIAL_PORT = None
            time.sleep(5)
        except Exception as e:
            print(f"[ERROR] Inesperado: {e}")
            time.sleep(5)


@app.route("/")
def index():
    contenido = """
    <hr>
    <div class="row">
      <div class="col-md-4">
        <div class="card">
          <div class="card-body text-center">
            <h5 class="card-title">Sensores</h5>
            <a href="/ver_sensores" class="btn btn-primary">Ver Sensores</a>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card">
          <div class="card-body text-center">
            <h5 class="card-title">Lecturas</h5>
            <a href="/monitoreo" class="btn btn-success">Monitoreo</a>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card">
          <div class="card-body text-center">
            <h5 class="card-title">Alertas</h5>
            <a href="/ver_alertas" class="btn btn-warning">Ver Alertas</a>
          </div>
        </div>
      </div>
    </div>
    """

    return render_template_string(
        BASE_HTML,
        titulo="Panel de Control",
        contenido=contenido,
        fechas=[],
        temperaturas=[],
        humedades=[]
    )


@app.route("/ver_sensores", methods=['GET', 'POST'])
def ver_sensores():
    if request.method == 'POST' and 'confirmar_sensor' in request.form:
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sensores (id_sensor, ubicacion, descripcion, fecha_instalacion)
                VALUES (%s, %s, %s, %s)
            """, (
                1,
                "Invernadero Claveles",
                "Sensor UTC",
                datetime.now().strftime('%Y-%m-%d')
            ))
            conn.commit()
            flash("Sensor registrado exitosamente")
        except Exception as e:
            flash(f"Error al registrar sensor: {str(e)}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    puertos_disponibles = []
    try:
        puertos = serial.tools.list_ports.comports()
        puertos_disponibles = [p.device for p in puertos if 'Arduino' in p.description or 'USB' in p.device]
    except Exception as e:
        print(f"Error detectando puertos: {e}")

    sensores = []
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sensores")
        sensores = cursor.fetchall()
    except Exception as e:
        flash(f"Error al obtener sensores: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    alerta_sensor = ""
    if puertos_disponibles and not sensores:
        alerta_sensor = f"""
        <div class="alert alert-info alert-dismissible fade show">
            <strong>¡Sensor detectado!</strong> Se ha encontrado un dispositivo en {puertos_disponibles[0]}. ¿Desea registrarlo?
            <form method="POST" class="mt-2">
                <input type="hidden" name="confirmar_sensor" value="1">
                <button type="submit" class="btn btn-primary btn-sm">Registrar Sensor</button>
            </form>
        </div>
        """

    tabla = f"""
    <hr>
    <div class="card">
        <div class="card-header bg-primary text-white">
            <h5 class="mb-0">Sensores Registrados</h5>
        </div>
        <div class="card-body">
            {alerta_sensor}
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Ubicación</th>
                            <th>Descripción</th>
                            <th>Fecha Instalación</th>
                            <th>Acciones</th>
                        </tr>
                    </thead>
                    <tbody>
    """

    for s in sensores:
        tabla += f"""
            <tr>
                <td>{s[0]}</td>
                <td>{s[1]}</td>
                <td>{s[2]}</td>
                <td>{s[3]}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="confirmDelete('{s[0]}','Sensor')">
                        Eliminar
                    </button>
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
    return render_template_string(BASE_HTML, 
                              titulo="Sensores Registrados", 
                              contenido=tabla,
                              fechas=[],
                              temperaturas=[],
                              humedades=[])


@app.route("/monitoreo")
def monitoreo():
    global lecturas_activas
    lecturas_activas = True

    conn = None
    cursor = None
    lecturas_a_mostrar = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        
        cursor.execute("""
            SELECT l.*, a.tipo_alerta, a.descripcion, s.ubicacion 
            FROM alertas a
            JOIN lecturas l ON a.id_sensor = l.id_sensor 
                AND DATE_FORMAT(a.fecha, '%Y-%m-%d %H:%i:%s') = DATE_FORMAT(l.fecha, '%Y-%m-%d %H:%i:%s')
            JOIN sensores s ON l.id_sensor = s.id_sensor
            ORDER BY a.fecha DESC
            LIMIT 2
        """)
        lecturas_a_mostrar = cursor.fetchall()

    except Exception as e:
        flash(f"Error al obtener lecturas altas: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    # =================== TABLA EN TIEMPO REAL ===================
    tabla_realtime = """
    <div class="card mb-4">
      <div class="card-header bg-primary text-white">
        <h5 class="mb-0">Lecturas en Tiempo Real</h5>
      </div>
      <div class="card-body table-responsive">
        <table id="tabla-realtime" class="table table-striped">
          <thead>
            <tr><th>Fecha</th><th>Temperatura (°C)</th><th>Humedad Suelo (raw)</th></tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
    <hr>
    """

    # =================== TABLA DE ALERTAS RECIENTES ===================
    tabla_altas = """
    <div class="card">
      <div class="card-header bg-warning text-dark">
        <h5 class="mb-0">Últimas Lecturas con Alertas</h5>
      </div>
      <div class="card-body table-responsive">
        <table class="table table-striped">
          <thead>
            <tr><th>Fecha</th><th>Tipo</th><th>Temperatura (°C)</th><th>Humedad Suelo</th><th>Ubicación</th></tr>
          </thead>
          <tbody>
    """

    for la in lecturas_a_mostrar:
        fecha_local = la['fecha'] - timedelta(hours=5)
        soil_class = ""
        if la['humedad_suelo'] > 800:
            soil_class = 'soil-dry'
        elif la['humedad_suelo'] > 400:
            soil_class = 'soil-moist'
        else:
            soil_class = 'soil-wet'

        tabla_altas += f"""
          <tr>
            <td>{fecha_local.strftime('%Y-%m-%d %H:%M:%S')}</td>
            <td>{la.get('tipo_alerta', 'Desconocida')}</td>
            <td class="alert-temperature">{la['temperatura']}</td>
            <td class="{soil_class}">{la['humedad_suelo']}</td>
            <td>{la['ubicacion']}</td>
          </tr>
        """

    tabla_altas += """
          </tbody>
        </table>
      </div>
    </div>
    """

    # =================== GRÁFICAS ===================
    graficos = """
    <div class="row mt-4">
      <div class="col-md-6">
        <div class="card">
          <div class="card-header bg-info text-white">Gráfica de Temperatura</div>
          <div class="card-body">
            <canvas id="tempChart" width="400" height="300"></canvas>
          </div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="card">
          <div class="card-header bg-info text-white">Gráfica de Humedad del Suelo</div>
          <div class="card-body">
            <canvas id="humChart" width="400" height="300"></canvas>
          </div>
        </div>
      </div>
    </div>
    <hr>
    """

    contenido = tabla_realtime + graficos + tabla_altas

    return render_template_string(
        BASE_HTML,
        titulo="Monitoreo en Tiempo Real",
        contenido=contenido,
        MAX_TEMP=MAX_TEMP,
        fechas=[],
        temperaturas=[],
        humedades=[]
    )

@app.route("/ver_alertas")
def ver_alertas():
    conn = None
    cursor = None
    alertas = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        
        cursor.execute("""
            SELECT a.*, s.ubicacion 
            FROM alertas a
            JOIN sensores s ON a.id_sensor = s.id_sensor
            ORDER BY a.fecha DESC
            LIMIT 2
        """)
        alertas = cursor.fetchall()

    except Exception as e:
        flash(f"Error al obtener alertas: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    if not alertas:
        contenido = "<div class='alert alert-info'>No hay alertas activas.</div>"
        return render_template_string(BASE_HTML, titulo="Alertas", contenido=contenido, fechas=[], temperaturas=[], humedades=[])

    tabla = f"""
    <hr>
    <div class="card">
      <div class="card-header bg-warning text-dark">
        <h5 class="mb-0">Alertas Críticas Recientes</h5>
      </div>
      <div class="card-body table-responsive">
        <table class="table table-striped">
          <thead>
            <tr><th>Fecha</th><th>Tipo</th><th>Descripción</th><th>Ubicación</th><th>Acciones</th></tr>
          </thead>
          <tbody>
    """

    for alerta in alertas:
        fecha_local = alerta['fecha'] - timedelta(hours=5)
        tabla += f"""
            <tr>
              <td>{fecha_local.strftime('%Y-%m-%d %H:%M:%S')}</td>
              <td>{alerta['tipo_alerta']}</td>
              <td>{alerta['descripcion']}</td>
              <td>{alerta['ubicacion']}</td>
              <td>
                <button class="btn btn-success btn-sm" onclick="enviarAlerta('{alerta['id_alerta']}')">WhatsApp</button>
              </td>
            </tr>
        """

    tabla += """
          </tbody>
        </table>
      </div>
    </div>
    """

    return render_template_string(BASE_HTML, titulo="Alertas", contenido=tabla, fechas=[], temperaturas=[], humedades=[])


@app.route("/eliminar_sensor/<int:id>")
def eliminar_sensor(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sensores WHERE id_sensor = %s", (id,))
        conn.commit()
        flash("Sensor eliminado correctamente")
    except Exception as e:
        flash(f"Error al eliminar sensor: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('ver_sensores'))

@app.route("/eliminar_alerta/<int:id>")
def eliminar_alerta(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM alertas WHERE id_alerta = %s", (id,))
        conn.commit()
        flash("Alerta eliminada correctamente")
    except Exception as e:
        flash(f"Error al eliminar alerta: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('ver_alertas'))


@app.route("/generar_enlace_whatsapp/<int:id>")
def generar_enlace_whatsapp(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        
        cursor.execute("""
            SELECT a.*, s.ubicacion 
            FROM alertas a 
            JOIN sensores s ON a.id_sensor = s.id_sensor 
            WHERE a.id_alerta = %s
        """, (id,))
        alerta = cursor.fetchone()

        if not alerta:
            return jsonify({"error": "No se encontró alerta con ese ID"}), 404

        fecha_local = alerta['fecha'] - timedelta(hours=5)
        mensaje = (
            "*ALERTA DEl INVERNADERO NUMERO UNO*\n\n"
            f"*Sensor*: {alerta['ubicacion']}\n"
            f"*Tipo*: {alerta['tipo_alerta']} en {alerta['ubicacion']}\n"
            f"*Descripción*: {alerta['descripcion']}\n"
            f"*Fecha*: {fecha_local.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "Este es un mensaje automático del sistema de monitoreo."
        )
        
        cursor.execute("DELETE FROM alertas WHERE id_alerta = %s", (id,))
        conn.commit()
        
        url = f"https://wa.me/{WHATSAPP_NUMBER}?text={mensaje.replace(' ', '%20').replace(chr(10), '%0A')}"
        return jsonify({"url": url})

    except Exception as e:
        return jsonify({"error": f"Error generando enlace WhatsApp: {e}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()



@app.route("/api/lecturas_realtime")
def api_lecturas_realtime():
    global lecturas_realtime
    data = [{
        "fecha": l["fecha"].strftime('%Y-%m-%d %H:%M:%S'),
        "temperatura": l["temperatura"],
        "humedad_suelo": l["humedad_suelo"]
    } for l in list(lecturas_realtime)]
    return jsonify(data)

if __name__ == "__main__":
    
    hilo_arduino = threading.Thread(target=leer_arduino, daemon=True)
    hilo_arduino.start()

    app.run(host="0.0.0.0", port=5000, debug=True)