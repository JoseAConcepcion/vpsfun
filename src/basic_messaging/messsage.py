import socket

HOST = '104.131.172.104'  
PORT = 12345  

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    mensaje = 'hola soy ' #tu nombre aqui
    s.sendall(mensaje.encode('utf-8'))
    data = s.recv(1024)

print('Respuesta del servidor:', data.decode('utf-8'))
