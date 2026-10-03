# 084 · The Loop That Never Ends: volatile and the Memory Model

> One thread sets a flag to `false`. Another checks that flag on every iteration and carries on regardless, forever. The JVM is not buggy: the memory model allowed it.

**Since:** Java 9 · **Category:** [Concurrency](../README.md#concurrency) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

A worker spins in a loop for as long as a flag is `true`. After a short pause, `main` flips the flag and waits for the worker to finish:

```java
static boolean running = true;

Thread worker = new Thread(() -> {
    while (running) {
        spins++;
    }
});
worker.start();
Thread.sleep(300);
running = false;      // please stop
worker.join();        // ...and does it?
```

Does `worker.join()` return? Think about it before you read on. Then notice that the real example below does *not* call a bare `join()`. It marks the worker as a daemon thread and waits with a timeout, because the honest answer is "that depends on the JIT compiler".

## The answer

On the HotSpot JVM, with default settings, this loop very often **never ends**. On JDK 25 and JDK 17 on the machine that produced the output below, it hung every time in the runs behind this page. But a hang is not what the language promises either. The Java memory model (JMM) only says that the worker is *allowed* never to see the write, because nothing creates a happens-before relationship between `running = false` in one thread and `while (running)` in the other. Whether the worker notices is up to the interpreter, the JIT compiler and the CPU, so you cannot test your way to safety. The program is wrong, and it is also unreliable evidence of that.

The fix is one keyword (`volatile`), and the second program below shows it and its siblings.

## Full example

The first program is the puzzle with a safety net. The worker is a **daemon thread**, so a stuck worker cannot keep the JVM alive, and `main` waits with a timeout and prints whether the worker really stopped. It is marked `nondeterministic` because the outcome belongs to the JIT, not to the code: the sample below shows what happened on one run, and on another JVM or with other flags it can print `true`.

```java run nondeterministic
public class StopFlag {

    static boolean running = true;      // plain field: no volatile, no lock, no atomic
    static long spins;

    public static void main(String[] args) throws InterruptedException {
        Thread worker = new Thread(() -> {
            while (running) {
                spins++;
            }
        }, "spinner");
        worker.setDaemon(true);         // a stuck worker must not keep the JVM alive
        worker.start();

        Thread.sleep(300);              // long enough for the loop to be hot and compiled
        running = false;                // the stop request
        worker.join(1_000);             // wait at most one second
        System.out.println("worker stopped: " + !worker.isAlive());
    }
}
```

Output:

```text output
worker stopped: false
```

The cause is the JIT, and you can test that. Save the program as `StopFlag.java` and run it with different compiler settings (the four outputs below are in the same order as the four commands):

```shell
java StopFlag.java
java -Xint StopFlag.java
java -XX:TieredStopAtLevel=1 StopFlag.java
java -XX:-UseOnStackReplacement StopFlag.java
```

```text
worker stopped: false
worker stopped: true
worker stopped: true
worker stopped: true
```

`-Xint` disables the JIT compiler, `TieredStopAtLevel=1` allows only the simple C1 compiler, and `-UseOnStackReplacement` forbids compiling a method that is already running (our `run` method is entered once and never returns, so that is the only way it can be compiled). The loop ends in all three of the modified runs and hangs in the default one, so it takes the optimizing C2 compiler, applied in the middle of the loop, to make the write invisible.

Now the cures. Each variant starts a daemon spinner on its own flag, waits 200 ms, requests the stop and reports whether the thread ended within five seconds. The program also shows two of the happens-before edges that make *plain* fields safe to share. Everything here is guaranteed by the memory model, so the output is deterministic.

```java run
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

public class StopFlagFixed {

    static volatile boolean volatileFlag = true;
    static final AtomicBoolean atomicFlag = new AtomicBoolean(true);
    static boolean guardedFlag = true;                       // plain, but only touched under the lock
    static synchronized boolean isGuarded() { return guardedFlag; }
    static synchronized void stopGuarded() { guardedFlag = false; }

    /** Starts a daemon spinner, lets it run, requests the stop and reports whether the thread ended. */
    static boolean runAndStop(Runnable spinLoop, Consumer<Thread> stopRequest) throws InterruptedException {
        Thread worker = new Thread(spinLoop);
        worker.setDaemon(true);
        worker.start();
        Thread.sleep(200);
        stopRequest.accept(worker);
        worker.join(5_000);
        return !worker.isAlive();
    }

    static int payload;                                      // plain field, published through a volatile flag
    static volatile boolean published;

    public static void main(String[] args) throws InterruptedException {
        System.out.println("volatile:      stopped=" + runAndStop(
                () -> { while (volatileFlag) { } }, t -> volatileFlag = false));
        System.out.println("AtomicBoolean: stopped=" + runAndStop(
                () -> { while (atomicFlag.get()) { } }, t -> atomicFlag.set(false)));
        System.out.println("synchronized:  stopped=" + runAndStop(
                () -> { while (isGuarded()) { } }, t -> stopGuarded()));
        System.out.println("interrupt:     stopped=" + runAndStop(
                () -> { while (!Thread.currentThread().isInterrupted()) { } }, Thread::interrupt));

        // Edge 1: a volatile write publishes everything the writer did before it, even plain writes.
        Thread reader = new Thread(() -> {
            while (!published) Thread.onSpinWait();
            System.out.println("reader sees payload=" + payload);
        });
        reader.setDaemon(true);
        reader.start();
        payload = 42;               // plain write ...
        published = true;           // ... ordered before this volatile write, which the reader's read pairs with
        reader.join(5_000);

        // Edge 2: start() and join() order the plain data on both sides.
        int[] box = {7};
        Thread doubler = new Thread(() -> box[0] *= 6);      // sees 7 because of the start() edge
        doubler.start();
        doubler.join();
        System.out.println("after join: " + box[0]);          // sees 42 because of the join() edge
    }
}
```

Output:

```text output
volatile:      stopped=true
AtomicBoolean: stopped=true
synchronized:  stopped=true
interrupt:     stopped=true
reader sees payload=42
after join: 42
```

## Why

**The JIT makes a legal optimization.** Inside the loop nothing writes `running`, takes a lock or calls anything the compiler has to treat as a synchronization point. As far as the Java memory model is concerned, the loop is not allowed to rely on another thread's writes, so the compiler may read the field *once*, before the loop. In effect, `while (running) { spins++; }` becomes `if (running) { while (true) { spins++; } }`. That is a textbook loop-invariant hoist, applied here by C2 after the loop became hot and the JVM swapped the running interpreter frame for compiled code (on-stack replacement). The interpreter, and the simple C1 compiler, re-read the field each time round, which is why the experiment above ends in those modes.

**Visibility needs an edge, not just a write.** The JMM defines which writes a read is allowed to see in terms of *happens-before*. If write *W* happens-before read *R*, then *R* sees *W* or something later. If there is no such chain between them, *R* may see any earlier write, including the initial value, forever. Here there is no edge between `running = false` and `while (running)`, so the worker is allowed to see `true` forever. `volatile`, `AtomicBoolean`, a lock and interruption each create that edge in a different way.

The rules worth knowing (JLS §17.4.5, §17.5, §12.4.2 and the `java.util.concurrent` package documentation):

| Action | Happens-before |
|---|---|
| Any action in a thread | later actions of the same thread (program order) |
| Unlocking a monitor (leaving `synchronized`) | every later lock of the same monitor |
| Write of a `volatile` field (and `AtomicX.set`) | every later read of that field |
| `Thread.start()` | every action in the started thread |
| Last action of a thread | another thread's `join()` returning, or `isAlive()` returning `false` |
| `Thread.interrupt()` | the interrupted thread detecting it (`isInterrupted`, `InterruptedException`) |
| End of a constructor, for `final` fields | any thread that gets the reference and reads those fields |
| End of static initialization | the first use of the class |
| Submitting to an `Executor`, `countDown()`, putting into a concurrent collection | what the other side does after the matching `get`, `await` or `take` |

Happens-before is transitive. The second program rests on that: `payload = 42` comes before the volatile write in program order, which comes before the reader's volatile read of `true`, which comes before `println`. That is why a plain `int` can be published safely through a volatile flag. Immutable objects are safe for a different reason: the `final` field rule in the table gives them their own edge.

## Gotchas

* **Volatile is about visibility and ordering, not atomicity.** `volatile int counter; counter++` still loses updates ([083](083-starting-gun.md) shows it). A stop flag is the textbook safe use, because one thread writes and the others only read.
* **Adding a call "fixes" it, which is worse.** In my runs on JDK 25, a `System.out.print("")`, `Thread.yield()`, `Thread.onSpinWait()` or `Thread.sleep(1)` in the loop made it end. These calls are opaque to the optimizer, so it does not hoist across them. But JLS §17.3 says explicitly that `sleep` and `yield` have no synchronization semantics, and its own example of broken code is `while (!this.done) Thread.sleep(1000);`, which the compiler is "free to read just once". The program is still racy and merely hides it on today's HotSpot. A heisenbug that disappears when you add logging is this one.
* **Plain `long` and `double` may tear.** JLS §17.7 allows a write of a non-volatile `long` or `double` to be done as two separate 32-bit writes, so a reader could see half of one value and half of another. 64-bit HotSpot does not do that in practice, so it cannot be demonstrated honestly, but the spec permits it. `volatile` long and double are always atomic. Single writes of every other type are atomic.
* **`final` is not a stop flag.** Final fields give the freeze guarantee only for the *initial* value after construction, and only if `this` does not escape from the constructor.
* **A passing test is not a verdict.** With `-Xint`, or on a loop that happens to be compiled differently, the broken code works. Never accept "it works on my machine" for a data race.
* **Keep a worker interruptible.** For anything that blocks or runs long, `Thread.interrupt()` and checking `isInterrupted()` is the standard cancellation protocol, and it already carries the edge.

## How to stay safe

* Share mutable state between threads only through `volatile`, atomics, locks or thread-safe collections, and say so in the field's declaration or documentation.
* Prefer **interruption** or a `volatile boolean` / `AtomicBoolean` for stop signals, and make the loop body do real work or block, rather than spin.
* Treat any field read by more than one thread without one of those tools as a bug, even if it has never failed. Tools such as [jcstress](https://github.com/openjdk/jcstress) exist to find the ones that fail only on some CPUs.
* Publish immutable objects with `final` fields, or through a volatile field, and you do not need to think about any of this again. Double-checked locking is the standard example of what happens when you do not ([082](082-lazy-and-dcl.md)).

## Related

* [083 · The Starting Gun: Testing Race Conditions](083-starting-gun.md), for provoking races on purpose
* [082 · Lazy Initialization: Double-Checked Locking, Holders and Lazy Constants](082-lazy-and-dcl.md), where a missing `volatile` breaks publication
* [081 · A Lock-Free Stack with Compare-and-Set](081-treiber-stack.md), built on the same edges
* [057 · final Isn't Final (Yet)](../06-hidden-corners/057-final-isnt-final.md), on what `final` does and does not promise

## Sources

* [JLS §17.4: Memory Model](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html#jls-17.4), in particular §17.4.5 (Happens-before Order)
* [JLS §17.3: Sleep and Yield](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html#jls-17.3) and [§17.7: Non-Atomic Treatment of double and long](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html#jls-17.7)
* [`java.util.concurrent` package summary: Memory Consistency Properties](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/package-summary.html#MemoryVisibility)
* Aleksey Shipilev, [Java Memory Model Pragmatics](https://shipilev.net/blog/2014/jmm-pragmatics/) (2014)
* Brian Goetz et al., [*Java Concurrency in Practice*](https://jcip.net/), chapter 3 (Sharing Objects)
