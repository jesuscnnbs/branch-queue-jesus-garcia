"""Pruebas del gestor de colas de la sucursal."""

from __future__ import annotations

import io
import threading
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import patch

from branch_queue import (
    SERVICE_TYPES,
    BranchQueue,
    EmptyQueueError,
    InvalidServiceTypeError,
    main,
)


class TicketTests(unittest.TestCase):
    def test_ticket_records_all_fields(self) -> None:
        before = datetime.now()
        ticket = BranchQueue().issue_ticket("  Ana  ", "DEPOSITO")
        after = datetime.now()

        self.assertEqual(ticket.number, 1)
        self.assertEqual(ticket.client_name, "Ana")
        self.assertEqual(ticket.service_type, "deposito")
        self.assertGreaterEqual(ticket.issued_at, before)
        self.assertLessEqual(ticket.issued_at, after)


class NumberingTests(unittest.TestCase):
    def test_numbers_are_global_and_sequential_across_services(self) -> None:
        branch = BranchQueue()

        tickets = [
            branch.issue_ticket("Ana", "deposito"),
            branch.issue_ticket("Beto", "retiro"),
            branch.issue_ticket("Carla", "gestion_cuenta"),
            branch.issue_ticket("Dora", "deposito"),
        ]

        self.assertEqual([t.number for t in tickets], [1, 2, 3, 4])

    def test_numbers_continue_after_serving(self) -> None:
        branch = BranchQueue()
        branch.issue_ticket("Ana", "retiro")
        branch.call_next("retiro")

        self.assertEqual(branch.issue_ticket("Beto", "retiro").number, 2)


class QueueOrderTests(unittest.TestCase):
    def test_clients_are_served_in_fifo_order_within_a_service(self) -> None:
        branch = BranchQueue()
        names = ["Ana", "Beto", "Carla"]

        for name in names:
            branch.issue_ticket(name, "deposito")
        branch.issue_ticket("Dora", "retiro")

        served = [branch.call_next("deposito").client_name for _ in names]
        self.assertEqual(served, names)

    def test_services_are_independent(self) -> None:
        branch = BranchQueue()
        branch.issue_ticket("Ana", "deposito")
        branch.issue_ticket("Beto", "retiro")

        self.assertEqual(branch.call_next("retiro").client_name, "Beto")
        self.assertEqual(branch.stats()["deposito"], 1)

    def test_peek_returns_next_without_removing_it(self) -> None:
        branch = BranchQueue()
        ticket = branch.issue_ticket("Ana", "retiro")
        branch.issue_ticket("Beto", "retiro")

        self.assertEqual(branch.peek_next("retiro"), ticket)
        self.assertEqual(branch.stats()["retiro"], 2)
        self.assertEqual(branch.call_next("retiro"), ticket)


class EmptyQueueTests(unittest.TestCase):
    def test_call_next_on_empty_queue_raises_descriptive_error(self) -> None:
        branch = BranchQueue()

        with self.assertRaisesRegex(EmptyQueueError, "retiro"):
            branch.call_next("retiro")

    def test_peek_next_on_empty_queue_raises_descriptive_error(self) -> None:
        branch = BranchQueue()

        with self.assertRaisesRegex(EmptyQueueError, "gestion_cuenta"):
            branch.peek_next("gestion_cuenta")

    def test_queue_still_works_after_empty_error(self) -> None:
        branch = BranchQueue()

        with self.assertRaises(EmptyQueueError):
            branch.call_next("deposito")

        branch.issue_ticket("Ana", "deposito")
        self.assertEqual(branch.call_next("deposito").client_name, "Ana")


class ValidationTests(unittest.TestCase):
    def test_invalid_service_type_is_rejected_on_issue(self) -> None:
        branch = BranchQueue()

        with self.assertRaisesRegex(InvalidServiceTypeError, "deposito"):
            branch.issue_ticket("Ana", "prestamo")

        self.assertEqual(branch.stats()["total"], 0)

    def test_invalid_service_type_is_rejected_on_call_and_peek(self) -> None:
        branch = BranchQueue()

        with self.assertRaises(InvalidServiceTypeError):
            branch.call_next("otro")
        with self.assertRaises(InvalidServiceTypeError):
            branch.peek_next("otro")

    def test_blank_client_name_is_rejected(self) -> None:
        branch = BranchQueue()

        with self.assertRaises(ValueError):
            branch.issue_ticket("   ", "deposito")

        self.assertEqual(branch.stats()["total"], 0)


class ReportingTests(unittest.TestCase):
    def test_list_waiting_groups_and_orders_by_service(self) -> None:
        branch = BranchQueue()
        branch.issue_ticket("Ana", "deposito")
        branch.issue_ticket("Beto", "retiro")
        branch.issue_ticket("Carla", "deposito")

        waiting = branch.list_waiting()

        self.assertEqual(set(waiting), set(SERVICE_TYPES))
        self.assertEqual(
            [t.client_name for t in waiting["deposito"]], ["Ana", "Carla"]
        )
        self.assertEqual(
            [t.client_name for t in waiting["retiro"]], ["Beto"]
        )
        self.assertEqual(waiting["gestion_cuenta"], [])

    def test_list_waiting_returns_a_copy(self) -> None:
        branch = BranchQueue()
        branch.issue_ticket("Ana", "deposito")

        waiting = branch.list_waiting()
        waiting["deposito"].clear()

        self.assertEqual(branch.stats()["deposito"], 1)

    def test_stats_counts_by_service_and_total(self) -> None:
        branch = BranchQueue()
        branch.issue_ticket("Ana", "deposito")
        branch.issue_ticket("Beto", "deposito")
        branch.issue_ticket("Carla", "retiro")

        self.assertEqual(
            branch.stats(),
            {
                "deposito": 2,
                "retiro": 1,
                "gestion_cuenta": 0,
                "total": 3,
            },
        )

    def test_stats_update_after_serving(self) -> None:
        branch = BranchQueue()
        branch.issue_ticket("Ana", "retiro")
        branch.call_next("retiro")

        self.assertEqual(branch.stats()["retiro"], 0)
        self.assertEqual(branch.stats()["total"], 0)


class ConcurrencyTests(unittest.TestCase):
    def test_concurrent_issuance_assigns_unique_numbers(self) -> None:
        branch = BranchQueue()
        worker_count = 4
        tickets_per_worker = 50
        tickets: list = []
        tickets_lock = threading.Lock()
        start = threading.Barrier(worker_count)

        def issuer(worker: int) -> None:
            start.wait()
            for index in range(tickets_per_worker):
                ticket = branch.issue_ticket(
                    f"Cliente {worker}-{index}", "retiro"
                )
                with tickets_lock:
                    tickets.append(ticket)

        threads = [
            threading.Thread(target=issuer, args=(worker,))
            for worker in range(worker_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        expected = list(range(1, worker_count * tickets_per_worker + 1))
        self.assertEqual(len(tickets), len(expected))
        self.assertEqual(sorted(t.number for t in tickets), expected)

    def test_concurrent_call_next_never_delivers_a_ticket_twice(self) -> None:
        branch = BranchQueue()
        total = 300
        agent_count = 6
        for index in range(total):
            branch.issue_ticket(f"Cliente {index}", "deposito")

        served: list[int] = []
        served_lock = threading.Lock()
        start = threading.Barrier(agent_count)

        def agent() -> None:
            start.wait()
            while True:
                try:
                    ticket = branch.call_next("deposito")
                except EmptyQueueError:
                    return
                with served_lock:
                    served.append(ticket.number)

        threads = [
            threading.Thread(target=agent) for _ in range(agent_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(served), total)
        self.assertEqual(sorted(served), list(range(1, total + 1)))
        self.assertEqual(branch.stats()["deposito"], 0)


class CliTests(unittest.TestCase):
    def test_cli_covers_issue_list_stats_call_empty_and_invalid_input(
        self,
    ) -> None:
        inputs = [
            "1", "Ana", "deposito",
            "1", "Beto", "retiro",
            "3",
            "4",
            "2", "deposito",
            "2", "deposito",
            "1", "Carla", "prestamo",
            "9",
            "5",
        ]

        output = io.StringIO()
        with patch("builtins.input", side_effect=inputs):
            with redirect_stdout(output):
                main()

        text = output.getvalue()
        self.assertIn("Ticket emitido", text)
        self.assertIn("Ana", text)
        self.assertIn("Beto", text)
        self.assertIn("Llamando al ticket", text)
        self.assertIn("Aviso:", text)
        self.assertIn("Tipo de servicio inválido", text)
        self.assertIn("Opción inválida", text)
        self.assertIn("Hasta luego", text)


if __name__ == "__main__":
    unittest.main()
