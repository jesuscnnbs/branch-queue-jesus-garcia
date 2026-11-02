# Gestor de colas de la sucursal

Gestor de colas en terminal para modelar la atención de clientes de una
sucursal bancaria. Cada cliente recibe un ticket con un número global y
espera en la cola de su tipo de servicio (`deposito`, `retiro` o
`gestion_cuenta`). Los agentes llaman siempre al cliente que lleva más tiempo
esperando en su servicio.

Implementado únicamente con la biblioteca estándar de Python, sin paquetes
externos.

## Requisitos

- Python 3.9 o superior (probado con Python 3.14).

## Uso

```bash
python3 branch_queue.py
```

Menú disponible:

```
1) Emitir ticket
2) Llamar al siguiente cliente
3) Ver lista de espera
4) Ver estadísticas
5) Salir
```

Ejemplo de sesión:

```
Elige una opción: 1
Nombre del cliente: Ana
Tipos de servicio: deposito, retiro, gestion_cuenta
Tipo de servicio: deposito
Ticket emitido: #001 - Ana (10:32:01) — servicio deposito.

Elige una opción: 3

=== Lista de espera ===
deposito (1)
  1. #001 - Ana (10:32:01)
retiro (0)
  (sin clientes)
gestion_cuenta (0)
  (sin clientes)
```

## Comportamiento

- Los números de ticket son globales y secuenciales: dos clientes nunca
  comparten número aunque estén en servicios distintos.
- Cada servicio tiene su propia cola FIFO. Un agente solo puede llamar a
  clientes de su servicio.
- `call_next` y `peek_next` lanzan `EmptyQueueError` si no hay clientes; la
  CLI lo muestra como aviso y continúa.
- Un tipo de servicio inválido se rechaza con un mensaje que indica los
  valores admitidos.
- La emisión y la atención están protegidas con un lock, de modo que varios
  agentes concurrentes no pueden recibir el mismo ticket ni emitir números
  duplicados.

## API

| Método | Descripción |
|---|---|
| `issue_ticket(client_name, service_type)` | Crea y encola un ticket; devuelve el `Ticket`. |
| `call_next(service_type)` | Desencola y devuelve el siguiente cliente. |
| `peek_next(service_type)` | Devuelve el siguiente cliente sin retirarlo. |
| `list_waiting()` | Diccionario por servicio con los tickets en orden FIFO. |
| `stats()` | Conteo por servicio más la clave `total`. |

## Pruebas

```bash
python3 -m unittest discover -s tests -t . -v
```

## Estructura

```
branch_queue.py            # modelo Ticket, BranchQueue y CLI
DESIGN.md                  # decisiones de diseño y concurrencia
tests/test_branch_queue.py # pruebas unitarias y de concurrencia
```
