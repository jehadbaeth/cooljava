# 050 · Anonymous Classes Meet var

> `var` lets you keep the type of a class that has no name, so a throwaway `new Object() { ... }` suddenly has fields you can read. It is Java's closest thing to structural typing, and its evil twin, double brace initialization, is a trap you should know by sight.

**Since:** Java 16 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Intermediate · **Verdict:** 🧪 Party trick

The `var` trick works on any Java from 10 on. The badge says 16 only because the full example also shows the local record that replaced it.

## The problem

Sometimes you need a tiny bag of values for ten lines of code: a word together with its length, a counter that a lambda can modify. Before Java 16 a local class was the only honest option, and it felt like building a shed to hold one hammer.

Anonymous classes can declare fields and methods, but before `var` you could reach them only in the very expression that creates the object (`new Object() { int x = 21; }.x` compiles). As soon as you stored the object in a variable, its declared type was `Object` (or the supertype), and the members were out of reach:

```java
Object counter = new Object() { int count; };
counter.count++;      // does not compile: Object has no field named count
```

## The trick

Declare the variable with `var`. The compiler infers the anonymous class itself as the type, and every member is accessible:

```java
var counter = new Object() { int count; void inc() { count++; } };
counter.inc();
System.out.println(counter.count);
```

This is deliberate. JEP 286 considered rejecting such initializers or inferring a supertype, and decided otherwise. Its reasoning: anonymous class types cannot be named, but they are easily understood, because "they're just classes", and allowing them "introduces a useful shorthand for declaring a singleton instance of a local class."

The same inference flows through generic methods. When a lambda in a stream `map` returns `new Object() { ... }`, the result type of the pipeline stage *is* that anonymous type, and the next lambda sees its fields. That gives you ad hoc tuples with no declaration at all.

## Full example

Five anonymous class tricks in one method (steps 0 to 4), followed by the local record that replaced the tuple trick (step 5). The record version prints the same lines:

```java run
import java.util.Comparator;
import java.util.List;

public class AdHocTypes {

    static abstract class Greeter {
        Greeter() { System.out.println("  1. superclass constructor"); }
        abstract String greeting();
    }

    public static void main(String[] args) {
        // 0. Before var the members were reachable only inside the creating expression.
        int inExpression = new Object() { int x = 21; int twice() { return x * 2; } }.twice();
        System.out.println("same expression: " + inExpression);

        // 1. var keeps the anonymous type, so its members are reachable.
        var counter = new Object() {
            int count;
            void inc() { count++; }
        };
        counter.inc();
        counter.inc();
        System.out.println("count = " + counter.count);

        // 2. A mutable cell that a lambda may capture (the variable itself stays effectively final).
        var sum = new Object() { int total; };
        List.of(3, 4, 5).forEach(n -> sum.total += n);
        System.out.println("total = " + sum.total);

        // 3. Ad hoc tuples in a stream pipeline: map to a throwaway type and keep using its fields.
        List<String> words = List.of("alpha", "be", "gamma", "pi", "epsilon", "omega");
        System.out.println("anonymous tuples:");
        words.stream()
                .map(w -> new Object() {
                    final String word = w;
                    final int length = w.length();
                })
                .filter(t -> t.length > 3)
                .sorted(Comparator.comparing(t -> t.word))
                .map(t -> t.word + "=" + t.length)
                .forEach(line -> System.out.println("  " + line));

        // 4. An anonymous class has no constructor: field initializers and instance initializers
        //    run in textual order after the superclass constructor.
        var greeter = new Greeter() {
            String name = initialName();
            { System.out.println("  3. instance initializer, name = " + name); }
            String initialName() { System.out.println("  2. field initializer"); return "Ada"; }
            String greeting() { return "hello " + name; }
        };
        System.out.println("  4. " + greeter.greeting());

        // 5. Since Java 16 the same tuple can have a name, equals, hashCode and toString.
        record Tagged(String word, int length) {}
        System.out.println("local record:");
        words.stream()
                .map(w -> new Tagged(w, w.length()))
                .filter(t -> t.length() > 3)
                .sorted(Comparator.comparing(Tagged::word))
                .map(t -> t.word() + "=" + t.length())
                .forEach(line -> System.out.println("  " + line));
    }
}
```

Output:

```text output
same expression: 42
count = 2
total = 12
anonymous tuples:
  alpha=5
  epsilon=7
  gamma=5
  omega=5
  1. superclass constructor
  2. field initializer
  3. instance initializer, name = Ada
  4. hello Ada
local record:
  alpha=5
  epsilon=7
  gamma=5
  omega=5
```

The ad hoc type only exists inside the method that creates it. It cannot be a field type or a return type, because `var` is not allowed there, and declaring it as `Object` loses the members again:

```java compile-fail
public class CannotName {
    var field = new Object() { int x; };

    static var make() { return new Object() { int x; }; }
}
```

```text compile-error
CannotName.java:2: error: 'var' is not allowed here
    var field = new Object() { int x; };
    ^
CannotName.java:4: error: 'var' is not allowed here
    static var make() { return new Object() { int x; }; }
           ^
2 errors
```

```java compile-fail
public class LostMembers {
    public static void main(String[] args) {
        Object plain = new Object() { int count; };
        plain.count++;
    }
}
```

```text compile-error
LostMembers.java:4: error: cannot find symbol
        plain.count++;
             ^
  symbol:   variable count
  location: variable plain of type Object
1 error
```

## The evil twin: double brace initialization

Two pairs of braces after `new` look like a collection literal, which Java does not have:

```java
List<String> names = new ArrayList<String>() {{ add("ada"); add("linus"); }};
```

The outer pair declares an anonymous subclass of `ArrayList`. The inner pair is an instance initializer from step 4 above, and it calls `add`. It is the same feature as the `var` trick, pointed at a collection. It is compact, and it costs more than it looks. The next program checks every common claim against the compiler:

```java run
import java.io.ByteArrayOutputStream;
import java.io.ObjectOutputStream;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

public class DoubleBrace {

    /** A typical value class: equals insists on the exact runtime class. */
    static class Point {
        final int x, y;
        Point(int x, int y) { this.x = x; this.y = y; }
        @Override public boolean equals(Object o) {
            return o != null && getClass() == o.getClass() && ((Point) o).x == x && ((Point) o).y == y;
        }
        @Override public int hashCode() { return 31 * x + y; }
    }

    /** Not Serializable, like most classes. */
    static class Plain {}

    final String label = String.valueOf(42);   // not a compile-time constant, so reading it needs the outer instance

    List<String> doubleBrace() {
        return new ArrayList<String>() {{ add("a"); add("b"); }};
    }

    static List<String> doubleBraceInStaticContext() {
        return new ArrayList<String>() {{ add("a"); add("b"); }};
    }

    Plain ignoresOuter() { return new Plain() {}; }

    Plain usesOuter() {
        return new Plain() {
            @Override public String toString() { return label; }
        };
    }

    static String fields(Object o) {
        return Arrays.stream(o.getClass().getDeclaredFields()).map(Field::getName).collect(Collectors.toList()).toString();
    }

    public static void main(String[] args) throws Exception {
        DoubleBrace outer = new DoubleBrace();
        List<String> list = outer.doubleBrace();

        // 1. One extra class per call site, and it is not an ArrayList any more.
        System.out.println("class:            " + list.getClass().getName());
        System.out.println("is an ArrayList:  " + (list.getClass() == ArrayList.class));
        List<String> second = new ArrayList<String>() {{ add("a"); add("b"); }};
        System.out.println("same class as a second site:   " + (list.getClass() == second.getClass()));
        System.out.println("same class from the same site: " + (list.getClass() == outer.doubleBrace().getClass()));

        // 2. It holds on to the outer instance, even though it never uses it.
        System.out.println("list fields:      " + fields(list));
        Field outerField = list.getClass().getDeclaredField("this$0");
        outerField.setAccessible(true);
        System.out.println("list.this$0 is the outer object: " + (outerField.get(list) == outer));
        System.out.println("static context:   " + fields(doubleBraceInStaticContext()));

        // 3. A plain anonymous class only keeps the field if it actually uses the outer instance.
        System.out.println("ignores outer:    " + fields(outer.ignoresOuter()));
        System.out.println("uses outer:       " + fields(outer.usesOuter()));

        // 4. equals: JDK collections compare with instanceof, but a getClass() based equals does not.
        System.out.println("list equals List.of: " + list.equals(List.of("a", "b")));
        System.out.println("Point equals Point:  " + new Point(1, 2).equals(new Point(1, 2)));
        System.out.println("Point equals {{}} Point: " + new Point(1, 2).equals(new Point(1, 2) {{ }}));

        // 5. Serialization drags the outer instance along.
        try (var out = new ObjectOutputStream(new ByteArrayOutputStream())) {
            out.writeObject(list);
        } catch (java.io.NotSerializableException e) {
            System.out.println("serializing it:     NotSerializableException: " + e.getMessage());
        }
        try (var out = new ObjectOutputStream(new ByteArrayOutputStream())) {
            out.writeObject(new ArrayList<>(list));
            System.out.println("serializing a copy: ok");
        }
    }
}
```

```text output
class:            DoubleBrace$1
is an ArrayList:  false
same class as a second site:   false
same class from the same site: true
list fields:      [this$0]
list.this$0 is the outer object: true
static context:   []
ignores outer:    []
uses outer:       [this$0]
list equals List.of: true
Point equals Point:  true
Point equals {{}} Point: false
serializing it:     NotSerializableException: DoubleBrace
serializing a copy: ok
```

Point 3 is a javac version detail. Before JDK 18, javac added the synthetic `this$0` field to every anonymous class created in an instance method, used or not. This tiny program on JDK 17 shows it:

```java run jdk=17
import java.lang.reflect.Field;

public class Outer17 {
    static class Plain {}

    Plain ignoresOuter() { return new Plain() {}; }

    public static void main(String[] args) {
        Field[] fields = new Outer17().ignoresOuter().getClass().getDeclaredFields();
        System.out.println("fields on JDK " + Runtime.version().feature() + ": " + fields.length);
        for (Field f : fields) System.out.println("  " + f.getName());
    }
}
```

```text output
fields on JDK 17: 1
  this$0
```

## How it works

* **`var` infers the anonymous class type.** JLS 14.4.1 takes the type of the initializer and only projects away synthetic type variables (captures). An anonymous class type is an ordinary class type, so it survives. Fields, methods and initializer blocks are all reachable by plain member access, with no reflection.
* **Pipelines carry the type for free.** In `words.stream().map(w -> new Object() {...})` generic inference solves `R` as the anonymous class, so `filter`, `sorted` and the next `map` all see `t.length` and `t.word`.
* **Initialization order is fixed.** The superclass constructor runs first, then field initializers and instance initializers in the order they appear. The output shows `1, 2, 3, 4` in exactly that order. Because an anonymous class cannot declare a constructor, the initializer block is the only place for setup logic. Double brace initialization is that same block calling methods on `this`.
* **The costs of double braces are all mechanical.** Each call site compiles to its own class (the first one here is `DoubleBrace$1`), so every use adds a class to load and keep. Because the new class is not `ArrayList`, `getClass()` comparisons fail, as the `Point` line shows. And the instance initializer is an inner class member, so in an instance method javac gives it a reference to the enclosing object.

### The memory leak, precisely

The list printed `[this$0]` and `list.this$0` is the outer object. In a static method there is no enclosing instance, and the list has no fields at all. So a double brace list built in an instance method keeps its creator alive for as long as the list lives. Pass such a list to a cache or a long lived registry and the whole creator object graph comes along.

JDK 18 narrowed this. The [JDK 18 release notes](https://www.oracle.com/java/technologies/javase/18-relnote-issues.html) say javac now omits unused `this$` fields, so the plain anonymous class in `ignoresOuter` has none on JDK 25 (and one on JDK 17, as the last block shows). The same notes say "subclasses of java.io.Serializable are not affected by this change", and `ArrayList` is Serializable. That is why the double brace list still holds the outer object on JDK 25, even though it never uses it, and why serializing it fails with `NotSerializableException: DoubleBrace`.

## Gotchas

* **Do not return anonymous types from your API.** Callers can only see the declared supertype, so the extra members are invisible to them. This is a local trick.
* **There is no `toString`, `equals` or `hashCode` to speak of.** The ad hoc object inherits the `Object` versions, so print its fields, not the object, or use a record when the tuple needs to be compared or logged.
* **Fields of anonymous classes are mutable by default.** The `final` in the tuple example is a choice, not a given.
* **Immutable collection factories end the need for double braces.** `List.of`, `Set.of`, `Map.of` and `Map.ofEntries` have been there since Java 9. For a mutable copy, write `new ArrayList<>(List.of("a", "b"))`.

## When to use it (and when not to)

Use `var x = new Object() { ... }` for a mutable cell captured by a lambda, or a one-off helper object inside a single method, if you like the compactness. Teach it as a curiosity: it shows that anonymous class types are real types.

For tuples, use a local record. It has a name, it is immutable, `equals`, `hashCode` and `toString` come for free, and the example prints the same lines either way. Do not use the anonymous version for anything that will be read by a team that has not seen the trick.

Never use double brace initialization in production code. It creates a class per call site, breaks `getClass()` based `equals`, keeps the enclosing instance alive, and cannot be serialized from an instance method. The immutable factories are shorter and have none of those problems.

## Related

* [034 · Intersection Types: Casting to Two Types at Once](../04-generics/034-intersection-types.md), another non-denotable type that `var` can hold
* [043 · Records Beyond POJOs](../05-modern-language/043-records-beyond-pojos.md), the denotable replacement for ad hoc tuples
* [053 · The Y Combinator in Java](053-y-combinator.md), where an object with a recursive method is one answer to "a lambda cannot name itself"
* [062 · Collection Traps](../07-puzzlers/062-collections-traps.md)

## Sources

* [JEP 286: Local-Variable Type Inference](https://openjdk.org/jeps/286), the section on non-denotable types
* [JLS §14.4.1: Local Variable Declarators and Types](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.4.1) and [§15.9.5: Anonymous Class Declarations](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.9.5)
* [JDK 18 release notes: Enclosing Instance Fields Omitted from Inner Classes That Don't Use Them](https://www.oracle.com/java/technologies/javase/18-relnote-issues.html)
* [JEP 395: Records](https://openjdk.org/jeps/395)
