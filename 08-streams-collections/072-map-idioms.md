# 072 · Map Power Idioms: merge, compute and Friends

> Java 8 quietly added eleven default methods to `Map` that delete most `if (map.containsKey(k))` blocks ever written. Two of them disagree about what "absent" means.

**Since:** Java 9 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Beginner · **Verdict:** ✅ Production

## The problem

Every codebase has these three snippets, usually several times:

```java
// counting
Integer old = counts.get(word);
counts.put(word, old == null ? 1 : old + 1);

// grouping into a multimap
List<String> list = index.get(key);
if (list == null) {
    list = new ArrayList<>();
    index.put(key, list);
}
list.add(value);

// caching
if (!cache.containsKey(key)) cache.put(key, load(key));
return cache.get(key);
```

They are verbose, they look up the key two or three times, and on a `ConcurrentHashMap` every one of them is a race: two threads can both see "absent" and both write.

## The trick

Since Java 8, `Map` has default methods that do the read-modify-write in one call:

| Method | Does | Typical use |
|---|---|---|
| `merge(k, v, f)` | absent: put `v`; present: put `f(old, v)`; `null` result removes | counting, summing |
| `computeIfAbsent(k, f)` | absent: put `f(k)` and return it; present: return existing | multimaps, caches |
| `computeIfPresent(k, f)` | present: put `f(k, old)`; `null` removes | updating only existing entries |
| `compute(k, f)` | always put `f(k, oldOrNull)`; `null` removes | full control |
| `getOrDefault(k, d)` | the value, or `d` if the key is **not contained** | lookups with fallback |
| `putIfAbsent(k, v)` | put `v` if the key is absent **or mapped to null** | eager defaults |
| `replaceAll(f)` | replace every value with `f(k, v)` | bulk updates |

So the three snippets become three lines:

```java
counts.merge(word, 1, Integer::sum);
index.computeIfAbsent(key, k -> new ArrayList<>()).add(value);
return cache.computeIfAbsent(key, this::load);
```

On a `ConcurrentHashMap` these methods are atomic, which fixes the race too. The methods are Java 8; `Map.of`, `Map.entry` and `Map.ofEntries` (used below) arrived in Java 9 with JEP 269.

## Full example

```java run
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.LongAdder;

public class MapIdioms {

    static int expensiveCalls = 0;

    static String expensiveLookup(String key) {
        expensiveCalls++;
        return key.toUpperCase();
    }

    static long fib(Map<Integer, Long> memo, int n) {
        return memo.computeIfAbsent(n, k -> k < 2 ? (long) k : fib(memo, k - 1) + fib(memo, k - 2));
    }

    public static void main(String[] args) throws InterruptedException {
        String[] words = "to be or not to be that is the question".split(" ");

        // 1. Counting: merge inserts 1 for a new key, otherwise combines old and new with Integer::sum.
        Map<String, Integer> counts = new TreeMap<>();
        for (String w : words) counts.merge(w, 1, Integer::sum);
        System.out.println("counts:        " + counts);

        // 2. Multimap: computeIfAbsent returns the list that is now in the map, new or existing.
        Map<Integer, List<String>> byLength = new TreeMap<>();
        for (String w : new TreeSet<>(Arrays.asList(words))) {
            byLength.computeIfAbsent(w.length(), k -> new ArrayList<>()).add(w);
        }
        System.out.println("by length:     " + byLength);

        // 3. A remapping function that returns null removes the entry.
        Map<String, Integer> stock = new TreeMap<>(Map.of("apples", 3, "figs", 2, "pears", 1, "plums", 5));
        stock.compute("pears", (fruit, n) -> n == null || n <= 1 ? null : n - 1);          // sold the last pear
        stock.merge("apples", -3, (n, delta) -> n + delta == 0 ? null : n + delta);         // and all the apples
        stock.computeIfPresent("plums", (fruit, n) -> n * 2);
        stock.computeIfPresent("kiwis", (fruit, n) -> n * 2);                               // absent: nothing happens
        System.out.println("stock:         " + stock);

        // 4. Null values: getOrDefault says "present", putIfAbsent says "absent".
        Map<String, String> config = new HashMap<>();
        config.put("timeout", null);
        System.out.println("getOrDefault:  " + config.getOrDefault("timeout", "30s") + " (key present, value null)");
        System.out.println("containsKey:   " + config.containsKey("timeout"));
        config.putIfAbsent("timeout", "30s");
        System.out.println("putIfAbsent:   " + config.get("timeout") + " (null counted as absent)");

        // 5. putIfAbsent evaluates its argument every time; computeIfAbsent only when needed.
        Map<String, String> cache = new HashMap<>();
        cache.putIfAbsent("k", expensiveLookup("k"));
        cache.putIfAbsent("k", expensiveLookup("k"));
        System.out.println("putIfAbsent x2:     expensive calls = " + expensiveCalls);
        expensiveCalls = 0;
        cache.clear();
        cache.computeIfAbsent("k", MapIdioms::expensiveLookup);
        cache.computeIfAbsent("k", MapIdioms::expensiveLookup);
        System.out.println("computeIfAbsent x2: expensive calls = " + expensiveCalls);

        // 6. Bulk updates in place.
        Map<String, Double> prices = new TreeMap<>(Map.of("tea", 2.0, "cake", 3.5, "jam", 4.0));
        prices.replaceAll((item, price) -> price * 1.5);
        prices.entrySet().removeIf(e -> e.getValue() > 5.5);
        System.out.println("prices:        " + prices);

        // 7. Literals: Map.of up to 10 pairs, Map.ofEntries for any number. Both are immutable.
        Map<String, Integer> ports = Map.ofEntries(Map.entry("http", 80), Map.entry("https", 443), Map.entry("ssh", 22));
        System.out.println("ports:         " + new TreeMap<>(ports));
        try {
            Map.of("http", 80, "http", 8080);
        } catch (IllegalArgumentException e) {
            System.out.println("Map.of:        " + e.getMessage());
        }

        // 8. Concurrent counting: merge on ConcurrentHashMap is one atomic step per call.
        String[] pages = {"home", "docs", "blog"};
        Map<String, Long> hits = new ConcurrentHashMap<>();
        Map<String, LongAdder> adders = new ConcurrentHashMap<>();
        Thread[] workers = new Thread[8];
        for (int t = 0; t < workers.length; t++) {
            workers[t] = new Thread(() -> {
                for (int i = 0; i < 30_000; i++) {
                    String page = pages[i % pages.length];
                    hits.merge(page, 1L, Long::sum);
                    adders.computeIfAbsent(page, p -> new LongAdder()).increment();
                }
            });
            workers[t].start();
        }
        for (Thread w : workers) w.join();
        System.out.println("hits (merge):  " + new TreeMap<>(hits));
        Map<String, Long> adderTotals = new TreeMap<>();
        adders.forEach((page, adder) -> adderTotals.put(page, adder.sum()));
        System.out.println("hits (adder):  " + adderTotals);

        // 9. computeIfAbsent must not modify the same map. HashMap detects it since Java 9.
        try {
            System.out.println("fib(30) = " + fib(new HashMap<>(), 30));
        } catch (ConcurrentModificationException e) {
            System.out.println("recursive computeIfAbsent: " + e.getClass().getSimpleName());
        }
    }
}
```

Output:

```text output
counts:        {be=2, is=1, not=1, or=1, question=1, that=1, the=1, to=2}
by length:     {2=[be, is, or, to], 3=[not, the], 4=[that], 8=[question]}
stock:         {figs=2, plums=10}
getOrDefault:  null (key present, value null)
containsKey:   true
putIfAbsent:   30s (null counted as absent)
putIfAbsent x2:     expensive calls = 2
computeIfAbsent x2: expensive calls = 1
prices:        {cake=5.25, tea=3.0}
ports:         {http=80, https=443, ssh=22}
Map.of:        duplicate key: http
hits (merge):  {blog=80000, docs=80000, home=80000}
hits (adder):  {blog=80000, docs=80000, home=80000}
recursive computeIfAbsent: ConcurrentModificationException
```

## How it works

* **`merge(k, 1, Integer::sum)`** is the canonical counter. For a new key it stores `1` without calling the function; for an existing key it stores `sum(old, 1)`. One lookup, no `null` check, and it reads like the sentence "merge a 1 into this key's count".
* **`computeIfAbsent(...).add(v)`** works because it *returns the value now in the map*, freshly created or not. That return value is what makes the one-line multimap possible. (`putIfAbsent` returns the *previous* value, which is `null` exactly when it inserted, so the same trick with it NPEs on every first insert.)
* **Returning `null` deletes.** In `compute`, `computeIfPresent` and `merge`, a `null` result removes the entry. Selling the last pear and all three apples leaves `{figs=2, plums=10}`: no zero-count entries to filter later. `computeIfPresent` on the absent `kiwis` does nothing at all.
* **`replaceAll` and `entrySet().removeIf`** update a map in place without an explicit iterator. The price increase turns jam into 6.0, which the `removeIf` then drops.
* **`Map.ofEntries` and `Map.of`** build immutable maps, reject `null` keys and values, and reject duplicate keys at construction time with an `IllegalArgumentException` (`duplicate key: http`). Their iteration order is deliberately unspecified and varies between runs, which is why the example copies them into a `TreeMap` before printing.
* **Atomic counting.** Eight threads each add 30,000 hits spread over three pages, and both counters end at exactly 80,000 per page. On a `ConcurrentHashMap`, `merge` and `computeIfAbsent` are atomic per key. `LongAdder` is the high-contention variant: `computeIfAbsent` creates one adder per key once, then `increment()` spreads updates across internal cells instead of fighting over one value.

### The null trap

The `Map` interface defines "absent" in two different ways:

* `getOrDefault(k, d)` returns `d` only if the map **does not contain the key**. A key mapped to `null` is contained, so you get `null` back, not `"30s"`.
* `putIfAbsent`, `computeIfAbsent` and `merge` treat a key mapped to `null` **as absent**. `putIfAbsent("timeout", "30s")` happily overwrites the `null`.

Same map, same key, opposite answers. The fix is not cleverness but policy: do not store `null` values. `ConcurrentHashMap` and `Map.of` reject them anyway.

## Gotchas

* **`putIfAbsent` is eager.** Its argument is evaluated before the call, so `putIfAbsent(k, expensiveLookup(k))` runs the lookup every time, as the counter shows (2 calls versus 1). Use `computeIfAbsent` when the value is expensive or has side effects.
* **Do not modify the map inside the function.** The recursive Fibonacci memo calls `computeIfAbsent` from inside `computeIfAbsent`. `HashMap` detects that since Java 9 and throws `ConcurrentModificationException`; on Java 8 the same code could insert an entry that `get` then could not find (bug JDK-8071667, triggered by a resize during the nested call). `ConcurrentHashMap` is less predictable still. Its Javadoc says the function "must not modify this map" and documents an `IllegalStateException` for a recursive update it detects. In practice whether you hit it depends on which internal bins the keys land in:

  ```java
  fib(new ConcurrentHashMap<>(), 10);   // happens to work: 55
  fib(new ConcurrentHashMap<>(), 30);   // IllegalStateException: Recursive update
  ```

  Memoize recursive functions with an explicit `get`, compute, `put` sequence instead ([009](../01-functional/009-memoization.md)).
* **Keep functions short on `ConcurrentHashMap`.** The function runs while part of the map is locked, so other writers to the same bin wait. Never do I/O inside `compute`.
* **Check-then-act is still a race.** Atomic methods only help if you use them. This loses updates under contention even on a `ConcurrentHashMap`, because two atomic calls are not one atomic step:

  ```java
  Long old = hits.get(page);
  hits.put(page, old == null ? 1 : old + 1);
  ```

* **`merge` with a `null` value throws.** `map.merge(k, null, f)` is a `NullPointerException`; there is no way to "merge in nothing".

## When to use it (and when not to)

Always, for counting, grouping, caching and in-place updates on maps you own. They are shorter, faster (one hash lookup instead of two or three) and, on concurrent maps, correct. When the whole map is built from a stream in one go, `Collectors.groupingBy` and `toMap` ([067](067-collectors-masterclass.md)) are the declarative alternative.

Do not use `computeIfAbsent` as a production cache: it never evicts, never expires and, on `ConcurrentHashMap`, holds a lock while loading. That is what Caffeine is for. And do not build clever logic on top of `null` values; the two meanings of "absent" will eventually bite.

## Related

* [067 · Collectors Masterclass](067-collectors-masterclass.md), the stream-based way to build the same maps
* [009 · Memoization Done Right](../01-functional/009-memoization.md), including the recursive `computeIfAbsent` trap
* [074 · Sequenced Collections and a 10-Line LRU Cache](074-sequenced-collections-lru.md), for a cache that does evict
* [066 · The Element That Vanished from the HashSet](../07-puzzlers/066-vanishing-hashset.md), on what keys must never do

## Sources

* [`java.util.Map` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Map.html)
* [`ConcurrentHashMap.computeIfAbsent` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/ConcurrentHashMap.html#computeIfAbsent(K,java.util.function.Function))
* [JEP 269: Convenience Factory Methods for Collections](https://openjdk.org/jeps/269)
* [`java.util.concurrent.atomic.LongAdder` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/atomic/LongAdder.html)
