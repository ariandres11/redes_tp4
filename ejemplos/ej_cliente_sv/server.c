#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>

#define PORT 8888
#define BUFSIZE 1024

int main() {
    int fd;
    struct sockaddr_in server_addr, client_addr;
    char buffer[BUFSIZE];
    socklen_t client_len = sizeof(client_addr);

    // 1. Crear el socket UDP
    if ((fd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("Error en socket");
        exit(EXIT_FAILURE);
    }

    // 2. Configurar la dirección del servidor
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = INADDR_ANY; // Escucha en cualquier interfaz
    server_addr.sin_port = htons(PORT);

    // 3. Asignar el puerto al socket (Bind)
    if (bind(fd, (struct sockaddr *)&server_addr, sizeof(server_addr)) < 0) {
        perror("Error en bind");
        close(fd);
        exit(EXIT_FAILURE);
    }

    printf("Servidor UDP escuchando en el puerto %d...\n", PORT);

    while (1) {
        // 4. Recibir datos del cliente
        ssize_t bytes_received = recvfrom(fd, buffer, BUFSIZE - 1, 0, 
                                          (struct sockaddr *)&client_addr, &client_len);
        if (bytes_received < 0) {
            perror("Error en recvfrom");
            continue;
        }

        buffer[bytes_received] = '\0'; // Asegurar terminación de cadena
        printf("Cliente [%s:%d] dice: %s\n", 
               inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port), buffer);

        // 5. Responder al cliente (Eco)
        sendto(fd, buffer, bytes_received, 0, 
               (struct sockaddr *)&client_addr, client_len);
    }

    close(fd);
    return 0;
}