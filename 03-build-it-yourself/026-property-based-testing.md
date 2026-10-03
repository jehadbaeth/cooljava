# 026 · Property-Based Testing in 80 Lines

> Stop inventing test inputs. State a rule, let a seeded `Random` throw a hundred cases at it, and then shrink the ugly counterexample it finds down to the smallest one that still fails.

**Since:** Java 21 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Example-based tests check the cases you thought of:

```java
assertEquals(1_000, toMillis(1));
assertEquals(60_000, toMillis(60));
assertEquals(3_600_000, toMillis(3_600));
```

All green. And `toMillis` is still broken, because the bug lives in a case nobody wrote down. The tests share a blind spot with the code: they were written by the same person, on the same afternoon, with the same assumptions.

## The trick

**Property-based testing** flips the job around. You state a rule that must hold for *every* input (a *property*), and the framework generates the inputs. Koen Claessen and John Hughes made the idea famous with Haskell's QuickCheck in 2000, and the core of it fits in a few dozen lines of Java:

* **`Gen<T>`** makes a random `T` from a seeded `Random`, so every run is reproducible from one number.
* **`forAll(gen, property)`** draws 100 values and stops at the first one that breaks the property.
* **Shrinking** is the part that makes it useful. A random counterexample looks like `[412, 87, 950, 13, 977]` or `73519248`, and you would rather debug `[0, 1]` or the exact number where things start to go wrong. So each generator also knows how to propose *smaller* versions of a value, and the runner keeps taking any smaller candidate that still fails until none does.

The shrinker for integers is a binary search toward zero, borrowed from QuickCheck: try `0`, then `n - n/2`, `n - n/4`, and so on down to `n - 1`. Taking the first candidate that still fails at least halves the distance to the boundary each round, so a failure that starts at "every value from B upward" shrinks to exactly B. Lists shrink by dropping chunks first (half the list, a quarter, single elements), then by shrinking one element at a time, so length is minimized before values.

## Full example

The library is the `Gen` record, the `Result` type, `forAll`, `firstFailing` and `holds`: 68 lines without blank lines and comments. The rest is the demo.

```java run
import java.util.*;
import java.util.function.*;

public class PropertyDemo {

    /** A generator makes a random T and proposes smaller versions of a given T. */
    record Gen<T>(Function<Random, T> generator, Function<T, List<T>> shrinker) {

        T generate(Random random) { return generator.apply(random); }
        List<T> shrink(T value) { return shrinker.apply(value); }

        static Gen<Integer> ints(int min, int max) {
            return new Gen<>(r -> r.nextInt(min, max + 1),
                    n -> towardZero(n).stream().filter(c -> c >= min && c <= max).toList());
        }

        // 0 first, then n - n/2, n - n/4, ..., n - 1: a binary search for the failure boundary.
        static List<Integer> towardZero(int n) {
            var candidates = new ArrayList<Integer>();
            if (n != 0) candidates.add(0);
            for (int d = n / 2; d != 0; d /= 2) candidates.add(n - d);
            return candidates;
        }

        static <T> Gen<List<T>> lists(Gen<T> element, int maxSize) {
            return new Gen<>(r -> {
                var list = new ArrayList<T>();
                int size = r.nextInt(maxSize + 1);
                for (int i = 0; i < size; i++) list.add(element.generate(r));
                return List.copyOf(list);
            }, list -> shrinkList(list, element));
        }

        // Shorter lists first (drop chunks of size n, n/2, ..., 1), then smaller elements.
        static <T> List<List<T>> shrinkList(List<T> list, Gen<T> element) {
            var candidates = new ArrayList<List<T>>();
            for (int chunk = list.size(); chunk > 0; chunk /= 2) {
                for (int from = 0; from + chunk <= list.size(); from += chunk) {
                    var shorter = new ArrayList<>(list.subList(0, from));
                    shorter.addAll(list.subList(from + chunk, list.size()));
                    candidates.add(shorter);
                }
            }
            for (int i = 0; i < list.size(); i++) {
                for (T smaller : element.shrink(list.get(i))) {
                    var copy = new ArrayList<>(list);
                    copy.set(i, smaller);
                    candidates.add(copy);
                }
            }
            return candidates;
        }
    }

    sealed interface Result<T> {
        record Passed<T>(int tests) implements Result<T> {}
        record Falsified<T>(int failedOnTest, T original, T minimal, int shrinkSteps) implements Result<T> {}
    }

    static <T> Result<T> forAll(long seed, int tests, Gen<T> gen, Predicate<T> property) {
        var random = new Random(seed);
        for (int i = 1; i <= tests; i++) {
            T value = gen.generate(random);
            if (holds(property, value)) continue;
            // Greedy shrinking: keep taking the first smaller candidate that still fails.
            T minimal = value;
            int steps = 0;
            for (Optional<T> next; (next = firstFailing(gen.shrink(minimal), property)).isPresent(); steps++) {
                minimal = next.get();
            }
            return new Result.Falsified<>(i, value, minimal, steps);
        }
        return new Result.Passed<>(tests);
    }

    static <T> Optional<T> firstFailing(List<T> candidates, Predicate<T> property) {
        return candidates.stream().filter(c -> !holds(property, c)).findFirst();
    }

    static <T> boolean holds(Predicate<T> property, T value) {
        try {
            return property.test(value);
        } catch (RuntimeException e) {
            return false;                               // a crash is a counterexample too
        }
    }

    // ---------- Demo: two bugs nobody wrote an example for, and one fix ----------

    // Bug 1: an int overflow, but only for long enough timeouts.
    static int toMillis(int seconds) { return seconds * 1000; }

    // Bug 2: an off-by-one loop bound never looks at the last element.
    static int max(List<Integer> xs) {
        int best = xs.get(0);
        for (int i = 1; i < xs.size() - 1; i++) best = Math.max(best, xs.get(i));
        return best;
    }

    static int maxFixed(List<Integer> xs) {
        int best = xs.get(0);
        for (int i = 1; i < xs.size(); i++) best = Math.max(best, xs.get(i));
        return best;
    }

    static final long SEED = 42;

    static <T> void check(String name, Gen<T> gen, Predicate<T> property) {
        System.out.println(name + "   (seed " + SEED + ")");
        switch (forAll(SEED, 100, gen, property)) {
            case Result.Passed<T>(int tests) -> System.out.println("  OK, passed " + tests + " tests");
            case Result.Falsified<T>(int test, T original, T minimal, int steps) -> {
                List<T> smaller = gen.shrink(minimal);
                long stillFailing = smaller.stream().filter(c -> !holds(property, c)).count();
                System.out.println("  falsified on test " + test + ": " + original);
                System.out.println("  shrunk in " + steps + " steps to:    " + minimal);
                System.out.println("  " + smaller.size() + " smaller candidates of that, " + stillFailing + " still fail");
            }
        }
    }

    public static void main(String[] args) {
        Gen<Integer> timeouts = Gen.ints(0, 100_000_000);      // anything up to about three years
        check("toMillis(s) == s * 1000L", timeouts, s -> toMillis(s) == s * 1000L);
        int boundary = Integer.MAX_VALUE / 1000 + 1;          // computed independently, for comparison
        System.out.printf("  first overflowing timeout by arithmetic: %d s, which is %.1f days%n",
                boundary, boundary / 86_400.0);

        Gen<List<Integer>> lists = Gen.lists(Gen.ints(-1000, 1000), 12);
        check("max(xs) == Collections.max(xs)", lists,
                xs -> xs.isEmpty() || max(xs) == Collections.max(xs));
        check("maxFixed(xs) == Collections.max(xs)", lists,
                xs -> xs.isEmpty() || maxFixed(xs) == Collections.max(xs));
    }
}
```

Output:

```text output
toMillis(s) == s * 1000L   (seed 42)
  falsified on test 1: 62431115
  shrunk in 12 steps to:    2147484
  22 smaller candidates of that, 0 still fail
  first overflowing timeout by arithmetic: 2147484 s, which is 24.9 days
max(xs) == Collections.max(xs)   (seed 42)
  falsified on test 8: [-215, 895, -120, -104, -459, -627, 501, -370, 977]
  shrunk in 14 steps to:    [0, 1]
  4 smaller candidates of that, 0 still fail
maxFixed(xs) == Collections.max(xs)   (seed 42)
  OK, passed 100 tests
```

## How it works

* **A generator is two functions.** `generator` makes a value from a `Random`, `shrinker` lists smaller neighbors of a value. `Gen.lists` builds both of its functions out of the element generator's, which is the whole trick behind composable generators: a `Gen<List<Integer>>` knows how to shrink its integers because `Gen<Integer>` does.
* **One seed, one run.** `forAll` creates `new Random(seed)` and draws every case from it, so the same seed always produces the same hundred inputs, the same failure and the same shrink path. That is why the output above is stable enough to be checked by a build, and why real frameworks print the seed of a failing run: paste it back in and you replay the exact failure.
* **Reading the first result.** The very first random timeout, 62431115 seconds, already overflows. Twelve shrink steps walk it down to exactly 2147484, and the independent arithmetic two lines later agrees: `2147484 * 1000` is just past `Integer.MAX_VALUE`, while `2147483 * 1000` still fits. The proof line says that none of the 22 smaller candidates of `2147484`, including `2147483`, still fails. That is 24.9 days, so every test that used timeouts of minutes or hours was green. The binary search is what makes this land on the boundary instead of somewhere near it. A shrinker that only tried `0` and `n / 2` would stop at the first value whose half no longer overflows, which is not the boundary at all.
* **Reading the second result.** Test 8 produced a nine-element list ending in its maximum, 977. Fourteen shrink steps drop elements and then shrink the survivors toward zero, ending at `[0, 1]`: the larger number last, which is the bug in one line, because the loop never reads the last element. One-element lists pass (the loop body never matters), so two elements is as short as a counterexample gets, and the proof line shows that none of the four smaller neighbors (`[]`, `[1]`, `[0]` and `[0, 0]`) still fails.
* **Exceptions are failures.** `holds` treats a `RuntimeException` as a broken property, so a function that crashes on some input shrinks to the smallest crashing input. Remove the `xs.isEmpty() ||` guard and the property shrinks to `[]`, because `max` calls `xs.get(0)`.
* **The fixed version passes all 100 cases.** That is evidence, not proof. A hundred random cases can miss a rare bug, which is why frameworks run more cases in CI, mix in edge cases on purpose and let you raise the count for a suspicious property.

## Gotchas

* **Greedy shrinking finds a local minimum.** The runner stops when no *single* shrink step still fails. That is the global minimum when failures are "monotone", as both bugs here are (every bigger timeout overflows; any list that ends in its unique maximum fails). It is not always: a sort that drops duplicates fails on `[37, 37]`, and shrinking one element at a time can never reach `[0, 0]`, because changing either `37` alone removes the duplicate.
* **Type-based shrinking can leave the generator's domain.** Here `ints(min, max)` filters candidates back into its range, but a generator built with `map` or a filter would need its own shrinker, and a naive one proposes values the generator could never have produced (an odd number from an "even numbers" generator). Hypothesis and jqwik avoid this with *integrated shrinking*: they shrink the random choices that built the value, so every shrunk value is one the generator could have produced.
* **The property can be the bug.** `reverse(xs).equals(xs)` fails and shrinks to a two-element list, not because `reverse` is broken but because the property is wrong. That is still a useful answer: the counterexample tells you which.
* **Properties need an oracle or an invariant.** The demo compares with `s * 1000L` and `Collections.max`. Without a trusted reference, use invariants instead: round trips (`parse(print(x)).equals(x)`), idempotence (`sort(sort(xs))` equals `sort(xs)`), or "the output is a permutation of the input".
* **Random cases favor the middle.** A uniform `Random` almost never produces `Integer.MIN_VALUE`, an empty string or a list of equal elements. Real frameworks inject those edge cases deliberately.

## When to use it (and when not to)

Property-based tests shine for pure functions with a crisp rule: parsers and printers (round trips), encoders, sorting and collection utilities, arithmetic on money or time, and anything with a simple reference implementation to compare against. They complement example tests; they do not replace the examples that document intent.

Do not ship this one. For JUnit 5 projects, [jqwik](https://jqwik.net/) is the standard Java answer: `@Property` methods with `@ForAll` parameters, generators for every common type, integrated shrinking, edge cases, statistics, stateful testing, and the seed of every failure. Be aware that its README currently describes it as in "pure maintenance mode": upstream updates and crucial fixes continue, new features do not, which is acceptable for a test-scope dependency but worth knowing. The toy leaves out size control (QuickCheck starts with small values and grows them), edge cases, integrated shrinking, combinators such as `map`, `flatMap` and `filter`, generators for records and strings, statistics about what was generated, and stateful testing of sequences of operations. Build this version to understand what the frameworks do for you, or when a 70-line helper in a test folder is all a small project needs.

## Related

* [022 · Retry with Exponential Backoff and Jitter](022-retry-backoff.md), another place where a seeded `Random` turns randomness into a deterministic test
* [027 · A JSON Parser with Sealed Types](027-json-parser.md), whose round trip is a textbook property
* [059 · Integer Overflow and Arithmetic Surprises](../07-puzzlers/059-integer-overflow.md), the bug class the first property caught
* [083 · The Starting Gun: Testing Race Conditions](../09-concurrency/083-starting-gun.md), for the bugs random inputs cannot reach

## Sources

* Koen Claessen and John Hughes, [QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs](https://www.cs.tufts.edu/~nr/cs257/archive/john-hughes/quick.pdf) (ICFP 2000)
* [`shrinkIntegral` in QuickCheck's Test.QuickCheck.Arbitrary](https://hackage.haskell.org/package/QuickCheck/docs/Test-QuickCheck-Arbitrary.html), the integer shrinking strategy used here
* David R. MacIver, [Integrated vs type based shrinking](https://hypothesis.works/articles/integrated-shrinking/) (Hypothesis blog, 2016)
* [jqwik User Guide](https://jqwik.net/docs/current/user-guide.html) and the [jqwik README](https://github.com/jqwik-team/jqwik) with its maintenance mode notice
