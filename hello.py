import socket
from datetime import datetime

# Configuración del servidor
HOST = '0.0.0.0'  # Escuchar en todas las interfaces
PORT = 12345       # Puerto en el que el servidor escuchará

# Crear un socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, PORT))
    s.listen()
    print(f'Servidor escuchando en {HOST}:{PORT}')

    while True:
        conn, addr = s.accept()
        with conn:
            print(f'Conexión desde {addr}')
            data = conn.recv(1024).decode('utf-8')
            if not data:
                break
            
            # Procesar el mensaje
            if data.startswith("hola soy "):
                nombre = data[9:]  # Extraer el nombre
                hora_actual = datetime.now().strftime("%H:%M:%S")
                respuesta = f"{nombre}, la hora es {hora_actual}"
                conn.sendall(respuesta.encode('utf-8'))
            else:
                conn.sendall(b'Mensaje no reconocido')

