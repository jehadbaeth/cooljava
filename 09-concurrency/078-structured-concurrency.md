# 078 · Structured Concurrency (Preview)

> What `{` and `}` did for `goto`, `StructuredTaskScope` does for threads: every task you fork ends before the block that forked it, one way or another.

**Since:** Java 27 (preview, JEP 533) · **Category:** [Concurrency](../README.md#concurrency) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

Fetching two things in parallel with an `ExecutorService` looks innocent:

```java
Future<User> user = executor.submit(() -> fetchUser(id));
Future<List<Order>> orders = executor.submit(() -> fetchOrders(id));
return new Dashboard(user.get(), orders.get());
```

Now let `fetchOrders` fail after 50 ms while `fetchUser` hangs for 10 seconds. `user.get()` waits the full 10 seconds before you even look at the failure. If the request thread is interrupted, both tasks keep running, orphaned. If `fetchUser` fails, `fetchOrders` keeps burning a connection for a result nobody will read. Nothing in the code says that these two tasks belong together, so nothing treats them as a unit.

## The trick

Give concurrent subtasks the same shape as a code block. A `StructuredTaskScope` is opened in try-with-resources, subtasks are forked inside it (each one on a new virtual thread), the owner calls `join()`, and `close()` guarantees that no subtask outlives the block:

```java
try (var scope = StructuredTaskScope.open()) {
    Subtask<String> user = scope.fork(() -> fetchUser(id));
    Subtask<List<String>> orders = scope.fork(() -> fetchOrders(id));
    scope.join();                                   // fails fast, cancels the sibling
    return new Dashboard(user.get(), orders.get());
}
```

What happens when subtasks complete is a **policy**, expressed as a `Joiner`. The JDK ships the common ones:

| Factory | `join()` returns | Cancels the scope when |
|---|---|---|
| `open()` (default) | `null` (`Void`), results via `Subtask.get()` | any subtask fails |
| `Joiner.allSuccessfulOrThrow()` | `List<T>` of results, in fork order | any subtask fails |
| `Joiner.anySuccessfulOrThrow()` | the first successful `T` | any subtask succeeds |
| `Joiner.awaitAllSuccessfulOrThrow()` | `null` (`Void`) | any subtask fails |
| `Joiner.allUntil(predicate)` | `List<Subtask<T>>`, every forked subtask | the predicate is true for a completed subtask |

The seventh preview (JEP 533, Java 27) added a third type parameter, `StructuredTaskScope<T, R, R_X>`, where `R_X` is the exception type `join()` throws. By default it is `ExecutionException`, but every `...OrThrow` factory has an overload taking a `Function<Throwable, R_X>`, so `join()` can throw *your* exception type directly.

## Full example

All "remote calls" are sleeps with wide margins (tens of milliseconds against ten seconds), so the output is deterministic.

```java preview
import java.time.Duration;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.StructuredTaskScope;
import java.util.concurrent.StructuredTaskScope.Joiner;
import java.util.concurrent.StructuredTaskScope.Subtask;
import java.util.concurrent.atomic.AtomicReference;

public class StructuredDemo {

    // Simulated remote calls: sleep, then answer or fail.
    static <T> T after(long millis, T value) throws InterruptedException {
        Thread.sleep(millis);
        return value;
    }

    static <T> T failAfter(long millis, String message) throws InterruptedException {
        Thread.sleep(millis);
        throw new IllegalStateException(message);
    }

    // A ten second call that records how it ended.
    static <T> T slow(T value, AtomicReference<String> fate) throws InterruptedException {
        try {
            Thread.sleep(Duration.ofSeconds(10));
            fate.set("finished");
            return value;
        } catch (InterruptedException e) {
            fate.set("interrupted");
            throw e;
        }
    }

    record Dashboard(String user, List<String> orders) {}

    static Dashboard dashboard() throws ExecutionException, InterruptedException {
        try (var scope = StructuredTaskScope.open()) {
            Subtask<String> user = scope.fork(() -> after(30, "ada"));
            Subtask<List<String>> orders = scope.fork(() -> after(20, List.of("telescope", "tripod")));
            scope.join();
            return new Dashboard(user.get(), orders.get());
        }
    }

    static final class QuoteException extends Exception {
        QuoteException(Throwable cause) { super("no quote: " + cause.getMessage(), cause); }
    }

    // join() throws QuoteException itself: R_X is inferred from the joiner.
    static List<Integer> quotes(boolean acmeIsDown) throws QuoteException, InterruptedException {
        var joiner = Joiner.<Integer, QuoteException>allSuccessfulOrThrow(QuoteException::new);
        try (var scope = StructuredTaskScope.open(joiner)) {
            scope.fork(() -> after(60, 120));   // slowest, still first in the list
            scope.fork(() -> acmeIsDown ? failAfter(10, "ACME is down") : after(10, 99));
            scope.fork(() -> after(30, 105));
            return scope.join();
        }
    }

    public static void main(String[] args) throws Exception {
        System.out.println("1. " + dashboard());

        // 2. One failure cancels the siblings.
        var reportFate = new AtomicReference<>("not finished");
        try (var scope = StructuredTaskScope.open()) {
            scope.fork(() -> slow("report", reportFate));
            scope.fork(() -> failAfter(50, "inventory service down"));
            scope.join();
        } catch (ExecutionException e) {
            System.out.println("2. ExecutionException caused by " + e.getCause());
        }
        System.out.println("   the slow sibling was " + reportFate.get());   // close() waited for it

        // 3. A custom exception type for join().
        System.out.println("3. " + quotes(false));
        try {
            quotes(true);
        } catch (QuoteException e) {
            System.out.println("   " + e.getMessage());
        }

        // 4. First success wins, the losers are cancelled.
        var mirrorFate = new AtomicReference<>("not finished");
        try (var scope = StructuredTaskScope.open(Joiner.<String>anySuccessfulOrThrow())) {
            scope.fork(() -> failAfter(10, "mirror-1 down"));
            scope.fork(() -> after(30, "mirror-2"));
            scope.fork(() -> slow("mirror-3", mirrorFate));
            System.out.println("4. downloaded from " + scope.join());
        }
        System.out.println("   mirror-3 was " + mirrorFate.get());

        // 5. A deadline for the whole scope.
        try (var scope = StructuredTaskScope.open(Joiner.<String>allSuccessfulOrThrow(),
                config -> config.withName("pricing").withTimeout(Duration.ofMillis(100)))) {
            scope.fork(() -> slow("price", new AtomicReference<>()));
            scope.join();
        } catch (ExecutionException e) {
            System.out.println("5. timed out, cause: " + e.getCause().getClass().getSimpleName());
        }

        // 6. Stop as soon as one replica is fresh enough (lag below 5 s), then inspect every subtask.
        try (var scope = StructuredTaskScope.open(
                Joiner.<Integer>allUntil(t -> t.state() == Subtask.State.SUCCESS && t.get() < 5))) {
            scope.fork(() -> failAfter(10, "replica-1 unreachable"));
            scope.fork(() -> after(30, 40));
            scope.fork(() -> after(150, 2));
            scope.fork(() -> after(10_000, 0));
            List<Subtask<Integer>> replicas = scope.join();
            System.out.println("6. scope cancelled: " + scope.isCancelled());
            for (Subtask<Integer> replica : replicas) {
                String detail = switch (replica.state()) {
                    case SUCCESS -> "lag " + replica.get() + " s";
                    case FAILED -> replica.exception().getMessage();
                    case UNAVAILABLE -> "cancelled before it finished";
                };
                System.out.printf("   %-11s %s%n", replica.state(), detail);
            }
        }
    }
}
```

Output:

```text output
1. Dashboard[user=ada, orders=[telescope, tripod]]
2. ExecutionException caused by java.lang.IllegalStateException: inventory service down
   the slow sibling was interrupted
3. [120, 99, 105]
   no quote: ACME is down
4. downloaded from mirror-2
   mirror-3 was interrupted
5. timed out, cause: CancelledByTimeoutException
6. scope cancelled: true
   FAILED      replica-1 unreachable
   SUCCESS     lag 40 s
   SUCCESS     lag 2 s
   UNAVAILABLE cancelled before it finished
```

## How it works

* **The scope owns its threads.** `fork` starts each subtask in a new virtual thread (change that with `Configuration.withThreadFactory`). Only the thread that opened the scope may fork or join; any other thread gets a `WrongThreadException`.
* **Joiners see every completion.** `onFork` and `onComplete` are called for each subtask, and returning `true` from `onComplete` *cancels the scope*. Cancellation interrupts all unfinished subtasks and wakes up the owner in `join()`. That is case 2: the failing call cancels the scope, the ten second sibling is interrupted after 50 ms, and its `catch` block records it.
* **`close()` is the structural guarantee.** It cancels the scope if needed and then waits for every subtask thread to terminate. That is why `reportFate` and `mirrorFate` are read *after* the `try` block: by then the subtasks are provably finished. No orphan can keep running behind your back.
* **Results come back typed.** With the default policy you read `Subtask.get()` after `join()`. The other joiners hand back the result directly: a `List<Integer>` in fork order for `allSuccessfulOrThrow` (case 3 prints `120` first although it finished last), a single value for `anySuccessfulOrThrow`, and for `allUntil` the subtasks themselves, so you can look at `state()`, `get()` and `exception()` of each one.
* **`R_X` removes the unwrapping dance.** With the default policies, `join()` throws `ExecutionException` and the real failure is the cause. Passing `QuoteException::new` makes the scope a `StructuredTaskScope<Integer, List<Integer>, QuoteException>`, and javac then demands that callers handle `QuoteException`, not a generic wrapper.
* **Timeouts are cancellation too.** `withTimeout` cancels the scope when the deadline passes. The default joiners then throw from `join()` with a `CancelledByTimeoutException` as the cause, as case 5 shows. `withName` names the scope; it shows up in thread dumps.
* **The tree is observable.** Scopes nest, and `jcmd <pid> Thread.dump_to_file -format=json dump.json` prints subtask threads grouped under the scope that forked them. Scoped values bound around a scope are inherited by its subtasks (see [079](079-scoped-values.md)).

## Gotchas

* **It is a preview API, and it moved a lot.** Since its first incubator in Java 19 the API has changed shape several times: subclasses such as `ShutdownOnFailure` were replaced by `open()` plus `Joiner` in the fifth preview (Java 25), and Java 27 added `R_X` and removed `Joiner.awaitAll()`. Code written against an older preview usually does not compile on the next one. You need `--enable-preview` at compile time and at run time.
* **Join before you read.** `Subtask.get()` before `join()` throws `IllegalStateException`, and so does `get()` on a subtask that failed or was cancelled. Closing a scope after forking without ever calling `join()` throws `IllegalStateException` ("Owner did not join after forking").
* **Cancellation is interruption.** A subtask that swallows `InterruptedException`, or blocks in something that ignores interrupts, still delays `close()`. Structured concurrency guarantees that `close()` waits, not that the wait is short.
* **`fork` takes a `Callable` or a `Runnable`.** A lambda that returns a value picks the `Callable` overload; `() -> System.out.println("x")` picks `Runnable` and yields a `Subtask` whose `get()` returns `null`.
* **Don't leak the scope.** Passing a scope to code that forks from another thread fails at run time. Keep fork and join in one method, which is the whole point anyway.

## When to use it (and when not to)

Use it whenever one request fans out into a few related calls that must succeed or fail together: building a page from several services, racing replicas, scatter-gather with a deadline. Compared with `CompletableFuture.allOf`, you get cancellation of siblings for free, plain blocking code inside each subtask, and stack traces that make sense.

Today it is a preview in Java 27. JEP 543 proposes to finalize it in Java 28 without further change, and its status is "Proposed to Target", not final. Until it ships as final, keep it out of libraries and long-lived production code unless you control the JDK version and accept the flag. For unrelated background work that should outlive the request, a plain executor is still the right tool.

## Related

* [077 · Virtual Threads: A Million Threads and the Pinning Trap](077-virtual-threads.md), the threads every subtask runs on
* [079 · Scoped Values: ThreadLocal's Better Sibling](079-scoped-values.md), context that subtasks inherit automatically
* [080 · CompletableFuture Cookbook](080-completablefuture-cookbook.md), the non-structured alternative for comparison
* [048 · Try-With-Resources Tricks](../05-modern-language/048-try-with-resources-tricks.md), the language feature that gives the scope its shape

## Sources

* [JEP 533: Structured Concurrency (Seventh Preview)](https://openjdk.org/jeps/533), the Java 27 API used here
* [JEP 543: Structured Concurrency](https://openjdk.org/jeps/543), proposed finalization for Java 28
* [JEP 505: Structured Concurrency (Fifth Preview)](https://openjdk.org/jeps/505), where `open()` and `Joiner` replaced the subclasses
* Nathaniel J. Smith, [Notes on structured concurrency, or: Go statement considered harmful](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/) (2018)
