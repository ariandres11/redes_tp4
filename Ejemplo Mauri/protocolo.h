// protocolo.h
// Definiciones y API del protocolo de la práctica
// Implementación en C para el servidor TCP.

#ifndef PROTOCOLO_H
#define PROTOCOLO_H

#include <sys/types.h>

#define DELIM "|"
#define MAX_USERNAME 64

// Códigos de error definitivos
#define ERR_USER_ALREADY_CONNECTED 100
#define ERR_INVALID_USERNAME 101
#define ERR_NOT_AUTHENTICATED 102
#define ERR_UNKNOWN_USER 103
#define ERR_INVALID_FORMAT 104
#define ERR_TRANSFER 105
#define ERR_NOT_ALLOWED 106
#define ERR_DELIVERY_FAILED 107
#define ERR_PROTOCOL_VIOLATION 108
#define ERR_FILE_TOO_LARGE 109

// Usuario conectado
typedef struct user {
    char username[MAX_USERNAME];
    int sockfd;
    struct user *next;
} user_t;

// Inicializa la tabla de usuarios (llamada en main)
void users_init(void);

// Añade usuario; devuelve 0 éxito, -1 si nombre inválido, -2 si duplicado
int user_add(const char *username, int sockfd);

// Elimina usuario por socket
void user_remove_by_sock(int sockfd);

// Comprueba si existe usuario
int user_exists(const char *username);

// Obtiene listado en formato "user1;user2;...". El buffer debe ser liberado por el llamador
char *user_list_dup(void);

// Busca nombre por socket; retorna NULL si no autenticado (no debe liberarse)
const char *user_name_by_sock(int sockfd);

// Busca socket por nombre de usuario; retorna -1 si no encontrado
int user_sock_by_name(const char *username);

// Enviar todos los bytes por socket (bloqueante hasta enviar todo o error)
ssize_t send_all(int sockfd, const void *buf, size_t len);

// Enviar respuesta terminada en '\n'
int send_linef(int sockfd, const char *fmt, ...);

// Manejar comando inválido (ayuda genérica)
int handle_not_allowed(int sockfd);

#endif // PROTOCOLO_H
