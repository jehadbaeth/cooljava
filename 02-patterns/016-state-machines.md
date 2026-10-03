# 016 · State Machines with Enums and Sealed Types

> A traffic light fits in an enum. An order with a payment id, a tracking number and a cancellation reason does not, and that is exactly where sealed records take over.

**Since:** Java 21 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

The usual state machine is a `String status` field plus `if` statements scattered over five services:

```java
if (order.status.equals("PAID") && order.trackingNo != null) { ... }
```

Every state shares every field, so a `CART` order has a `trackingNo` (null, hopefully), a `DELIVERED` order might still have a `cancelReason`, and nobody can answer "which transitions exist?" without reading all of the code. Yaron Minsky's advice from the ML world applies directly: **make illegal states unrepresentable**.

## The trick

Use the strongest tool that fits the data:

1. **No data per state? An enum.** Each constant answers "where do I go on this event?" with a constant-specific method. For a table you can print, query or load from configuration, use an `EnumMap<State, EnumMap<Event, State>>` instead.
2. **Data per state? A sealed interface of records.** Each state is a record holding exactly the fields that exist *in that state*. A transition is a `switch` over the state that returns a new record, and the compiler checks that every state is handled.

```java
sealed interface Order permits Cart, Paid, Shipped, Delivered, Cancelled {}
record Paid(List<String> items, String paymentId) implements Order {}
record Shipped(List<String> items, String trackingNo) implements Order {}
```

A `Cart` cannot have a tracking number, because the `Cart` record has no such component. The illegal state does not need a check; it does not exist.

## Full example

```java run
import java.time.LocalDate;
import java.util.*;
import java.util.stream.*;

public class StateMachineDemo {

    // Part 1: an enum. States carry no data; each constant knows its successors.
    enum Signal { TIMER, FAULT, REPAIR }

    enum Light {
        RED      { Light on(Signal s) { return s == Signal.TIMER ? GREEN : common(s); } },
        GREEN    { Light on(Signal s) { return s == Signal.TIMER ? YELLOW : common(s); } },
        YELLOW   { Light on(Signal s) { return s == Signal.TIMER ? RED : common(s); } },
        FLASHING { Light on(Signal s) { return s == Signal.REPAIR ? RED : FLASHING; } };

        abstract Light on(Signal s);

        // Shared rule: any working light starts flashing on a fault; REPAIR is meaningless.
        Light common(Signal s) {
            if (s == Signal.FAULT) return FLASHING;
            throw new IllegalStateException(s + " is not allowed while " + this);
        }
    }

    // Part 1b: the same machine as data, in an EnumMap transition table.
    static final Map<Light, Map<Signal, Light>> TABLE = new EnumMap<>(Light.class);
    static void allow(Light from, Signal signal, Light to) {
        TABLE.computeIfAbsent(from, k -> new EnumMap<>(Signal.class)).put(signal, to);
    }
    static {
        allow(Light.RED, Signal.TIMER, Light.GREEN);
        allow(Light.GREEN, Signal.TIMER, Light.YELLOW);
        allow(Light.YELLOW, Signal.TIMER, Light.RED);
        for (Light l : EnumSet.range(Light.RED, Light.YELLOW)) allow(l, Signal.FAULT, Light.FLASHING);
        for (Signal s : Signal.values()) allow(Light.FLASHING, s, s == Signal.REPAIR ? Light.RED : Light.FLASHING);
    }
    static Optional<Light> next(Light from, Signal signal) {
        return Optional.ofNullable(TABLE.get(from).get(signal));
    }

    // Part 2: sealed records. Each state holds exactly the data that exists in that state.
    sealed interface Order permits Cart, Paid, Shipped, Delivered, Cancelled {}
    record Cart(List<String> items) implements Order {}
    record Paid(List<String> items, String paymentId) implements Order {}
    record Shipped(List<String> items, String trackingNo) implements Order {}
    record Delivered(String trackingNo, LocalDate on) implements Order {}
    record Cancelled(String reason, String refund) implements Order {}

    sealed interface Command permits AddItem, Pay, Ship, Deliver, Cancel {}
    record AddItem(String item) implements Command {}
    record Pay(String paymentId) implements Command {}
    record Ship(String trackingNo) implements Command {}
    record Deliver(LocalDate on) implements Command {}
    record Cancel(String reason) implements Command {}

    static final class IllegalTransition extends RuntimeException {
        IllegalTransition(Order o, Command c, String why) {
            super(c.getClass().getSimpleName() + " rejected in state " + o.getClass().getSimpleName() + ": " + why);
        }
    }

    static Order reject(Order o, Command c, String why) { throw new IllegalTransition(o, c, why); }

    // The outer switch has no default: a new state does not compile until it is handled here.
    static Order apply(Order order, Command cmd) {
        return switch (order) {
            case Cart cart -> switch (cmd) {
                case AddItem(String item) -> new Cart(Stream.concat(cart.items().stream(), Stream.of(item)).toList());
                case Pay p when cart.items().isEmpty() -> reject(order, cmd, "cart is empty");
                case Pay(String paymentId) -> new Paid(cart.items(), paymentId);
                case Cancel(String reason) -> new Cancelled(reason, "none");
                default -> reject(order, cmd, "not paid yet");
            };
            case Paid paid -> switch (cmd) {
                case Ship(String trackingNo) -> new Shipped(paid.items(), trackingNo);
                case Cancel(String reason) -> new Cancelled(reason, paid.paymentId());
                default -> reject(order, cmd, "already paid");
            };
            case Shipped shipped -> switch (cmd) {
                case Deliver(LocalDate on) -> new Delivered(shipped.trackingNo(), on);
                default -> reject(order, cmd, "on its way");
            };
            case Delivered d -> reject(order, cmd, "final state");
            case Cancelled c -> reject(order, cmd, "final state");
        };
    }

    public static void main(String[] args) {
        System.out.println("== traffic light (enum methods)");
        Light light = Light.RED;
        for (Signal s : List.of(Signal.TIMER, Signal.TIMER, Signal.FAULT, Signal.TIMER, Signal.REPAIR)) {
            Light after = light.on(s);
            System.out.println(light + " --" + s + "--> " + after);
            light = after;
        }
        try {
            Light.GREEN.on(Signal.REPAIR);
        } catch (IllegalStateException e) {
            System.out.println("rejected: " + e.getMessage());
        }

        System.out.println("== traffic light (EnumMap table)");
        TABLE.forEach((from, row) -> System.out.println(from + " accepts " + row.keySet()));
        boolean agree = true;
        for (Light l : Light.values())
            for (Signal s : Signal.values()) {
                Optional<Light> viaMethod;
                try { viaMethod = Optional.of(l.on(s)); } catch (IllegalStateException e) { viaMethod = Optional.empty(); }
                agree &= viaMethod.equals(next(l, s));
            }
        System.out.println("methods and table agree on all " + Light.values().length * Signal.values().length + " pairs: " + agree);

        System.out.println("== order (sealed records)");
        Order order = new Cart(List.of());
        var script = List.of(new AddItem("telescope"), new AddItem("tripod"), new Pay("PAY-7"),
                new Ship("TRK-42"), new Deliver(LocalDate.of(2027, 3, 1)));
        for (Command cmd : script) {
            order = apply(order, cmd);
            System.out.println(order);
        }

        for (var attempt : List.<Map.Entry<Order, Command>>of(
                Map.entry(new Cart(List.of()), new Pay("PAY-8")),
                Map.entry(new Cart(List.of("lens")), new Ship("TRK-1")),
                Map.entry(new Paid(List.of("lens"), "PAY-9"), new Cancel("changed my mind")),
                Map.entry(order, new Cancel("too late")))) {
            try {
                System.out.println("ok: " + apply(attempt.getKey(), attempt.getValue()));
            } catch (IllegalTransition e) {
                System.out.println(e.getMessage());
            }
        }
    }
}
```

Output:

```text output
== traffic light (enum methods)
RED --TIMER--> GREEN
GREEN --TIMER--> YELLOW
YELLOW --FAULT--> FLASHING
FLASHING --TIMER--> FLASHING
FLASHING --REPAIR--> RED
rejected: REPAIR is not allowed while GREEN
== traffic light (EnumMap table)
RED accepts [TIMER, FAULT]
GREEN accepts [TIMER, FAULT]
YELLOW accepts [TIMER, FAULT]
FLASHING accepts [TIMER, FAULT, REPAIR]
methods and table agree on all 12 pairs: true
== order (sealed records)
Cart[items=[telescope]]
Cart[items=[telescope, tripod]]
Paid[items=[telescope, tripod], paymentId=PAY-7]
Shipped[items=[telescope, tripod], trackingNo=TRK-42]
Delivered[trackingNo=TRK-42, on=2027-03-01]
Pay rejected in state Cart: cart is empty
Ship rejected in state Cart: not paid yet
ok: Cancelled[reason=changed my mind, refund=PAY-9]
Cancel rejected in state Delivered: final state
```

Why not simply pass the successor to each constant's constructor? Because enum constants are fields, initialized in order, and a constant cannot refer to one declared after it. Only `YELLOW(RED)` is legal here, which is why javac reports two errors:

```java compile-fail
public class ForwardReference {
    enum Light {
        RED(GREEN), GREEN(YELLOW), YELLOW(RED);

        final Light next;
        Light(Light next) { this.next = next; }
    }

    public static void main(String[] args) {
        System.out.println(Light.RED.next);
    }
}
```

```text compile-error
ForwardReference.java:3: error: illegal forward reference
        RED(GREEN), GREEN(YELLOW), YELLOW(RED);
            ^
ForwardReference.java:3: error: illegal forward reference
        RED(GREEN), GREEN(YELLOW), YELLOW(RED);
                          ^
2 errors
```

## How it works

* **Constant-specific methods dodge the forward reference.** Method bodies run long after all constants exist, so `RED` may mention `GREEN` inside `on(...)` even though it may not mention it in its constructor arguments. The shared `common` method holds the rule every working light has in common (a fault makes it flash), and each constant overrides only what differs.
* **The table is data, so you can ask it questions.** `row.keySet()` answers "which signals does this state accept?" without running anything, which is what you need for a UI that greys out buttons, for documentation or for drawing the diagram. Nested `EnumMap`s are arrays indexed by ordinal, so a lookup costs two array accesses.
* **The agreement check is the honest test.** Two representations of one machine can drift apart. The demo compares all 12 (state, signal) pairs, which is cheap and catches typos in either version. In a real codebase pick *one* representation; the comparison here only shows that they describe the same machine.
* **Records make the data per state exact.** `Paid` has a `paymentId`, `Shipped` has a `trackingNo`, `Cancelled` has a `reason` and the payment to refund. Cancelling the `Paid` order in the output yields `refund=PAY-9`, copied from the state it leaves; cancelling a `Cart` records `none`, because there is no payment id to copy. The transition is where data moves from one state to the next.
* **Exhaustiveness lives in the outer switch.** It lists all five states with no `default`, so adding a `Returned` record to `Order` breaks the build right here (see [019](019-visitor-vs-sealed.md) for the exact compiler error). The inner switches use `default` to reject everything they do not mention, which is a deliberate choice explained below.
* **Guards express conditional transitions.** `case Pay p when cart.items().isEmpty()` comes before the general `case Pay(...)`, so paying for an empty cart is rejected with a reason, not turned into an empty paid order.

## Gotchas

* **`default` in the inner switches trades safety for brevity.** Add a new `Refund` command and every state silently rejects it. If you want the compiler to force a decision for every (state, command) pair, list the rejected commands explicitly; on Java 22 or newer that is a one-liner with unnamed patterns, `case Ship _, Deliver _ -> reject(...)`.
* **Transitions return new objects; the caller must keep them.** `apply(order, cmd)` without assigning the result changes nothing. That is the price of immutability, and also why replaying a list of commands (as in the script) gives a free audit log.
* **Persisting sealed states needs a discriminator.** In a database the state usually becomes a `status` column plus nullable columns again. Map to and from the records at the repository boundary, and keep the nulls out of the domain.
* **Enum states are singletons, so they cannot hold per-instance data.** Do not sneak mutable fields into `Light` to remember "flashing since when"; that is the moment to switch to records.
* **Do not hand-roll a workflow engine.** Timers, persistence, retries and human approvals belong to tools built for them (Spring State Machine, Temporal, a BPMN engine). The patterns here are for the state logic inside one service.

## When to use it (and when not to)

Use the enum for small, data-free machines: protocol phases, UI modes, traffic lights, connection states. Switch to an `EnumMap` table when the transitions should be inspectable or come from configuration. Use sealed records as soon as states carry different data, which in business software is almost always: orders, payments, subscriptions, support tickets. All three are plain Java with no framework, and all three put the whole machine on one screen.

## Related

* [015 · Enums with Behavior: Strategy Pattern without Classes](015-enum-strategy.md)
* [030 · Phantom Types: Let the Compiler Track State](../04-generics/030-phantom-types.md), for checking transitions at compile time instead of run time
* [019 · The Visitor Pattern Is Dead, Long Live Sealed Types](019-visitor-vs-sealed.md)
* [025 · Event Sourcing in 60 Lines](../03-build-it-yourself/025-event-sourcing.md), where the command script becomes the source of truth

## Sources

* Yaron Minsky, [Effective ML Revisited](https://blog.janestreet.com/effective-ml-revisited/) (2011), "make illegal states unrepresentable"
* [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441) and [JEP 440: Record Patterns](https://openjdk.org/jeps/440)
* [`java.util.EnumMap` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/EnumMap.html)
* [JLS §8.3.3: Restrictions on Field References in Initializers](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.3.3)
