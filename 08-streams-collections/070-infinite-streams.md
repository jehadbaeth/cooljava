# 070 · Infinite Streams and Generators

> A stream that never ends is perfectly safe, right up to the moment you ask it to sort itself.

**Since:** Java 16 · **Category:** [Streams and Collections](../README.md#streams-and-collections) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

"The first 10 primes", "the first Fibonacci number above 1000", "roll a die until it shows a six". Each of these has two parts tangled together: *how to produce the next value* and *when to stop*. The loop version welds them into one block:

```java
List<Long> primes = new ArrayList<>();
for (long n = 2; primes.size() < 10; n++) {
    if (isPrime(n)) primes.add(n);
}
```

Change the stopping rule ("primes below 500", "the 10,001st prime") and you rewrite the loop. Generators separate the two: one expression describes the *whole* infinite sequence, and the stopping rule is a separate, swappable operation at the end.

## The trick

Java has three ways to make an infinite (or open-ended) stream:

```java
Stream.iterate(seed, next)              // seed, next(seed), next(next(seed)), ... forever (Java 8)
Stream.iterate(seed, hasNext, next)     // a for loop as a stream: stops when hasNext fails (Java 9)
Stream.generate(supplier)               // supplier.get(), supplier.get(), ... independent calls (Java 8)
```

Streams are **lazy**: nothing is computed until a terminal operation pulls, and a short-circuiting operation (`limit`, `takeWhile`, `findFirst`, `anyMatch`) stops pulling once it has its answer. That is the whole safety argument. An infinite source plus a short-circuiting operation is a finite computation; an infinite source plus an operation that needs *every* element is an infinite loop.

Carrying state from one element to the next is the only hard part. A record makes it painless: Fibonacci needs two numbers, so the seed is a pair.

```java
record Fib(long current, long next) {
    Fib step() { return new Fib(next, current + next); }
}
Stream.iterate(new Fib(0, 1), Fib::step).map(Fib::current)   // 0, 1, 1, 2, 3, 5, ...
```

The generators are Java 8 and 9 API; the example needs Java 16 for records and `Stream.toList()`.

## Full example

```java run
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.*;

public class InfiniteStreams {

    /** A Fibonacci step as an immutable pair: (F(n), F(n+1)). */
    record Fib(long current, long next) {
        Fib step() { return new Fib(next, current + next); }
    }

    static final AtomicInteger primeChecks = new AtomicInteger();

    static boolean isPrime(long n) {
        primeChecks.incrementAndGet();
        if (n < 2) return false;
        for (long d = 2; d * d <= n; d++) {
            if (n % d == 0) return false;
        }
        return true;
    }

    static Stream<Long> primes() {
        return Stream.iterate(2L, n -> n + 1).filter(InfiniteStreams::isPrime);
    }

    static Stream<Long> collatz(long start) {
        return Stream.iterate(start, n -> n != 1, n -> n % 2 == 0 ? n / 2 : 3 * n + 1);
    }

    public static void main(String[] args) {
        // Fibonacci as an infinite stream of pairs, projected to the first component.
        Stream<Long> fibonacci = Stream.iterate(new Fib(0, 1), Fib::step).map(Fib::current);
        System.out.println("fib:          " + fibonacci.limit(12).toList());

        System.out.println("first > 1000: " + Stream.iterate(new Fib(0, 1), Fib::step)
                .map(Fib::current).filter(n -> n > 1000).findFirst().orElseThrow());

        // Where does long run out? Overflow turns the sum negative, takeWhile notices.
        List<Long> fitsInLong = Stream.iterate(new Fib(0, 1), Fib::step)
                .map(Fib::current).takeWhile(n -> n >= 0).toList();
        System.out.println("fibs in long: " + fitsInLong.size() + ", largest " + fitsInLong.get(fitsInLong.size() - 1));

        // Primes: an infinite filter is fine as long as something downstream stops it.
        System.out.println("primes:       " + primes().limit(10).toList());
        primeChecks.set(0);
        System.out.println("10001st:      " + primes().skip(10_000).findFirst().orElseThrow()
                + " after " + primeChecks.get() + " checks");

        // limit placement changes the meaning, not just the speed.
        primeChecks.set(0);
        System.out.println("filter, limit " + primes().limit(5).toList() + " checks=" + primeChecks.get());
        primeChecks.set(0);
        System.out.println("limit, filter " + Stream.iterate(2L, n -> n + 1).limit(5)
                .filter(InfiniteStreams::isPrime).toList() + " checks=" + primeChecks.get());

        // The three-argument iterate is a for loop: it stops before emitting the element that fails.
        System.out.println("collatz(6):   " + collatz(6).toList());
        System.out.println("with the 1:   " + Stream.concat(collatz(6), Stream.of(1L)).toList());
        System.out.println("steps(27):    " + collatz(27).count());
        System.out.println("peak(27):     " + collatz(27).mapToLong(Long::longValue).max().orElseThrow());

        // takeWhile and dropWhile cut at the first failure; filter looks at everything.
        List<Integer> readings = List.of(1, 3, 5, 6, 7, 9);
        System.out.println("takeWhile odd " + readings.stream().takeWhile(n -> n % 2 == 1).toList());
        System.out.println("dropWhile odd " + readings.stream().dropWhile(n -> n % 2 == 1).toList());
        System.out.println("filter odd    " + readings.stream().filter(n -> n % 2 == 1).toList());

        // generate: every element comes from an independent supplier call. Seeded, so repeatable.
        var dice = new Random(2024);
        List<Integer> rolls = Stream.generate(() -> dice.nextInt(6) + 1).takeWhile(r -> r != 6).toList();
        System.out.println("rolls before the first six: " + rolls);

        IntStream powersOfTwo = IntStream.iterate(1, n -> n > 0, n -> n * 2);
        System.out.println("int powers of two: " + powersOfTwo.count());
    }
}
```

Output:

```text output
fib:          [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89]
first > 1000: 1597
fibs in long: 93, largest 7540113804746346429
primes:       [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
10001st:      104743 after 104742 checks
filter, limit [2, 3, 5, 7, 11] checks=10
limit, filter [2, 3, 5] checks=5
collatz(6):   [6, 3, 10, 5, 16, 8, 4, 2]
with the 1:   [6, 3, 10, 5, 16, 8, 4, 2, 1]
steps(27):    111
peak(27):     9232
takeWhile odd [1, 3, 5]
dropWhile odd [6, 7, 9]
filter odd    [1, 3, 5, 7, 9]
rolls before the first six: [1, 3, 1, 5]
int powers of two: 31
```

## How it works

* **Pull, not push.** A terminal operation asks the pipeline for one element at a time, and each element travels through every stage before the next one is produced. `primes().limit(5)` therefore runs `isPrime` on 2, 3, 4, ..., 11 and then stops: exactly 10 checks for 5 primes, no matter that the source is infinite.
* **`limit` placement is semantics, not tuning.** `filter` then `limit(5)` means "the first five primes". `limit(5)` then `filter` means "the primes among the first five numbers", which is `[2, 3, 5]` after 5 checks. Both are correct; only one is what you meant.
* **`skip` is lazy too.** `primes().skip(10_000).findFirst()` finds the 10,001st prime (104743, the answer to Project Euler problem 7) after checking every number from 2 to 104743 once, and never stores the 10,000 skipped primes.
* **Records make stateful generators honest.** Each `Fib` is immutable and `step()` returns a new one, so the stream never mutates its own seed. The pair trick works for any recurrence that looks back a fixed number of steps.
* **Overflow as a stopping rule.** `long` holds 93 Fibonacci numbers, F(0) to F(92) = 7540113804746346429. The next sum wraps around to a negative number and `takeWhile(n -> n >= 0)` stops there. Cute, and in real code `Math.addExact` (which throws) is the honest version.
* **The three-argument `iterate` is a `for` loop.** `iterate(6, n -> n != 1, next)` behaves like `for (n = 6; n != 1; n = next(n))`: the condition is tested *before* an element is emitted, so the final `1` of the Collatz sequence never appears. That is fine for counting steps (27 famously takes 111 steps and climbs to 9232), but if you want the 1, append it with `Stream.concat` or use an inclusive `takeWhile` gatherer ([069](069-stream-gatherers.md)).
* **`takeWhile` and `dropWhile` (Java 9) cut at the first failure.** On `1, 3, 5, 6, 7, 9`, `takeWhile(odd)` stops at the 6 and never sees the 7. `filter` keeps looking. That difference is what makes `takeWhile` safe on infinite streams and `filter` not.
* **`generate` calls the supplier once per element.** A seeded `Random` makes it repeatable: the example rolls four times before the first six, on every run.

## Gotchas

These pipelines never return. Do not run them:

```java
Stream.iterate(1, n -> n + 1).sorted().limit(3).toList();          // sorted() must see every element first
Stream.iterate(1, n -> n + 1).filter(n -> n < 10).toList();         // filter cannot know the numbers only grow
Stream.generate(() -> dice.nextInt(3)).distinct().limit(5).toList(); // only 3 distinct values exist, it waits for a 4th
Stream.iterate(0, n -> n + 2).takeWhile(n -> n != 7).toList();       // 7 never shows up
```

* **Stateful operations are barriers.** `sorted()` buffers the whole input before emitting anything, and `distinct()` remembers every element it has seen. On an infinite stream the first never emits and the second leaks memory forever. `distinct().limit(n)` only terminates if `n` distinct values actually exist.
* **`filter` is not a stopping rule.** Use `takeWhile` when the condition is about "from here on, nothing matches".
* **`generate` is unordered.** Its Javadoc says "infinite sequential unordered stream". In a parallel stream `generate(...).limit(n)` may return any `n` elements, and a stateful supplier (a counter, a shared `Random`) is a race. Keep generators sequential, or switch to `IntStream.range` plus a pure function of the index.
* **Mutable seeds bite.** `Stream.iterate(new int[]{0, 1}, a -> { a[1] = ...; return a; })` hands out the same array every time; anything that holds on to an element sees it change. Return a fresh value from `next`, as `Fib::step` does.
* **Boxing costs.** `Stream<Long>` boxes every number. For hot numeric generators use `LongStream.iterate` and friends, as `IntStream.iterate` does for the powers of two (31 of them fit in an `int`).

## When to use it (and when not to)

Use infinite streams whenever the *sequence* is the natural thing to describe and the stopping rule varies: test data generators, simulations with a seeded `Random`, retry delays (`iterate(100, d -> d * 2)`), pagination cursors, mathematical sequences. They compose well with `limit`, `takeWhile` and `findFirst`, and they read like the definition of the sequence.

Do not use them for tight numeric loops where a plain `for` is faster and just as clear, or when the stopping rule depends on state outside the stream. And whenever you add an operation to an infinite pipeline, ask one question: does this operation need to see the end? If yes, it never returns.

## Related

* [069 · Stream Gatherers: Custom Intermediate Operations](069-stream-gatherers.md), for windows, scans and inclusive `takeWhile` on infinite streams
* [073 · Stream Laziness Puzzlers](073-stream-laziness-puzzlers.md), the element-by-element execution order in detail
* [071 · Zipping Streams and Custom Spliterators](071-zip-and-spliterators.md), for generators that do not fit `iterate`
* [059 · Integer Overflow and Arithmetic Surprises](../07-puzzlers/059-integer-overflow.md)

## Sources

* [`java.util.stream.Stream` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/Stream.html), for `iterate`, `generate`, `takeWhile` and `dropWhile`
* [`java.util.stream` package summary: Laziness and short-circuiting](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/package-summary.html#StreamOps)
* [Creating Streams](https://dev.java/learn/api/collections-and-streams/streams/creating/), the dev.java tutorial on `iterate` and `generate`
* [Collatz conjecture](https://en.wikipedia.org/wiki/Collatz_conjecture), Wikipedia, including the famous 111 steps of 27
