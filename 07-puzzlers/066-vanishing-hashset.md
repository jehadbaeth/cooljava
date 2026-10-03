# 066 · The Element That Vanished from the HashSet

> Put a point in a `HashSet`, nudge its `x`, and ask whether the set contains it. The set says no, and keeps it anyway. A hash-based collection makes a promise about a value, and a value that changes behind its back breaks the promise.

**Since:** Java 16 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

The contract of `equals` and `hashCode` is one of the oldest rules in Java, and breaking it fails in quiet ways: no exception, no warning, just a collection that stops finding things. The traps below are older than records; the example only needs Java 16 for `record` and pattern matching for `instanceof`.

Predict every line of output, in order. Section 1 inserts a mutable `Point` into a `HashSet`, changes `x`, and probes the set several ways. Section 2 defines `equals` without `hashCode`. Section 3 writes an `equals` that is not an override. Section 4 compares `instanceof` and `getClass()` implementations of `equals`. Section 5 asks whether records cure all of this. Section 6 puts the same mutable point into an identity-based set.

```java run
import java.util.*;

public class VanishingElement {

    // Section 1: a mutable key. equals and hashCode both read x and y.
    static class Point {
        int x, y;
        Point(int x, int y) { this.x = x; this.y = y; }
        @Override public boolean equals(Object o) { return o instanceof Point p && p.x == x && p.y == y; }
        @Override public int hashCode() { return Objects.hash(x, y); }
        @Override public String toString() { return "(" + x + "," + y + ")"; }
    }

    // Section 2: equals without hashCode.
    static class Money {
        final int cents;
        Money(int cents) { this.cents = cents; }
        @Override public boolean equals(Object o) { return o instanceof Money m && m.cents == cents; }
    }

    // Section 3: an overload, not an override. The parameter type is Pt, not Object.
    static class Pt {
        final int x, y;
        Pt(int x, int y) { this.x = x; this.y = y; }
        public boolean equals(Pt other) { return other != null && other.x == x && other.y == y; }
        @Override public int hashCode() { return Objects.hash(x, y); }
    }

    // Section 4: instanceof-based equals, with a subclass that adds state.
    static class Flat {
        final int x, y;
        Flat(int x, int y) { this.x = x; this.y = y; }
        @Override public boolean equals(Object o) { return o instanceof Flat f && f.x == x && f.y == y; }
        @Override public int hashCode() { return Objects.hash(x, y); }
    }

    static class Painted extends Flat {
        final String color;
        Painted(int x, int y, String color) { super(x, y); this.color = color; }
        @Override public boolean equals(Object o) {
            return o instanceof Painted p && super.equals(o) && p.color.equals(color);
        }
    }

    // Section 4, other side: getClass-based equals is symmetric but rejects every subclass.
    static class Exact {
        final int x, y;
        Exact(int x, int y) { this.x = x; this.y = y; }
        @Override public boolean equals(Object o) {
            return o != null && o.getClass() == getClass() && ((Exact) o).x == x && ((Exact) o).y == y;
        }
        @Override public int hashCode() { return Objects.hash(x, y); }
    }

    // Section 5: records generate equals and hashCode, but a component can still be mutable.
    record Pos(int x, int y) {}
    record Bag(List<String> items) {}
    record SafeBag(List<String> items) { SafeBag { items = List.copyOf(items); } }

    static List<String> show(Collection<?> c) { return c.stream().map(String::valueOf).toList(); }

    public static void main(String[] args) {
        System.out.println("-- 1. mutate a key after inserting it");
        Set<Point> set = new HashSet<>();
        Point p = new Point(1, 2);
        set.add(p);
        p.x = 10;
        System.out.println("size=" + set.size() + " contains(p)=" + set.contains(p)
                + " contains((1,2))=" + set.contains(new Point(1, 2))
                + " contains((10,2))=" + set.contains(new Point(10, 2)));
        System.out.println("iteration finds it: " + show(set));
        System.out.println("remove(p)=" + set.remove(p));
        set.add(p);
        System.out.println("add(p) again: size=" + set.size() + " " + show(set));
        Set<Point> careful = new HashSet<>();
        Point q = new Point(1, 2);
        careful.add(q);
        careful.remove(q);
        q.x = 10;
        careful.add(q);
        System.out.println("remove, mutate, re-add: contains=" + careful.contains(q) + " size=" + careful.size());

        System.out.println("-- 2. equals without hashCode");
        Money a = new Money(500), b = new Money(500);
        System.out.println("a.equals(b)=" + a.equals(b)
                + " list.contains=" + List.of(a).contains(b)
                + " set.contains=" + new HashSet<>(List.of(a)).contains(b));

        System.out.println("-- 3. equals(Pt) is not equals(Object)");
        Pt m = new Pt(1, 2), n = new Pt(1, 2);
        Object asObject = n;
        System.out.println("m.equals(n)=" + m.equals(n) + " m.equals((Object) n)=" + m.equals(asObject)
                + " list.contains=" + List.of(m).contains(n)
                + " set.contains=" + new HashSet<>(List.of(m)).contains(n));

        System.out.println("-- 4. instanceof against getClass");
        Flat flat = new Flat(1, 2);
        Painted red = new Painted(1, 2, "red");
        System.out.println("flat.equals(red)=" + flat.equals(red) + " red.equals(flat)=" + red.equals(flat));
        System.out.println("{flat}.contains(red)=" + new HashSet<>(List.of(flat)).contains(red)
                + " {red}.contains(flat)=" + new HashSet<>(List.of(red)).contains(flat));
        Exact exact = new Exact(1, 2);
        Exact subclass = new Exact(1, 2) { };
        System.out.println("exact.equals(subclass)=" + exact.equals(subclass)
                + " subclass.equals(exact)=" + subclass.equals(exact));

        System.out.println("-- 5. records");
        System.out.println("Pos: " + new Pos(1, 2) + " contains copy=" + Set.of(new Pos(1, 2)).contains(new Pos(1, 2)));
        List<String> names = new ArrayList<>(List.of("ada"));
        Set<Bag> bags = new HashSet<>();
        Bag bag = new Bag(names);
        bags.add(bag);
        names.add("grace");
        System.out.println("Bag after names.add: contains=" + bags.contains(bag) + " size=" + bags.size());
        List<String> others = new ArrayList<>(List.of("ada"));
        Set<SafeBag> safeBags = new HashSet<>();
        SafeBag safe = new SafeBag(others);
        safeBags.add(safe);
        others.add("grace");
        System.out.println("SafeBag after others.add: contains=" + safeBags.contains(safe) + " " + safe);

        System.out.println("-- 6. identity-based set");
        Set<Point> byIdentity = Collections.newSetFromMap(new IdentityHashMap<>());
        Point r = new Point(1, 2);
        byIdentity.add(r);
        r.x = 10;
        System.out.println("contains(r)=" + byIdentity.contains(r)
                + " contains(equal copy)=" + byIdentity.contains(new Point(10, 2)));
        byIdentity.add(new Point(10, 2));
        System.out.println("add equal copy: size=" + byIdentity.size());
    }
}
```

## The answer

```text output
-- 1. mutate a key after inserting it
size=1 contains(p)=false contains((1,2))=false contains((10,2))=false
iteration finds it: [(10,2)]
remove(p)=false
add(p) again: size=2 [(10,2), (10,2)]
remove, mutate, re-add: contains=true size=1
-- 2. equals without hashCode
a.equals(b)=true list.contains=true set.contains=false
-- 3. equals(Pt) is not equals(Object)
m.equals(n)=true m.equals((Object) n)=false list.contains=false set.contains=false
-- 4. instanceof against getClass
flat.equals(red)=true red.equals(flat)=false
{flat}.contains(red)=false {red}.contains(flat)=true
exact.equals(subclass)=false subclass.equals(exact)=false
-- 5. records
Pos: Pos[x=1, y=2] contains copy=true
Bag after names.add: contains=false size=1
SafeBag after others.add: contains=true SafeBag[items=[ada]]
-- 6. identity-based set
contains(r)=true contains(equal copy)=false
add equal copy: size=2
```

The `equals(Pt)` mistake from section 3 has a one-line detector. Add `@Override` and javac refuses:

```java compile-fail
public class OverrideCheck {
    static class Pt {
        final int x;
        Pt(int x) { this.x = x; }
        @Override public boolean equals(Pt other) { return other != null && other.x == x; }
    }
}
```

```text compile-error
OverrideCheck.java:5: error: method does not override or implement a method from a supertype
        @Override public boolean equals(Pt other) { return other != null && other.x == x; }
        ^
1 error
```

## Why

### Section 1: a hash set looks where the hash says

A `HashSet` is a `HashMap` with a dummy value. On `add`, it computes the element's hash code, picks a bucket from it, and stores a node holding the element **and the hash it was filed under**. On `contains`, `remove` and every other lookup, it computes the hash again from the element's *current* state, goes to that bucket, and compares first the stored hash, then identity, then `equals`.

After `p.x = 10`, the node still sits in the bucket for the hash of `(1,2)`, and every lookup that starts from the current `p` goes to the bucket for `(10,2)`. A lookup with a fresh `(1,2)` finds the right bucket and the right stored hash, but then `equals` compares it with `p`, which now reads `(10,2)`, and says no. Nothing finds the element, yet it is still in the set. Iteration finds it because iteration walks the table without hashing anything. `remove(p)` is a lookup and misses, so the object cannot be removed by key. Only operations that walk the table (an iterator's `remove`, `removeIf`, `clear`) can get it out. `add(p)` is a lookup followed by an insert, and it misses too, so the same object goes in a second time under its new hash. That is the duplicate: `size=2` and the same `(10,2)` twice.

The last line of section 1 shows the safe order for the rare case where you must mutate: take it out, change it, put it back. Rebuilding a new set from an old one also works, because every element is hashed afresh.

The `Set` Javadoc says exactly this: the behavior of a set is not specified if an element changes in a way that affects `equals` comparisons while it is in the set. "Not specified" is the polite version of "anything may happen".

### Section 2: equals without hashCode

`HashMap` compares hash codes before it ever calls `equals`. `Object.hashCode` is derived from the object's identity, so two `Money` objects that are `equals` almost certainly get different hash codes. The stored hash of the element and the hash of the probe then differ, and the set never gets as far as calling `equals`. `List.contains` uses only `equals`, so the same pair is equal in a list and different in a set. The contract in `Object.hashCode` is a one-way street: equal objects must have equal hash codes, while unequal objects may share one.

### Section 3: an overload is not an override

`equals(Pt)` has a different signature from `equals(Object)`, so it adds a method and overrides nothing. Which one runs is decided at compile time from the static type of the argument. `m.equals(n)` picks the new overload and says `true`. Casting `n` to `Object` picks the inherited `equals(Object)`, which is identity, and says `false`. Every collection calls `equals(Object)`, so `List.contains` and `HashSet.contains` see identity, even though `hashCode` is correct. The detector is `@Override`: javac rejects the annotated version, as the answer shows.

### Section 4: symmetric or substitutable, not both

`Flat.equals` accepts any `Flat`, so `flat.equals(red)` is `true`. `Painted.equals` additionally insists on a `Painted`, so `red.equals(flat)` is `false`. Symmetry is broken, and collections expose it: `HashMap` calls `equals` on the probe, with the stored element as the argument, so `{flat}.contains(red)` calls `red.equals(flat)` and fails, while `{red}.contains(flat)` calls `flat.equals(red)` and succeeds. The hash codes agree, so only `equals` decides, and it answers differently depending on which object was inserted first.

Switching to `getClass()` repairs symmetry and transitivity. The cost is that no subclass instance is ever equal to a base instance, even a subclass that adds nothing. `new Exact(1, 2) { }` is an anonymous subclass, a stand-in for a test double or a generated proxy, and it is not equal to the object it stands in for. That breaks the Liskov substitution principle: code that works with an `Exact` stops working with a subclass of it. Bloch's analysis in *Effective Java* (Item 10) concludes that you cannot extend an instantiable class and add a value component while keeping the contract. The ways out are composition (a `Painted` that holds a `Flat`), or value classes that cannot be subclassed at all, which is what records are.

### Section 5: records cure the typing mistakes, not the shared state

A record generates `equals`, `hashCode` and `toString` from its components, so sections 2 and 3 cannot happen unless you hand-write those methods. Its fields are final, so section 1 cannot happen with `Pos`: there is no `p.x = 10`. The Javadoc calls a record "shallowly immutable", and the weight is on *shallowly*. The generated `hashCode` combines the hash codes of the components, and a `List` component hashes its current contents. Add to the list that `Bag` holds and the record's hash changes under it, so the record vanishes from the set in the same way `Point` did. The cure is the defensive copy in the compact constructor: `items = List.copyOf(items)` takes an immutable snapshot, and `others.add("grace")` no longer reaches the record.

### Section 6: identity never changes

`IdentityHashMap` hashes with `System.identityHashCode` and compares with `==`. Neither depends on the fields, so the mutated point is found. The price is that an equal copy is a stranger: `contains(equal copy)` is `false`, and `add` accepts it as a second element. The Javadoc is blunt that this class "intentionally violates" the `Map` contract. It is the right tool when identity really is the question, such as a visited set in a graph walk, and a poor repair for value semantics.

## Gotchas

* **`HashMap` keys follow the same rule.** Mutate a key and `get` returns `null`, `remove` returns `null`, and the entry stays in the table. A `List` used as a key is the commonest accidental case: `m.put(k, "v"); k.add("b"); m.get(k)` returns `null`.
* **`TreeSet` and `TreeMap` break differently.** They file elements by `compareTo`, not by hash, and the tree never re-sorts. Change a field that takes part in the ordering and lookups can walk to the wrong side, so the element becomes unfindable.
* **Entities with generated ids.** If `hashCode` uses an id that is assigned on save, the hash changes at the moment of persisting, which is exactly section 1. Hash on a stable business key, or do not put unsaved entities into hash collections.
* **Arrays in records.** Arrays inherit identity `equals`, so `new A(new int[] {1}).equals(new A(new int[] {1}))` is `false` for a record with an `int[]` component. Use a `List`, or override the three methods and use `Arrays.equals` and `Arrays.hashCode`.
* **Nothing throws.** There is no exception to catch and no warning in the log. The only symptoms are `false` where you expected `true`, a set that is bigger than it should be, and entries that no lookup can find, so they cannot be removed by key either.

## How to stay safe

* **Make everything that feeds `hashCode` immutable**: `final` fields, records, and `List.copyOf`, `Map.copyOf` or an array clone in the constructor for collection components. A key that cannot change cannot vanish.
* **If you must mutate, take it out first**: `remove`, change, `add`.
* **Override `equals` and `hashCode` together, and always write `@Override`.** Let the IDE or a record generate them, and keep them reading the same fields.
* **Do not subclass value classes.** Prefer `final` classes and records, and compose instead of extending. If you must use inheritance, keep subclass state out of `equals`, or accept `getClass()` with its limits.
* **Use `IdentityHashMap` only on purpose.** It is a different tool for a different question.
* **Test the contract.** A handful of checks (reflexive, symmetric, transitive, consistent with `hashCode`, survives a round trip through a `HashSet`) catches all six sections. See [026](../03-build-it-yourself/026-property-based-testing.md) for a way to generate the inputs.

## Related

* [056 · "Aa" Equals "BB" (in hashCode)](../06-hidden-corners/056-hashcode-collisions.md)
* [062 · Collection Traps](062-collections-traps.md)
* [043 · Records Beyond POJOs](../05-modern-language/043-records-beyond-pojos.md)
* [063 · ConcurrentModificationException and the One Case It Doesn't Fire](063-concurrent-modification.md)

## Sources

* Joshua Bloch, *Effective Java*, 3rd edition, Addison-Wesley, 2018, Item 10 (obey the general contract when overriding `equals`) and Item 11 (always override `hashCode` when you override `equals`)
* [`java.util.Set` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Set.html), the note on mutable set elements
* [`java.lang.Object` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Object.html), the `equals` and `hashCode` contracts
* [`java.util.IdentityHashMap` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/IdentityHashMap.html)
* [`java.lang.Record` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Record.html), "shallowly immutable"
