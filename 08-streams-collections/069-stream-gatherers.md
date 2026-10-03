# 069 · Stream Gatherers: Custom Intermediate Operations

> For ten years you could write your own terminal operation but not your own `map`. Java 24 finally hands you the middle of the pipeline.

**Since:** Java 24 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Advanced · **Verdict:** ✅ Production

## The problem

The Stream API has a fixed menu of intermediate operations: `map`, `filter`, `flatMap`, `distinct`, `sorted`, `limit`, `takeWhile` and a few more. Ask for anything slightly different and you fall off the edge:

* "group the elements into batches of 3" (there is no `window`),
* "distinct, but by a key" (`distinct()` only uses `equals`),
* "`takeWhile`, but keep the element that failed the test",
* "drop an element if it equals the previous one" (Unix `uniq`).

The usual escapes are all bad. `collect` into a list and loop, which kills laziness and infinite streams. A `filter` with a captured `HashSet`, which is a stateful lambda the Javadoc explicitly warns against. Or a custom `Spliterator` wrapper, which is a hundred lines of plumbing for a two-line idea. [Custom collectors](068-custom-collector.md) do not help either: a collector always ends the stream.

## The trick

`Stream.gather(Gatherer)` (JEP 485, final in Java 24 after previews in 22 and 23) accepts a user-defined intermediate operation. A `Gatherer<T, A, R>` mirrors a collector:

| Part | Collector | Gatherer |
|---|---|---|
| state | `supplier()` | `initializer()` |
| per element | `accumulator()` | `integrator()`, which may **push** zero or more outputs and may **return `false` to stop** |
| parallel merge | `combiner()` | `combiner()` (absent means sequential only) |
| end of input | `finisher()` returns the result | `finisher()` may push final outputs |

The integrator receives the state, the element and a `Downstream`. It emits with `downstream.push(r)`, and its return value answers "do you want more input?". That one boolean is what makes short-circuiting operations possible:

```java
static <T> Gatherer<T, ?, T> takeWhileInclusive(Predicate<? super T> test) {
    return Gatherer.ofSequential(
            Gatherer.Integrator.<Void, T, T>of((unused, element, downstream) ->
                    downstream.push(element) && test.test(element)));
}
```

Push the element, then stop if it failed the test. That is the whole operation.

## Full example

```java run
import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;
import java.util.stream.*;

public class GatherersDemo {

    /** Keeps the first element seen for each key. Stateful, never stops early: greedy. */
    static <T, K> Gatherer<T, ?, T> distinctBy(Function<? super T, ? extends K> key) {
        return Gatherer.ofSequential(
                () -> new HashSet<K>(),
                Gatherer.Integrator.ofGreedy((seen, element, downstream) ->
                        seen.add(key.apply(element)) ? downstream.push(element) : true));
    }

    /** Like takeWhile, but also emits the first element that fails the test. Short-circuits. */
    static <T> Gatherer<T, ?, T> takeWhileInclusive(Predicate<? super T> test) {
        return Gatherer.ofSequential(
                Gatherer.Integrator.<Void, T, T>of((unused, element, downstream) ->
                        downstream.push(element) && test.test(element)));
    }

    /** Drops an element if it equals the one right before it, like Unix uniq. */
    static <T> Gatherer<T, ?, T> dedupeConsecutive() {
        class Last { T value; boolean any; }
        return Gatherer.ofSequential(
                Last::new,
                Gatherer.Integrator.<Last, T, T>ofGreedy((last, element, downstream) -> {
                    if (last.any && Objects.equals(last.value, element)) return true;
                    last.any = true;
                    last.value = element;
                    return downstream.push(element);
                }));
    }

    record Reading(String sensor, int value) {}

    public static void main(String[] args) {
        List<Integer> oneToEight = List.of(1, 2, 3, 4, 5, 6, 7, 8);

        // Built-ins.
        System.out.println("windowFixed(3):   " + oneToEight.stream().gather(Gatherers.windowFixed(3)).toList());
        System.out.println("windowSliding(3): " + oneToEight.stream().limit(5).gather(Gatherers.windowSliding(3)).toList());
        System.out.println("scan(+):          " + oneToEight.stream().gather(Gatherers.scan(() -> 0, Integer::sum)).toList());
        System.out.println("fold(+):          " + oneToEight.stream().gather(Gatherers.fold(() -> 0, Integer::sum)).toList());

        // Custom ones.
        var readings = List.of(new Reading("north", 3), new Reading("south", 5), new Reading("north", 4),
                new Reading("east", 1), new Reading("south", 9));
        System.out.println("distinctBy:       " + readings.stream().gather(distinctBy(Reading::sensor)).toList());

        // Infinite source: only short-circuiting makes this terminate.
        System.out.println("takeWhile:        " + Stream.iterate(1, n -> n * 2).takeWhile(n -> n < 100).toList());
        System.out.println("takeWhileIncl.:   " + Stream.iterate(1, n -> n * 2).gather(takeWhileInclusive(n -> n < 100)).toList());

        System.out.println("dedupeConsecutive " + Stream.of("a", "a", "b", "b", "b", "a", "c", "c")
                .gather(dedupeConsecutive()).toList());

        // Gatherers compose with andThen, so one can feed another.
        Gatherer<Integer, ?, List<Integer>> evensInPairs = takeWhileInclusive((Integer n) -> n < 10)
                .andThen(Gatherers.windowFixed(2));
        System.out.println("andThen:          " + Stream.iterate(0, n -> n + 2).gather(evensInPairs).toList());

        // One to many: mapMulti (Java 16) and a stateless gatherer do the same job.
        System.out.println("mapMulti:         " + Stream.of(1, 2, 3)
                .<Integer>mapMulti((n, sink) -> { for (int i = 0; i < n; i++) sink.accept(n); }).toList());
        System.out.println("as a gatherer:    " + Stream.of(1, 2, 3)
                .gather(Gatherer.<Integer, Integer>of((unused, n, downstream) -> {
                    for (int i = 0; i < n; i++) if (!downstream.push(n)) return false;
                    return true;
                })).toList());

        mapConcurrentDemo(3);
        mapConcurrentDemo(2);
    }

    /** "a" can finish only after "b", and "b" only after "c". That needs three tasks running at once. */
    static void mapConcurrentDemo(int maxConcurrency) {
        Map<String, String> waitsFor = Map.of("a", "b", "b", "c");
        Map<String, CountDownLatch> finished = Map.of(
                "a", new CountDownLatch(1), "b", new CountDownLatch(1), "c", new CountDownLatch(1));
        List<String> completionOrder = new CopyOnWriteArrayList<>();
        try {
            List<String> results = Stream.of("a", "b", "c")
                    .gather(Gatherers.mapConcurrent(maxConcurrency, id -> {
                        String dependency = waitsFor.get(id);
                        if (dependency != null) await(finished.get(dependency), id + " gave up waiting for " + dependency);
                        completionOrder.add(id);
                        finished.get(id).countDown();
                        return id.toUpperCase() + (Thread.currentThread().isVirtual() ? "(virtual)" : "(platform)");
                    }))
                    .toList();
            System.out.println("mapConcurrent(" + maxConcurrency + "): finished " + completionOrder + ", emitted " + results);
        } catch (RuntimeException e) {
            System.out.println("mapConcurrent(" + maxConcurrency + "): " + e);
        }
    }

    static void await(CountDownLatch latch, String message) {
        try {
            if (!latch.await(1, TimeUnit.SECONDS)) throw new IllegalStateException(message);
        } catch (InterruptedException e) {
            throw new CancellationException("interrupted: " + message);
        }
    }
}
```

Output:

```text output
windowFixed(3):   [[1, 2, 3], [4, 5, 6], [7, 8]]
windowSliding(3): [[1, 2, 3], [2, 3, 4], [3, 4, 5]]
scan(+):          [1, 3, 6, 10, 15, 21, 28, 36]
fold(+):          [36]
distinctBy:       [Reading[sensor=north, value=3], Reading[sensor=south, value=5], Reading[sensor=east, value=1]]
takeWhile:        [1, 2, 4, 8, 16, 32, 64]
takeWhileIncl.:   [1, 2, 4, 8, 16, 32, 64, 128]
dedupeConsecutive [a, b, a, c]
andThen:          [[0, 2], [4, 6], [8, 10]]
mapMulti:         [1, 2, 2, 3, 3, 3]
as a gatherer:    [1, 2, 2, 3, 3, 3]
mapConcurrent(3): finished [c, b, a], emitted [A(virtual), B(virtual), C(virtual)]
mapConcurrent(2): java.lang.IllegalStateException: a gave up waiting for b
```

The last line takes about one second: that is the timeout in `await` expiring.

## How it works

### The built-ins

`java.util.stream.Gatherers` ships five, and all five are built with `ofSequential`:

* **`windowFixed(n)`** batches elements into lists of `n`; the last window may be shorter (`[7, 8]`). It pushes the partial window from its *finisher*, which is exactly what the end-of-input hook is for.
* **`windowSliding(n)`** emits every run of `n` consecutive elements, overlapping.
* **`scan(init, f)`** is a running fold: it emits every intermediate result (`1, 3, 6, ...`), so prefix sums, running maxima and balances become one line.
* **`fold(init, f)`** emits only the final value, as a one-element stream. Use it when you want a reduction but keep streaming afterwards; otherwise `reduce` or a collector is clearer.
* **`mapConcurrent(n, f)`** applies `f` with at most `n` invocations in flight. Its Javadoc is precise, and worth reading literally: it executes the function concurrently "using virtual threads", and "this operation preserves the ordering of the stream". In-progress tasks are cancelled "on a best-effort basis" when the downstream no longer wants elements, and if a function call fails, its exception is rethrown as a `RuntimeException` "after which any remaining tasks are canceled".

The `mapConcurrent` demo checks each of those claims. With `maxConcurrency` 3, `a` waits for `b` and `b` waits for `c`, so the tasks *finish* in the order `c, b, a`, which is only possible if all three ran at the same time. They are still *emitted* in the order `a, b, c`, each on a virtual thread. With `maxConcurrency` 2, `c` cannot start until `a` is done, `a` cannot finish without `c`, and `a` gives up after one second. Its `IllegalStateException` comes out of the stream unchanged (it already is a `RuntimeException`), and the still-waiting `b` is cancelled.

### The custom ones

* **`distinctBy`** keeps a `HashSet` of keys as its state. Because the state comes from the initializer, every stream evaluation gets a fresh set, which is what makes this safe where `filter(seen::add)` with a captured set is not.
* **`takeWhileInclusive`** never stores anything (state type `Void`) and short-circuits by returning `false`. On `Stream.iterate(1, n -> n * 2)`, an infinite stream, it stops after pushing `128`, one element further than the built-in `takeWhile`.
* **`dedupeConsecutive`** remembers only the last element, so it runs in constant memory on any stream length, unlike `distinct()`, which remembers everything.
* **Greedy or not.** `Integrator.ofGreedy` marks an integrator that never *initiates* a stop: it only passes on the downstream's answer. The stream can use that to skip cancellation checks. `takeWhileInclusive` starts the stop itself, so it uses `Integrator.of`.
* **`andThen`** fuses two gatherers into one. Here a short-circuiting gatherer feeds `windowFixed(2)`, and the infinite stream of even numbers ends after `[8, 10]`.

### Gatherer or mapMulti?

For pure one-to-many expansion, `mapMulti` (Java 16) is shorter and does the same job, as the two identical lines show. It cannot keep state between elements, cannot stop the stream and cannot push anything at the end. The moment you need any of those three, you need a gatherer.

## Gotchas

* **Type inference gives up quickly.** Generic factories like `ofSequential(initializer, Integrator.ofGreedy(lambda))` often need explicit witnesses (`Gatherer.Integrator.<Last, T, T>ofGreedy(...)`) or a typed lambda parameter (`(Integer n) -> n < 10` above). That is noise, but it is compile-time noise.
* **Respect `push`'s answer.** `push` returns `false` when the downstream wants nothing more. An integrator that emits several elements per input should stop at the first `false`, as the `mapMulti` style gatherer does, instead of computing outputs nobody will read.
* **Do not mark a short-circuiting integrator as greedy.** The spec allows the stream to ignore a greedy integrator's return value. The current implementation happens to stop anyway, which is precisely the kind of behavior not to rely on.
* **Sequential gatherers serialize their stage.** A gatherer without a combiner (all five built-ins, everything made with `ofSequential`) "may only be evaluated sequentially". It still works in a parallel stream, but it is a bottleneck there. Supply a combiner via `Gatherer.of(initializer, integrator, combiner, finisher)` if the operation can really be split.
* **`mapConcurrent` has head-of-line blocking.** Because order is preserved, one slow element holds back every result behind it, and a full set of `n` finished-but-not-emitted results stops new tasks from starting. It is a bounded fan-out for blocking I/O, not a work-stealing pool. And do not wrap it around CPU-bound work: virtual threads do not add cores (see [077](../09-concurrency/077-virtual-threads.md)).
* **State must stay private.** The Javadoc forbids leaking the state object or the `Downstream` to other threads or keeping them beyond the call. Capture neither in a field.

## When to use it (and when not to)

Use gatherers for reusable, stateful intermediate steps that the Stream API lacks: windows, running totals, distinct by key, dedupe, rate-limited concurrent mapping. Put each one behind a well-named static factory, exactly like a custom collector, and the call site reads like a built-in: `.gather(distinctBy(Reading::sensor))`.

Skip them when an existing operation fits (`takeWhile`, `mapMulti`, `distinct`), and when the job is really a reduction, which belongs in a collector. On Java 21 or earlier there is no `gather` at all: libraries like jOOλ or StreamEx are the fallback there.

## Related

* [068 · Writing Your Own Collector](068-custom-collector.md), the terminal-operation sibling with the same four-function shape
* [070 · Infinite Streams and Generators](070-infinite-streams.md), where short-circuiting gatherers earn their keep
* [073 · Stream Laziness Puzzlers](073-stream-laziness-puzzlers.md), for how elements flow through stages one by one
* [077 · Virtual Threads: A Million Threads and the Pinning Trap](../09-concurrency/077-virtual-threads.md), the machinery behind `mapConcurrent`

## Sources

* [JEP 485: Stream Gatherers](https://openjdk.org/jeps/485)
* [`java.util.stream.Gatherer` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Gatherer.html)
* [`java.util.stream.Gatherers` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Gatherers.html), including the exact `mapConcurrent` contract
* [The Gatherer API](https://dev.java/learn/api/collections-and-streams/streams/gatherers/), the dev.java tutorial
* [Better Java Streams with Gatherers (JEP Café #23)](https://www.youtube.com/watch?v=jqUhObgDd5Q), on the official Java YouTube channel
