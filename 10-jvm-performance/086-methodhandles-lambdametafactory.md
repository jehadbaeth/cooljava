# 086 · MethodHandles and LambdaMetafactory: Reflection at Full Speed

> Reflection checks its paperwork on every call. A method handle checks it once. A lambda built by `LambdaMetafactory` stops being reflection at all, and the JIT treats it like code you wrote by hand.

**Since:** Java 16 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

Mappers, serializers, DI containers and validators all call methods they only learn about at runtime: "read the property named in this config file", "call every getter on this class". The textbook tool is `java.lang.reflect.Method`:

```java
Method getter = Planet.class.getMethod("moons");
int moons = (Integer) getter.invoke(planet);   // varargs array, boxing, access checks, casts
```

Every `invoke` call takes an `Object[]`, boxes primitives, and has historically re-checked access. For a long time the JIT also could not see through it. Called once per request, nobody cares. Called once per field per row of a ten-million-row export, it shows up in the profiler.

## The trick

Java 7 added `java.lang.invoke` (JSR 292), and it gives you two upgrades.

**1. Method handles.** A `MethodHandle` is a typed, directly executable reference to a method, constructor or field. Access is checked once, when a `Lookup` creates it. After that it is just a callable thing with a fixed `MethodType`:

```java
MethodHandle concat = lookup.findVirtual(String.class, "concat", methodType(String.class, String.class));
String s = (String) concat.invokeExact("Hello, ", "world");
```

Handles compose. `insertArguments`, `filterReturnValue`, `guardWithTest` and friends build new handles out of old ones, which is how `invokedynamic` string concatenation and record `toString` are implemented inside the JDK.

**2. `LambdaMetafactory`.** This is the bootstrap method javac uses for every lambda and method reference. You can call it yourself to turn a handle into a real instance of a functional interface. The JDK generates a small hidden class whose `apply` calls your target directly, with no reflection left on the call path.

## Full example

```java run
import java.lang.invoke.*;
import java.lang.reflect.Method;
import java.util.*;
import java.util.function.*;

import static java.lang.invoke.MethodType.methodType;

public class HandlesDemo {

    record Planet(String name, int moons) {}

    /** Turns any reflective getter into a real Function, as fast as a lambda. */
    @SuppressWarnings("unchecked")
    static <T, R> Function<T, R> toFunction(MethodHandles.Lookup lookup, Method getter) throws Throwable {
        MethodHandle impl = lookup.unreflect(getter);
        CallSite site = LambdaMetafactory.metafactory(
                lookup,
                "apply",                                  // the interface method to implement
                methodType(Function.class),               // factory: captures nothing, returns a Function
                methodType(Object.class, Object.class),   // erased signature of Function.apply
                impl,                                     // what apply() should call
                impl.type());                             // specialized signature, here (Planet)String
        return (Function<T, R>) site.getTarget().invokeExact();
    }

    public static void main(String[] args) throws Throwable {
        MethodHandles.Lookup lookup = MethodHandles.lookup();
        var earth = new Planet("Earth", 1);
        var mars = new Planet("Mars", 2);

        // 1. Finding handles: virtual methods, static methods, even private fields.
        MethodHandle concat = lookup.findVirtual(String.class, "concat", methodType(String.class, String.class));
        MethodHandle max = lookup.findStatic(Math.class, "max", methodType(int.class, int.class, int.class));
        MethodHandle moonsField = lookup.findGetter(Planet.class, "moons", int.class);

        String hello = (String) concat.invokeExact("Hello, ", "world");
        int bigger = (int) max.invokeExact(3, 7);
        int moons = (int) moonsField.invokeExact(mars);
        System.out.println(hello + " | max = " + bigger + " | Mars moons = " + moons);
        System.out.println("concat type: " + concat.type());

        // 2. invokeExact means exact: the call site's static types must match the handle's type.
        try {
            Object wrong = concat.invokeExact("a", "b");   // call site says (String,String)Object
            System.out.println(wrong);
        } catch (WrongMethodTypeException e) {
            System.out.println("invokeExact: " + e.getMessage());
        }
        System.out.println("invoke adapts: " + concat.invoke("a", "b"));

        // 3. Combinators: build behavior out of handles, no new classes.
        MethodHandle greet = MethodHandles.insertArguments(concat, 0, "Hello, ");      // (String)String
        MethodHandle upper = lookup.findVirtual(String.class, "toUpperCase", methodType(String.class));
        MethodHandle shout = MethodHandles.filterReturnValue(greet, upper);
        MethodHandle isEmpty = lookup.findVirtual(String.class, "isEmpty", methodType(boolean.class));
        MethodHandle stranger = MethodHandles.dropArguments(
                MethodHandles.constant(String.class, "HELLO, STRANGER"), 0, String.class);
        MethodHandle polite = MethodHandles.guardWithTest(isEmpty, stranger, shout);
        System.out.println("polite: " + (String) polite.invokeExact("ada") + " | " + (String) polite.invokeExact(""));
        MethodHandle atLeastZero = MethodHandles.insertArguments(max, 0, 0);          // (int)int
        System.out.println("clamp(-5) = " + (int) atLeastZero.invokeExact(-5)
                + ", clamp(5) = " + (int) atLeastZero.invokeExact(5));

        // 4. LambdaMetafactory: a reflective Method becomes a plain Function.
        Method getter = Planet.class.getMethod("name");
        Function<Planet, String> nameOf = toFunction(lookup, getter);
        System.out.println("names: " + List.of(earth, mars).stream().map(nameOf).toList());
        System.out.println("generated class is hidden? " + nameOf.getClass().isHidden());

        // Capturing works too: the factory type lists the captured values.
        CallSite bound = LambdaMetafactory.metafactory(lookup, "get",
                methodType(Supplier.class, Planet.class), methodType(Object.class),
                lookup.unreflect(getter), methodType(String.class));
        @SuppressWarnings("unchecked")
        Supplier<String> earthName = (Supplier<String>) bound.getTarget().invokeExact(earth);
        System.out.println("bound supplier: " + earthName.get());
    }
}
```

Output:

```text output
Hello, world | max = 7 | Mars moons = 2
concat type: (String,String)String
invokeExact: handle's method type (String,String)String but found (String,String)Object
invoke adapts: ab
polite: HELLO, ADA | HELLO, STRANGER
clamp(-5) = 0, clamp(5) = 5
names: [Earth, Mars]
generated class is hidden? true
bound supplier: Earth
```

### A rough timing comparison

The next program reads `moons()` from 4,096 records two thousand times per trial, seven trials per variant, and reports the best trial. It is **not a benchmark**: a hand-rolled loop is at the mercy of warm-up, inlining decisions, loop unrolling and whatever else your machine is doing. If the numbers matter, measure with [JMH](https://github.com/openjdk/jmh). The checksum is printed so the JIT cannot discard the work. The numbers below are one run on one arm64 Mac with JDK 25 and **they vary** between runs and machines; only the rough ratios are interesting.

```java run nondeterministic
import java.lang.invoke.*;
import java.lang.reflect.Method;
import java.util.function.ToIntFunction;

import static java.lang.invoke.MethodType.methodType;

public class HandleTiming {

    record Planet(String name, int moons) {}

    interface Body { long run(Planet[] planets) throws Throwable; }

    static final Method METHOD;                     // static final: a constant for the JIT
    static Method mutableMethod;                    // plain field: as if looked up at runtime
    static final MethodHandle CONSTANT_HANDLE;
    static MethodHandle mutableHandle;
    static final ToIntFunction<Planet> GENERATED;   // built by LambdaMetafactory

    static {
        try {
            var lookup = MethodHandles.lookup();
            METHOD = Planet.class.getMethod("moons");
            mutableMethod = METHOD;
            CONSTANT_HANDLE = lookup.unreflect(METHOD);
            mutableHandle = CONSTANT_HANDLE;
            @SuppressWarnings("unchecked")
            var f = (ToIntFunction<Planet>) LambdaMetafactory.metafactory(lookup, "applyAsInt",
                    methodType(ToIntFunction.class), methodType(int.class, Object.class),
                    CONSTANT_HANDLE, methodType(int.class, Planet.class)).getTarget().invokeExact();
            GENERATED = f;
        } catch (Throwable t) {
            throw new ExceptionInInitializerError(t);
        }
    }

    static long direct(Planet[] ps) {
        long s = 0;
        for (Planet p : ps) s += p.moons();
        return s;
    }
    static long constantMethod(Planet[] ps) throws Exception {
        long s = 0;
        for (Planet p : ps) s += (Integer) METHOD.invoke(p);
        return s;
    }
    static long mutableMethod(Planet[] ps) throws Exception {
        long s = 0;
        for (Planet p : ps) s += (Integer) mutableMethod.invoke(p);
        return s;
    }
    static long constantHandle(Planet[] ps) throws Throwable {
        long s = 0;
        for (Planet p : ps) s += (int) CONSTANT_HANDLE.invokeExact(p);
        return s;
    }
    static long mutableHandle(Planet[] ps) throws Throwable {
        long s = 0;
        for (Planet p : ps) s += (int) mutableHandle.invokeExact(p);
        return s;
    }
    static long generated(Planet[] ps) {
        long s = 0;
        for (Planet p : ps) s += GENERATED.applyAsInt(p);
        return s;
    }

    static void measure(String label, Body body, Planet[] planets) throws Throwable {
        int rounds = 2_000;
        long checksum = 0, best = Long.MAX_VALUE;
        for (int trial = 0; trial < 7; trial++) {      // the first trials double as warm-up
            long start = System.nanoTime();
            for (int r = 0; r < rounds; r++) checksum += body.run(planets);
            best = Math.min(best, System.nanoTime() - start);
        }
        double nsPerCall = (double) best / ((long) rounds * planets.length);
        System.out.printf("%-29s %6.2f ns/call  (checksum %d)%n", label, nsPerCall, checksum);
    }

    public static void main(String[] args) throws Throwable {
        Planet[] planets = new Planet[4096];
        for (int i = 0; i < planets.length; i++) planets[i] = new Planet("p" + i, i % 7);
        measure("direct call", HandleTiming::direct, planets);
        measure("Method.invoke, static final", HandleTiming::constantMethod, planets);
        measure("Method.invoke, mutable field", HandleTiming::mutableMethod, planets);
        measure("MethodHandle, static final", HandleTiming::constantHandle, planets);
        measure("MethodHandle, mutable field", HandleTiming::mutableHandle, planets);
        measure("LambdaMetafactory", HandleTiming::generated, planets);
    }
}
```

One sample run:

```text output
direct call                     0.55 ns/call  (checksum 171990000)
Method.invoke, static final     0.75 ns/call  (checksum 171990000)
Method.invoke, mutable field    4.26 ns/call  (checksum 171990000)
MethodHandle, static final      0.54 ns/call  (checksum 171990000)
MethodHandle, mutable field     2.50 ns/call  (checksum 171990000)
LambdaMetafactory               0.54 ns/call  (checksum 171990000)
```

## How it works

* **A `Lookup` is a capability.** `MethodHandles.lookup()` carries the access rights of the class that called it. That is why `findGetter(Planet.class, "moons", int.class)` can read a *private* record field: `Planet` is a nestmate of `HandlesDemo`. The check happens once, at lookup time, not on every call.
* **`invokeExact` is signature polymorphic.** javac does not pass an `Object[]`. It compiles the call with a descriptor built from the static types at the call site, including the cast on the result. `(String) concat.invokeExact("a", "b")` has type `(String,String)String` and matches. Assigning to `Object` changes the call site to `(String,String)Object`, and the JVM refuses with `WrongMethodTypeException`, as the output shows. `invoke` is the forgiving version: it adapts the types with `asType`, at a small cost.
* **Combinators are new handles, not new classes.** `polite` is "if the argument is empty return a constant, otherwise prepend `Hello, ` and upper-case". It was assembled from four JDK methods at runtime, and the JIT can inline the whole tree when the handle is a constant.
* **`metafactory` takes six arguments.** In order: the caller's lookup, the interface method name (`apply`), the *factory type* (captured values in, interface out: `()Function`, or `(Planet)Supplier` for the bound example), the erased interface signature, the implementation handle, and the specialized signature. It returns a `CallSite` whose target is a factory. Invoking that factory gives an instance of a hidden class, exactly like the one javac's `invokedynamic` produces for `Planet::name`.
* **Why the timing looks the way it does.** A `static final` handle is a constant for the JIT, so it inlines through it and lands next to the direct call. The same handle in a mutable field cannot be folded, so every call goes through the generic invoker, several times slower in the sample. The `LambdaMetafactory` function is an ordinary class with an ordinary method, so the JIT inlines it like any other lambda.
* **Reflection caught up, partly.** Since JDK 18 (JEP 416), `Method.invoke` and `Field.get` are themselves implemented with method handles. That explains why `Method.invoke` from a `static final` field came close to the direct call in the sample. The variant with the mutable field is the realistic one for frameworks that look up `Method` objects in a map, and it was the slowest line.

The APIs are from Java 7 (method handles) and Java 8 (`LambdaMetafactory`); the example uses records and `Stream.toList()`, hence Java 16.

## Gotchas

* **The cast is part of the call.** Forget `(String)` in front of `invokeExact`, or cast to the wrong type, and it still compiles. It fails at runtime with `WrongMethodTypeException`.
* **Constants or nothing.** Most of the speed comes from the JIT treating the handle as a constant. Keep handles in `static final` fields (or behind `invokedynamic`/`ClassValue`), not in a `HashMap<String, MethodHandle>` you query per call. When you do need a dynamic lookup, generate a `LambdaMetafactory` function once and cache *that*.
* **One metafactory call, one new class.** Each call defines a fresh hidden class. Do it once per target method, never once per invocation, or you will watch Metaspace grow.
* **The lookup must be able to see the target.** `metafactory` needs a full-privilege lookup (`MethodHandles.lookup()`, not `publicLookup()`), and the generated class lives in the lookup class's package and loader. For targets in other modules use `MethodHandles.privateLookupIn`, which requires the target package to be open to you.
* **Only direct handles qualify.** The implementation passed to `metafactory` must come straight from `findVirtual`, `findStatic`, `unreflect` and friends. A handle built with combinators (like `polite`) is rejected with `LambdaConversionException`.
* **Use primitive interfaces for primitive returns.** A `Function<Planet, Integer>` boxes every result. The timing example uses `ToIntFunction` with instantiated type `(Planet)int` to avoid that.
* **`invokeExact` throws `Throwable`.** Every caller has to deal with it. Wrap it once at the edge of your framework, not everywhere.

## When to use it (and when not to)

Use method handles and `LambdaMetafactory` when you write the kind of code that calls user methods by name: serializers, mappers, DI containers, rule engines, test frameworks. Build the handles or functions once at startup, store them as constants or in a cache keyed by class, and you get near-direct-call speed with runtime flexibility.

In application code you almost never need this. If you can write `Planet::name`, write `Planet::name`. And before rewriting a reflective hot path, profile it: on modern JDKs plain `Method.invoke` is often fast enough, and JMH will tell you the truth faster than intuition.

## Related

* [085 · Dynamic Proxies: Implementing Interfaces at Runtime](085-dynamic-proxies.md), where every call goes through `Method.invoke`
* [087 · Property Names from Method References with SerializedLambda](087-serialized-lambda.md), which looks inside the lambdas `LambdaMetafactory` makes
* [088 · Generating Bytecode with the Class-File API](088-classfile-api-hidden-classes.md), the same hidden classes, built by hand
* [089 · Calling C Without JNI: The Foreign Function and Memory API](089-foreign-function-memory.md), where native functions arrive as method handles

## Sources

* [`java.lang.invoke.MethodHandles` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/MethodHandles.html)
* [`java.lang.invoke.LambdaMetafactory` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/LambdaMetafactory.html)
* [JEP 416: Reimplement Core Reflection with Method Handles](https://openjdk.org/jeps/416)
* [JMH, the Java Microbenchmark Harness](https://github.com/openjdk/jmh)
