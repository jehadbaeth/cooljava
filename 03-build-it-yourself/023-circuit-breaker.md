# 023 · A Circuit Breaker in 80 Lines

> When a dependency is down, the kindest thing your code can do is stop calling it. Three states, one `AtomicReference`, and a clock you control.

**Since:** Java 21 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

The inventory service is down. Every request to your shop calls it anyway, waits for a two second timeout, then shows a fallback. Now every request takes two seconds, your thread pool fills up with threads waiting on a dead service, and the outage of one small dependency becomes the outage of the whole shop. Meanwhile, the inventory service, trying to restart, is hammered by thousands of requests per second and cannot get up.

Retrying makes this worse, not better (see [022](022-retry-backoff.md)). What you want is a component that *notices* the dependency is failing, fails fast for a while without calling it at all, and carefully checks whether it is back.

## The trick

Michael Nygard popularized the **circuit breaker** in *Release It!* (2007), and Martin Fowler's bliki entry made it a household name. It is a small state machine wrapped around a call:

| State | Calls | Transition |
|---|---|---|
| **Closed** | go through, failures are counted | after `threshold` consecutive failures: Open |
| **Open** | rejected at once, fallback used | after `openTimeout`: Half-Open |
| **Half-Open** | exactly one probe goes through | probe succeeds: Closed. Probe fails: Open again |

In modern Java the states are a sealed interface of records, so each state carries exactly the data it needs (`Closed` has a failure count, `Open` the instant it opened). The current state lives in an `AtomicReference`, and every transition is a compare-and-set, which makes the breaker thread-safe without a lock. Time comes from an injected `InstantSource`, so a test can jump ten seconds into the future with one assignment.

## Full example

The breaker is the `State` hierarchy, the exception and the `CircuitBreaker` class: 73 lines including blank lines, 63 without blank lines and comments.

```java run
import java.io.IOException;
import java.time.*;
import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;

public class CircuitBreakerDemo {

    sealed interface State {
        record Closed(int failures) implements State {
            @Override public String toString() { return "CLOSED(failures=" + failures + ")"; }
        }
        record Open(Instant since) implements State {
            @Override public String toString() { return "OPEN(since " + since.getEpochSecond() + "s)"; }
        }
        record HalfOpen() implements State {
            @Override public String toString() { return "HALF_OPEN"; }
        }
    }

    /** Thrown to the fallback when the breaker rejects a call. No stack trace: rejecting must be cheap. */
    static final class CircuitOpenException extends RuntimeException {
        CircuitOpenException(String message) { super(message, null, false, false); }
    }

    static final class CircuitBreaker {
        private final int failureThreshold;
        private final Duration openTimeout;
        private final InstantSource clock;
        private final AtomicReference<State> state = new AtomicReference<>(new State.Closed(0));

        CircuitBreaker(int failureThreshold, Duration openTimeout, InstantSource clock) {
            this.failureThreshold = failureThreshold;
            this.openTimeout = openTimeout;
            this.clock = clock;
        }

        State state() { return state.get(); }

        <T> T call(Callable<T> action, Function<? super Exception, ? extends T> fallback) {
            if (!tryAcquirePermission()) return fallback.apply(new CircuitOpenException("circuit is " + state()));
            T result;
            try {
                result = action.call();          // the protected call runs outside any CAS
            } catch (Exception e) {
                onFailure();
                return fallback.apply(e);
            }
            onSuccess();
            return result;
        }

        private boolean tryAcquirePermission() {
            while (true) {
                State current = state.get();
                switch (current) {
                    case State.Closed closed -> { return true; }
                    case State.HalfOpen halfOpen -> { return false; }      // a probe is already in flight
                    case State.Open(Instant since) -> {
                        if (clock.instant().isBefore(since.plus(openTimeout))) return false;
                        if (state.compareAndSet(current, new State.HalfOpen())) return true;   // one winner
                    }
                }
                // Lost the race against another thread: read the new state and decide again.
            }
        }

        private void onSuccess() {
            state.updateAndGet(s -> s instanceof State.Open ? s : new State.Closed(0));
        }

        private void onFailure() {
            Instant now = clock.instant();       // read outside: updateAndGet may run the function twice
            state.updateAndGet(s -> switch (s) {
                case State.Closed(int failures) when failures + 1 >= failureThreshold -> new State.Open(now);
                case State.Closed(int failures) -> new State.Closed(failures + 1);
                case State.HalfOpen halfOpen -> new State.Open(now);
                case State.Open open -> open;
            });
        }
    }

    // ---------- Demo: a manual clock and a service we can switch off ----------

    static Instant now = Instant.EPOCH;
    static boolean healthy = true;
    static int serviceCalls = 0;

    static String inventory() throws IOException {
        serviceCalls++;
        if (!healthy) throw new IOException("timeout");
        return "42 in stock";
    }

    static void request(CircuitBreaker breaker, Callable<String> action) {
        String answer = breaker.call(action, e -> "fallback (" + e.getMessage() + ")");
        System.out.printf("t=%3ds  %-48s -> %s, service calls so far: %d%n",
                now.getEpochSecond(), answer, breaker.state(), serviceCalls);
    }

    public static void main(String[] args) {
        var breaker = new CircuitBreaker(3, Duration.ofSeconds(10), () -> now);
        Callable<String> call = CircuitBreakerDemo::inventory;

        request(breaker, call);
        healthy = false;
        System.out.println("-- inventory goes down");
        for (int i = 0; i < 5; i++) {
            now = now.plusSeconds(1);
            request(breaker, call);
        }

        System.out.println("-- 10 seconds after opening: one probe, still down");
        now = Instant.ofEpochSecond(13);
        request(breaker, call);
        now = now.plusSeconds(1);
        request(breaker, call);

        System.out.println("-- inventory recovers; the next probe closes the circuit");
        healthy = true;
        now = Instant.ofEpochSecond(23);
        request(breaker, () -> {
            // While this probe is in flight, any other call is rejected, even from the same thread.
            request(breaker, call);
            return inventory();
        });
        now = now.plusSeconds(1);
        request(breaker, call);
    }
}
```

Output:

```text output
t=  0s  42 in stock                                      -> CLOSED(failures=0), service calls so far: 1
-- inventory goes down
t=  1s  fallback (timeout)                               -> CLOSED(failures=1), service calls so far: 2
t=  2s  fallback (timeout)                               -> CLOSED(failures=2), service calls so far: 3
t=  3s  fallback (timeout)                               -> OPEN(since 3s), service calls so far: 4
t=  4s  fallback (circuit is OPEN(since 3s))             -> OPEN(since 3s), service calls so far: 4
t=  5s  fallback (circuit is OPEN(since 3s))             -> OPEN(since 3s), service calls so far: 4
-- 10 seconds after opening: one probe, still down
t= 13s  fallback (timeout)                               -> OPEN(since 13s), service calls so far: 5
t= 14s  fallback (circuit is OPEN(since 13s))            -> OPEN(since 13s), service calls so far: 5
-- inventory recovers; the next probe closes the circuit
t= 23s  fallback (circuit is HALF_OPEN)                  -> HALF_OPEN, service calls so far: 5
t= 23s  42 in stock                                      -> CLOSED(failures=0), service calls so far: 6
t= 24s  42 in stock                                      -> CLOSED(failures=0), service calls so far: 7
```

## How it works

* **States are values.** `Closed(2)` and `Open(since 3s)` are immutable records. A transition never mutates a state; it swaps the whole reference for a new one. That is what makes compare-and-set enough: either your swap wins, or someone else changed the state first and you look again.
* **Exactly one probe.** When the open timeout has passed, every caller that notices tries `compareAndSet(open, new HalfOpen())`. Only one CAS can succeed against the same `Open` instance, so only one probe reaches the service. Everyone else sees `HalfOpen` and is rejected. The nested call in the demo proves it deterministically: it runs while the probe is in flight, gets the fallback, and does not increase the service call count.
* **The slow part runs outside the atomic part.** `updateAndGet` may call its function several times under contention, so the function must be pure: no clock reads, no logging, and certainly not the protected call itself. That is why `onFailure` reads the clock first.
* **Rejection is cheap.** `CircuitOpenException` passes `writableStackTrace = false` to its superclass, so rejecting a call costs no stack walk. That matters exactly when the breaker is open and rejecting thousands of calls a second (see [092](../10-jvm-performance/092-cheap-exceptions.md)).
* **Reading the output:** three timeouts open the circuit at t=3s, after which the calls at t=4s and t=5s get the fallback at once while the service call count stays at 4. At t=13s the single probe fails and reopens the circuit (note the new `since`). At t=23s there are two lines: the first is the nested call, rejected because the probe is in flight, and the second is the probe itself, which succeeds and closes the circuit. Seven requests during the outage cost only four calls to the dead service.
* **`InstantSource` is the smallest clock.** It has a single abstract method, `instant()`, so the test clock is the lambda `() -> now`. In production pass `Clock.systemUTC()`, since every `Clock` is an `InstantSource`.

## Gotchas

* **Consecutive failures are a crude signal.** A dependency that fails twice, succeeds once and repeats never opens this breaker (threshold 3), although two thirds of its calls fail. Production breakers use a sliding window over the last N calls or the last N seconds and open on a failure *rate*, usually with a minimum number of calls so that one failure out of one call does not count as 100%.
* **Slow is the new down.** A dependency that answers in 30 seconds is worse than one that fails at once. Give every protected call a timeout, and consider counting slow calls as failures. Without a timeout, a probe that hangs keeps this breaker half-open forever.
* **Decide what counts as a failure.** A `404` or a validation error is the caller's problem, not the dependency's. Count only the exceptions that indicate the dependency is unhealthy, or a bad client can open the breaker for everyone.
* **One breaker per dependency,** not one per call site and not one for everything. A breaker shared by two services opens for both when either fails.
* **A fallback is a product decision.** Stale cache, a default, a degraded page or an honest error message are all valid. Silently returning wrong data is not.
* **Observe it.** A breaker that opens without anyone noticing hides an outage. Log or publish every transition.

## When to use it (and when not to)

Use a circuit breaker around every remote dependency whose failure should not take you down with it: HTTP services, payment providers, search clusters. Combine it with a timeout (always), retries with backoff (inside the breaker, so failed retries count) and bulkheads.

Do not ship this one. [Resilience4j](https://resilience4j.readme.io/docs/circuitbreaker) is the standard on the JVM: count-based and time-based sliding windows, failure *rate* and slow call thresholds, a configurable number of half-open probes and a maximum wait in half-open, extra states such as `FORCED_OPEN` and `DISABLED`, events and metrics, and decorators that compose with its retry, rate limiter and bulkhead. Netflix Hystrix, the library that made the pattern popular in Java, has been in maintenance mode since 2018, and its README points to Resilience4j. Build this version to understand the state machine, to test your fallbacks, or when a dependency-free 80 lines is genuinely all you need.

## Related

* [022 · Retry with Exponential Backoff and Jitter](022-retry-backoff.md), the breaker's natural partner
* [024 · Token Bucket Rate Limiter](024-token-bucket.md), the same lazy-time and CAS ideas applied to throughput
* [016 · State Machines with Enums and Sealed Types](../02-patterns/016-state-machines.md)
* [092 · Cheap Exceptions: The Cost of a Stack Trace](../10-jvm-performance/092-cheap-exceptions.md)

## Sources

* Martin Fowler, [CircuitBreaker](https://martinfowler.com/bliki/CircuitBreaker.html) (2014), which credits Michael Nygard's *Release It!*
* Michael T. Nygard, [Release It! Second Edition](https://pragprog.com/titles/mnee2/release-it-second-edition/) (Pragmatic Bookshelf, 2018)
* [Resilience4j CircuitBreaker documentation](https://resilience4j.readme.io/docs/circuitbreaker)
* [Netflix Hystrix README](https://github.com/Netflix/Hystrix), including the maintenance mode notice
* [`java.time.InstantSource` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/InstantSource.html)
