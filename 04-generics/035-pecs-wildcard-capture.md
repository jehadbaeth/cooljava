# 035 · PECS and Wildcard Capture

> `List<Integer>` is not a `List<Number>`, `LocalDate` is not a `Comparable<LocalDate>`, and `Collections.max` starts with `Object &` for a reason that predates both. Four letters and one helper method sort it all out.

**Since:** Java 10 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Generics are invariant: a `List<Integer>` is not a `List<Number>`, even though every `Integer` is a `Number`. That is correct (otherwise you could add a `Double` to a list of integers through the back door), but it makes the obvious signatures far too strict. Here are two utility methods that look perfectly reasonable:

```java compile-fail
import java.time.LocalDate;
import java.util.*;

public class NaiveSignatures {
    static <T> void copy(List<T> dst, List<T> src) {
        dst.addAll(src);
    }

    static <T extends Comparable<T>> T max(Collection<T> items) {
        T best = null;
        for (T item : items) {
            if (best == null || item.compareTo(best) > 0) best = item;
        }
        return best;
    }

    public static void main(String[] args) {
        List<Number> numbers = new ArrayList<>();
        List<Integer> ints = List.of(1, 2, 3);
        copy(numbers, ints);

        List<LocalDate> launches = List.of(LocalDate.of(1957, 10, 4), LocalDate.of(1969, 7, 16));
        System.out.println(max(launches));
    }
}
```

```text compile-error
NaiveSignatures.java:20: error: method copy in class NaiveSignatures cannot be applied to given types;
        copy(numbers, ints);
        ^
  required: List<T>,List<T>
  found:    List<Number>,List<Integer>
  reason: inference variable T has incompatible equality constraints Integer,Number
  where T is a type-variable:
    T extends Object declared in method <T>copy(List<T>,List<T>)
NaiveSignatures.java:23: error: method max in class NaiveSignatures cannot be applied to given types;
        System.out.println(max(launches));
                           ^
  required: Collection<T>
  found:    List<LocalDate>
  reason: inference variable T has incompatible equality constraints ChronoLocalDate,LocalDate
  where T is a type-variable:
    T extends Comparable<T> declared in method <T>max(Collection<T>)
2 errors
```

The second error is the sneaky one. `LocalDate` does not implement `Comparable<LocalDate>`. It implements `ChronoLocalDate`, which extends `Comparable<ChronoLocalDate>`, so that dates from different calendar systems can be compared with each other. javac needs a single `T` that is both `LocalDate` (from the list) and `ChronoLocalDate` (from the `Comparable`), and there is none.

## The trick

**PECS: Producer `extends`, Consumer `super`.** Joshua Bloch coined the mnemonic in *Effective Java*; Maurice Naftalin and Philip Wadler call the same rule the Get and Put Principle. Ask of each parameter whether it hands `T`s to you or takes `T`s from you:

* a parameter you only **read** `T`s from is a producer: `List<? extends T>`,
* a parameter you only **write** `T`s into is a consumer: `List<? super T>`,
* a parameter you do both with stays `List<T>`.

So `copy` becomes `copy(List<? super T> dst, List<? extends T> src)`, which is exactly the signature of `Collections.copy`. And `Comparable` is always a consumer (it *takes* a `T` in `compareTo`), so the bound becomes `T extends Comparable<? super T>`: "`T` can be compared with something that is `T` or one of its supertypes". `LocalDate` qualifies through `Comparable<ChronoLocalDate>`.

The second half of the trick is for the opposite situation. A public method that takes `List<?>` has the friendliest possible signature, but inside it you cannot put anything back into the list. The fix is a private generic **capture helper**: calling `<T> helper(List<T>)` with a `List<?>` makes javac invent a name for the unknown type, and inside the helper that name is just `T`.

## Full example

```java run
import java.lang.reflect.Method;
import java.time.LocalDate;
import java.util.*;

public class PecsDemo {

    // src produces Ts (extends), dst consumes them (super).
    static <T> void copy(List<? super T> dst, List<? extends T> src) {
        for (T item : src) {
            dst.add(item);
        }
    }

    // Comparable is a consumer of T, so it gets "? super T".
    static <T extends Comparable<? super T>> T max(Collection<? extends T> items) {
        Iterator<? extends T> it = items.iterator();
        T best = it.next();
        while (it.hasNext()) {
            T next = it.next();
            if (next.compareTo(best) > 0) best = next;
        }
        return best;
    }

    // Same bounds, but Object comes first, exactly like Collections.max.
    static <T extends Object & Comparable<? super T>> T compatibleMax(Collection<? extends T> items) {
        return max(items);
    }

    // The public signature says "any list". The helper gives the unknown type a name.
    static void swap(List<?> list, int i, int j) {
        swapHelper(list, i, j);
    }

    private static <T> void swapHelper(List<T> list, int i, int j) {
        T first = list.get(i);
        list.set(i, list.get(j));
        list.set(j, first);
    }

    public static void main(String[] args) throws Exception {
        List<Integer> ints = List.of(3, 1, 2);
        List<Number> numbers = new ArrayList<>(List.of(0.5));
        List<Object> anything = new ArrayList<>(List.of("start"));
        copy(numbers, ints);
        copy(anything, ints);
        System.out.println("numbers  = " + numbers);
        System.out.println("anything = " + anything);

        // A Comparator<Number> is a perfectly good Comparator<? super Integer>.
        Comparator<Number> byValue = Comparator.comparingDouble(Number::doubleValue);
        var sorted = new ArrayList<>(ints);
        sorted.sort(byValue);
        System.out.println("sorted   = " + sorted);

        List<LocalDate> launches = List.of(
                LocalDate.of(1957, 10, 4), LocalDate.of(1969, 7, 16), LocalDate.of(1961, 4, 12));
        LocalDate latest = max(launches);
        System.out.println("latest   = " + latest);

        // Erasure replaces T with its leftmost bound, and that becomes the bytecode signature.
        describe(Collections.class.getMethod("max", Collection.class));
        describe(PecsDemo.class.getDeclaredMethod("max", Collection.class));
        describe(PecsDemo.class.getDeclaredMethod("compatibleMax", Collection.class));

        List<String> crew = new ArrayList<>(List.of("Gagarin", "Tereshkova", "Leonov"));
        swap(crew, 0, 2);
        Collections.swap(crew, 1, 2);
        System.out.println("swapped  = " + crew);
    }

    static void describe(Method m) {
        String name = m.getDeclaringClass().getSimpleName() + "." + m.getName();
        System.out.printf("%-26s returns %s in bytecode%n", name, m.getReturnType().getName());
    }
}
```

Output:

```text output
numbers  = [0.5, 3, 1, 2]
anything = [start, 3, 1, 2]
sorted   = [1, 2, 3]
latest   = 1969-07-16
Collections.max            returns java.lang.Object in bytecode
PecsDemo.max               returns java.lang.Comparable in bytecode
PecsDemo.compatibleMax     returns java.lang.Object in bytecode
swapped  = [Leonov, Gagarin, Tereshkova]
```

And here is the capture problem the helper solves. Without it, javac refuses the most innocent line imaginable:

```java compile-fail
import java.util.*;

public class NaiveSwap {
    static void swap(List<?> list, int i, int j) {
        list.set(i, list.get(j));
    }

    public static void main(String[] args) {
        swap(new ArrayList<>(List.of("a", "b")), 0, 1);
    }
}
```

```text compile-error
NaiveSwap.java:5: error: incompatible types: Object cannot be converted to CAP#1
        list.set(i, list.get(j));
                            ^
  where CAP#1 is a fresh type-variable:
    CAP#1 extends Object from capture of ?
Note: Some messages have been simplified; recompile with -Xdiags:verbose to get full output
1 error
```

## How it works

* **`? extends T` makes a list read-only for `T`s, `? super T` makes it write-only.** From a `List<? extends Number>` you can `get` a `Number`, but you cannot `add` anything except `null`, because the list might really be a `List<Double>`. Into a `List<? super Integer>` you can `add` an `Integer`, but `get` only promises `Object`. `copy` uses each list in exactly the direction its wildcard allows, which is why `T = Integer` works for a `List<Number>` and a `List<Object>` destination alike.
* **Comparators and comparables are always consumers.** `List<E>.sort` takes a `Comparator<? super E>`, so the `Comparator<Number>` sorts `Integer`s. Same story for `max`: with `Comparable<? super T>`, javac picks `T = LocalDate`, and the result is a `LocalDate`, not a vaguer `ChronoLocalDate`.
* **Capture conversion** (JLS §5.1.10) turns every *use* of an expression of type `List<?>` into `List<CAP#1>` for a fresh, nameless type `CAP#1`. In `list.set(i, list.get(j))` javac cannot prove that the value read from the list has the type the list accepts, so it rejects the call. Passing `list` to `swapHelper` captures the wildcard once and binds it to `T`, and inside the helper `get` and `set` agree. The JDK's own `Collections.swap` takes the other exit: its source assigns the list to a raw `List` under `@SuppressWarnings`, with a comment noting that capturing the wildcard would work too but "will require a call to a supplementary private method".
* **The `Object &` in `Collections.max` is about binary compatibility.** A type variable erases to its *leftmost* bound (the mechanics are in [034](034-intersection-types.md)). `PecsDemo.max` therefore erases to a method returning `Comparable`. Before Java 5, `Collections.max(Collection)` returned `Object`, and every class compiled against it calls a method with the descriptor `(Ljava/util/Collection;)Ljava/lang/Object;`. Had the generified version erased to `Comparable`, all that old bytecode would have died with `NoSuchMethodError`. Putting `Object` first keeps the old erasure while the second bound still lets the body call `compareTo`. The output shows the effect: `Collections.max` and `compatibleMax` return `Object` in bytecode, the version without `Object &` returns `Comparable`.

## Gotchas

* **Never put wildcards in return types.** A method returning `List<? extends Number>` forces every caller to deal with a capture they did not ask for. Wildcards belong on parameters, where they make the method accept more; return the most specific type you can.
* **Every mention is captured separately.** Two reads of the same `List<?>` variable produce two unrelated captures, which is why even `list.set(i, list.get(j))` fails. Storing the value in a local does not help either (an `Object` still is not a `CAP#1`); the helper is the fix.
* **`List<?>` is not raw `List`.** `List<?>` is a type-safe "list of something"; raw `List` switches the checks off, which is why the JDK needs `@SuppressWarnings` for its shortcut in `swap`.
* **The problem hides behind inference.** `copy(numbers, List.of(1, 2, 3))` compiles even with the naive signature, because javac simply builds a `List<Number>` for you. The error shows up only once the list already has a type of its own, which in real code is almost always.
* **Not everything needs a wildcard.** If a parameter is both read from and written to (`sort(List<T>)`, a `Map<K, V>` you update), it must stay exact. PECS applies per parameter, per direction.

## When to use it (and when not to)

Use PECS on every parameter of a public or library API that is only read or only written: it costs nothing at runtime and saves callers from copying lists just to satisfy the compiler. The JDK follows it religiously (`Collections.copy`, `addAll(Collection<? super T>, T...)`, `Comparator.comparing(Function<? super T, ? extends U>)`). Use capture helpers whenever a `?` in a signature is friendlier than a type parameter the caller would never use. In private application code that only ever sees one concrete type, plain `List<Order>` is fine; add wildcards the first time a subtype gets rejected.

## Related

* [034 · Intersection Types: Casting to Two Types at Once](034-intersection-types.md), for how leftmost-bound erasure works
* [031 · Self-Bounded Generics for Inheritable Builders](031-self-bounded-generics.md), where `Comparable<T>` gets its self type
* [020 · A Type-Safe Event Bus in 50 Lines](../03-build-it-yourself/020-event-bus.md), whose handlers are `Consumer<? super E>`
* [039 · Type Erasure Puzzlers and Generic Arrays](039-erasure-and-arrays.md)

## Sources

* Joshua Bloch, *Effective Java*, 3rd edition (Addison-Wesley, 2018), [Item 31: Use bounded wildcards to increase API flexibility](https://www.informit.com/articles/article.aspx?p=2861454&seqNum=6), the origin of PECS
* The Java Tutorials, [Wildcard Capture and Helper Methods](https://docs.oracle.com/javase/tutorial/java/generics/capture.html) and [Guidelines for Wildcard Use](https://docs.oracle.com/javase/tutorial/java/generics/wildcardGuidelines.html)
* [JLS §5.1.10: Capture Conversion](https://docs.oracle.com/javase/specs/jls/se25/html/jls-5.html#jls-5.1.10)
* [`Collections.max` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Collections.html#max(java.util.Collection))
