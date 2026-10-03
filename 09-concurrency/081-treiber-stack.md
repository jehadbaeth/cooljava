# 081 · A Lock-Free Stack with Compare-and-Set

> Read the top, build the new top, swap only if nobody beat you to it, otherwise try again. Ten lines, no locks, and a famous bug that Java's garbage collector quietly prevents for you.

**Since:** Java 16 · **Category:** [Concurrency](../README.md#concurrency) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

A `synchronized` stack is correct and simple, but every `push` and `pop` takes the same lock. Under contention threads queue up, get parked by the OS and woken again, and a thread that is descheduled while holding the lock stalls everybody else. Sometimes you want a structure where *some* thread always makes progress, no matter what the scheduler does to the others.

## The trick

R. Kent Treiber's 1986 stack needs only one atomic primitive: **compare-and-set** (CAS). `top.compareAndSet(expected, update)` replaces `top` only if it still holds `expected`, atomically, and tells you whether it worked:

```java
void push(T value) {
    Node<T> oldTop;
    do {
        oldTop = top.get();                                          // 1. read
    } while (!top.compareAndSet(oldTop, new Node<>(value, oldTop))); // 2. swap if unchanged, else retry
}
```

If another thread changed `top` between the read and the CAS, the CAS fails and the loop retries with a fresh snapshot. Nobody ever blocks. A failed CAS means *another* thread's CAS succeeded, so the system as a whole always makes progress: that is what **lock-free** means.

Nodes are immutable records. Once a node is published on the stack it never changes, which is what makes the snapshot safe to reason about.

## Full example

Four threads start together behind a latch, each pushes 100,000 unique numbers and pops after every second push. Afterwards the stack is drained and the books must balance exactly: every number pushed is popped exactly once, nothing is lost, nothing is duplicated. The test runs against both the `AtomicReference` version and a `VarHandle` version. The ABA part at the end is a single-threaded replay of a bad interleaving, so its output is deterministic too.

```java run
import java.lang.invoke.MethodHandles;
import java.lang.invoke.VarHandle;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

public class TreiberDemo {

    interface Stack<T> {
        void push(T value);
        T pop();   // null when empty
    }

    record Node<T>(T value, Node<T> next) {}

    static final class TreiberStack<T> implements Stack<T> {
        private final AtomicReference<Node<T>> top = new AtomicReference<>();

        public void push(T value) {
            Node<T> oldTop;
            do {
                oldTop = top.get();
            } while (!top.compareAndSet(oldTop, new Node<>(value, oldTop)));
        }

        public T pop() {
            Node<T> oldTop;
            do {
                oldTop = top.get();
                if (oldTop == null) return null;
            } while (!top.compareAndSet(oldTop, oldTop.next()));
            return oldTop.value();
        }
    }

    // Same algorithm on a plain volatile field: no extra AtomicReference object per stack.
    static final class VarHandleStack<T> implements Stack<T> {
        private static final VarHandle TOP;
        static {
            try {
                TOP = MethodHandles.lookup().findVarHandle(VarHandleStack.class, "top", Node.class);
            } catch (ReflectiveOperationException e) {
                throw new ExceptionInInitializerError(e);
            }
        }
        private volatile Node<T> top;

        public void push(T value) {
            Node<T> oldTop;
            do {
                oldTop = top;
            } while (!TOP.compareAndSet(this, oldTop, new Node<>(value, oldTop)));
        }

        public T pop() {
            Node<T> oldTop;
            do {
                oldTop = top;
                if (oldTop == null) return null;
            } while (!TOP.compareAndSet(this, oldTop, oldTop.next()));
            return oldTop.value();
        }
    }

    static void hammer(String name, Stack<Integer> stack, int threads, int perThread) throws Exception {
        var startingGun = new CountDownLatch(1);
        List<Future<List<Integer>>> results = new ArrayList<>();
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        for (int t = 0; t < threads; t++) {
            int base = t * perThread;
            results.add(pool.submit(() -> {
                var popped = new ArrayList<Integer>();
                startingGun.await();
                for (int i = 0; i < perThread; i++) {
                    stack.push(base + i);
                    if (i % 2 == 1) popped.add(stack.pop());
                }
                return popped;
            }));
        }
        startingGun.countDown();   // everybody starts at once
        pool.shutdown();           // Future.get() below waits for the results
        var seen = new BitSet();
        int poppedDuringRun = 0, duplicates = 0, nulls = 0;
        for (Future<List<Integer>> result : results) {
            for (Integer value : result.get()) {
                poppedDuringRun++;
                if (value == null) nulls++;
                else if (seen.get(value)) duplicates++;
                else seen.set(value);
            }
        }
        int drained = 0;
        for (Integer value; (value = stack.pop()) != null; drained++) {
            if (seen.get(value)) duplicates++;
            else seen.set(value);
        }
        int pushed = threads * perThread;
        System.out.printf("%-15s pushed %,d | popped %,d + drained %,d | duplicates %d | nulls %d | missing %d%n",
                name, pushed, poppedDuringRun, drained, duplicates, nulls, pushed - seen.cardinality());
    }

    // ABA, replayed step by step with a node pool that recycles nodes, as C code with a free list would.
    static final class Cell {
        final String name;
        Cell next;
        Cell(String name, Cell next) { this.name = name; this.next = next; }
    }

    static String contents(Cell top) {
        var names = new StringJoiner(", ", "[", "]");
        for (Cell c = top; c != null; c = c.next) names.add(c.name);
        return names.toString();
    }

    static void aba() {
        Cell c = new Cell("C", null), b = new Cell("B", c), a = new Cell("A", b);
        var plainTop = new AtomicReference<>(a);
        var stampedTop = new AtomicStampedReference<>(a, 0);

        // Thread 1 begins pop(): it reads top = A and A.next = B, then is descheduled.
        Cell seenTop = plainTop.get();
        Cell seenNext = seenTop.next;
        int[] stamp = new int[1];
        stampedTop.get(stamp);
        int seenStamp = stamp[0];

        // Thread 2 pops A, pops B, then pushes the recycled node A back on top of C.
        a.next = c;
        plainTop.set(a);
        stampedTop.set(a, seenStamp + 3);   // three operations, three stamp bumps

        // Thread 1 wakes up and finishes its pop with the values it read earlier.
        boolean plainOk = plainTop.compareAndSet(seenTop, seenNext);
        boolean stampedOk = stampedTop.compareAndSet(seenTop, seenNext, seenStamp, seenStamp + 1);
        System.out.println("ABA with AtomicReference:        CAS " + plainOk + ", stack " + contents(plainTop.get())
                + " (B was already popped)");
        System.out.println("ABA with AtomicStampedReference: CAS " + stampedOk + ", stack " + contents(stampedTop.getReference()));
    }

    public static void main(String[] args) throws Exception {
        hammer("AtomicReference", new TreiberStack<>(), 4, 100_000);
        hammer("VarHandle", new VarHandleStack<>(), 4, 100_000);
        aba();
    }
}
```

Output:

```text output
AtomicReference pushed 400,000 | popped 200,000 + drained 200,000 | duplicates 0 | nulls 0 | missing 0
VarHandle       pushed 400,000 | popped 200,000 + drained 200,000 | duplicates 0 | nulls 0 | missing 0
ABA with AtomicReference:        CAS true, stack [B, C] (B was already popped)
ABA with AtomicStampedReference: CAS false, stack [A, C]
```

## How it works

* **The CAS is the linearization point.** A concurrent object is *linearizable* if every operation appears to take effect at a single instant between its call and its return. For this stack that instant is the successful `compareAndSet`. Everything before it is private preparation (reading `top`, allocating a node), and a failed CAS has no visible effect at all. So the stack behaves as if pushes and pops happened one at a time in *some* order, which is exactly what the zero duplicates and zero missing values check.
* **No pop ever saw an empty stack.** Every thread has always pushed more than it has popped when it calls `pop`, so in any linear order of the operations the stack is non-empty at each pop. The `nulls 0` column confirms that nobody observed a state that never existed.
* **Immutable nodes keep it simple.** `Node` is a record. `push` builds a new node pointing at the snapshot; `pop` swings `top` to `oldTop.next()`, which can never change behind its back. A retry allocates another node, which is cheap for a modern allocator.
* **`VarHandle` removes an indirection.** `AtomicReference` is a separate object holding a volatile field. `VarHandle.compareAndSet(this, expected, update)` (Java 9) performs the same CAS directly on the stack's own `volatile` field. That is how `java.util.concurrent` itself is written today.

### ABA, and why Java mostly does not care

The danger in CAS algorithms is the **ABA problem**: thread 1 reads `top == A`, gets descheduled, other threads pop `A`, pop `B` and push `A` again. When thread 1 resumes, `top == A` still holds, so its CAS succeeds and installs its stale `next`, `B`, a node that was already popped. The replay above shows the result: the plain CAS returns `true` and `B` rises from the dead.

That only happens if the *same node object* comes back. In C, it does: `free(A)` followed by `malloc` often returns the same address. In Java, thread 1 still holds a reference to `A`, so the garbage collector cannot reclaim it, and every `push` allocates a fresh node. A recycled `A` is impossible unless you build your own node pool, which is precisely what the replay does with its mutable `Cell`s. Treiber's stack as written above is ABA-safe in Java for free.

If you do pool nodes, or compare plain values instead of fresh objects, pair the reference with a version number: `AtomicStampedReference` compares *both* and bumps the stamp on every change, so the stale CAS fails.

## Gotchas

* **Lock-free is not wait-free.** A single unlucky thread can, in theory, lose the CAS race forever while others succeed. Lock-free only guarantees that *someone* makes progress.
* **Contention still hurts.** Every thread hammers one memory location, so the cache line bounces between cores. Under heavy contention a lock-free stack can be *slower* than a lock, which at least parks the losers. Measure with JMH, never with the toy above.
* **Never mutate a published node.** Setting `next` after the CAS, or reusing nodes to save allocations, reopens every hazard that immutability closed.
* **`AtomicStampedReference` allocates a pair object per update**, and stamps can wrap around after 2³² changes. It is a correctness tool, not a speed trick.
* **The stack only stores references.** Pushing a mutable object and changing it afterwards is your race, not the stack's.

## When to use it (and when not to)

Build it once to understand CAS loops, linearizability and ABA; the same retry pattern appears in counters, lazy initialization and every class in `java.util.concurrent.atomic`. In production, use `ConcurrentLinkedDeque` (lock-free, by Doug Lea and Martin Buchholz) for a concurrent stack, or `ArrayDeque` behind a lock when contention is modest. Write your own lock-free structure only when profiling says the lock is the bottleneck, and then test it with tools built for the job, such as [jcstress](https://github.com/openjdk/jcstress).

The algorithm itself works since Java 5 (`AtomicReference`); this example uses records, hence Java 16.

## Related

* [083 · The Starting Gun: Testing Race Conditions](083-starting-gun.md), the latch technique used in the test above
* [084 · The Loop That Never Ends: volatile and the Memory Model](084-visibility-puzzler.md), the visibility rules CAS relies on
* [082 · Lazy Initialization: Double-Checked Locking, Holders and Lazy Constants](082-lazy-and-dcl.md), another place where atomics and `volatile` meet
* [086 · MethodHandles and LambdaMetafactory: Reflection at Full Speed](../10-jvm-performance/086-methodhandles-lambdametafactory.md), the `java.lang.invoke` family `VarHandle` belongs to

## Sources

* [Treiber stack](https://en.wikipedia.org/wiki/Treiber_stack), Wikipedia, with the reference to R. K. Treiber, *Systems Programming: Coping with Parallelism*, IBM research report (1986)
* Brian Goetz et al., *Java Concurrency in Practice* (2006), section 15.4, "Nonblocking algorithms"
* [`AtomicStampedReference` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/atomic/AtomicStampedReference.html)
* [`VarHandle` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/VarHandle.html) and [JEP 193: Variable Handles](https://openjdk.org/jeps/193)
* Maurice Herlihy and Jeannette Wing, [Linearizability: A Correctness Condition for Concurrent Objects](https://cs.brown.edu/~mph/HerlihyW90/p463-herlihy.pdf) (1990)
