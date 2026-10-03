# 083 · The Starting Gun: Testing Race Conditions

> Your counter is broken and your test passes, because the threads never actually raced: the first one finished before the last one had started. Hold them at a gate, fire a pistol, and watch the bug show up.

**Since:** Java 8 · **Category:** [Concurrency](../README.md#concurrency) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

A classic unit test for thread safety:

```java
for (int i = 0; i < 8; i++) new Thread(() -> { for (int j = 0; j < 1000; j++) counter.value++; }).start();
```

It starts eight threads and expects the sum to be wrong. It is often *right*. Creating and starting a platform thread costs far more than a thousand increments, so each thread has frequently finished its work before the next one exists. Nothing overlapped, so nothing was lost, so the test reports a healthy counter that is about to fail in production on the day the load is higher.

A race condition needs an *overlap*. A good test manufactures one.

## The trick

Use a `CountDownLatch` as a **starting gun**. Every worker announces that it is ready and then blocks on the gate. Once all are waiting, the main thread opens the gate with one `countDown()`, and all workers run at the same instant. This is the `ready`, `start` and `done` latch trio that Brian Goetz and colleagues show as the `TestHarness` in *Java Concurrency in Practice* (section 5.5.1).

```java
CountDownLatch ready = new CountDownLatch(n);
CountDownLatch gun = new CountDownLatch(1);
CountDownLatch done = new CountDownLatch(n);
// each worker: ready.countDown(); gun.await(); task.run(); done.countDown();
ready.await();      // everyone is parked at the gate
gun.countDown();    // fire
done.await();       // everyone has finished
```

Related tools for the same job:

* **`CyclicBarrier`** is a gate that resets itself. The same threads can race again and again, and an optional *barrier action* runs once per round, which is the right place to check an invariant.
* **`Phaser`** is a barrier whose parties can join and leave, with numbered phases. Use it when the number of participants changes while the test runs.

## Full example

First the race itself. The counter is shared by eight threads and each thread adds 5000, so the expected total is 40000. The program runs 40 races per row, with and without the gate, and counts the races in which updates were lost. The counter is `volatile` on purpose, for reasons explained below.

```java run nondeterministic
import java.util.concurrent.*;

public class StartingGun {

    static final int THREADS = 8;
    static final int WORK = 5_000;
    static final int RACES = 40;

    static class Plain { int value; }
    static class Volatile { volatile int value; }

    /** Runs the task on THREADS threads. With the gate they start together, without it as soon as each exists. */
    static void race(boolean gate, Runnable task) throws InterruptedException {
        CountDownLatch ready = new CountDownLatch(THREADS);
        CountDownLatch gun = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(THREADS);
        for (int i = 0; i < THREADS; i++) {
            new Thread(() -> {
                ready.countDown();
                try {
                    if (gate) gun.await();
                    task.run();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } finally {
                    done.countDown();
                }
            }).start();
        }
        ready.await();      // every worker exists and is parked at the gate
        gun.countDown();    // fire
        done.await();
    }

    interface Experiment { int lostUpdates(boolean gate) throws InterruptedException; }

    static void report(String label, Experiment experiment) throws InterruptedException {
        for (boolean gate : new boolean[] {false, true}) {
            int racesWithLoss = 0;
            for (int i = 0; i < RACES; i++) {
                if (experiment.lostUpdates(gate) > 0) racesWithLoss++;
            }
            System.out.printf("%-13s %-8s: updates lost in %2d of %d races%n",
                    label, gate ? "gate" : "no gate", racesWithLoss, RACES);
        }
    }

    public static void main(String[] args) throws InterruptedException {
        report("plain int", gate -> {
            Plain counter = new Plain();
            race(gate, () -> { for (int i = 0; i < WORK; i++) counter.value++; });
            return THREADS * WORK - counter.value;
        });
        report("volatile int", gate -> {
            Volatile counter = new Volatile();
            race(gate, () -> { for (int i = 0; i < WORK; i++) counter.value++; });
            return THREADS * WORK - counter.value;
        });

        Volatile counter = new Volatile();
        race(true, () -> { for (int i = 0; i < WORK; i++) counter.value++; });
        System.out.println("one gated race: expected " + THREADS * WORK + ", got " + counter.value);
    }
}
```

Output (one real run, **the numbers change on every run** and with the number of cores):

```text output
plain int     no gate : updates lost in  4 of 40 races
plain int     gate    : updates lost in  0 of 40 races
volatile int  no gate : updates lost in 12 of 40 races
volatile int  gate    : updates lost in 39 of 40 races
one gated race: expected 40000, got 20305
```

The same program with the JIT compiler switched off shows how much the compiler was hiding. Save it as `StartingGun.java` and run:

```shell
java -Xint StartingGun.java
```

```text
plain int     no gate : updates lost in 39 of 40 races
plain int     gate    : updates lost in 40 of 40 races
volatile int  no gate : updates lost in 38 of 40 races
volatile int  gate    : updates lost in 40 of 40 races
one gated race: expected 40000, got 12231
```

Interpreted code is so slow that the threads overlap whether or not there is a gate. That output is a real run too, and it varies as well.

Now the cures, and the other synchronizers. Everything printed here is deterministic: the only lines come from the main thread or from a barrier or phaser callback, and those run on exactly one thread at a time, so the order never varies.

```java run
import java.lang.management.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

public class StartingGunFixed {

    static final int THREADS = 8;
    static final int WORK = 5_000;

    static int guarded;
    static synchronized void incrementGuarded() { guarded++; }

    static void gatedRace(Runnable task) throws InterruptedException {
        CountDownLatch ready = new CountDownLatch(THREADS);
        CountDownLatch gun = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(THREADS);
        for (int i = 0; i < THREADS; i++) {
            new Thread(() -> {
                ready.countDown();
                try {
                    gun.await();
                    task.run();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } finally {
                    done.countDown();
                }
            }).start();
        }
        ready.await();
        gun.countDown();
        done.await();
    }

    static void barrierRounds() throws InterruptedException {
        int parties = 4, rounds = 3;
        AtomicInteger hits = new AtomicInteger();
        // The action runs once per round, before any thread is released into the next one.
        CyclicBarrier barrier = new CyclicBarrier(parties,
                () -> System.out.println("  round done, hits so far: " + hits.get()));
        List<Thread> threads = new ArrayList<>();
        for (int t = 0; t < parties; t++) {
            Thread thread = new Thread(() -> {
                try {
                    for (int r = 0; r < rounds; r++) {
                        hits.incrementAndGet();
                        barrier.await();
                    }
                } catch (InterruptedException | BrokenBarrierException e) {
                    throw new IllegalStateException(e);
                }
            });
            threads.add(thread);
            thread.start();
        }
        for (Thread thread : threads) thread.join();
    }

    static void phases() throws InterruptedException {
        // onAdvance runs when every registered party has arrived. Returning true terminates the phaser.
        Phaser phaser = new Phaser(3) {
            @Override protected boolean onAdvance(int phase, int registeredParties) {
                System.out.println("  phase " + phase + " done, " + registeredParties + " parties registered");
                return phase == 2 || registeredParties == 0;
            }
        };
        List<Thread> threads = new ArrayList<>();
        for (int id = 1; id <= 3; id++) {
            int worker = id;
            Thread thread = new Thread(() -> {
                phaser.arriveAndAwaitAdvance();                     // end of phase 0
                if (worker == 3) {
                    phaser.arriveAndDeregister();                   // worker 3 leaves during phase 1
                    return;
                }
                phaser.arriveAndAwaitAdvance();                     // end of phase 1
                phaser.arriveAndAwaitAdvance();                     // end of phase 2
            });
            threads.add(thread);
            thread.start();
        }
        for (Thread thread : threads) thread.join();
        System.out.println("  terminated: " + phaser.isTerminated());
    }

    /** Each thread takes its own lock first, and only then waits for the other to do the same. */
    static Thread deadlockProne(String name, Object first, Object second, CountDownLatch bothHoldOne) {
        Thread thread = new Thread(() -> {
            synchronized (first) {
                bothHoldOne.countDown();
                try {
                    bothHoldOne.await();
                } catch (InterruptedException e) {
                    return;
                }
                synchronized (second) {
                    System.out.println("never printed");
                }
            }
        }, name);
        thread.setDaemon(true);     // so the JVM can exit while they are stuck
        thread.start();
        return thread;
    }

    static void deadlockDetection() throws InterruptedException {
        Object lockA = new Object(), lockB = new Object();
        CountDownLatch bothHoldOne = new CountDownLatch(2);
        deadlockProne("alpha", lockA, lockB, bothHoldOne);
        deadlockProne("beta", lockB, lockA, bothHoldOne);

        ThreadMXBean threads = ManagementFactory.getThreadMXBean();
        long[] ids = null;
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (ids == null && System.nanoTime() < deadline) {
            Thread.sleep(10);
            ids = threads.findDeadlockedThreads();
        }
        if (ids == null) {
            System.out.println("  no deadlock found");
            return;
        }
        ThreadInfo[] infos = threads.getThreadInfo(ids);
        Arrays.sort(infos, Comparator.comparing(ThreadInfo::getThreadName));
        for (ThreadInfo info : infos) {
            System.out.println("  " + info.getThreadName() + " is " + info.getThreadState()
                    + " on a " + info.getLockInfo().getClassName()
                    + " owned by " + info.getLockOwnerName());
        }
    }

    public static void main(String[] args) throws InterruptedException {
        AtomicInteger atomic = new AtomicInteger();
        LongAdder adder = new LongAdder();
        gatedRace(() -> {
            for (int i = 0; i < WORK; i++) {
                atomic.incrementAndGet();
                adder.increment();
                incrementGuarded();
            }
        });
        System.out.println("expected      " + THREADS * WORK);
        System.out.println("AtomicInteger " + atomic.get());
        System.out.println("LongAdder     " + adder.sum());
        System.out.println("synchronized  " + guarded);

        System.out.println("CyclicBarrier:");
        barrierRounds();
        System.out.println("Phaser:");
        phases();
        System.out.println("Deadlock:");
        deadlockDetection();
    }
}
```

Output:

```text output
expected      40000
AtomicInteger 40000
LongAdder     40000
synchronized  40000
CyclicBarrier:
  round done, hits so far: 4
  round done, hits so far: 8
  round done, hits so far: 12
Phaser:
  phase 0 done, 3 parties registered
  phase 1 done, 2 parties registered
  phase 2 done, 2 parties registered
  terminated: true
Deadlock:
  alpha is BLOCKED on a java.lang.Object owned by beta
  beta is BLOCKED on a java.lang.Object owned by alpha
```

## How it works

* **The gate removes the head start.** Without it, thread 1 runs while thread 2 is still being created, so the window in which two threads touch the counter at the same moment is tiny. With it, `ready.await()` guarantees that all eight threads exist, and one `countDown()` wakes them all at almost the same moment. That is the difference between the `no gate` and `gate` rows for the volatile counter in the first output.
* **`volatile` does not make `++` atomic.** `counter.value++` is three steps: read, add one, write. Volatile makes each step visible to the other threads, but another thread can still slip in between the read and the write, and then one of the two increments is overwritten. That is a lost update. The volatile row is the dependable demo of it. It is also the most common wrong fix for a counter that loses updates.
* **Why the plain `int` rows look odd.** In the sample the plain counter lost updates in some ungated races and in *none* of the gated ones, as if the gate had made the code safer. It is the JIT. The plain rows run first, so the first row runs on cold code, which is slow enough for the threads to overlap. By the second row the loop has been compiled, and a compiled loop over a plain field is allowed to keep the counter in a register and write it back once, so the window for a lost update shrinks from 5000 read-modify-write cycles per thread to one. With the JIT switched off, every plain row loses updates (see the `-Xint` run above). A plain counter that passes a stress test after a warm-up has proven nothing, which is why the demo counter is `volatile`. The same compiler freedom is what makes the loop in [084](084-visibility-puzzler.md) spin forever.
* **`AtomicInteger` and `LongAdder` are exact.** `incrementAndGet` is one hardware compare-and-set loop. `LongAdder` keeps several cells and sums them in `sum()`, so contended increments rarely collide, at the price of `sum()` not being an atomic snapshot while writers are active. Both end at exactly `expected` in the second output. `synchronized` does too, and is the simplest answer when the critical section is bigger than one counter.
* **`CyclicBarrier` is a starting gun you can reuse.** Every thread calls `await()` and blocks until all four have arrived. The barrier then runs its action once, on the last thread to arrive, and only then releases everybody. That is why the action sees `4`, `8` and `12` hits: in each round, every increment happened before the action, and no increment of the next round before it. Put your invariant check there.
* **`Phaser` handles the changing crowd.** It has numbered phases and a party count you can change with `register()` and `arriveAndDeregister()`. Worker 3 leaves in phase 1, so phases 1 and 2 complete with two parties. Returning `true` from `onAdvance` terminates the phaser, and every later `arriveAndAwaitAdvance()` returns immediately with a negative number.
* **Deadlock detection.** `ThreadMXBean.findDeadlockedThreads()` finds cycles of threads that wait for monitors or `java.util.concurrent.locks` ownable synchronizers. The latch inside the `synchronized` block makes the deadlock certain instead of likely: each thread holds its first lock before either asks for the second. `getLockOwnerName()` shows who each blocked thread waits for. `jstack` and `jcmd <pid> Thread.print` print the same cycle as "Found one Java-level deadlock".

## Gotchas

* **A stress test proves the presence of a bug, never its absence.** Zero lost updates in 40 races means "not found yet". Run enough rounds to make a failure likely, and then run in CI on different hardware too.
* **You need real cores.** On a single core, or a heavily loaded CI machine, the threads time-slice instead of overlapping, and the same test finds far fewer races.
* **Do not put the timing in the test.** `Thread.sleep(100)` to "give the others a chance" is a flaky test that is slow as well. Latches and barriers say exactly what you are waiting for.
* **Guard every `await` with a timeout in real tests.** `done.await(10, TimeUnit.SECONDS)` turns a deadlocked implementation into a failing test instead of a hung build.
* **The deadlocked threads are daemons for a reason.** Threads stuck on a monitor cannot be interrupted or stopped, so the demo marks them as daemon threads and the JVM can still exit. A test that provokes a deadlock needs the same trick, or one bad test hangs the whole suite.
* **Interleavings you cannot reach by luck need a tool.** Real testing of lock-free code and memory ordering belongs in [jcstress](https://github.com/openjdk/jcstress), the OpenJDK harness built for exactly that job.

## When to use it (and when not to)

Use a starting gun when you write a regression test for a race you already suspect, when you demonstrate a bug to a colleague, or when a stress test only fails "sometimes" and you want it to fail reliably. It costs 15 lines and no libraries.

Do not mistake it for verification. A passing gated test is evidence, not proof, and it says nothing about memory-model effects that your CPU's ordering happens to hide. For lock-free structures use jcstress. For design-level confidence reduce the shared mutable state ([079](079-scoped-values.md) or immutable data) rather than testing harder.

## Related

* [084 · The Loop That Never Ends: volatile and the Memory Model](084-visibility-puzzler.md), where the JIT's freedom decides the outcome
* [081 · A Lock-Free Stack with Compare-and-Set](081-treiber-stack.md), a structure worth stress testing with a gate
* [077 · Virtual Threads: A Million Threads and the Pinning Trap](077-virtual-threads.md), for why platform threads are the right choice for a race demo
* [063 · ConcurrentModificationException and the One Case It Doesn't Fire](../07-puzzlers/063-concurrent-modification.md), a race-like failure that is deterministic

## Sources

* Brian Goetz et al., [*Java Concurrency in Practice*](https://jcip.net/) (2006), section 5.5.1, Latches (the `TestHarness`)
* [`CountDownLatch`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/CountDownLatch.html), [`CyclicBarrier`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/CyclicBarrier.html) and [`Phaser`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/Phaser.html) Javadoc (Java 25)
* [`ThreadMXBean.findDeadlockedThreads`](https://docs.oracle.com/en/java/javase/25/docs/api/java.management/java/lang/management/ThreadMXBean.html#findDeadlockedThreads()) Javadoc (Java 25)
* [OpenJDK jcstress](https://github.com/openjdk/jcstress), the Java Concurrency Stress tests
