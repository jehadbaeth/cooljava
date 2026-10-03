# 022 · Retry with Exponential Backoff and Jitter

> Retrying in a tight loop turns one failing server into a denial of service run by your own clients. Add exponential backoff, then add randomness, and the herd disperses.

**Since:** Java 17 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

The naive retry is a loop:

```java
for (int i = 0; i < 5; i++) {
    try { return client.fetch(); }
    catch (IOException e) { Thread.sleep(100); }
}
```

It has three bugs that only show up under load:

1. **Fixed delays do not back off.** If the server is overloaded, hitting it again every 100 ms keeps it overloaded.
2. **Synchronized clients stay synchronized.** A thousand clients that failed at the same moment all sleep exactly 100 ms and all come back at the same moment. Exponential backoff alone does not fix that: they still come back together, just less often.
3. **Everything is retried.** A `400 Bad Request` will be just as bad on the fifth attempt, and an interrupt is a request to stop, not a hiccup.

And it is untestable: the only way to check the timing is to actually wait.

## The trick

Marc Brooker's 2015 AWS Architecture Blog post simulated the alternatives and gave the recipe that most AWS SDKs now implement. The delay before retry number *n* is drawn uniformly at random from zero up to an exponentially growing, capped ceiling:

```text
ceiling = min(cap, base * 2^(n-1))
sleep   = random_between(0, ceiling)          // "full jitter"
```

The exponential part spreads load *over time*; the jitter spreads clients *apart from each other*. In his simulation, plain exponential backoff was "the clear loser", while full jitter and decorrelated jitter both cut the total work dramatically.

The Java part is making it testable. The retry function takes its sleeping and its randomness as parameters: a one-method `Sleeper` interface and a `RandomGenerator`. Production passes `Thread::sleep` and a real random source; a test passes a fake sleeper that just advances a counter and a `Random` with a fixed seed. Now the entire timeline is deterministic and runs in microseconds.

## Full example

```java run
import java.io.IOException;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.Callable;
import java.util.function.*;
import java.util.random.RandomGenerator;

public class RetryDemo {

    @FunctionalInterface interface Sleeper { void sleep(Duration duration) throws InterruptedException; }

    @FunctionalInterface interface Backoff { Duration delay(int retry, RandomGenerator random); }

    record RetryPolicy(int maxAttempts, Backoff backoff, Predicate<? super Exception> retryable) {
        RetryPolicy {
            if (maxAttempts < 1) throw new IllegalArgumentException("maxAttempts must be at least 1");
        }
    }

    static Backoff exponential(Duration base, Duration cap) {
        return (retry, random) -> Duration.ofMillis(ceiling(base, cap, retry));
    }

    static Backoff fullJitter(Duration base, Duration cap) {
        return (retry, random) -> Duration.ofMillis(random.nextLong(ceiling(base, cap, retry) + 1));
    }

    // base * 2^(retry-1), capped. The shift is capped too, so a large retry count cannot overflow.
    private static long ceiling(Duration base, Duration cap, int retry) {
        return Math.min(cap.toMillis(), base.toMillis() << Math.min(retry - 1, 30));
    }

    static <T> T retry(Callable<T> action, RetryPolicy policy, Sleeper sleeper, RandomGenerator random)
            throws Exception {
        List<Exception> earlier = new ArrayList<>();
        for (int attempt = 1; ; attempt++) {
            try {
                return action.call();
            } catch (InterruptedException e) {
                throw e;                                   // a request to stop, never retried
            } catch (Exception e) {
                if (attempt >= policy.maxAttempts() || !policy.retryable().test(e)) {
                    for (Exception previous : earlier) {   // keep the whole history for the post-mortem
                        if (previous != e) e.addSuppressed(previous);
                    }
                    throw e;
                }
                earlier.add(e);
                sleeper.sleep(policy.backoff().delay(attempt, random));
            }
        }
    }

    // ---------- Demo: a fake clock, a fake sleeper and a seeded Random ----------

    static long now = 0;   // fake time in milliseconds

    static Callable<String> service(String name, int failures, Supplier<Exception> failure) {
        int[] calls = {0};
        return () -> {
            calls[0]++;
            boolean fails = calls[0] <= failures;
            System.out.printf("  t=%5d ms  %s attempt %d %s%n", now, name, calls[0], fails ? "fails" : "succeeds");
            if (fails) throw failure.get();
            return "200 OK";
        };
    }

    public static void main(String[] args) throws Exception {
        Sleeper fakeSleeper = d -> {
            System.out.printf("  t=%5d ms  sleep %d ms%n", now, d.toMillis());
            now += d.toMillis();
        };
        var random = new Random(42);
        var base = Duration.ofMillis(100);
        var cap = Duration.ofSeconds(2);
        var policy = new RetryPolicy(5, fullJitter(base, cap), e -> e instanceof IOException);

        System.out.println("flaky service, three failures then success:");
        String result = retry(service("flaky", 3, () -> new IOException("connection reset")), policy, fakeSleeper, random);
        System.out.println("  result: " + result);

        System.out.println("non-retryable failure:");
        now = 0;
        try {
            retry(service("strict", 9, () -> new IllegalArgumentException("400 Bad Request")), policy, fakeSleeper, random);
        } catch (IllegalArgumentException e) {
            System.out.println("  gave up at once: " + e.getMessage());
        }

        System.out.println("service down for good:");
        now = 0;
        try {
            retry(service("down", 99, () -> new IOException("connection refused")), policy, fakeSleeper, random);
        } catch (IOException e) {
            System.out.println("  gave up: " + e.getMessage() + ", " + e.getSuppressed().length + " earlier failures attached");
        }

        // Why jitter: 1000 clients fail at t=0 and retry three times. Count the busiest 10 ms window.
        System.out.println("delays without jitter: " + java.util.stream.IntStream.rangeClosed(1, 7)
                .mapToObj(r -> exponential(base, cap).delay(r, random).toMillis() + "ms").toList());
        for (var entry : new TreeMap<>(Map.of("1 no jitter", exponential(base, cap),
                                              "2 full jitter", fullJitter(base, cap))).entrySet()) {
            var clientsPerWindow = new HashMap<Long, Integer>();
            for (int client = 0; client < 1000; client++) {
                long t = 0;
                for (int retry = 1; retry <= 3; retry++) {
                    t += entry.getValue().delay(retry, random).toMillis();
                    clientsPerWindow.merge(t / 10, 1, Integer::sum);
                }
            }
            System.out.printf("%-13s busiest 10 ms window: %4d of 3000 retries%n",
                    entry.getKey().substring(2), Collections.max(clientsPerWindow.values()));
        }
    }
}
```

Output:

```text output
flaky service, three failures then success:
  t=    0 ms  flaky attempt 1 fails
  t=    0 ms  sleep 2 ms
  t=    2 ms  flaky attempt 2 fails
  t=    2 ms  sleep 106 ms
  t=  108 ms  flaky attempt 3 fails
  t=  108 ms  sleep 260 ms
  t=  368 ms  flaky attempt 4 succeeds
  result: 200 OK
non-retryable failure:
  t=    0 ms  strict attempt 1 fails
  gave up at once: 400 Bad Request
service down for good:
  t=    0 ms  down attempt 1 fails
  t=    0 ms  sleep 26 ms
  t=   26 ms  down attempt 2 fails
  t=   26 ms  sleep 84 ms
  t=  110 ms  down attempt 3 fails
  t=  110 ms  sleep 87 ms
  t=  197 ms  down attempt 4 fails
  t=  197 ms  sleep 368 ms
  t=  565 ms  down attempt 5 fails
  gave up: connection refused, 4 earlier failures attached
delays without jitter: [100ms, 200ms, 400ms, 800ms, 1600ms, 2000ms, 2000ms]
no jitter     busiest 10 ms window: 1000 of 3000 retries
full jitter   busiest 10 ms window:  164 of 3000 retries
```

## How it works

* **`ceiling` doubles and then flattens.** The no-jitter line shows the shape: 100, 200, 400, 800, 1600, and then the 2 second cap. The cap matters: without it, attempt 20 would sleep for over a day.
* **Full jitter draws from the whole range.** With the seeded `Random`, the flaky service sleeps 2 ms (drawn from 0 to 100), then 106 ms (0 to 200), then 260 ms (0 to 400). A 2 ms sleep looks wrong but is fine: on average the delays still grow exponentially, and an occasional near-immediate retry is exactly what keeps clients from bunching.
* **The predicate decides what is worth retrying.** `IOException` means "the network or the server had a bad moment". `IllegalArgumentException` (our stand-in for a 400 response) is the caller's fault, so the strict service is tried once.
* **Exhaustion keeps the history.** When the last attempt fails, the earlier exceptions are attached with `addSuppressed`, so a stack trace in the log shows all five failures, not just the last one.
* **The herd numbers are the whole argument.** Without jitter, all 1000 clients retry in the same 10 ms window, three times in a row. With full jitter the busiest window holds 164, about a sixth of the peak, and the rest are spread out. That is the difference between a server that recovers and one that is knocked over again the moment it comes back.
* **Fakes make time free.** `fakeSleeper` advances a counter instead of blocking, so the "service down" scenario, which would take more than half a second in real life, runs instantly and prints the same timeline every time. In production, pass `Thread::sleep` (the `Duration` overload exists since Java 19) or `d -> Thread.sleep(d.toMillis())` on older versions, and `RandomGenerator.getDefault()`.

## Gotchas

* **Only retry idempotent operations.** Retrying a `POST /payments` after a timeout can charge twice, because the first request may have succeeded. Make the operation idempotent first (an idempotency key the server deduplicates on), then retry it.
* **Retries multiply across layers.** If the UI, the gateway and the service each retry three times, one user click can become 27 calls to the database. Retry at one layer, usually the one closest to the failing dependency.
* **Bound the total time, not just the attempts.** Ten attempts with these settings can sleep for up to 11.1 seconds in the worst case, on top of the calls themselves. Pass a deadline and stop retrying when the next sleep would cross it.
* **Respect the server.** If a response carries `Retry-After`, use it instead of your own delay. If a dependency is clearly down, stop retrying altogether: that is the job of a [circuit breaker](023-circuit-breaker.md).
* **Never retry `InterruptedException`.** It means someone wants this thread to stop. The code above lets it propagate immediately, from both the action and the sleeper.
* **The same exception can be thrown twice.** Code that throws a cached, preallocated exception would make `e.addSuppressed(e)` fail with `IllegalArgumentException: Self-suppression not permitted`, which is why the loop checks `previous != e`.
* **Shared `Random` is fine, `Math.random()` in tests is not.** A hidden global random source makes the timeline impossible to reproduce. Inject it.

## When to use it (and when not to)

Use it for every call across a network to something that can fail transiently: HTTP APIs, databases, message brokers. Exponential backoff with full jitter is not a clever trick, it is the standard, and this version (37 lines of code without the demo) is genuinely shippable for a small service.

If you already depend on a resilience library, use its retry instead: [Resilience4j](https://resilience4j.readme.io/docs/retry) (`IntervalFunction.ofExponentialRandomBackoff`, which jitters around the exponential value by a randomization factor rather than drawing from zero), [Failsafe](https://failsafe.dev/retry/) or Spring Retry. They add what the toy leaves out: metrics and events, async and reactive variants, deadlines, result-based retry ("retry while the response is 503"), and integration with circuit breakers and rate limiters. Do not retry at all when the operation is not idempotent, or when a fast failure is more useful to the user than a slow success.

## Related

* [023 · A Circuit Breaker in 80 Lines](023-circuit-breaker.md), what to do when retrying stops making sense
* [024 · Token Bucket Rate Limiter](024-token-bucket.md), retry budgets are token buckets
* [096 · java.time Tricks: Clocks, Adjusters and Time Zones](../11-jdk-gems/096-java-time-tricks.md), more on injectable time
* [003 · Try: Turning Exceptions into Values](../01-functional/003-try-monad.md)

## Sources

* Marc Brooker, [Exponential Backoff And Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/), AWS Architecture Blog (2015)
* Marc Brooker, [Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/), Amazon Builders' Library
* [Resilience4j Retry documentation](https://resilience4j.readme.io/docs/retry)
* [`java.util.random.RandomGenerator` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/random/RandomGenerator.html)
