# 003 · Try: Turning Exceptions into Values

> `URI::new` throws a checked exception, so it cannot go into `stream().map(...)`. Wrap it in a `Try` and it can, and one bad URL no longer sinks the whole batch.

**Since:** Java 21 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Exceptions and lambdas do not get along. This does not compile, because `new URI(s)` throws the checked `URISyntaxException` and `Function.apply` declares nothing:

```java
List<URI> uris = raw.stream().map(URI::new).toList();     // error: unreported exception URISyntaxException
```

So you switch to `URI::create`, which wraps the problem in an unchecked `IllegalArgumentException`. Now it compiles, and the first malformed URL kills the entire stream. The other 9,999 good ones are lost with it, and you get no list of what failed.

What you actually want is a value that says "this step succeeded with X" or "this step failed with exception E", so the stream can keep going and you can sort the results out at the end.

## The trick

**Try** is [002's Either](002-either.md) with the error type fixed to the exception, plus one crucial habit: every operation that runs your code catches what it throws.

```java
sealed interface Try<T> {
    record Success<T>(T value) implements Try<T> {}
    record Failure<T>(Exception error) implements Try<T> {}

    static <T> Try<T> of(CheckedSupplier<? extends T> body) {
        try {
            return new Success<>(body.get());
        } catch (Exception e) {
            return new Failure<>(e);
        }
    }
}
```

`CheckedSupplier` is a one line functional interface whose method is allowed to `throw Exception`. That single declaration is what lets `() -> new URI(s)` into a lambda. From there it is the usual family: `map` and `flatMap` on the success, `recover` and `recoverWith` on the failure, `fold` to leave, `toOptional` to forget the error, and `get` to turn it back into an exception.

The interesting decisions are not the API. They are *what to catch* and *what that does to the laws*.

## Full example

```java run
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.file.*;
import java.util.*;
import java.util.function.*;
import java.util.stream.*;

public class TryDemo {

    @FunctionalInterface
    interface CheckedSupplier<T> { T get() throws Exception; }

    @FunctionalInterface
    interface CheckedFunction<T, R> { R apply(T value) throws Exception; }

    sealed interface Try<T> {
        record Success<T>(T value) implements Try<T> {}
        record Failure<T>(Exception error) implements Try<T> {}

        static <T> Try<T> success(T value) { return new Success<>(value); }
        static <T> Try<T> failure(Exception error) { return new Failure<>(error); }

        // Catches Exception, not Throwable: an OutOfMemoryError should still take the JVM down.
        static <T> Try<T> of(CheckedSupplier<? extends T> body) {
            try {
                return success(body.get());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();   // we swallowed the signal, so put it back
                return failure(e);
            } catch (Exception e) {
                return failure(e);
            }
        }

        // Like Scala's and Vavr's flatMap, this one also catches what f throws.
        default <R> Try<R> flatMap(CheckedFunction<? super T, Try<R>> f) {
            return switch (this) {
                case Success<T>(T value) -> Try.of(() -> f.apply(value)).fold(Try::failure, inner -> inner);
                case Failure<T>(Exception error) -> failure(error);
            };
        }

        default <R> Try<R> map(CheckedFunction<? super T, ? extends R> f) {
            return flatMap(value -> success(f.apply(value)));
        }

        default Try<T> recoverWith(CheckedFunction<? super Exception, Try<T>> f) {
            return switch (this) {
                case Success<T> success -> success;
                case Failure<T>(Exception error) -> Try.of(() -> f.apply(error)).fold(Try::failure, inner -> inner);
            };
        }

        default Try<T> recover(CheckedFunction<? super Exception, ? extends T> f) {
            return recoverWith(error -> success(f.apply(error)));
        }

        default <X> X fold(Function<? super Exception, ? extends X> onFailure,
                           Function<? super T, ? extends X> onSuccess) {
            return switch (this) {
                case Success<T>(T value) -> onSuccess.apply(value);
                case Failure<T>(Exception error) -> onFailure.apply(error);
            };
        }

        default Optional<T> toOptional() { return fold(error -> Optional.empty(), Optional::ofNullable); }

        // The door back to exceptions. Unchecked ones come out exactly as they went in.
        default T get() {
            return switch (this) {
                case Success<T>(T value) -> value;
                case Failure<T>(RuntimeException e) -> throw e;
                case Failure<T>(Exception e) -> throw new IllegalStateException("Try failed", e);
            };
        }
    }

    // URISyntaxException carries structured details, no need to parse its message.
    static String describe(Exception e) {
        return switch (e) {
            case URISyntaxException u -> "URISyntaxException: " + u.getReason() + " at index " + u.getIndex();
            default -> e.getClass().getSimpleName() + ": " + e.getMessage();
        };
    }

    // recoverWith tries the next source, recover supplies the last resort.
    static Try<Integer> port(Map<String, String> env, Map<String, String> file) {
        return Try.of(() -> Integer.parseInt(env.get("PORT")))
                .recoverWith(e -> Try.of(() -> Integer.parseInt(file.get("port"))))
                .recover(e -> 8080);
    }

    public static void main(String[] args) throws Exception {
        System.out.println(Try.of(() -> Integer.parseInt("21")).map(n -> n * 2));
        System.out.println(Try.of(() -> Integer.parseInt("twenty one")).map(n -> n * 2));

        // Streams: without Try, the first bad element ends the party.
        List<String> raw = List.of("https://openjdk.org/jeps/409", "http://exa mple.com",
                "mailto:duke@example.org", "https://docs.oracle.com/en/java/");
        try {
            System.out.println(raw.stream().map(URI::create).map(URI::getHost).toList());
        } catch (IllegalArgumentException e) {
            System.out.println("plain stream died: " + describe((URISyntaxException) e.getCause()));
        }

        List<Try<String>> hosts = raw.stream()
                .map(s -> Try.of(() -> new URI(s))          // checked URISyntaxException: fine here
                        .map(URI::getHost)
                        .map(host -> host.toUpperCase()))   // a mailto: URI has no host
                .toList();
        System.out.println("hosts:    " + hosts.stream().flatMap(t -> t.toOptional().stream()).toList());
        hosts.stream()
                .flatMap(t -> t instanceof Try.Failure<String>(Exception e) ? Stream.of(e) : Stream.<Exception>empty())
                .forEach(e -> System.out.println("problem:  " + describe(e)));

        System.out.println("port " + port(Map.of("PORT", "eighty"), Map.of("port", "8081")));
        System.out.println("port " + port(Map.of("PORT", "eighty"), Map.of()));

        // get() leaves the Try world again.
        try {
            Try.of(() -> Files.readString(Path.of("no-such-file.txt"))).get();
        } catch (IllegalStateException e) {
            System.out.println("get() threw: " + e.getMessage() + ", cause " + e.getCause());
        }

        // Interrupts survive being turned into values.
        Try<String> nap = Try.of(() -> {
            Thread.currentThread().interrupt();
            Thread.sleep(1_000);
            return "rested";
        });
        System.out.println(nap + ", still interrupted? " + Thread.interrupted());

        // The price of catching inside flatMap: left identity only holds for functions that do not throw.
        CheckedFunction<String, Try<Integer>> strictLength = s -> {
            if (s.isBlank()) throw new IllegalArgumentException("blank input");
            return Try.success(s.length());
        };
        System.out.println("success(a).flatMap(f) = " + Try.success(" ").flatMap(strictLength));
        try {
            System.out.println("f.apply(a)            = " + strictLength.apply(" "));
        } catch (IllegalArgumentException e) {
            System.out.println("f.apply(a)            threw " + e);
        }

        // Failures compare by exception identity.
        CheckedSupplier<Integer> bad = () -> Integer.parseInt("x");
        System.out.println("two identical failures equal? " + Try.of(bad).equals(Try.of(bad)));
    }
}
```

Output:

```text output
Success[value=42]
Failure[error=java.lang.NumberFormatException: For input string: "twenty one"]
plain stream died: URISyntaxException: Illegal character in authority at index 10
hosts:    [OPENJDK.ORG, DOCS.ORACLE.COM]
problem:  URISyntaxException: Illegal character in authority at index 10
problem:  NullPointerException: Cannot invoke "String.toUpperCase()" because "<parameter1>" is null
port Success[value=8081]
port Success[value=8080]
get() threw: Try failed, cause java.nio.file.NoSuchFileException: no-such-file.txt
Failure[error=java.lang.InterruptedException: sleep interrupted], still interrupted? true
success(a).flatMap(f) = Failure[error=java.lang.IllegalArgumentException: blank input]
f.apply(a)            threw java.lang.IllegalArgumentException: blank input
two identical failures equal? false
```

## How it works

* **`Try.of` is the only `try` block** that matters. `flatMap` and `recoverWith` route the user's function through `Try.of`, and `map` and `recover` are built on those, so *every* function you hand to a `Try` runs inside a catch. That is why the `NullPointerException` from `host.toUpperCase()` on the hostless `mailto:` URI became a `Failure` instead of a crash. (The `<parameter1>` in its message is the helpful NPE text doing its best without debug symbols. Like plain `javac` without `-g`, the source launcher keeps no local variable names; compile with `-g` and it says `"host"`.)
* **The checked exception problem disappears** because `CheckedFunction.apply` declares `throws Exception`. `URI::getHost` fits it too: a method that throws nothing is compatible with one that may throw. For the full story on checked exceptions in lambdas, including generic `throws` clauses, see [037](../04-generics/037-generic-throws-lambdas.md).
* **`recoverWith` versus `recover`.** `recoverWith` returns another `Try`, so it can fail again (the second config source), while `recover` always produces a value. In the output, the first `port` call is rescued by the file, the second falls through to `8080`.
* **`get()` uses a nested record pattern.** `case Failure<T>(RuntimeException e)` matches only when the component is unchecked and rethrows it unchanged. The next case catches the checked rest (`NoSuchFileException` here) and wraps it, because a `T get()` cannot throw a checked exception without lying in its signature. Vavr's choice is a [sneaky throw](../04-generics/036-sneaky-throws.md) of the original instead.

### What to catch, and what it costs

* **`Exception`, not `Throwable`.** A `StackOverflowError` or `OutOfMemoryError` inside a `Try` means the JVM is in trouble, and turning it into a value that some caller may log and ignore is the worst possible reaction. Scala's `Try` makes the same call with its `NonFatal` extractor. Vavr catches `Throwable` but immediately rethrows `VirtualMachineError`, `LinkageError`, `ThreadDeath` and `InterruptedException`.
* **`InterruptedException` is a signal, not an error.** Catching it clears the thread's interrupt flag, so a `Try` that swallows it silently breaks cancellation. This version restores the flag and the output proves it (`still interrupted? true`). Scala and Vavr take the other legitimate route and refuse to capture it at all.
* **The laws bend.** [001's](001-maybe-monad.md) left identity says `success(a).flatMap(f)` equals `f.apply(a)`. Here the left side is a `Failure` and the right side is a thrown exception, so the law only holds for functions that do not throw. That is the deliberate trade: being total (never throwing) matters more to `Try` than being a lawful monad.

## Gotchas

* **Try catches your bugs too.** The `NullPointerException` above is a programming error, and `Try` filed it next to a legitimately malformed URL. Keep the code inside a `Try` small and close to the thing that can actually fail.
* **`Failure` equality is identity.** Records compare components with `equals`, and `Throwable` does not override it, so two failures from the same input are not equal (last line of output). Do not use `Try` as a map key or assert on it with `assertEquals`; compare `fold(e -> e.getClass(), v -> v)` or similar instead. Vavr works around this by comparing stack traces.
* **Exceptions still cost what exceptions cost.** Every `Failure` holds a fully filled in stack trace. In a hot loop where failure is common, that is the expensive part (see [092](../10-jvm-performance/092-cheap-exceptions.md)), and a plain `Either` with an error record is cheaper.
* **`toOptional` throws information away.** Fine for "give me the hosts I could parse". Not fine if anyone will later ask why there are only two.

## When to use it (and when not to)

`Try` earns its place at the seams where exception throwing APIs meet functional code: parsing in streams, batch jobs that must report every failed record, fallback chains (`recoverWith`) across several sources. Wrap the call, carry the value, decide at the end.

Exceptions are simply better when nobody nearby can do anything useful about the failure. A request handler that cannot reach the database should throw and let the framework return a 500, roll back the transaction and log the stack trace. Wrapping that in a `Try` just adds a step where someone can forget to look. And if you do use it widely, prefer [Vavr's](https://vavr.io/) `Try` to your own: the hard parts (fatal errors, sneaky `get`, equality, a hundred convenience methods) are already decided.

## Related

* [002 · Either: Typed Errors Without Exceptions](002-either.md), when the errors deserve their own types
* [036 · Sneaky Throws: Checked Exceptions Without the Paperwork](../04-generics/036-sneaky-throws.md)
* [037 · Checked Exceptions in Lambdas, Properly](../04-generics/037-generic-throws-lambdas.md)
* [092 · Cheap Exceptions: The Cost of a Stack Trace](../10-jvm-performance/092-cheap-exceptions.md)

## Sources

* [`scala.util.Try`](https://www.scala-lang.org/api/current/scala/util/Try.html) and [`scala.util.control.NonFatal`](https://www.scala-lang.org/api/current/scala/util/control/NonFatal$.html), the design this one follows
* [Vavr `Try` source (0.10.5)](https://github.com/vavr-io/vavr/blob/v0.10.5/vavr/src/main/java/io/vavr/control/Try.java), for its fatal error list, sneaky `get` and stack trace based `equals`
* [Interrupts](https://docs.oracle.com/javase/tutorial/essential/concurrency/interrupt.html), The Java Tutorials, on the interrupt status flag
* [`java.net.URI` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/net/URI.html), the checked constructor versus `URI.create`
