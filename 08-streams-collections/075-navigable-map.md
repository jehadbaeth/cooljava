# 075 · NavigableMap Superpowers

> `TreeMap.get` answers "what is stored at exactly this key?". Its sibling methods answer "what is the nearest key below or above this one?", and that one question covers IP lookups, price histories and the hash ring behind half the distributed caches on the planet.

**Since:** Java 16 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

A surprising number of lookups are not "find this key" but "find the entry this key falls into":

* Which customer owns IP address `10.0.1.77`? The table stores ranges, not every address.
* What did the plan cost on 31 December 2025? Prices are stored when they change, not for every day.
* Which cache server is responsible for `user-4711`? The servers sit at points on a hash ring, keys fall between them.

The naive answers are a linear scan over a list of ranges, or a `HashMap` with one entry per possible key. The first is O(n) per lookup, the second does not fit in memory.

## The trick

`TreeMap` implements `NavigableMap` (Java 6), a sorted map with **neighbor queries**, all O(log n):

| Method | Returns |
|---|---|
| `floorEntry(k)` / `floorKey(k)` | greatest key `<= k` |
| `ceilingEntry(k)` / `ceilingKey(k)` | least key `>= k` |
| `lowerEntry(k)` / `higherEntry(k)` | strictly `<` and strictly `>` |
| `firstEntry()`, `lastEntry()`, `pollFirstEntry()` | the ends, optionally removing |
| `headMap(k, incl)`, `tailMap(k, incl)`, `subMap(lo, incl, hi, incl)` | **live views** of a key range |
| `descendingMap()` | a live view in reverse order |

Store each range under its **start**, and "which range contains `x`?" becomes `floorEntry(x)`. A tax table is the classic one-liner:

```java
NavigableMap<Integer, Integer> marginalRate = new TreeMap<>(Map.of(0, 0, 12_000, 20, 50_000, 40, 150_000, 45));
int rate = marginalRate.floorEntry(64_000).getValue();   // 40
```

Put servers on a ring of hash values, and "who owns this key?" becomes `ceilingEntry(hash(key))`, wrapping around to `firstEntry()` past the top. That is consistent hashing, from the 1997 paper by Karger and others that Akamai was built on.

## Full example

```java run
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.util.*;
import java.util.stream.IntStream;

public class Navigable {

    // 1. Ranges with gaps: key = first address of the range, value = the whole range.
    record IpRange(long first, long last, String owner) {}

    static long ip(String dotted) {
        long value = 0;
        for (String part : dotted.split("\\.")) value = value * 256 + Integer.parseInt(part);
        return value;
    }

    static final NavigableMap<Long, IpRange> RANGES = new TreeMap<>();

    static void assign(String first, String last, String owner) {
        RANGES.put(ip(first), new IpRange(ip(first), ip(last), owner));
    }

    static String ownerOf(String address) {
        long value = ip(address);
        Map.Entry<Long, IpRange> candidate = RANGES.floorEntry(value);    // last range starting at or before it
        if (candidate == null || value > candidate.getValue().last()) return "(unassigned)";
        return candidate.getValue().owner();
    }

    // 2. Consistent hashing: servers sit at many points ("virtual nodes") on a ring of int hashes.
    static final class HashRing {
        private final NavigableMap<Integer, String> ring = new TreeMap<>();
        private final int virtualNodes;

        HashRing(int virtualNodes, String... servers) {
            this.virtualNodes = virtualNodes;
            for (String server : servers) add(server);
        }

        void add(String server) {
            for (int i = 0; i < virtualNodes; i++) ring.put(hash(server + "#" + i), server);
        }

        String serverFor(String key) {
            Map.Entry<Integer, String> owner = ring.ceilingEntry(hash(key));
            return (owner != null ? owner : ring.firstEntry()).getValue();    // past the top: wrap around
        }
    }

    /** First four bytes of MD5: stable across runs and JVMs, and well mixed. */
    static int hash(String s) {
        try {
            byte[] d = MessageDigest.getInstance("MD5").digest(s.getBytes(StandardCharsets.UTF_8));
            return (d[0] & 0xff) << 24 | (d[1] & 0xff) << 16 | (d[2] & 0xff) << 8 | (d[3] & 0xff);
        } catch (NoSuchAlgorithmException e) {
            throw new AssertionError(e);
        }
    }

    static Map<String, Integer> load(HashRing ring, List<String> keys) {
        Map<String, Integer> counts = new TreeMap<>();
        for (String key : keys) counts.merge(ring.serverFor(key), 1, Integer::sum);
        return counts;
    }

    public static void main(String[] args) {
        assign("10.0.0.0", "10.0.0.255", "office");
        assign("10.0.1.0", "10.0.1.127", "lab");
        assign("192.168.0.0", "192.168.255.255", "home");
        for (String address : List.of("10.0.0.42", "10.0.1.77", "10.0.1.200", "8.8.8.8", "192.168.3.4")) {
            System.out.printf("%-12s -> %s%n", address, ownerOf(address));
        }

        // 3. A time series: the price is stored when it changes, queried for any day.
        NavigableMap<LocalDate, Double> price = new TreeMap<>();
        price.put(LocalDate.of(2024, 1, 1), 9.99);
        price.put(LocalDate.of(2025, 3, 1), 11.99);
        price.put(LocalDate.of(2026, 2, 15), 12.49);
        for (LocalDate day : List.of(LocalDate.of(2023, 6, 1), LocalDate.of(2025, 12, 31), LocalDate.of(2026, 2, 15))) {
            Map.Entry<LocalDate, Double> asOf = price.floorEntry(day);
            System.out.println("price on " + day + ": " + (asOf == null ? "not sold yet" : asOf.getValue()));
        }
        LocalDate probe = LocalDate.of(2025, 6, 1);
        System.out.println("around " + probe + ": lower " + price.lowerKey(probe) + ", higher " + price.higherKey(probe)
                + ", newest first " + price.descendingMap());

        // 4. Views are live, in both directions.
        NavigableMap<LocalDate, Double> recent = price.tailMap(LocalDate.of(2025, 1, 1), true);
        price.put(LocalDate.of(2026, 7, 1), 13.99);              // write to the map, read through the view
        System.out.println("recent view:  " + recent);
        price.headMap(LocalDate.of(2025, 1, 1), false).clear();  // retention: delete everything before 2025
        recent.pollLastEntry();                                  // write through the view, visible in the map
        System.out.println("whole map:    " + price);
        try {
            recent.put(LocalDate.of(2020, 1, 1), 1.0);
        } catch (IllegalArgumentException e) {
            System.out.println("put outside the view: IllegalArgumentException: " + e.getMessage());
        }

        // 5. Consistent hashing versus hash % n when a fourth server joins.
        List<String> keys = IntStream.range(0, 10_000).mapToObj(i -> "user-" + i).toList();
        System.out.println("1 point per server:    " + load(new HashRing(1, "cache-a", "cache-b", "cache-c"), keys));
        HashRing ring = new HashRing(200, "cache-a", "cache-b", "cache-c");
        System.out.println("200 points per server: " + load(ring, keys));

        Map<String, String> before = new HashMap<>();
        for (String key : keys) before.put(key, ring.serverFor(key));
        ring.add("cache-d");
        long movedOnRing = keys.stream().filter(k -> !ring.serverFor(k).equals(before.get(k))).count();
        long movedModulo = keys.stream().filter(k -> Math.floorMod(hash(k), 3) != Math.floorMod(hash(k), 4)).count();
        System.out.println("after adding cache-d:  " + load(ring, keys));
        System.out.println("keys that moved: ring " + movedOnRing + ", hash % n " + movedModulo + " (of " + keys.size() + ")");
    }
}
```

Output:

```text output
10.0.0.42    -> office
10.0.1.77    -> lab
10.0.1.200   -> (unassigned)
8.8.8.8      -> (unassigned)
192.168.3.4  -> home
price on 2023-06-01: not sold yet
price on 2025-12-31: 11.99
price on 2026-02-15: 12.49
around 2025-06-01: lower 2025-03-01, higher 2026-02-15, newest first {2026-02-15=12.49, 2025-03-01=11.99, 2024-01-01=9.99}
recent view:  {2025-03-01=11.99, 2026-02-15=12.49, 2026-07-01=13.99}
whole map:    {2025-03-01=11.99, 2026-02-15=12.49}
put outside the view: IllegalArgumentException: key out of range
1 point per server:    {cache-a=3122, cache-b=2250, cache-c=4628}
200 points per server: {cache-a=3287, cache-b=3642, cache-c=3071}
after adding cache-d:  {cache-a=2561, cache-b=2464, cache-c=2260, cache-d=2715}
keys that moved: ring 2715, hash % n 7461 (of 10000)
```

## How it works

* **Store ranges by their start, then check the end.** `floorEntry(x)` finds the last range that *starts* at or before `x`, which is the only range that can contain it. It does not know whether `x` is past that range's end, so the explicit `last()` check is what turns `10.0.1.200` (after the end of `lab`) and `8.8.8.8` (before every range, so `floorEntry` returns `null`) into `(unassigned)`. Forget it and gaps silently belong to their left neighbor.
* **"As of" queries are the same trick on a time axis.** `floorEntry(day)` returns the price that was in force on that day: the last change on or before it. A date before the first entry gets `null`, which is the honest answer. Event sourcing snapshots, configuration history and exchange rates all have this shape.
* **Views are windows, not copies.** `tailMap(2025-01-01, true)` stores no entries of its own; it is the base map plus bounds. The price added to the base map appears in the view, `headMap(...).clear()` deletes from the base map (a retention policy in one line), and `pollLastEntry()` on the view removed the July entry from the map. A write the view's bounds cannot hold is rejected with `IllegalArgumentException: key out of range`.
* **The ring.** Each server is hashed onto the int range several times (`cache-a#0`, `cache-a#1`, ...). A key belongs to the first server point at or after its own hash, and `ceilingEntry` finds it in O(log n). When nothing is above the key's hash, the search wraps around to `firstEntry()`, which closes the ring.
* **Why virtual nodes.** With one point per server, the arcs between three random points are wildly unequal, as the first load line shows. With 200 points each, the arcs average out and the load evens up.
* **Why consistent hashing at all.** When `cache-d` joins, it takes over slices of everyone's arc, so only the keys in those slices move: about a quarter, which is the minimum possible for going from three servers to four. With `hash % n`, a key stays put only if its hash leaves the same remainder modulo 3 and modulo 4, so about three quarters of all keys move, and for a cache that means three quarters of all lookups suddenly miss.

## Gotchas

* **`null` means "no neighbor", so check it.** `floorEntry`, `ceilingEntry`, `firstEntry` and friends return `null` at the edges. The `*Key` variants are worse for unboxing: `int k = map.floorKey(x)` throws a `NullPointerException` below the smallest key.
* **Inclusive or exclusive?** The one-argument `headMap(k)` excludes `k`, `tailMap(k)` includes it, and `subMap(a, b)` is half-open `[a, b)`. Use the four-argument `subMap(a, true, b, true)` overloads and say what you mean.
* **Virtual node collisions overwrite.** Two virtual nodes that hash to the same int make `ring.put` replace one server with another without a sound. Rare with 32 bits and a few thousand points, but real systems use 64-bit hashes or check `put`'s return value.
* **Overlapping ranges break the floor trick.** `floorEntry` finds one candidate. If ranges can overlap or nest (IP allocations often do), you need an interval tree or longest-prefix matching, not a `TreeMap`.
* **Keys must be immutable and the comparator consistent with `equals`.** A `TreeMap` uses only the comparator to identify keys: two keys that compare as equal are the same key, whatever `equals` says ([076](076-comparator-combinators.md)).
* **Not thread-safe.** For concurrent use, `ConcurrentSkipListMap` implements the same `NavigableMap` interface, including the live views, lock-free.

## When to use it (and when not to)

Whenever a lookup is about *nearest* rather than *exact*: ranges, schedules, histories, leaderboards, rate tables, rings. The API is from 2006 and has none of the sharp edges of newer additions; the badge says Java 16 only because the example uses records and `Stream.toList()`. Reach for a `TreeMap` before you write a binary search over a sorted list by hand.

It is the wrong tool for overlapping intervals, for very large datasets that do not fit in memory (use a database index, which is the same idea on disk) and for hot paths where a `HashMap`'s O(1) exact lookup is all you need. For production consistent hashing across a cluster, the ring above is the right mental model, but replication, weights and membership changes are why people use the implementation inside their cache or database client.

## Related

* [074 · Sequenced Collections and a 10-Line LRU Cache](074-sequenced-collections-lru.md), since every `NavigableMap` is also a `SequencedMap`
* [076 · Comparator Combinators](076-comparator-combinators.md), for building the comparator a `TreeMap` sorts by
* [025 · Event Sourcing in 60 Lines](../03-build-it-yourself/025-event-sourcing.md), where "state as of" queries come up naturally
* [056 · "Aa" Equals "BB" (in hashCode)](../06-hidden-corners/056-hashcode-collisions.md), on why a ring needs a well-mixed hash

## Sources

* [`java.util.NavigableMap` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/NavigableMap.html)
* [`java.util.TreeMap` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/TreeMap.html)
* David Karger et al., [Consistent Hashing and Random Trees](https://www.cs.princeton.edu/courses/archive/fall09/cos518/papers/chash.pdf) (STOC 1997)
* Tom White, [Consistent Hashing](https://tom-e-white.com/2007/11/consistent-hashing.html) (2007), a Java implementation with a `SortedMap` ring
