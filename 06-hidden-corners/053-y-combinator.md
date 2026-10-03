# 053 · The Y Combinator in Java

> A lambda cannot call itself, because it has no name. Lambda calculus solved that in the 1930s with a function that finds the fixed point of any function, and Java's `Function` type is enough to build it, as long as you know why the famous version loops forever.

**Since:** Java 8 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

Recursion needs a name to call. A method has one. A lambda does not, and the obvious attempt is rejected by the compiler:

```java compile-fail
import java.util.function.Function;

public class NoName {
    public static void main(String[] args) {
        Function<Integer, Long> fact = n -> n == 0 ? 1L : n * fact.apply(n - 1);
        System.out.println(fact.apply(5));
    }
}
```

```text compile-error
NoName.java:5: error: variable fact might not have been initialized
        Function<Integer, Long> fact = n -> n == 0 ? 1L : n * fact.apply(n - 1);
                                                              ^
1 error
```

The variable `fact` is not definitely assigned until the whole declaration has finished, and a lambda body may only read local variables that are. Moving the lambda into a static field does not help either, because a field cannot name itself in its own initializer:

```java compile-fail
import java.util.function.Function;

public class NoNameField {
    static Function<Integer, Long> fact = n -> n == 0 ? 1L : n * fact.apply(n - 1);

    public static void main(String[] args) {
        System.out.println(fact.apply(5));
    }
}
```

```text compile-error
NoNameField.java:4: error: self-reference in initializer
    static Function<Integer, Long> fact = n -> n == 0 ? 1L : n * fact.apply(n - 1);
                                                                 ^
1 error
```

Pure lambda calculus has no names at all, no variables you can assign and no loops, and still computes everything. The tool it uses for recursion is the Y combinator. This document builds it in Java in five steps, with the compiler as witness for each one.

## The trick

**Step 1: take the recursive call as a parameter.** Instead of a function that calls itself, write a function that takes "the function for smaller inputs" and returns "the function for this input". Call that a step:

```java
Step<Integer, Long> FACTORIAL = self -> n -> n == 0 ? 1L : n * self.apply(n - 1);
```

Nothing in it refers to itself by name. Give it a working factorial for inputs below n and it hands back a working factorial for n. Give it a function that must never be called and it still works for 0, which the program below checks.

**Step 2: ask for the fixed point.** We want a function `fix` with `fix(step)` equal to `step(fix(step))`. The literal translation is `step.apply(fix(step))`, and Java evaluates the argument first, so it recurses forever and ends in a `StackOverflowError`.

**Step 3: delay the inner call.** Wrap it in a lambda: `v -> step.apply(fix(step)).apply(v)`. The inner `fix` call now waits until there is an argument. It works, but it is a method that calls itself by name, which is the thing we wanted to get rid of.

**Step 4: remove the name by applying a function to itself.** Let `w = x -> step(x x)`. Then `w w = step(w w)`, so `w w` is exactly the fixed point we want. That is the Y combinator:

```text
Y = λf. (λx. f (x x)) (λx. f (x x))
```

It needs a type whose argument is its own type, which is why Java needs the `Self` interface. And in a language that evaluates arguments before calling, `x x` runs before `step` is ever called, so Y also loops forever in Java.

**Step 5: eta-expand `x x`.** `v -> x x v` is the same function as `x x`, but it is a lambda, so nothing is evaluated until it is called with an argument. That is the call-by-value variant of Y, usually named Z:

```text
Z = λf. (λx. f (λv. x x v)) (λx. f (λv. x x v))
```

Here is how it unfolds for `z(FACTORIAL).apply(2)`. `z` builds `w` and calls `w.apply(w)`, which applies the step to the delayed `v -> w w v` and returns the factorial function. Calling it with 2 evaluates `2 * self.apply(1)`. The call to `self` runs `w w` again, which applies the step a second time and produces a fresh factorial function for 1, and so on until the step returns 1 for 0.

## Full example

Every step is a separate method so you can see steps 2 to 4 fail or cheat and step 5 work. The program then uses Z for factorial and Fibonacci, counts what it costs, uses the fixed point to add memoization without touching the Fibonacci step, and finishes with the boring ways to recurse in a lambda.

```java run
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;

public class YCombinator {

    /** A function that takes itself as its argument. The type has to mention itself. */
    interface Self<T, R> extends Function<Self<T, R>, Function<T, R>> {}

    /** One step of a recursive function: given "the function for smaller inputs", return the function. */
    interface Step<T, R> extends Function<Function<T, R>, Function<T, R>> {}

    // Step 1: the recursive call is a parameter, so nothing refers to itself by name.
    static final Step<Integer, Long> FACTORIAL = self -> n -> n == 0 ? 1L : n * self.apply(n - 1);
    static final Step<Integer, Long> FIBONACCI = self -> n -> n < 2 ? n : self.apply(n - 1) + self.apply(n - 2);

    // Step 2: fix(step) = step(fix(step)). Java evaluates the argument first, so this never returns.
    static <T, R> Function<T, R> naiveFix(Step<T, R> step) {
        return step.apply(naiveFix(step));
    }

    // Step 3: delay the inner call with a lambda. It works, but the method recurses by its own name.
    static <T, R> Function<T, R> namedFix(Step<T, R> step) {
        return v -> step.apply(namedFix(step)).apply(v);
    }

    // Step 4: the Y combinator. No name needed, but x.apply(x) runs before step is called, so it loops.
    static <T, R> Function<T, R> y(Step<T, R> step) {
        Self<T, R> w = x -> step.apply(x.apply(x));
        return w.apply(w);
    }

    // Step 5: the Z combinator. Wrapping x x in v -> x x v delays it until there is an argument.
    static <T, R> Function<T, R> z(Step<T, R> step) {
        Self<T, R> w = x -> step.apply(v -> x.apply(x).apply(v));
        return w.apply(w);
    }

    // Open recursion: a step receives "self", so a wrapper can intercept every recursive call.
    static <T, R> Step<T, R> callCounting(Step<T, R> step, int[] calls) {
        return self -> {
            Function<T, R> inner = step.apply(self);
            return t -> {
                calls[0]++;
                return inner.apply(t);
            };
        };
    }

    static <T, R> Step<T, R> memoized(Step<T, R> step) {
        Map<T, R> cache = new HashMap<>();
        return self -> {
            Function<T, R> inner = step.apply(self);
            return t -> {
                R hit = cache.get(t);
                if (hit == null) {
                    hit = inner.apply(t);
                    cache.put(t, hit);
                }
                return hit;
            };
        };
    }

    static String outcome(Runnable attempt) {
        try {
            attempt.run();
            return "returned a value";
        } catch (StackOverflowError e) {
            return "StackOverflowError";
        }
    }

    // The boring ways to recurse in a lambda. A static field must be qualified to name itself.
    static final Function<Integer, Long> FIELD = n -> n == 0 ? 1L : n * YCombinator.FIELD.apply(n - 1);

    static long factorial(int n) {
        return n == 0 ? 1L : n * factorial(n - 1);
    }

    public static void main(String[] args) {
        System.out.println("0. a step is not recursive by itself");
        Function<Integer, Long> neverCalled = n -> {
            throw new IllegalStateException("never called");
        };
        System.out.println("  0! from a step fed a function that throws: " + FACTORIAL.apply(neverCalled).apply(0));

        System.out.println("1. steps that fail in a strict language");
        System.out.println("  naive fix:    " + outcome(() -> naiveFix(FACTORIAL)));
        System.out.println("  Y combinator: " + outcome(() -> y(FACTORIAL)));

        System.out.println("2. step 3, recursion by the method's own name");
        System.out.println("  5! = " + namedFix(FACTORIAL).apply(5));

        System.out.println("3. the Z combinator");
        Function<Integer, Long> fact = z(FACTORIAL);
        Function<Integer, Long> fib = z(FIBONACCI);
        System.out.println("  20! = " + fact.apply(20));
        List<Long> firstFibs = new ArrayList<>();
        for (int i = 0; i <= 12; i++) firstFibs.add(fib.apply(i));
        System.out.println("  fib(0..12) = " + firstFibs);

        System.out.println("4. what Z costs: the step runs again on every recursive call");
        int[] applications = {0};
        int[] calls = {0};
        Step<Integer, Long> counted = self -> {
            applications[0]++;
            Function<Integer, Long> inner = FACTORIAL.apply(self);
            return n -> {
                calls[0]++;
                return inner.apply(n);
            };
        };
        System.out.println("  5! = " + z(counted).apply(5) + ", calls: " + calls[0] + ", step applications: " + applications[0]);

        System.out.println("5. open recursion: memoization without touching the Fibonacci step");
        int[] plain = {0};
        int[] cached = {0};
        System.out.println("  fib(25) = " + z(callCounting(FIBONACCI, plain)).apply(25) + ", calls: " + plain[0]);
        System.out.println("  fib(25) = " + z(memoized(callCounting(FIBONACCI, cached))).apply(25) + ", calls: " + cached[0]);

        System.out.println("6. the boring ways to recurse in a lambda");
        AtomicReference<Function<Integer, Long>> holder = new AtomicReference<>();
        holder.set(n -> n == 0 ? 1L : n * holder.get().apply(n - 1));
        Function<Integer, Long> anonymous = new Function<Integer, Long>() {
            @Override
            public Long apply(Integer n) {
                return n == 0 ? 1L : n * this.apply(n - 1);
            }
        };
        System.out.println("  qualified static field: " + FIELD.apply(10));
        System.out.println("  holder:                 " + holder.get().apply(10));
        System.out.println("  anonymous class:        " + anonymous.apply(10));
        System.out.println("  plain method:           " + factorial(10));
    }
}
```

Output:

```text output
0. a step is not recursive by itself
  0! from a step fed a function that throws: 1
1. steps that fail in a strict language
  naive fix:    StackOverflowError
  Y combinator: StackOverflowError
2. step 3, recursion by the method's own name
  5! = 120
3. the Z combinator
  20! = 2432902008176640000
  fib(0..12) = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]
4. what Z costs: the step runs again on every recursive call
  5! = 120, calls: 6, step applications: 6
5. open recursion: memoization without touching the Fibonacci step
  fib(25) = 75025, calls: 242785
  fib(25) = 75025, calls: 26
6. the boring ways to recurse in a lambda
  qualified static field: 3628800
  holder:                 3628800
  anonymous class:        3628800
  plain method:           3628800
```

## How it works

* **A step is a function with the recursion removed.** `FACTORIAL` and `FIBONACCI` never mention themselves. They get `self` from outside, which is the only reason the combinator can choose what `self` is.
* **The fixed point is a function that is its own step.** `fix(step)` must behave like `step(fix(step))`, so the function you get back, applied to `n`, uses `step` to peel one layer and hands the rest to itself.
* **Both attempts in section 1 died in the same way.** `naiveFix` evaluates `naiveFix(step)` as an argument before it can call `step.apply`, and `y` evaluates `x.apply(x)` before it can call `step.apply`. Neither ever reaches the step. Wikipedia's article on fixed-point combinators says that in strict languages Y "loops indefinitely until terminating via a stack overflow", which is what the output shows.
* **Z works because a lambda is a value.** `v -> x.apply(x).apply(v)` is built without running `x.apply(x)`. The evaluation happens only when the recursive call has an argument, by which point the base case is close.
* **The type needs a name.** `x x` has no finite type in plain simply typed lambda calculus. Java gets one by naming a type that mentions itself: `Self<T, R>` is a function from `Self<T, R>` to `Function<T, R>`. Without the interface `x.apply(x)` would not type check.
* **The counters show the real cost.** Calling `5!` takes 6 calls and 6 applications of the step. Z rebuilds the function at every level of recursion, so you pay a few allocations per call on top of the call itself.
* **Open recursion is the part with real value.** Because the step takes `self`, a wrapper can decide what `self` is. `memoized` hands in a cache, so `fib(25)` needs 26 calls instead of 242785, and the Fibonacci step has no idea. That is the same trick as decorating a function, applied to its recursive calls.

## Gotchas

* **Eager evaluation is the whole story.** The textbook Y combinator is meant for lazy evaluation, where `x x` is not computed until its value is needed. In Java it overflows the stack, so you need the eta-expanded Z. (A typed lazy language like Haskell still needs a recursive newtype to give `x x` a type, which is the role `Self` plays here.)
* **Only one argument.** `Function` takes one parameter. A recursive function of two inputs needs currying ([008](../01-functional/008-currying-composition.md)), a tuple or a record.
* **Stack depth is not improved.** Java has no tail call optimization, and each level here passes through the delayed lambda, the `Self` lambda and the step, so it uses more stack than the same plain method. For deep recursion, see trampolines ([007](../01-functional/007-trampolines.md)).
* **Generics get in the way.** `Step` is only a name for `Function<Function<T, R>, Function<T, R>>`, and you can write that out, though the signatures get unreadable fast. `Self` cannot be written out, because its type mentions itself, so it must be declared as an interface.
* **The field variant is a loophole.** The static field in section 6 works only because the lambda writes `YCombinator.FIELD`. The simple name `FIELD` is the `self-reference in initializer` error from the top of this page, and the qualified name is how you walk around the rule.

## When to use it (and when not to)

Do not use it. This is a party trick. Every task above is simpler with a method:

* a static method, `factorial(int)`, which is the plain answer and the one the stack handles best,
* an instance or static field holding the lambda, referenced with a qualified name,
* a holder such as `AtomicReference` for a local lambda that needs to call itself,
* an anonymous class, where `this` already refers to the function.

What is worth taking away is open recursion: a recursive function that receives its own recursive call as an argument can be wrapped, traced, memoized or limited from outside. The honest Java way to get that is a plain interface and a decorator, as in [009](../01-functional/009-memoization.md), not a combinator. Interviewers occasionally ask for the Y combinator. Now you can answer, and you can also say why Java needs the Z variant.

## Related

* [054 · Church Encoding: Arithmetic with Nothing but Lambdas](054-church-encoding.md), the other half of the lambda calculus party
* [009 · Memoization Done Right](../01-functional/009-memoization.md), the practical version of the memoization demo
* [007 · Trampolines: Stack-Safe Recursion](../01-functional/007-trampolines.md), for recursion that does not overflow
* [050 · Anonymous Classes Meet var](050-anonymous-classes-var.md), where an object with a recursive method is the easy answer

## Sources

* [Fixed-point combinator](https://en.wikipedia.org/wiki/Fixed-point_combinator), Wikipedia, including the strict (call-by-value) variant
* [The Y Combinator (Slightly Less Than Rigorous)](https://mvanier.livejournal.com/2897.html), Mike Vanier, a derivation in the same step-by-step spirit
* [JLS §15.27.2: Lambda Body](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.27.2), on definite assignment of captured locals
* [JLS §8.3.3: Restrictions on Field References in Initializers](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.3.3), the self-reference rule
