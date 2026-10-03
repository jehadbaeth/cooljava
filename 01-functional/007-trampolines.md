# 007 · Trampolines: Stack-Safe Recursion

> The JVM will not turn your tail call into a loop, so you do it yourself: instead of calling the next step, *return* it, and let a `while` loop do the bouncing.

**Since:** Java 21 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

Recursion is the natural way to write a lot of algorithms, and every recursive call costs a stack frame. A thread's stack is small (typically 1 or 2 MB, set by `-Xss`), so a recursion depth in the hundreds of thousands ends the same way every time:

```java
static long sum(long n) { return n == 0 ? 0 : n + sum(n - 1); }

sum(1_000_000);   // java.lang.StackOverflowError
```

The usual functional advice is "make it tail recursive": pass an accumulator so the recursive call is the very last thing the method does. In Scheme, Scala (`@tailrec`) or Kotlin (`tailrec`) the compiler then turns the call into a jump. In Java, nothing happens. Here is what javac produces for the tail recursive version:

```shell
cat > Tail.java <<'EOF'
public class Tail {
    static long sum(long n, long acc) {
        return n == 0 ? acc : sum(n - 1, acc + n);
    }
}
EOF
javac Tail.java && javap -c Tail.class | sed -n '/static long sum/,$p'
```

```text
  static long sum(long, long);
    Code:
         0: lload_0
         1: lconst_0
         2: lcmp
         3: ifne          10
         6: lload_2
         7: goto          19
        10: lload_0
        11: lconst_1
        12: lsub
        13: lload_2
        14: lload_0
        15: ladd
        16: invokestatic  #7                  // Method sum:(JJ)J
        19: lreturn
}
```

A real `invokestatic` at offset 16, followed by `lreturn`. A tail call, compiled as a plain call. HotSpot's JIT does not eliminate it either, and the original Project Loom proposal stated outright that "it is not the goal of this project to add an automatic tail-call optimization to the JVM". Mutual recursion (`isEven` calls `isOdd` calls `isEven`) is even further out of reach, since no compiler can turn it into a local loop.

## The trick

Do not make the recursive call. *Describe* it and return the description:

```java
sealed interface Trampoline<T> {
    record Done<T>(T value) implements Trampoline<T> {}                    // finished, here is the answer
    record More<T>(Supplier<Trampoline<T>> next) implements Trampoline<T> {} // not yet, call me again
}

static Trampoline<Long> sum(long n, long acc) {
    return n == 0 ? new Done<>(acc) : new More<>(() -> sum(n - 1, acc + n));
}
```

`sum` now returns immediately: either with the answer, or with a lambda that computes the next step. A small `while` loop calls `next.get()` over and over until it lands on a `Done`. Each bounce returns before the next one starts, so the stack depth stays constant, and the recursion lives on the heap as a chain of short-lived lambdas.

That handles tail calls. For recursion that does work *after* the recursive call returns (`n + sum(n - 1)`), add a third case, `FlatMap`, which means "run this trampoline, then feed its result to this function". The run loop has to reassociate nested `FlatMap`s so they never pile up on the Java stack. Rúnar Bjarnason's "Stackless Scala With Free Monads" is the classic write-up of exactly this design.

## Full example

```java run
import java.util.function.*;

public class TrampolineDemo {

    sealed interface Trampoline<T> {
        record Done<T>(T value) implements Trampoline<T> {}
        record More<T>(Supplier<Trampoline<T>> next) implements Trampoline<T> {}
        record FlatMap<A, T>(Trampoline<A> source, Function<A, Trampoline<T>> f) implements Trampoline<T> {
            // One step of evaluation. Never recurses: it always returns a new, smaller problem.
            Trampoline<T> step() {
                return switch (source) {
                    case Done<A>(A value) -> f.apply(value);
                    case More<A>(var next) -> new FlatMap<>(next.get(), f);
                    case FlatMap<?, A> inner -> inner.reassociate(f);
                };
            }

            // (source >>= f) >>= g  becomes  source >>= (x -> f(x) >>= g): left nesting turned right.
            <R> Trampoline<R> reassociate(Function<T, Trampoline<R>> g) {
                return new FlatMap<>(source, a -> new FlatMap<>(f.apply(a), g));
            }
        }

        static <T> Trampoline<T> done(T value) { return new Done<>(value); }
        static <T> Trampoline<T> more(Supplier<Trampoline<T>> next) { return new More<>(next); }

        default <R> Trampoline<R> flatMap(Function<T, Trampoline<R>> f) { return new FlatMap<>(this, f); }
        default <R> Trampoline<R> map(Function<T, R> f) { return flatMap(t -> done(f.apply(t))); }

        // The trampoline itself: bounce until Done. The Java stack never grows.
        default T run() {
            Trampoline<T> current = this;
            while (true) {
                switch (current) {
                    case Done<T>(T value) -> { return value; }
                    case More<T>(var next) -> current = next.get();
                    case FlatMap<?, T> flatMap -> current = flatMap.step();
                }
            }
        }
    }

    // The naive versions: one Java stack frame per step.
    static long sum(long n) { return n == 0 ? 0 : n + sum(n - 1); }
    static long sumTail(long n, long acc) { return n == 0 ? acc : sumTail(n - 1, acc + n); }
    static boolean isEven(int n) { return n == 0 || isOdd(n - 1); }
    static boolean isOdd(int n) { return n != 0 && isEven(n - 1); }

    // The same functions, trampolined. Each returns at once with "done" or "here is what to do next".
    static Trampoline<Long> sumT(long n, long acc) {
        return n == 0 ? Trampoline.done(acc) : Trampoline.more(() -> sumT(n - 1, acc + n));
    }
    static Trampoline<Boolean> isEvenT(int n) {
        return n == 0 ? Trampoline.done(true) : Trampoline.more(() -> isOddT(n - 1));
    }
    static Trampoline<Boolean> isOddT(int n) {
        return n == 0 ? Trampoline.done(false) : Trampoline.more(() -> isEvenT(n - 1));
    }

    // Not a tail call: the addition happens after the recursive result arrives. flatMap handles it.
    static Trampoline<Long> sumNonTail(long n) {
        return n == 0 ? Trampoline.done(0L) : Trampoline.more(() -> sumNonTail(n - 1)).map(rest -> n + rest);
    }

    static void attempt(String label, Supplier<Object> body) {
        try {
            System.out.printf("%-36s = %s%n", label, body.get());
        } catch (StackOverflowError e) {
            System.out.printf("%-36s -> StackOverflowError%n", label);
        }
    }

    public static void main(String[] args) {
        attempt("naive sum(1_000)", () -> sum(1_000));
        attempt("naive sum(1_000_000)", () -> sum(1_000_000));
        attempt("tail recursive sum(1_000_000)", () -> sumTail(1_000_000, 0));
        attempt("naive isEven(1_000_000)", () -> isEven(1_000_000));

        attempt("trampolined sum(1_000_000)", () -> sumT(1_000_000, 0).run());
        attempt("trampolined isEven(1_000_000)", () -> isEvenT(1_000_000).run());
        attempt("trampolined isOdd(1_000_001)", () -> isOddT(1_000_001).run());
        attempt("non-tail sum via flatMap(1_000_000)", () -> sumNonTail(1_000_000).run());
    }
}
```

Output:

```text output
naive sum(1_000)                     = 500500
naive sum(1_000_000)                 -> StackOverflowError
tail recursive sum(1_000_000)        -> StackOverflowError
naive isEven(1_000_000)              -> StackOverflowError
trampolined sum(1_000_000)           = 500000500000
trampolined isEven(1_000_000)        = true
trampolined isOdd(1_000_001)         = true
non-tail sum via flatMap(1_000_000)  = 500000500000
```

## How it works

* **Returning instead of calling.** `sumT` never calls `sumT`. It returns a `More` holding a lambda that *would* call it. The caller of `run()` is the only frame that stays on the stack, and its loop invokes each lambda, which returns immediately with the next `More`. A million bounces, constant stack depth.
* **Mutual recursion comes free.** `isEvenT` returns a step that calls `isOddT`, which returns a step that calls `isEvenT`. The loop does not care which function produced the next step. This is something even `@tailrec` in Scala cannot do (it only handles self recursion); Scala's standard library ships `scala.util.control.TailCalls` with this exact trampoline for it.
* **`FlatMap` handles non-tail calls.** In `sumNonTail`, the `n + rest` has to wait for the recursive result. Instead of waiting on the Java stack, the pending addition is stored as the function inside a `FlatMap` node. `step()` peels one layer at a time: a `Done` source feeds its value to the function, a `More` source is forced once, and a nested `FlatMap` is rotated by `reassociate` so the work to do next is always at the top. Without that rotation, running a left-nested chain would recurse once per level and overflow just like the original.
* **Where the stack went.** The pending additions now live on the heap as a chain of closures, a million of them at the deepest point. That is the honest cost: you trade 2 MB of stack for some tens of megabytes of short-lived garbage.
* **The naive cliff is not a fixed number.** The output shows `sum(1_000)` working and `sum(1_000_000)` failing, but where exactly it breaks depends on `-Xss`, the platform's default stack size, and whether the JIT has compiled the method yet (compiled frames are smaller than interpreted ones). Never rely on a recursion depth "that worked on my machine".

## Gotchas

* **Speed.** A trampolined loop allocates a lambda and a record per step and dispatches through a `switch`. It is several times slower than a plain loop. If the recursion is a simple tail call, the best trampoline is a `while` loop written by hand.
* **Forgetting `run()`.** `sumT(10, 0)` returns a `More`, not a number. The type system catches this when you assign it to a `long`, but not when you pass it to `println`.
* **Strict arguments still recurse.** `more(() -> ...)` is lazy, but `done(expensive(n))` or arguments evaluated before the `more` are not. Anything that recurses *outside* the lambda is back on the Java stack.
* **Bigger stack instead?** `new Thread(null, task, "deep", 512 * 1024 * 1024)` asks for a huge stack for one thread. It works, the JVM treats the size as a hint, and it postpones the problem rather than solving it. For a one-off batch job it is a legitimate, boring fix.

## When to use it (and when not to)

Trampolines are the right tool when the recursion is the clearest way to express the algorithm and the depth depends on input you do not control: interpreters and evaluators, deeply nested data (a JSON document that is a list of a list of a list...), parser combinators, and library code like a `State` or `Free` monad whose `flatMap` chains would otherwise overflow (see [005](005-state-monad.md)).

For ordinary code, rewrite the recursion as a loop, or with an explicit `ArrayDeque` as the stack. It is faster, easier to debug, and every Java developer can read it. Reach for a trampoline when that rewrite would turn a ten line recursive function into a fifty line state machine.

## Related

* [005 · The State Monad: Pure Functions That Carry State](005-state-monad.md), which overflows the stack for exactly this reason
* [028 · Parser Combinators: Grammars as Code](../03-build-it-yourself/028-parser-combinators.md), a classic victim of deep recursion
* [053 · The Y Combinator in Java](../06-hidden-corners/053-y-combinator.md), recursion with no names at all
* [054 · Church Encoding: Arithmetic with Nothing but Lambdas](../06-hidden-corners/054-church-encoding.md)

## Sources

* Rúnar Bjarnason, [Stackless Scala With Free Monads](http://blog.higher-order.com/assets/trampolines.pdf) (2012), the reassociating trampoline in detail
* Ron Pressler, [Project Loom: Fibers and Continuations for the Java Virtual Machine](https://cr.openjdk.org/~rpressler/loom/Loom-Proposal.html) (2017), on automatic tail-call optimization not being a goal
* [Trampoline (computing)](https://en.wikipedia.org/wiki/Trampoline_(computing)), Wikipedia
* [`scala.util.control.TailCalls`](https://www.scala-lang.org/api/current/scala/util/control/TailCalls$.html), the same idea in Scala's standard library
