# 034 · Intersection Types: Casting to Two Types at Once

> Java has a type for "a `Runnable` that is also `Serializable`", it just never gave it a name. You spell it `Runnable & Serializable`, and the JDK itself does exactly that.

**Since:** Java 10 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Sometimes one interface is not enough to describe what you need:

* a method that needs both arithmetic (`Number.doubleValue()`) and ordering (`Comparable.compareTo()`) on the same argument,
* a lambda that must run *and* survive serialization (a distributed job, a cached comparator),
* a task that carries a capability flag, such as "safe to retry".

The classic workaround is a new interface, `interface SerializableRunnable extends Runnable, Serializable {}`. It works until you need a third combination, and every caller must now know your private little interface instead of the two standard ones.

## The trick

An **intersection type** `A & B` is a value that is both. You can write it in two places:

```java
static <T extends Number & Comparable<T>> T clamp(T value, T lo, T hi)   // a bound (Java 5)

Runnable job = (Runnable & Serializable) () -> System.out.println("hi");  // a cast (Java 8)
```

A third place needs no syntax at all: javac infers intersection types on its own, and since Java 10 `var` can hold one. The cast form is the reason for the title. Applied to a lambda, it makes the compiler generate a lambda class that implements *every* interface in the cast, which is how you get serializable lambdas and how you mix marker interfaces into a lambda.

## Full example

```java run
import java.io.*;
import java.math.BigDecimal;
import java.util.*;

public class IntersectionDemo {

    // 1. Two bounds: Number gives doubleValue(), Comparable gives compareTo().
    static <T extends Number & Comparable<T>> String range(List<T> values) {
        T min = values.get(0), max = values.get(0);
        for (T v : values) {
            if (v.compareTo(min) < 0) min = v;
            if (v.compareTo(max) > 0) max = v;
        }
        return min + ".." + max + " spread " + (max.doubleValue() - min.doubleValue());
    }

    // 2. & in a generic method: use members of both types, return the caller's exact type.
    static <T extends Appendable & CharSequence> T appendItem(T out, String item) throws IOException {
        if (out.length() > 0) out.append(", ");   // length() is CharSequence, append() is Appendable
        out.append(item);
        return out;
    }

    // A helper whose bound is an intersection: the lambda argument becomes serializable, no cast needed.
    static <T extends Runnable & Serializable> T serializable(T task) { return task; }

    // 3. A marker interface has no methods, so it can be mixed into any lambda.
    interface Idempotent {}

    static void runWithRetry(String name, Runnable task) {
        int maxAttempts = task instanceof Idempotent ? 3 : 1;
        for (int attempt = 1; ; attempt++) {
            try {
                task.run();
                System.out.println(name + ": succeeded on attempt " + attempt);
                return;
            } catch (IllegalStateException e) {
                if (attempt == maxAttempts) {
                    System.out.println(name + ": gave up after " + attempt + " attempt(s)");
                    return;
                }
            }
        }
    }

    static Runnable flaky(int failures) {
        int[] calls = {0};
        return () -> { if (++calls[0] <= failures) throw new IllegalStateException("try again"); };
    }

    static byte[] serialize(Object o) throws IOException {
        var bytes = new ByteArrayOutputStream();
        try (var out = new ObjectOutputStream(bytes)) { out.writeObject(o); }
        return bytes.toByteArray();
    }

    static Object deserialize(byte[] data) throws IOException, ClassNotFoundException {
        try (var in = new ObjectInputStream(new ByteArrayInputStream(data))) { return in.readObject(); }
    }

    public static void main(String[] args) throws Exception {
        System.out.println(range(List.of(3, 9, 4)));
        System.out.println(range(List.of(new BigDecimal("2.50"), new BigDecimal("0.75"))));

        StringBuilder colors = appendItem(appendItem(new StringBuilder(), "red"), "green");
        colors.insert(0, '[').append(']');   // still a StringBuilder, so insert() is available
        System.out.println(colors);

        // Serializable lambdas: the cast decides which interfaces the lambda class implements.
        String greeting = "hello";
        Runnable job = (Runnable & Serializable) () -> System.out.println(greeting + " from a revived lambda");
        ((Runnable) deserialize(serialize(job))).run();
        Runnable viaHelper = serializable(() -> System.out.println("helper lambda revived too"));
        ((Runnable) deserialize(serialize(viaHelper))).run();
        try {
            Runnable plain = () -> System.out.println("plain");
            serialize(plain);
        } catch (NotSerializableException e) {
            System.out.println("plain lambda: " + e.getClass().getSimpleName());
        }

        // Marker mixing: the same flaky task, with and without the capability.
        runWithRetry("plain", flaky(2));
        Runnable retryable = flaky(2);
        runWithRetry("idempotent", (Runnable & Idempotent) retryable::run);

        // var keeps the intersection, so both views work without casts.
        var both = (Runnable & Idempotent) () -> {};
        Runnable asTask = both;
        Idempotent asMarker = both;
        System.out.println("one object, two types: " + (asTask == asMarker));

        // javac infers intersections on its own: Integer and String share several supertypes.
        var mixed = List.of(1, "two");
        Serializable first = mixed.get(0);
        Comparable<?> second = mixed.get(1);
        System.out.println("mixed list elements are Serializable and Comparable: " + first + ", " + second);
    }
}
```

Output:

```text output
3..9 spread 6.0
0.75..2.50 spread 1.75
[red, green]
hello from a revived lambda
helper lambda revived too
plain lambda: NotSerializableException
plain: gave up after 1 attempt(s)
idempotent: succeeded on attempt 3
one object, two types: true
mixed list elements are Serializable and Comparable: 1, two
```

What exactly did javac infer for `List.of(1, "two")`? Ask it to convert an element to `String` and it prints the anonymous type in full:

```java compile-fail
import java.util.*;

public class MixedList {
    public static void main(String[] args) {
        var mixed = List.of(1, "two");
        String s = mixed.get(0);
    }
}
```

```text compile-error
MixedList.java:6: error: incompatible types: INT#1 cannot be converted to String
        String s = mixed.get(0);
                            ^
  where INT#1,INT#2 are intersection types:
    INT#1 extends Object,Serializable,Comparable<? extends INT#2>,Constable,ConstantDesc
    INT#2 extends Object,Serializable,Comparable<?>,Constable,ConstantDesc
1 error
```

## How it works

* **Bounds.** In `<T extends Number & Comparable<T>>`, the first bound may be a class, the rest must be interfaces. Inside the method, `T` has the members of all of them. Passing a `List<AtomicInteger>` fails to compile with "incompatible bounds", because `AtomicInteger` is a `Number` that is not `Comparable`.
* **Erasure picks the leftmost bound.** `T` erases to `Number`, and `javap -c` shows each `compareTo` call preceded by a `checkcast Comparable`. That rule is why `Collections.max` is declared `<T extends Object & Comparable<? super T>>`, see [035](035-pecs-wildcard-capture.md).
* **Intersection casts on lambdas.** A lambda needs a functional interface as its target. An intersection qualifies when, all together, it has exactly one abstract method, so `Runnable & Serializable` works and `Runnable & Callable<String>` is rejected with `INT#1 is not a functional interface ... multiple non-overriding abstract methods found`. The metafactory then spins a class that implements every interface in the cast.
* **Serializable lambdas** are stored as a `SerializedLambda` (capturing class, method name, captured arguments, here `greeting`). On the way back, `SerializedLambda.readResolve` hands that data to a synthetic `$deserializeLambda$` method that javac generated in the capturing class. The JDK uses exactly this cast: `Comparator.comparing` returns `(Comparator<T> & Serializable) (c1, c2) -> ...`, which is why JDK comparators survive serialization.
* **The helper `serializable(T)` needs no cast.** javac resolves `T` to the glb of its bounds, `Runnable & Serializable`, and uses that as the lambda's target type. The output proves the lambda really was serializable.
* **Markers.** `Idempotent` has no methods, so it adds no abstract method to the intersection. The lambda class implements it, `instanceof` sees it, and `runWithRetry` makes a decision based on a type rather than a boolean flag. The method reference `retryable::run` creates a new lambda object, which is how you add a marker to a `Runnable` you did not create.
* **`var` and inference.** `var both = (Runnable & Idempotent) ...` gives the variable the intersection type itself, which no explicit declaration can do. For `List.of(1, "two")`, javac computes the least upper bound of `Integer` and `String`: `Object & Serializable & Comparable<...> & Constable & ConstantDesc`, the recursive monster shown in the compile error.

## Gotchas

* **Serializable lambdas are fragile.** The bytes point at a synthetic method in the capturing class (here `lambda$main$7607577c$1`: javac gives serializable lambdas hash-based names to make them a little more stable). Change the lambda, its captures or the code around it and old bytes may stop deserializing. The Java Tutorial calls serializing lambdas "strongly discouraged", and the JLS mentions run-time overhead and security implications. Fine for transport between identical builds, never for storage.
* **Everything captured must be serializable too.** Capture a `Connection` or a non-serializable `this` and the write fails with `NotSerializableException` at runtime, not at compile time.
* **Marker mixing hides intent.** `(Runnable & Idempotent) task::run` is clever, but a `record RetryableTask(Runnable body, int maxAttempts)` says the same thing without type tricks and can carry data.
* **Appendable throws `IOException`.** Through `T extends Appendable & CharSequence`, `append` has `Appendable`'s signature, so `appendItem` must declare `IOException` even when you only ever pass a `StringBuilder`.
* **No named intersections.** You cannot declare a field or a return type as `Runnable & Serializable`. Only bounds, casts, inference and `var` can mention them. If you need the type in a signature, a generic type variable with that bound is the way to carry it.

## When to use it (and when not to)

Multiple bounds on a type parameter are everyday, production-grade Java: use them whenever a generic method truly needs two capabilities. Intersection casts for serializable lambdas are fine when lambdas travel between JVMs running the same build, and they are how the JDK makes its comparators serializable. Marker mixing and `var` intersections are mostly party tricks: neat to know, rarely the clearest code. That mix earns the ⚠️.

## Related

* [035 · PECS and Wildcard Capture](035-pecs-wildcard-capture.md), including the `Object &` trick in `Collections.max`
* [087 · Property Names from Method References with SerializedLambda](../10-jvm-performance/087-serialized-lambda.md), the other thing serializable lambdas are good for
* [050 · Anonymous Classes Meet var](../06-hidden-corners/050-anonymous-classes-var.md), another type you can hold but never name
* [076 · Comparator Combinators](../08-streams-collections/076-comparator-combinators.md)

## Sources

* [JLS §4.9: Intersection Types](https://docs.oracle.com/javase/specs/jls/se25/html/jls-4.html#jls-4.9) and [§15.16: Cast Expressions](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.16)
* [JLS §15.27.4: Run-Time Evaluation of Lambda Expressions](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.27.4) and the [Java Tutorial on lambda expressions](https://docs.oracle.com/javase/tutorial/java/javaOO/lambdaexpressions.html) (see "Serialization")
* [`java.lang.invoke.SerializedLambda` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/SerializedLambda.html)
