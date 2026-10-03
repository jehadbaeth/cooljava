# 054 · Church Encoding: Arithmetic with Nothing but Lambdas

> In the 1930s Alonzo Church showed that numbers, booleans and `if` can all be built from functions and nothing else. Java's lambdas are enough to redo it, and javac's type checker puts up a fight that teaches you more than the arithmetic does.

**Since:** Java 8 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

Suppose a language only has functions. No `int`, no `boolean`, no `if`, no loops. Can you still compute `2^3`? Church's answer was yes: represent *data by what you can do with it*. That is the idea behind the lambda calculus, a complete model of computation with just three ingredients:

* a variable: `x`
* an abstraction (a function): `λx. body`
* an application (a call): `f x`

Java has exactly these: a name, `x -> body`, and `f.apply(x)`. So the question is how far a handful of one-argument lambdas can take you.

## The trick

A **Church numeral** is the number `n` represented as "a function that applies another function `f` exactly `n` times":

```text
0       = λf. λx. x
1       = λf. λx. f x
2       = λf. λx. f (f x)
succ n  = λf. λx. f (n f x)
add m n = λf. λx. m f (n f x)
mult m n = λf. m (n f)
exp m n = n m
```

Nothing in there is a number. `add` runs `f` first `n` times and then `m` more times. `mult` takes "repeat `f` `n` times" and repeats that `m` times. And `exp` is almost insulting: `m^n` is just `n` applied to `m`, because "do `m` (which is already a repeat-`f`-`m`-times machine) `n` times" is exponentiation.

**Church booleans** are functions that pick one of two arguments, and `if` is just calling the boolean:

```text
true  = λt. λf. t
false = λt. λf. f
if c a b = c a b
isZero n = n (λx. false) true
```

`isZero` shows the whole style: start with `true`, and if the numeral applies "always return false" even once, the answer becomes `false`. Zero applies it zero times.

## Full example

To print a Church numeral as an `int`, apply it to `i -> i + 1` and start from `0`. That is the only place where real numbers enter the program.

```java run
import java.util.function.*;

public class ChurchEncoding {

    // A Church numeral n is "apply f n times". T is the type that f works on.
    interface Num<T> extends Function<Function<T, T>, Function<T, T>> {}

    // A Church boolean picks one of its two arguments.
    interface Bool<A> extends Function<A, Function<A, A>> {}

    static <T> Num<T> zero() { return f -> x -> x; }
    static <T> Num<T> succ(Num<T> n) { return f -> x -> f.apply(n.apply(f).apply(x)); }
    static <T> Num<T> add(Num<T> m, Num<T> n) { return f -> x -> m.apply(f).apply(n.apply(f).apply(x)); }
    static <T> Num<T> mult(Num<T> m, Num<T> n) { return f -> m.apply(n.apply(f)); }

    // m^n is "n applied to m". That needs n one level up: it repeats a Num<T>, a function from T -> T to T -> T.
    static <T> Num<T> exp(Num<T> m, Num<Function<T, T>> n) { return f -> n.apply(m).apply(f); }

    static <T> Num<T> of(int k) {
        Num<T> n = zero();
        for (int i = 0; i < k; i++) n = succ(n);
        return n;
    }

    static int toInt(Num<Integer> n) { return n.apply(i -> i + 1).apply(0); }

    static <A> Bool<A> tru() { return t -> f -> t; }
    static <A> Bool<A> fls() { return t -> f -> f; }

    // Start with true; every application of the numeral's function turns it to false.
    static <A> Bool<A> isZero(Num<Bool<A>> n) { return n.apply(x -> fls()).apply(tru()); }

    // Eager if: Java evaluates both branches before the boolean gets to pick one.
    static <A> A ifEager(Bool<A> condition, A thenValue, A elseValue) {
        return condition.apply(thenValue).apply(elseValue);
    }

    // Lazy if: pass thunks and force only the winner.
    static <A> A ifLazy(Bool<Supplier<A>> condition, Supplier<A> thenValue, Supplier<A> elseValue) {
        return condition.apply(thenValue).apply(elseValue).get();
    }

    static String say(String branch) {
        System.out.println("  evaluating " + branch);
        return branch;
    }

    public static void main(String[] args) {
        System.out.println("-- arithmetic");
        System.out.println("2 + 3 = " + toInt(add(of(2), of(3))));
        System.out.println("4 * 5 = " + toInt(mult(of(4), of(5))));
        Num<Integer> two = of(2);
        Num<Function<Integer, Integer>> three = of(3);   // the exponent lives one type level up
        System.out.println("2 ^ 3 = " + toInt(exp(two, three)));

        boolean agree = true;
        for (int a = 0; a <= 4; a++) {
            for (int b = 0; b <= 4; b++) {
                Num<Integer> ca = of(a), cb = of(b);
                Num<Function<Integer, Integer>> exponent = of(b);
                agree &= toInt(add(ca, cb)) == a + b;
                agree &= toInt(mult(ca, cb)) == a * b;
                agree &= toInt(exp(ca, exponent)) == (int) Math.pow(a, b);
            }
        }
        System.out.println("matches int arithmetic for 0..4: " + agree);
        System.out.println("3 as repetition: " + ChurchEncoding.<String>of(3).apply(s -> s + "ha").apply(""));

        System.out.println("-- booleans");
        Bool<String> zeroTest = isZero(of(0));
        Bool<String> threeTest = isZero(of(3));
        System.out.println("isZero(0): " + zeroTest.apply("yes").apply("no"));
        System.out.println("isZero(3): " + threeTest.apply("yes").apply("no"));

        System.out.println("-- if");
        System.out.println("eager:");
        System.out.println("  result: " + ifEager(ChurchEncoding.<String>tru(), say("then"), say("else")));
        System.out.println("lazy:");
        System.out.println("  result: " + ifLazy(ChurchEncoding.<Supplier<String>>tru(),
                () -> say("then"), () -> say("else")));

        System.out.println("-- cost");
        System.out.println("of(1000) = " + toInt(of(1000)));
        try {
            toInt(of(100_000));
        } catch (StackOverflowError e) {
            System.out.println("of(100000): StackOverflowError");
        }
    }
}
```

Output:

```text output
-- arithmetic
2 + 3 = 5
4 * 5 = 20
2 ^ 3 = 8
matches int arithmetic for 0..4: true
3 as repetition: hahaha
-- booleans
isZero(0): yes
isZero(3): no
-- if
eager:
  evaluating then
  evaluating else
  result: then
lazy:
  evaluating then
  result: then
-- cost
of(1000) = 1000
of(100000): StackOverflowError
```

Why does `Num` carry a type parameter at all? Because Java will not let a lambda stand for a polymorphic numeral. Here is the natural first attempt, a numeral that works for any `T`:

```java compile-fail
import java.util.function.Function;

public class GenericLambda {
    interface Numeral {
        <T> Function<T, T> apply(Function<T, T> f);
    }

    public static void main(String[] args) {
        Numeral zero = f -> x -> x;
    }
}
```

```text compile-error
GenericLambda.java:9: error: incompatible types: invalid functional descriptor for lambda expression
        Numeral zero = f -> x -> x;
                       ^
    method (Function<T,T>)Function<T,T> in interface Numeral is generic
  where T is a type-variable:
    T extends Object declared in method <T>apply(Function<T,T>)
1 error
```

## How it works

* **A numeral is a loop in disguise.** `Num<T>` takes the function `f` to repeat and returns a function that repeats it. `toInt` plugs in "add one" and a starting value of zero, and `ChurchEncoding.<String>of(3)` plugs in "append ha" and the empty string. The "3" is nothing but how often the function runs.
* **`Num<T>` extends `Function<Function<T, T>, Function<T, T>>`** so that a lambda can implement it (it has one abstract method, inherited) and the signatures stay readable. Lambda calculus gets by with untyped functions. Java needs a type for everything, and that is where it gets interesting.
* **A lambda cannot implement a generic method.** The `compile-fail` block above is what you would write if numerals were truly polymorphic, a rank-2 type in the jargon, and javac rejects it with `invalid functional descriptor for lambda expression` (the message ends by pointing at the generic method). The only way out is to fix the type parameter on the interface (`Num<T>`), so each numeral works for exactly one `T`. An anonymous class *may* implement a generic method, so a fully polymorphic numeral is possible, at the price of one anonymous class per numeral. That defeats the purpose of a lambda-only exercise.
* **Fixing `T` has consequences, and `exp` shows them.** Exponentiation applies the exponent `n` to the base `m`, so `n` must repeat a *numeral*, which is a function from `T -> T` to `T -> T`. Its `T` is therefore `Function<T, T>`, one level up from the base. That is why `exp` takes a `Num<T>` and a `Num<Function<T, T>>`, and why `main` builds the exponent separately (`three`, and `exponent` inside the loop). The same trick shows up in `isZero`, which needs a numeral over `Bool<A>`. In the untyped lambda calculus none of this bookkeeping exists, and in a language with rank-2 types (Haskell with an extension, or System F on paper) one numeral serves every purpose.
* **Church booleans pick, they do not branch.** `tru()` returns its first argument, `fls()` its second, and `condition.apply(a).apply(b)` is the `if`. The "eager" run in the output shows the catch: Java evaluates both arguments before the call, so both branches execute (here, both lines print). Wrapping the branches in `Supplier` lets the boolean choose one and force only that one. This is also why real lambda calculus is usually studied with lazy evaluation.
* **The arithmetic really is checked.** The nested loop compares `add`, `mult` and `exp` against plain `int` arithmetic for every pair from 0 to 4, including `0^0 = 1`, which falls out of the encoding without a special case.

## Gotchas

* **Time and stack follow the value.** A numeral *is* its repetition count, so `of(n)` creates `n` closures, `toInt` runs `n` nested calls, `mult` costs `m * n` applications and `exp` costs as much as the result is large. The last two lines of the output show the stack side: 1000 is fine, 100000 overflows the default stack. A trampoline ([007](../01-functional/007-trampolines.md)) could make the loops safe, but that is a lot of machinery for a number.
* **No subtraction for free.** `succ` is two lines, but the predecessor function is famously awkward in the lambda calculus (it needs pairs, repeated for every step), and Java's types make it worse. This doc stops where the pleasant part ends.
* **Types leak into every call.** Mixed `of(...)` calls need explicit type witnesses (`ChurchEncoding.<String>of(3)`) or typed locals, because the result type cannot be inferred from a later call in a chain.
* **Church's boolean is a pair of choices, not a value you can print.** You can only observe it by choosing something, which is why the examples ask `apply("yes").apply("no")`.

## When to use it (and when not to)

Never in production: `int` is faster, smaller, and has a debugger. Church encoding earns its place as a teaching device. It makes closures, currying (see [008](../01-functional/008-currying-composition.md)) and the limits of Java's generics visible in a few lines, and it makes the idea of *data as its own eliminator* concrete: a Church numeral is its own `for` loop, and a Church boolean is its own `if`. Visitors and the `fold`/`match` methods in the [Maybe monad](../01-functional/001-maybe-monad.md) are the same idea in a more respectable outfit.

If you want to go further with lambdas-only computation, the next stop is the [Y combinator](053-y-combinator.md), which adds recursion to a language that has none.

## Related

* [053 · The Y Combinator in Java](053-y-combinator.md)
* [008 · Currying, Partial Application and Function Composition](../01-functional/008-currying-composition.md)
* [038 · Higher-Kinded Types in Java (Yes, Really)](../04-generics/038-higher-kinded-types.md), for more of what Java's type system cannot say directly
* [007 · Trampolines: Stack-Safe Recursion](../01-functional/007-trampolines.md)

## Sources

* [Church encoding](https://en.wikipedia.org/wiki/Church_encoding), Wikipedia, with the numeral, boolean and pair encodings
* [The Lambda Calculus](https://plato.stanford.edu/entries/lambda-calculus/), Stanford Encyclopedia of Philosophy
* Alonzo Church, *The Calculi of Lambda-Conversion* (Princeton University Press, 1941)
* [JLS §15.27: Lambda Expressions](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.27)
* Benjamin C. Pierce, *Types and Programming Languages* (MIT Press, 2002), the chapters on the untyped lambda calculus and on System F
