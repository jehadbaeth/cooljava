# 079 · Scoped Values: ThreadLocal's Better Sibling

> A `ThreadLocal` is a global variable with a per-thread twist and a `remove()` you will forget. A `ScopedValue` is bound for exactly one call and then simply gone.

**Since:** Java 25 · **Category:** [Concurrency](../README.md#concurrency) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Frameworks need to pass context (the current user, a request id, a transaction) through layers of code that never mention it. Adding a `user` parameter to every method between the HTTP handler and the audit log is honest but miserable, so for twenty years the answer has been `ThreadLocal`:

```java
static final ThreadLocal<String> CURRENT_USER = new ThreadLocal<>();

CURRENT_USER.set("ada");
try {
    handle(request);          // somewhere deep inside: CURRENT_USER.get()
} finally {
    CURRENT_USER.remove();    // forget this once and the next request on this thread is "ada"
}
```

JEP 506 calls out three design flaws in that approach. It is **mutable**: any code anywhere can call `set`, so you cannot tell from reading the handler which value the audit log will see. It is **unbounded**: the value lives until someone removes it, which in a thread pool means it leaks into whatever task runs next. And it is **expensive to inherit**: `InheritableThreadLocal` copies the parent's whole map into every child thread at creation, which hurts when threads are as cheap as [virtual threads](077-virtual-threads.md).

## The trick

`ScopedValue` (final in Java 25, JEP 506) binds a value for the *dynamic extent* of one method call, and that is the only way to give it a value:

```java
static final ScopedValue<String> CURRENT_USER = ScopedValue.newInstance();

ScopedValue.where(CURRENT_USER, "ada").run(() -> handle(request));
// inside handle(), on this thread, at any depth: CURRENT_USER.get() is "ada"
// after run() returns: CURRENT_USER is unbound again, nothing to clean up
```

There is no `set` and no `remove`. Code inside the scope can only *rebind* the value for a nested call, and the outer binding comes back automatically when that call returns. Data flows one way, from caller to callee, and the lifetime is visible in the code's indentation.

## Full example

```java run
import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class ScopedValuesDemo {

    // The old way.
    static final ThreadLocal<String> USER_TL = ThreadLocal.withInitial(() -> "anonymous");
    static final InheritableThreadLocal<String> TENANT_ITL = new InheritableThreadLocal<>();

    // The new way.
    static final ScopedValue<String> USER = ScopedValue.newInstance();
    static final ScopedValue<String> REQUEST_ID = ScopedValue.newInstance();

    // Deep inside the call stack, no parameters needed.
    static String audit(String action) {
        return "[" + REQUEST_ID.orElse("no-request") + "] " + USER.get() + " " + action;
    }

    static String loadReport(String name) throws IOException {
        if (name.isBlank()) throw new IOException("report name missing");
        return audit("loaded report " + name);
    }

    public static void main(String[] args) throws Exception {
        // 1. ThreadLocal leaks across tasks on a pooled thread.
        try (ExecutorService pool = Executors.newSingleThreadExecutor()) {
            pool.submit(() -> USER_TL.set("ada")).get();          // task 1 forgets remove()
            System.out.println("task 2 runs as: " + pool.submit(USER_TL::get).get());
        }

        // 2. InheritableThreadLocal copies the value into each child at creation time.
        TENANT_ITL.set("acme");
        Thread child = new Thread(() -> {
            System.out.println("child inherited: " + TENANT_ITL.get());
            TENANT_ITL.set("evil-corp");                          // only changes the child's copy
        });
        child.start();
        child.join();
        System.out.println("parent still has: " + TENANT_ITL.get());

        // 3. A scoped value exists only inside its scope.
        System.out.println("bound outside? " + USER.isBound());
        try {
            USER.get();
        } catch (java.util.NoSuchElementException e) {
            System.out.println("get() outside: " + e.getMessage());
        }

        // 4. Bind two values for one call; rebind for a nested call.
        ScopedValue.where(USER, "ada").where(REQUEST_ID, "req-42").run(() -> {
            System.out.println(audit("opened the dashboard"));
            ScopedValue.where(USER, "system").run(() -> System.out.println(audit("ran the nightly job")));
            System.out.println(audit("is back"));                // outer binding restored
        });
        System.out.println("bound after run()? " + USER.isBound());

        // 5. call() returns a value and propagates the operation's checked exception type.
        String report = ScopedValue.where(USER, "grace").call(() -> loadReport("q3"));
        System.out.println(report);
        try {
            ScopedValue.where(USER, "grace").call(() -> loadReport(" "));
        } catch (IOException e) {
            System.out.println("IOException, no wrapping: " + e.getMessage());
        }

        // 6. Plain threads started inside a scope do not inherit the binding.
        ScopedValue.where(USER, "ada").run(() -> {
            Thread worker = Thread.ofVirtual().start(
                    () -> System.out.println("new thread sees binding? " + USER.isBound()));
            try {
                worker.join();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        });
    }
}
```

Output:

```text output
task 2 runs as: ada
child inherited: acme
parent still has: acme
bound outside? false
get() outside: ScopedValue not bound
[req-42] ada opened the dashboard
[req-42] system ran the nightly job
[req-42] ada is back
bound after run()? false
[no-request] grace loaded report q3
IOException, no wrapping: report name missing
new thread sees binding? false
```

And here is what happens if you try to treat it like a `ThreadLocal`:

```java compile-fail
public class NoSetter {
    static final ScopedValue<String> USER = ScopedValue.newInstance();

    public static void main(String[] args) {
        USER.set("mallory");
    }
}
```

```text compile-error
NoSetter.java:5: error: cannot find symbol
        USER.set("mallory");
            ^
  symbol:   method set(String)
  location: variable USER of type ScopedValue<String>
1 error
```

## How it works

* **Section 1 is the bug `ThreadLocal` invites.** Task 2 should run as `anonymous`, the `withInitial` default, but the pool reuses its one thread and task 1 never called `remove()`, so task 2 runs as `ada`. In a web server, that is somebody else's session.
* **`where(key, value)` returns a `Carrier`**, an immutable list of bindings. `run(Runnable)` and `call(CallableOp)` install those bindings on the current thread, execute the operation, and remove them in a `finally`, even on exceptions. The cleanup you used to write by hand is part of the API.
* **Rebinding is a stack, not a mutation.** The nested `where(USER, "system")` pushes a new binding; when its `run` returns, the old one is visible again. The third line of section 4 prints `ada` once more, without anyone restoring anything, and `REQUEST_ID` stays `req-42` throughout because only `USER` was rebound.
* **`call` keeps checked exceptions typed.** `CallableOp<T, X extends Throwable>` declares `T call() throws X`, so `call(() -> loadReport(...))` throws `IOException` itself, not a wrapper. `run` takes a plain `Runnable`.
* **Fast reads.** Because a binding cannot change inside a scope, `get()` can cache the lookup per thread. JEP 506 says a `get()` is often as fast as reading a local variable, however deep the callee sits, and there is no per-thread map to copy when a thread starts.
* **Inheritance only where structure guarantees safety.** Section 6 shows that a thread started with `Thread.ofVirtual().start` does not see the binding. The one place bindings are inherited is a [`StructuredTaskScope`](078-structured-concurrency.md): its subtasks see the scoped values bound when the scope was opened, and since the scope cannot outlive the binding, that sharing is safe and costs nothing to copy.

## Gotchas

* **No default values on the key.** There is no `ScopedValue.withInitial`. Use `orElse(fallback)` at the read site (it rejects a `null` fallback in Java 25) or `isBound()`, and `orElseThrow(...)` for a custom exception.
* **The value itself can still be mutable.** Binding a `HashMap` makes the *reference* fixed, not the map. Bind immutable values (records, `List.of`) or you rebuild the action-at-a-distance problem you just escaped.
* **Not a replacement for every `ThreadLocal`.** A per-thread *cache* (a reusable buffer, a `MessageDigest`) needs a mutable slot that lives as long as the thread; that is still `ThreadLocal`'s job, at least on platform threads.
* **Context does not cross executors.** Submitting work to an `ExecutorService` from inside a scope drops the binding, as section 6 shows for a plain thread. Re-bind explicitly inside the task, or use structured concurrency.
* **`InheritableThreadLocal` snapshots at creation.** Section 2 shows the semantics: the child gets a copy when it is *created*, and later changes on either side are invisible to the other. With a million virtual threads that copy happens a million times.

## When to use it (and when not to)

Use scoped values for context that is set once at an entry point and only read below it: authenticated principal, request or trace id, tenant, locale, a transaction handle. That covers most framework-level `ThreadLocal` usage, and it fits virtual threads and structured concurrency naturally.

Keep `ThreadLocal` for per-thread caches and for the rare case where code deep down really must *change* what code higher up sees (and then ask whether a return value would be clearer). Don't use either to avoid passing an argument between three methods you own; a parameter is still the most honest context.

## Related

* [077 · Virtual Threads: A Million Threads and the Pinning Trap](077-virtual-threads.md), where per-thread state stops being cheap
* [078 · Structured Concurrency (Preview)](078-structured-concurrency.md), the one place scoped values are inherited
* [006 · The Reader Monad: Dependency Injection with Plain Functions](../01-functional/006-reader-monad.md), the functional way to pass context explicitly
* [048 · Try-With-Resources Tricks](../05-modern-language/048-try-with-resources-tricks.md), the old pattern for "set, then always clean up"

## Sources

* [JEP 506: Scoped Values](https://openjdk.org/jeps/506), final in Java 25
* [`java.lang.ScopedValue` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/ScopedValue.html)
* [`java.lang.InheritableThreadLocal` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/InheritableThreadLocal.html)
* [JEP 429: Scoped Values (Incubator)](https://openjdk.org/jeps/429), the original motivation and design discussion
