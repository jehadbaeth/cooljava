# 068 · Writing Your Own Collector

> Four small functions and a set of flags. Get the fourth function wrong and every sequential test still passes.

**Since:** Java 16 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Advanced · **Verdict:** ✅ Production

## The problem

The built-in collectors (see [067](067-collectors-masterclass.md)) cover counting, summing, grouping and joining. They do not cover a surprising number of everyday questions:

* "the 5 highest scores" without sorting 200,000 elements just to throw 199,995 away,
* "mean *and standard deviation*" (`summarizingDouble` has no variance),
* "top 3 per category", which is just the first one used as a `groupingBy` downstream.

The usual workaround is `collect(toList())` followed by a hand-written loop. That materializes everything, cannot run in parallel, and does not compose. A custom `Collector` fixes all three, and it is smaller than people expect.

## The trick

A `Collector<T, A, R>` is a recipe in four functions plus metadata:

| Part | Type | Job |
|---|---|---|
| supplier | `Supplier<A>` | make a fresh, empty mutable container |
| accumulator | `BiConsumer<A, T>` | fold one element into a container |
| combiner | `BinaryOperator<A>` | merge two containers (parallel only) |
| finisher | `Function<A, R>` | turn the container into the result |
| characteristics | `Set<Characteristics>` | promises: `IDENTITY_FINISH`, `UNORDERED`, `CONCURRENT` |

`Collector.of(...)` builds one from lambdas. A top N collector keeps a **bounded min-heap**: the weakest of the current top N sits at the head, so each new element costs one `offer` and at most one `poll`, and memory stays at N no matter how long the stream is.

```java
Collector.of(
        () -> new PriorityQueue<T>(order),
        (heap, t) -> { heap.offer(t); if (heap.size() > n) heap.poll(); },
        (left, right) -> { right.forEach(t -> offer.accept(left, t)); return left; },
        heap -> { List<T> r = new ArrayList<>(heap); r.sort(order.reversed()); return r; },
        Collector.Characteristics.UNORDERED);
```

`Collector.of` has been there since Java 8. The badge says 16 because the example uses records and `Stream.toList()`.

## Full example

```java run
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.*;
import java.util.stream.*;

public class CustomCollectorDemo {

    /** The n largest elements, largest first. A bounded min-heap keeps memory at O(n). */
    static <T> Collector<T, ?, List<T>> topN(int n, Comparator<? super T> order) {
        BiConsumer<PriorityQueue<T>, T> offer = (heap, t) -> {
            heap.offer(t);
            if (heap.size() > n) heap.poll();          // evict the weakest of the current top n
        };
        return Collector.of(
                () -> new PriorityQueue<T>(order),     // min-heap: the weakest candidate sits at the head
                offer,
                (left, right) -> {                     // merge two partial top-n heaps
                    right.forEach(t -> offer.accept(left, t));
                    return left;
                },
                heap -> {
                    List<T> result = new ArrayList<>(heap);
                    result.sort(order.reversed());
                    return result;
                },
                Collector.Characteristics.UNORDERED);  // the result is sorted anyway, input order is irrelevant
    }

    /** Count, mean and variance in one pass: Welford's update, Chan's parallel merge. */
    static final class Moments {
        long n;
        double mean, m2;

        void add(double x) {
            n++;
            double delta = x - mean;
            mean += delta / n;
            m2 += delta * (x - mean);
        }

        Moments combine(Moments other) {
            if (other.n == 0) return this;
            if (n == 0) return other;
            long total = n + other.n;
            double delta = other.mean - mean;
            mean += delta * other.n / total;
            m2 += other.m2 + delta * delta * n * other.n / total;
            n = total;
            return this;
        }
    }

    record Stats(long count, double mean, double stddev) {
        @Override public String toString() {
            return String.format("n=%d mean=%.4f stddev=%.4f", count, mean, stddev);
        }
    }

    static <T> Collector<T, Moments, Stats> stats(ToDoubleFunction<? super T> value) {
        return Collector.of(
                Moments::new,
                (m, t) -> m.add(value.applyAsDouble(t)),
                Moments::combine,
                m -> new Stats(m.n, m.mean, m.n > 1 ? Math.sqrt(m.m2 / (m.n - 1)) : 0.0));
    }

    /** Same collector, different combiner. Used to count calls and to break things on purpose. */
    static <T, A, R> Collector<T, A, R> withCombiner(Collector<T, A, R> c, BinaryOperator<A> combiner) {
        return Collector.of(c.supplier(), c.accumulator(), combiner, c.finisher(),
                c.characteristics().toArray(Collector.Characteristics[]::new));
    }

    static <T, A, R> Collector<T, A, R> countingCombines(Collector<T, A, R> c, AtomicInteger calls) {
        return withCombiner(c, (a, b) -> {
            calls.incrementAndGet();
            return c.combiner().apply(a, b);
        });
    }

    /** What a parallel stream does, done by hand: two isolated halves, one combine, one finish. */
    static <T, A, R> R splitByHand(Collector<T, A, R> c, List<T> left, List<T> right) {
        A a = c.supplier().get();
        left.forEach(t -> c.accumulator().accept(a, t));
        A b = c.supplier().get();
        right.forEach(t -> c.accumulator().accept(b, t));
        return c.finisher().apply(c.combiner().apply(a, b));
    }

    public static void main(String[] args) {
        List<Integer> scores = new Random(42).ints(200_000, 0, 1_000_000).boxed().toList();
        Collector<Integer, ?, List<Integer>> top5 = topN(5, Comparator.naturalOrder());

        System.out.println("top 5 sequential: " + scores.stream().collect(top5));
        System.out.println("top 5 parallel:   " + scores.parallelStream().collect(top5));
        System.out.println("top 3 by hand:    " + splitByHand(topN(3, Comparator.<Integer>naturalOrder()),
                List.of(5, 1, 9, 3), List.of(8, 2, 7)));

        List<Double> values = IntStream.rangeClosed(1, 1_000_000).asDoubleStream().boxed().toList();
        System.out.println("stats sequential: " + values.stream().collect(stats(x -> x)));
        System.out.println("stats parallel:   " + values.parallelStream().collect(stats(x -> x)));

        // A custom collector composes like a built-in one, here as a groupingBy downstream.
        System.out.println("stats by parity:  " + IntStream.rangeClosed(1, 10).boxed()
                .collect(Collectors.groupingBy(i -> i % 2 == 0 ? "even" : "odd", TreeMap::new, stats(i -> i))));

        // Sequential streams never call the combiner, so a sequential test never tests it.
        var sequentialCalls = new AtomicInteger();
        var parallelCalls = new AtomicInteger();
        scores.stream().collect(countingCombines(top5, sequentialCalls));
        scores.parallelStream().collect(countingCombines(top5, parallelCalls));
        System.out.println("combiner calls, sequential: " + sequentialCalls.get());
        System.out.println("combiner calls, parallel > 0: " + (parallelCalls.get() > 0));

        // A combiner that drops the right half: invisible sequentially, wrong in parallel.
        var broken = withCombiner(top5, (left, right) -> left);
        var expected = scores.stream().collect(top5);
        System.out.println("broken, sequential correct? " + scores.stream().collect(broken).equals(expected));
        System.out.println("broken, parallel correct?   " + scores.parallelStream().collect(broken).equals(expected));

        // IDENTITY_FINISH is a promise. Break it and the finisher is silently skipped.
        BinaryOperator<List<String>> concat = (a, b) -> { a.addAll(b); return a; };
        UnaryOperator<List<String>> sort = list -> { Collections.sort(list); return list; };
        Collector<String, List<String>, List<String>> honest = Collector.of(ArrayList::new, List::add, concat, sort);
        Collector<String, List<String>, List<String>> lying = Collector.of(ArrayList::new, List::add, concat, sort,
                Collector.Characteristics.IDENTITY_FINISH);
        var fruit = List.of("pear", "fig", "apple");
        System.out.println("finisher runs:        " + fruit.stream().collect(honest));
        System.out.println("IDENTITY_FINISH lies: " + fruit.stream().collect(lying));

        System.out.println("toList()              " + Collectors.toList().characteristics());
        System.out.println("toSet()               " + Collectors.toSet().characteristics());
        System.out.println("joining()             " + Collectors.joining().characteristics());
        System.out.println("groupingByConcurrent  " + Collectors.groupingByConcurrent(x -> x).characteristics());
        System.out.println("topN (ours)           " + top5.characteristics());
    }
}
```

Output:

```text output
top 5 sequential: [999996, 999992, 999991, 999989, 999986]
top 5 parallel:   [999996, 999992, 999991, 999989, 999986]
top 3 by hand:    [9, 8, 7]
stats sequential: n=1000000 mean=500000.5000 stddev=288675.2789
stats parallel:   n=1000000 mean=500000.5000 stddev=288675.2789
stats by parity:  {even=n=5 mean=6.0000 stddev=3.1623, odd=n=5 mean=5.0000 stddev=3.1623}
combiner calls, sequential: 0
combiner calls, parallel > 0: true
broken, sequential correct? true
broken, parallel correct?   false
finisher runs:        [apple, fig, pear]
IDENTITY_FINISH lies: [pear, fig, apple]
toList()              [IDENTITY_FINISH]
toSet()               [UNORDERED, IDENTITY_FINISH]
joining()             []
groupingByConcurrent  [CONCURRENT, UNORDERED, IDENTITY_FINISH]
topN (ours)           [UNORDERED]
```

## How it works

* **The heap is the whole top N trick.** `PriorityQueue` with the natural order is a min-heap, so `poll()` removes the smallest of the current candidates. After every element the heap holds the N largest seen so far. That is O(total × log N) time and O(N) memory, against O(total × log total) and O(total) for "sort, then `limit(5)`". The finisher sorts the five survivors, largest first.
* **The combiner is only for parallel streams.** A sequential stream creates one container and never combines anything, which the `combiner calls, sequential: 0` line proves. A parallel stream splits the source, runs supplier and accumulator on each chunk in isolation, and merges results pairwise with the combiner. `splitByHand` does exactly that with two halves, which is how to unit test a combiner deterministically. The real number of combiner calls in parallel depends on the size of the common pool, so the example only prints that it is above zero.
* **A broken combiner passes every sequential test.** `(left, right) -> left` throws away half of the work. Sequentially the result is still correct; in parallel it is wrong. If you write a collector, test it with `parallelStream()` (or with `splitByHand`), or you have not tested the combiner at all.
* **Statistics need a mergeable state, not just a running total.** Welford's update keeps `n`, the running mean and `m2` (the sum of squared deviations), which is numerically stable where the textbook `sum of squares minus square of sum` is not. Chan, Golub and LeVeque's formula merges two such states exactly, so the parallel result matches the sequential one at the printed precision.
* **Composition is free.** `stats(i -> i)` drops straight into `groupingBy` as a downstream collector, same as `counting()`.

### What the characteristics promise

* **`IDENTITY_FINISH`** says "the container *is* the result, the finisher is a no-op". The stream implementation believes you and skips the finisher with an unchecked cast. The `lying` collector declares it next to a sorting finisher, and its output comes back unsorted. If `A` and `R` were different types you would get a `ClassCastException` at the call site instead. The four-argument `Collector.of` (no finisher) adds `IDENTITY_FINISH` for you; the five-argument one only uses what you pass.
* **`UNORDERED`** says "the result does not depend on encounter order". `toSet()` declares it, `toList()` does not, and neither does `joining()`. It lets the stream drop ordering constraints upstream, and it is one of the two conditions for a concurrent reduction.
* **`CONCURRENT`** says "many threads may call the accumulator on *one shared container*". A parallel stream then skips the per-chunk containers and the combiner entirely, but only if the collector is also `UNORDERED` or the source is unordered. `groupingByConcurrent` is the built-in example. Your container must then be genuinely thread-safe (`ConcurrentHashMap`, `LongAdder`), or results get lost silently.

## Gotchas

* **Never capture a container outside the supplier.** `Collector.of(() -> shared, ...)` returns the same list for every chunk, and in parallel several threads write to one `ArrayList`. The `Collector` contract requires each container to be thread-confined unless you declare `CONCURRENT`.
* **The combiner may mutate and return either argument**, but whichever it does not return is never used again. Returning a brand new object is also allowed, just slower.
* **Ties in top N are unspecified.** When two elements compare equal, which one survives depends on the order they arrive in, and that differs between a sequential and a parallel run (and, in parallel, with the size of the common pool). Break ties in the comparator (`thenComparing(...)`) if it matters.
* **Do not reach for a collector when a stream operation fits.** For one-to-one or one-to-many transformations that keep the stream going, an intermediate operation ([069 · Gatherers](069-stream-gatherers.md)) is the right tool. A collector always ends the stream.

## When to use it (and when not to)

Write a collector when a reduction is reused in several places, needs to run in parallel, or should work as a `groupingBy` downstream: top N, histograms, streaming statistics, "collect into my immutable type". Wrap it in a static factory method with a good name, and test it with a parallel stream.

Do not write one for a single call site where `collect(toList())` plus three lines is clearer. And do not hand-roll statistics if a library you already depend on (Apache Commons Math, for instance) has them.

## Related

* [067 · Collectors Masterclass](067-collectors-masterclass.md), the built-ins this one plugs into
* [069 · Stream Gatherers: Custom Intermediate Operations](069-stream-gatherers.md), the same four-function idea for the middle of a pipeline
* [071 · Zipping Streams and Custom Spliterators](071-zip-and-spliterators.md), the other end: how sources split for parallelism
* [076 · Comparator Combinators](076-comparator-combinators.md), for the comparator a top N collector needs

## Sources

* [`java.util.stream.Collector` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Collector.html), including the associativity and identity constraints
* [Algorithms for calculating variance](https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance), Wikipedia, covering Welford's online algorithm and Chan et al.'s parallel merge
* Brian Goetz, [State of the Lambda: Libraries Edition](https://cr.openjdk.org/~briangoetz/lambda/lambda-libraries-final.html)
