# Protocolo de Aplicación TCP para Chat y Transferencia de Archivos

## Objetivo del protocolo

Especificación definitiva para una aplicación cliente-servidor TCP con:
- Servidor en C
- Cliente en Python
- Comunicación TCP, múltiples clientes concurrentes
- Chat privado y broadcast
- Transferencia de archivos por TCP (modo binario)
- Lista de usuarios conectados
- Desconexión controlada
- Manejo de errores

El servidor mantiene una tabla que asocia sockets a nombres de usuario válidos y disponibles. El protocolo evita redundancias enviando solo la información mínima necesaria.

---

## Formato general de los mensajes

- Codificación: UTF-8
- Delimitador de campo: `|`
- Cada comando es una línea terminada en `\n` (modo texto) salvo durante la transferencia binaria de archivos.
- Formato general (texto): `COMANDO|campo1|campo2|...|campoN\n`
- El primer campo siempre es el comando en mayúsculas.
- El servidor identifica el remitente por el socket origen; por tanto los clientes no envían su propio nombre.
- Para campos de texto que pueden contener `|`, se recomienda evitarlos o implementar escaping en la capa de aplicación.

---

## Comandos soportados 

- Cliente -> Servidor:
  - `LOGIN|username`
  - `LOGOUT`
  - `LIST`
  - `MSG|destinatario|mensaje`
  - `BROADCAST|mensaje`
  - `FILE|destinatario|filename|filesize`
  - `PING`

- Servidor -> Cliente (ack/error/eventos):
  - `ACK|COMANDO` (ver variantes)
  - `ERROR|codigo|descripcion`
  - `FROM|remitente|mensaje` (evento privado recibido)
  - `BROADCASTFROM|remitente|mensaje` (evento broadcast)
  - `FILEFROM|remitente|filename|filesize` (inicio de transferencia)
  - `PONG`

---

## Códigos de error 

- `100` - Usuario ya conectado
- `101` - Nombre de usuario inválido
- `102` - Usuario no autenticado
- `103` - Usuario desconocido u offline
- `104` - Formato de mensaje inválido
- `105` - Error de transferencia de archivo
- `106` - Comando no permitido
- `107` - Entrega de mensaje fallida
- `108` - Violación de protocolo
- `109` - Archivo excede tamaño máximo

Ejemplos:
- `ERROR|100|Usuario ya conectado`
- `ERROR|103|Usuario no conectado`

---

## LOGIN

- Cliente -> Servidor: `LOGIN|username`
  - `username` debe ser válido (formato permitido) y estar disponible.
- Servidor procesa:
  - Si válido y disponible: asocia socket -> username y responde `ACK|LOGIN`
  - Si inválido o en uso: responde `ERROR|100|Usuario ya conectado` o `ERROR|101|Nombre de usuario inválido`

Ejemplo:
- Cliente: `LOGIN|alice\n`
- Servidor: `ACK|LOGIN\n`

---

## LOGOUT

- Cliente -> Servidor: `LOGOUT\n`
- Servidor procesa:
  - Cierra sesión del usuario asociado al socket y responde `ACK|LOGOUT`

Ejemplo:
- Cliente: `LOGOUT\n`
- Servidor: `ACK|LOGOUT\n`

---

## LIST

- Cliente -> Servidor: `LIST\n`
- Servidor -> Cliente: `ACK|LIST|count|user1;user2;user3\n`
- Si `count` es 0, la respuesta será `ACK|LIST|0|\n`
- Si el cliente no está autenticado: `ERROR|102|Usuario no autenticado`

Ejemplo (sin usuarios):
- Cliente: `LIST\n`
- Servidor: `ACK|LIST|0|\n`

Ejemplo (con usuarios):
- Servidor: `ACK|LIST|2|bob;carla\n`

---

## MSG (mensaje privado)

- Cliente -> Servidor: `MSG|destinatario|mensaje\n`
  - `destinatario`: nombre de usuario destino
  - `mensaje`: texto libre (todo lo que sigue hasta el `\n`)
- Servidor valida:
  - Origen autenticado, destinatario existe y está online
  - Si válido: reenvía al destinatario el evento:
    - `FROM|remitente|mensaje\n`
  - Responde al remitente: `ACK|MSG\n`
  - Si falla: `ERROR|103|Usuario no conectado` o `ERROR|104|Formato de mensaje inválido`

Ejemplo:
- Cliente (alice): `MSG|bob|Hola Bob, ¿estás?\n`
- Servidor -> bob: `FROM|alice|Hola Bob, ¿estás?\n`
- Servidor -> alice: `ACK|MSG\n`

---

## BROADCAST

- Cliente -> Servidor: `BROADCAST|mensaje\n`
- Servidor valida y reenvía a todos los clientes conectados (excepto posible filtro de origen) el evento:
  - `BROADCASTFROM|remitente|mensaje\n`
- Servidor responde: `ACK|BROADCAST\n`
- Si falla: `ERROR|106|Comando no permitido` o `ERROR|104|Formato de mensaje inválido`

Ejemplo:
- Cliente: `BROADCAST|Buenos días a todos\n`
- Servidor -> todos: `BROADCASTFROM|alice|Buenos días a todos\n`
- Servidor -> cliente origen: `ACK|BROADCAST\n`

---

## FILE (nuevo flujo: negociación + transferencia binaria)

Diseño: el protocolo usa dos fases para transferir archivos. La negociación se realiza en modo texto; la transferencia de datos se realiza en modo binario leyendo exactamente `filesize` bytes del socket.

1) Inicio (cliente solicita envío)
- Cliente -> Servidor: `FILE|destinatario|filename|filesize\n`
  - `filesize` es entero decimal con número exacto de bytes a enviar.

2) Aceptación del servidor
- Servidor -> Cliente (origen): `ACK|FILE\n`  (si acepta)
- En caso de rechazo: `ERROR|105|Transferencia fallida` o `ERROR|109|Archivo excede tamaño máximo`

3) Notificación al destinatario
- Servidor -> Destinatario: `FILEFROM|remitente|filename|filesize\n`
  - Destinatario debe estar preparado para leer exactamente `filesize` bytes binarios inmediatamente después del `FILEFROM` (si el servidor implementa push directo), o el servidor coordina el flujo para que el origen envíe los bytes a continuación.

4) Transferencia de bytes
- Tras `ACK|FILE`, el cliente origen envía exactamente `filesize` bytes binarios por la misma conexión TCP (sin delimitadores de línea durante este bloque).
- El servidor debe leer exactamente `filesize` bytes del socket del remitente y reenviarlos (pipe) al socket del destinatario; o bien almacenar temporalmente si la arquitectura lo requiere.

5) Confirmación final
- Al completar la recepción y reenvío, el servidor envía `ACK|FILE\n` al remitente y opcionalmente al destinatario.
- En caso de fallo durante la transferencia: `ERROR|105|Transferencia fallida`

Ejemplo completo:
- Cliente (alice) -> Servidor: `FILE|bob|foto.jpg|20480\n`
- Servidor -> Alice: `ACK|FILE\n`
- Servidor -> Bob: `FILEFROM|alice|foto.jpg|20480\n`
- Cliente (alice) -> Servidor: <envía 20480 bytes binarios>
- Servidor -> Cliente (alice): `ACK|FILE\n`
- Servidor -> Cliente (bob): `ACK|FILE\n` (opcional)

Notas:
- El servidor debe manejar correctamente la lectura binaria y no mezclarla con el modo texto de comandos.
- Si el servidor reenvía los bytes en streaming, debe garantizar orden y bloqueo hasta completar `filesize` bytes.

---

## ACK 

- Formato único: `ACK|COMANDO\n`
- Ejemplos:
  - `ACK|LOGIN\n`
  - `ACK|LIST|2|bob;carla\n` (para `LIST` se incluye el payload)
  - `ACK|MSG\n`
  - `ACK|BROADCAST\n`
  - `ACK|FILE\n`

Variante opcional para `FILE`:
- `ACK|FILE|bytes_received` (si se requiere más detalle)

---

## ERROR 

- Formato único: `ERROR|codigo|descripcion\n`
- Ejemplo: `ERROR|105|Transferencia fallida\n`

---

## PING / PONG

- Cliente -> Servidor: `PING\n`
- Servidor -> Cliente: `PONG\n`

Usados para detectar sockets muertos y mantener sesiones.

---

## Diagramas de secuencia 

### A. Mensaje privado

```
Alice -> Servidor: LOGIN|alice\n
Servidor -> Alice: ACK|LOGIN\n
Alice -> Servidor: MSG|bob|Hola Bob!\n
Servidor -> Bob: FROM|alice|Hola Bob!\n
Servidor -> Alice: ACK|MSG\n
```

### B. Broadcast

```
Alice -> Servidor: BROADCAST|Buenos días a todos\n
Servidor -> Todos: BROADCASTFROM|alice|Buenos días a todos\n
Servidor -> Alice: ACK|BROADCAST\n
```

### C. Transferencia de archivo (negociación + binario)

```
Alice -> Servidor: FILE|bob|foto.jpg|20480\n
Servidor -> Alice: ACK|FILE\n
Servidor -> Bob: FILEFROM|alice|foto.jpg|20480\n
# Alice envía 20480 bytes binarios al Servidor (raw)
Alice -> Servidor: <20480 bytes>
# Servidor reenvía 20480 bytes binarios a Bob (raw)
Servidor -> Bob: <20480 bytes>
Servidor -> Alice: ACK|FILE\n
```

---

## Notas de implementación (actualizadas)

- Todos los comandos de protocolo en modo texto deben terminar con `\n`.
- El parser de línea debe dividir el buffer por `|` y tomar el resto de la línea como payload cuando corresponda.
- Para `FILE`, el servidor y clientes deben manejar un modo binario: tras la negociación y `ACK|FILE`, leer exactamente `filesize` bytes sin esperar `\n` dentro del bloque binario.
- Después de leer/reenviar exactamente `filesize` bytes, el lado receptor vuelve al modo línea (texto) y procesa el siguiente comando que termine en `\n`.
- En C (servidor): usar `recv()`/`read()` con contador de bytes para bloques binarios; usar `select/poll/epoll` o hilos para multiplexar.
- En Python (cliente): usar `socket.recv()` y bucles hasta acumular `filesize` bytes.
- Establecer límites razonables (p. ej. `filesize` máximo) y validar antes de aceptar la transferencia para evitar DoS.

---

## Versión final recomendada para implementación

### Comandos que debe implementar el servidor (C)
- Parsear y procesar (texto): `LOGIN|username`, `LOGOUT`, `LIST`, `MSG|dest|msg`, `BROADCAST|msg`, `FILE|dest|filename|filesize`, `PING`
- Responder/emitir: `ACK|...`, `ERROR|...`, `FROM|...`, `BROADCASTFROM|...`, `FILEFROM|...`, `PONG`
- Gestionar la transición a/desde modo binario para `FILE` y leer/escribir exactamente `filesize` bytes.

### Comandos que debe implementar el cliente (Python)
- Envío (texto): `LOGIN|username\n`, `LOGOUT\n`, `LIST\n`, `MSG|dest|msg\n`, `BROADCAST|msg\n`, `FILE|dest|filename|filesize\n`, `PING\n`
- Recepción/handle: `ACK|...`, `ERROR|...`, `FROM|sender|msg\n`, `BROADCASTFROM|sender|msg\n`, `FILEFROM|sender|filename|filesize\n`, `PONG\n`
- Si el cliente inicia una `FILE`, tras `ACK|FILE` debe enviar `filesize` bytes binarios.
- Si el cliente recibe `FILEFROM`, debe prepararse para leer `filesize` bytes binarios desde su socket (si el servidor la entrega directamente).

### Códigos de error definitivos
- `100` - Usuario ya conectado
- `101` - Nombre de usuario inválido
- `102` - Usuario no autenticado
- `103` - Usuario desconocido u offline
- `104` - Formato de mensaje inválido
- `105` - Error de transferencia de archivo
- `106` - Comando no permitido
- `107` - Entrega de mensaje fallida
- `108` - Violación de protocolo
- `109` - Archivo excede tamaño máximo

---
