#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>

#define SERVER_IP "127.0.0.1"
#define PORT 8888
#define BUFSIZE 1024

int main(int argc, char *argv[]) {
    int fd;
    struct sockaddr_in server_addr;
    char buffer[BUFSIZE];
    socklen_t server_len = sizeof(server_addr);

    // 1. VALIDACIÓN: Controlar que haya al menos un argumento
    if (argc < 2) {
        fprintf(stderr, "Uso: %s hola como estas\n", argv[0]);
        exit(EXIT_FAILURE);
    }

    // 2. CONCATENACIÓN: Unificar todos los argumentos en el buffer de mensaje
    char mensaje[BUFSIZE];
    memset(mensaje, 0, sizeof(mensaje)); // Limpiamos el buffer

    for (int i = 1; i < argc; i++) {
        // Controlar que no desbordemos el buffer del mensaje
        if (strlen(mensaje) + strlen(argv[i]) + 2 > BUFSIZE) {
            fprintf(stderr, "Error: El mensaje es demasiado largo.\n");
            break;
        }
        
        strcat(mensaje, argv[i]);
        
        // Agregamos un espacio después de cada palabra, excepto en la última
        if (i < argc - 1) {
            strcat(mensaje, " ");
        }
    }

    // 3. Crear el socket UDP
    if ((fd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("Error en socket");
        exit(EXIT_FAILURE);
    }

    // 4. Configurar la dirección del servidor de destino
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(PORT);
    if (inet_pton(AF_INET, SERVER_IP, &server_addr.sin_addr) <= 0) {
        perror("Dirección IP inválida");
        close(fd);
        exit(EXIT_FAILURE);
    }

    // 5. Enviar el mensaje unificado al servidor
    printf("Enviando mensaje al servidor: \"%s\"\n", mensaje);
    sendto(fd, mensaje, strlen(mensaje), 0, 
           (struct sockaddr *)&server_addr, server_len);

    // 6. Recibir la respuesta del servidor (Eco)
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