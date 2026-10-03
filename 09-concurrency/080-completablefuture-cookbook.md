# 080 · CompletableFuture Cookbook

> Fifty-odd methods, three of which you actually need daily, and a handful of traps that only show up when something fails. Here are the recipes, with the traps labeled.

**Since:** Java 12 · **Category:** [Concurrency](../README.md#concurrency) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

`CompletableFuture` arrived in Java 8 and is still the JDK's standard way to compose asynchronous results: HTTP client responses, async database drivers and most Java SDKs hand you one. Its API is huge (`thenApply`, `thenApplyAsync`, `thenCompose`, `thenCombine`, `handle`, `whenComplete`, `exceptionally`, plus `Async` variants with and without executors), and the names do not tell you the important parts:

* which method flattens and which one nests,
* how to wait for *all* of a list and get the values back,
* which error handler recovers and which one only watches,
* what exception you actually get when a stage fails,
* and on which thread your callback runs.

## The trick

Learn the handful of shapes and their failure behavior, and treat everything else as variations:

| You have | You want | Use |
|---|---|---|
| `CF<A>` and `A -> B` | `CF<B>` | `thenApply` (map) |
| `CF<A>` and `A -> CF<B>` | `CF<B>` | `thenCompose` (flatMap) |
| `CF<A>`, `CF<B>`, `(A, B) -> C` | `CF<C>` | `thenCombine` (zip) |
| `List<CF<T>>` | `CF<List<T>>` | `allOf` plus `join` in a `thenApply` |
| a failure | a value | `exceptionally`, or `handle` for both cases |
| a failure | another async attempt | `exceptionallyCompose` (Java 12) |
| a result or a failure | a log line, result unchanged | `whenComplete` |
| no answer in time | an error or a default | `orTimeout`, `completeOnTimeout` (Java 9) |

## Full example

Every "remote call" is a `supplyAsync` on `CompletableFuture.delayedExecutor`, so delays are controlled and the output is deterministic. Thread names are normalized so the pool's numbering does not leak into the output.

```java run
import java.util.List;
import java.util.Locale;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

public class FutureCookbook {

    static final ExecutorService IO = Executors.newFixedThreadPool(4, named("io"));

    static ThreadFactory named(String prefix) {
        var counter = new AtomicInteger();
        return task -> {
            Thread thread = new Thread(task, prefix + "-" + counter.incrementAndGet());
            thread.setDaemon(true);
            return thread;
        };
    }

    // Fake remote calls that answer (or fail) after a fixed delay, on the io pool.
    static <T> CompletableFuture<T> after(long millis, T value) {
        Executor delayed = CompletableFuture.delayedExecutor(millis, TimeUnit.MILLISECONDS, IO);
        return CompletableFuture.supplyAsync(() -> value, delayed);
    }

    static <T> CompletableFuture<T> failAfter(long millis, String message) {
        Executor delayed = CompletableFuture.delayedExecutor(millis, TimeUnit.MILLISECONDS, IO);
        return CompletableFuture.supplyAsync(() -> { throw new IllegalStateException(message); }, delayed);
    }

    static CompletableFuture<Integer> userId(String name) { return after(20, name.length()); }

    static CompletableFuture<List<String>> orders(int userId) {
        return after(20, List.of("order-" + userId + "a", "order-" + userId + "b"));
    }

    static String describe(Throwable e) {
        String name = e.getClass().getSimpleName();
        return e.getMessage() == null ? name : name + "(" + e.getMessage() + ")";
    }

    static String thread() { return Thread.currentThread().getName().replaceAll("\\d+$", "N"); }

    static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            throw new IllegalStateException(e);
        }
    }

    public static void main(String[] args) throws Exception {
        // 1. Map, flatMap, zip.
        CompletableFuture<String> shout = after(10, "ada").thenApply(String::toUpperCase);
        CompletableFuture<CompletableFuture<List<String>>> nested = userId("ada").thenApply(FutureCookbook::orders);
        CompletableFuture<List<String>> flat = userId("ada").thenCompose(FutureCookbook::orders);
        CompletableFuture<String> price = after(30, 120.0).thenCombine(after(10, 0.9),
                (usd, rate) -> String.format(Locale.ROOT, "%.2f EUR", usd * rate));
        System.out.println("thenApply:      " + shout.join());
        System.out.println("thenApply(f):   a " + nested.join().getClass().getSimpleName() + " inside a future");
        System.out.println("thenCompose:    " + flat.join());
        System.out.println("thenCombine:    " + price.join());

        // 2. allOf returns CF<Void>. Collect the values yourself; order follows the input list.
        List<CompletableFuture<String>> calls = List.of(after(60, "slow"), after(10, "fast"), after(30, "medium"));
        CompletableFuture<List<String>> all = CompletableFuture.allOf(calls.toArray(new CompletableFuture[0]))
                .thenApply(ignored -> calls.stream().map(CompletableFuture::join).collect(Collectors.toList()));
        System.out.println("allOf:          " + all.join());

        // 3. anyOf: first completion wins, even a failure, and the result type is Object.
        Object winner = CompletableFuture.anyOf(after(50, "mirror-1"), after(10, "mirror-2")).join();
        System.out.println("anyOf:          " + winner);
        try {
            CompletableFuture.anyOf(failAfter(10, "mirror-1 down"), after(50, "mirror-2")).join();
        } catch (CompletionException e) {
            System.out.println("anyOf:          failed with " + describe(e.getCause()));
        }

        // 4. Timeouts complete the future; they do not stop the work behind it.
        var slowTaskFinished = new CountDownLatch(1);
        CompletableFuture<String> slow = CompletableFuture.supplyAsync(() -> {
            sleep(200);
            slowTaskFinished.countDown();
            return "fresh";
        }, IO);
        try {
            slow.orTimeout(50, TimeUnit.MILLISECONDS).join();
        } catch (CompletionException e) {
            System.out.println("orTimeout:      " + describe(e.getCause()));
        }
        System.out.println("completeOnTimeout: " + after(500, "fresh").completeOnTimeout("cached", 50, TimeUnit.MILLISECONDS).join());

        // 5. Three ways to look at a failure.
        CompletableFuture<String> broken = failAfter(10, "db down");
        CompletableFuture<String> watched = broken.whenComplete(
                (value, error) -> System.out.println("whenComplete:   saw " + describe(error)));
        try {
            watched.join();
        } catch (CompletionException e) {
            System.out.println("                ...and the failure goes on: " + describe(e.getCause()));
        }
        System.out.println("handle:         " + broken.handle((value, error) -> error == null ? value : "default").join());
        System.out.println("exceptionally:  " + broken.exceptionally(error -> "default, got a " + error.getClass().getSimpleName()).join());
        System.out.println("exceptionallyCompose: "
                + failAfter(10, "primary down").exceptionallyCompose(error -> after(10, "row from replica")).join());

        // 6. join() vs get(): same failure, different wrapper.
        try {
            broken.join();
        } catch (CompletionException e) {
            System.out.println("join() threw:   CompletionException, cause " + describe(e.getCause()));
        }
        try {
            broken.get();
        } catch (ExecutionException e) {
            System.out.println("get() threw:    ExecutionException, cause " + describe(e.getCause()));
        }

        // 7. Where does the code run?
        System.out.println("supplyAsync(f):     " + CompletableFuture.supplyAsync(FutureCookbook::thread).join());
        System.out.println("supplyAsync(f, io): " + CompletableFuture.supplyAsync(FutureCookbook::thread, IO).join());
        System.out.println("thenApply on a completed future: "
                + CompletableFuture.completedFuture("x").thenApply(x -> thread()).join());

        System.out.println("the timed-out task still finished: " + slowTaskFinished.await(1, TimeUnit.SECONDS));
        IO.shutdown();
    }
}
```

Output:

```text output
thenApply:      ADA
thenApply(f):   a CompletableFuture inside a future
thenCompose:    [order-3a, order-3b]
thenCombine:    108.00 EUR
allOf:          [slow, fast, medium]
anyOf:          mirror-2
anyOf:          failed with IllegalStateException(mirror-1 down)
orTimeout:      TimeoutException
completeOnTimeout: cached
whenComplete:   saw CompletionException(java.lang.IllegalStateException: db down)
                ...and the failure goes on: IllegalStateException(db down)
handle:         default
exceptionally:  default, got a CompletionException
exceptionallyCompose: row from replica
join() threw:   CompletionException, cause IllegalStateException(db down)
get() threw:    ExecutionException, cause IllegalStateException(db down)
supplyAsync(f):     ForkJoinPool.commonPool-worker-N
supplyAsync(f, io): io-N
thenApply on a completed future: main
the timed-out task still finished: true
```

## How it works

* **`thenApply` vs `thenCompose`** is `map` vs `flatMap`. Pass a function that itself returns a future to `thenApply` and you get the second line of output: a future of a future, which nobody wants to `join()` twice. `thenCombine` waits for two *independent* futures that already run in parallel, so the price is ready when the slower of the two is, not after both in sequence.
* **`allOf` is a barrier, not a collector.** It returns `CompletableFuture<Void>` because the inputs may have different types. Once it completes, every input is done, so calling `join()` on each inside `thenApply` never blocks. The list comes back in input order (`slow` first) even though `fast` finished first.
* **`anyOf` takes the first *completion*.** Success or failure, whichever comes first, and the result is typed `Object`. If you want "first success", create a fresh `CompletableFuture`, let each candidate `complete` it on success, and fail it only when every candidate has failed.
* **Failures arrive wrapped.** When a `supplyAsync` task throws, the future completes with a `CompletionException` whose cause is the real exception. That is why `exceptionally` printed `CompletionException` above, not `IllegalStateException`. Always unwrap with `getCause()` before deciding what went wrong.
* **The three handlers differ in what they return.** `whenComplete` is a *tap*: it sees value or error, and the stage it returns has the *same* outcome, so the failure keeps going. `handle` sees both and returns a new value. `exceptionally` only runs on failure and recovers with a value; `exceptionallyCompose` (Java 12) recovers with another future, perfect for a fallback call.
* **`join` vs `get`.** Both block. `join()` throws the unchecked `CompletionException`, which is pleasant in lambdas and streams. `get()` throws the checked `ExecutionException` plus `InterruptedException`. The cause is the same `IllegalStateException` in both cases.
* **Executors.** Without an explicit executor, `...Async` methods use `ForkJoinPool.commonPool()`. Non-async stages like `thenApply` run on whichever thread completes the previous stage, or on the *calling* thread if it is already complete, which is why the last thread line says `main`.

### A quiet change in Java 25

Up to Java 24 the Javadoc carried an exception: if the common pool's parallelism is below 2 (a container with one or two CPUs, for example), every `supplyAsync` without an executor gets a brand new thread instead. The Java 25 Javadoc dropped that clause, and the behavior changed with it. The same program, forced to parallelism 1, on Java 24:

```java run jdk=24 args="-Djava.util.concurrent.ForkJoinPool.common.parallelism=1"
import java.util.concurrent.CompletableFuture;

public class DefaultExecutor {
    public static void main(String[] args) {
        String thread = CompletableFuture.supplyAsync(() -> Thread.currentThread().getName()).join();
        System.out.println("Java " + Runtime.version().feature() + ": supplyAsync ran on " + thread);
    }
}
```

```text output
Java 24: supplyAsync ran on Thread-0
```

And on Java 25:

```java run args="-Djava.util.concurrent.ForkJoinPool.common.parallelism=1"
import java.util.concurrent.CompletableFuture;

public class DefaultExecutor {
    public static void main(String[] args) {
        String thread = CompletableFuture.supplyAsync(() -> Thread.currentThread().getName()).join();
        System.out.println("Java " + Runtime.version().feature() + ": supplyAsync ran on " + thread);
    }
}
```

```text output
Java 25: supplyAsync ran on ForkJoinPool.commonPool-worker-1
```

On a small container before Java 25, "async" quietly meant "an unbounded number of fresh platform threads". One more reason to pass an executor explicitly.

## Gotchas

* **`orTimeout` does not cancel anything.** It completes the future with a `TimeoutException`, and that is all. The last line of output shows the slow task ran to the end anyway. `cancel(true)` does not interrupt either: a `CompletableFuture` has no link to the thread computing it.
* **Never block the common pool.** It is shared by parallel streams and every library that calls `supplyAsync` without an executor, and it has only about as many threads as cores. Blocking I/O belongs on your own executor (or virtual threads: `Executors.newVirtualThreadPerTaskExecutor()` is a fine executor argument).
* **Exceptions in callbacks vanish silently** if nobody joins the resulting stage. A `thenAccept(this::save)` whose `save` throws produces a failed future that nobody looks at. End fire-and-forget chains with `whenComplete` or `exceptionally` that logs.
* **`thenApply` vs `thenApplyAsync`.** The non-async variant may run on an I/O thread of whatever library completed the future (an HTTP client selector, say). Use the `Async` variant with an executor when the callback is heavy.
* **Locale.** `String.format("%.2f", ...)` uses the default locale; on a German machine it prints `108,00`. The example passes `Locale.ROOT` for that reason.

## When to use it (and when not to)

Use `CompletableFuture` when an API already hands you one (`HttpClient.sendAsync`, async drivers), when you need to combine results from several independent calls without blocking threads, or as the glue for a small event-driven pipeline.

On Java 21 or later, for "call three services and combine", plain blocking code on [virtual threads](077-virtual-threads.md) is usually easier to read and debug, and [structured concurrency](078-structured-concurrency.md) adds the sibling cancellation that `CompletableFuture` lacks. The example compiles on Java 12 because of `exceptionallyCompose`; everything else in it works on Java 9, and the core API on Java 8.

## Related

* [077 · Virtual Threads: A Million Threads and the Pinning Trap](077-virtual-threads.md), the blocking-style alternative
* [078 · Structured Concurrency (Preview)](078-structured-concurrency.md), for fan-out with real cancellation
* [022 · Retry with Exponential Backoff and Jitter](../03-build-it-yourself/022-retry-backoff.md), which combines nicely with `exceptionallyCompose`
* [003 · Try: Turning Exceptions into Values](../01-functional/003-try-monad.md), the same success-or-failure idea without threads

## Sources

* [`CompletableFuture` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/CompletableFuture.html), including the rules for the default executor
* [JEP 266: More Concurrency Updates](https://openjdk.org/jeps/266), which added `orTimeout`, `completeOnTimeout` and `delayedExecutor` in Java 9
* Tomasz Nurkiewicz, [CompletableFuture can't be interrupted](https://nurkiewicz.com/2015/03/completablefuture-cant-be-interrupted.html) (2015)
