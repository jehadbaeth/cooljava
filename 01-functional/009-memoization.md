# 009 · Memoization Done Right

> Caching a pure function takes one line. Caching a recursive one with the same line works for fib(13) and explodes at fib(14), which is the worst kind of bug: the kind your unit tests are too small to see.

**Since:** Java 16 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Some functions are expensive and pure: the same input always gives the same output. Computing them twice is waste. The textbook victim is Fibonacci, where the naive recursion recomputes the same subproblems an exponential number of times. The textbook cure is **memoization**: remember each result in a map, keyed by the argument.

Java hands you a map method that looks tailor made for it, `computeIfAbsent`: "if there is no value for this key, compute one, store it and return it". Wrap it in a function and you are done. For a non-recursive function you really are done. For a recursive one, you have just written a program that depends on the internal layout of a hash table.

## The trick

A generic memoizer is five lines:

```java
static <K, V> Function<K, V> memoize(Function<K, V> f) {
    Map<K, V> cache = new ConcurrentHashMap<>();
    return key -> cache.computeIfAbsent(key, f);
}
```

The recursive version is where people reach for the same one-liner and get burned:

```java
static long fibTrap(Map<Integer, Long> cache, int n) {
    if (n < 2) return n;
    return cache.computeIfAbsent(n, k -> fibTrap(cache, k - 1) + fibTrap(cache, k - 2));
}
```

The mapping function calls `computeIfAbsent` on the *same map* while the outer call is still in progress. The Javadoc forbids exactly that ("must not attempt to update any other mappings of this map"), and the maps enforce it on a best-effort basis, so you get an exception sometimes and a silent success other times.

There are two honest fixes, and neither needs a lock:

1. **Look up, compute outside the map, then store.** Three plain steps (`get`, compute, `put`), so the recursion happens while the map is not in the middle of anything.
2. **A memoizer that passes itself.** The function you memoize receives the memoized version of itself as an argument, so the recursion goes through the cache without the author writing any cache code. This is the same self-reference move as the [Y combinator](../06-hidden-corners/053-y-combinator.md), but with an anonymous class instead of lambda gymnastics.

## Full example

The first program shows the trap with the real exceptions, both fixes, and what happens when eight threads ask for the same key. The pattern works on any Java version; this example uses records.

```java run
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.*;

public class MemoDemo {

    /** The easy case: a pure function of one argument, no recursion. */
    static <K, V> Function<K, V> memoize(Function<K, V> f) {
        Map<K, V> cache = new ConcurrentHashMap<>();
        return key -> cache.computeIfAbsent(key, f);
    }

    /** The trap: the mapping function calls back into the map it is computing for. */
    static long fibTrap(Map<Integer, Long> cache, int n) {
        if (n < 2) return n;
        return cache.computeIfAbsent(n, k -> fibTrap(cache, k - 1) + fibTrap(cache, k - 2));
    }

    /** Fix 1: get, compute outside of the map, put. */
    static long fibGetPut(Map<Integer, Long> cache, int n) {
        if (n < 2) return n;
        Long hit = cache.get(n);
        if (hit != null) return hit;
        long value = fibGetPut(cache, n - 1) + fibGetPut(cache, n - 2);
        cache.put(n, value);
        return value;
    }

    /** Fix 2: the body receives the memoized function itself and recurses through it. */
    static <K, V> Function<K, V> memoizeRecursive(BiFunction<Function<K, V>, K, V> body) {
        Map<K, V> cache = new ConcurrentHashMap<>();
        return new Function<>() {
            @Override public V apply(K key) {
                V hit = cache.get(key);
                if (hit != null) return hit;
                V value = body.apply(this, key);
                V raced = cache.putIfAbsent(key, value);   // if another thread won, hand out its value
                return raced != null ? raced : value;
            }
        };
    }

    static String describe(Throwable e) {
        StackTraceElement top = e.getStackTrace()[0];
        return e + " (thrown by " + top.getClassName() + "." + top.getMethodName() + ")";
    }

    static String attempt(Map<Integer, Long> cache, int n) {
        try {
            return String.valueOf(fibTrap(cache, n));
        } catch (RuntimeException e) {
            return describe(e);
        }
    }

    static int firstFailure(Supplier<Map<Integer, Long>> freshMap) {
        for (int n = 2; n <= 60; n++) {
            try {
                fibTrap(freshMap.get(), n);
            } catch (RuntimeException e) {
                return n;
            }
        }
        return -1;
    }

    static String nested(int outerKey, int innerKey) {
        Map<Integer, String> cache = new ConcurrentHashMap<>();
        try {
            cache.computeIfAbsent(outerKey, k -> cache.computeIfAbsent(innerKey, j -> "x"));
            return "ok";
        } catch (RuntimeException e) {
            return describe(e);
        }
    }

    record Cell(int row, int col) {}

    static <T> List<T> runConcurrently(int threads, Callable<T> task) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        try {
            List<Future<T>> futures = new ArrayList<>();
            for (int i = 0; i < threads; i++) futures.add(pool.submit(task));
            List<T> results = new ArrayList<>();
            for (Future<T> f : futures) results.add(f.get());
            return results;
        } finally {
            pool.shutdown();
        }
    }

    static void await(CyclicBarrier barrier) {
        try {
            barrier.await();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    public static void main(String[] args) throws Exception {
        // 1. The easy case: three calls, one computation.
        AtomicInteger calls = new AtomicInteger();
        Function<Integer, Integer> square = memoize(n -> { calls.incrementAndGet(); return n * n; });
        System.out.println("square(12) x3 = " + square.apply(12) + ", " + square.apply(12) + ", " + square.apply(12)
                + " with " + calls + " computation");

        // 2. The trap, with the real exceptions.
        System.out.println("HashMap fib(2):  " + attempt(new HashMap<>(), 2));
        System.out.println("HashMap fib(3):  " + attempt(new HashMap<>(), 3));
        System.out.println("CHM fib(13):     " + attempt(new ConcurrentHashMap<>(), 13));
        System.out.println("CHM fib(14):     " + attempt(new ConcurrentHashMap<>(), 14));

        // 3. The cliff moves when the table layout moves, which is the whole problem.
        System.out.println("first failing n, default table:  " + firstFailure(ConcurrentHashMap::new));
        System.out.println("first failing n, capacity 16:    " + firstFailure(() -> new ConcurrentHashMap<>(16)));
        System.out.println("first failing n, capacity 64:    " + firstFailure(() -> new ConcurrentHashMap<>(64)));
        System.out.println("nested keys 1 and 2:   " + nested(1, 2));
        System.out.println("nested keys 1 and 17:  " + nested(1, 17));

        // 4. Fix 1: get, compute, put. Fine on a plain HashMap, single thread.
        Map<Integer, Long> cache = new HashMap<>();
        System.out.println("get-put fib(90) = " + fibGetPut(cache, 90) + ", entries cached: " + cache.size());

        // 5. Fix 2: the memoizer passes itself. Works for any key type, here a record.
        Function<Integer, Long> fib = memoizeRecursive((self, n) -> n < 2 ? n : self.apply(n - 1) + self.apply(n - 2));
        System.out.println("self-passing fib(90) = " + fib.apply(90));
        Function<Cell, Long> paths = memoizeRecursive((self, c) -> c.row() == 0 || c.col() == 0
                ? 1L
                : self.apply(new Cell(c.row() - 1, c.col())) + self.apply(new Cell(c.row(), c.col() - 1)));
        System.out.println("lattice paths on a 16x16 grid = " + paths.apply(new Cell(16, 16)));

        // 6. Eight threads, one key. computeIfAbsent runs the function once and the others wait.
        AtomicInteger locked = new AtomicInteger();
        Function<String, Object> viaComputeIfAbsent = memoize(key -> {
            locked.incrementAndGet();
            try { Thread.sleep(20); } catch (InterruptedException e) { throw new IllegalStateException(e); }
            return new Object();
        });
        List<Object> a = runConcurrently(8, () -> viaComputeIfAbsent.apply("k"));
        System.out.println("computeIfAbsent: " + locked + " computation, " + a.stream().distinct().count() + " distinct value");

        // get/put does not wait: the barrier forces all eight threads to be inside the function together.
        AtomicInteger unlocked = new AtomicInteger();
        CyclicBarrier allInside = new CyclicBarrier(8);
        Function<String, Object> viaGetPut = memoizeRecursive((self, key) -> {
            unlocked.incrementAndGet();
            await(allInside);
            return new Object();
        });
        List<Object> b = runConcurrently(8, () -> viaGetPut.apply("k"));
        System.out.println("get-put:         " + unlocked + " computations, " + b.stream().distinct().count() + " distinct value");
    }
}
```

Output:

```text output
square(12) x3 = 144, 144, 144 with 1 computation
HashMap fib(2):  1
HashMap fib(3):  java.util.ConcurrentModificationException (thrown by java.util.HashMap.computeIfAbsent)
CHM fib(13):     233
CHM fib(14):     java.lang.IllegalStateException: Recursive update (thrown by java.util.concurrent.ConcurrentHashMap.transfer)
first failing n, default table:  14
first failing n, capacity 16:    26
first failing n, capacity 64:    -1
nested keys 1 and 2:   ok
nested keys 1 and 17:  java.lang.IllegalStateException: Recursive update (thrown by java.util.concurrent.ConcurrentHashMap.computeIfAbsent)
get-put fib(90) = 2880067194370816120, entries cached: 89
self-passing fib(90) = 2880067194370816120
lattice paths on a 16x16 grid = 601080390
computeIfAbsent: 1 computation, 1 distinct value
get-put:         8 computations, 1 distinct value
```

Memoized caches grow without bound, so here is the second half: a size limit with an LRU policy, and weak keys, with the ways each one disappoints.

```java run
import java.util.*;
import java.util.function.Function;

public class BoundedMemoDemo {

    /** Memoize with at most maxEntries results; the least recently used one is dropped first. */
    static <K, V> Function<K, V> memoizeLru(Function<K, V> f, int maxEntries) {
        Map<K, V> cache = new LinkedHashMap<>(16, 0.75f, true) {
            @Override protected boolean removeEldestEntry(Map.Entry<K, V> eldest) {
                return size() > maxEntries;
            }
        };
        return key -> {
            synchronized (cache) {
                V hit = cache.get(key);   // access order: even a read changes the map, so reads lock too
                if (hit != null) return hit;
            }
            V value = f.apply(key);       // compute outside the lock
            synchronized (cache) {
                cache.put(key, value);
            }
            return value;
        };
    }

    /** System.gc() is only a hint, so ask a few times. Returns true once the map has dropped everything. */
    static boolean emptiedByGc(Map<?, ?> map) throws InterruptedException {
        for (int round = 0; round < 30 && !map.isEmpty(); round++) {
            System.gc();
            Thread.sleep(10);
        }
        return map.isEmpty();
    }

    public static void main(String[] args) throws Exception {
        // 1. LRU: capacity 3. Reading 1 makes it recent, so 4 evicts 2, and asking for 2 recomputes it.
        List<Integer> computed = new ArrayList<>();
        Function<Integer, Integer> square = memoizeLru(n -> { computed.add(n); return n * n; }, 3);
        for (int n : new int[] {1, 2, 3, 1, 4, 2}) square.apply(n);
        System.out.println("computed: " + computed);

        // 2. Weak keys: the entry goes away when nobody else holds the key.
        Map<Object, Object> plain = Collections.synchronizedMap(new WeakHashMap<>());
        Object key = new Object();
        plain.put(key, "derived data");
        key = null;
        System.out.println("plain value, entry gone after GC:           " + emptiedByGc(plain));

        // 3. A value that points back at its key keeps the key alive forever.
        Map<Object, Object> leaky = Collections.synchronizedMap(new WeakHashMap<>());
        Object selfKey = new Object();
        leaky.put(selfKey, new Object[] {selfKey});
        selfKey = null;
        System.out.println("value references its key, entry gone:       " + emptiedByGc(leaky));

        // 4. A string literal lives in the constant pool, so it is never unreachable either.
        Map<Object, Object> literal = Collections.synchronizedMap(new WeakHashMap<>());
        literal.put("config", "derived data");
        System.out.println("string literal key, entry gone:             " + emptiedByGc(literal));
    }
}
```

Output:

```text output
computed: [1, 2, 3, 4, 2]
plain value, entry gone after GC:           true
value references its key, entry gone:       false
string literal key, entry gone:             false
```

## How it works

* **`computeIfAbsent` has a contract, and recursion violates it.** The mapping function runs while the map is in the middle of an update. `ConcurrentHashMap` keeps a placeholder (a `ReservationNode`) in the bin for the key being computed and holds that bin's lock. If the nested call needs the *same bin*, or if the table resizes while the placeholder is still there, the map notices and throws `IllegalStateException: Recursive update`. The `nested keys 1 and 17` line is the first case: with 16 bins, keys 1 and 17 share a bin. Keys 1 and 2 do not, the nested call succeeds, and the code looks fine. It is still forbidden.
* **The resize case is why fib(13) works and fib(14) does not.** The stack trace in the output names the method: `ConcurrentHashMap.transfer`, the resize routine. A default table has 16 bins and grows when it reaches 12 entries. At fib(14) the 12th entry is added while the outer call for key 14 is still waiting, so the resize runs into its placeholder. At fib(13) the same resize happens only after every pending call has finished. Presizing the map moves the cliff (capacity 16 fails later, capacity 64 not before fib(60)) but does not remove it. The exact numbers are an implementation detail of JDK 25.
* **`HashMap` detects it differently and earlier.** It compares its modification counter before and after the mapping function and throws a bare `ConcurrentModificationException` (no message, hence nothing after the class name) if the function changed the map. In fib(3) the nested call adds key 2, so the counter changed. In fib(2) the nested calls return `n` directly and never touch the map. Since Java 9 this check exists on a best-effort basis. On Java 8 the same code could loop forever on `ConcurrentHashMap` ([JDK-8062841](https://bugs.openjdk.org/browse/JDK-8062841)) or leave a `HashMap` holding an entry that `get` cannot find ([JDK-8071667](https://bugs.openjdk.org/browse/JDK-8071667)). Both are listed as fixed in Java 9, and the fix was detection (an exception), not support for recursion.
* **The get/put fix works because nothing is in flight.** `fibGetPut` finishes both recursive calls before it touches the map again, so the map is never mid-update when the recursion re-enters it. The cost is that two threads can both miss and both compute. That is harmless for a pure function, as the last output line shows: all eight threads ran the function, but `putIfAbsent` made them agree on one stored value.
* **Self-passing separates the recursion from the cache.** `memoizeRecursive` hands `this` to the body, so `self.apply(n - 1)` goes through the cache check, and the body author never writes cache code. Because the recursion never happens inside a map method, the same code works on a plain `HashMap`, a `ConcurrentHashMap` or an LRU map. Record keys work out of the box: `Cell` gets `equals` and `hashCode` from the record, so the grid walk solves a few hundred subproblems instead of enumerating C(32,16) = 601,080,390 paths one by one.
* **The LRU variant needs a lock even for reads.** `new LinkedHashMap<>(16, 0.75f, true)` orders entries by access, so `get` reorders the internal list. It computes outside the lock on purpose, so a slow function does not block every other key. See [074 · Sequenced Collections and a 10-Line LRU Cache](../08-streams-collections/074-sequenced-collections-lru.md) for the mechanism itself.
* **Weak keys fix a different problem.** `WeakHashMap` drops an entry once its key is otherwise unreachable, which suits "derived data per object" caches whose lifetime should follow the object. The last two output lines show two ways to defeat it: a value that points back at its own key, and a key that something else keeps alive (a string literal lives in the class's constant pool).

## Gotchas

* **`computeIfAbsent` does not cache `null`.** If the function returns `null`, nothing is stored and the next call computes again. The same goes for the `get`, then `put` variant above, which treats a `null` hit as a miss. If `null` is a legitimate answer, store `Optional` or a sentinel.
* **Exceptions are not cached either.** A function that throws leaves no entry behind, so the next caller tries again. That is usually what you want for transient failures and a bad idea for an input that always fails.
* **Only memoize pure functions.** If the result depends on the clock, a database row or a mutable argument, the cache will happily serve a stale answer forever. Mutable keys are the same bug in another coat: change a key after inserting it and the entry is lost.
* **A slow function inside `computeIfAbsent` blocks other work.** `ConcurrentHashMap` can hold a lock on the bin while it computes, so other threads updating keys in that bin wait. Keep the function short, or use the `get`, compute, `putIfAbsent` pattern, or a `Future`-based memoizer, which the book *Java Concurrency in Practice* builds step by step in its chapter on results caches. Two threads whose functions each look up the other's key can also deadlock inside `computeIfAbsent`.
* **Memoizing recursion does not reduce stack depth.** `fib.apply(100_000)` still recurses 100,000 frames deep on first call and throws `StackOverflowError`. Warm the cache bottom up in a loop, or see [007 · Trampolines](007-trampolines.md).
* **`long` holds Fibonacci numbers only up to fib(92).** The example stops at 90. Past 92, switch to `BigInteger`, or the cache will faithfully store overflowed garbage.
* **`System.gc()` in the weak-key demo is a request, not a command.** The loop makes it reliable in practice on HotSpot. Never build program logic on when a weak entry disappears.
* **A cache created inside a method dies with the method.** Call `memoize(f)` once and keep the result, usually in a `static final` field. Calling it per request gives you a fresh, empty cache every time.

## When to use it (and when not to)

Memoize a function that is pure, expensive compared to a map lookup, called repeatedly with a small or naturally bounded set of arguments, and not recursive (or recursive in the self-passing style). Parsed formats, compiled regexes, dynamic programming tables and per-class reflection results are all good candidates.

Do not use an unbounded `ConcurrentHashMap` as a cache in a long-running service. It never evicts, never expires, and its memory use is decided by whatever your users type. When you need a size bound, time-based expiry, refresh or statistics, use a purpose-built cache such as [Caffeine](https://github.com/ben-manes/caffeine). The hand-rolled versions here are for tests, tools, algorithms and bounded domains. And whatever you build, never put recursion inside `computeIfAbsent`: even when it works today, it works by accident.

## Related

* [072 · Map Power Idioms: merge, compute and Friends](../08-streams-collections/072-map-idioms.md), for the rest of the `Map` toolbox and a shorter look at the same trap
* [074 · Sequenced Collections and a 10-Line LRU Cache](../08-streams-collections/074-sequenced-collections-lru.md), for the eviction mechanism
* [082 · Lazy Initialization: Double-Checked Locking, Holders and Lazy Constants](../09-concurrency/082-lazy-and-dcl.md), the one-value version of the same idea
* [053 · The Y Combinator in Java](../06-hidden-corners/053-y-combinator.md), for the self-reference trick in its purest form

## Sources

* [`ConcurrentHashMap.computeIfAbsent` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/ConcurrentHashMap.html), including the rule about not updating other mappings
* [`HashMap.computeIfAbsent` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/HashMap.html), including the best-effort `ConcurrentModificationException`
* [JDK-8062841: ConcurrentHashMap.computeIfAbsent stuck in an endless loop](https://bugs.openjdk.org/browse/JDK-8062841)
* [JDK-8071667: HashMap.computeIfAbsent() adds entry that HashMap.get() does not find](https://bugs.openjdk.org/browse/JDK-8071667)
* Brian Goetz et al., [Java Concurrency in Practice](https://jcip.net/), section 5.6, "Building an efficient, scalable result cache"
