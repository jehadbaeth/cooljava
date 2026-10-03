# 043 · Records Beyond POJOs

> A record is not a shorter way to write a JavaBean. It is a promise: these components, this equality, nothing else. Here is how to make the promise hold.

**Since:** Java 16 · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Most people meet records as "Lombok `@Value` without Lombok": `record Point(int x, int y) {}` and done. That is fine for points. It falls apart the moment a component needs a rule:

```java
record Team(String name, List<String> members) {}

var people = new ArrayList<>(List.of("ada", "linus"));
var team = new Team("kernel", people);
people.add("mallory");               // team.members() now has three entries
team.members().clear();              // and anyone can empty it
```

The record is "immutable" only in the sense that its fields are `final`. The list they point to is whatever the caller made it. Add an `int[]` component and even `equals` stops meaning what you think. Records give you a lot for free, but only if you use the hooks they offer.

## The trick

A record's canonical constructor is the single door every instance walks through, and the **compact constructor** lets you stand at that door without retyping the fields:

```java
record Team(String name, List<Email> members) {
    Team {
        members = List.copyOf(members);     // reassign the parameter, not the field
    }
}
```

The compact constructor runs *before* the implicit field assignments, so anything you do to the parameters (validate, normalize, copy) is what ends up in the fields. Around that, records support almost everything a class does: static factories, instance methods, interfaces, generics, and declarations local to a method. What they refuse is just as useful: no extra instance fields, no `extends`, no reassigning components.

## Full example

```java run
import java.util.*;
import java.util.stream.*;

public class RecordsDemo {

    // Compact constructor: validate and normalize the parameters; the fields are assigned afterwards.
    record Email(String value) {
        Email {
            Objects.requireNonNull(value, "email");
            value = value.strip().toLowerCase(Locale.ROOT);
            if (!value.matches("[^@\\s]+@[^@\\s]+\\.[a-z]+")) {
                throw new IllegalArgumentException("not an email: " + value);
            }
        }
    }

    // Defensive copy: the record owns an unmodifiable snapshot, not the caller's list.
    record Team(String name, List<Email> members) {
        Team {
            members = List.copyOf(members);
        }
    }

    // Static factories name the ways to build a value; the constructor keeps the invariant.
    record Range(int low, int high) {
        Range {
            if (low > high) throw new IllegalArgumentException(low + " > " + high);
        }
        static Range between(int a, int b) { return new Range(Math.min(a, b), Math.max(a, b)); }
        static Range single(int value) { return new Range(value, value); }
        boolean contains(int x) { return low <= x && x <= high; }
        int length() { return high - low + 1; }
    }

    // Records implement interfaces like any other class.
    record Version(int major, int minor, int patch) implements Comparable<Version> {
        private static final Comparator<Version> ORDER = Comparator.comparingInt(Version::major)
                .thenComparingInt(Version::minor)
                .thenComparingInt(Version::patch);

        static Version parse(String text) {
            String[] parts = text.split("\\.");
            return new Version(Integer.parseInt(parts[0]), Integer.parseInt(parts[1]), Integer.parseInt(parts[2]));
        }
        @Override public int compareTo(Version other) { return ORDER.compare(this, other); }
        @Override public String toString() { return major + "." + minor + "." + patch; }
    }

    // Generic records work as expected, including generic methods.
    record Pair<A, B>(A first, B second) {
        <C> Pair<A, C> withSecond(C value) { return new Pair<>(first, value); }
    }

    // Arrays are the trap: equals and hashCode use the array's identity.
    record Polygon(int[] xs) {}

    record SafePolygon(int[] xs) {
        SafePolygon { xs = xs.clone(); }
        @Override public int[] xs() { return xs.clone(); }
        @Override public boolean equals(Object o) { return o instanceof SafePolygon p && Arrays.equals(xs, p.xs); }
        @Override public int hashCode() { return Arrays.hashCode(xs); }
        @Override public String toString() { return "SafePolygon" + Arrays.toString(xs); }
    }

    public static void main(String[] args) {
        System.out.println(new Email("  Ada@Example.ORG "));
        try {
            new Email("ada at example dot org");
        } catch (IllegalArgumentException e) {
            System.out.println("rejected, " + e.getMessage());
        }

        var people = new ArrayList<>(List.of(new Email("ada@example.org"), new Email("linus@example.org")));
        var team = new Team("kernel", people);
        people.add(new Email("mallory@example.org"));
        System.out.println(team.members().size() + " members in the team, " + people.size() + " in the caller's list");
        try {
            team.members().clear();
        } catch (UnsupportedOperationException e) {
            System.out.println("team.members() is read-only");
        }

        Range range = Range.between(9, 3);
        System.out.println(range + " contains 5? " + range.contains(5) + ", length " + range.length()
                + "; single: " + Range.single(7));

        List<Version> versions = Stream.of("1.10.0", "1.2.3", "0.9.9", "1.2.10")
                .map(Version::parse)
                .sorted()
                .toList();
        System.out.println("sorted versions: " + versions);

        // A local record as a composite map key: equals and hashCode come for free.
        record Cell(int row, int col) {}
        Map<Cell, String> board = new HashMap<>();
        board.put(new Cell(0, 0), "X");
        board.put(new Cell(1, 1), "O");
        System.out.println("(1,1) holds " + board.get(new Cell(1, 1)) + ", (2,2) holds " + board.get(new Cell(2, 2)));

        // Local enums, interfaces and records name intermediate results where they are used.
        enum Grade { PASS, FAIL }
        interface Rater { Grade rate(int score); }
        record Scored(String name, int score) {}
        Rater rater = score -> score >= 50 ? Grade.PASS : Grade.FAIL;
        Map<Grade, List<String>> byGrade = Stream.of(new Scored("Ada", 91), new Scored("Bob", 42), new Scored("Cy", 77))
                .collect(Collectors.groupingBy(s -> rater.rate(s.score()), () -> new EnumMap<>(Grade.class),
                        Collectors.mapping(Scored::name, Collectors.toList())));
        System.out.println("grades: " + byGrade);

        Pair<String, Integer> answer = new Pair<>("answer", 42);
        Pair<String, Double> precise = answer.withSecond(42.0);
        System.out.println(answer + " and " + precise);

        int[] corners = {0, 4, 4, 0};
        var a = new Polygon(corners);
        var b = new Polygon(new int[] {0, 4, 4, 0});
        System.out.println("Polygon equals? " + a.equals(b) + ", found in a set? " + new HashSet<>(List.of(a)).contains(b));
        corners[0] = 99;
        System.out.println("the 'immutable' Polygon now holds " + Arrays.toString(a.xs()));

        int[] safeCorners = {0, 4, 4, 0};
        var c = new SafePolygon(safeCorners);
        var d = new SafePolygon(new int[] {0, 4, 4, 0});
        safeCorners[0] = 99;
        System.out.println(c + " equals? " + c.equals(d) + ", found in a set? " + new HashSet<>(List.of(c)).contains(d));
    }
}
```

Output:

```text output
Email[value=ada@example.org]
rejected, not an email: ada at example dot org
2 members in the team, 3 in the caller's list
team.members() is read-only
Range[low=3, high=9] contains 5? true, length 7; single: Range[low=7, high=7]
sorted versions: [0.9.9, 1.2.3, 1.2.10, 1.10.0]
(1,1) holds O, (2,2) holds null
grades: {PASS=[Ada, Cy], FAIL=[Bob]}
Pair[first=answer, second=42] and Pair[first=answer, second=42.0]
Polygon equals? false, found in a set? false
the 'immutable' Polygon now holds [99, 4, 4, 0]
SafePolygon[0, 4, 4, 0] equals? true, found in a set? true
```

Now for the refusals. A record cannot carry hidden state:

```java compile-fail
public class HiddenState {
    record Counter(String name) {
        private int hits;
    }

    public static void main(String[] args) {
        System.out.println(new Counter("visits"));
    }
}
```

```text compile-error
HiddenState.java:3: error: field declaration must be static
        private int hits;
                    ^
  (consider replacing field with record component)
1 error
```

And its components are `final`, in methods and in the compact constructor alike:

```java compile-fail
public class FinalComponents {
    record Point(int x, int y) {
        Point moveRight() {
            x++;
            return this;
        }
    }

    record Email(String value) {
        Email {
            this.value = value.strip();
        }
    }

    public static void main(String[] args) {
        System.out.println(new Point(1, 2).moveRight() + " " + new Email(" e "));
    }
}
```

```text compile-error
FinalComponents.java:4: error: cannot assign a value to final variable x
            x++;
            ^
FinalComponents.java:11: error: cannot assign a value to final variable value
            this.value = value.strip();
                ^
2 errors
```

## How it works

* **Compact constructor = canonical constructor minus the boilerplate.** In `Email`, the line `value = value.strip().toLowerCase(Locale.ROOT)` reassigns the *parameter*; javac appends `this.value = value;` at the end. Writing `this.value = ...` yourself is an error, as the second compile-fail block shows, precisely so that the generated assignment stays the only one.
* **`List.copyOf` is the right defensive copy.** It returns an unmodifiable list, rejects `null` elements, and generally skips the copy when its argument is already an unmodifiable list, so copying twice costs nothing. The output shows both halves: the team kept 2 members while the caller's list grew to 3, and `clear()` threw.
* **Static factories** (`Range.between`, `Range.single`) give names to the ways of building a value and can normalize arguments before the constructor checks the invariant. `between(9, 3)` swapped the bounds; `new Range(9, 3)` would have thrown.
* **Interfaces and generics work as usual.** `Version` sorts numerically (`1.2.10` before `1.10.0`, which a string sort gets wrong) through a `Comparator` built from accessor references. `Pair<A, B>` is generic and has a generic method.
* **Local records, enums and interfaces** arrived together with records in Java 16. `Cell`, `Grade`, `Rater` and `Scored` live inside `main`, next to their only use. They are implicitly `static`, so they cannot capture local variables or `this`.
* **Records make great map keys.** `equals` and `hashCode` are derived from all components, so `new Cell(1, 1)` finds the entry stored under a different `new Cell(1, 1)`. No forgotten field in a hand-written `hashCode`.
* **Equality uses `Objects.equals` per component**, and for an array that means identity. Two `Polygon`s with the same coordinates are not equal, a `HashSet` cannot find one by the other, and mutating the caller's array changed the record. `SafePolygon` fixes all three by cloning on the way in and out and overriding `equals`, `hashCode` and `toString` with the `Arrays` versions. Usually the better fix is a `List<Integer>` component.

## Gotchas

* **No `extends`, ever.** Every record implicitly extends `java.lang.Record`. The grammar has no slot for an `extends` clause, so `record Point(int x, int y) extends Base {}` fails with a plain syntax error (`'{' expected`). Share behavior through interfaces with default methods.
* **Shallow immutability.** `final` fields do not freeze what they point to. Copy collections with `List.copyOf`/`Map.copyOf` and arrays with `clone()`, or the record is only as immutable as its least careful caller.
* **`toString` prints everything.** A `record Credentials(String user, String password)` logs the password. Override `toString` for anything sensitive.
* **Not JavaBeans.** Accessors are `name()`, not `getName()`. Libraries that only look for getters will not see the components; Jackson has supported records since 2.12 and most current frameworks do too, but older versions may not.
* **Serialization goes through the canonical constructor**, which is good news: a tampered byte stream cannot produce a `Range` with `low > high`, because deserialization calls the constructor and its checks run. That is a big improvement over classic serialization, which bypasses constructors entirely.

## When to use it (and when not to)

Use records for values: ids, money, ranges, coordinates, DTOs, query results, events, composite keys, and the cases of a sealed type. Put every invariant in the compact constructor so an invalid instance can never exist, and copy every mutable component.

Do not use them for entities whose identity outlives their state (a JPA `@Entity` needs a no-arg constructor and mutable fields), for types that need inheritance, or for objects whose fields must stay private. And if you find yourself overriding `equals`, `hashCode`, `toString` and the accessor, as `SafePolygon` does, ask whether a `List` component or a plain final class would be clearer.

## Related

* [014 · Withers: Painless Copies of Immutable Records](../02-patterns/014-record-withers.md)
* [040 · Algebraic Data Types with Sealed Interfaces and Records](040-algebraic-data-types.md)
* [066 · The Element That Vanished from the HashSet](../07-puzzlers/066-vanishing-hashset.md), on what broken `equals` and `hashCode` do to collections
* [076 · Comparator Combinators](../08-streams-collections/076-comparator-combinators.md)

## Sources

* [JEP 395: Records](https://openjdk.org/jeps/395)
* [JLS §8.10: Record Classes](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.10)
* [`java.lang.Record` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Record.html), for the exact `equals` contract
* Chris Hegarty and Alex Buckley, [Record Serialization](https://inside.java/2020/07/20/record-serialization/), Inside.java (2020)
