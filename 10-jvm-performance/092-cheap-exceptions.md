# 092 · Cheap Exceptions: The Cost of a Stack Trace

> Most of the price of `new Exception()` is the stack walk, not the throw. Skip the walk and the exception gets several times cheaper. The JVM sometimes does this behind your back, and takes your stack traces with it.

**Since:** Java 16 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

Every `Throwable` captures the call stack at the moment it is *constructed*. The constructor calls `fillInStackTrace()`, a native method that walks all frames of the current thread and records them. The cost grows with the depth of the stack, and in a web application, with its servlet filters, proxies and framework layers, a hundred frames is normal.

For an exception that signals a real failure that is a good deal: the trace is exactly what you want in the log. For an exception that is part of a protocol (a parser backtracking, a validation failing 50 times a second, a `NotFound` that the caller handles immediately), nobody reads the trace, and you pay for it every time.

Honest disclaimer first: if an exception is thrown on the happy path of your program, the best optimization is to not use an exception. Return an `Optional`, a result type (see [002](../01-functional/002-either.md)), or an error code. This document is about the cases where you are stuck with exceptions: legacy APIs, deep recursion that needs a non-local exit, and library code that must fit an exception-based contract.

## The trick

`Throwable` has a protected constructor that exists for exactly this purpose (since Java 7):

```java
protected Throwable(String message, Throwable cause,
                    boolean enableSuppression, boolean writableStackTrace)
```

`RuntimeException` and `Exception` re-export it. Pass `false` for `writableStackTrace` and the constructor never calls `fillInStackTrace()`:

```java
static class NoTrace extends RuntimeException {
    NoTrace(String message) { super(message, null, false, false); }
}
```

The pattern works on any Java version from 7; the example below happens to use records and `Stream.toList()`, hence Java 16. Before Java 7 the same effect came from overriding `fillInStackTrace()` to return `this`, which also still works. A third option is to allocate the exception once, keep it in a `static final` field and throw it again and again.

## Full example

Three parts. The first compares what each variant keeps, deterministically. The second shows the JVM doing the same trick on its own. The third is a rough timing, flagged nondeterministic.

### 1. What you keep and what you lose

```java run
import java.io.PrintWriter;
import java.io.StringWriter;

public class CheapExceptions {

    /** The default: fills in the stack trace on construction, which is the expensive part. */
    static class Classic extends RuntimeException {
        Classic(String message) { super(message); }
    }

    /** Opts out through the protected constructor: no suppression, no stack trace. */
    static class NoTrace extends RuntimeException {
        NoTrace(String message) { super(message, null, false, false); }
        NoTrace(String message, Throwable cause) { super(message, cause, false, false); }
    }

    /** The older spelling of the same idea, which also works on Java 6. */
    static class Overridden extends RuntimeException {
        Overridden(String message) { super(message); }
        @Override public Throwable fillInStackTrace() { return this; }
    }

    /** A preallocated exception keeps the trace of the moment it was created. */
    static final Classic CACHED = new Classic("created once");

    record Address(String city) {}
    record User(String name, Address address) {}

    static User find(int id) { return null; }
    static User userWithoutAddress = new User("Ada", null);
    static String[] names = new String[2];

    static void throwCached() { throw CACHED; }

    static String describe(RuntimeException e) {
        return e.getClass().getSimpleName() + ": trace frames > 0? " + (e.getStackTrace().length > 0)
                + ", suppressed=" + e.getSuppressed().length;
    }

    public static void main(String[] args) {
        // 1. What each variant keeps.
        for (RuntimeException e : new RuntimeException[] {
                new Classic("boom"), new NoTrace("boom"), new Overridden("boom")}) {
            e.addSuppressed(new IllegalStateException("close failed"));
            System.out.println(describe(e));
        }

        var cause = new IllegalArgumentException("root cause");
        var wrapped = new NoTrace("wrapped", cause);
        System.out.println("cause is kept: " + (wrapped.getCause() == cause));

        var text = new StringWriter();
        wrapped.printStackTrace(new PrintWriter(text));
        System.out.println(text.toString().lines().filter(l -> !l.startsWith("\t")).toList());

        // 2. A preallocated exception points at the place it was born, not where it was thrown.
        try {
            throwCached();
        } catch (Classic e) {
            StackTraceElement top = e.getStackTrace()[0];
            System.out.println("thrown in throwCached(), trace says: " + top.getMethodName());
        }

        // 3. Helpful NullPointerException messages (JEP 358) name the null thing.
        Runnable[] mistakes = {
                () -> find(1).name(),
                () -> userWithoutAddress.address().city(),
                () -> System.out.println(names[1].length()),
        };
        for (Runnable mistake : mistakes) {
            try {
                mistake.run();
            } catch (NullPointerException e) {
                System.out.println(e.getMessage());
            }
        }
    }
}
```

Output:

```text output
Classic: trace frames > 0? true, suppressed=1
NoTrace: trace frames > 0? false, suppressed=0
Overridden: trace frames > 0? false, suppressed=1
cause is kept: true
[CheapExceptions$NoTrace: wrapped, Caused by: java.lang.IllegalArgumentException: root cause]
thrown in throwCached(), trace says: <clinit>
Cannot invoke "CheapExceptions$User.name()" because the return value of "CheapExceptions.find(int)" is null
Cannot invoke "CheapExceptions$Address.city()" because the return value of "CheapExceptions$User.address()" is null
Cannot invoke "String.length()" because "CheapExceptions.names[1]" is null
```

### 2. The JVM does it too

After a throw site has fired often enough, the optimizing JIT compiler (C2) may replace the exception it would create with a single preallocated instance that has no stack trace. The flag is `-XX:+OmitStackTraceInFastThrow` and it is **on by default**. It applies to the implicit exceptions the JVM raises itself: `NullPointerException`, `ArithmeticException`, `ArrayIndexOutOfBoundsException`, `ArrayStoreException` and `ClassCastException`. An exception you `throw new` yourself is never affected. The class Javadoc of `NullPointerException` documents it: such objects may be constructed "as if suppression were disabled and/or the stack trace was not writable".

```java run
public class FastThrow {
    static String name;   // always null

    static int length() {
        return name.length();
    }

    public static void main(String[] args) {
        String firstMessage = null;
        boolean lostTrace = false;
        String laterMessage = "n/a";
        for (int i = 1; i <= 200_000 && !lostTrace; i++) {
            try {
                length();
            } catch (NullPointerException e) {
                if (i == 1) firstMessage = e.getMessage();
                if (e.getStackTrace().length == 0) {
                    lostTrace = true;
                    laterMessage = e.getMessage();
                }
            }
        }
        System.out.println("first NPE message:   " + firstMessage);
        System.out.println("NPE without a trace: " + lostTrace);
        System.out.println("its message:         " + laterMessage);
    }
}
```

Output:

```text output
first NPE message:   Cannot invoke "String.length()" because "FastThrow.name" is null
NPE without a trace: true
its message:         null
```

The first exception carries a helpful message and a normal stack trace. After a few thousand throws from the same compiled code, the JVM starts handing out the shared, trace-less instance, and its message is `null` too. In the runs made while writing this, the switch happened after roughly six thousand iterations, but the exact point depends on JIT timing, which is why the program only prints that it happened. Running the same file with the flag turned off:

```shell
java -XX:-OmitStackTraceInFastThrow FastThrow.java
```

```text
first NPE message:   Cannot invoke "String.length()" because "FastThrow.name" is null
NPE without a trace: false
its message:         n/a
```

### 3. A rough look at the price

This block measures a call that dives some frames deep and then fails. The first four lines are correct and deterministic: all variants report failure the same way. The timing lines are **nondeterministic**, the block is flagged that way, and the output below is one real sample run.

```java run nondeterministic
import java.util.function.IntSupplier;

public class ExceptionCost {

    static class Classic extends RuntimeException {
        Classic(String message) { super(message); }
    }

    static class NoTrace extends RuntimeException {
        NoTrace(String message) { super(message, null, false, false); }
    }

    static final NoTrace PREALLOCATED = new NoTrace("preallocated");

    /** Goes depth frames down, then fails the way the caller asked for. */
    static int dive(int depth, int kind) {
        if (depth > 0) return dive(depth - 1, kind);
        return switch (kind) {
            case 0 -> throw new Classic("boom");
            case 1 -> throw new NoTrace("boom");
            case 2 -> throw PREALLOCATED;
            default -> -1;                       // an error code instead of an exception
        };
    }

    static int attempt(int depth, int kind) {
        try {
            return dive(depth, kind);
        } catch (RuntimeException e) {
            return -1;
        }
    }

    static long nanosPerCall(IntSupplier op, int rounds) {
        long sink = 0;
        long start = System.nanoTime();
        for (int i = 0; i < rounds; i++) sink += op.getAsInt();
        long elapsed = System.nanoTime() - start;
        if (sink == 42) System.out.println();   // keeps the loop from being optimized away
        return elapsed / rounds;
    }

    public static void main(String[] args) {
        String[] names = {"new Classic()", "new NoTrace()", "preallocated NoTrace", "return -1"};

        // Correctness first, and deterministic: every variant reports failure the same way.
        for (int kind = 0; kind < names.length; kind++) {
            System.out.printf("%-22s -> %d%n", names[kind], attempt(10, kind));
        }

        // Timing second, and not deterministic. This is a rough sketch, not a benchmark.
        for (int depth : new int[] {5, 50, 500}) {
            for (int kind = 0; kind < names.length; kind++) {
                int d = depth, k = kind;
                nanosPerCall(() -> attempt(d, k), 30_000);                  // warm-up
                long ns = nanosPerCall(() -> attempt(d, k), 30_000);
                System.out.printf("depth %3d  %-22s ~%6d ns per call%n", depth, names[kind], ns);
            }
        }
    }
}
```

Output:

```text output
new Classic()          -> -1
new NoTrace()          -> -1
preallocated NoTrace   -> -1
return -1              -> -1
depth   5  new Classic()          ~   653 ns per call
depth   5  new NoTrace()          ~   148 ns per call
depth   5  preallocated NoTrace   ~   138 ns per call
depth   5  return -1              ~     3 ns per call
depth  50  new Classic()          ~  2799 ns per call
depth  50  new NoTrace()          ~  1654 ns per call
depth  50  preallocated NoTrace   ~  1654 ns per call
depth  50  return -1              ~    33 ns per call
depth 500  new Classic()          ~ 24675 ns per call
depth 500  new NoTrace()          ~ 16308 ns per call
depth 500  preallocated NoTrace   ~ 16468 ns per call
depth 500  return -1              ~  1376 ns per call
```

A hand-rolled `System.nanoTime()` loop is a sketch, not a benchmark. There is no fork, the warm-up is short, the lambda call and the JIT's inlining decisions leak into the numbers, and the machine is doing other things. Use [JMH](https://github.com/openjdk/jmh) before you quote any of this to anybody. The shape is still instructive, and Aleksey Shipilev measured it properly in "The Exceptional Performance of Lil' Exception" (see Sources).

## How it works

* **Construction is the expensive part.** `Throwable(String, Throwable, boolean, boolean)` calls `fillInStackTrace()` only when `writableStackTrace` is `true`. That native call walks the stack and stores a compact backtrace in a private field. The `StackTraceElement[]` you see from `getStackTrace()` is built lazily from it, on the first call. So `new Classic("boom")` pays the walk even if nobody ever prints the trace.
* **The cost scales with depth.** In the sample, the stack trace added several hundred nanoseconds at a depth of 5, and the gap to the trace-less variants kept growing in absolute terms as the stack got deeper. Shipilev's JMH runs show the same linear growth, from about 2 microseconds at depth 1 to about 83 at depth 1024.
* **The throw itself still costs something.** In the sample, `NoTrace` and the preallocated instance take the same time as each other, and both are far from the error code. Unwinding has to look for a handler frame by frame. When the JIT inlines the throw site into the catching method, the whole thing can collapse to a jump, which is what makes a preallocated exception so cheap in microbenchmarks. A recursion that cannot be inlined shows the less flattering picture above.
* **The variants.** `NoTrace` uses the constructor flags. `Overridden` is the pre-Java 7 spelling. In the first part both end up with zero frames, but `Overridden` still has suppression enabled (`suppressed=1`), while `NoTrace` dropped the suppressed exception too (`suppressed=0`). `getCause()` keeps working, which is the point of the four-argument constructor taking a cause.
* **Preallocated exceptions lie.** `CACHED` was constructed in the static initializer, so its stack trace says `<clinit>` however deep or far away it is thrown from, which is what the output shows. If you want to throw a shared instance, make it trace-less so it cannot mislead anybody.
* **Helpful `NullPointerException` messages (JEP 358, Java 14, on by default since Java 15).** The JVM describes what was null by analyzing the bytecode at the failing instruction: `because the return value of "CheapExceptions.find(int)" is null`. The message is computed lazily, on the first call to `getMessage()`, from the backtrace that `fillInStackTrace()` recorded. It costs nothing unless somebody asks. Local variable names appear only when the class was compiled with `javac -g`, otherwise you get `"<local4>"`.
* **Fast throw has no backtrace to analyze.** The shared instance has neither frames nor an extended message, which is why the second part prints `null` for it. Same cause, two symptoms.

## Gotchas

* **The great vanishing stack trace.** A production NPE with a missing stack trace and `null` message is not a bug in your logging. It is `OmitStackTraceInFastThrow`. The first occurrences, from before the JIT kicked in, are earlier in the log. Search for them, or run with `-XX:-OmitStackTraceInFastThrow` while debugging. The flag is a trade-off you can legitimately flip in production if your hot paths throw rarely.
* **Try-with-resources loses secondary failures.** With `enableSuppression=false`, `addSuppressed` is silently ignored, so an exception from `close()` disappears without a trace. Keep suppression enabled unless you control all the code that touches the exception.
* **`catch` blocks that log the trace get nothing.** A trace-less exception logged with `log.error("failed", e)` prints a single line. Great for the log volume, a disaster if you wanted to know where it came from. Put the context in the message instead.
* **Do not use this for failures that need diagnosing.** Only use trace-less exceptions for control flow signals whose origin is obvious from the type and message, such as a parser's `Backtrack` or a search's `Found`.
* **A shared exception is shared mutable state.** Whoever holds it can call `addSuppressed`, `initCause` or `setStackTrace`, and every other thread sees the result. The `false, false` constructor with an explicit cause (even `null`) makes all three harmless: `addSuppressed` and `setStackTrace` become no-ops and `initCause` throws `IllegalStateException`. That makes a preallocated `NoTrace` effectively immutable, and a preallocated `Classic` not.
* **JFR sees creation, not throwing.** The built-in event `jdk.JavaExceptionThrow` fires when an exception object is *created*, so a cached instance that is thrown a million times shows up once. [091](091-custom-jfr-events.md) has the machinery if you want an event of your own.

## When to use it (and when not to)

Use trace-less exceptions in parsers, interpreters and search algorithms where an exception is a deliberate, local, non-local exit. Scala's `scala.util.control.NoStackTrace` exists for the same reason. Use the four-argument constructor for them, with a clear type name and message.

Do not use it to make slow code faster by default. First measure with a real benchmark, then check whether you can return a value instead. For failures that a human or a log search will have to diagnose, the trace is the feature, and `OmitStackTraceInFastThrow` is the one case where you might even want to turn the JVM's own optimization off.

## Related

* [091 · Custom JFR Events: A Flight Recorder for Your Own Code](091-custom-jfr-events.md), to measure what is actually happening in production
* [003 · Try: Turning Exceptions into Values](../01-functional/003-try-monad.md), exceptions as plain data, with no throw at all
* [002 · Either: Typed Errors Without Exceptions](../01-functional/002-either.md), the real fix for expected failures
* [036 · Sneaky Throws: Checked Exceptions Without the Paperwork](../04-generics/036-sneaky-throws.md)

## Sources

* Aleksey Shipilev, [The Exceptional Performance of Lil' Exception](https://shipilev.net/blog/2014/exceptional-performance/) (2014)
* [JEP 358: Helpful NullPointerExceptions](https://openjdk.org/jeps/358)
* [`java.lang.Throwable` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Throwable.html), including the four-argument constructor
* [`java.lang.NullPointerException` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/NullPointerException.html)
* [JMH](https://github.com/openjdk/jmh), the Java Microbenchmark Harness
* [`scala.util.control.NoStackTrace`](https://www.scala-lang.org/api/current/scala/util/control/NoStackTrace.html), the same trick as a Scala trait
