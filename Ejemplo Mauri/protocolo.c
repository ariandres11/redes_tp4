// protocolo.c
// Implementación de utilidades del protocolo y tabla de usuarios.

#define _GNU_SOURCE
#include "protocolo.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <unistd.h>
#include <sys/socket.h>
#include <pthread.h>

static user_t *users_head = NULL;
static pthread_mutex_t users_mutex = PTHREAD_MUTEX_INITIALIZER;

void users_init(void) {
    pthread_mutex_lock(&users_mutex);
    users_head = NULL;
    pthread_mutex_unlock(&users_mutex);
}

int user_add(const char *username, int sockfd) {
    if (!username || strlen(username) == 0 || strlen(username) >= MAX_USERNAME)
        return -1; // inválido
    // no permitir caracteres '|' ni ';' ni '\n'
    if (strchr(username, '|') || strchr(username, ';') || strchr(username, '\n'))
        return -1;

    pthread_mutex_lock(&users_mutex);
    // comprobar duplicado
    user_t *cur = users_head;
    while (cur) {
        if (strcmp(cur->username, username) == 0) {
            pthread_mutex_unlock(&users_mutex);
            return -2; // duplicado
        }
        cur = cur->next;
    }

    user_t *u = malloc(sizeof(user_t));
    if (!u) {
        pthread_mutex_unlock(&users_mutex);
        return -1;
    }
    strncpy(u->username, username, MAX_USERNAME-1);
    u->username[MAX_USERNAME-1] = '\0';
    u->sockfd = sockfd;
    u->next = users_head;
    users_head = u;
    pthread_mutex_unlock(&users_mutex);
    return 0;
}

void user_remove_by_sock(int sockfd) {
    pthread_mutex_lock(&users_mutex);
    user_t *cur = users_head, *prev = NULL;
    while (cur) {
        if (cur->sockfd == sockfd) {
            if (prev) prev->next = cur->next;
            else users_head = cur->next;
            free(cur);
            break;
        }
        prev = cur;
        cur = cur->next;
    }
    pthread_mutex_unlock(&users_mutex);
}

int user_exists(const char *username) {
    int found = 0;
    pthread_mutex_lock(&users_mutex);
    user_t *cur = users_head;
    while (cur) {
        if (strcmp(cur->username, username) == 0) { found = 1; break; }
        cur = cur->next;
    }
    pthread_mutex_unlock(&users_mutex);
    return found;
}

char *user_list_dup(void) {
    pthread_mutex_lock(&users_mutex);
    // calcular tamaño
    size_t total = 1; // terminal '\0'
    user_t *cur = users_head;
    int first = 1;
    while (cur) {
        total += strlen(cur->username) + (first ? 0 : 1); // +1 for ';'
        first = 0;
        cur = cur->next;
    }
    char *out = malloc(total);
    if (!out) { pthread_mutex_unlock(&users_mutex); return NULL; }
    out[0] = '\0';
    cur = users_head; first = 1;
    while (cur) {
        if (!first) strcat(out, ";");
        strcat(out, cur->username);
        first = 0;
        cur = cur->next;
    }
    pthread_mutex_unlock(&users_mutex);
    return out;
}

const char *user_name_by_sock(int sockfd) {
    const char *name = NULL;
    pthread_mutex_lock(&users_mutex);
    user_t *cur = users_head;
    while (cur) {
        if (cur->sockfd == sockfd) { name = cur->username; break; }
        cur = cur->next;
    }
    pthread_mutex_unlock(&users_mutex);
    return name;
}

int user_sock_by_name(const char *username) {
    int sockfd = -1;
    pthread_mutex_lock(&users_mutex);
    user_t *cur = users_head;
    while (cur) {
        if (strcmp(cur->username, username) == 0) {
            sockfd = cur->sockfd;
            break;
        }
        cur = cur->next;
    }
    pthread_mutex_unlock(&users_mutex);
    return sockfd;
}

int send_broadcast(const char *sender, const char *message) {
    int result = 0;
    size_t cap = 0, count = 0;
    int *fds = NULL;

    pthread_mutex_lock(&users_mutex);
    for (user_t *cur = users_head; cur; cur = cur->next) {
        if (strcmp(cur->username, sender) != 0) {
            if (count == cap) {
                size_t new_cap = cap ? cap * 2 : 8;
                int *tmp = realloc(fds, new_cap * sizeof(int));
                if (!tmp) {
                    result = -1;
                    break;
                }
                fds = tmp;
                cap = new_cap;
            }
            fds[count++] = cur->sockfd;
        }
    }
    pthread_mutex_unlock(&users_mutex);

    if (result < 0) {
        free(fds);
        return -1;
    }

    for (size_t i = 0; i < count; ++i) {
        if (send_linef(fds[i], "BROADCASTFROM|%s|%s", sender, message) != 0) {
            result = -1;
        }
    }
    free(fds);
    return result;
}

ssize_t send_all(int sockfd, const void *buf, size_t len) {
    size_t total = 0;
    const char *p = buf;
    while (total < len) {
        ssize_t sent = send(sockfd, p + total, len - total, 0);
        if (sent <= 0) return sent;
        total += sent;
    }
    return total;
}

int send_linef(int sockfd, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    char *buf = NULL;
    int n = vasprintf(&buf, fmt, ap);
    va_end(ap);
    if (n < 0 || !buf) return -1;
    // asegurar terminador '\n'
    if (buf[n-1] != '\n') {
        char *buf2;
        if (asprintf(&buf2, "%s\n", buf) < 0) { free(buf); return -1; }
        free(buf);
        buf = buf2;
        n = strlen(buf);
    }
    ssize_t r = send_all(sockfd, buf, n);
    free(buf);
    return (r == n) ? 0 : -1;
}

int handle_not_allowed(int sockfd) {
    return send_linef(sockfd, "ERROR|%d|Comando no permitido", ERR_NOT_ALLOWED);
}
