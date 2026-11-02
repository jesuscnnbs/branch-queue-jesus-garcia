# Notas de diseño — Gestor de colas de la sucursal

## 1. Una cola por tipo de servicio frente a una cola única

`BranchQueue` mantiene un `collections.deque` independiente por cada tipo de
servicio (`deposito`, `retiro`, `gestion_cuenta`). Todos los tickets comparten
un contador global, pero esperan en colas distintas.

Con esta estructura, `call_next(service_type)` es **O(1)**: la cabeza del
`deque` de ese servicio ya es el cliente que lleva más tiempo esperando para
ese servicio, así que basta con un `popleft()`. `peek_next` también es O(1)
(`queue[0]`).

Si existiera una sola cola compartida para todos los servicios, la cabeza
podría ser un cliente de otro servicio. Para encontrar al más antiguo del tipo
pedido habría que:

- recorrer la cola completa hasta el primer ticket de ese servicio: **O(n)**;
- o retirar un elemento del medio: **O(n)** en una lista o deque;
- o mantener índices/colas auxiliares por servicio, que en la práctica
  equivale a volver a tener una cola por servicio.

Por tanto, la cola separada traslada el coste a la emisión (un `append`,
O(1)) y deja la operación crítica —llamar al siguiente— en O(1). Además, el
aislamiento por servicio hace imposible que un agente llame a un cliente de
otra cola: el método solo mira la cola solicitada.

Las operaciones de reporte (`list_waiting` y `stats`) son **O(n)** sobre el
total de clientes en espera, porque necesitan recorrer o contar todos los
tickets. Ese coste es inevitable para mostrar el estado completo.

## 2. Dos agentes del mismo servicio llamando a `call_next` a la vez

El escenario peligroso es este:

1. El agente A comprueba que la cola no está vacía y lee al primer cliente.
2. Antes de que A retire el ticket, el agente B hace lo mismo y lee al mismo
   cliente.
3. Ambos agentes llaman al mismo cliente.

El GIL de CPython **no evita** esta carrera: la secuencia "comprobar si hay
clientes" + "desencolar" está formada por varias operaciones y el intérprete
puede cambiar de hilo entre ellas. La exclusión mutua tiene que ser explícita.

Por eso `BranchQueue` usa un `threading.Lock` compartido por todas las colas.
Dentro de `call_next`, bajo el lock, se hace primero la comprobación y
inmediatamente después el `popleft()`. **La mutación que debe ocurrir primero
es el `popleft()`**: retirar el ticket de la cola es lo que lo "reclama" para
un agente. Solo después de esa mutación se devuelve el ticket. Si el ticket se
leyera sin retirarlo y se devolviera fuera del lock, dos agentes podrían
recibirlo.

El mismo razonamiento se aplica a la emisión de tickets: incrementar el
contador global y hacer `append` en la cola deben ocurrir bajo el mismo lock.
Si se incrementara el contador fuera de él, dos clientes podrían recibir el
mismo número; si se encolara antes de asignar el número, otro hilo podría
observar un estado inconsistente.

`list_waiting` y `stats` también toman el lock para obtener una instantánea
coherente y no observar una cola a medio modificar.

### ¿Bastaría con un lock por servicio?

Sí para `call_next`, porque las colas son independientes. Sin embargo, el
contador de tickets es global, así que la emisión necesitaría un lock global
(o atómico) de todos modos. Usar un único lock es más simple, correcto y
suficiente para la escala de una sucursal; si el rendimiento fuera crítico,
se podría separar el contador global de los locks por cola.

## 3. Decisiones adicionales

- **Errores explícitos**: `EmptyQueueError` permite distinguir "no hay nadie
  esperando" de un tipo de servicio inválido. La CLI los captura y muestra un
  aviso, de modo que una cola vacía nunca rompe el programa.
- **Validación temprana**: `normalize_service_type` acepta mayúsculas y
  espacios sobrantes, pero rechaza cualquier valor fuera de los tres
  canónicos con un mensaje que lista los válidos.
- **Tickets inmutables**: `Ticket` es un `dataclass(frozen=True)`; una vez
  emitido, sus datos no cambian. `issued_at` se fija con
  `datetime.now()` en el momento de creación.
- **Sin dependencias externas**: solo `collections.deque`, `datetime`,
  `threading` y, en las pruebas, `unittest`/`unittest.mock`.
