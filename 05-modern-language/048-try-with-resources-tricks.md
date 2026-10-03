# 048 · Try-With-Resources Tricks

> Anything with a "do this, then undo that" shape is a resource: locks, transactions, timers, temporary settings. Give it a `close()` and the compiler guarantees the undo.

**Since:** Java 22 · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Most people meet try-with-resources through files and streams, then never think about it again. Everything else keeps the old shape:

```java
lock.lock();
try {
    update();
} finally {
    lock.unlock();   // fine, until someone adds a second step to undo
}
```

With two or three undo steps, `finally` grows nested `try` blocks, swallows exceptions (see [060](../07-puzzlers/060-finally-puzzlers.md)), or forgets one. Try-with-resources does the bookkeeping for you: it closes in reverse order, never skips a close, and keeps every exception.

## The trick

Make the undo step an `AutoCloseable`, then lean on four details.

**1. A resource can be a lambda.** `AutoCloseable` has one abstract method, so `lock::unlock` fits. The catch is that `AutoCloseable.close()` is declared `throws Exception`, which forces a `catch` everywhere. Narrow it once:

```java
@FunctionalInterface
interface Scope extends AutoCloseable {
    @Override void close();       // no checked exception
}

static Scope locked(Lock lock) {
    lock.lock();
    return lock::unlock;
}
```

**2. Name it `_` when you never use it.** javac's `-Xlint:try` warns about a resource the body never references. Since Java 22 (JEP 456) the answer is an unnamed variable:

```java
try (var _ = locked(lock)) {
    update();
}
```

**3. Existing variables and `null` work too.** Since Java 9 (JEP 213) the resource can be an effectively final variable, `try (shared)`. A `null` resource is skipped on close, which makes optional resources easy.

**4. Exceptions are never lost.** If the body and a `close()` both throw, the body's exception wins and the close failures are attached to it as suppressed exceptions.

## Full example

```java run
import java.util.*;
import java.util.concurrent.locks.*;
import java.util.function.*;

public class ResourceTricks {

    /** An AutoCloseable whose close() throws nothing, so it can be a lambda and needs no catch. */
    @FunctionalInterface
    interface Scope extends AutoCloseable {
        @Override void close();
    }

    // 1. Lambdas as resources.
    static Scope locked(Lock lock) {
        lock.lock();
        return lock::unlock;
    }

    static Scope timed(String label, LongSupplier nanoClock, Consumer<String> sink) {
        long start = nanoClock.getAsLong();
        return () -> sink.accept(label + " took " + (nanoClock.getAsLong() - start) / 1_000_000 + " ms");
    }

    // A resource that logs, and can be told to fail on close.
    static final class Res implements Scope {
        private final String name;
        private final String failOnClose;

        Res(String name, String failOnClose) {
            this.name = name;
            this.failOnClose = failOnClose;
            System.out.println("  open " + name);
        }

        @Override public void close() {
            System.out.println("  close " + name);
            if (failOnClose != null) throw new IllegalStateException(failOnClose);
        }
    }

    // 2. Execute around, built on top of try-with-resources: callers cannot forget to roll back.
    static final class Tx implements Scope {
        private boolean committed;

        Tx() { System.out.println("  begin"); }
        void commit() { committed = true; System.out.println("  commit"); }
        @Override public void close() { if (!committed) System.out.println("  rollback"); }
    }

    static <T> T inTransaction(Function<Tx, T> work) {
        try (Tx tx = new Tx()) {
            T result = work.apply(tx);
            tx.commit();
            return result;
        }
    }

    public static void main(String[] args) {
        System.out.println("lock as a lambda:");
        ReentrantLock lock = new ReentrantLock();
        try (var _ = locked(lock)) {
            System.out.println("  inside, locked = " + lock.isLocked());
        }
        System.out.println("  after, locked = " + lock.isLocked());

        System.out.println("timing scope with a fake clock:");
        long[] now = {0};
        try (var _ = timed("load", () -> now[0], line -> System.out.println("  " + line))) {
            now[0] += 42_000_000;
        }

        System.out.println("reverse order, body fails, close failures are suppressed:");
        try (Res a = new Res("a", "a failed to close");
             Res b = new Res("b", null);
             Res c = new Res("c", "c failed to close")) {
            System.out.println("  body");
            throw new IllegalArgumentException("body failed");
        } catch (IllegalArgumentException e) {
            System.out.println("  caught: " + e.getMessage()
                    + ", suppressed: " + Arrays.stream(e.getSuppressed()).map(Throwable::getMessage).toList());
        }

        System.out.println("body succeeds, first close failure wins:");
        try (Res a = new Res("a", "a failed to close");
             Res c = new Res("c", "c failed to close")) {
            System.out.println("  body");
        } catch (IllegalStateException e) {
            System.out.println("  caught: " + e.getMessage()
                    + ", suppressed: " + Arrays.stream(e.getSuppressed()).map(Throwable::getMessage).toList());
        }

        System.out.println("effectively final and null resources:");
        Res shared = new Res("shared", null);
        try (shared) {
            System.out.println("  using " + shared.name);
        }
        boolean wantAudit = false;
        try (Res audit = wantAudit ? new Res("audit", null) : null) {
            System.out.println("  no audit resource, and closing it is not an NPE");
        }

        System.out.println("execute around:");
        System.out.println("  result = " + inTransaction(tx -> 6 * 7));
        try {
            inTransaction(tx -> { throw new IllegalStateException("constraint violated"); });
        } catch (IllegalStateException e) {
            System.out.println("  caught: " + e.getMessage());
        }
    }
}
```

Output:

```text output
lock as a lambda:
  inside, locked = true
  after, locked = false
timing scope with a fake clock:
  load took 42 ms
reverse order, body fails, close failures are suppressed:
  open a
  open b
  open c
  body
  close c
  close b
  close a
  caught: body failed, suppressed: [c failed to close, a failed to close]
body succeeds, first close failure wins:
  open a
  open c
  body
  close c
  close a
  caught: c failed to close, suppressed: [a failed to close]
effectively final and null resources:
  open shared
  using shared
  close shared
  no audit resource, and closing it is not an NPE
execute around:
  begin
  commit
  result = 42
  begin
  rollback
  caught: constraint violated
```

The wrong turn everyone takes first is to use plain `AutoCloseable` for the lambda. `close()` throws `Exception`, so javac insists on handling it:

```java compile-fail
public class PlainAutoCloseable {
    public static void main(String[] args) {
        try (AutoCloseable resource = () -> System.out.println("closed")) {
            System.out.println("body");
        }
    }
}
```

```text compile-error
PlainAutoCloseable.java:3: error: unreported exception Exception; must be caught or declared to be thrown
        try (AutoCloseable resource = () -> System.out.println("closed")) {
                           ^
  exception thrown from implicit call to close() on resource variable 'resource'
1 error
```

And this is the warning that `_` silences. `Named.java` declares `try (Scope held = () -> System.out.println("released"))` around a body that never mentions `held`. `Unnamed.java` is the same program with `Scope _` instead. Compile both with `-Xlint:try`, then run the second:

```shell
$ javac -Xlint:try -d out Named.java
$ javac -Xlint:try -d out Unnamed.java
$ java -cp out Unnamed
```

```text
Named.java:7: warning: [try] auto-closeable resource held is never referenced in body of corresponding try statement
        try (Scope held = () -> System.out.println("released")) {
                   ^
1 warning
working
released
```

## How it works

* **The desugaring.** `try (R r = init) { body }` closes `r` in a hidden `finally`, wrapped so that a failing `close()` never replaces the exception from the body. JLS 14.20.3.1 spells it out: the primary exception is the one from the body, and each failure from `close()` is added with `addSuppressed`.
* **Reverse order, and before `catch`.** Resources are closed last to first, and all of them are closed before the `catch` or `finally` of the same statement runs. The log shows `close c`, `close b`, `close a`, and only then `caught`. If a later resource fails to open, the earlier ones are still closed and the later ones are never created, so a failed initializer cannot leak what came before it.
* **Two failure modes.** In the first demo the body throws, so `body failed` is primary and both close failures are suppressed, in closing order (`c`, then `a`). In the second demo the body is fine, `c` closes first and fails, and `a`'s failure is attached to it. Either way you get one exception to catch and the full story on it.
* **Why `Scope` extends `AutoCloseable`.** The override with no `throws` clause is legal because an overriding method may throw less. That one line removes the `catch (Exception e)` that plain `AutoCloseable` would force on every caller. `lock::unlock` and `() -> sink.accept(...)` then work as resources, because `Scope` is a functional interface.
* **Unnamed variables.** `_` declares a variable that has no name, cannot be read, and does not trigger the `[try]` lint. It works on the resource of a try, with `var` (`var _ = locked(lock)`) or with an explicit type.
* **Execute around.** `inTransaction` wraps try-with-resources around a callback. The `Tx` resource rolls back in `close()` unless `commit()` ran, and the helper commits only when the work returns normally. Callers pass a lambda and cannot forget either half.
* **The timing helper.** `timed` returns a lambda that reads the clock again when closed. The clock is injected (`LongSupplier`), so the example prints `42 ms` deterministically. In real code pass `System::nanoTime`.

## Gotchas

* **`close()` runs even when the body throws, so it must tolerate half finished work.** A `close()` that assumes success, such as one that commits, will make things worse. The `Tx` pattern, "undo unless told otherwise", is the safe shape.
* **Do not let `close()` throw `InterruptedException`.** The `AutoCloseable` Javadoc strongly advises against it, because the exception interacts with the thread's interrupted status and runtime misbehavior is likely if it ends up suppressed.
* **A suppressed exception is easy to overlook.** Loggers print them, `getMessage()` does not. When you rethrow or wrap, keep the cause chain, or the close failures disappear from your logs.
* **`_` needs Java 22.** On Java 21 it was a preview feature, and `javac --release 21` rejects it with `unnamed variables are not supported in -source 21`. The rest of the tricks, including `try (shared)` (Java 9), work much earlier.
* **A resource variable is final.** You cannot reassign `a` inside the body, and `try (shared)` requires `shared` to be effectively final.
* **Closing twice is your problem.** `Closeable.close()` must have no effect when called again, but `AutoCloseable.close()` is only strongly encouraged to behave that way. If a resource can be closed explicitly and by the try, make `close()` idempotent.

## When to use it (and when not to)

Use it whenever an undo step exists: locks, temporary files and directories, transactions, MDC or logging context, timers, mocks that must be reset, `Arena` and `StructuredTaskScope` from the newer APIs. The `Scope` interface plus a few factory methods (`locked` and `timed` above, or a `withMdc(key, value)` of your own) gives you scoped behavior in one line with no new library.

Prefer the execute-around form (`inTransaction(tx -> ...)`) when forgetting the second half must be impossible, since the caller never touches the resource. Prefer the resource form when you need several resources in one block, or when checked exceptions need to flow through unchanged, which lambdas make awkward.

Skip it for fire-and-forget cleanup that belongs to a framework (a `@PreDestroy`, a `Cleaner`) and for resources whose lifetime is not lexical. Try-with-resources is for "acquire, use, release" inside one block.

## Related

* [060 · finally Always Wins](../07-puzzlers/060-finally-puzzlers.md), for what the old `finally` shape gets wrong
* [089 · Calling C Without JNI: The Foreign Function and Memory API](../10-jvm-performance/089-foreign-function-memory.md), where `Arena` is a resource
* [078 · Structured Concurrency (Preview)](../09-concurrency/078-structured-concurrency.md), where the scope is a resource
* [022 · Retry with Exponential Backoff and Jitter](../03-build-it-yourself/022-retry-backoff.md), another execute-around helper

## Sources

* [JLS 14.20.3: try-with-resources](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.20.3)
* [`AutoCloseable` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/AutoCloseable.html)
* [JEP 456: Unnamed Variables and Patterns](https://openjdk.org/jeps/456)
* [JEP 213: Milling Project Coin](https://openjdk.org/jeps/213), which added effectively final variables as resources
