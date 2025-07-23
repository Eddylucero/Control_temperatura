# Usa una imagen base de Python. Versión estable y soportada.
FROM python:3.12-slim-buster

# Directorio de trabajo
WORKDIR /app

# Copia requirements primero (para cache de capas Docker)
COPY requirements.txt .

# Instala dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo el código
COPY . .

# Expone el puerto de Flask
EXPOSE 5000

# Define variable de entorno para Flask
ENV FLASK_APP=controller.py

# Comando de arranque
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
