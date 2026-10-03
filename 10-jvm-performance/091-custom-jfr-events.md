# 091 · Custom JFR Events: A Flight Recorder for Your Own Code

> The JVM already records GC pauses, lock contention and JIT decisions in a low-overhead black box. Subclass one class and your own business events land in the same timeline.

**Since:** Java 16 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

A customer says "checkout was slow around 14:05". You have logs with timestamps and strings, metrics with five-minute averages, and a profiler that was not attached. None of them can tell you which orders were slow, what the GC was doing at that moment, or whether the threads were blocked on a lock.

`System.nanoTime()` around a block plus a log line gets you one of those answers, at the price of formatting, I/O and a log format nobody can query.

## The trick

Java Flight Recorder (JFR) is built into HotSpot. It keeps typed, timestamped events in per-thread buffers and writes them to a ring of files on disk. The JDK emits close to 200 event types itself, and the API in `jdk.jfr` lets you add your own. Define one by subclassing `jdk.jfr.Event`:

```java
@Name("demo.OrderProcessed")
@Label("Order Processed")
@Category({"Demo", "Orders"})
static class OrderProcessed extends Event {
    @Label("Order id") long orderId;
    @Label("Customer") String customer;
}
```

Then time and report a piece of work:

```java
var event = new OrderProcessed();
event.begin();
// ... the work being measured ...
event.end();
if (event.shouldCommit()) {
    event.orderId = id;          // only fill in fields if somebody will read them
    event.customer = customer;
    event.commit();
}
```

Every field is a typed column. Start time, duration, thread and (optionally) stack trace come for free. `shouldCommit()` is the important method: it is `false` when no recording is running, when the event is disabled, or when the duration is below the configured threshold. Put everything expensive behind it.

## Full example

The program defines an event, records four orders into a file under a temporary directory, reads the file back with `RecordingFile`, and then watches three more orders live with a `RecordingStream`. Two of the four recorded orders take over 50 ms and the threshold is 50 ms, so only those two are committed.

```java run
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import jdk.jfr.*;
import jdk.jfr.consumer.*;

public class OrderEvents {

    @Name("demo.OrderProcessed")
    @Label("Order Processed")
    @Category({"Demo", "Orders"})
    @Description("One order went through the pipeline")
    static class OrderProcessed extends Event {
        @Label("Order id") long orderId;
        @Label("Customer") String customer;
        @Label("Line items") int items;
        @Label("Payload") @DataAmount long payloadBytes;
    }

    static int expensiveCalls = 0;

    static long expensiveSize(int orderId) {
        expensiveCalls++;
        return orderId * 1024L;
    }

    static void process(int orderId, String customer, int items, int pauseMillis) throws InterruptedException {
        var event = new OrderProcessed();
        event.begin();
        Thread.sleep(pauseMillis);                 // stands in for the real work
        event.end();
        if (event.shouldCommit()) {
            event.orderId = orderId;
            event.customer = customer;
            event.items = items;
            event.payloadBytes = expensiveSize(orderId);
            event.commit();
        }
    }

    public static void main(String[] args) throws Exception {
        Path dir = Files.createTempDirectory("jfr-demo");
        Path file = dir.resolve("orders.jfr");
        try {
            EventType type = EventType.getEventType(OrderProcessed.class);
            System.out.println("type:     " + type.getName() + " (" + type.getLabel() + ")");
            System.out.println("category: " + type.getCategoryNames());
            var builtIn = Set.of("startTime", "duration", "eventThread", "stackTrace");
            System.out.println("fields:   " + type.getFields().stream()
                    .map(ValueDescriptor::getName).filter(name -> !builtIn.contains(name)).toList());

            process(0, "nobody", 1, 120);          // no recording yet, so shouldCommit() is false
            System.out.println("expensiveSize calls before recording: " + expensiveCalls);

            try (Recording recording = new Recording()) {
                recording.enable(OrderProcessed.class).withThreshold(Duration.ofMillis(50)).withoutStackTrace();
                recording.setDestination(file);    // written when the recording stops
                recording.start();
                process(1, "ada", 3, 0);
                process(2, "linus", 1, 120);
                process(3, "grace", 7, 0);
                process(4, "margaret", 2, 150);
                recording.stop();
            }
            System.out.println("expensiveSize calls after recording:  " + expensiveCalls);

            List<RecordedEvent> events = RecordingFile.readAllEvents(file);
            System.out.println("events in file: " + events.size());
            for (RecordedEvent e : events) {
                System.out.printf("  order %d for %s: %d items, %d bytes, slow=%b, stack=%s%n",
                        e.getLong("orderId"), e.getString("customer"), e.getInt("items"),
                        e.getLong("payloadBytes"), e.getDuration().toMillis() >= 50, e.getStackTrace());
            }

            // Live, in-process monitoring: no file, a callback fires as events are flushed.
            var live = Collections.synchronizedList(new ArrayList<String>());
            var seen = new CountDownLatch(3);
            try (var stream = new RecordingStream()) {
                stream.enable(OrderProcessed.class).withThreshold(Duration.ZERO).withoutStackTrace();
                stream.onEvent("demo.OrderProcessed", e -> {
                    live.add("order " + e.getLong("orderId") + " for " + e.getString("customer"));
                    seen.countDown();
                });
                stream.startAsync();
                process(10, "dennis", 1, 0);
                process(11, "barbara", 2, 0);
                process(12, "ken", 3, 0);
                System.out.println("stream delivered all three? " + seen.await(10, TimeUnit.SECONDS));
            }
            live.stream().sorted().forEach(line -> System.out.println("  live: " + line));
        } finally {
            try (Stream<Path> files = Files.walk(dir)) {
                files.sorted(Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
            }
        }
    }
}
```

Output:

```text output
type:     demo.OrderProcessed (Order Processed)
category: [Demo, Orders]
fields:   [orderId, customer, items, payloadBytes]
expensiveSize calls before recording: 0
expensiveSize calls after recording:  2
events in file: 2
  order 2 for linus: 1 items, 2048 bytes, slow=true, stack=null
  order 4 for margaret: 2 items, 4096 bytes, slow=true, stack=null
stream delivered all three? true
  live: order 10 for dennis
  live: order 11 for barbara
  live: order 12 for ken
```

## How it works

* **The base class is a stub.** The methods on `jdk.jfr.Event` have empty bodies in the JDK source. When your subclass is loaded, JFR instruments it and fills in `begin`, `end`, `commit` and `shouldCommit`. That is why `Event` has `final` methods and why you cannot meaningfully override them.
* **Registration is automatic.** The event is registered with the recorder the first time the class is used (`@Registered` defaults to `true`), and `EventType.getEventType(...)` returns its metadata: the `@Name`, the `@Label`, the `@Category` path shown as a tree in tools, and the fields.
* **Fields are columns.** Primitives, `String`, `Thread` and `Class` are supported. The output lists the four fields we declared, in addition to the built-in `startTime`, `duration`, `eventThread` and `stackTrace` that every event has. `@DataAmount` is a unit hint so tools can show `4 kB` instead of `4096`.
* **`shouldCommit()` is the cost control.** Before the recording started, the pre-run call to `process(0, ...)` took 120 ms, yet `expensiveSize` was never called (first count: 0). Inside the recording, four orders ran but only the two slower than the 50 ms threshold made it past `shouldCommit()`, so `expensiveSize` ran exactly twice and the file holds exactly two events. The fast orders paid for a timestamp pair and a branch, nothing more.
* **Settings are per recording.** `recording.enable(...)` returns an `EventSettings` for threshold, stack trace and period. `withoutStackTrace()` is why `getStackTrace()` prints `null`. Stack traces are on by default and walking the stack is a noticeable part of the cost of a commit, so turn them off for hot events that do not need them.
* **`RecordingFile` reads the binary format back.** Fields are fetched by name and type (`getLong("orderId")`). That makes JFR a decent test oracle too: assert in a unit test that your code emitted the events you expect.
* **`RecordingStream` is the live version (Java 14, JEP 349).** Events are flushed from the thread-local buffers about once a second, and a separate thread parses them and calls your handler. That is why the example waits on a `CountDownLatch` instead of assuming the callback already ran. Handlers see events in order, but not instantly.

The example uses `Stream.toList()` (Java 16) and `RecordingStream` (Java 14), so Java 16 is the floor. The event API itself dates from Java 9 and shipped in OpenJDK 11.

### The command line half

In production you rarely write a `Recording` yourself. You start one with a JVM flag and inspect the file with the `jfr` tool. Take a tiny program with two events and no recording code at all:

```java
@Name("demo.Greeting")
@Label("Greeting")
@StackTrace(false)
static class Greeting extends Event {
    @Label("Who") String who;
    @Label("Length") int length;
}
// main: for "Ada" and "Grace", fill a Greeting and call commit()
```

```shell
javac Hello.java
java -Xlog:disable -XX:StartFlightRecording:filename=hello.jfr,settings=none Hello
jfr print --events demo.Greeting hello.jfr
```

```text
demo.Greeting {
  startTime = 10:55:03.543 (2026-10-03)
  who = "Ada"
  length = 3
  eventThread = "main" (javaThreadId = 3)
}

demo.Greeting {
  startTime = 10:55:03.543 (2026-10-03)
  who = "Grace"
  length = 5
  eventThread = "main" (javaThreadId = 3)
}
```

`settings=none` starts a recording without any of the built-in events, so only ours show up (use `settings=profile` for the full picture). The timestamps above are from one real run and will differ on yours. `jfr view` renders the same data as a table and uses your `@Label` texts for the column headings:

```shell
jfr view demo.Greeting hello.jfr
```

```text
                                     Greeting

Start Time Duration Event Thread         Stack Trace         Who           Length
---------- -------- -------------------- ------------------- ------------- ------
10:55:03        0 s main                 N/A                 Ada                3
10:55:03        0 s main                 N/A                 Grace              5
```

`jfr summary` lists event counts per type, and `jfr print --json` gives machine-readable output. For a JVM that is already running, `jcmd <pid> JFR.start` and `jcmd <pid> JFR.dump` do the same without a restart.

## Gotchas

* **Silent field loss.** Arrays, enums and other reference types are silently ignored, as are `transient` and `static` fields. No error, the column just does not exist. Use a `String` or a number.
* **No `begin()` means duration zero.** If you call only `commit()`, the event has a start time and a zero duration. That is fine for "something happened", wrong for "how long did it take". `begin()` and `end()` are what make the threshold meaningful.
* **One event object per occurrence.** Do not cache and reuse an event instance, and never share one between threads. Allocate a new one each time, short-lived objects are cheap.
* **Fill in fields after the `shouldCommit()` check, not before.** Anything you compute for the event (sizes, hashes, string formatting) is wasted work when the event is dropped. That is the single most common way to make custom events slower than they should be.
* **Defaults differ for your own events.** The `@Threshold` default is `0 ns`, so your event records every occurrence unless you annotate it (`@Threshold("20 ms")`) or set a threshold in the recording. The JDK's own `default.jfc` profile mostly uses 0, 10 or 20 ms for its events, and a hot path with millions of events per second fills a recording fast.
* **Pick stable names.** Without `@Name` the event is called after the class, including the enclosing class and `$`. A reverse-DNS name (`com.example.Orders.Processed`) survives refactoring and is what you filter on in `jfr print --events`.
* **`jdk.jfr` must be present.** A `jlink` image or a minimal container without the `jdk.jfr` module cannot record anything.
* **A recording is not a metrics system.** Events live in a bounded buffer or ring of files, are meant to be pulled after the fact (`jcmd <pid> JFR.dump`) and have no alerting. Use them for diagnosis, and keep counters and histograms for dashboards.

## When to use it (and when not to)

Use it for latency-sensitive or incident-prone seams: a request pipeline, a cache refill, a retry loop, a circuit breaker changing state. Run JFR continuously with a maximum age (`-XX:StartFlightRecording:maxage=1h,...`), and when something goes wrong dump the last hour and see your events next to GC, safepoints and thread states. JEP 328 sets the goal of at most 1% overhead for the default configuration, and no measurable overhead when it is not enabled. Your own events are as cheap as you make them.

Do not use it as a logging replacement (no free text, no levels, no shipping to a log aggregator) or for per-element events inside a tight loop. For benchmarks, use JMH.

## Related

* [077 · Virtual Threads: A Million Threads and the Pinning Trap](../09-concurrency/077-virtual-threads.md), where the built-in `jdk.VirtualThreadPinned` event is the tool for finding pinning
* [023 · A Circuit Breaker in 80 Lines](../03-build-it-yourself/023-circuit-breaker.md), a natural place to emit an event on every state change
* [092 · Cheap Exceptions: The Cost of a Stack Trace](092-cheap-exceptions.md), because stack trace capture is the same cost that `@StackTrace(false)` avoids here

## Sources

* [`jdk.jfr.Event` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.jfr/jdk/jfr/Event.html)
* [`jdk.jfr.consumer.RecordingStream` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.jfr/jdk/jfr/consumer/RecordingStream.html)
* [JEP 328: Flight Recorder](https://openjdk.org/jeps/328) and [JEP 349: JFR Event Streaming](https://openjdk.org/jeps/349)
* [The `jfr` command (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/specs/man/jfr.html)
