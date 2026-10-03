# 073 · Stream Laziness Puzzlers

> A stream that maps three orders to three invoices and counts them sends exactly zero invoices. Streams are lazy, and since Java 9 `count()` is lazy enough to skip your lambdas altogether.

**Since:** Java 10 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

Every lambda below records what it touched in a trace, and every numbered line prints that trace. Before you scroll to the answer, predict for each line which lambdas run, how often, and in which order. Pay special attention to line 1 and the table in line 2.

```java run
import java.util.*;
import java.util.function.*;
import java.util.stream.*;

public class LazyStreams {

    static final List<String> trace = new ArrayList<>();

    /** Records that a stage touched a value, then hands the value on unchanged. */
    static <T> T saw(String stage, T value) {
        trace.add(stage + ":" + value);
        return value;
    }

    /** Returns the trace so far and clears it. */
    static String drain() {
        String result = trace.isEmpty() ? "(nothing ran)" : String.join(" ", trace);
        trace.clear();
        return result;
    }

    static void peekThenCount(String label, Supplier<Stream<?>> pipeline) {
        long count = pipeline.get().peek(x -> saw("peek", x)).count();
        System.out.printf("   %-28s count=%d, peek ran %d times%n", label, count, trace.size());
        trace.clear();
    }

    static int invoicesSent = 0;

    static String sendInvoice(String order) {
        invoicesSent++;
        return "invoice for " + order;
    }

    public static void main(String[] args) {
        List<String> orders = List.of("A-17", "B-42", "C-99");
        List<String> fruit = List.of("lime", "fig", "plum", "kiwi");

        // 1. A side effect in map, followed by count().
        long invoices = orders.stream().map(LazyStreams::sendInvoice).count();
        System.out.println("1. invoices counted: " + invoices + ", invoices sent: " + invoicesSent);

        // 2. Same question with peek: which of these pipelines actually run?
        System.out.println("2. peek(...).count() on a list of " + fruit.size() + ":");
        peekThenCount("stream()", () -> fruit.stream());
        peekThenCount("map(String::toUpperCase)", () -> fruit.stream().map(String::toUpperCase));
        peekThenCount("sorted()", () -> fruit.stream().sorted());
        peekThenCount("skip(1)", () -> fruit.stream().skip(1));
        peekThenCount("filter(f -> true)", () -> fruit.stream().filter(f -> true));
        peekThenCount("flatMap(Stream::of)", () -> fruit.stream().flatMap(Stream::of));
        peekThenCount("distinct()", () -> fruit.stream().distinct());
        peekThenCount("iterate(1, i <= 4, i + 1)", () -> Stream.iterate(1, i -> i <= 4, i -> i + 1));
        List<String> collected = fruit.stream().peek(f -> saw("peek", f)).collect(Collectors.toList());
        System.out.printf("   %-28s size=%d,  peek ran %d times%n", "collect(toList()).size()", collected.size(), trace.size());
        trace.clear();

        // 3. No terminal operation, no work.
        Stream<String> pending = fruit.stream().map(f -> saw("map", f));
        System.out.println("3. before forEach: " + drain());
        pending.forEach(f -> { });
        System.out.println("   after forEach:  " + drain());

        // 4. In which order do filter, map and forEach see the elements?
        fruit.stream()
                .filter(f -> saw("filter", f).length() == 4)
                .map(f -> saw("map", f).toUpperCase())
                .forEach(f -> saw("out", f));
        System.out.println("4. order: " + drain());

        // 5. How much of the list does findFirst look at?
        String firstP = fruit.stream()
                .filter(f -> saw("filter", f).startsWith("p"))
                .map(f -> saw("map", f).toUpperCase())
                .findFirst().orElseThrow();
        System.out.println("5. findFirst: " + drain() + " -> " + firstP);

        // 6. The same shape with sorted() in the middle.
        String smallest = fruit.stream()
                .filter(f -> saw("filter", f).length() == 4)
                .sorted()
                .map(f -> saw("map", f).toUpperCase())
                .findFirst().orElseThrow();
        System.out.println("6. sorted:    " + drain() + " -> " + smallest);

        // 7. Every inner stream is infinite. Does findFirst still return?
        int firstAboveFive = Stream.of(1, 2, 3)
                .flatMap(n -> Stream.iterate(n, i -> i + 1))
                .filter(i -> i > 5)
                .findFirst().orElseThrow();
        System.out.println("7. flatMap over infinite streams: " + firstAboveFive);

        // 8. Two pipelines from one stream variable.
        Stream<String> shared = fruit.stream();
        shared.filter(f -> f.length() == 4);            // result ignored
        try {
            shared.map(String::toUpperCase);
            System.out.println("8. reuse worked");
        } catch (IllegalStateException e) {
            System.out.println("8. reuse: IllegalStateException: " + e.getMessage());
        }
        Supplier<Stream<String>> fresh = fruit::stream;
        System.out.println("   a Supplier gives a new stream each time: "
                + fresh.get().count() + " fruit, " + fresh.get().filter(f -> f.length() == 4).count() + " with four letters");
    }
}
```

## The answer

```text output
1. invoices counted: 3, invoices sent: 0
2. peek(...).count() on a list of 4:
   stream()                     count=4, peek ran 0 times
   map(String::toUpperCase)     count=4, peek ran 0 times
   sorted()                     count=4, peek ran 0 times
   skip(1)                      count=3, peek ran 0 times
   filter(f -> true)            count=4, peek ran 4 times
   flatMap(Stream::of)          count=4, peek ran 4 times
   distinct()                   count=4, peek ran 4 times
   iterate(1, i <= 4, i + 1)    count=4, peek ran 4 times
   collect(toList()).size()     size=4,  peek ran 4 times
3. before forEach: (nothing ran)
   after forEach:  map:lime map:fig map:plum map:kiwi
4. order: filter:lime map:lime out:LIME filter:fig filter:plum map:plum out:PLUM filter:kiwi map:kiwi out:KIWI
5. findFirst: filter:lime filter:fig filter:plum map:plum -> PLUM
6. sorted:    filter:lime filter:fig filter:plum filter:kiwi map:kiwi -> KIWI
7. flatMap over infinite streams: 6
8. reuse: IllegalStateException: stream has already been operated upon or closed
   a Supplier gives a new stream each time: 4 fruit, 3 with four letters
```

## Why

### `count()` skips the pipeline when the size is already known

Every stream carries flags describing its source: `SIZED`, `ORDERED`, `DISTINCT`, `SORTED` and a few more. A `List` reports `SIZED`, and so do arrays, `IntStream.range`, `HashSet` and most JDK collections. Each intermediate operation declares whether it keeps or clears that flag. `map`, `peek`, `sorted` and `boxed` cannot change the number of elements, so they keep it. `filter`, `flatMap`, `distinct`, `takeWhile` and `mapMulti` might, so they clear it.

Since Java 9, `count()` checks the flag first. If the whole pipeline is still `SIZED`, it returns the size of the source and never traverses a single element. No traversal means no `map`, no `peek` and no `sendInvoice`. The Javadoc of `count()` has said so since Java 9, with almost exactly this example:

> An implementation may choose to not execute the stream pipeline (either sequentially or in parallel) if it is capable of computing the count directly from the stream source. In such cases no source elements will be traversed and no intermediate operations will be evaluated.

That explains the table. `skip(1)` keeps the flag too: on JDK 17 through 27 (all checked) slice operations on a `SIZED` stream compute the new size arithmetically, so the pipeline is skipped. An `iterate` source with a `hasNext` predicate has no idea how many elements it will produce, so it must actually run. `filter(f -> true)` never removes anything, but the stream cannot know that, so the flag is gone and `peek` runs. And the same pipeline with `collect(...)` instead of `count()` needs the elements themselves, so `peek` runs four times. On Java 8, `count()` was a plain reduction, so every line in the table ran `peek`.

Your own `Spliterator` gets the same treatment if it reports `SIZED`, as [071](071-zip-and-spliterators.md) shows with a source that counts how often it is pulled.

### Vertical, not horizontal

Line 4 does not run `filter` on everything, then `map` on everything. The terminal operation builds a chain of sinks, one per stage, and the source pushes **one element at a time through the whole chain**: `lime` goes through filter, map and forEach before `fig` is even read. `fig` fails the filter and never reaches `map`. That is why a stream over a million elements does not need a million-element intermediate list for every stage.

### Short-circuiting stops the source

`findFirst`, `findAny`, `anyMatch`, `allMatch`, `noneMatch` and `limit` are short-circuiting. Once `findFirst` has its answer, the source loop checks a cancellation flag before each element and stops. In line 5, `kiwi` is never read at all, and `map` runs exactly once.

### `sorted()` is a barrier

A sort cannot emit its smallest element before it has seen all of them. So `sorted()` collects everything upstream (all four `filter` calls run), sorts, and only then pushes elements downstream, where `findFirst` stops after the first one: `map` runs once, on `kiwi`. Short-circuiting below a barrier saves the downstream work but not the upstream work. On an infinite stream that barrier means the program never finishes, which [070](070-infinite-streams.md) covers.

### `flatMap` became lazy in Java 10

Line 7 returns `6`, because the first inner stream (1, 2, 3, ...) reaches 6 and `findFirst` cancels it. On Java 8 and 9 `flatMap` pushed each inner stream into the downstream completely before checking for cancellation, so the same line never returned. The fix (JDK-8075939) shipped in Java 10. If you maintain Java 8 code, an infinite or huge inner stream behind `flatMap` is a hang waiting to happen. It is also why this doc's badge says Java 10 although the `count()` shortcut is from Java 9: line 7 needs the fix, and the no-argument `orElseThrow()` is Java 10 API anyway.

### A stream is a one-shot pipeline, not a collection

Calling an intermediate operation on a stream links a new stage to it and marks the old one as used. In line 8 the ignored `filter` call already consumed `shared`, so the `map` call throws `IllegalStateException` with the message shown, even though no terminal operation ever ran. If code needs to traverse the same data twice, pass the collection or a `Supplier<Stream<T>>`, never the `Stream`.

### Parallel streams: order of side effects is not order of results

The last classic is about `forEach` on a parallel stream. This one is not deterministic, so the output below is one sample run and will look different on your machine and on every run:

```java run nondeterministic
import java.util.*;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.stream.*;

public class ParallelOrder {
    public static void main(String[] args) {
        List<Integer> numbers = IntStream.rangeClosed(1, 12).boxed().collect(Collectors.toList());

        Queue<Integer> forEachOrder = new ConcurrentLinkedQueue<>();
        numbers.parallelStream().forEach(forEachOrder::add);
        System.out.println("forEach:            " + forEachOrder);

        List<Integer> orderedOrder = new ArrayList<>();
        numbers.parallelStream().forEachOrdered(orderedOrder::add);
        System.out.println("forEachOrdered:     " + orderedOrder);

        System.out.println("map + collect:      " + numbers.parallelStream().map(n -> n * 10).collect(Collectors.toList()));

        // A shared, non-thread-safe list as a side-effect target.
        List<Integer> unsafe = new ArrayList<>();
        try {
            IntStream.range(0, 100_000).parallel().forEach(unsafe::add);
            System.out.println("ArrayList.add:      " + unsafe.size() + " of 100000 elements arrived");
        } catch (RuntimeException e) {
            System.out.println("ArrayList.add:      " + e.getClass().getSimpleName());
        }
        List<Integer> safe = IntStream.range(0, 100_000).parallel().boxed().collect(Collectors.toList());
        System.out.println("collect(toList()):  " + safe.size() + " of 100000 elements arrived");
    }
}
```

```text output
forEach:            [8, 9, 2, 7, 3, 6, 1, 5, 4, 11, 12, 10]
forEachOrdered:     [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
map + collect:      [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
ArrayList.add:      32574 of 100000 elements arrived
collect(toList()):  100000 of 100000 elements arrived
```

`forEach` on a parallel stream runs the action in whatever thread and order the fork/join pool happens to schedule. `forEachOrdered` restores encounter order, and `collect` keeps it without any help, because each chunk is collected separately and the chunks are combined in order. The shared `ArrayList` is the real lesson: concurrent `add` calls overwrite each other or blow up on a resize. Either way the result is wrong, and you cannot tell from the code which way it fails.

## Gotchas

* **Debug output that vanishes.** A `peek(System.out::println)` that printed yesterday stops printing after someone replaces `.collect(toList()).size()` with `.count()`. Nothing is broken; the pipeline simply no longer runs. The `peek` Javadoc says it "exists mainly to support debugging", and this is why it should stay that way.
* **The same code behaves differently on a different source.** Swap the `List` for an `Iterator` based stream, or add a `filter` upstream, and the side effects in `map` start happening again. Whether your lambda runs depends on flags you cannot see in the code.
* **`sorted().findFirst()` is a full sort.** It reads and sorts everything to return one element. `min(comparator)` does the same job in one pass without buffering.
* **Side effects make laziness visible.** Interference (modifying the source while the stream runs) gives you a `ConcurrentModificationException` on an `ArrayList` and undefined behavior elsewhere. Stateful lambdas (`seen.add(x)` inside a `filter`) silently change meaning with ordering and parallelism.
* **`forEachOrdered` costs most of the parallelism.** It has to hold back results until all earlier elements are done. If you need order, you usually want `collect`, not ordered side effects.
* **Resource-backed streams are single-use too.** `Files.lines(path)` cannot be traversed twice either, and it must be closed (try-with-resources), which a `Supplier<Stream<String>>` makes easy to forget.

## How to stay safe

* Treat stream lambdas as pure functions. Put actions that must happen (sending, saving, logging that matters) in a plain loop or in the terminal `forEach`, never in `map`, `filter` or `peek`.
* If you need both the elements and their number, collect once and call `size()`.
* Prefer `min`, `max`, `anyMatch` and `findFirst` over `sorted()` followed by a short-circuit, unless you genuinely need the order.
* Never store a `Stream` in a field or pass it to code that might traverse it twice. Pass the collection or a `Supplier`.
* In parallel streams, combine results with collectors or reductions instead of writing into shared state. A custom [collector](068-custom-collector.md) with a correct combiner is the safe version of "add to my list".

## Related

* [070 · Infinite Streams and Generators](070-infinite-streams.md), where the `sorted()` barrier turns into a hang
* [071 · Zipping Streams and Custom Spliterators](071-zip-and-spliterators.md), on `SIZED` and the other characteristics
* [068 · Writing Your Own Collector](068-custom-collector.md), for parallel aggregation without shared state
* [069 · Stream Gatherers: Custom Intermediate Operations](069-stream-gatherers.md), to write your own stateful stages properly

## Sources

* [`java.util.stream.Stream` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Stream.html), see `count()` and `peek()`
* [`java.util.stream` package summary (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/package-summary.html), the sections on laziness, non-interference, side effects and ordering
* [`Stream` Javadoc (Java 8)](https://docs.oracle.com/javase/8/docs/api/java/util/stream/Stream.html), for comparison: no `count()` note yet
* [`java.util.Spliterator` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Spliterator.html), for the `SIZED` characteristic
