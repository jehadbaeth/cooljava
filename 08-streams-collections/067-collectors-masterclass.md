# 067 · Collectors Masterclass

> `groupingBy` is a pivot table that fits in one line, as long as you know which downstream collector goes in the second slot.

**Since:** Java 16 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

"Count the books per genre, sorted by genre" is the kind of request that turns into this:

```java
Map<String, Long> counts = new TreeMap<>();
for (Book b : books) {
    Long old = counts.get(b.genre());
    counts.put(b.genre(), old == null ? 1L : old + 1);
}
```

Then someone asks for the best rated title per genre, then for all tags per genre without duplicates, then for both the longest book and the average rating, and the loop grows a second map, a third map and a flag. Every one of those questions is a *reduction*, and `java.util.stream.Collectors` already ships the pieces. The trick is knowing how they nest.

## The trick

Almost every interesting collector takes a **downstream collector**: a second collector that reduces each group (or each partition, or each mapped value) instead of dumping it into a `List`. You build a pipeline of reductions the same way you build a pipeline of stream operations:

```java
groupingBy(Book::genre,                 // 1. how to split
           TreeMap::new,                // 2. which map to build (sorted keys)
           collectingAndThen(           // 3. how to reduce each group
               maxBy(comparingDouble(Book::rating)),
               best -> best.orElseThrow().title()))
```

The catalogue of downstream pieces worth memorizing:

| Collector | Turns a group into | Since |
|---|---|---|
| `counting()` | a `Long` | 8 |
| `summingInt`, `averagingDouble`, `summarizingInt` | a number or a stats object | 8 |
| `mapping(f, down)` | the group with `f` applied first | 8 |
| `filtering(p, down)` | the group with non-matching elements dropped, **group kept** | 9 |
| `flatMapping(f, down)` | the group with each element expanded into many | 9 |
| `maxBy`, `minBy` | an `Optional` of the extreme element | 8 |
| `collectingAndThen(down, f)` | whatever `f` makes of the downstream result | 8 |
| `teeing(down1, down2, merger)` | two reductions in one pass, then merged | 12 |
| `joining(sep, prefix, suffix)` | a `String` | 8 |

The collectors themselves date from Java 8, 9 and 12. The example below uses records (and a local record), which is why the badge says 16.

## Full example

```java run
import java.util.*;
import java.util.stream.*;
import static java.util.Comparator.comparingDouble;
import static java.util.Comparator.comparingInt;
import static java.util.stream.Collectors.*;

public class CollectorsDemo {

    record Book(String title, String author, String genre, int year, int pages, double rating, List<String> tags) {}

    static final List<Book> BOOKS = List.of(
            new Book("Dune", "Herbert", "SciFi", 1965, 412, 4.3, List.of("desert", "politics")),
            new Book("Neuromancer", "Gibson", "SciFi", 1984, 271, 3.9, List.of("cyberpunk", "ai")),
            new Book("Foundation", "Asimov", "SciFi", 1951, 255, 4.2, List.of("empire", "math")),
            new Book("Caves of Steel", "Asimov", "SciFi", 1954, 270, 4.1, List.of("ai", "robots")),
            new Book("Emma", "Austen", "Classic", 1815, 474, 4.0, List.of("romance", "society")),
            new Book("Persuasion", "Austen", "Classic", 1817, 249, 4.1, List.of("romance")),
            new Book("Dracula", "Stoker", "Horror", 1897, 418, 4.0, List.of("vampires", "letters")),
            new Book("It", "King", "Horror", 1986, 1138, 4.2, List.of("clowns", "childhood")));

    static void show(String label, Object value) {
        System.out.printf("%-21s %s%n", label, value);
    }

    public static void main(String[] args) {
        // 1. Group, then reduce each group. The TreeMap supplier keeps the keys sorted.
        show("count by genre", BOOKS.stream()
                .collect(groupingBy(Book::genre, TreeMap::new, counting())));
        show("titles by genre", BOOKS.stream()
                .collect(groupingBy(Book::genre, TreeMap::new, mapping(Book::title, toList()))));

        // 2. filtering() inside the group keeps empty groups; filter() before grouping drops them.
        show("modern, filtering()", BOOKS.stream()
                .collect(groupingBy(Book::genre, TreeMap::new, filtering(b -> b.year() >= 1950, counting()))));
        show("modern, filter()", BOOKS.stream()
                .filter(b -> b.year() >= 1950)
                .collect(groupingBy(Book::genre, TreeMap::new, counting())));

        // 3. flatMapping: one book has many tags, each genre gets one sorted set.
        show("tags by genre", BOOKS.stream()
                .collect(groupingBy(Book::genre, TreeMap::new,
                        flatMapping(b -> b.tags().stream(), toCollection(TreeSet::new)))));

        // 4. Numeric downstreams.
        show("pages by genre", BOOKS.stream()
                .collect(groupingBy(Book::genre, TreeMap::new, summingInt(Book::pages))));
        show("avg rating by author", BOOKS.stream()
                .collect(groupingBy(Book::author, TreeMap::new, averagingDouble(Book::rating))));

        // 5. maxBy yields Optional<Book>; collectingAndThen unwraps it in the same pass.
        show("best by genre", BOOKS.stream()
                .collect(groupingBy(Book::genre, TreeMap::new,
                        collectingAndThen(maxBy(comparingDouble(Book::rating)), best -> best.orElseThrow().title()))));

        // 6. Two levels deep: genre, then author, then count.
        show("genre > author", BOOKS.stream()
                .collect(groupingBy(Book::genre, TreeMap::new, groupingBy(Book::author, TreeMap::new, counting()))));

        // 7. partitioningBy always has both keys, even when one side is empty.
        show("long reads", BOOKS.stream()
                .collect(partitioningBy(b -> b.pages() > 400, mapping(Book::title, toList()))));
        show("over 2000 pages", BOOKS.stream()
                .collect(partitioningBy(b -> b.pages() > 2000, counting())));

        // 8. toMap without a merge function throws on the first duplicate key.
        try {
            BOOKS.stream().collect(toMap(Book::author, Book::title));
        } catch (IllegalStateException e) {
            show("toMap duplicate", e.getMessage());
        }
        show("toMap with merge", BOOKS.stream()
                .collect(toMap(Book::author, Book::title, (a, b) -> a + " & " + b, TreeMap::new)));

        // 9. teeing: two unrelated aggregates in one pass, merged at the end.
        record Summary(String longest, double avgRating) {}
        show("teeing", BOOKS.stream()
                .collect(teeing(
                        maxBy(comparingInt(Book::pages)),
                        averagingDouble(Book::rating),
                        (longest, avg) -> new Summary(longest.orElseThrow().title(), avg))));

        // For plain numbers, summarizingInt already gives count, sum, min, average and max.
        show("year stats", BOOKS.stream().collect(summarizingInt(Book::year)));

        // 10. joining with a delimiter, a prefix and a suffix.
        show("by decade", BOOKS.stream()
                .sorted(comparingInt(Book::year))
                .collect(groupingBy(b -> b.year() / 10 * 10 + "s", TreeMap::new,
                        mapping(Book::title, joining(", ", "<", ">")))));
    }
}
```

Output:

```text output
count by genre        {Classic=2, Horror=2, SciFi=4}
titles by genre       {Classic=[Emma, Persuasion], Horror=[Dracula, It], SciFi=[Dune, Neuromancer, Foundation, Caves of Steel]}
modern, filtering()   {Classic=0, Horror=1, SciFi=4}
modern, filter()      {Horror=1, SciFi=4}
tags by genre         {Classic=[romance, society], Horror=[childhood, clowns, letters, vampires], SciFi=[ai, cyberpunk, desert, empire, math, politics, robots]}
pages by genre        {Classic=723, Horror=1556, SciFi=1208}
avg rating by author  {Asimov=4.15, Austen=4.05, Gibson=3.9, Herbert=4.3, King=4.2, Stoker=4.0}
best by genre         {Classic=Persuasion, Horror=It, SciFi=Dune}
genre > author        {Classic={Austen=2}, Horror={King=1, Stoker=1}, SciFi={Asimov=2, Gibson=1, Herbert=1}}
long reads            {false=[Neuromancer, Foundation, Caves of Steel, Persuasion], true=[Dune, Emma, Dracula, It]}
over 2000 pages       {false=8, true=0}
toMap duplicate       Duplicate key Asimov (attempted merging values Foundation and Caves of Steel)
toMap with merge      {Asimov=Foundation & Caves of Steel, Austen=Emma & Persuasion, Gibson=Neuromancer, Herbert=Dune, King=It, Stoker=Dracula}
teeing                Summary[longest=It, avgRating=4.1]
year stats            IntSummaryStatistics{count=8, sum=15369, min=1815, average=1921.125000, max=1986}
by decade             {1810s=<Emma, Persuasion>, 1890s=<Dracula>, 1950s=<Foundation, Caves of Steel>, 1960s=<Dune>, 1980s=<Neuromancer, It>}
```

## How it works

* **`groupingBy(classifier, mapFactory, downstream)`** creates one fresh downstream accumulator per key, feeds each element to the accumulator of its key, and finishes all of them at the end. The two-argument form uses a `HashMap`, whose iteration order you should never print or test against; the three-argument form lets you pass `TreeMap::new` (sorted) or `LinkedHashMap::new` (first-seen order). Note the argument order: the map factory sits *between* the classifier and the downstream.
* **`filtering` versus `filter`** is the most useful difference in the table. `filter` runs before grouping, so a genre with no modern books never becomes a key: `Classic` simply vanishes from the second "modern" line. `filtering` runs inside each group, so the key exists and its count is `0`. Reports usually want the zero.
* **`flatMapping`** is to `groupingBy` what `flatMap` is to a stream. Combined with `toCollection(TreeSet::new)` it deduplicates and sorts each genre's tags in the same pass.
* **`maxBy` returns `Optional`**, because a stream can be empty. Inside `groupingBy` a group is never empty (a key only exists because an element produced it), so `orElseThrow()` inside `collectingAndThen` is safe there and gives you a plain `String` per genre.
* **`partitioningBy`** is `groupingBy` specialized to a boolean, with one guarantee `groupingBy` does not give: both `false` and `true` are always present. "Over 2000 pages" proves it with `true=0`.
* **`toMap` without a merge function** throws `IllegalStateException` on a duplicate key, and the message names the key and both values. With a merge function and a map supplier it becomes a safe, sorted index. `toMap` is for *one value per key*; if you expect several, `groupingBy` is the honest choice.
* **`teeing`** (Java 12) sends every element to two downstream collectors and merges the results once at the end. It is the clean answer to "I need two unrelated aggregates but I only want to traverse once". For several statistics of one number, `summarizingInt` is shorter, as the `year stats` line shows.
* **`joining(", ", "<", ">")`** puts the prefix and suffix around the whole joined string, once per group here, not around each element.

## Gotchas

* **Null keys and null values.** `groupingBy` throws `NullPointerException` ("element cannot be mapped to a null key") if the classifier returns `null`. `toMap` throws if the *value* mapper returns `null`, even though `HashMap` allows null values. Map nulls to a sentinel or an `Optional` first.
* **`counting()` returns `Long`, `summingInt` returns `Integer`.** `Map<String, Integer> m = ...collect(groupingBy(g, counting()))` does not compile, which surprises people every time. Wrap with `collectingAndThen(counting(), Long::intValue)` if you really need `int`.
* **No promises about the default containers.** `toList()` and the default `groupingBy` map make no guarantee about type, mutability or thread safety. If you plan to modify the result, ask for it explicitly with `toCollection(ArrayList::new)` or a map supplier. (The `Stream.toList()` versus `Collectors.toList()` mutability trap lives in [062](../07-puzzlers/062-collections-traps.md).)
* **Sorting before grouping only helps with ordered containers.** The `by decade` line is in year order inside each group because the stream was sorted and `groupingBy` preserves encounter order within a group. It would not help the keys of a `HashMap`.
* **Deep nesting is a readability cliff.** Three levels of `groupingBy` with a `collectingAndThen` inside is correct and unreadable. Extract named collectors (`static Collector<Book, ?, String> bestTitle()`) once the line wraps twice.
* **Parallel streams and `groupingBy`.** Merging per-thread maps is expensive. If order does not matter, `groupingByConcurrent` uses one `ConcurrentMap` instead, but measure before believing it helps.

## When to use it (and when not to)

Use the built-in collectors for any "group, count, sum, pick the best" report over in-memory data. They are declarative, single-pass and much harder to get subtly wrong than a hand-written loop with `get`, `null` check and `put`. Start every non-trivial one with an explicit map supplier so the output is deterministic.

Do not use them as a database. If the data lives in SQL, `GROUP BY` there is faster and moves fewer bytes. And when no built-in fits (top N per group, streaming statistics, a histogram with fixed buckets), do not twist five collectors into a knot: [write your own](068-custom-collector.md), it takes twenty lines.

## Related

* [068 · Writing Your Own Collector](068-custom-collector.md), for the reductions that are not in the table
* [072 · Map Power Idioms: merge, compute and Friends](072-map-idioms.md), the imperative cousins of `groupingBy` and `toMap`
* [076 · Comparator Combinators](076-comparator-combinators.md), for the comparators inside `maxBy` and `sorted`
* [062 · Collection Traps](../07-puzzlers/062-collections-traps.md)

## Sources

* [`java.util.stream.Collectors` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Collectors.html)
* [`java.util.stream` package summary: Reduction operations](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/package-summary.html#Reduction)
* Brian Goetz, [State of the Lambda: Libraries Edition](https://cr.openjdk.org/~briangoetz/lambda/lambda-libraries-final.html), the design notes behind collectors and downstream composition
* Raoul-Gabriel Urma, [Processing Data with Java SE 8 Streams, Part 2](https://www.oracle.com/technical-resources/articles/java/architect-streams-pt2.html), on `collect` and grouping
