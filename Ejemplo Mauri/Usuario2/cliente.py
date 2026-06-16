#!/usr/bin/env python3
"""
Cliente de consola TCP compatible con el servidor C del protocolo definido.
Solo utiliza la biblioteca estándar de Python 3.
"""

import os
import socket
import sys
import threading
import traceback

DOWNLOAD_DIR = "downloads"
BUFFER_SIZE = 4096
TEXT_ENCODING = "utf-8"


def print_help():
    """Imprime los comandos disponibles en la consola."""
    print("Comandos disponibles:")
    print("  /list")
    print("  /msg usuario mensaje")
    print("  /broadcast mensaje")
    print("  /sendfile usuario ruta_archivo")
    print("  /ping")
    print("  /logout")
    print("  /help")
    print("")


class ReceiverThread(threading.Thread):
    """Hilo que recibe y procesa mensajes del servidor."""

    def __init__(self, sock, stop_event, file_start_event, file_complete_event):
        super().__init__(daemon=True)
        self.sock = sock
        self.stop_event = stop_event
        self.file_start_event = file_start_event
        self.file_complete_event = file_complete_event
        self.text_buffer = b""
        self.binary_file = None
        self.binary_remaining = 0
        self.binary_sender = ""
        self.binary_filename = ""

    def run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    data = self.sock.recv(BUFFER_SIZE)
                except OSError as exc:
                    if not self.stop_event.is_set():
                        print(f"\n[ERROR] Error de socket: {exc}")
                    self.stop_event.set()
                    break

                if not data:
                    print("\n[INFO] Desconectado del servidor.")
                    self.stop_event.set()
                    break

                self.process_bytes(data)
        except Exception:
            print("\n[ERROR] Error en el hilo receptor:")
            traceback.print_exc()
            self.stop_event.set()
        finally:
            if self.binary_file is not None:
                try:
                    self.binary_file.close()
                except Exception:
                    pass

    def process_bytes(self, data):
        """Procesa bytes recibidos, distinguiendo texto y datos binarios."""
        offset = 0
        while offset < len(data):
            if self.binary_file is not None:
                to_write = min(len(data) - offset, self.binary_remaining)
                chunk = data[offset:offset + to_write]
                self.binary_file.write(chunk)
                offset += to_write
                self.binary_remaining -= to_write
                if self.binary_remaining == 0:
                    self.binary_file.close()
                    self.binary_file = None
                    print(f"\n[INFO] Archivo recibido de {self.binary_sender}: {self.binary_filename}")
                    print_prompt()
                    self.binary_sender = ""
                    self.binary_filename = ""
                continue

            next_newline = data.find(b"\n", offset)
            if next_newline == -1:
                self.text_buffer += data[offset:]
                break

            self.text_buffer += data[offset:next_newline]
            offset = next_newline + 1
            line = self.text_buffer.decode(TEXT_ENCODING, errors="replace").rstrip("\r")
            self.text_buffer = b""
            self.process_line(line)

    def process_line(self, line):
        """Process a single line de texto del protocolo."""
        if not line:
            return

        parts = line.split("|")
        command = parts[0].upper()

        if command == "FROM" and len(parts) >= 3:
            sender = parts[1]
            message = "|".join(parts[2:])
            print(f"\n[PRIVADO] {sender}: {message}")
        elif command == "BROADCASTFROM" and len(parts) >= 3:
            sender = parts[1]
            message = "|".join(parts[2:])
            print(f"\n[BROADCAST] {sender}: {message}")
        elif command == "FILEFROM" and len(parts) >= 4:
            self.start_file_receive(parts)
            return
        elif command == "ACK" and len(parts) >= 2:
            subcommand = parts[1].upper()
            if subcommand == "LOGIN":
                print("\n[INFO] Login aceptado.")
            elif subcommand == "LOGOUT":
                print("\n[INFO] Logout aceptado. Cerrando cliente.")
                self.stop_event.set()
            elif subcommand == "LIST":
                if len(parts) >= 4:
                    count = parts[2]
                    users = parts[3].split(";") if parts[3] else []
                    print(f"\n[INFO] Usuarios conectados ({count}): {', '.join(users)}")
                else:
                    print("\n[INFO] Lista de usuarios recibida.")
            elif subcommand == "MSG":
                print("\n[INFO] Mensaje privado enviado.")
            elif subcommand == "BROADCAST":
                print("\n[INFO] Broadcast enviado.")
            elif subcommand == "FILE_START":
                self.file_start_event.set()
            elif subcommand == "FILE_COMPLETE":
                self.file_complete_event.set()
            else:
                print(f"\n[ACK] {'|'.join(parts[1:])}")
        elif command == "ERROR" and len(parts) >= 3:
            code = parts[1]
            description = "|".join(parts[2:])
            print(f"\n[ERROR] {description} (codigo {code})")
        elif command == "PONG":
            print("\n[PONG] Respuesta recibida.")
        else:
            print(f"\n[INFO] Mensaje no reconocido: {line}")

        print_prompt()

    def start_file_receive(self, parts):
        """Inicia la recepción de un archivo binario tras recibir FILEFROM."""
        sender = parts[1]
        filename = parts[2]
        try:
            filesize = int(parts[3])
        except ValueError:
            print(f"\n[ERROR] Tamaño de archivo inválido en FILEFROM: {parts[3]}")
            print_prompt()
            return

        if filesize < 0:
            print("\n[ERROR] Tamaño de archivo no puede ser negativo.")
            print_prompt()
            return

        if not os.path.isdir(DOWNLOAD_DIR):
            try:
                os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            except OSError as exc:
                print(f"\n[ERROR] No se pudo crear el directorio de descargas: {exc}")
                print_prompt()
                return

        filepath = os.path.join(DOWNLOAD_DIR, filename)
        try:
            self.binary_file = open(filepath, "wb")
        except OSError as exc:
            print(f"\n[ERROR] No se pudo abrir el archivo para escritura: {exc}")
            print_prompt()
            return

        self.binary_sender = sender
        self.binary_filename = filepath
        self.binary_remaining = filesize
        print(f"\n[INFO] Recibiendo archivo de {sender}: {filename} ({filesize} bytes)")
        print_prompt()


def print_prompt():
    """Imprime el prompt de entrada sin interferir con el hilo receptor."""
    sys.stdout.write("> ")
    sys.stdout.flush()


def prompt_server_info():
    """Solicita IP, puerto y nombre de usuario al usuario."""
    host = input("IP del servidor: ").strip()
    port_text = input("Puerto: ").strip()
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError("Puerto inválido")

    username = input("Nombre de usuario: ").strip()
    if not username:
        raise ValueError("Nombre de usuario no puede estar vacío")

    return host, port, username


def connect_to_server(host, port):
    """Crea y conecta el socket TCP al servidor."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    return sock


def send_line(sock, line):
    """Envía una línea de texto terminada en salto de línea."""
    data = (line + "\n").encode(TEXT_ENCODING)
    sock.sendall(data)


def send_file(sock, dest_user, file_path, file_start_event, file_complete_event, stop_event):
    """Envía un archivo al servidor siguiendo el protocolo FILE."""
    if not os.path.isfile(file_path):
        print(f"[ERROR] El archivo no existe: {file_path}")
        return

    filename = os.path.basename(file_path)
    filesize = os.path.getsize(file_path)

    if filesize < 0:
        print("[ERROR] El tamaño del archivo no puede ser negativo.")
        return

    file_start_event.clear()
    file_complete_event.clear()

    try:
        send_line(sock, f"FILE|{dest_user}|{filename}|{filesize}")
    except OSError as exc:
        print(f"[ERROR] No se pudo enviar FILE: {exc}")
        stop_event.set()
        return

    print("[INFO] Esperando ACK|FILE_START...")
    if not file_start_event.wait(timeout=10):
        print("[ERROR] No se recibió ACK|FILE_START.")
        return

    try:
        with open(file_path, "rb") as source_file:
            sent = 0
            while sent < filesize:
                chunk = source_file.read(BUFFER_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)
                sent += len(chunk)
                percent = (sent * 100) // filesize if filesize > 0 else 100
                print(f"[INFO] Enviando archivo... {percent}%", end="\r", flush=True)
    except OSError as exc:
        print(f"\n[ERROR] No se pudo leer o enviar el archivo: {exc}")
        stop_event.set()
        return
    except OSError as exc:
        print(f"\n[ERROR] Error de socket durante envío: {exc}")
        stop_event.set()
        return

    print("\n[INFO] Archivo enviado. Esperando ACK|FILE_COMPLETE...")
    if not file_complete_event.wait(timeout=30):
        print("[ERROR] No se recibió ACK|FILE_COMPLETE.")
        return

    print("[INFO] Transferencia completada correctamente.")


def main():
    print("Cliente TCP de consola para servidor de chat y archivos.")
    print_help()

    try:
        host, port, username = prompt_server_info()
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return

    try:
        sock = connect_to_server(host, port)
    except Exception as exc:
        print(f"[ERROR] No se pudo conectar al servidor: {exc}")
        return

    stop_event = threading.Event()
    file_start_event = threading.Event()
    file_complete_event = threading.Event()

    receiver = ReceiverThread(sock, stop_event, file_start_event, file_complete_event)
    receiver.start()

    try:
        send_line(sock, f"LOGIN|{username}")
    except OSError as exc:
        print(f"[ERROR] No se pudo enviar LOGIN: {exc}")
        stop_event.set()

    while not stop_event.is_set():
        try:
            print_prompt()
            line = input().strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[INFO] Interrupción recibida. Cerrando cliente.")
            stop_event.set()
            break

        if not line:
            continue

        if line.startswith("/"):
            parts = line.split(maxsplit=2)
            command = parts[0].lower()

            if command == "/list":
                try:
                    send_line(sock, "LIST")
                except OSError as exc:
                    print(f"[ERROR] No se pudo enviar LIST: {exc}")
                    stop_event.set()
            elif command == "/msg":
                if len(parts) < 3:
                    print("[ERROR] Uso: /msg usuario mensaje")
                    continue
                dest_user, message = parts[1], parts[2]
                try:
                    send_line(sock, f"MSG|{dest_user}|{message}")
                except OSError as exc:
                    print(f"[ERROR] No se pudo enviar MSG: {exc}")
                    stop_event.set()
            elif command == "/broadcast":
                if len(parts) < 2:
                    print("[ERROR] Uso: /broadcast mensaje")
                    continue
                message = line[len("/broadcast "):].strip()
                if not message:
                    print("[ERROR] El mensaje no puede estar vacío.")
                    continue
                try:
                    send_line(sock, f"BROADCAST|{message}")
                except OSError as exc:
                    print(f"[ERROR] No se pudo enviar BROADCAST: {exc}")
                    stop_event.set()
            elif command == "/ping":
                try:
                    send_line(sock, "PING")
                except OSError as exc:
                    print(f"[ERROR] No se pudo enviar PING: {exc}")
                    stop_event.set()
            elif command == "/logout":
                try:
                    send_line(sock, "LOGOUT")
                except OSError as exc:
                    print(f"[ERROR] No se pudo enviar LOGOUT: {exc}")
                stop_event.set()
            elif command == "/sendfile":
                if len(parts) < 3:
                    print("[ERROR] Uso: /sendfile usuario ruta_archivo")
                    continue
                dest_user = parts[1]
                file_path = parts[2]
                send_file(sock, dest_user, file_path, file_start_event, file_complete_event, stop_event)
            elif command == "/help":
                print_help()
            else:
                print("[ERROR] Comando desconocido. Escriba /help para ver los comandos.")
        else:
            print("[ERROR] Comando inválido. Todos los comandos comienzan con '/'.")

    try:
        sock.close()
    except Exception:
        pass

    receiver.join(timeout=1)
    print("[INFO] Cliente finalizado.")


if __name__ == "__main__":
    main()
