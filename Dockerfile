# Usa una imagen base de Python. Puedes ajustar la versión si es necesario.
FROM python:3.13.5-slim-buster

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo de requerimientos e instala las dependencias.
# Esto se hace primero para aprovechar el cache de Docker si requirements.txt no cambia.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código de la aplicación al contenedor.
# Esto incluye controller.py, image_5a52b7.png, etc.
COPY . .

# Expone el puerto en el que la aplicación Flask se ejecutará.
# Flask por defecto usa el puerto 5000.
EXPOSE 5000

# Define la variable de entorno FLASK_APP para que Flask sepa cuál es tu aplicación.
# Esta es una variable de entorno de Flask, no las que usarías para la DB.
ENV FLASK_APP=controller.py

# Comando para ejecutar la aplicación Flask.
# --host=0.0.0.0 permite que la aplicación sea accesible desde fuera del contenedor.
# --port=5000 asegura que Flask escuche en el puerto que expusiste.
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]