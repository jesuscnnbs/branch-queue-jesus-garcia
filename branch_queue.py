"""Gestor de colas de una sucursal bancaria.

Implementado únicamente con biblioteca estándar de Python:
``collections.deque``, ``datetime`` y ``threading``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock

SERVICE_TYPES: tuple[str, ...] = ("deposito", "retiro", "gestion_cuenta")


class InvalidServiceTypeError(ValueError):
    """El tipo de servicio no es uno de los admitidos."""


class EmptyQueueError(Exception):
    """No hay clientes esperando para el servicio solicitado."""


def normalize_service_type(service_type: str) -> str:
    """Valida y normaliza un tipo de servicio.

    Acepta mayúsculas y espacios sobrantes, pero solo los tres valores
    canónicos definidos en ``SERVICE_TYPES``.
    """
    normalized = service_type.strip().lower()
    if normalized not in SERVICE_TYPES:
        valid = ", ".join(SERVICE_TYPES)
        raise InvalidServiceTypeError(
            f"Tipo de servicio inválido: {service_type!r}. Válidos: {valid}"
        )
    return normalized


@dataclass(frozen=True)
class Ticket:
    """Ticket emitido a un cliente.

    ``number`` es global y secuencial entre todos los servicios.
    ``issued_at`` se fija en el momento de creación del ticket, es decir,
    en el momento de llegada del cliente.
    """

    number: int
    client_name: str
    service_type: str
    issued_at: datetime = field(default_factory=datetime.now)


class BranchQueue:
    """Colas FIFO independientes por tipo de servicio.

    El contador de tickets es global. Todas las mutaciones de estado
    (asignar número, encolar, desencolar) se protegen con un lock para
    que varios agentes puedan operar concurrentemente sin entregar el
    mismo cliente dos veces.
    """

    def __init__(self) -> None:
        self._queues: dict[str, deque[Ticket]] = {
            service: deque() for service in SERVICE_TYPES
        }
        self._next_number = 1
        self._lock = Lock()

    def issue_ticket(self, client_name: str, service_type: str) -> Ticket:
        """Crea un ticket y lo encola en la cola de su servicio."""
        name = client_name.strip()
        if not name:
            raise ValueError("El nombre del cliente no puede estar vacío.")

        normalized = normalize_service_type(service_type)

        # Asignar el número y encolar deben ser una sola operación atómica;
        # si no, dos emisiones concurrentes podrían compartir número.
        with self._lock:
            ticket = Ticket(
                number=self._next_number,
                client_name=name,
                service_type=normalized,
            )
            self._next_number += 1
            self._queues[normalized].append(ticket)

        return ticket

    def call_next(self, service_type: str) -> Ticket:
        """Desencola y devuelve el siguiente cliente del servicio dado."""
        normalized = normalize_service_type(service_type)

        with self._lock:
            queue = self._queues[normalized]
            if not queue:
                raise EmptyQueueError(
                    f"No hay clientes esperando para el servicio {normalized!r}."
                )
            # popleft() es la mutación que reclama el ticket. Debe ocurrir
            # antes de devolverlo para que otro agente no lo reciba también.
            return queue.popleft()

    def peek_next(self, service_type: str) -> Ticket:
        """Devuelve el siguiente cliente sin retirarlo de la cola."""
        normalized = normalize_service_type(service_type)

        with self._lock:
            queue = self._queues[normalized]
            if not queue:
                raise EmptyQueueError(
                    f"No hay clientes esperando para el servicio {normalized!r}."
                )
            return queue[0]

    def list_waiting(self) -> dict[str, list[Ticket]]:
        """Devuelve los clientes en espera agrupados por servicio.

        Cada lista respeta el orden FIFO y se devuelve una copia para no
        exponer las colas internas.
        """
        with self._lock:
            return {
                service: list(queue)
                for service, queue in self._queues.items()
            }

    def stats(self) -> dict[str, int]:
        """Devuelve el número de clientes en espera por servicio y el total."""
        with self._lock:
            counts = {
                service: len(queue)
                for service, queue in self._queues.items()
            }
        counts["total"] = sum(counts.values())
        return counts


# --------------------------------------------------------------------
# Interfaz de línea de comandos
# --------------------------------------------------------------------

MENU = """
=== Gestor de colas de la sucursal ===
1) Emitir ticket
2) Llamar al siguiente cliente
3) Ver lista de espera
4) Ver estadísticas
5) Salir
"""


def _format_ticket(ticket: Ticket) -> str:
    return (
        f"#{ticket.number:03d} - {ticket.client_name} "
        f"({ticket.issued_at:%H:%M:%S})"
    )


def _prompt_service_type() -> str:
    print("Tipos de servicio: " + ", ".join(SERVICE_TYPES))
    return input("Tipo de servicio: ")


def _handle_issue(branch: BranchQueue) -> None:
    client_name = input("Nombre del cliente: ")
    service_type = _prompt_service_type()

    try:
        ticket = branch.issue_ticket(client_name, service_type)
    except ValueError as exc:  # incluye InvalidServiceTypeError
        print(f"Error: {exc}")
        return

    print(
        f"Ticket emitido: {_format_ticket(ticket)} "
        f"— servicio {ticket.service_type}."
    )


def _handle_call_next(branch: BranchQueue) -> None:
    service_type = _prompt_service_type()

    try:
        ticket = branch.call_next(service_type)
    except EmptyQueueError as exc:
        print(f"Aviso: {exc}")
    except InvalidServiceTypeError as exc:
        print(f"Error: {exc}")
    else:
        print(
            f"Llamando al ticket {_format_ticket(ticket)} "
            f"— servicio {ticket.service_type}."
        )


def _print_waiting(branch: BranchQueue) -> None:
    waiting = branch.list_waiting()

    print("\n=== Lista de espera ===")
    for service in SERVICE_TYPES:
        tickets = waiting[service]
        print(f"{service} ({len(tickets)})")
        if not tickets:
            print("  (sin clientes)")
        else:
            for position, ticket in enumerate(tickets, start=1):
                print(f"  {position}. {_format_ticket(ticket)}")
    print()


def _print_stats(branch: BranchQueue) -> None:
    stats = branch.stats()

    print("\n=== Estadísticas ===")
    for service in SERVICE_TYPES:
        print(f"  {service:<15} {stats[service]}")
    print(f"  {'total':<15} {stats['total']}")
    print()


def main() -> None:
    branch = BranchQueue()
    print("Bienvenido al gestor de colas de la sucursal.")

    try:
        while True:
            print(MENU)
            option = input("Elige una opción: ").strip()

            if option == "1":
                _handle_issue(branch)
            elif option == "2":
                _handle_call_next(branch)
            elif option == "3":
                _print_waiting(branch)
            elif option == "4":
                _print_stats(branch)
            elif option == "5":
                print("Hasta luego.")
                return
            else:
                print(f"Opción inválida: {option!r}. Elige un número del 1 al 5.")
    except (EOFError, KeyboardInterrupt):
        print("\nHasta luego.")


if __name__ == "__main__":
    main()
