#!/usr/bin/env python3
"""
Cliente TCP con Interfaz Gráfica (GUI) para el servidor de chat y archivos.
Utiliza la biblioteca estándar 'tkinter' de Python.
"""

import os
import socket
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog
import queue
import platform
import subprocess

DOWNLOAD_DIR = "downloads"
BUFFER_SIZE = 4096
TEXT_ENCODING = "utf-8"


class ReceiverThread(threading.Thread):
    def __init__(
        self,
        sock,
        gui_queue,
        stop_event,
        file_start_event,
        file_complete_event,
        username,
    ):
        super().__init__(daemon=True)
        self.sock = sock
        self.gui_queue = gui_queue
        self.stop_event = stop_event
        self.file_start_event = file_start_event
        self.file_complete_event = file_complete_event
        self.username = username
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
                        self.gui_queue.put(("ERROR", f"Error de socket: {exc}"))
                    self.stop_event.set()
                    break

                if not data:
                    self.gui_queue.put(("INFO", "Desconectado del servidor."))
                    self.stop_event.set()
                    break

                self.process_bytes(data)
        except Exception as e:
            self.gui_queue.put(("ERROR", f"Error en receptor: {e}"))
            self.stop_event.set()
        finally:
            if self.binary_file is not None:
                try:
                    self.binary_file.close()
                except:
                    pass

    def process_bytes(self, data):
        offset = 0
        while offset < len(data):
            if self.binary_file is not None:
                to_write = min(len(data) - offset, self.binary_remaining)
                chunk = data[offset : offset + to_write]
                self.binary_file.write(chunk)
                offset += to_write
                self.binary_remaining -= to_write
                if self.binary_remaining == 0:
                    self.binary_file.close()
                    self.binary_file = None
                    self.gui_queue.put(
                        (
                            "FILE_RECEIVED",
                            self.binary_sender,
                            self.binary_filename,
                        )
                    )
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
        if not line:
            return
        parts = line.split("|")
        command = parts[0].upper()

        if command == "FROM" and len(parts) >= 3:
            sender, message = parts[1], "|".join(parts[2:])
            self.gui_queue.put(("MSG", sender, message))
        elif command == "BROADCASTFROM" and len(parts) >= 3:
            sender, message = parts[1], "|".join(parts[2:])
            self.gui_queue.put(("BROADCAST", sender, message))
        elif command == "FILEFROM" and len(parts) >= 4:
            self.start_file_receive(parts)
        elif command == "ACK" and len(parts) >= 2:
            subcommand = parts[1].upper()
            if subcommand == "LOGIN":
                self.gui_queue.put(("LOGIN_OK", "Login aceptado por el servidor."))
            elif subcommand == "LOGOUT":
                self.gui_queue.put(("INFO", "Logout aceptado."))
                self.stop_event.set()
            elif subcommand == "LIST":
                if len(parts) >= 4:
                    users = parts[3].split(";") if parts[3] else []
                    self.gui_queue.put(("USERS", users))
            elif subcommand == "FILE_START":
                self.file_start_event.set()
            elif subcommand == "FILE_COMPLETE":
                self.file_complete_event.set()
        elif command == "ERROR" and len(parts) >= 3:
            self.gui_queue.put(("ERROR", f"{'|'.join(parts[2:])} (Error {parts[1]})"))
        elif command == "PONG":
            self.gui_queue.put(("INFO", "PONG recibido del servidor."))

    def start_file_receive(self, parts):
        sender, filename = parts[1], parts[2]
        try:
            filesize = int(parts[3])
        except ValueError:
            return

        user_download_dir = f"downloads_{self.username}"
        if not os.path.isdir(user_download_dir):
            os.makedirs(user_download_dir, exist_ok=True)

        filepath = os.path.join(user_download_dir, filename)
        try:
            self.binary_file = open(filepath, "wb")
            self.binary_sender = sender
            self.binary_filename = filepath
            self.binary_remaining = filesize
            self.gui_queue.put(
                (
                    "INFO",
                    f"Recibiendo archivo de {sender}: {filename} ({filesize} bytes)...",
                )
            )
        except OSError as exc:
            self.gui_queue.put(("ERROR", f"No se pudo crear el archivo: {exc}"))


def send_file_thread(
    sock,
    dest_user,
    file_path,
    file_start_event,
    file_complete_event,
    stop_event,
    gui_queue,
):
    filename = os.path.basename(file_path)
    filesize = os.path.getsize(file_path)

    file_start_event.clear()
    file_complete_event.clear()

    try:
        sock.sendall(f"FILE|{dest_user}|{filename}|{filesize}\n".encode(TEXT_ENCODING))
    except OSError:
        gui_queue.put(("ERROR", "No se pudo enviar solicitud de archivo."))
        return

    gui_queue.put(("INFO", "Esperando aceptación del archivo por el servidor..."))
    if not file_start_event.wait(timeout=10):
        gui_queue.put(
            (
                "ERROR",
                "El servidor no respondió a la solicitud de archivo en el tiempo límite.",
            )
        )
        return

    gui_queue.put(("INFO", "Enviando bytes del archivo..."))
    try:
        with open(file_path, "rb") as f:
            sent = 0
            while sent < filesize:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)
                sent += len(chunk)
    except OSError as exc:
        gui_queue.put(("ERROR", f"Error enviando archivo: {exc}"))
        return

    if not file_complete_event.wait(timeout=30):
        gui_queue.put(
            ("ERROR", "No se recibió confirmación final de transferencia del servidor.")
        )
        return

    gui_queue.put(("INFO", "Transferencia de archivo completada correctamente."))


class ChatGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat TCP - Login")
        self.sock = None
        self.stop_event = threading.Event()
        self.gui_queue = queue.Queue()
        self.file_start_event = threading.Event()
        self.file_complete_event = threading.Event()
        self.receiver = None
        self.username = ""
        self.chat_display = None

        self.setup_login_ui()
        self.root.after(100, self.process_queue)

    def setup_login_ui(self):
        self.frame = tk.Frame(self.root, padx=20, pady=20)
        self.frame.pack()

        tk.Label(self.frame, text="IP Servidor:").grid(row=0, column=0, sticky="e")
        self.ip_entry = tk.Entry(self.frame)
        self.ip_entry.insert(0, "127.0.0.1")
        self.ip_entry.grid(row=0, column=1)

        tk.Label(self.frame, text="Puerto:").grid(row=1, column=0, sticky="e")
        self.port_entry = tk.Entry(self.frame)
        self.port_entry.insert(0, "5000")
        self.port_entry.grid(row=1, column=1)

        tk.Label(self.frame, text="Usuario:").grid(row=2, column=0, sticky="e")
        self.user_entry = tk.Entry(self.frame)
        self.user_entry.grid(row=2, column=1)
        self.user_entry.focus()

        self.connect_btn = tk.Button(self.frame, text="Conectar", command=self.connect)
        self.connect_btn.grid(row=3, column=0, columnspan=2, pady=10)
        self.root.bind("<Return>", lambda event: self.connect())

    def connect(self):
        host = self.ip_entry.get().strip()
        port_txt = self.port_entry.get().strip()
        self.username = self.user_entry.get().strip()

        if not self.username:
            messagebox.showerror("Error", "Ingrese un nombre de usuario")
            return

        self.connect_btn.config(state="disabled")
        self.root.unbind("<Return>")

        try:
            port = int(port_txt)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, port))
        except Exception as e:
            messagebox.showerror("Error de conexión", f"No se pudo conectar: {e}")
            self.connect_btn.config(state="normal")
            self.root.bind("<Return>", lambda event: self.connect())
            return

        self.stop_event.clear()
        # Iniciar hilo receptor
        self.receiver = ReceiverThread(
            self.sock,
            self.gui_queue,
            self.stop_event,
            self.file_start_event,
            self.file_complete_event,
            self.username,
        )
        self.receiver.start()

        # Enviar intento de login
        self.send_cmd(f"LOGIN|{self.username}")
        # El cambio de interfaz se hará cuando recibamos LOGIN_OK en process_queue

    def setup_chat_ui(self):
        self.root.title(f"Chat TCP - Conectado como: {self.username}")
        self.root.geometry("650x450")

        # Paneles principales
        right_panel = tk.Frame(self.root, width=150)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)

        left_panel = tk.Frame(self.root)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Controles inferiores (Entrada y envío) - Se empaquetan en el fondo primero
        bottom_frame = tk.Frame(left_panel)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        # Historial de Chat
        self.chat_display = scrolledtext.ScrolledText(
            left_panel, state="disabled", wrap=tk.WORD
        )
        self.chat_display.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Configurar colores de etiquetas para los distintos mensajes
        self.chat_display.tag_config("sent_private", foreground="blue")
        self.chat_display.tag_config("recv_private", foreground="green")
        self.chat_display.tag_config("sent_broadcast", foreground="purple")
        self.chat_display.tag_config("recv_broadcast", foreground="darkorange")
        self.chat_display.tag_config("system", foreground="gray")
        self.chat_display.tag_config("error", foreground="red")

        self.msg_entry = tk.Entry(bottom_frame)
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.msg_entry.bind("<Return>", lambda e: self.send_message())
        self.msg_entry.focus()

        tk.Button(bottom_frame, text="Enviar", command=self.send_message).pack(
            side=tk.LEFT, padx=5
        )
        self.broadcast_var = tk.BooleanVar()
        tk.Checkbutton(
            bottom_frame, text="Broadcast", variable=self.broadcast_var
        ).pack(side=tk.LEFT)

        # Panel lateral derecho (Usuarios y acciones)
        tk.Label(right_panel, text="Usuarios en línea:").pack()
        self.user_listbox = tk.Listbox(right_panel)
        self.user_listbox.pack(fill=tk.BOTH, expand=True, pady=5)

        tk.Button(
            right_panel, text="Actualizar Lista", command=lambda: self.send_cmd("LIST")
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            right_panel, text="Enviar Archivo", command=self.send_file_dialog
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            right_panel, text="Ping Servidor", command=lambda: self.send_cmd("PING")
        ).pack(fill=tk.X, pady=2)
        tk.Button(right_panel, text="Desconectar", command=self.logout, fg="red").pack(
            fill=tk.X, pady=10
        )

    def append_text(self, text, tags=None):
        if not self.chat_display:
            return
        self.chat_display.config(state="normal")
        if tags:
            self.chat_display.insert(tk.END, text + "\n", tags)
        else:
            self.chat_display.insert(tk.END, text + "\n")
        self.chat_display.yview(tk.END)
        self.chat_display.config(state="disabled")

    def send_cmd(self, cmd):
        if self.sock and not self.stop_event.is_set():
            try:
                self.sock.sendall((cmd + "\n").encode(TEXT_ENCODING))
            except Exception as e:
                if self.chat_display:
                    self.append_text(
                        f"[ERROR SISTEMA] No se pudo enviar el comando: {e}", "error"
                    )
                else:
                    messagebox.showerror("Error", f"No se pudo enviar el comando: {e}")

    def send_message(self):
        msg = self.msg_entry.get().strip()
        if not msg:
            return

        if self.broadcast_var.get():
            self.send_cmd(f"BROADCAST|{msg}")
            self.append_text(f"[Tú a Todos]: {msg}", "sent_broadcast")
        else:
            sel = self.user_listbox.curselection()
            if not sel:
                messagebox.showwarning(
                    "Atención",
                    "Seleccione un destinatario de la lista a la derecha, o marque la casilla 'Broadcast'.",
                )
                return
            dest = self.user_listbox.get(sel[0])
            self.send_cmd(f"MSG|{dest}|{msg}")
            self.append_text(f"[Tú a {dest}]: {msg}", "sent_private")

        self.msg_entry.delete(0, tk.END)

    def send_file_dialog(self):
        sel = self.user_listbox.curselection()
        if not sel:
            messagebox.showwarning(
                "Atención",
                "Seleccione a quién desea enviar el archivo en la lista de usuarios.",
            )
            return
        dest = self.user_listbox.get(sel[0])

        filepath = filedialog.askopenfilename(
            title=f"Seleccionar archivo para enviar a {dest}"
        )
        if not filepath:
            return

        # Ejecutar envío de archivo en hilo separado para no congelar la GUI
        threading.Thread(
            target=send_file_thread,
            args=(
                self.sock,
                dest,
                filepath,
                self.file_start_event,
                self.file_complete_event,
                self.stop_event,
                self.gui_queue,
            ),
            daemon=True,
        ).start()

    def open_file(self, filepath):
        try:
            if platform.system() == "Windows":
                os.startfile(filepath)
            elif platform.system() == "Darwin":
                subprocess.call(("open", filepath))
            else:
                subprocess.call(("xdg-open", filepath))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir el archivo: {e}")

    def process_queue(self):
        """Procesa mensajes recibidos del hilo de red para actualizar la GUI de forma segura."""
        while not self.gui_queue.empty():
            try:
                item = self.gui_queue.get()
                type_ = item[0]
                if type_ == "LOGIN_OK":
                    if hasattr(self, "frame") and self.frame.winfo_exists():
                        self.frame.destroy()
                    self.setup_chat_ui()
                    self.append_text(
                        "=======================================", "system"
                    )
                    self.append_text(f"✅ {item[1]}", "system")
                    self.append_text(
                        f"👋 ¡Bienvenido al chat, {self.username}!", "system"
                    )
                    self.append_text(
                        "👉 Escribe un mensaje abajo y presiona Enviar.", "system"
                    )
                    self.append_text(
                        "👉 Selecciona un usuario a la derecha para un chat privado.",
                        "system",
                    )
                    self.append_text(
                        "👉 O marca la casilla 'Broadcast' para hablar con todos.",
                        "system",
                    )
                    self.append_text(
                        "=======================================", "system"
                    )
                    self.root.after(100, lambda: self.send_cmd("LIST"))
                elif type_ == "MSG":
                    self.append_text(f"[{item[1]}]: {item[2]}", "recv_private")
                elif type_ == "BROADCAST":
                    self.append_text(f"[📢 {item[1]}]: {item[2]}", "recv_broadcast")
                elif type_ == "FILE_RECEIVED":
                    sender = item[1]
                    filepath = item[2]
                    filename = os.path.basename(filepath)
                    if hasattr(self, "chat_display") and self.chat_display:
                        self.append_text(
                            f"[*] Archivo recibido de {sender}: {filename}", "system"
                        )
                    if messagebox.askyesno(
                        "Archivo recibido",
                        f"{sender} te ha enviado un archivo:\n{filename}\n\n¿Deseas abrirlo?",
                    ):
                        self.open_file(filepath)
                elif type_ == "INFO":
                    if hasattr(self, "chat_display") and self.chat_display:
                        self.append_text(f"[*] {item[1]}", "system")
                elif type_ == "ERROR":
                    if hasattr(self, "chat_display") and self.chat_display:
                        self.append_text(f"[❌ ERROR] {item[1]}", "error")
                    else:
                        messagebox.showerror("Error", item[1])
                        self.stop_event.set()
                        if (
                            hasattr(self, "connect_btn")
                            and self.connect_btn.winfo_exists()
                        ):
                            self.connect_btn.config(state="normal")
                            self.root.bind("<Return>", lambda event: self.connect())
                elif type_ == "USERS":
                    if hasattr(self, "user_listbox") and self.user_listbox:
                        self.user_listbox.delete(0, tk.END)
                        count = 0
                        for u in item[1]:
                            if u and u != self.username:
                                self.user_listbox.insert(tk.END, u)
                                count += 1
                        if count == 0:
                            self.user_listbox.insert(tk.END, "(Nadie más en línea)")
            except Exception as e:
                print(f"[DEBUG] Error procesando cola GUI: {e}")

        if self.stop_event.is_set():
            if self.chat_display and hasattr(self, "msg_entry"):
                if self.msg_entry.cget("state") != "disabled":
                    self.append_text("[*] Conexión terminada.", "system")
                    self.msg_entry.config(state="disabled")
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
                self.sock = None

        # Mantener el bucle vivo para permitir reconexiones en la misma ventana
        try:
            self.root.after(100, self.process_queue)
        except Exception:
            pass

    def logout(self):
        self.send_cmd("LOGOUT")
        self.stop_event.set()

    def on_closing(self):
        self.stop_event.set()
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ChatGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
