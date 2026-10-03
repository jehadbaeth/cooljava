# 025 · Event Sourcing in 60 Lines

> Don't store the balance. Store everything that ever happened to the account, and let the balance be a fold. Records and sealed types make the whole model about a page long.

**Since:** Java 21 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

A classic `accounts` table has a `balance` column, and every operation overwrites it:

```sql
UPDATE accounts SET balance = balance - 30.00 WHERE id = 42;
```

After the update, the old value is gone. Why is the balance 25.50? When was it last above 100? What did the account look like when the customer complained last Tuesday? Who knows. You can bolt on an audit table, but then you have two sources of truth that can disagree, and the audit table always loses that argument.

## The trick

**Event sourcing** turns this around. The source of truth is an append-only log of *events*, facts in the past tense: `Opened`, `Deposited`, `Withdrawn`, `Closed`. The current state is not stored; it is computed by folding the events, starting from an empty account:

```text
state = events.fold(EMPTY, (account, event) -> account.apply(event))
```

The functional shape that falls out (Jérémie Chassaing calls it the *Decider*) has exactly two functions:

* **`decide(state, command) -> events`** holds the business rules. It looks at the current state and either turns a *command* (a request in the imperative, like `Withdraw`) into new events, or rejects it.
* **`evolve(state, event) -> state`** applies one fact. It never validates and never fails: an event already happened, so arguing with it is pointless.

Both are pure functions, so sealed interfaces, records and pattern matching `switch` fit them perfectly. The compiler checks that every event is handled in `evolve` and every command in `decide`. Everything else (rebuilding state, snapshots, time travel, new read models) is just a fold over a different slice of the log.

## Full example

The model (events, commands, state, `apply`, `decide` and the store) is 57 lines from the first `sealed interface` to the end of `EventStore`, not counting blank lines and comments. The demo follows.

```java run
import java.util.*;

public class EventSourcingDemo {

    // Events: facts in the past tense. Stored forever, never changed, never validated again.
    sealed interface Event permits Opened, Deposited, Withdrawn, Closed {}
    record Opened(String owner) implements Event {}
    record Deposited(long cents) implements Event {}
    record Withdrawn(long cents) implements Event {}
    record Closed() implements Event {}

    // Commands: requests in the imperative. They may be rejected.
    sealed interface Command permits Open, Deposit, Withdraw, Close {}
    record Open(String owner) implements Command {}
    record Deposit(long cents) implements Command {}
    record Withdraw(long cents) implements Command {}
    record Close() implements Command {}

    static final class Rejected extends RuntimeException {
        Rejected(String reason) { super(reason); }
    }

    record Account(String owner, long balance, boolean open, int version) {
        static final Account NONE = new Account(null, 0, false, 0);

        // evolve: the only place where state changes. Pure, total, no validation.
        Account apply(Event event) {
            return switch (event) {
                case Opened(String name) -> new Account(name, 0, true, version + 1);
                case Deposited(long cents) -> new Account(owner, balance + cents, open, version + 1);
                case Withdrawn(long cents) -> new Account(owner, balance - cents, open, version + 1);
                case Closed() -> new Account(owner, balance, false, version + 1);
            };
        }

        static Account replay(Account start, List<Event> events) {
            Account state = start;
            for (Event event : events) state = state.apply(event);
            return state;
        }
    }

    // decide: the business rules. Reads the current state, returns new facts or says no.
    static List<Event> decide(Account state, Command command) {
        return switch (command) {
            case Open(String owner) when state.version() > 0 -> throw new Rejected("account already exists");
            case Open(String owner) -> List.of(new Opened(owner));
            case Command c when !state.open() -> throw new Rejected("account is not open");
            case Deposit(long cents) when cents <= 0 -> throw new Rejected("deposit must be positive");
            case Deposit(long cents) -> List.of(new Deposited(cents));
            case Withdraw(long cents) when cents > state.balance() -> throw new Rejected(
                    "insufficient funds: balance " + money(state.balance()) + ", requested " + money(cents));
            case Withdraw(long cents) -> List.of(new Withdrawn(cents));
            case Close() when state.balance() != 0 -> throw new Rejected("balance must be zero to close");
            case Close() -> List.of(new Closed());
        };
    }

    /** Append-only streams with optimistic concurrency: you must say which version you decided on. */
    static final class EventStore {
        private final Map<String, List<Event>> streams = new HashMap<>();

        synchronized List<Event> load(String stream) {
            return List.copyOf(streams.getOrDefault(stream, List.of()));
        }

        synchronized void append(String stream, int expectedVersion, List<Event> events) {
            List<Event> log = streams.computeIfAbsent(stream, s -> new ArrayList<>());
            if (log.size() != expectedVersion) {
                throw new IllegalStateException("conflict: decided on version " + expectedVersion
                        + " but the stream is at version " + log.size());
            }
            log.addAll(events);
        }
    }

    // ---------- Demo ----------

    static String money(long cents) { return "%d.%02d".formatted(cents / 100, cents % 100); }

    static void handle(EventStore store, String stream, Command command) {
        Account state = Account.replay(Account.NONE, store.load(stream));
        try {
            List<Event> events = decide(state, command);
            store.append(stream, state.version(), events);
            System.out.println("  " + command + " -> " + events);
        } catch (Rejected e) {
            System.out.println("  " + command + " -> rejected: " + e.getMessage());
        }
    }

    public static void main(String[] args) {
        var store = new EventStore();
        System.out.println("commands:");
        handle(store, "acc-42", new Open("Ada"));
        handle(store, "acc-42", new Deposit(100_00));
        handle(store, "acc-42", new Withdraw(30_00));
        handle(store, "acc-42", new Deposit(5_50));
        handle(store, "acc-42", new Withdraw(200_00));
        handle(store, "acc-42", new Deposit(-1));

        // Two clerks read version 4 at the same time. The first append wins, the second must retry.
        System.out.println("two clerks, one stream:");
        Account seenByBoth = Account.replay(Account.NONE, store.load("acc-42"));
        store.append("acc-42", seenByBoth.version(), decide(seenByBoth, new Deposit(20_00)));
        System.out.println("  clerk A appended a deposit of 20.00");
        try {
            store.append("acc-42", seenByBoth.version(), decide(seenByBoth, new Withdraw(70_00)));
        } catch (IllegalStateException e) {
            System.out.println("  clerk B: " + e.getMessage() + ", reloading and retrying");
            handle(store, "acc-42", new Withdraw(70_00));
        }
        handle(store, "acc-42", new Close());
        handle(store, "acc-42", new Withdraw(25_50));
        handle(store, "acc-42", new Close());

        List<Event> history = store.load("acc-42");
        System.out.println("statement (replaying the log):");
        Account running = Account.NONE;
        for (Event event : history) {
            running = running.apply(event);
            System.out.printf("  v%d %-22s balance %7s%n", running.version(), event, money(running.balance()));
        }
        System.out.println("current: " + Account.replay(Account.NONE, history));

        // Time travel: the state as of any version is a fold over a prefix of the log.
        System.out.println("as of v3: " + Account.replay(Account.NONE, history.subList(0, 3)));

        // Snapshot: cache a state, then replay only the tail. Must equal the full replay.
        Account snapshot = Account.replay(Account.NONE, history.subList(0, 5));
        List<Event> tail = history.subList(snapshot.version(), history.size());
        Account fromSnapshot = Account.replay(snapshot, tail);
        System.out.println("snapshot at v" + snapshot.version() + " + " + tail.size() + " events equals full replay of "
                + history.size() + ": " + fromSnapshot.equals(Account.replay(Account.NONE, history)));

        // A brand new read model, answered from old facts: nobody planned for this question.
        long largestDeposit = history.stream()
                .mapToLong(e -> e instanceof Deposited(long cents) ? cents : 0).max().orElse(0);
        System.out.println("largest deposit ever: " + money(largestDeposit));
    }
}
```

Output:

```text output
commands:
  Open[owner=Ada] -> [Opened[owner=Ada]]
  Deposit[cents=10000] -> [Deposited[cents=10000]]
  Withdraw[cents=3000] -> [Withdrawn[cents=3000]]
  Deposit[cents=550] -> [Deposited[cents=550]]
  Withdraw[cents=20000] -> rejected: insufficient funds: balance 75.50, requested 200.00
  Deposit[cents=-1] -> rejected: deposit must be positive
two clerks, one stream:
  clerk A appended a deposit of 20.00
  clerk B: conflict: decided on version 4 but the stream is at version 5, reloading and retrying
  Withdraw[cents=7000] -> [Withdrawn[cents=7000]]
  Close[] -> rejected: balance must be zero to close
  Withdraw[cents=2550] -> [Withdrawn[cents=2550]]
  Close[] -> [Closed[]]
statement (replaying the log):
  v1 Opened[owner=Ada]      balance    0.00
  v2 Deposited[cents=10000] balance  100.00
  v3 Withdrawn[cents=3000]  balance   70.00
  v4 Deposited[cents=550]   balance   75.50
  v5 Deposited[cents=2000]  balance   95.50
  v6 Withdrawn[cents=7000]  balance   25.50
  v7 Withdrawn[cents=2550]  balance    0.00
  v8 Closed[]               balance    0.00
current: Account[owner=Ada, balance=0, open=false, version=8]
as of v3: Account[owner=Ada, balance=7000, open=true, version=3]
snapshot at v5 + 3 events equals full replay of 8: true
largest deposit ever: 100.00
```

## How it works

* **Two vocabularies.** Commands are wishes (`Withdraw[cents=20000]`), events are facts (`Withdrawn[cents=3000]`). Only `decide` turns one into the other, and it is the only code that can say no: the 200.00 withdrawal and the negative deposit are rejected there and leave no trace in the log.
* **`apply` never fails.** It has no `if`, no exceptions and no I/O. That is essential, because it runs again on every replay, possibly years later, possibly on events written by an older version of your code. If the rules change, `decide` changes; history stays valid.
* **Exhaustive switches guard the model.** Add a `Frozen` event to the `permits` clause and `apply` stops compiling until it handles it. The guarded `case Command c when !state.open()` catches every command on a closed or unopened account in one line, and the unguarded cases after it keep the switch exhaustive.
* **The version is the concurrency control.** Each decision is made on a specific version, and `append` refuses to write if the stream has moved on. Clerk B decided on version 4, clerk A got there first, so B's append fails, B reloads version 5 and decides again. In a database this is a unique constraint on `(stream_id, version)`.
* **Time travel is a prefix.** "As of v3" folds only the first three events. The same technique answers "what was the balance on March 3rd" if events carry timestamps.
* **Snapshots are a cache, not a source of truth.** The snapshot at version 5 plus the three remaining events gives exactly the same record as replaying all eight, and record equality proves it in one call. If a snapshot is ever wrong, throw it away and replay.
* **New questions, old data.** "Largest deposit ever" was not a requirement when the events were written, yet it can be answered retroactively. With a `balance` column that information was destroyed on every update.

## Gotchas

* **Events are forever, so their schema is too.** Renaming a field in `Deposited` breaks every stored event. Plan for versioned events and *upcasters* that translate old shapes into new ones while reading.
* **Replay must be deterministic.** No `Instant.now()`, no random numbers, no lookups in `apply`. Anything that varies belongs in the event itself, decided once in `decide`.
* **Side effects belong outside the fold.** Sending the welcome email inside `apply` sends it again on every replay. React to newly appended events instead (an outbox or a subscription), never to replayed ones.
* **Long streams get slow.** Thousands of events per aggregate means snapshots, or a sign that the aggregate boundary is wrong. Keep streams small (one account, one order) rather than one stream for everything.
* **Reads usually need projections.** "All accounts with a balance over 1000" cannot be answered by replaying every stream on each query. Event-sourced systems maintain separate read models updated from the event stream (CQRS), which are eventually consistent.
* **Deleting data is hard.** "Append-only forever" collides with the right to erasure. The usual answer is crypto-shredding: encrypt personal data per user and delete the key.

## When to use it (and when not to)

Event sourcing pays off where history *is* the domain: ledgers and payments, order lifecycles, inventory movements, anything audited or regulated, and systems where you will want to answer questions nobody has thought of yet. It is a poor fit for CRUD screens, for data whose history nobody cares about, and for teams new to it under deadline pressure: the projections, schema evolution and eventual consistency are real costs, paid every day.

The toy leaves out persistence, event metadata (ids, timestamps, causation), subscriptions, projections, upcasting and snapshots stored outside memory. For production on the JVM, look at Axon Framework, at a dedicated event store such as KurrentDB (formerly EventStoreDB), or at a plain relational table with a `(stream_id, version)` unique key, which takes you surprisingly far. Whatever you pick, keep `decide` and `apply` as pure as they are here: that part of the toy is exactly right.

## Related

* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md), the modeling toolkit used here
* [016 · State Machines with Enums and Sealed Types](../02-patterns/016-state-machines.md), the account lifecycle as an explicit state machine
* [017 · Command Pattern with Undo and Redo in Lambdas](../02-patterns/017-command-undo.md), commands without the event log
* [020 · A Type-Safe Event Bus in 50 Lines](020-event-bus.md), events as notifications rather than as the source of truth

## Sources

* Martin Fowler, [Event Sourcing](https://martinfowler.com/eaaDev/EventSourcing.html) (2005)
* Jérémie Chassaing, [Functional Event Sourcing Decider](https://thinkbeforecoding.com/post/2021/12/17/functional-event-sourcing-decider) (2021)
* Greg Young, [CQRS Documents](https://cqrs.files.wordpress.com/2010/11/cqrs_documents.pdf) (2010)
* [Event Sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing), Azure Architecture Center
