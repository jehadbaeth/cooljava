# 014 · Withers: Painless Copies of Immutable Records

> Records cannot change, so you copy them with one component swapped. Easy, until a chain of copies trips over your own validation halfway through.

**Since:** Java 16 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

A record is immutable, which is the point. But data still evolves: a booking gets another guest, moves to February, changes its name. Without help, every change repeats every component:

```java
var moved = new Booking(old.guest(), feb10, old.checkOut(), old.guests());
```

With four components this is merely tedious. With twelve it is a bug farm: swap two `LocalDate` arguments by accident and the compiler is perfectly happy.

## The trick

Write a **wither** per component: a method that returns a copy with exactly one component replaced. It is the immutable cousin of a setter:

```java
record Booking(String guest, LocalDate checkIn, LocalDate checkOut, int guests) {
    Booking withGuests(int n) { return new Booking(guest, checkIn, checkOut, n); }
}
```

Three refinements make withers safe in real code:

1. **Every wither goes through the canonical constructor**, so the compact constructor's validation runs on every copy. An invalid booking cannot be created by copying a valid one.
2. **Components that are validated together get one wither together.** If `checkOut` must be after `checkIn`, a chain `withCheckIn(...).withCheckOut(...)` can fail in the middle. A `withStay(in, out)` cannot.
3. **For many changes at once, use a builder made from the record** (`toBuilder()`): mutate freely, validate once in `build()`.

## Full example

```java run
import java.lang.reflect.*;
import java.time.LocalDate;
import java.util.*;

public class WitherDemo {

    record Booking(String guest, LocalDate checkIn, LocalDate checkOut, int guests) {
        static int constructed = 0;   // counts canonical constructor runs, for this demo only

        Booking {
            constructed++;
            Objects.requireNonNull(guest, "guest");
            if (!checkOut.isAfter(checkIn))
                throw new IllegalArgumentException("checkOut " + checkOut + " is not after checkIn " + checkIn);
            if (guests < 1 || guests > 4)
                throw new IllegalArgumentException("guests must be 1..4, was " + guests);
        }

        Booking withGuest(String g) { return new Booking(g, checkIn, checkOut, guests); }
        Booking withCheckIn(LocalDate d) { return new Booking(guest, d, checkOut, guests); }
        Booking withCheckOut(LocalDate d) { return new Booking(guest, checkIn, d, guests); }
        Booking withGuests(int n) { return new Booking(guest, checkIn, checkOut, n); }
        // Components that are validated together are replaced together.
        Booking withStay(LocalDate in, LocalDate out) { return new Booking(guest, in, out, guests); }

        Builder toBuilder() { return new Builder(this); }

        static final class Builder {
            private String guest;
            private LocalDate checkIn, checkOut;
            private int guests;

            private Builder(Booking b) { guest = b.guest; checkIn = b.checkIn; checkOut = b.checkOut; guests = b.guests; }
            Builder guest(String g) { guest = g; return this; }
            Builder checkIn(LocalDate d) { checkIn = d; return this; }
            Builder checkOut(LocalDate d) { checkOut = d; return this; }
            Builder guests(int n) { guests = n; return this; }
            Booking build() { return new Booking(guest, checkIn, checkOut, guests); }
        }
    }

    /** A generic copy for any record: replace one component by name. Checked only at run time. */
    @SuppressWarnings("unchecked")
    static <R extends Record> R with(R record, String component, Object value) {
        RecordComponent[] parts = record.getClass().getRecordComponents();
        Class<?>[] types = new Class<?>[parts.length];
        Object[] values = new Object[parts.length];
        boolean found = false;
        try {
            for (int i = 0; i < parts.length; i++) {
                types[i] = parts[i].getType();
                found |= parts[i].getName().equals(component);
                values[i] = parts[i].getName().equals(component) ? value : parts[i].getAccessor().invoke(record);
            }
            if (!found)
                throw new IllegalArgumentException(record.getClass().getSimpleName() + " has no component '" + component + "'");
            return (R) record.getClass().getDeclaredConstructor(types).newInstance(values);
        } catch (InvocationTargetException e) {
            if (e.getCause() instanceof RuntimeException re) throw re;   // validation failures stay visible
            throw new IllegalStateException(e.getCause());
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }

    static void attempt(String label, Runnable action) {
        try {
            action.run();
        } catch (IllegalArgumentException e) {
            System.out.println(label + " rejected: " + e.getMessage());
        }
    }

    public static void main(String[] args) {
        var feb10 = LocalDate.of(2027, 2, 10);
        var feb12 = LocalDate.of(2027, 2, 12);
        var jan = new Booking("Ada", LocalDate.of(2027, 1, 10), LocalDate.of(2027, 1, 12), 2);
        System.out.println(jan);

        // 1. One component changes, the original is untouched.
        System.out.println(jan.withGuests(3) + ", original still has " + jan.guests());

        // 2. Validation runs on every copy.
        attempt("withGuests(7)", () -> jan.withGuests(7));

        // 3. The chain trap: the intermediate copy (Feb 10 to Jan 12) is invalid.
        attempt("chain", () -> jan.withCheckIn(feb10).withCheckOut(feb12));
        System.out.println("withStay: " + jan.withStay(feb10, feb12));

        // 4. Every wither is one allocation and one validation.
        Booking.constructed = 0;
        jan.withGuest("Grace").withGuests(4).withStay(feb10, feb12);
        System.out.println("three withers -> " + Booking.constructed + " constructions");
        Booking.constructed = 0;
        Booking viaBuilder = jan.toBuilder().guest("Grace").guests(4).checkIn(feb10).checkOut(feb12).build();
        System.out.println("one builder   -> " + Booking.constructed + " construction: " + viaBuilder);

        // 5. The reflective, generic copy: works for any record, fails only at run time.
        System.out.println("generic: " + with(jan, "guests", 4));
        attempt("generic typo", () -> with(jan, "guestCount", 4));
        attempt("generic guests=9", () -> with(jan, "guests", 9));
        System.out.println("copy equals original? " + with(jan, "guest", "Ada").equals(jan));
    }
}
```

Output:

```text output
Booking[guest=Ada, checkIn=2027-01-10, checkOut=2027-01-12, guests=2]
Booking[guest=Ada, checkIn=2027-01-10, checkOut=2027-01-12, guests=3], original still has 2
withGuests(7) rejected: guests must be 1..4, was 7
chain rejected: checkOut 2027-01-12 is not after checkIn 2027-02-10
withStay: Booking[guest=Ada, checkIn=2027-02-10, checkOut=2027-02-12, guests=2]
three withers -> 3 constructions
one builder   -> 1 construction: Booking[guest=Grace, checkIn=2027-02-10, checkOut=2027-02-12, guests=4]
generic: Booking[guest=Ada, checkIn=2027-01-10, checkOut=2027-01-12, guests=4]
generic typo rejected: Booking has no component 'guestCount'
generic guests=9 rejected: guests must be 1..4, was 9
copy equals original? true
```

## How it works

* **Withers are one-line constructor calls.** Inside the record, the component fields (`guest`, `checkIn`, ...) are in scope, so each wither passes them through unchanged and swaps one. The original is never touched, as the second line shows.
* **The compact constructor is the single gate.** Every path in the example, the withers, the builder and even the reflective `with`, ends in `new Booking(...)`, so the `guests must be 1..4` rule cannot be bypassed. That is why `withGuests(7)` and the reflective `guests=9` are both rejected by the same rule, with the same message format.
* **The chain trap is real.** `jan.withCheckIn(feb10)` has to produce a complete, valid booking before `.withCheckOut(feb12)` ever runs, and "Feb 10 to Jan 12" is not one. The JEP 468 text calls this out explicitly: withers for components that are validated together must update them together. Here, that is `withStay`.
* **The builder trades safety in the middle for one check at the end.** `toBuilder()` copies all components into mutable fields, you change as many as you like in any order, and `build()` calls the canonical constructor exactly once. The counter shows it: three withers, three constructions; one builder, one.
* **The generic `with` uses the record reflection API** added with records in Java 16: `getRecordComponents()` lists the components in declaration order, `getAccessor()` reads them, and the canonical constructor is the one whose parameter types match the components exactly. It is the only version you write once for every record type, and it pays for that with strings: the typo `guestCount` compiles happily and fails at run time.

### What about `with` expressions?

JEP 468, *Derived Record Creation*, proposes letting the compiler write withers for you:

```java
// Proposed syntax from JEP 468. Not valid Java in any JDK released so far.
Booking moved = jan with {
    checkIn = feb10;
    checkOut = feb12;
};
```

The block runs on local copies of all components, then calls the canonical constructor once, which would also make the chain trap disappear. But be precise about its status: JEP 468 is a **Candidate**, it has no target release, and it has not shipped even as a preview. JDK 27 with preview features enabled still sees a syntax error:

```java compile-fail jdk=27 args="--enable-preview --release 27"
public class Derived {
    record Point(int x, int y, int z) {}

    public static void main(String[] args) {
        Point p = new Point(1, 2, 3);
        Point q = p with { x = 0; };
        System.out.println(q);
    }
}
```

```text compile-error
Derived.java:6: error: ';' expected
        Point q = p with { x = 0; };
                   ^
Derived.java:6: error: not a statement
        Point q = p with { x = 0; };
                    ^
Derived.java:6: error: ';' expected
        Point q = p with { x = 0; };
                        ^
3 errors
```

## Gotchas

* **Copies are shallow.** A `List` component is shared between the original and every copy. Defensively copy it in the compact constructor (`items = List.copyOf(items)`) and the problem disappears.
* **Withers on a record do not survive a refactoring for free.** Add a component and every wither needs editing. The compiler finds them all, because every `new Booking(...)` call now has the wrong arity, but it is still busywork that a builder or JEP 468 would avoid.
* **Allocation is real, but usually cheap.** A chain of N withers creates N objects and runs validation N times. Short-lived objects are what generational garbage collectors are best at, and the JIT can often eliminate intermediate copies through escape analysis once the code is hot, but do not rely on that in a tight loop: use the builder or a multi-component wither there.
* **The reflective `with` is slow and fragile.** Every call reflects over the class, boxes primitives and has no compile-time checks. Use it for tests, tooling or generic infrastructure, not for domain code.
* **Copy equals original when nothing changed.** Records compare by value, so `with(jan, "guest", "Ada").equals(jan)` is `true`. Do not use identity (`==`) to detect "was this booking modified?".

## When to use it (and when not to)

Hand-written withers are the right default for small records (up to five or six components) in domain code: they are obvious, fast and type safe. Add a combined wither whenever the compact constructor checks a relationship between components. Switch to `toBuilder()` when callers typically change several components at once, or when the record grows large enough that a dozen withers become noise. Lombok's `@With` and the Immutables library generate withers if you already use them. Keep the reflective copy for generic code that truly cannot know the record type at compile time.

## Related

* [013 · Step Builder: Compile-Time Required Fields](013-step-builder.md)
* [010 · Lenses: Deep Updates on Immutable Records](../01-functional/010-lenses.md), for withers that reach into nested records
* [043 · Records Beyond POJOs](../05-modern-language/043-records-beyond-pojos.md), for compact constructor validation
* [017 · Command Pattern with Undo and Redo in Lambdas](017-command-undo.md), where immutable snapshots make undo trivial

## Sources

* [JEP 468: Derived Record Creation (Preview)](https://openjdk.org/jeps/468), status Candidate
* [JEP 395: Records](https://openjdk.org/jeps/395)
* [`java.lang.reflect.RecordComponent` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/reflect/RecordComponent.html)
* [JLS §8.10.4: Record Constructor Declarations](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.10.4)
