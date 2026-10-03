# 008 · Currying, Partial Application and Function Composition

> Every function takes one argument if you squint hard enough. Squinting is called currying, and it is how you bake a dependency into a function once instead of passing it on every call.

**Since:** Java 16 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

A pricing function needs two things: the pricing rules and an order.

```java
static double gross(Pricing pricing, Order order) { ... }
```

The rules are fixed at startup; the orders arrive one by one. Yet every caller has to carry `pricing` around just to hand it over, and `orders.stream().map(...)` wants a `Function<Order, Double>`, not a two-argument method. The usual fix is a lambda at every call site (`o -> gross(pricing, o)`), which works but says nothing about intent and gets copied everywhere.

The same itch appears with small transformations. You have five `String -> String` steps and want one function that runs them all, chosen at run time from configuration. Writing `step5(step4(step3(step2(step1(s)))))` by hand does not scale, and it cannot be built from a list.

## The trick

Three old ideas from lambda calculus, all expressible with `java.util.function`:

* **Currying** turns a function of two arguments into a function of one argument that returns another function: `(a, b) -> r` becomes `a -> b -> r`. It is named after Haskell Curry, although Moses Schönfinkel (and before him Gottlob Frege) had the idea first.
* **Partial application** fixes some arguments now and leaves the rest for later. With a curried function, it is just calling it with fewer arguments.
* **Composition** glues functions end to end: `f.andThen(g)` is "first `f`, then `g`".

```java
static <A, B, R> Function<A, Function<B, R>> curry(BiFunction<A, B, R> f) {
    return a -> b -> f.apply(a, b);
}

static <A, B, R> Function<B, R> partial(BiFunction<A, B, R> f, A a) {
    return b -> f.apply(a, b);
}

Function<Order, Double> retail = partial(CurryingDemo::gross, new Pricing(0.19, 0.00));
```

The design rule that makes all of this pay off: **dependencies first, data last**. If `gross` took the order first, you could not fix the pricing without a `flip`.

## Full example

```java run
import java.util.*;
import java.util.function.*;
import java.util.stream.*;

public class CurryingDemo {

    /** The JDK stops at BiFunction, so arity 3 needs its own interface. */
    @FunctionalInterface
    interface Function3<A, B, C, R> {
        R apply(A a, B b, C c);

        default Function<A, Function<B, Function<C, R>>> curried() {
            return a -> b -> c -> apply(a, b, c);
        }
    }

    static <A, B, R> Function<A, Function<B, R>> curry(BiFunction<A, B, R> f) {
        return a -> b -> f.apply(a, b);
    }

    static <A, B, R> BiFunction<A, B, R> uncurry(Function<A, Function<B, R>> f) {
        return (a, b) -> f.apply(a).apply(b);
    }

    static <A, B, R> Function<B, R> partial(BiFunction<A, B, R> f, A a) {
        return b -> f.apply(a, b);
    }

    static <A, B, R> BiFunction<B, A, R> flip(BiFunction<A, B, R> f) {
        return (b, a) -> f.apply(a, b);
    }

    // Dependency first, data last.
    record Pricing(double vatRate, double discount) {}
    record Order(String item, double net) {}

    static double gross(Pricing pricing, Order order) {
        double cents = order.net() * 100 * (1 - pricing.discount()) * (1 + pricing.vatRate());
        return Math.round(cents) / 100.0;
    }

    public static void main(String[] args) {
        // 1. Currying by hand and with helpers.
        Function<Integer, Function<Integer, Integer>> add = a -> b -> a + b;
        Function<Integer, Integer> addTen = add.apply(10);
        System.out.println("addTen(5) = " + addTen.apply(5));
        System.out.println("uncurry(add)(2, 3) = " + uncurry(add).apply(2, 3));
        BiFunction<String, Integer, String> repeat = String::repeat;
        System.out.println("curry(repeat)(\"ab\")(3) = " + curry(repeat).apply("ab").apply(3));
        System.out.println("flip(repeat)(3, \"ab\") = " + flip(repeat).apply(3, "ab"));

        // 2. Partial application of the dependency: two price lists, one function each.
        Function<Order, Double> retail = partial(CurryingDemo::gross, new Pricing(0.19, 0.00));
        Function<Order, Double> staffSale = partial(CurryingDemo::gross, new Pricing(0.19, 0.30));
        List<Order> orders = List.of(new Order("telescope", 400.00), new Order("star chart", 12.50));
        System.out.println("retail:     " + orders.stream().map(retail).toList());
        System.out.println("staff sale: " + orders.stream().map(staffSale).toList());

        // 3. Arity 3: fix the bounds, get a reusable clamp.
        Function3<Integer, Integer, Integer, Integer> clamp = (lo, hi, x) -> Math.max(lo, Math.min(hi, x));
        Function<Integer, Integer> percent = clamp.curried().apply(0).apply(100);
        System.out.println("percent: " + Stream.of(-5, 42, 180).map(percent).toList());

        // 4. andThen versus compose: same functions, opposite order.
        Function<Integer, Integer> inc = x -> x + 1;
        Function<Integer, Integer> dbl = x -> x * 2;
        System.out.println("inc.andThen(dbl)(5) = " + inc.andThen(dbl).apply(5));
        System.out.println("inc.compose(dbl)(5) = " + inc.compose(dbl).apply(5));

        // 5. A pipeline built from a list: identity is the neutral element of andThen.
        List<Function<String, String>> steps = List.of(
                String::strip,
                String::toLowerCase,
                s -> s.replaceAll("[^a-z0-9]+", "-"),
                s -> s.replaceAll("^-|-$", ""));
        Function<String, String> slugify = steps.stream().reduce(Function.identity(), Function::andThen);
        System.out.println("slug: " + slugify.apply("  Currying, Partial Application & Composition! "));
        System.out.println("no steps: " + Stream.<Function<String, String>>empty()
                .reduce(Function.identity(), Function::andThen).apply("unchanged"));

        // 6. Predicates compose too: not, and, or.
        Predicate<String> longWord = s -> s.length() > 4;
        Predicate<String> keep = Predicate.not(String::isBlank).and(longWord.or(s -> s.startsWith("#")));
        System.out.println("kept: " + Stream.of("lambda", " ", "#java", "fun", "", "monad").filter(keep).toList());

        // 7. Point free: a method reference has no type until it gets a target, hence the cast.
        Function<String, Integer> wordCount = ((Function<String, String>) String::strip)
                .andThen(s -> s.isEmpty() ? 0 : s.split("\\s+").length);
        System.out.println("words: " + Stream.of("  one  two three ", "   ").map(wordCount).toList());
    }
}
```

Output:

```text output
addTen(5) = 15
uncurry(add)(2, 3) = 5
curry(repeat)("ab")(3) = ababab
flip(repeat)(3, "ab") = ababab
retail:     [476.0, 14.88]
staff sale: [333.2, 10.41]
percent: [0, 42, 100]
inc.andThen(dbl)(5) = 12
inc.compose(dbl)(5) = 11
slug: currying-partial-application-composition
no steps: unchanged
kept: [lambda, #java, monad]
words: [3, 0]
```

And here is where Java's type system stops playing along. Each of these three lines looks reasonable:

```java compile-fail
import java.util.*;
import java.util.function.*;

public class ReadabilityLimits {
    public static void main(String[] args) {
        var add = a -> b -> a + b;
        List.of("a", " ").stream().filter(String::isBlank.negate()).count();
        Function<Integer, String> show = Integer::toString;
    }
}
```

```text compile-error
ReadabilityLimits.java:6: error: cannot infer type for local variable add
        var add = a -> b -> a + b;
            ^
  (lambda expression needs an explicit target-type)
ReadabilityLimits.java:7: error: method reference not expected here
        List.of("a", " ").stream().filter(String::isBlank.negate()).count();
                                          ^
ReadabilityLimits.java:8: error: incompatible types: invalid method reference
        Function<Integer, String> show = Integer::toString;
                                         ^
    reference to toString is ambiguous
      both method toString(int) in Integer and method toString() in Integer match
3 errors
```

## How it works

* **Currying is just a lambda that returns a lambda.** `a -> b -> a + b` parses as `a -> (b -> a + b)`. The inner lambda captures `a`, so `add.apply(10)` is a closure that remembers 10 and waits for the second number. That closure *is* the partially applied function.
* **`partial` skips the curried detour.** Calling `curry(f).apply(a)` and `partial(f, a)` give the same `Function<B, R>`. The helper exists because `apply(a).apply(b)` gets noisy fast, and most real code only ever wants to fix the first argument. The pricing example shows the payoff: `retail` and `staffSale` are plain `Function<Order, Double>` values that drop straight into `map`, and the 30 percent staff discount turns `[476.0, 14.88]` into `[333.2, 10.41]`.
* **Argument order is API design.** `flip` exists because many methods put the data first. `Math.clamp` (Java 21) is `clamp(value, min, max)`, so you cannot fix the bounds by partially applying it; the hand-written `clamp` above takes the bounds first for exactly this reason. Functional languages put the "configuration" arguments first by convention, which is also why [006](006-reader-monad.md) can treat a dependency as the first argument of every function.
* **Arity 3 and up needs your own interface.** The JDK has `Function` and `BiFunction` and nothing beyond. A `Function3` with a `curried()` default method is the smallest fix. [004](004-validation-applicative.md) uses the same trick inside its `combine`: it zips the first two fields into a function `c -> d -> f.apply(a, b, c, d)` that is still waiting for the remaining fields, then feeds them in one at a time.
* **`andThen` reads left to right, `compose` right to left.** `inc.andThen(dbl)` is `dbl(inc(5)) = 12`; `inc.compose(dbl)` is `inc(dbl(5)) = 11`. Most people find `andThen` easier to read because it matches the order of execution.
* **`reduce` needs a neutral element, and `Function.identity()` is it.** Composition is associative and the identity function changes nothing, so `reduce(Function.identity(), Function::andThen)` is well defined for any list, including the empty one, which returns its input unchanged. [018](../02-patterns/018-middleware-chain.md) uses the same reduction to build a middleware chain.
* **Predicates have their own combinators.** `and`, `or` and `negate` are default methods, and the static `Predicate.not` (Java 11) exists for one reason: a method reference cannot be the receiver of a method call, so `String::isBlank.negate()` is a syntax error, as the compile error above shows.

## Gotchas

* **Method references need a target type before you can call methods on them.** That is the cast in step 7, the "method reference not expected here" error and the reason `var add = a -> b -> a + b` cannot infer anything. Assign to a typed variable first, or use a static helper like `Predicate.not`.
* **Overloads break method references.** `Integer::toString` matches both `toString()` on an instance and the static `toString(int)`, so javac refuses to pick. Write the lambda `i -> i.toString()` or use `String::valueOf` with an explicit target.
* **`UnaryOperator.andThen` returns a `Function`.** `andThen` is inherited from `Function` and is declared to return `Function<T, V>`, so a `reduce` over a `List<UnaryOperator<String>>` that tries to keep the result a `UnaryOperator` does not compile. Use `Function<String, String>` for pipelines.
* **Boxing everywhere.** `Function<Integer, Function<Integer, Integer>>` boxes every number and allocates a closure per partial application. On hot numeric paths, prefer `IntUnaryOperator` and friends, or plain methods.
* **Stack traces become archaeology.** A failure inside a composed pipeline shows frames like `lambda$main$3` with no name a human chose. Named methods referenced with `::` read better in a stack trace than anonymous lambdas.

## When to use it (and when not to)

Partial application of dependencies is genuinely useful: build `Function<Order, Double>` once from the configuration, then pass it to code that knows nothing about pricing. `andThen` pipelines and `Predicate.not` belong in everyday code; they are short and read in execution order. Building a pipeline from a list with `reduce` is the right tool when the steps really come from configuration or plugins.

Hand-curried types like `Function<A, Function<B, Function<C, R>>>` are a different story. Java has no automatic currying, no type inference for lambdas without a target and no syntax for `f(a)(b)`, so curried code is longer and harder to read than the method it replaces. Use currying as an internal trick (as in 004's `combine`), not as a public API style. If a teammate needs a whiteboard to read a signature, write a small interface with a good name instead.

## Related

* [004 · Validation: Collect Every Error, Not Just the First](004-validation-applicative.md), where currying feeds fields into a constructor one at a time
* [006 · The Reader Monad: Dependency Injection with Plain Functions](006-reader-monad.md), dependency first taken all the way
* [018 · Middleware Chains: Chain of Responsibility as Function Composition](../02-patterns/018-middleware-chain.md), composition with a `reduce`
* [053 · The Y Combinator in Java](../06-hidden-corners/053-y-combinator.md), curried lambdas pushed to the limit

## Sources

* [Currying](https://en.wikipedia.org/wiki/Currying), Wikipedia, on Curry, Schönfinkel and Frege
* [`java.util.function.Function` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/function/Function.html)
* [`java.util.function.Predicate` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/function/Predicate.html), including `not`
* [JDK-8050818: Predicate::not, provide an easier way to negate a predicate](https://bugs.openjdk.org/browse/JDK-8050818)
* [JLS §15.13: Method Reference Expressions](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.13)
