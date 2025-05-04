import socket
import logging
from datetime import datetime
import os
import sys

# Configuración del logging
logging.basicConfig(filename='servidor.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Configuración del servidor
HOST = '0.0.0.0'  # Escuchar en todas las interfaces
PORT = 12345       # Puerto en el que el servidor escuchará

# Función principal del servidor
def run_server():
    # Crear un socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        logging.info(f'Servidor escuchando en {HOST}:{PORT}')

        while True:
            conn, addr = s.accept()
            with conn:
                logging.info(f'Conexión desde {addr}')
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    break
                
                # Procesar el mensaje
                if data.startswith("hola soy "):
                    nombre = data[9:]  # Extraer el nombre
                    hora_actual = datetime.now().strftime("%H:%M:%S")
                    respuesta = f"{nombre}, la hora es {hora_actual}"
                    conn.sendall(respuesta.encode('utf-8'))
                    
                    # Guardar el nombre en el log
                    logging.info(f'Nombre recibido: {nombre}')
                else:
                    conn.sendall(b'Mensaje no reconocido')

if __name__ == "__main__":
    # Ejecutar el servidor en segundo plano
    if os.fork() > 0:
        sys.exit()  # Salir del proceso padre

    run_server()
