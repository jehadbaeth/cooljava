# 071 · Zipping Streams and Custom Spliterators

> Java streams cannot zip, so you write your own source. It turns out a `Spliterator` is just an iterator that knows how to cut itself in half.

**Since:** Java 16 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Advanced · **Verdict:** ✅ Production

## The problem

Three requests that the Stream API cannot satisfy out of the box:

* **Zip.** Pair `[1, 2, 3, ...]` with `["gold", "silver", "bronze"]`. Python has `zip`, Kotlin has `zip`, Java has nothing. A `zip` was in early Java 8 builds and was removed before the release; Guava's `Streams.zip` and a dozen blog posts filled the gap.
* **A lazy remote source.** A REST endpoint returns users 3 per page. You want `users().limit(4)` to make exactly two HTTP calls, not to download all pages into a `List` first.
* **A parallel-friendly custom source.** Something array-like that is not a `Collection`, where `parallel()` should actually split the work.

All three are the same problem: you need to write a stream *source*. Every stream is built on a `java.util.Spliterator`, and `StreamSupport.stream(spliterator, parallel)` turns any spliterator into a full `Stream`.

## The trick

A `Spliterator<T>` has four methods that matter:

| Method | Question it answers |
|---|---|
| `tryAdvance(action)` | "give me the next element, or say there is none" |
| `trySplit()` | "hand off a part of your elements to another thread, or return `null`" |
| `estimateSize()` | "roughly how many are left?" (`Long.MAX_VALUE` means "no idea") |
| `characteristics()` | flags like `ORDERED`, `SIZED`, `SUBSIZED`, `NONNULL`, `IMMUTABLE` |

There are two levels of effort:

1. **Sequential only.** Write an `Iterator` and wrap it: `Spliterators.spliteratorUnknownSize(iterator, ORDERED)`. That is all `zip` needs.
2. **Splittable.** Implement `Spliterator` directly and make `trySplit` carve off a piece. This is what makes `parallel()` worth anything.

```java
static <A, B, R> Stream<R> zip(Stream<A> as, Stream<B> bs, BiFunction<? super A, ? super B, ? extends R> f) {
    Iterator<A> ia = as.iterator();
    Iterator<B> ib = bs.iterator();
    Iterator<R> zipped = new Iterator<>() {
        public boolean hasNext() { return ia.hasNext() && ib.hasNext(); }
        public R next() { return f.apply(ia.next(), ib.next()); }
    };
    return StreamSupport.stream(Spliterators.spliteratorUnknownSize(zipped, Spliterator.ORDERED), false);
}
```

The spliterator API is Java 8. The example uses records and `Stream.toList()`, hence 16.

## Full example

```java run
import java.util.*;
import java.util.function.*;
import java.util.stream.*;

public class ZipAndSpliterators {

    // 1. zip for any two streams, even infinite ones: walk both iterators in lockstep.
    static <A, B, R> Stream<R> zip(Stream<A> as, Stream<B> bs, BiFunction<? super A, ? super B, ? extends R> f) {
        Iterator<A> ia = as.iterator();
        Iterator<B> ib = bs.iterator();
        Iterator<R> zipped = new Iterator<>() {
            public boolean hasNext() { return ia.hasNext() && ib.hasNext(); }
            public R next() { return f.apply(ia.next(), ib.next()); }
        };
        return StreamSupport.stream(Spliterators.spliteratorUnknownSize(zipped, Spliterator.ORDERED), false)
                .onClose(() -> { as.close(); bs.close(); });
    }

    // 2. zip for two random-access lists: an index stream is SIZED and splits well in parallel.
    static <A, B, R> Stream<R> zip(List<A> as, List<B> bs, BiFunction<? super A, ? super B, ? extends R> f) {
        return IntStream.range(0, Math.min(as.size(), bs.size())).mapToObj(i -> f.apply(as.get(i), bs.get(i)));
    }

    // 3. A lazy source over a paginated API: fetch the next page only when the buffer runs dry.
    record Page(List<String> items, boolean last) {}

    static Page fetchUsers(int page) {
        List<String> all = List.of("ada", "bob", "cy", "dee", "eve", "fay", "gus", "hal", "ivy", "jo");
        int from = Math.min(page * 3, all.size()), to = Math.min(from + 3, all.size());
        System.out.println("    fetching page " + page);   // stands in for GET /users?page=n
        return new Page(all.subList(from, to), to == all.size());
    }

    static final class PagedSpliterator implements Spliterator<String> {
        private int nextPage = 0;
        private boolean lastPageSeen = false;
        private Iterator<String> buffer = Collections.emptyIterator();

        @Override public boolean tryAdvance(Consumer<? super String> action) {
            while (!buffer.hasNext()) {
                if (lastPageSeen) return false;
                Page page = fetchUsers(nextPage++);
                lastPageSeen = page.last();
                buffer = page.items().iterator();
            }
            action.accept(buffer.next());
            return true;
        }
        @Override public Spliterator<String> trySplit() { return null; }      // pages come one after another
        @Override public long estimateSize() { return Long.MAX_VALUE; }      // "unknown"
        @Override public int characteristics() { return ORDERED | NONNULL; }
    }

    static Stream<String> users() { return StreamSupport.stream(new PagedSpliterator(), false); }

    // 4. A splittable source over part of an array. An ORDERED trySplit must hand off a prefix.
    static final class ArrayRange<T> implements Spliterator<T> {
        private final T[] array;
        private int from, to;
        private final boolean splitCorrectly;  // false: hand off the suffix instead, to show the damage
        int pulled;                            // elements delivered through tryAdvance

        ArrayRange(T[] array, int from, int to, boolean splitCorrectly) {
            this.array = array; this.from = from; this.to = to; this.splitCorrectly = splitCorrectly;
        }

        @Override public boolean tryAdvance(Consumer<? super T> action) {
            if (from >= to) return false;
            pulled++;
            action.accept(array[from++]);
            return true;
        }
        @Override public Spliterator<T> trySplit() {
            int mid = (from + to) >>> 1;
            if (mid - from < 4) return null;                  // too small to be worth splitting
            if (splitCorrectly) {
                var prefix = new ArrayRange<>(array, from, mid, true);
                from = mid;
                return prefix;
            }
            var suffix = new ArrayRange<>(array, mid, to, false);
            to = mid;
            return suffix;
        }
        @Override public long estimateSize() { return to - from; }
        @Override public int characteristics() { return ORDERED | SIZED | SUBSIZED | NONNULL | IMMUTABLE; }
        @Override public String toString() { return "[" + from + ", " + to + ")"; }
    }

    static <T> Stream<T> parallelOver(T[] array, boolean splitCorrectly) {
        return StreamSupport.stream(new ArrayRange<>(array, 0, array.length, splitCorrectly), true);
    }

    public static void main(String[] args) {
        Stream<Integer> naturals = Stream.iterate(1, n -> n + 1);
        System.out.println("zip streams: " + zip(naturals, Stream.of("gold", "silver", "bronze"),
                (n, medal) -> n + ". " + medal).toList());

        List<Double> prices = List.of(2.5, 1.0, 4.0);
        List<Integer> quantities = List.of(4, 10, 2, 99);
        System.out.println("zip lists:   " + zip(prices, quantities, (p, q) -> p * q).toList());
        System.out.println("dot product: " + zip(prices, quantities, (p, q) -> p * q).parallel()
                .mapToDouble(Double::doubleValue).sum());

        try (var closing = zip(Stream.of(1).onClose(() -> System.out.println("closed left")),
                               Stream.of(2).onClose(() -> System.out.println("closed right")), Integer::sum)) {
            System.out.println("zip and close: " + closing.toList());
        }

        System.out.println("first 4 users:");
        System.out.println("  -> " + users().limit(4).toList());
        System.out.println("first user starting with g:");
        System.out.println("  -> " + users().filter(u -> u.startsWith("g")).findFirst().orElseThrow());
        System.out.println("count all users:");
        System.out.println("  -> " + users().count());

        // Splitting by hand: each call carves the first half off the receiver.
        Integer[] sixteen = IntStream.range(0, 16).boxed().toArray(Integer[]::new);
        var rest = new ArrayRange<>(sixteen, 0, 16, true);
        var firstHalf = rest.trySplit();
        var firstQuarter = firstHalf.trySplit();
        System.out.println("split by hand: " + firstQuarter + " " + firstHalf + " " + rest
                + ", sizes " + firstQuarter.estimateSize() + " " + firstHalf.estimateSize() + " " + rest.estimateSize());

        Integer[] big = IntStream.range(0, 100_000).boxed().toArray(Integer[]::new);
        List<Integer> expected = Arrays.asList(big);
        List<Integer> good = parallelOver(big, true).toList();
        List<Integer> bad = parallelOver(big, false).toList();
        System.out.println("prefix split, order kept? " + good.equals(expected));
        System.out.println("suffix split, order kept? " + bad.equals(expected)
                + ", same elements? " + bad.stream().sorted().toList().equals(expected));
        System.out.println("parallel sum: " + parallelOver(big, true).mapToLong(Integer::longValue).sum());

        // SIZED lets count() answer from estimateSize() without pulling a single element.
        var counted = new ArrayRange<>(big, 0, big.length, true);
        System.out.println("count = " + StreamSupport.stream(counted, false).count() + ", elements pulled: " + counted.pulled);
    }
}
```

Output:

```text output
zip streams: [1. gold, 2. silver, 3. bronze]
zip lists:   [10.0, 10.0, 8.0]
dot product: 28.0
zip and close: [3]
closed left
closed right
first 4 users:
    fetching page 0
    fetching page 1
  -> [ada, bob, cy, dee]
first user starting with g:
    fetching page 0
    fetching page 1
    fetching page 2
  -> gus
count all users:
    fetching page 0
    fetching page 1
    fetching page 2
    fetching page 3
  -> 10
split by hand: [0, 4) [4, 8) [8, 16), sizes 4 4 8
prefix split, order kept? true
suffix split, order kept? false, same elements? true
parallel sum: 4999950000
count = 100000, elements pulled: 0
```

## How it works

### zip

* **Two iterators in lockstep.** `Stream.iterator()` is lazy: it pulls from the stream only when you call `next()`. So zipping an infinite stream of naturals with three medals produces three pairs and stops, because `hasNext()` is false as soon as *either* side runs out.
* **`spliteratorUnknownSize(iterator, ORDERED)`** adapts the iterator. "Unknown size" means `estimateSize()` reports `Long.MAX_VALUE` and no `SIZED` flag, which is honest: you cannot know how long a zip of two arbitrary streams will be.
* **`onClose` forwards closing.** Streams over files or sockets need closing. Without `onClose`, closing the zipped stream would leak both inputs. The try-with-resources block shows both handlers firing, in order, after the result is printed.
* **The list version is better when you can use it.** `IntStream.range` is `SIZED` and splits perfectly, so `zip(prices, quantities, ...)` runs fine in parallel. It stops at the shorter list (`99` is ignored), and the dot product is `2.5 × 4 + 1.0 × 10 + 4.0 × 2 = 28.0`.

### The paginated source

* **`tryAdvance` is the only method doing real work.** It serves elements from the current page and fetches the next page only when the buffer is empty. The output shows the effect: `limit(4)` needs four users, which live on pages 0 and 1, so exactly two requests go out. Finding the first user starting with `g` takes three pages. Only `count()` reads all four.
* **`trySplit` returns `null`.** Page `n + 1` comes after page `n`, so there is nothing to hand off. A `null` is always a legal answer; the stream simply stays single-threaded for this source.
* **`estimateSize` returns `Long.MAX_VALUE`** and the characteristics are only `ORDERED | NONNULL`. If the API returned a reliable total count, you could report `SIZED`, but only if the number is exact for the whole traversal. A wrong `SIZED` is worse than none, because `count()` and `toArray()` trust it.

### The splittable range

* **`trySplit` returns a prefix.** For an `ORDERED` spliterator, the Javadoc requires that the returned spliterator covers a *strict prefix* of the elements. The framework puts the returned half on the left of the result and the receiver on the right. The hand-split line shows the pattern: `[0, 16)` hands off `[0, 8)` and keeps `[8, 16)`; `[0, 8)` then hands off `[0, 4)`.
* **Violating that rule corrupts results silently.** The `splitCorrectly = false` variant hands off the suffix. In parallel, every element still arrives (`same elements? true`), but in the wrong order (`order kept? false`), and nothing throws. Sums, being order-insensitive, would still look right, which is exactly why this bug survives testing.
* **`SIZED | SUBSIZED`** says "my size is exact, and so are the sizes of all my splits". That lets the framework preallocate arrays for `toArray` and `toList` and write each chunk's results straight to its final position. It also lets `count()` return `estimateSize()` without traversing: `elements pulled: 0`.
* **Stop splitting early.** Each split costs an object and a task; the framework already stops when chunks get small, and `mid - from < 4` adds a floor of its own. Real implementations use a much larger threshold, like a few thousand elements.

## Gotchas

* **The iterator zip is sequential only.** `spliteratorUnknownSize` can split, but only by buffering batches of elements from the iterator into arrays, which rarely pays off. Do not expect `zip(...).parallel()` over two arbitrary streams to scale.
* **Consuming the inputs.** `as.iterator()` is a terminal operation on `as`. After calling `zip`, the input streams are used up, as with any terminal operation.
* **Do not lie in `characteristics()`.** `IMMUTABLE` and `CONCURRENT` promise how the source behaves under modification, `DISTINCT` and `SORTED` let operations skip work. A false flag makes `distinct()` or `sorted()` return wrong results without any error.
* **Late binding.** A spliterator over a mutable source should bind to it when traversal *starts*, not when the spliterator is created, and should fail fast (`ConcurrentModificationException`) on interference. The array range here sidesteps the question by declaring `IMMUTABLE`, which is only true because nobody writes to the array.
* **Java 24 gatherers can zip too**, as long as the second side is passed in as state: Gunnar Morling's zipping gatherer holds the second stream's iterator. It reads nicer in a pipeline but has the same sequential nature ([069](069-stream-gatherers.md)).

## When to use it (and when not to)

Write the iterator-based `zip` once in a utility class (or use Guava's `Streams.zip`) and stop worrying about it. Prefer the index-based version whenever both sides are random-access lists.

Write a custom `Spliterator` when your source is lazy and expensive (paginated APIs, database cursors, log files) or when you own an array-like structure and want real parallelism. For the lazy, sequential case, extending `Spliterators.AbstractSpliterator` and implementing only `tryAdvance` is even shorter. Do not write a splitting spliterator for a structure that is already a `Collection`: `ArrayList` and friends ship excellent ones.

## Related

* [069 · Stream Gatherers: Custom Intermediate Operations](069-stream-gatherers.md), the other extension point, in the middle of the pipeline
* [070 · Infinite Streams and Generators](070-infinite-streams.md), for infinite sources built with `iterate` and `generate`
* [073 · Stream Laziness Puzzlers](073-stream-laziness-puzzlers.md), including why `count()` skips work on `SIZED` sources
* [068 · Writing Your Own Collector](068-custom-collector.md), the terminal side of parallel splitting

## Sources

* [`java.util.Spliterator` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Spliterator.html), including the prefix rule for `trySplit`
* [`java.util.stream.StreamSupport` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/StreamSupport.html)
* Gunnar Morling, [A Zipping Gatherer](https://www.morling.dev/blog/zipping-gatherer/), on the history of the missing `zip`
* [Guava `Streams.zip`](https://guava.dev/releases/snapshot-jre/api/docs/com/google/common/collect/Streams.html)
