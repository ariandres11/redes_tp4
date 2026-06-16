// server.c
// Servidor TCP multihilo para el protocolo simplificado.
// Soporta LOGIN|username, LOGOUT, LIST, PING

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <pthread.h>

#include "protocolo.h"

#define PORT 5000
#define BACKLOG 10
#define BUF_SIZE 4096
#define FILE_MAX_SIZE 10485760
#define FILE_BUFFER_SIZE 4096

static int transfer_file_stream(int srcfd, int destfd, long filesize) {
    char buffer[FILE_BUFFER_SIZE];
    long remaining = filesize;

    while (remaining > 0) {
        ssize_t to_read = remaining < FILE_BUFFER_SIZE ? remaining : FILE_BUFFER_SIZE;
        ssize_t n = recv(srcfd, buffer, to_read, 0);
        if (n <= 0) {
            return -1;
        }

        ssize_t sent = send_all(destfd, buffer, n);
        if (sent != n) {
            return -1;
        }

        remaining -= n;
    }
    return 0;
}

static int handle_file_request(int clientfd, const char *sender, char *dest, char *filename, char *filesize_str) {
    if (!sender) {
        send_linef(clientfd, "ERROR|%d|Usuario no autenticado", ERR_NOT_AUTHENTICATED);
        return -1;
    }
    if (!dest || !filename || !filesize_str) {
        send_linef(clientfd, "ERROR|%d|Formato de mensaje inválido", ERR_INVALID_FORMAT);
        return -1;
    }

    char *endptr = NULL;
    long filesize = strtol(filesize_str, &endptr, 10);
    if (endptr == NULL || *endptr != '\0' || filesize < 0) {
        send_linef(clientfd, "ERROR|%d|Formato de mensaje inválido", ERR_INVALID_FORMAT);
        return -1;
    }
    if (filesize > FILE_MAX_SIZE) {
        send_linef(clientfd, "ERROR|%d|Archivo excede tamaño máximo", ERR_FILE_TOO_LARGE);
        return -1;
    }

    int destfd = user_sock_by_name(dest);
    if (destfd < 0) {
        send_linef(clientfd, "ERROR|%d|Usuario no conectado", ERR_UNKNOWN_USER);
        return -1;
    }

    if (send_linef(clientfd, "ACK|FILE_START") != 0) {
        send_linef(clientfd, "ERROR|%d|Transferencia fallida", ERR_TRANSFER);
        return -1;
    }

    if (send_linef(destfd, "FILEFROM|%s|%s|%ld", sender, filename, filesize) != 0) {
        send_linef(clientfd, "ERROR|%d|Transferencia fallida", ERR_TRANSFER);
        return -1;
    }

    if (transfer_file_stream(clientfd, destfd, filesize) != 0) {
        send_linef(clientfd, "ERROR|%d|Transferencia fallida", ERR_TRANSFER);
        return -1;
    }

    if (send_linef(clientfd, "ACK|FILE_COMPLETE") != 0) {
        return -1;
    }

    return 0;
}

// Cada hilo cliente ejecuta esta función
void *client_thread(void *arg) {
    int clientfd = *(int *)arg;
    free(arg);

    char buf[BUF_SIZE];
    ssize_t n;
    // Buffer para líneas completas
    char linebuf[BUF_SIZE];
    size_t linepos = 0;

    while (1) {
        n = recv(clientfd, buf, sizeof(buf), 0);
        if (n <= 0) break; // desconexión o error
        for (ssize_t i = 0; i < n; ++i) {
            char c = buf[i];
            if (c == '\r') continue; // ignorar CR
            if (c == '\n') {
                linebuf[linepos] = '\0';
                // procesar línea completa
                if (linepos == 0) {
                    // línea vacía: ignorar
                    linepos = 0; continue;
                }
                // separar por '|'
                char *copy = strdup(linebuf);
                if (!copy) { goto cleanup; }
                // obtener comando
                char *saveptr = NULL;
                char *cmd = strtok_r(copy, "|", &saveptr);
                if (!cmd) {
                    send_linef(clientfd, "ERROR|%d|Formato de mensaje inválido", ERR_INVALID_FORMAT);
                    free(copy);
                    linepos = 0; continue;
                }

                if (strcmp(cmd, "LOGIN") == 0) {
                    char *username = strtok_r(NULL, "|", &saveptr);
                    if (!username) {
                        send_linef(clientfd, "ERROR|%d|Formato de mensaje inválido", ERR_INVALID_FORMAT);
                    } else {
                        // validar username
                        if (strlen(username) == 0) {
                            send_linef(clientfd, "ERROR|%d|Nombre de usuario inválido", ERR_INVALID_USERNAME);
                        } else if (user_exists(username)) {
                            send_linef(clientfd, "ERROR|%d|Usuario ya conectado", ERR_USER_ALREADY_CONNECTED);
                        } else {
                            int r = user_add(username, clientfd);
                            if (r == 0) {
                                send_linef(clientfd, "ACK|LOGIN");
                            } else if (r == -2) {
                                send_linef(clientfd, "ERROR|%d|Usuario ya conectado", ERR_USER_ALREADY_CONNECTED);
                            } else {
                                send_linef(clientfd, "ERROR|%d|Nombre de usuario inválido", ERR_INVALID_USERNAME);
                            }
                        }
                    }
                } else if (strcmp(cmd, "LOGOUT") == 0) {
                    const char *name = user_name_by_sock(clientfd);
                    if (!name) {
                        send_linef(clientfd, "ERROR|%d|Usuario no autenticado", ERR_NOT_AUTHENTICATED);
                    } else {
                        user_remove_by_sock(clientfd);
                        send_linef(clientfd, "ACK|LOGOUT");
                        free(copy);
                        goto cleanup; // cerrar conexión tras logout
                    }
                } else if (strcmp(cmd, "LIST") == 0) {
                    const char *name = user_name_by_sock(clientfd);
                    if (!name) {
                        send_linef(clientfd, "ERROR|%d|Usuario no autenticado", ERR_NOT_AUTHENTICATED);
                    } else {
                        char *list = user_list_dup();
                        if (!list) {
                            send_linef(clientfd, "ACK|LIST|0|");
                        } else {
                            // contar usuarios
                            int count = 0;
                            if (strlen(list) > 0) {
                                // contar separadores ';'
                                for (char *p = list; *p; ++p) if (*p == ';') ++count;
                                count += 1; // número de usuarios = separadores+1
                            }
                            if (strlen(list) == 0) {
                                send_linef(clientfd, "ACK|LIST|0|");
                            } else {
                                send_linef(clientfd, "ACK|LIST|%d|%s", count, list);
                            }
                            free(list);
                        }
                    }
                } else if (strcmp(cmd, "MSG") == 0) {
                    const char *sender = user_name_by_sock(clientfd);
                    char *dest = strtok_r(NULL, "|", &saveptr);
                    char *message = saveptr;
                    if (!sender) {
                        send_linef(clientfd, "ERROR|%d|Usuario no autenticado", ERR_NOT_AUTHENTICATED);
                    } else if (!dest || !message || *message == '\0') {
                        send_linef(clientfd, "ERROR|%d|Formato de mensaje inválido", ERR_INVALID_FORMAT);
                    } else {
                        int destfd = user_sock_by_name(dest);
                        if (destfd < 0) {
                            send_linef(clientfd, "ERROR|%d|Usuario no conectado", ERR_UNKNOWN_USER);
                        } else {
                            send_linef(destfd, "FROM|%s|%s", sender, message);
                            send_linef(clientfd, "ACK|MSG");
                        }
                    }
                } else if (strcmp(cmd, "BROADCAST") == 0) {
                    const char *sender = user_name_by_sock(clientfd);
                    char *message = saveptr;
                    if (!sender) {
                        send_linef(clientfd, "ERROR|%d|Usuario no autenticado", ERR_NOT_AUTHENTICATED);
                    } else if (!message || *message == '\0') {
                        send_linef(clientfd, "ERROR|%d|Formato de mensaje inválido", ERR_INVALID_FORMAT);
                    } else {
                        send_broadcast(sender, message);
                        send_linef(clientfd, "ACK|BROADCAST");
                    }
                } else if (strcmp(cmd, "FILE") == 0) {
                    const char *sender = user_name_by_sock(clientfd);
                    char *dest = strtok_r(NULL, "|", &saveptr);
                    char *filename = strtok_r(NULL, "|", &saveptr);
                    char *filesize_str = saveptr;
                    handle_file_request(clientfd, sender, dest, filename, filesize_str);
                } else if (strcmp(cmd, "PING") == 0) {
                    send_linef(clientfd, "PONG");
                } else {
                    // comandos no implementados para esta versión
                    send_linef(clientfd, "ERROR|%d|Comando no permitido", ERR_NOT_ALLOWED);
                }

                free(copy);
                linepos = 0;
            } else {
                if (linepos + 1 < sizeof(linebuf)) {
                    linebuf[linepos++] = c;
                } else {
                    // línea demasiado larga -> protocolo violado
                    send_linef(clientfd, "ERROR|%d|Formato de mensaje inválido", ERR_INVALID_FORMAT);
                    linepos = 0;
                }
            }
        }
    }

cleanup:
    // limpiar estado asociado al socket
    user_remove_by_sock(clientfd);
    close(clientfd);
    return NULL;
}

int main(void) {
    int listenfd, *pclient;
    struct sockaddr_in servaddr, cliaddr;
    socklen_t clilen;

    users_init();

    if ((listenfd = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
        perror("socket"); exit(EXIT_FAILURE);
    }

    int opt = 1;
    setsockopt(listenfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = htonl(INADDR_ANY);
    servaddr.sin_port = htons(PORT);

    if (bind(listenfd, (struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) {
        perror("bind"); exit(EXIT_FAILURE);
    }

    if (listen(listenfd, BACKLOG) < 0) {
        perror("listen"); exit(EXIT_FAILURE);
    }

    printf("Servidor escuchando en puerto %d\n", PORT);

    while (1) {
        clilen = sizeof(cliaddr);
        int connfd = accept(listenfd, (struct sockaddr *)&cliaddr, &clilen);
        if (connfd < 0) {
            perror("accept"); continue;
        }
        pclient = malloc(sizeof(int));
        *pclient = connfd;
        pthread_t tid;
        if (pthread_create(&tid, NULL, client_thread, pclient) != 0) {
            perror("pthread_create"); close(connfd); free(pclient);
            continue;
        }
        pthread_detach(tid);
    }

    close(listenfd);
    return 0;
}
