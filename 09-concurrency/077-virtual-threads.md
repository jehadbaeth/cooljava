# 077 · Virtual Threads: A Million Threads and the Pinning Trap

> A thread that costs about as much as an object, so you can block in it without guilt. Just don't pool it, and don't fall asleep inside a static initializer.

**Since:** Java 21 · **Category:** [Concurrency](../README.md#concurrency) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

A platform thread is a wrapper around an operating system thread: about a megabyte of reserved stack, a kernel scheduling entity, and a creation cost you notice. So we pooled them, and then we discovered the arithmetic of a blocking server. With 200 pooled threads and requests that each wait 50 ms on a database, you serve at most 4,000 requests per second, no matter how idle the CPU is.

The industry answer was asynchronous code: callbacks, `CompletableFuture` chains, reactive streams. It scales, but you lose readable stack traces, `try`/`catch`, debuggers that step through your logic, and the plain sequential style the language was designed for.

## The trick

Make threads cheap instead of making code asynchronous. A **virtual thread** is a `java.lang.Thread` that the JDK schedules onto a small pool of platform *carrier* threads. When it blocks (sleep, socket read, `BlockingQueue.take`, lock wait), the JDK copies its stack frames to the heap, *unmounts* it, and lets the carrier run something else. When the operation completes, it is mounted again, possibly on a different carrier.

The idiomatic shape is one new virtual thread per task, closed by try-with-resources:

```java
try (ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor()) {
    for (Request request : requests) {
        executor.submit(() -> handle(request));   // plain blocking code inside
    }
}   // close() waits until every task has finished
```

`ExecutorService` has been `AutoCloseable` since Java 19, and `close()` waits for all submitted tasks, so the block above is also a correctness boundary: nothing escapes it still running.

## Full example

First the headline number. The same blocking workload runs on a classic pool of 200 platform threads and on virtual threads, and then a million virtual threads all sleep at once. The timings are real but vary from run to run and machine to machine; the task counts do not.

```java run nondeterministic
import java.time.Duration;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

public class MillionSleepers {

    static void run(String label, ExecutorService executor, int tasks, Duration nap) {
        var done = new AtomicInteger();
        long start = System.nanoTime();
        try (executor) {
            for (int i = 0; i < tasks; i++) {
                executor.submit(() -> {
                    Thread.sleep(nap);
                    return done.incrementAndGet();
                });
            }
        }   // close() waits for every task
        long millis = (System.nanoTime() - start) / 1_000_000;
        System.out.printf("  %-22s %,9d tasks done in %,6d ms%n", label, done.get(), millis);
    }

    public static void main(String[] args) {
        System.out.println("10,000 tasks, each sleeping 50 ms:");
        run("200 platform threads", Executors.newFixedThreadPool(200), 10_000, Duration.ofMillis(50));
        run("virtual threads", Executors.newVirtualThreadPerTaskExecutor(), 10_000, Duration.ofMillis(50));

        System.out.println("1,000,000 tasks, each sleeping 1 s:");
        run("virtual threads", Executors.newVirtualThreadPerTaskExecutor(), 1_000_000, Duration.ofSeconds(1));
    }
}
```

Output (one sample run):

```text output
10,000 tasks, each sleeping 50 ms:
  200 platform threads      10,000 tasks done in  2,833 ms
  virtual threads           10,000 tasks done in     82 ms
1,000,000 tasks, each sleeping 1 s:
  virtual threads        1,000,000 tasks done in  1,433 ms
```

Now the deterministic tour: what a virtual thread looks like from the inside, how to limit concurrency without a pool, and why a `ThreadLocal` cache stops being a cache.

```java run
import java.time.Duration;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

public class VirtualThreadsTour {

    // A classic per-thread cache: one expensive buffer per thread, reused across tasks.
    static final AtomicInteger buffersCreated = new AtomicInteger();
    static final ThreadLocal<StringBuilder> BUFFER = ThreadLocal.withInitial(() -> {
        buffersCreated.incrementAndGet();
        return new StringBuilder(64 * 1024);
    });

    static int buffersNeededFor(ExecutorService executor, int tasks) {
        buffersCreated.set(0);
        try (executor) {
            for (int i = 0; i < tasks; i++) {
                executor.submit(() -> BUFFER.get().setLength(0));
            }
        }
        return buffersCreated.get();
    }

    public static void main(String[] args) throws Exception {
        // 1. A virtual thread is a Thread. It is always a daemon thread.
        Thread hello = Thread.ofVirtual().name("hello-vt").start(() -> {
            Thread me = Thread.currentThread();
            System.out.println(me.getName() + ": virtual=" + me.isVirtual() + ", daemon=" + me.isDaemon());
        });
        hello.join();

        // 2. Limit concurrency with a Semaphore, not with a pool size.
        var permits = new Semaphore(10);
        var inFlight = new AtomicInteger();
        var peak = new AtomicInteger();
        var calls = new AtomicInteger();
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            for (int i = 0; i < 500; i++) {
                executor.submit(() -> {
                    permits.acquire();
                    try {
                        peak.accumulateAndGet(inFlight.incrementAndGet(), Math::max);
                        Thread.sleep(Duration.ofMillis(5));   // the "fragile downstream service"
                        calls.incrementAndGet();
                    } finally {
                        inFlight.decrementAndGet();
                        permits.release();
                    }
                    return null;
                });
            }
        }
        System.out.println("downstream calls: " + calls.get() + ", peak in flight <= 10: " + (peak.get() <= 10));

        // 3. ThreadLocal caches assume threads are reused. Virtual threads never are.
        System.out.println("buffers for 10,000 tasks on 8 pooled threads: "
                + buffersNeededFor(Executors.newFixedThreadPool(8), 10_000));
        System.out.println("buffers for 10,000 tasks on virtual threads:  "
                + buffersNeededFor(Executors.newVirtualThreadPerTaskExecutor(), 10_000));
    }
}
```

Output:

```text output
hello-vt: virtual=true, daemon=true
downstream calls: 500, peak in flight <= 10: true
buffers for 10,000 tasks on 8 pooled threads: 8
buffers for 10,000 tasks on virtual threads:  10000
```

## How it works

* **Continuations under the hood.** A virtual thread is a `Thread` object plus a continuation. Blocking calls in the JDK (sleep, `java.net` sockets, `java.util.concurrent` locks and queues, and since Java 24 also `synchronized` and `Object.wait`) check whether they run on a virtual thread. If so, they park the continuation, which copies the live stack frames to the heap and frees the carrier. That is why a million sleepers fit into one JVM: a parked virtual thread is a few hundred bytes to a few kilobytes of heap, not a megabyte of reserved stack.
* **The scheduler** is a `ForkJoinPool` in FIFO mode with one carrier per core by default (`jdk.virtualThreadScheduler.parallelism`). Virtual threads are not time-sliced: one that computes without blocking keeps its carrier until it is done. They help with *waiting*, not with *computing*.
* **Always daemon, no priorities.** `isDaemon()` is always `true` and `setPriority` is ignored. A JVM whose only live threads are virtual simply exits.
* **Semaphores, not pools, limit concurrency.** The thing you want to protect is the downstream resource (ten database connections, a rate-limited API), so guard *that* with a `Semaphore`. The 490 tasks waiting for a permit are parked virtual threads and cost almost nothing.
* **`ThreadLocal` caching breaks down.** The tour shows it: 8 pooled threads need 8 buffers, while 10,000 virtual threads need 10,000, because each virtual thread runs exactly one task and dies. Thread locals still *work* on virtual threads; they just stop being a cache and start being a memory multiplier. For request context, [scoped values](079-scoped-values.md) are the better fit.

### The pinning trap

A virtual thread is **pinned** when it cannot unmount while blocking, so it holds its carrier hostage. In Java 21 to 23 the famous case was blocking inside `synchronized`: a few threads sleeping in a `synchronized` block could freeze an entire server, because there are only as many carriers as cores. JEP 491 fixed that in Java 24 by letting the JVM track monitors per virtual thread instead of per carrier.

Pinning is not gone, though. JEP 491 lists the remaining cases: a native frame on the stack (JNI, or a Foreign Function call that calls back into Java and blocks), and class loading or initialization. This demo runs with a single carrier, so pinning becomes visible as ordering. Thread A blocks first, then thread B asks for the carrier. The latch makes sure B starts only after A is inside its critical section:

```java run args="-Djdk.virtualThreadScheduler.parallelism=1 -Djdk.virtualThreadScheduler.maxPoolSize=1"
import java.util.*;
import java.util.concurrent.CountDownLatch;

public class PinningDemo {

    static final List<String> events = Collections.synchronizedList(new ArrayList<>());
    static final Object LOCK = new Object();
    static volatile CountDownLatch blockerInside;

    static void nap() {
        blockerInside.countDown();
        try {
            Thread.sleep(300);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    static class SlowConfig {
        static final String VALUE;
        static {
            events.add("A: sleeping inside a static initializer");
            nap();
            VALUE = "config";
        }
    }

    static void scenario(String title, Runnable blocker) throws InterruptedException {
        events.clear();
        blockerInside = new CountDownLatch(1);
        Thread a = Thread.ofVirtual().start(() -> {
            blocker.run();
            events.add("A: done");
        });
        blockerInside.await();   // A is now about to block in its critical section
        Thread b = Thread.ofVirtual().start(() -> events.add("B: got the carrier"));
        a.join();
        b.join();
        System.out.println(title);
        events.forEach(e -> System.out.println("  " + e));
    }

    public static void main(String[] args) throws InterruptedException {
        scenario("synchronized + sleep:", () -> {
            synchronized (LOCK) {
                events.add("A: sleeping inside synchronized");
                nap();
            }
        });
        scenario("static initializer + sleep:", () -> events.add("A: read " + SlowConfig.VALUE));
    }
}
```

Output:

```text output
synchronized + sleep:
  A: sleeping inside synchronized
  B: got the carrier
  A: done
static initializer + sleep:
  A: sleeping inside a static initializer
  A: read config
  A: done
  B: got the carrier
```

In the first scenario B runs while A sleeps, even though A holds a monitor: on Java 24 and later, `synchronized` no longer pins. In the second, B only gets the carrier after A is completely done, because A sleeps with the JVM's class initialization call on its stack and cannot unmount. The demo compiles on Java 21, but the first scenario needs a Java 24 or newer runtime: on 21 to 23, where `synchronized` still pinned (JEP 491 describes it), both scenarios would end with B last.

The old `-Djdk.tracePinnedThreads` flag was removed in Java 24. The supported way to find pinning is the JFR event `jdk.VirtualThreadPinned`, which now also tells you *why*:

```shell
java -Djdk.virtualThreadScheduler.parallelism=1 -Djdk.virtualThreadScheduler.maxPoolSize=1 \
     -XX:StartFlightRecording:filename=pin.jfr PinningDemo.java > /dev/null
jfr print --events jdk.VirtualThreadPinned --stack-depth 3 pin.jfr
```

```text
jdk.VirtualThreadPinned {
  startTime = 00:22:40.465 (2026-10-03)
  duration = 308 ms
  blockingOperation = "LockSupport.park"
  pinnedReason = "VM call to PinningDemo$SlowConfig.<clinit> on stack"
  carrierThread = "ForkJoinPool-1-worker-1" (javaThreadId = 36)
  eventThread = "" (javaThreadId = 39, virtual)
  stackTrace = [
    java.lang.VirtualThread.parkOnCarrierThread(boolean, long) line: 833
    java.lang.VirtualThread.parkNanos(long) line: 801
    java.lang.VirtualThread.sleepNanos(long) line: 983
  ]
}
```

Only the static initializer shows up. The `synchronized` sleep produced no event at all, and the `pinnedReason` names the exact culprit. The default JFR threshold for this event is 20 ms, so short pins stay quiet unless you lower it.

## Gotchas

* **Never pool virtual threads.** `Executors.newFixedThreadPool(200, Thread.ofVirtual().factory())` compiles and runs, and throws away the whole point: you are back to 200 concurrent tasks, plus thread locals that leak between tasks. Create one per task and let them die.
* **CPU-bound work gains nothing.** Ten thousand virtual threads crunching numbers still share one carrier per core. Use parallel streams or a `ForkJoinPool` for that.
* **Heavy `ThreadLocal` users multiply memory.** Libraries that cache big objects per thread (some JSON mappers, older date formatters, connection wrappers) allocate one per virtual thread. Check before migrating a million-request server.
* **Remaining pinning.** Blocking inside a static initializer, while loading a class, or under a native frame still pins. `synchronized` pinning only disappears on Java 24+; if you are stuck on 21, prefer `ReentrantLock` around blocking calls.
* **Unbounded fan-out moves the bottleneck.** Virtual threads make it trivial to open 100,000 sockets at once. The remote service, the file descriptor limit and the database pool will not be as relaxed about it. Hence the semaphore.

## When to use it (and when not to)

Use virtual threads for anything that spends most of its life waiting: HTTP handlers, JDBC calls, message consumers, fan-out to several services. On Java 21 or later, a thread-per-request server on virtual threads is usually simpler than its reactive equivalent and scales to similar concurrency; on Java 24 or later most of the pinning caveats are gone too. Spring Boot, Quarkus and Jetty have a switch for it, and Helidon 4 is built on them.

Don't bother for CPU-bound batch jobs, and be careful with code that leans on `ThreadLocal` caches or long native calls. If you need the subtasks of one request to fail and cancel together, put [structured concurrency](078-structured-concurrency.md) on top.

## Related

* [078 · Structured Concurrency (Preview)](078-structured-concurrency.md), for treating a group of virtual threads as one unit of work
* [079 · Scoped Values: ThreadLocal's Better Sibling](079-scoped-values.md), the context-passing tool that fits virtual threads
* [080 · CompletableFuture Cookbook](080-completablefuture-cookbook.md), the asynchronous style virtual threads often replace
* [024 · Token Bucket Rate Limiter](../03-build-it-yourself/024-token-bucket.md), when a semaphore is not enough and you need a rate

## Sources

* [JEP 444: Virtual Threads](https://openjdk.org/jeps/444)
* [JEP 491: Synchronize Virtual Threads without Pinning](https://openjdk.org/jeps/491), including the list of remaining pinning cases
* [Oracle Java 25 guide: Virtual Threads](https://docs.oracle.com/en/java/javase/25/core/virtual-threads.html)
* [`Thread.Builder.OfVirtual` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Thread.Builder.OfVirtual.html)
