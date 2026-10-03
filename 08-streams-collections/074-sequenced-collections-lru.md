# 074 · Sequenced Collections and a 10-Line LRU Cache

> For 25 years "give me the last element" was spelled differently for every collection, and for two of them the answer was a loop. Java 21 settled on `getLast()`, and the LRU cache that `LinkedHashMap` has hidden since Java 1.4 got a little friendlier too.

**Since:** Java 21 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Beginner · **Verdict:** ✅ Production

## The problem

Many collections have a well-defined order, but before Java 21 there was no common type for "ordered" and every class had its own vocabulary:

| Collection | First element | Last element |
|---|---|---|
| `List` | `list.get(0)` | `list.get(list.size() - 1)` |
| `Deque` | `deque.getFirst()` | `deque.getLast()` |
| `SortedSet` | `set.first()` | `set.last()` |
| `LinkedHashSet` | `set.iterator().next()` | iterate over everything |
| `LinkedHashMap` | `map.entrySet().iterator().next()` | iterate over everything |

Iterating backwards was worse: `ListIterator` for lists, `descendingIterator()` for deques, `descendingSet()` for sorted sets, and nothing at all for `LinkedHashSet` or `LinkedHashMap` short of copying them. A method that wanted "any ordered collection" as a parameter had to accept `Collection` and hope.

## The trick

[JEP 431](https://openjdk.org/jeps/431) (Stuart Marks, Java 21) retrofitted three interfaces into the collection hierarchy:

```java
interface SequencedCollection<E> extends Collection<E> {
    SequencedCollection<E> reversed();
    void addFirst(E e);   void addLast(E e);
    E getFirst();         E getLast();
    E removeFirst();      E removeLast();
}
interface SequencedSet<E> extends Set<E>, SequencedCollection<E> { SequencedSet<E> reversed(); }
interface SequencedMap<K, V> extends Map<K, V> {
    SequencedMap<K, V> reversed();
    Map.Entry<K, V> firstEntry();       Map.Entry<K, V> lastEntry();
    Map.Entry<K, V> pollFirstEntry();   Map.Entry<K, V> pollLastEntry();
    V putFirst(K k, V v);               V putLast(K k, V v);
    SequencedSet<K> sequencedKeySet();  // plus sequencedValues(), sequencedEntrySet()
}
```

`List` and `Deque` now extend `SequencedCollection`, `LinkedHashSet` and `SortedSet` are `SequencedSet`s, and `LinkedHashMap` and `SortedMap` are `SequencedMap`s. Almost all methods are defaults, so existing implementations got them for free.

The second half of the trick is older. `LinkedHashMap` can keep its entries in **access order** (most recently used last) and asks a protected hook, `removeEldestEntry`, after every insertion. Override the hook and you have a bounded LRU cache:

```java
class LruCache<K, V> extends LinkedHashMap<K, V> {
    private final int capacity;

    LruCache(int capacity) {
        super(16, 0.75f, true);              // true: access order, not insertion order
        this.capacity = capacity;
    }

    @Override protected boolean removeEldestEntry(Map.Entry<K, V> eldest) {
        return size() > capacity;
    }
}
```

Sequenced methods make it pleasant to inspect: `sequencedKeySet().getFirst()` is the next victim, `lastEntry()` the most recently used entry, `reversed()` the hot-first view.

## Full example

```java run
import java.util.*;

public class Sequenced {

    static class LruCache<K, V> extends LinkedHashMap<K, V> {
        private final int capacity;

        LruCache(int capacity) {
            super(16, 0.75f, true);              // true: access order, not insertion order
            this.capacity = capacity;
        }

        @Override protected boolean removeEldestEntry(Map.Entry<K, V> eldest) {
            return size() > capacity;
        }
    }

    /** Works for every ordered collection, which used to be impossible to type. */
    static String ends(SequencedCollection<?> c) {
        return c.getFirst() + " .. " + c.getLast() + "   reversed: " + c.reversed();
    }

    public static void main(String[] args) {
        // 1. One vocabulary for four very different classes.
        List<String> list = new ArrayList<>(List.of("b", "c"));
        list.addFirst("a");
        list.addLast("d");
        System.out.println("ArrayList      " + ends(list));
        System.out.println("ArrayDeque     " + ends(new ArrayDeque<>(List.of(1, 2, 3))));
        System.out.println("LinkedHashSet  " + ends(new LinkedHashSet<>(List.of("x", "y", "z"))));
        System.out.println("TreeSet        " + ends(new TreeSet<>(List.of(30, 10, 20))));

        // 2. reversed() is a live view, not a copy: writes go through to the original.
        List<Integer> numbers = new ArrayList<>(List.of(1, 2, 3));
        List<Integer> backwards = numbers.reversed();
        backwards.add(0);          // the end of the view is the front of the original
        backwards.set(0, 99);      // the front of the view is the end of the original
        System.out.println("view " + backwards + " original " + numbers);

        // 3. On a LinkedHashSet, addFirst and addLast move an element that is already there.
        SequencedSet<String> recent = new LinkedHashSet<>(List.of("x", "y", "z"));
        recent.addFirst("z");
        System.out.println("LinkedHashSet after addFirst(z): " + recent);

        // 4. LinkedHashMap as a SequencedMap.
        LinkedHashMap<String, Integer> scores = new LinkedHashMap<>();
        scores.put("ada", 3);
        scores.put("bob", 5);
        scores.putFirst("cy", 1);
        scores.putLast("ada", 4);   // existing key: new value, moved to the end
        System.out.println("scores " + scores + " first " + scores.firstEntry() + " last " + scores.lastEntry());
        System.out.println("keys reversed " + scores.sequencedKeySet().reversed() + ", polled " + scores.pollFirstEntry() + " -> " + scores);

        // 5. What cannot work, fails loudly.
        tryIt("TreeSet.addFirst(0)", () -> new TreeSet<>(List.of(1, 2)).addFirst(0));
        tryIt("List.of(1).removeFirst()", () -> List.of(1).removeFirst());
        tryIt("new ArrayList<>().getFirst()", () -> new ArrayList<Integer>().getFirst());
        tryIt("firstEntry().setValue(9)", () -> scores.firstEntry().setValue(9));

        // 6. The LRU cache: capacity 3, and every get counts as a use.
        LruCache<String, String> cache = new LruCache<>(3);
        cache.put("a", "alpha");
        cache.put("b", "beta");
        cache.put("c", "gamma");
        cache.get("a");                          // a is now the most recently used
        cache.put("d", "delta");                 // over capacity: evicts the eldest, b
        System.out.println("LRU " + cache.sequencedKeySet() + ", next victim " + cache.sequencedKeySet().getFirst()
                + ", hottest " + cache.lastEntry());
        cache.containsKey("c");                  // not an access: c stays the eldest
        cache.getOrDefault("c", "?");            // an access: c moves to the end
        System.out.println("after containsKey(c) then getOrDefault(c): " + cache.sequencedKeySet());

        // 7. Two traps. putFirst inserts at the eviction end, so the new entry evicts itself.
        cache.putFirst("e", "epsilon");
        System.out.println("after putFirst(e): " + cache.sequencedKeySet() + ", contains e? " + cache.containsKey("e"));

        // And in access order, get() is a structural modification.
        try {
            for (String key : cache.keySet()) {
                System.out.println("  reading " + key + " = " + cache.get(key));
            }
        } catch (ConcurrentModificationException e) {
            System.out.println("iterate and get: ConcurrentModificationException");
        }
    }

    static void tryIt(String label, Runnable action) {
        try {
            action.run();
            System.out.println(label + " worked");
        } catch (RuntimeException e) {
            System.out.printf("%-30s %s%n", label, e.getClass().getSimpleName());
        }
    }
}
```

Output:

```text output
ArrayList      a .. d   reversed: [d, c, b, a]
ArrayDeque     1 .. 3   reversed: [3, 2, 1]
LinkedHashSet  x .. z   reversed: [z, y, x]
TreeSet        10 .. 30   reversed: [30, 20, 10]
view [99, 2, 1, 0] original [0, 1, 2, 99]
LinkedHashSet after addFirst(z): [z, x, y]
scores {cy=1, bob=5, ada=4} first cy=1 last ada=4
keys reversed [ada, bob, cy], polled cy=1 -> {bob=5, ada=4}
TreeSet.addFirst(0)            UnsupportedOperationException
List.of(1).removeFirst()       UnsupportedOperationException
new ArrayList<>().getFirst()   NoSuchElementException
firstEntry().setValue(9)       UnsupportedOperationException
LRU [c, a, d], next victim c, hottest d=delta
after containsKey(c) then getOrDefault(c): [a, d, c]
after putFirst(e): [a, d, c], contains e? false
  reading a = alpha
iterate and get: ConcurrentModificationException
```

## How it works

* **Retrofitting by default methods.** `List.getFirst()` is a default that calls `get(0)` and throws `NoSuchElementException` when the list is empty; `List.reversed()` returns a view class that maps index `i` to `size() - 1 - i`. That is why every existing `List` implementation, including your own, gained the methods without recompiling.
* **`reversed()` returns views everywhere.** Adding to the end of the reversed list inserted `0` at the front of the original, and setting index 0 of the view overwrote the original's last element: `view [99, 2, 1, 0] original [0, 1, 2, 99]`. No copying, so `for (var x : list.reversed())` is free.
* **Positioning means different things for different types.** A `LinkedHashSet` keeps one copy of each element, so `addFirst("z")` *moves* `z` to the front. `LinkedHashMap.putFirst` and `putLast` do the same with keys. A `TreeSet` decides positions by comparison, so `addFirst` cannot be honored and throws `UnsupportedOperationException`, as does anything that would modify an immutable `List.of`.
* **`firstEntry()` returns a snapshot.** The entry is an immutable copy, so `setValue` throws instead of silently writing to the map. Use `put` or `replace` to change the value.
* **Access order is a single constructor flag.** With `accessOrder = true`, `get`, `getOrDefault`, `put`, `putIfAbsent`, `compute` and `merge` move the touched entry to the end. `containsKey` does not, which is why `c` stayed the eldest until `getOrDefault` touched it. After each insertion `LinkedHashMap` calls `removeEldestEntry(firstEntry)`; returning `true` deletes it. The `LinkedHashMap` Javadoc describes exactly this use, so it is not a hack but the intended extension point, available since Java 1.4.

### The two LRU traps in the output

* **`putFirst` evicts its own entry.** It inserts `e` at the front, which is the eviction end, then the size check removes the eldest entry, which is now `e`. The cache is unchanged and `e` is gone. In an LRU cache, only ever use `put`.
* **Reading while iterating throws.** In access order, `get` reorders the linked list, which counts as a structural modification, so the second step of the loop throws `ConcurrentModificationException`. Iterate over `entrySet()` and read `entry.getValue()`, which does not count as an access.

## Gotchas

* **Not thread-safe, not even for readers.** Since every `get` mutates the internal linked list, two threads that "only read" can corrupt it. `Collections.synchronizedMap(new LruCache<>(n))` is correct but serializes every access, and you still have to lock the map manually while iterating. Anything with real concurrency needs a purpose-built cache such as Caffeine.
* **`List` plus `Deque` no longer compiles.** `List.reversed()` returns a `List` and `Deque.reversed()` a `Deque`, so a type that is both must override `reversed()` with a type compatible with both. `LinkedList` got such an override in the JDK; your own code gets a compile error (see below). JEP 431 calls this out as its main source incompatibility.
* **`getFirst()` throws on empty collections.** `NoSuchElementException`, unlike `Deque.peekFirst()` which returns `null`. Check `isEmpty()` first when empty is a normal case.
* **Compiling on a newer JDK than you run on.** Kotlin's standard library has `removeFirst()` and `removeLast()` extension functions on mutable lists. Compiled against JDK 21, those calls resolve to the new Java member methods instead, and the program fails with `NoSuchMethodError` on an older runtime (older Android versions are the famous case). For Java code the cure is `--release N`, which makes javac reject APIs newer than the target.
* **Capacity is in entries, not bytes.** `size() > capacity` knows nothing about how large the values are. For memory-bounded caches, weigh entries, or again, use a library.

The compatibility trap, with the real javac error:

```java compile-fail
import java.util.*;

public class ListDeque {
    // Compiled fine for 25 years. Then Java 21 gave List and Deque each a reversed() method.
    interface Stack<E> extends List<E>, Deque<E> {}

    public static void main(String[] args) {
        System.out.println("never gets here");
    }
}
```

```text compile-error
ListDeque.java:5: error: types Deque<E> and List<E> are incompatible;
    interface Stack<E> extends List<E>, Deque<E> {}
    ^
  both define reversed(), but with unrelated return types
  where E is a type-variable:
    E extends Object declared in interface Stack
1 error
```

## When to use it (and when not to)

Use the sequenced methods everywhere: `getLast()` and `reversed()` are simply better spellings, and `SequencedCollection` is the right parameter type when your method needs order but not indexes. Library code that must run on Java 17 cannot, so it keeps the old idioms.

The `LinkedHashMap` LRU is perfect for single-threaded, in-process memoization with a hard size limit: parsers, template caches, per-request computations, tests. Do not use it as a shared application cache. It has no expiry, no statistics, no size-by-weight and no concurrency story beyond one big lock. That is where Caffeine (or Guava's `CacheBuilder` in older code) earns its dependency.

## Related

* [072 · Map Power Idioms: merge, compute and Friends](072-map-idioms.md), where `computeIfAbsent` makes a cache that never evicts
* [075 · NavigableMap Superpowers](075-navigable-map.md), the sorted relative of `SequencedMap`
* [063 · ConcurrentModificationException and the One Case It Doesn't Fire](../07-puzzlers/063-concurrent-modification.md)
* [009 · Memoization Done Right](../01-functional/009-memoization.md)

## Sources

* [JEP 431: Sequenced Collections](https://openjdk.org/jeps/431)
* [`java.util.SequencedCollection` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/SequencedCollection.html)
* [`java.util.LinkedHashMap` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/LinkedHashMap.html), including `removeEldestEntry` and access order
* [Caffeine](https://github.com/ben-manes/caffeine), the go-to concurrent cache for Java
