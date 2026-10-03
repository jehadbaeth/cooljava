# 037 · Checked Exceptions in Lambdas, Properly

> Give your functional interface a type parameter for the exception and write `throws E`. javac infers the checked type from the lambda body, and infers "nothing" when the body throws nothing.

**Since:** Java 8 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

The functional interfaces in `java.util.function` declare no checked exceptions, so this does not compile:

```java compile-fail
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

public class PlainFunction {
    public static void main(String[] args) {
        List<Path> paths = List.of(Path.of("a.txt"), Path.of("b.txt"));
        List<List<String>> lines = paths.stream()
                .map(p -> Files.readAllLines(p))
                .toList();
        System.out.println(lines);
    }
}
```

```text compile-error
PlainFunction.java:9: error: unreported exception IOException; must be caught or declared to be thrown
                .map(p -> Files.readAllLines(p))
                                            ^
1 error
```

You have three honest options. Wrap every call in a try/catch inside the lambda (noisy), sneak the exception past the compiler and lose it from every signature ([036 · Sneaky Throws](036-sneaky-throws.md)), or teach the interface about the exception so the compiler keeps tracking it. This document is the third option.

## The trick

Add a type parameter for the exception to the functional interface, and use it in the `throws` clause of the single method *and* of every higher-order method that calls it:

```java
@FunctionalInterface
interface ThrowingFunction<T, R, E extends Exception> {
    R apply(T t) throws E;
}

static <T, R, E extends Exception> List<R> mapAll(
        List<T> items, ThrowingFunction<? super T, ? extends R, E> f) throws E { ... }
```

`E` is an ordinary inference variable of `mapAll`. When you call `mapAll(paths, p -> Files.readAllLines(p))`, javac looks at what the lambda body can throw, finds `IOException`, and concludes `E = IOException`. So `mapAll` now `throws IOException`, the caller must handle exactly that, and `catch (IOException e)` compiles. Pass a lambda that throws nothing and `E` is inferred as `RuntimeException`, so the call needs no handler at all. One method, both worlds.

The JDK already does this once, in `Optional.orElseThrow(Supplier<? extends X>) throws X`. Hand it `() -> new IOException(...)` and you must handle `IOException`. Hand it `IllegalStateException::new` and you need nothing.

## Full example

```java run
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;
import java.util.stream.Stream;

public class ThrowingLambdas {

    @FunctionalInterface
    interface ThrowingFunction<T, R, E extends Exception> {
        R apply(T t) throws E;
    }

    // Propagates exactly what the function throws, nothing more and nothing less.
    static <T, R, E extends Exception> List<R> mapAll(
            List<T> items, ThrowingFunction<? super T, ? extends R, E> f) throws E {
        List<R> out = new ArrayList<>();
        for (T item : items) {
            out.add(f.apply(item));
        }
        return out;
    }

    // Bridge into java.util.function, where checked exceptions have no place to go.
    static <T, R> Function<T, R> unchecked(ThrowingFunction<? super T, ? extends R, ? extends IOException> f) {
        return t -> {
            try {
                return f.apply(t);
            } catch (IOException e) {
                throw new UncheckedIOException(e);
            }
        };
    }

    // No throws clause: this compiles only because E is inferred as RuntimeException.
    static int totalLength(List<String> words) {
        int total = 0;
        for (int length : mapAll(words, String::length)) {
            total += length;
        }
        return total;
    }

    public static void main(String[] args) throws IOException {
        Path dir = Files.createTempDirectory("throwing");
        Path good = Files.write(dir.resolve("good.txt"), Arrays.asList("one", "two"));
        Path missing = dir.resolve("missing.txt");
        try {
            // 1. The lambda throws IOException, so mapAll throws IOException, and we can catch it by type.
            System.out.println(mapAll(Arrays.asList(good), Files::readAllLines));
            try {
                mapAll(Arrays.asList(good, missing), Files::readAllLines);
            } catch (IOException e) {
                System.out.println("typed catch: " + e.getClass().getSimpleName());
            }

            // 2. Nothing checked in the lambda, nothing checked in the signature.
            System.out.println("total length: " + totalLength(Arrays.asList("ab", "cde")));

            // 3. The JDK's own version of the idea.
            try {
                Optional.empty().orElseThrow(() -> new IOException("no value"));
            } catch (IOException e) {
                System.out.println("orElseThrow: " + e.getMessage());
            }
            int value = Optional.of(5).orElseThrow(() -> new IllegalStateException("never happens"));
            System.out.println("orElseThrow without a handler: " + value);

            // 4. Crossing into the Streams API: wrap on the way in, unwrap at the boundary.
            try {
                Stream.of(good, missing)
                        .map(unchecked(p -> Files.readAllLines(p)))
                        .collect(Collectors.toList());
            } catch (UncheckedIOException e) {
                IOException cause = e.getCause();   // UncheckedIOException.getCause() is typed as IOException
                System.out.println("unwrapped: " + cause.getClass().getSimpleName());
            }
        } finally {
            Files.delete(good);
            Files.delete(dir);
        }
    }
}
```

Output:

```text output
[[one, two]]
typed catch: NoSuchFileException
total length: 5
orElseThrow: no value
orElseThrow without a handler: 5
unwrapped: NoSuchFileException
```

Now the two limits of the inference. First, `E` is a single type, but a method can throw several. Make the lambda throw both `IOException` and `SQLException` and javac does what the language specification says: it takes the least upper bound.

```java compile-fail
import java.io.IOException;
import java.sql.SQLException;

public class TwoExceptions {
    @FunctionalInterface
    interface ThrowingFunction<T, R, E extends Exception> {
        R apply(T t) throws E;
    }

    static <T, R, E extends Exception> R call(T input, ThrowingFunction<T, R, E> f) throws E {
        return f.apply(input);
    }

    static String load(String key) throws IOException, SQLException {
        if (key.isEmpty()) throw new IOException("empty key");
        throw new SQLException("no database");
    }

    public static void main(String[] args) {
        try {
            call("k", TwoExceptions::load);
        } catch (IOException | SQLException e) {
            System.out.println(e);
        }
    }
}
```

```text compile-error
TwoExceptions.java:21: error: unreported exception Exception; must be caught or declared to be thrown
            call("k", TwoExceptions::load);
                ^
1 error
```

Second, if the combinator promises more than the lambda can deliver, the bounds contradict each other and inference gives up:

```java compile-fail
import java.io.IOException;
import java.sql.SQLException;

public class WrongException {
    @FunctionalInterface
    interface ThrowingSupplier<R, E extends Exception> {
        R get() throws E;
    }

    // A combinator that only ever propagates IOException.
    static <R, E extends IOException> R ioOnly(ThrowingSupplier<R, E> body) throws E {
        return body.get();
    }

    static String query() throws SQLException {
        throw new SQLException("no database");
    }

    public static void main(String[] args) throws Exception {
        ioOnly(() -> query());
    }
}
```

```text compile-error
WrongException.java:20: error: incompatible types: inference variable E has incompatible bounds
        ioOnly(() -> query());
              ^
    upper bounds: IOException
    lower bounds: SQLException
  where E,R are type-variables:
    E extends IOException declared in method <R,E>ioOnly(ThrowingSupplier<R,E>)
    R extends Object declared in method <R,E>ioOnly(ThrowingSupplier<R,E>)
1 error
```

## How it works

* **Lambda bodies produce lower bounds.** JLS §18.2.5 says that for a lambda whose target function type has a `throws` clause containing inference variables, every checked exception the body can throw must be a subtype of those variables, and each such variable also gets a `throws` bound. Method references work the same way. For `p -> Files.readAllLines(p)` that yields `IOException <: E`.
* **Resolution then picks the answer.** JLS §18.4 resolves a variable with lower bounds to their least upper bound. That is why one thrown type gives exactly that type, and why two unrelated types collapse into their common supertype (`Exception` in `TwoExceptions`, which is the error you see: `unreported exception Exception`). A variable with no lower bounds that carries a `throws` bound becomes `RuntimeException`, provided every proper upper bound is a supertype of `RuntimeException`. This is the very same rule that [036](036-sneaky-throws.md) abuses: there, nothing ever supplies a lower bound, so `E` falls through to `RuntimeException` and the cast does the rest. Here an honest lambda body supplies the lower bound, and the type survives.
* **Wildcards still go on `T` and `R`.** `ThrowingFunction<? super T, ? extends R, E>` is ordinary PECS ([035](035-pecs-wildcard-capture.md)). `E` stays exact, because it is an inference variable of the method, not something to widen.
* **`UncheckedIOException` is the JDK's designated wrapper.** Its constructor accepts only an `IOException`, and its `getCause()` is declared to return `IOException`, so unwrapping at the boundary needs no cast, as in step 4.
* **The bridge `unchecked` is deliberately not generic in `E`.** Its parameter is `ThrowingFunction<..., ? extends IOException>`, so a lambda or method reference that throws `FileNotFoundException` or `NoSuchFileException` is accepted, while one that throws `SQLException` is rejected with `unreported exception SQLException`. The wildcard leaves no inference variable to grow, and the only place left to put the exception is the `catch (IOException e)` inside the bridge.
* **Why `E extends Exception` and not `Throwable`?** Callers do not handle `Error`s, so `Exception` is the useful bound for your own interfaces. `Optional.orElseThrow` uses `Throwable`, which works the same way.

## Gotchas

* **No unions.** Brian Goetz named the root cause in his 2010 "Exception transparency" message to the lambda mailing list: a type parameter stands for exactly one type, while a `throws` clause is a list. The only fix on offer is a common supertype, so a lambda throwing two unrelated checked types forces its callers to handle `Exception`. Either give your domain a shared base exception, or wrap one of them.
* **A narrower bound removes the "throws nothing" escape.** With `E extends IOException` (as in `ioOnly`), `RuntimeException` is not an allowed answer, so even `ioOnly(() -> "x")` forces its caller to handle `IOException`. Keep the bound at `Exception` unless you want exactly that.
* **You cannot catch `E`.** `catch (E e)` is rejected with "unexpected type, required: class, found: type parameter E". Generic code can only *propagate* `E` through `throws`. Handling it takes a concrete type, which is why the bridge above is written for `IOException` and not for a generic `E`.
* **Do not overload on the two kinds of interface.** Declaring both `run(Function<String, Integer>)` and `<E extends Exception> run(ThrowingFunction<String, Integer, E>)` makes `run(s -> s.length())` fail with "reference to run is ambiguous", because an implicitly typed lambda does not help javac choose. Use different names, as `unchecked` and `mapAll` do here.
* **The Streams API does not take these interfaces.** `map`, `filter` and `forEach` want `java.util.function` types, so inside a pipeline the exact type is lost again and you fall back to wrapping (step 4). For I/O heavy loops a plain `for` statement is often the clearest answer, and it needs no new interface at all.
* **One interface per shape.** `Supplier`, `Consumer`, `Predicate`, `BiFunction`, `Runnable` all need a throwing twin if you want to use them. Writing six of them is boring, and libraries such as [jOOL](https://github.com/jOOQ/jOOL), whose `Unchecked` class wraps the common functional interfaces into ones that may throw checked exceptions, have done it for you (its README shows the wrapping pattern, so its role is that of the `unchecked` bridge above, not of `mapAll`).
* **Overuse makes signatures noisy.** `throws E` on every helper is the price of exact types. Use it for combinators that are really about exceptions (retry, transaction scope, resource handling), not for every utility.

## When to use it (and when not to)

Use it when you write a higher-order method that runs caller-supplied code and the caller's checked exceptions should come out the other side unchanged: `inTransaction(connection -> ...) throws SQLException`, `retry(() -> ...) throws IOException`, `withFile(path, in -> ...) throws IOException`, resource scopes, test fixtures. It costs nothing at runtime, it is plain Java 8, and the JDK itself sets the precedent.

Compare it with the other two options. Sneaky throws ([036](036-sneaky-throws.md)) hides the type from every signature and is for the rare corner where you control both ends. Wrapping in `UncheckedIOException` keeps the compiler quiet and the cause recoverable, and it is the right answer at a stream boundary. Values that carry failure ([003 · Try](../01-functional/003-try-monad.md), [002 · Either](../01-functional/002-either.md)) make the failure part of the data flow instead of the control flow, which is the better fit once the pipeline gets long.

## Related

* [036 · Sneaky Throws: Checked Exceptions Without the Paperwork](036-sneaky-throws.md), the same inference rule used to hide the exception instead of tracking it
* [035 · PECS and Wildcard Capture](035-pecs-wildcard-capture.md), for the wildcards on `T` and `R`
* [003 · Try: Turning Exceptions into Values](../01-functional/003-try-monad.md)
* [002 · Either: Typed Errors Without Exceptions](../01-functional/002-either.md)

## Sources

* JLS [§18.2.5 Checked Exception Constraints](https://docs.oracle.com/javase/specs/jls/se25/html/jls-18.html#jls-18.2.5) and [§18.4 Resolution](https://docs.oracle.com/javase/specs/jls/se25/html/jls-18.html#jls-18.4)
* Brian Goetz, [Exception transparency](https://mail.openjdk.org/pipermail/lambda-dev/2010-June/001484.html), lambda-dev mailing list (June 2010)
* [`Optional.orElseThrow` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Optional.html#orElseThrow(java.util.function.Supplier))
* [`UncheckedIOException` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/io/UncheckedIOException.html)
* [jOOL](https://github.com/jOOQ/jOOL), `org.jooq.lambda.Unchecked`
