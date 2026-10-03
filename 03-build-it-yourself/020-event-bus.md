# 020 · A Type-Safe Event Bus in 50 Lines

> A map from `Class` to listeners, a breadth-first walk up the type hierarchy, and a `try` around every handler. That is the whole bus, and the compiler still checks every subscriber.

**Since:** Java 21 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

An order is placed. Inventory wants to reserve stock, the mailer wants to send a confirmation, analytics wants a number, audit wants everything. The direct approach makes the order service know all of them:

```java
void placeOrder(Order order) {
    repository.save(order);
    inventory.reserve(order);
    mailer.sendConfirmation(order);
    analytics.recordRevenue(order);
    audit.log(order);              // and next sprint, a fifth collaborator
}
```

Every new reaction means editing the producer. An event bus inverts that: the producer announces *what happened*, and anyone interested listens. The classic implementations (Guava's `EventBus`, CDI events) find listeners by reflection on annotated methods. You can get the same decoupling with plain generics and keep the compiler on your side.

## The trick

Key the listeners by the event's `Class`, and make `subscribe` generic so the handler's type is tied to the key:

```java
<E> Registration subscribe(Class<E> type, Consumer<? super E> handler)
```

Three small ideas do the rest:

* **`type.cast(event)` instead of an unchecked cast.** Each subscriber stores its own `Class<E>`, so delivery is checked at runtime and the code needs no `@SuppressWarnings`.
* **Dispatch to supertypes.** Publishing an `OrderPlaced` also reaches subscribers of `OrderEvent`, of any interface it implements, and of `Object`. A breadth-first walk over `getSuperclass()` and `getInterfaces()` collects those types, and `ClassValue` caches the walk per class.
* **Unsubscribe by closing.** `subscribe` returns an `AutoCloseable` whose `close()` throws nothing, so a temporary listener fits in a try-with-resources block.

Delivery goes through an `Executor`. `Runnable::run` makes the bus synchronous; a thread pool makes it asynchronous. Each delivery is wrapped in its own `try`, so a broken subscriber is reported and the others still run.

## Full example

The bus itself is the `Registration` interface plus the `EventBus` class: 49 lines of code, not counting blank lines and comments. The rest is the demo.

```java run
import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;

public class EventBusDemo {

    /** Closing a registration unsubscribes. No checked exception, so try-with-resources stays clean. */
    interface Registration extends AutoCloseable {
        @Override void close();
    }

    static final class EventBus {
        private record Subscriber<E>(Class<E> type, Consumer<? super E> handler) {
            void deliver(Object event) { handler.accept(type.cast(event)); }
        }

        // The class itself first, then its supertypes, breadth first, each exactly once. Cached per class.
        private static final ClassValue<Set<Class<?>>> TYPES = new ClassValue<>() {
            @Override protected Set<Class<?>> computeValue(Class<?> type) {
                var seen = new LinkedHashSet<Class<?>>();
                var queue = new ArrayDeque<Class<?>>(List.of(type));
                while (!queue.isEmpty()) {
                    Class<?> next = queue.poll();
                    if (!seen.add(next)) continue;
                    if (next.getSuperclass() != null) queue.add(next.getSuperclass());
                    queue.addAll(List.of(next.getInterfaces()));
                }
                return Collections.unmodifiableSet(seen);
            }
        };

        private final Map<Class<?>, List<Subscriber<?>>> subscribers = new ConcurrentHashMap<>();
        private final Executor executor;
        private final BiConsumer<Object, RuntimeException> onError;

        EventBus(Executor executor, BiConsumer<Object, RuntimeException> onError) {
            this.executor = executor;
            this.onError = onError;
        }

        <E> Registration subscribe(Class<E> type, Consumer<? super E> handler) {
            var subscriber = new Subscriber<>(type, handler);
            subscribers.computeIfAbsent(type, t -> new CopyOnWriteArrayList<>()).add(subscriber);
            return () -> subscribers.get(type).removeIf(s -> s == subscriber);
        }

        /** Returns how many deliveries were handed to the executor. */
        int publish(Object event) {
            int deliveries = 0;
            for (Class<?> type : TYPES.get(event.getClass())) {
                for (Subscriber<?> subscriber : subscribers.getOrDefault(type, List.of())) {
                    deliveries++;
                    executor.execute(() -> {
                        try {
                            subscriber.deliver(event);
                        } catch (RuntimeException e) {
                            onError.accept(event, e);   // one bad subscriber never stops the others
                        }
                    });
                }
            }
            return deliveries;
        }
    }

    // A closed set of domain events, plus a cross-cutting marker interface.
    sealed interface OrderEvent permits OrderPlaced, OrderShipped, OrderCancelled { String orderId(); }
    interface CustomerFacing {}
    record OrderPlaced(String orderId, long cents) implements OrderEvent, CustomerFacing {}
    record OrderShipped(String orderId, String carrier) implements OrderEvent, CustomerFacing {}
    record OrderCancelled(String orderId, String reason) implements OrderEvent {}

    public static void main(String[] args) {
        BiConsumer<Object, RuntimeException> report = (event, e) -> System.out.println(
                "  !! a subscriber failed on " + event.getClass().getSimpleName() + ": " + e.getMessage());
        var bus = new EventBus(Runnable::run, report);   // synchronous: runs on the publisher's thread

        bus.subscribe(OrderPlaced.class, e -> System.out.println("  inventory: reserve stock for " + e.orderId()));
        bus.subscribe(CustomerFacing.class, e -> System.out.println("  mailer: write to customer about " + e));
        bus.subscribe(OrderEvent.class, e -> System.out.println("  analytics: " + switch (e) {
            case OrderPlaced p -> "revenue +" + p.cents() + " cents";
            case OrderShipped s -> "shipped by " + s.carrier();
            case OrderCancelled c -> "lost order, " + c.reason();
        }));
        bus.subscribe(OrderCancelled.class, e -> { throw new IllegalStateException("refund service is down"); });
        bus.subscribe(Object.class, e -> System.out.println("  audit: " + e.getClass().getSimpleName()));

        System.out.println("publish OrderPlaced");
        bus.publish(new OrderPlaced("A-1", 4999));

        System.out.println("publish OrderCancelled");
        bus.publish(new OrderCancelled("A-0", "changed my mind"));

        System.out.println("publish OrderShipped with a temporary tracker");
        try (var tracker = bus.subscribe(OrderShipped.class, e -> System.out.println("  tracker: follow the " + e.carrier()))) {
            bus.publish(new OrderShipped("A-1", "drone"));
        }
        System.out.println("publish OrderShipped after the tracker was closed");
        bus.publish(new OrderShipped("A-2", "bike courier"));

        // Asynchronous delivery: any Executor works. A queue we drain by hand keeps the demo deterministic.
        var pending = new ArrayDeque<Runnable>();
        var async = new EventBus(pending::add, report);
        async.subscribe(OrderEvent.class, e -> System.out.println("  async analytics: " + e.orderId()));
        async.subscribe(Object.class, e -> System.out.println("  async audit: " + e.getClass().getSimpleName()));
        int queued = async.publish(new OrderPlaced("B-7", 1250));
        System.out.println("async publish returned with " + queued + " deliveries queued, none run yet");
        while (!pending.isEmpty()) pending.poll().run();
    }
}
```

Output:

```text output
publish OrderPlaced
  inventory: reserve stock for A-1
  analytics: revenue +4999 cents
  mailer: write to customer about OrderPlaced[orderId=A-1, cents=4999]
  audit: OrderPlaced
publish OrderCancelled
  !! a subscriber failed on OrderCancelled: refund service is down
  analytics: lost order, changed my mind
  audit: OrderCancelled
publish OrderShipped with a temporary tracker
  tracker: follow the drone
  analytics: shipped by drone
  mailer: write to customer about OrderShipped[orderId=A-1, carrier=drone]
  audit: OrderShipped
publish OrderShipped after the tracker was closed
  analytics: shipped by bike courier
  mailer: write to customer about OrderShipped[orderId=A-2, carrier=bike courier]
  audit: OrderShipped
async publish returned with 2 deliveries queued, none run yet
  async analytics: B-7
  async audit: OrderPlaced
```

And the type safety is real. A handler for the wrong type does not compile:

```java compile-fail
import java.util.function.Consumer;

public class WrongHandler {
    record OrderPlaced(String orderId) {}

    static <E> void subscribe(Class<E> type, Consumer<? super E> handler) {}

    public static void main(String[] args) {
        subscribe(OrderPlaced.class, (CharSequence text) -> System.out.println(text.length()));
    }
}
```

```text compile-error
WrongHandler.java:9: error: method subscribe in class WrongHandler cannot be applied to given types;
        subscribe(OrderPlaced.class, (CharSequence text) -> System.out.println(text.length()));
        ^
  required: Class<E>,Consumer<? super E>
  found:    Class<OrderPlaced>,(CharSeque[...]th())
  reason: inference variable E has incompatible bounds
    equality constraints: OrderPlaced
    upper bounds: CharSequence,Object
  where E is a type-variable:
    E extends Object declared in method <E>subscribe(Class<E>,Consumer<? super E>)
1 error
```

javac infers `E = OrderPlaced` from the class literal, and the lambda would need `E` to be a `CharSequence`. No `E` satisfies both, so the mistake never reaches runtime.

## How it works

* **The signature carries the safety.** `Class<E>` fixes `E`, and `Consumer<? super E>` accepts a handler for `E` or any supertype of it (PECS: the consumer *consumes* `E`). So an `OrderEvent` handler may listen to `OrderPlaced`, and a `CharSequence` handler may not.
* **One heterogeneous map.** `Map<Class<?>, List<Subscriber<?>>>` cannot express "the list for `Class<E>` holds subscribers of `E`", so the record keeps that link itself: each `Subscriber<E>` pairs the handler with its own `Class<E>`, and `deliver` uses `type.cast`. This is the type-safe heterogeneous container from [033](../04-generics/033-heterogeneous-container.md), applied to lists of listeners.
* **The type walk is breadth first.** For `OrderPlaced` it yields `OrderPlaced`, `Record`, `OrderEvent`, `CustomerFacing`, `Object`. That explains the output order: the specific subscriber first, then the interfaces in declaration order, then `audit` on `Object`. A `LinkedHashSet` keeps the order stable and visits a diamond only once.
* **`ClassValue` is the right cache.** It is the JDK's built-in, thread-safe answer to "compute something per class, once", and it stores the value with the class itself instead of in a global map that would pin every event class forever.
* **The sealed hierarchy pays off in the subscriber.** The analytics handler switches over `OrderEvent` with no `default` branch. Add a fourth event to the `permits` clause and that switch stops compiling until someone handles it.
* **Unsubscribing removes by identity.** `removeIf(s -> s == subscriber)` removes exactly this registration, even if the same lambda was subscribed twice. `CopyOnWriteArrayList` makes it safe to unsubscribe in the middle of a dispatch, because the loop iterates over a snapshot.
* **Exception isolation is one `try`.** In the output, the failing refund subscriber is reported and analytics and audit still see the cancellation.

## Gotchas

* **Synchronous delivery is depth first.** If a subscriber publishes another event, that event is fully delivered before the remaining subscribers of the first one run. Guava solves this with a per-thread queue. If your handlers publish, add a queue or make the bus asynchronous.
* **A thread pool loses ordering.** With `Executors.newFixedThreadPool(4)`, `OrderShipped` can be handled before `OrderPlaced`. If order matters per aggregate, use a single-threaded executor per key, or a real log such as Kafka.
* **Asynchronous means fire and forget.** There is no back-pressure, no retry and no way for the publisher to learn about failures. The error handler is the only signal, so make it log loudly.
* **Lambdas cannot be unsubscribed by value.** That is why `subscribe` returns a `Registration`. Lose it and the listener stays forever (a classic memory leak in long-lived buses).
* **Generic events are erased.** You can subscribe to `Envelope.class` but not to `Envelope<OrderPlaced>`. Use distinct event types instead of generic wrappers.
* **Dead events vanish.** If nobody listens, nothing happens. `publish` returns the delivery count; a production bus would route zero-delivery events to a dead letter handler.

## When to use it (and when not to)

Use an in-process bus to decouple modules *inside one application*: a modular monolith, a desktop app, a game loop, plugin hooks. Keep the event types few and explicit, and keep the subscriber list discoverable (one wiring class, not subscriptions sprinkled everywhere).

Be honest about the cost: an event bus turns visible method calls into invisible control flow. Guava's own Javadoc now says "We recommend against using EventBus" for exactly that reason, and suggests dependency injection for decoupling and reactive streams for reacting to events. If you are in Spring, `ApplicationEventPublisher` with `@EventListener` (and `@TransactionalEventListener` for after-commit events) is the standard answer. In Jakarta EE, use CDI events. Across processes, use a message broker; an in-memory bus loses everything on restart. Build this one when you want ten lines of wiring with no framework, and understand that it leaves out ordering guarantees, back-pressure, dead letters, persistence and monitoring.

## Related

* [033 · The Type-Safe Heterogeneous Container](../04-generics/033-heterogeneous-container.md), the `Class<T>` keyed map behind the bus
* [035 · PECS and Wildcard Capture](../04-generics/035-pecs-wildcard-capture.md), why the handler is `Consumer<? super E>`
* [025 · Event Sourcing in 60 Lines](025-event-sourcing.md), where events become the source of truth instead of notifications
* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md)

## Sources

* [Guava `EventBus` Javadoc](https://guava.dev/releases/snapshot-jre/api/docs/com/google/common/eventbus/EventBus.html), including the section "Avoid EventBus"
* [`java.lang.ClassValue` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/ClassValue.html)
* Martin Fowler, [What do you mean by "Event-Driven"?](https://martinfowler.com/articles/201701-event-driven.html) (2017)
* [Spring Framework reference: Standard and Custom Events](https://docs.spring.io/spring-framework/reference/core/beans/context-introduction.html#context-functionality-events)
