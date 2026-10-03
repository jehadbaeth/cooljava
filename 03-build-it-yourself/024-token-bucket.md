# 024 · Token Bucket Rate Limiter

> No timer thread, no scheduler, no background refill. A token bucket only has to do arithmetic when somebody knocks, and the lock-free version fits in one `AtomicLong`.

**Since:** Java 17 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Your API allows each client 2 requests per second, with short bursts of up to 5 tolerated. The first idea is a counter that a scheduled task resets every second:

```java
scheduler.scheduleAtFixedRate(() -> counter.set(0), 1, 1, TimeUnit.SECONDS);
boolean tryAcquire() { return counter.incrementAndGet() <= 2; }
```

That is a *fixed window*, and it has two problems. A client can send 2 requests at 0.99 s and 2 more at 1.01 s, so 4 in 20 ms despite "2 per second". And you now run a timer per client: a million API keys means a million scheduled resets, almost all for clients that went quiet hours ago.

## The trick

A **token bucket** holds up to `capacity` tokens and gains one every `1 / rate` seconds. Each request takes a token, or is rejected if the bucket is empty. Capacity is the burst you tolerate; rate is the long-term average you allow.

The key insight is that nobody needs to add the tokens *when they arrive*. Store the time of the last refill, and when a request comes in, compute how many tokens were earned since then: `elapsed / nanosPerToken`. A bucket nobody touches costs nothing, and the lazily computed state is exactly what a timer would have produced.

The second insight makes it lock free. Instead of "tokens plus a timestamp" (two variables that must change together), store a single number: the instant at which the bucket *would be empty*. Tokens available now are `(now - emptyAt) / nanosPerToken`, capped at capacity; taking a token moves `emptyAt` forward by `nanosPerToken`. One `long`, one compare-and-set. This is the **Generic Cell Rate Algorithm (GCRA)** from ATM networking, which is a token bucket viewed from the other side.

## Full example

Both implementations together, with their interface, are 50 lines of code without blank lines and comments. The demo runs them side by side on the same fake clock and checks that they agree on every decision.

```java run
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.function.LongSupplier;

public class TokenBucketDemo {

    interface RateLimiter {
        boolean tryAcquire(int permits);
        default boolean tryAcquire() { return tryAcquire(1); }
    }

    /** The textbook version: a token count plus the time of the last refill, refilled lazily. */
    static final class SynchronizedTokenBucket implements RateLimiter {
        private final long capacity;
        private final long nanosPerToken;
        private final LongSupplier nanoTime;
        private long tokens;
        private long lastRefill;

        SynchronizedTokenBucket(long capacity, long nanosPerToken, LongSupplier nanoTime) {
            this.capacity = capacity;
            this.nanosPerToken = nanosPerToken;
            this.nanoTime = nanoTime;
            this.tokens = capacity;                                // start full
            this.lastRefill = nanoTime.getAsLong();
        }

        @Override public synchronized boolean tryAcquire(int permits) {
            long now = nanoTime.getAsLong();
            long earned = (now - lastRefill) / nanosPerToken;      // whole tokens since the last refill
            tokens = Math.min(capacity, tokens + earned);
            // Keep the unfinished fraction of the next token, unless the bucket is full.
            lastRefill = tokens == capacity ? now : lastRefill + earned * nanosPerToken;
            if (tokens < permits) return false;
            tokens -= permits;
            return true;
        }
    }

    /** Lock free: one AtomicLong holding the instant at which the bucket would be empty (GCRA). */
    static final class AtomicTokenBucket implements RateLimiter {
        private final long capacity;
        private final long nanosPerToken;
        private final LongSupplier nanoTime;
        private final AtomicLong emptyAt;

        AtomicTokenBucket(long capacity, long nanosPerToken, LongSupplier nanoTime) {
            this.capacity = capacity;
            this.nanosPerToken = nanosPerToken;
            this.nanoTime = nanoTime;
            this.emptyAt = new AtomicLong(nanoTime.getAsLong() - capacity * nanosPerToken);   // start full
        }

        @Override public boolean tryAcquire(int permits) {
            while (true) {
                long now = nanoTime.getAsLong();
                long current = emptyAt.get();
                long fullBucket = now - capacity * nanosPerToken;           // emptyAt of a full bucket
                long base = current - fullBucket > 0 ? current : fullBucket;  // max(), safe for nanoTime wrap-around
                long next = base + permits * nanosPerToken;
                if (next - now > 0) return false;                           // those tokens are not earned yet
                if (emptyAt.compareAndSet(current, next)) return true;      // else another thread won: retry
            }
        }
    }

    // ---------- Demo: a fake nanoTime ----------

    static long now = 0;

    public static void main(String[] args) throws InterruptedException {
        long nanosPerToken = 500_000_000L;                     // 2 tokens per second
        LongSupplier fakeTime = () -> now;
        RateLimiter sync = new SynchronizedTokenBucket(5, nanosPerToken, fakeTime);
        RateLimiter atomic = new AtomicTokenBucket(5, nanosPerToken, fakeTime);

        System.out.println("capacity 5, 2 tokens per second ('#' allowed, '.' rejected)");
        int[][] schedule = { {0, 7}, {500, 2}, {1250, 2}, {1500, 2}, {10_000, 7} };   // {millis, requests}
        for (int[] slot : schedule) {
            now = slot[0] * 1_000_000L;
            var bySync = new StringBuilder();
            var byAtomic = new StringBuilder();
            for (int i = 0; i < slot[1]; i++) {
                bySync.append(sync.tryAcquire() ? '#' : '.');
                byAtomic.append(atomic.tryAcquire() ? '#' : '.');
            }
            System.out.printf("  t=%6d ms  %d requests  synchronized %-7s  lock-free %-7s%n",
                    slot[0], slot[1], bySync, byAtomic);
        }

        // Random traffic, about 10 requests per second for 100 seconds, both buckets side by side.
        now = 0;
        sync = new SynchronizedTokenBucket(5, nanosPerToken, fakeTime);
        atomic = new AtomicTokenBucket(5, nanosPerToken, fakeTime);
        var random = new Random(7);
        int allowed = 0;
        boolean identical = true;
        for (int i = 0; i < 1000; i++) {
            now += random.nextLong(200_000_000L);
            boolean a = sync.tryAcquire();
            boolean b = atomic.tryAcquire();
            identical &= a == b;
            if (a) allowed++;
        }
        System.out.printf("random traffic: 1000 requests in %.1f s, allowed %d, upper bound %d, identical decisions: %b%n",
                now / 1e9, allowed, 5 + now / nanosPerToken, identical);

        // Contention: 8 threads, a frozen clock and 1000 tokens. Exactly 1000 may succeed.
        now = 0;
        for (RateLimiter limiter : List.of(new SynchronizedTokenBucket(1000, nanosPerToken, fakeTime),
                                           new AtomicTokenBucket(1000, nanosPerToken, fakeTime))) {
            var granted = new AtomicInteger();
            var threads = new ArrayList<Thread>();
            for (int t = 0; t < 8; t++) {
                threads.add(new Thread(() -> {
                    for (int i = 0; i < 10_000; i++) if (limiter.tryAcquire()) granted.incrementAndGet();
                }));
            }
            threads.forEach(Thread::start);
            for (Thread thread : threads) thread.join();
            System.out.printf("%-23s 8 threads, 80000 attempts: granted %d%n",
                    limiter.getClass().getSimpleName(), granted.get());
        }
    }
}
```

Output:

```text output
capacity 5, 2 tokens per second ('#' allowed, '.' rejected)
  t=     0 ms  7 requests  synchronized #####..  lock-free #####..
  t=   500 ms  2 requests  synchronized #.       lock-free #.
  t=  1250 ms  2 requests  synchronized #.       lock-free #.
  t=  1500 ms  2 requests  synchronized #.       lock-free #.
  t= 10000 ms  7 requests  synchronized #####..  lock-free #####..
random traffic: 1000 requests in 98.5 s, allowed 201, upper bound 202, identical decisions: true
SynchronizedTokenBucket 8 threads, 80000 attempts: granted 1000
AtomicTokenBucket       8 threads, 80000 attempts: granted 1000
```

## How it works

* **Bursts, then the rate.** At t=0 the full bucket lets 5 of 7 requests through. Half a second later exactly one token has been earned. At t=10 s the bucket has been idle for 8.5 seconds but holds 5 tokens, not the 17 it would have earned: the cap is what keeps an idle client from saving up an enormous burst.
* **The fraction is kept.** At t=1250 ms, 750 ms have passed since the last refill: one whole token, plus 250 ms of progress towards the next. `lastRefill` advances by exactly one token's worth instead of jumping to `now`, so at t=1500 ms the next token is ready. Setting `lastRefill = now` on every call is the classic bug: under steady traffic it silently throws away fractions and the real rate drops below the configured one.
* **Integer nanos, no floating point.** Expressing the rate as "nanoseconds per token" keeps all arithmetic in `long`. A `double` token count works too but drifts at the edges, and two implementations using doubles would not agree bit for bit.
* **The atomic version is the same bucket.** `emptyAt` is `lastRefill - tokens * nanosPerToken` folded into one number, and clamping it to `now - capacity * nanosPerToken` is the `Math.min(capacity, ...)`. The random traffic run shows both making identical decisions on 1000 requests, allowing 201 against a theoretical maximum of 202 (5 for the initial burst plus 2 per second).
* **Compare-and-set does the locking.** Two threads that read the same `emptyAt` both compute a `next`; only one CAS succeeds, and the loser recomputes from the new value. The frozen-clock test is deterministic despite real threads: with 1000 tokens and no refill, any correct implementation grants exactly 1000, never 1001.
* **Differences, not comparisons.** `System.nanoTime()` values are only meaningful relative to each other and may be negative or wrap around. That is why the code writes `next - now > 0` rather than `next > now`.

## Gotchas

* **`tryAcquire(n)` with `n > capacity` can never succeed.** Validate it, or the caller waits forever.
* **Pick the time source carefully.** Use `System::nanoTime` in production, never `System.currentTimeMillis()`: wall clock time jumps when NTP adjusts it, and a backwards jump would mint or destroy tokens.
* **One bucket per key means a map of buckets.** Per-client limiting needs a `ConcurrentHashMap<String, RateLimiter>` plus eviction of idle entries (a bucket that has been idle longer than `capacity * nanosPerToken` is full again and can simply be dropped).
* **Local limits are not global limits.** Ten instances behind a load balancer, each allowing 2 per second, allow 20. A cluster-wide limit needs shared state, typically Redis with an atomic script, or Bucket4j with a distributed backend.
* **Rejecting is not the only option.** Blocking callers until a token arrives turns the limiter into a throttle. Guava's `RateLimiter.acquire()` does exactly that by computing how long to sleep.

## When to use it (and when not to)

A token bucket is the right default for API rate limits, outbound call budgets and retry budgets: bursts are allowed, the average is enforced, and the state is two numbers. Both versions here are small and correct enough for a single process; the synchronized one is the easier to read and is fast enough unless you are measuring millions of calls per second.

How it compares with the other classic algorithms:

| Algorithm | State per key | Behavior |
|---|---|---|
| Token bucket / GCRA | one or two numbers | bursts up to capacity, then the rate |
| Leaky bucket as a queue | a queue and a worker | perfectly smooth output, at the cost of latency and memory |
| Fixed window counter | counter and window start | simplest; up to twice the limit across a window boundary |
| Sliding window log | one timestamp per request | exact, but memory grows with the limit |
| Sliding window counter | two counters | weights the previous window by overlap; a good approximation |

(A leaky bucket used as a *meter* rather than a queue is mathematically the mirror image of the token bucket.) For production, use [Bucket4j](https://bucket4j.com/) when you need distributed buckets or several limits at once ("100 per minute and 1000 per hour"), Guava's `RateLimiter` (still marked `@Beta`) for blocking throttles, or Resilience4j's `RateLimiter`, which splits time into fixed cycles rather than using a bucket. The toy leaves out per-key management, distributed state, metrics and blocking acquisition.

## Related

* [022 · Retry with Exponential Backoff and Jitter](022-retry-backoff.md)
* [023 · A Circuit Breaker in 80 Lines](023-circuit-breaker.md), the same compare-and-set approach applied to failure states
* [081 · A Lock-Free Stack with Compare-and-Set](../09-concurrency/081-treiber-stack.md), the CAS retry loop in its purest form
* [083 · The Starting Gun: Testing Race Conditions](../09-concurrency/083-starting-gun.md), for sharper contention tests than the one above

## Sources

* [Token bucket](https://en.wikipedia.org/wiki/Token_bucket), Wikipedia, including the leaky bucket comparison
* [Generic cell rate algorithm](https://en.wikipedia.org/wiki/Generic_cell_rate_algorithm), Wikipedia
* Brandur Leach, [Rate Limiting, Cells, and GCRA](https://brandur.org/rate-limiting)
* [Bucket4j](https://bucket4j.com/), and the [Guava `RateLimiter` Javadoc](https://guava.dev/releases/snapshot-jre/api/docs/com/google/common/util/concurrent/RateLimiter.html)
* [Resilience4j RateLimiter documentation](https://resilience4j.readme.io/docs/ratelimiter), which describes its cycle-based internals
