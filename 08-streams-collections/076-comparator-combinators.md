# 076 · Comparator Combinators

> A sort order should read like a sentence: by city, then oldest first, nulls last. It does, right up to the moment `.reversed()` makes the compiler forget what `p` is.

**Since:** Java 16 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

The hand-written comparator is a small machine for producing bugs:

```java
people.sort((a, b) -> {
    int byCity = a.city().compareTo(b.city());
    if (byCity != 0) return byCity;
    return b.age() - a.age();        // overflow waiting to happen
});                                  // and a NullPointerException if a city is null
```

Every key adds another `if`, every reversal means swapping `a` and `b` in exactly the right place, and nobody tests the nulls. Since Java 8 the same thing can be assembled from named parts.

## The trick

`Comparator` has a small kit of static and default methods that build bigger comparators out of smaller ones:

| Combinator | What it builds |
|---|---|
| `comparing(keyFn)` | order by a key, using the key's natural order |
| `comparing(keyFn, keyComparator)` | order by a key, using another comparator for the key |
| `comparingInt/Long/Double(keyFn)` | the same, without boxing the key |
| `thenComparing(...)`, `thenComparingInt(...)` | tie-breakers, tried in order |
| `reversed()` | the opposite order |
| `naturalOrder()`, `reverseOrder()` | `compareTo` and its opposite, as a `Comparator` |
| `nullsFirst(c)`, `nullsLast(c)` | wrap `c` so that `null` is allowed and sorts at one end |

Read a chain from left to right and it says what you mean:

```java
Comparator<Person> order = Comparator.comparing(Person::city)
        .thenComparing(Person::age, Comparator.reverseOrder())
        .thenComparing(Person::name, String.CASE_INSENSITIVE_ORDER);
```

## Full example

```java run
import java.util.*;
import java.util.stream.*;

public class Combinators {

    record Person(String name, String city, int age, String nickname) {}

    static final List<Person> PEOPLE = List.of(
            new Person("Linus", "Helsinki", 55, null),
            new Person("ada", "London", 36, "Countess"),
            new Person("Grace", "New York", 85, "Amazing Grace"),
            new Person("Alan", "London", 41, null),
            new Person("Barbara", "London", 36, "Bobbie"));

    static String sorted(Comparator<Person> order) {
        return PEOPLE.stream().sorted(order).map(p -> p.name()).collect(Collectors.joining(", "));
    }

    public static void main(String[] args) {
        // 1. A key, optionally with its own comparator for the key.
        System.out.println("natural:        " + sorted(Comparator.comparing(Person::name)));
        System.out.println("ignoring case:  " + sorted(Comparator.comparing(Person::name, String.CASE_INSENSITIVE_ORDER)));

        // 2. A chain. After the first link the receiver supplies the type, so plain lambdas are fine.
        Comparator<Person> chain = Comparator.comparing(Person::city)
                .thenComparing(Person::age, Comparator.reverseOrder())
                .thenComparing(p -> p.name(), String.CASE_INSENSITIVE_ORDER);
        System.out.println("city, age desc: " + sorted(chain));

        // reversed() flips the whole chain built so far, not just the last key.
        Comparator<Person> twoKeys = Comparator.comparing(Person::city).thenComparingInt(Person::age);
        System.out.println("city, age:      " + sorted(twoKeys));
        System.out.println("  reversed():   " + sorted(twoKeys.reversed()));

        // 3. Nulls. reversed() flips them too.
        Comparator<Person> nicknameNullsFirst =
                Comparator.comparing(Person::nickname, Comparator.nullsFirst(Comparator.naturalOrder()));
        System.out.println("nulls first:    " + sorted(nicknameNullsFirst.thenComparing(Person::name)));
        System.out.println("  reversed():   " + sorted(nicknameNullsFirst.reversed().thenComparing(Person::name)));

        // 4. The four ways to write "name, descending" that compile.
        Comparator<Person> viaMethodRef = Comparator.comparing(Person::name).reversed();
        Comparator<Person> viaTypedLambda = Comparator.comparing((Person p) -> p.name()).reversed();
        Comparator<Person> viaTypeWitness = Comparator.<Person, String>comparing(p -> p.name()).reversed();
        Comparator<Person> viaReverseOrder = Comparator.comparing(p -> p.name(), Comparator.reverseOrder());
        System.out.println("name desc:      " + sorted(viaMethodRef));
        System.out.println("all four agree: " + Stream.of(viaMethodRef, viaTypedLambda, viaTypeWitness, viaReverseOrder)
                .map(Combinators::sorted).distinct().count() + " distinct result");

        // 5. Never subtract to compare: the difference of two ints can overflow.
        Comparator<Integer> subtract = (a, b) -> a - b;
        List<Integer> numbers = Arrays.asList(-1, Integer.MAX_VALUE);
        System.out.println("MAX_VALUE - (-1) = " + (Integer.MAX_VALUE - -1));
        numbers.sort(subtract);
        System.out.println("sorted with a - b:            " + numbers);
        numbers.sort(Integer::compare);
        System.out.println("sorted with Integer::compare: " + numbers);

        // 6. A TreeSet decides equality with the comparator alone, so a lazy comparator drops elements.
        Set<Person> byCityOnly = new TreeSet<>(Comparator.comparing(Person::city));
        byCityOnly.addAll(PEOPLE);
        System.out.println("TreeSet by city only: " + byCityOnly.size() + " of " + PEOPLE.size()
                + " kept: " + byCityOnly.stream().map(Person::name).toList());
        Set<Person> withTieBreak = new TreeSet<>(Comparator.comparing(Person::city).thenComparing(Person::name));
        withTieBreak.addAll(PEOPLE);
        System.out.println("with a name tie-break: " + withTieBreak.size() + " of " + PEOPLE.size() + " kept");

        Set<String> names = new TreeSet<>(String.CASE_INSENSITIVE_ORDER);
        names.add("Ada");
        System.out.println("add(\"ADA\") returns " + names.add("ADA") + ", contains(\"aDa\") is " + names.contains("aDa")
                + ", but List.of(\"Ada\").contains(\"aDa\") is " + List.of("Ada").contains("aDa"));
    }
}
```

Output:

```text output
natural:        Alan, Barbara, Grace, Linus, ada
ignoring case:  ada, Alan, Barbara, Grace, Linus
city, age desc: Linus, Alan, ada, Barbara, Grace
city, age:      Linus, ada, Barbara, Alan, Grace
  reversed():   Grace, Alan, ada, Barbara, Linus
nulls first:    Alan, Linus, Grace, Barbara, ada
  reversed():   ada, Barbara, Grace, Alan, Linus
name desc:      ada, Linus, Grace, Barbara, Alan
all four agree: 1 distinct result
MAX_VALUE - (-1) = -2147483648
sorted with a - b:            [2147483647, -1]
sorted with Integer::compare: [-1, 2147483647]
TreeSet by city only: 3 of 5 kept: [Linus, ada, Grace]
with a name tie-break: 5 of 5 kept
add("ADA") returns false, contains("aDa") is true, but List.of("Ada").contains("aDa") is false
```

## The inference trap

Now the line everybody writes once. It looks equivalent to `viaMethodRef` above, with a lambda instead of a method reference:

```java compile-fail
import java.util.Comparator;

public class Trap {
    record Person(String name, int age) {}

    public static void main(String[] args) {
        Comparator<Person> byNameDesc = Comparator.comparing(p -> p.name()).reversed();
    }
}
```

```text compile-error
Trap.java:7: error: cannot find symbol
        Comparator<Person> byNameDesc = Comparator.comparing(p -> p.name()).reversed();
                                                                   ^
  symbol:   method name()
  location: variable p of type Object
Trap.java:7: error: incompatible types: Comparator<Object> cannot be converted to Comparator<Person>
        Comparator<Person> byNameDesc = Comparator.comparing(p -> p.name()).reversed();
                                                                                    ^
2 errors
```

Two errors for one mistake. The first is the root cause: `p` was inferred as an `Object`. The second is the consequence: the whole expression became a `Comparator<Object>`, which is not the `Comparator<Person>` it is assigned to.

## How it works

* **Why `p` is an `Object`.** `comparing` is generic: `<T, U extends Comparable<? super U>> Comparator<T> comparing(Function<? super T, ? extends U>)`. Java has to infer `T`. With `Comparator<Person> c = Comparator.comparing(p -> p.name())` the target type supplies `Person`. But in `comparing(...).reversed()` the `comparing(...)` call is only the *receiver* of another call. A receiver has no target type, so inference has nothing to go on except the lambda, and an implicitly typed lambda `p -> ...` is not allowed to contribute (its body cannot be examined until its parameter types are known). `T` falls back to `Object`, and `Object` has no `name()`.
* **Why the method reference works.** `Person::name` is an *exact* method reference: there is one method called `name`, it is not generic and not varargs. Exact references take part in inference ([JLS 15.12.2.2](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.12.2.2)), so `T` is found from `Person::name` itself.
* **The other cures** are all in the example: give the lambda parameter a type (`(Person p) -> p.name()`, an *explicitly* typed lambda does take part), spell the type arguments out (`Comparator.<Person, String>comparing(...)`), or avoid `reversed()` by passing the reversed key comparator in directly. The last one is arguably the cleanest, because it also lets you reverse a single key inside a longer chain.
* **Only the first link has this problem.** In `chain`, `.thenComparing(p -> p.name(), ...)` compiles because the receiver is already a `Comparator<Person>`, which fixes `T`.
* **`reversed()` reverses everything before it.** It is a method on the comparator built so far, so `city, age` becomes `city desc, age desc` (compare the two lines in the output). To reverse one key, reverse that key's comparator: `thenComparing(Person::age, Comparator.reverseOrder())`.
* **Subtraction overflows.** `Integer.MAX_VALUE - -1` is `2147483648`, which does not fit in an `int` and wraps to `-2147483648`. The comparator then claims that the biggest int is smaller than `-1`. It works in every test that uses small numbers, which is the dangerous kind of wrong. See also [059](../07-puzzlers/059-integer-overflow.md).
* **The comparator defines identity in sorted collections.** `TreeSet` and `TreeMap` never call `equals`. Two elements are "the same" when `compare` returns `0`, so a comparator that looks only at the city keeps one person per city and silently ignores the rest. The `Comparable` and `Comparator` Javadocs call this being *consistent with equals*, and it is only a recommendation. A tie-breaker on a unique field restores it.

## Gotchas

* **The key extractor runs on every comparison, twice.** Sorting `n` items does about `n log n` comparisons, so an extractor that parses a date or hits a map is paid for a lot. If the key is expensive, compute it once per element (a record holding element and key, sorted, then unwrapped).
* **`comparing(Person::age)` boxes.** The `int` becomes an `Integer` before it is compared. The JIT may remove the allocation, but you cannot count on it, so use `comparingInt` and `thenComparingInt` for primitive keys. The result is the same, only cheaper.
* **`reversed()` flips `nullsFirst` into nulls last.** The `reversed()` line under `nulls first` in the output shows it: the two `null` nicknames moved to the end. If you want a particular null placement together with a particular order, wrap last: `nullsLast(Comparator.<String>naturalOrder().reversed())`.
* **`naturalOrder()` needs `Comparable`.** For `String`, mind that natural order is by UTF-16 code unit, so `"Z"` sorts before `"a"`. Use `String.CASE_INSENSITIVE_ORDER`, or a `java.text.Collator` for human-facing text in a given locale.
* **Sorts are stable** (`List.sort` and `Stream.sorted` on ordered streams), so ties keep their original order. That is why `ada` stays ahead of `Barbara` for the equal age of 36, and it is a legitimate way to sort in several passes.
* **A comparator that breaks its contract** (not antisymmetric, not transitive) can make `List.sort` throw `IllegalArgumentException: Comparison method violates its general contract!`, but only for lists big enough to reach the merge phase of TimSort. Smaller lists just give wrong answers, quietly, as the subtraction example shows.

## When to use it (and when not to)

Always, instead of hand-written `compare` methods. A combinator chain is shorter, has no off-by-one reversal and handles nulls in one visible place. Name the chain once (`static final Comparator<Person> BY_CITY_THEN_AGE = ...`) and reuse it, especially in `TreeMap`s, where the comparator is part of the data structure's meaning.

Skip the chain for a one-off sort of ints or strings (`Collections.sort(list)` and `list.sort(null)` are fine), and write a real `compare` method for hot paths where profiling shows the extractor calls matter. For ordering that is part of a type's identity, implement `Comparable` once and keep it consistent with `equals`.

## Related

* [075 · NavigableMap Superpowers](075-navigable-map.md), whose `TreeMap` is only as good as its comparator
* [059 · Integer Overflow and Arithmetic Surprises](../07-puzzlers/059-integer-overflow.md), for the `a - b` family of bugs
* [062 · Collection Traps](../07-puzzlers/062-collections-traps.md), where `TreeSet` and `compareTo` also bite
* [067 · Collectors Masterclass](067-collectors-masterclass.md), for `maxBy`, `minBy` and sorted grouping

## Sources

* [`java.util.Comparator` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Comparator.html)
* [`java.lang.Comparable` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Comparable.html), on consistency with `equals`
* [JLS 15.12.2.2: Phase 1, Identify Matching Arity Methods Applicable by Strict Invocation](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.12.2.2), which defines which arguments take part in inference
* [JLS 15.13.1: Compile-Time Declaration of a Method Reference](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.13.1), for *exact* method references
