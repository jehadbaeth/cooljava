# 005 · The State Monad: Pure Functions That Carry State

> A random number generator with no mutable field, which still returns exactly the numbers `new Random(42)` does, and lets you replay any run from a single `long`.

**Since:** Java 16 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

`java.util.Random` is a little state machine hidden behind a mutable field. Every `nextInt()` reads the seed, computes the next one, writes it back and returns some of its bits. That is convenient right up to the moment you want to:

* replay a simulation or a game from a saved point,
* test a function that consumes randomness without mocking `Random`,
* run the same "program" against many different seeds and compare the outcomes.

All three need the state to be a *value* you can hold, copy and hand back, not a field that changes under you.

## The trick

Write every step as a pure function from the old state to a result *and* the new state, and wrap that function in a record:

```java
record State<S, A>(Function<S, Pair<A, S>> run) {
    <B> State<S, B> flatMap(Function<? super A, State<S, B>> f) {
        return new State<>(s -> {
            Pair<A, S> first = run.apply(s);
            return f.apply(first.value()).run().apply(first.state());
        });
    }
}
```

`flatMap` is the plumbing: it runs the first step, feeds its result to `f` to choose the next step, and threads the new state into it. The caller never sees a seed. Together with `pure` (return a value, leave the state alone) it is a monad, with the same laws as [001's Maybe](001-maybe-monad.md). Three tiny helpers complete the toolkit: `get` (read the state), `set` (replace it) and `modify` (transform it).

Nothing runs when you build a `State`. You get a *description* of a computation, and it only happens when you call `run.apply(initialState)`. That is what makes replay free: run the same description with the same initial state and you get the same answer, every time.

## Full example

```java run
import java.util.*;
import java.util.function.*;
import java.util.stream.*;

public class StateDemo {

    record Pair<A, S>(A value, S state) {}

    enum Unit { UNIT }

    // A State<S, A> is a function from a state to a result and the next state. Nothing else.
    record State<S, A>(Function<S, Pair<A, S>> run) {

        static <S, A> State<S, A> pure(A value) { return new State<>(s -> new Pair<>(value, s)); }
        static <S> State<S, S> get() { return new State<>(s -> new Pair<>(s, s)); }
        static <S> State<S, Unit> set(S next) { return new State<>(s -> new Pair<>(Unit.UNIT, next)); }
        static <S> State<S, Unit> modify(UnaryOperator<S> f) { return new State<>(s -> new Pair<>(Unit.UNIT, f.apply(s))); }

        <B> State<S, B> flatMap(Function<? super A, State<S, B>> f) {
            return new State<>(s -> {
                Pair<A, S> first = run.apply(s);
                return f.apply(first.value()).run().apply(first.state());
            });
        }

        <B> State<S, B> map(Function<? super A, ? extends B> f) { return flatMap(a -> pure(f.apply(a))); }

        A eval(S initial) { return run.apply(initial).value(); }
    }

    static <S, A> State<S, List<A>> replicate(int n, State<S, A> step) {
        State<S, List<A>> program = State.pure(List.of());
        for (int i = 0; i < n; i++) {
            program = program.flatMap(list -> step.map(x -> Stream.concat(list.stream(), Stream.of(x)).toList()));
        }
        return program;
    }

    // java.util.Random's generator, exactly as its Javadoc specifies it, as a pure transition.
    static final long MULTIPLIER = 0x5DEECE66DL, ADDEND = 0xBL, MASK = (1L << 48) - 1;

    static long seed(long userSeed) { return (userSeed ^ MULTIPLIER) & MASK; }   // what new Random(seed) does

    static State<Long, Integer> next(int bits) {
        return new State<>(seed -> {
            long nextSeed = (seed * MULTIPLIER + ADDEND) & MASK;
            return new Pair<>((int) (nextSeed >>> (48 - bits)), nextSeed);
        });
    }

    static final State<Long, Integer> NEXT_INT = next(32);

    // Random.nextInt(bound), rejection loop included: a retry is just a recursive flatMap.
    static State<Long, Integer> nextInt(int bound) {
        if ((bound & (bound - 1)) == 0) return next(31).map(r -> (int) ((bound * (long) r) >> 31));
        return next(31).flatMap(u -> u - (u % bound) + (bound - 1) < 0 ? nextInt(bound) : State.pure(u % bound));
    }

    record Roll(List<Integer> dice, int total) {}

    static final State<Long, Integer> DIE = nextInt(6).map(n -> n + 1);
    static final State<Long, Roll> THREE_DICE =
            DIE.flatMap(a -> DIE.flatMap(b -> DIE.map(c -> new Roll(List.of(a, b, c), a + b + c))));

    // A stack machine with get, set and modify. The state is an immutable list, top first.
    static State<List<Integer>, Unit> push(int x) {
        return State.modify(stack -> Stream.concat(Stream.of(x), stack.stream()).toList());
    }

    static final State<List<Integer>, Integer> POP = State.<List<Integer>>get()
            .flatMap(stack -> State.set(stack.subList(1, stack.size())).map(u -> stack.get(0)));

    static State<List<Integer>, Unit> rpn(String program) {
        State<List<Integer>, Unit> machine = State.pure(Unit.UNIT);
        for (String token : program.split(" ")) {
            State<List<Integer>, Unit> step = switch (token) {
                case "+" -> POP.flatMap(b -> POP.flatMap(a -> push(a + b)));
                case "*" -> POP.flatMap(b -> POP.flatMap(a -> push(a * b)));
                default -> push(Integer.parseInt(token));
            };
            machine = machine.flatMap(u -> step);
        }
        return machine;
    }

    public static void main(String[] args) {
        Random classic = new Random(42);
        System.out.println("pure:   " + replicate(4, NEXT_INT).eval(seed(42)));
        System.out.println("Random: " + IntStream.range(0, 4).map(i -> classic.nextInt()).boxed().toList());

        Random classicDice = new Random(31337);
        System.out.println("pure nextInt(6):   " + replicate(10, nextInt(6)).eval(seed(31337)));
        System.out.println("Random nextInt(6): " + IntStream.range(0, 10).map(i -> classicDice.nextInt(6)).boxed().toList());

        // A program is a value: run it, replay it, run it with another seed.
        Pair<Roll, Long> first = THREE_DICE.run().apply(seed(42));
        Pair<Roll, Long> replay = THREE_DICE.run().apply(seed(42));
        System.out.println("seed 42:      " + first.value());
        System.out.println("seed 42 again equal? " + first.equals(replay));
        System.out.println("seed 4711:    " + THREE_DICE.eval(seed(4711)));
        System.out.println("continue from the saved state: " + THREE_DICE.eval(first.state()));

        System.out.println("rpn 3 4 + 2 * -> " + rpn("3 4 + 2 *").run().apply(List.of()).state());

        // The honest part: every flatMap adds stack frames when the program finally runs.
        State<Long, Integer> heads = State.pure(0);
        for (int i = 0; i < 1_000_000; i++) {
            heads = heads.flatMap(count -> nextInt(2).map(flip -> count + flip));
        }
        try {
            System.out.println("1,000,000 flips: " + heads.eval(seed(1)));
        } catch (StackOverflowError e) {
            System.out.println("1,000,000 flips chained with flatMap: StackOverflowError");
        }

        // The pragmatic fix: keep the pure step, drive it with a loop.
        long state = seed(1);
        int count = 0;
        for (int i = 0; i < 1_000_000; i++) {
            Pair<Integer, Long> flip = nextInt(2).run().apply(state);
            count += flip.value();
            state = flip.state();
        }
        System.out.println("1,000,000 flips driven by a loop: " + count + " heads");
    }
}
```

Output:

```text output
pure:   [-1170105035, 234785527, -1360544799, 205897768]
Random: [-1170105035, 234785527, -1360544799, 205897768]
pure nextInt(6):   [5, 3, 5, 4, 0, 1, 5, 2, 3, 1]
Random nextInt(6): [5, 3, 5, 4, 0, 1, 5, 2, 3, 1]
seed 42:      Roll[dice=[3, 4, 1], total=8]
seed 42 again equal? true
seed 4711:    Roll[dice=[5, 2, 4], total=11]
continue from the saved state: Roll[dice=[3, 1, 2], total=6]
rpn 3 4 + 2 * -> [14]
1,000,000 flips chained with flatMap: StackOverflowError
1,000,000 flips driven by a loop: 499889 heads
```

## How it works

* **Bit for bit with `java.util.Random`.** The `Random` Javadoc does not just describe its generator, it *specifies* it (a 48-bit linear congruential generator with multiplier `0x5DEECE66D` and addend `0xB`, and an exact `nextInt(bound)` algorithm), precisely so that equal seeds give equal sequences on every JVM. The first four lines of output show the pure version reproducing it, both for `nextInt()` and for `nextInt(6)`. The only difference is where the seed lives.
* **`seed(42)` is `new Random(42)`'s constructor.** It applies the same initial scramble (`seed ^ multiplier`), so the user facing seed means the same thing in both worlds.
* **The rejection loop became recursion.** `Random.nextInt(bound)` discards a few over-represented values with a `for` loop that calls `next(31)` again. In `State` that is `flatMap(u -> rejected ? nextInt(bound) : pure(u % bound))`: "try again" is just choosing the same step as the continuation.
* **Replay is equality.** Running `THREE_DICE` twice on `seed(42)` gives records that are `equals`, result *and* final state. Another seed gives another roll, and feeding the final state of one run into the next continues the sequence, exactly like calling `Random` again would.
* **`get`, `set` and `modify` are the whole vocabulary.** `push` is a `modify`, `pop` is a `get` followed by a `set`, and the RPN interpreter is a fold of steps with `flatMap`. No stack object exists anywhere; the "stack" is the value threaded between steps.

## Gotchas

* **Deep chains overflow the stack.** A million `flatMap`s build a million nested functions, and running them recurses once per level. The output shows the crash. Libraries fix this by trampolining `flatMap` (see [007](007-trampolines.md)); the low tech fix is the one at the end of the example, a loop that drives the pure step. It keeps every benefit except composing the whole run as one value.
* **No do-notation.** Haskell and Scala let you write a sequence of stateful steps as if they were statements. In Java every step is another nested lambda, and three dice already form a staircase. Beyond four or five steps it stops being readable.
* **Allocation everywhere.** Every step allocates a `Pair`, a `State` and a lambda or two, and boxes the `Long` seed. Fine for game logic and tests, not for a hot loop that needs millions of random numbers per second.
* **`Unit` is a workaround.** Java has no unit type, so steps that produce nothing return an enum constant. `Void` with `null` works too, but `null` in a monad is how [001](001-maybe-monad.md)'s laws break.

## When to use it (and when not to)

It is a party trick in Java, but an instructive one. The idea underneath it is very much production grade: *make state explicit and pass it in and out*. That is how you get deterministic simulations, replayable game sessions and seed driven tests, and you can have it without the monad: a pure `Pair<A, S> step(S state)` and a loop.

Reach for the full `State` wrapper only when the steps really need to be composed as values (built up from configuration, reused in many programs). For everyday randomness use `RandomGenerator` with a fixed seed in tests. For [property-based testing](../03-build-it-yourself/026-property-based-testing.md), a pure, seedable generator is what turns "it failed once on CI" into a test case you can replay, and that is worth the ceremony.

## Related

* [001 · The Maybe Monad from Scratch](001-maybe-monad.md), for the laws this one also obeys
* [006 · The Reader Monad: Dependency Injection with Plain Functions](006-reader-monad.md), the read only cousin
* [007 · Trampolines: Stack-Safe Recursion](007-trampolines.md), the cure for the stack overflow above
* [026 · Property-Based Testing in 80 Lines](../03-build-it-yourself/026-property-based-testing.md), where seeded generators earn their keep

## Sources

* [`java.util.Random` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Random.html), which specifies the LCG and the `nextInt(bound)` algorithm
* [State Monad](https://wiki.haskell.org/State_Monad), HaskellWiki
* Philip Wadler, [Monads for functional programming](https://homepages.inf.ed.ac.uk/wadler/papers/marktoberdorf/baastad.pdf) (1995), where state is one of the motivating effects
