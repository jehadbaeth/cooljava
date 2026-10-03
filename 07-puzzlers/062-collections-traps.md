# 062 · Collection Traps

> `remove(1)` and `remove(Integer.valueOf(1))` do different things, a `Set<Short>` refuses to shrink, and `Arrays.asList` on an `int[]` gives you a list of exactly one thing. The Collections Framework is solid; its method signatures are where the bodies are buried.

**Since:** Java 16 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

Eighteen lines, every one of them ordinary collection code that compiles cleanly. Write down what each line prints (a value, or the name of the exception it throws) before you scroll. Lines 1 and 2 are the `SetList` example from Joshua Bloch's *Effective Java* (Item 52, "Use overloading judiciously"), and line 3 is "The Joy of Sets" from the *Java Puzzlers* talks that Bloch ran with Neal Gafter, Bill Pugh and others.

```java run
import java.util.*;
import java.util.concurrent.Callable;
import java.util.stream.*;

public class CollectionTraps {

    // Prints the value of the expression, or the simple name of the exception it throws.
    static void show(String label, Callable<?> expression) {
        Object result;
        try {
            result = expression.call();
        } catch (Exception e) {
            result = e.getClass().getSimpleName();
        }
        System.out.printf("%-44s %s%n", label, result);
    }

    public static void main(String[] args) {
        Set<Integer> set = new TreeSet<>();
        List<Integer> list = new ArrayList<>();
        for (int i = -3; i < 3; i++) {
            set.add(i);
            list.add(i);
        }
        for (int i = 0; i < 3; i++) {
            set.remove(i);
            list.remove(i);
        }
        show(" 1. set after remove(0), (1), (2)", () -> set);
        show(" 2. list after remove(0), (1), (2)", () -> list);

        Set<Short> shorts = new HashSet<>();
        for (short i = 0; i < 100; i++) {
            shorts.add(i);
            shorts.remove(i - 1);
        }
        show(" 3. shorts.size()", shorts::size);

        int[] primes = {2, 3, 5, 7};
        show(" 4. Arrays.asList(primes).size()", () -> Arrays.asList(primes).size());
        show(" 5. Arrays.asList(primes).contains(2)", () -> Arrays.asList(primes).contains(2));

        String[] planets = {"Mercury", "Venus", "Earth"};
        List<String> view = Arrays.asList(planets);
        show(" 6. view.set(0, \"Vulcan\"), then planets[0]", () -> { view.set(0, "Vulcan"); return planets[0]; });
        show(" 7. view.add(\"Mars\")", () -> view.add("Mars"));

        show(" 8. List.of(1, 2, 3).contains(null)", () -> List.of(1, 2, 3).contains(null));
        show(" 9. Arrays.asList(1, 2, 3).contains(null)", () -> Arrays.asList(1, 2, 3).contains(null));

        List<String> crew = new ArrayList<>(List.of("Ada", "Grace"));
        List<String> readOnly = Collections.unmodifiableList(crew);
        List<String> snapshot = List.copyOf(crew);
        crew.add("Linus");
        show("10. readOnly, after crew.add(\"Linus\")", () -> readOnly);
        show("11. snapshot, after crew.add(\"Linus\")", () -> snapshot);

        show("12. Stream.of(1, 2).toList().add(3)", () -> Stream.of(1, 2).toList().add(3));
        show("13. ...collect(Collectors.toList()).add(3)", () -> Stream.of(1, 2).collect(Collectors.toList()).add(3));
        show("14. Stream.of(\"a\", null).toList()", () -> Stream.of("a", null).toList());
        show("15. List.copyOf(Arrays.asList(\"a\", null))", () -> List.copyOf(Arrays.asList("a", null)));

        List<Integer> numbers = new ArrayList<>(List.of(1, 2, 3, 4, 5));
        List<Integer> middle = numbers.subList(1, 4);
        show("16. middle.set(0, 20), then numbers", () -> { middle.set(0, 20); return numbers; });
        show("17. middle.clear(), then numbers", () -> { middle.clear(); return numbers; });
        numbers.add(6);
        show("18. middle.size(), after numbers.add(6)", middle::size);
    }
}
```

Done guessing? Here is the real run.

## The answer

```text output
 1. set after remove(0), (1), (2)            [-3, -2, -1]
 2. list after remove(0), (1), (2)           [-2, 0, 2]
 3. shorts.size()                            100
 4. Arrays.asList(primes).size()             1
 5. Arrays.asList(primes).contains(2)        false
 6. view.set(0, "Vulcan"), then planets[0]   Vulcan
 7. view.add("Mars")                         UnsupportedOperationException
 8. List.of(1, 2, 3).contains(null)          NullPointerException
 9. Arrays.asList(1, 2, 3).contains(null)    false
10. readOnly, after crew.add("Linus")        [Ada, Grace, Linus]
11. snapshot, after crew.add("Linus")        [Ada, Grace]
12. Stream.of(1, 2).toList().add(3)          UnsupportedOperationException
13. ...collect(Collectors.toList()).add(3)   true
14. Stream.of("a", null).toList()            [a, null]
15. List.copyOf(Arrays.asList("a", null))    NullPointerException
16. middle.set(0, 20), then numbers          [1, 20, 3, 4, 5]
17. middle.clear(), then numbers             [1, 5]
18. middle.size(), after numbers.add(6)      ConcurrentModificationException
```

## Why

### Lines 1 and 2: two `remove` methods, one name

`Set<Integer>` has exactly one `remove`: `remove(Object)`. The loop variable boxes to an `Integer`, and the values 0, 1 and 2 leave the set. `List<Integer>` has *two*: `remove(Object)` and `remove(int index)`. Overload resolution tries methods that need no boxing first (see [061](061-boxing-overloading.md)), so `list.remove(i)` picks `remove(int index)`. It removes position 0 (leaving `[-2, -1, 0, 1, 2]`), then position 1 (the `-1`), then position 2 (the `1`). The survivors are every other element. Bloch's point in *Effective Java* is that generics and autoboxing damaged the `List` interface: before Java 5, `remove(Object)` and `remove(int)` took obviously different arguments, and afterwards a `List<Integer>` made them collide. The fix is to say what you mean: `list.remove(Integer.valueOf(i))` or `list.remove((Integer) i)`.

### Line 3: the set that never shrinks

`i` is a `short`, but `i - 1` is an `int`: Java never does arithmetic on anything narrower than `int`. So `shorts.remove(i - 1)` boxes to an `Integer`. A `Short` with value 4 and an `Integer` with value 4 are not `equals` (wrapper equality requires the same wrapper class), so not a single `remove` ever finds anything, and all 100 shorts stay in the set. The compiler is no help because `Collection.remove` takes an `Object`, not an `E`. That was deliberate: you can ask a `Set<Number>` to remove an `Integer`, and `contains`/`remove` on a value of the wrong type is legal and simply answers "not here". The fix is `shorts.remove((short) (i - 1))`.

### Lines 4 and 5: a list of one array

`Arrays.asList(T... a)` is a varargs method, and type variables only stand for reference types. An `int[]` cannot be a `T[]`, so the compiler treats the whole array as a *single* `T` and wraps it: the result is a `List<int[]>` of size 1. `contains(2)` boxes `2` to an `Integer` and compares it with the one element, which is an array, so the answer is `false`. With an `Integer[]` both lines would do what you expect. For primitives, use `IntStream.of(primes).boxed().toList()` or `Arrays.stream(primes)`.

### Lines 6 and 7: fixed size, write through

`Arrays.asList` does not copy. It returns a fixed-size list *backed by the array*, so `set` writes straight into `planets`, which now names a planet from Star Trek. Anything that would change the size (`add`, `remove`, `clear`) throws `UnsupportedOperationException`, because an array cannot grow. It is a view, not a container. Wrap it in `new ArrayList<>(...)` when you want an ordinary list.

### Lines 8 and 9: null hostility

The collections from `List.of`, `Set.of`, `Map.of` and `List.copyOf` reject `null` elements outright, and they go one step further: even *asking* whether they contain `null` throws a `NullPointerException`. The `Collection.contains` Javadoc allows that ("throws NullPointerException if the specified element is null and this collection does not permit null elements"), but almost no older collection does it, so code that probes with `contains(null)` breaks the day someone swaps an `Arrays.asList` for a `List.of`.

### Lines 10 and 11: unmodifiable is not immutable

`Collections.unmodifiableList` returns a read-only *view* of the original list. You cannot change the list through the view, but anyone holding the original can, and the view shows the change. `List.copyOf` takes a snapshot: later changes to `crew` do not show up. If you hand out a list from a getter and want it frozen, copy it.

### Lines 12 to 15: three kinds of "list from a stream"

`Stream.toList()` (Java 16) returns an unmodifiable list, so `add` throws. `Collectors.toList()` happens to return an `ArrayList` today, so `add` works, but its Javadoc makes "no guarantees on the type, mutability, serializability, or thread-safety" of the result. Code that mutates it relies on an implementation detail. Use `Collectors.toCollection(ArrayList::new)` if you need a mutable list. The third difference is `null`: `Stream.toList()` accepts null elements, while `List.copyOf` and `Collectors.toUnmodifiableList()` throw. All of them are called "unmodifiable", and they still disagree.

### Lines 16 to 18: `subList` is a window, and windows break

`subList(1, 4)` is a view of positions 1 to 3 of `numbers`. Writes go through (line 16), and so do structural changes made *through the view*: `middle.clear()` removes three elements from the parent, which is the idiomatic way to delete a range from a list. But a structural change to the parent that does not go through the view (`numbers.add(6)`) invalidates it, and the next use of `middle` throws `ConcurrentModificationException`, without a second thread in sight. [063](063-concurrent-modification.md) is all about that exception.

## Gotchas

* **`Set.of` and `Map.of` iteration order changes from run to run.** The immutable collections mix a per-JVM random salt into their iteration order, precisely so that nobody comes to depend on it. Tests that compare `Set.of(...).toString()` with a string are flaky by design.
* **`Map.of` and `Set.of` throw `IllegalArgumentException` on duplicates.** `Set.of("a", "a")` fails at run time, which surprises anyone used to `new HashSet<>(List.of("a", "a"))` quietly deduplicating.
* **`List.of(array)` with a `String[]`** uses the varargs overload and gives you a list of the strings, but `List.of(intArray)` gives you a `List<int[]>` of size 1, exactly like line 4.
* **`Collections.emptyList()`, `singletonList` and `nCopies` are unmodifiable too.** A method that returns `Collections.emptyList()` on one path and an `ArrayList` on another hands its callers a coin flip.
* **`TreeSet` and `TreeMap` use `compareTo`, not `equals`.** A case-insensitive comparator makes `"a"` and `"A"` the same element, which is the same story as `BigDecimal` in [058](058-floating-point.md).

## How to stay safe

* Never call `remove` on a `List<Integer>` without making the intent visible: `remove(int index)` or `remove(Integer.valueOf(x))`.
* Make the argument type of `contains` and `remove` match the element type exactly. IDE inspections and Error Prone's `CollectionIncompatibleType` check flag lines 3 and 5, and Error Prone's `ArraysAsListPrimitiveArray` catches line 4 at the source.
* Treat `Arrays.asList` as an *array adapter*, not as a list factory. For a fixed list of constants use `List.of`, for a mutable one `new ArrayList<>(List.of(...))`.
* Return `List.copyOf(field)` from getters, not `Collections.unmodifiableList(field)`, unless a live view is really what you want.
* Prefer `Stream.toList()` when the result should not change, and `Collectors.toCollection(ArrayList::new)` when it should. Do not mutate the result of `Collectors.toList()`.
* Keep `subList` views short-lived: use them in one statement (`list.subList(a, b).clear()`) and never store them in a field.

Most of these traps are as old as the Collections Framework (or as old as autoboxing). The example needs Java 16 only for `Stream.toList()`.

## Related

* [061 · Boxing and Overloading Traps](061-boxing-overloading.md), the overload rule behind lines 1 to 3
* [063 · ConcurrentModificationException and the One Case It Doesn't Fire](063-concurrent-modification.md)
* [066 · The Element That Vanished from the HashSet](066-vanishing-hashset.md)
* [074 · Sequenced Collections and a 10-Line LRU Cache](../08-streams-collections/074-sequenced-collections-lru.md)

## Sources

* [`java.util.List` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/List.html), section "Unmodifiable Lists"
* [`java.util.Arrays.asList` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Arrays.html#asList(T...))
* [`java.util.stream.Collectors.toList` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Collectors.html#toList())
* Bill Pugh, [Painful Java Puzzlers and Bug Patterns](http://www.cs.umd.edu/~pugh/DevIgnition-Painful-puzzlers.pdf) (DevIgnition 2012), which reproduces "The Joy of Sets"
* Joshua Bloch, *Effective Java*, 3rd edition (Addison-Wesley, 2018), Item 52: Use overloading judiciously
