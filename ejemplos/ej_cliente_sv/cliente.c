#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>

#define SERVER_IP "127.0.0.1"
#define PORT 8888
#define BUFSIZE 1024

int main() {
    int fd;
    struct sockaddr_in server_addr;
    char *mensaje = "¡Hola desde el cliente UDP!";
    char buffer[BUFSIZE];
    socklen_t server_len = sizeof(server_addr);

    // 1. Crear el socket UDP
    if ((fd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("Error en socket");
        exit(EXIT_FAILURE);
    }

    // 2. Configurar la dirección del servidor de destino
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(PORT);
    if (inet_pton(AF_INET, SERVER_IP, &server_addr.sin_addr) <= 0) {
        perror("Dirección IP inválida");
        close(fd);
        exit(EXIT_FAILURE);
    }

    // 3. Enviar mensaje al servidor
    printf("Enviando mensaje al servidor...\n");
    sendto(fd, mensaje, strlen(mensaje), 0, 
           (struct sockaddr *)&server_addr, server_len);

    // 4. Recibir la respuesta del servidor (Eco)
    ssize_t bytes_received = recvfrom(fd, buffer, BUFSIZE - 1, 0, 
                                      (struct sockaddr *)&server_addr, &server_len);
    if (bytes_received < 0) {
        perror("Error en recvfrom");
    } else {
        buffer[bytes_received] = '\0';
        printf("Respuesta del servidor: %s\n", buffer);
    }

    close(fd);
    return 0;
}