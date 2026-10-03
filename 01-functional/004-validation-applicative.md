# 004 · Validation: Collect Every Error, Not Just the First

> `flatMap` is a queue: nobody gets served until the person in front is done. Independent checks deserve a different shape, one that looks at everything at once and reports every problem.

**Since:** Java 21 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

[002's Either](002-either.md) is fail fast by design. Chain four field checks with `flatMap` and a form with four mistakes reports one of them:

```java
name(form.name()).flatMap(n ->
email(form.email()).flatMap(e ->
age(form.age()).flatMap(a ->
password(form.password()).map(p -> new SignUp(n, e, a, p)))));
```

That is not laziness in the implementation. It is baked into the *type* of `flatMap`: `Function<T, Validation<R>>` needs the `T` from the previous step before it can even run the next one. If the name is invalid, there is no name, so the lambda that would check the email cannot be called. Short circuiting is the only possible behavior.

But the email check does not need the name. The four checks are **independent**, and independent checks can all run first and be combined afterwards.

## The trick

Give `Validation` a second way to combine values, one that takes two *already computed* results instead of a function that produces the next one:

```java
default <U, R> Validation<R> zipWith(Validation<U> other, BiFunction<? super T, ? super U, ? extends R> f) {
    return switch (new Both<>(this, other)) {
        case Both<T, U>(Valid<T>(T a), Valid<U>(U b)) -> valid(f.apply(a, b));
        case Both<T, U>(Valid<T> a, Invalid<U>(List<String> e)) -> invalid(e);
        case Both<T, U>(Invalid<T>(List<String> e), Valid<U> b) -> invalid(e);
        case Both<T, U>(Invalid<T>(List<String> e1), Invalid<U>(List<String> e2)) ->
                invalid(Stream.concat(e1.stream(), e2.stream()).toList());
    };
}
```

Both sides are in hand, so when both are invalid it can keep both error lists. That one method is what makes `Validation` an **applicative functor** (this operation is often called `map2`, `product` or `ap`), and it is all you need to combine any number of fields: zip two, then zip the result with the third, and so on.

Inside a single field the rules often *do* depend on each other ("is it a number?" before "is it at least 18?"), and there `flatMap` is exactly right. The skill is using each where it fits: `flatMap` along a field, `zipWith` across fields.

## Full example

```java run
import java.util.*;
import java.util.function.*;
import java.util.stream.*;

public class ValidationDemo {

    sealed interface Validation<T> {
        record Valid<T>(T value) implements Validation<T> {}
        record Invalid<T>(List<String> errors) implements Validation<T> {
            public Invalid {
                errors = List.copyOf(errors);
                if (errors.isEmpty()) throw new IllegalArgumentException("Invalid needs at least one error");
            }
        }

        static <T> Validation<T> valid(T value) { return new Valid<>(value); }
        static <T> Validation<T> invalid(List<String> errors) { return new Invalid<>(errors); }
        static <T> Validation<T> check(boolean ok, T value, String error) {
            return ok ? valid(value) : invalid(List.of(error));
        }

        default <R> Validation<R> map(Function<? super T, ? extends R> f) {
            return switch (this) {
                case Valid<T>(T value) -> valid(f.apply(value));
                case Invalid<T>(List<String> errors) -> invalid(errors);
            };
        }

        // Monadic: the next step needs this value, so an Invalid has to stop the chain.
        default <R> Validation<R> flatMap(Function<? super T, Validation<R>> f) {
            return switch (this) {
                case Valid<T>(T value) -> f.apply(value);
                case Invalid<T>(List<String> errors) -> invalid(errors);
            };
        }

        // Applicative: both results already exist, so every error can be kept.
        default <U, R> Validation<R> zipWith(Validation<U> other, BiFunction<? super T, ? super U, ? extends R> f) {
            return switch (new Both<>(this, other)) {
                case Both<T, U>(Valid<T>(T a), Valid<U>(U b)) -> valid(f.apply(a, b));
                case Both<T, U>(Valid<T> a, Invalid<U>(List<String> e)) -> invalid(e);
                case Both<T, U>(Invalid<T>(List<String> e), Valid<U> b) -> invalid(e);
                case Both<T, U>(Invalid<T>(List<String> e1), Invalid<U>(List<String> e2)) ->
                        invalid(Stream.concat(e1.stream(), e2.stream()).toList());
            };
        }
    }

    record Both<A, B>(Validation<A> first, Validation<B> second) {}

    interface Function4<A, B, C, D, R> { R apply(A a, B b, C c, D d); }

    // N fields from zipWith: carry a curried function along and feed it one argument at a time.
    static <A, B, C, D, R> Validation<R> combine(Validation<A> va, Validation<B> vb, Validation<C> vc,
                                                Validation<D> vd, Function4<A, B, C, D, R> f) {
        return va.zipWith(vb, (a, b) -> (Function<C, Function<D, R>>) c -> d -> f.apply(a, b, c, d))
                .zipWith(vc, (g, c) -> g.apply(c))
                .zipWith(vd, (g, d) -> g.apply(d));
    }

    record Form(String name, String email, String age, String password) {}

    record SignUp(String name, String email, int age, String password) {
        static int built = 0;
        SignUp { built++; }
    }

    static Validation<String> name(String raw) {
        return Validation.check(raw != null && !raw.isBlank(), raw, "name is required");
    }

    // Along one field the steps depend on each other: flatMap.
    static Validation<String> email(String raw) {
        return Validation.check(raw != null && !raw.isBlank(), raw, "email is required")
                .flatMap(e -> Validation.check(e.matches("[^@\\s]+@[^@\\s]+\\.[a-z]{2,}"), e,
                        "email '" + e + "' is not an address"));
    }

    // Parse, then check the parsed value. The result is an Integer, not a String.
    static Validation<Integer> age(String raw) {
        return Validation.check(raw != null && raw.matches("\\d{1,3}"), raw, "age must be a number")
                .map(Integer::parseInt)
                .flatMap(n -> Validation.check(n >= 18, n, "age must be at least 18"));
    }

    // Two independent rules on the same field: zipWith reports both.
    static Validation<String> password(String raw) {
        return Validation.check(raw != null, raw, "password is required")
                .flatMap(p -> Validation.check(p.length() >= 12, p, "password needs 12+ characters")
                        .zipWith(Validation.check(p.chars().anyMatch(Character::isDigit), p, "password needs a digit"),
                                (longEnough, hasDigit) -> p));
    }

    static Validation<SignUp> signUpWithFlatMap(Form form) {
        return name(form.name()).flatMap(n ->
               email(form.email()).flatMap(e ->
               age(form.age()).flatMap(a ->
               password(form.password()).map(p -> new SignUp(n, e, a, p)))));
    }

    static Validation<SignUp> signUpApplicative(Form form) {
        return combine(name(form.name()), email(form.email()), age(form.age()), password(form.password()),
                SignUp::new);
    }

    static void show(String label, Validation<SignUp> result) {
        switch (result) {
            case Validation.Valid<SignUp>(SignUp s) -> System.out.println(label + "valid " + s);
            case Validation.Invalid<SignUp>(List<String> errors) -> {
                System.out.println(label + errors.size() + " error(s)");
                errors.forEach(e -> System.out.println("    " + e));
            }
        }
    }

    public static void main(String[] args) {
        var bad = new Form("", "ada@lovelace", "12", "secret");
        show("flatMap chain: ", signUpWithFlatMap(bad));
        show("applicative:   ", signUpApplicative(bad));

        var good = new Form("Ada", "ada@example.org", "33", "correct horse 1");
        show("flatMap chain: ", signUpWithFlatMap(good));
        show("applicative:   ", signUpApplicative(good));
        System.out.println("SignUp records built: " + SignUp.built);

        // Why Validation is not a lawful monad: ap derived from flatMap disagrees with zipWith.
        Validation<Function<Integer, Integer>> brokenFunction = Validation.invalid(List.of("broken function"));
        Validation<Integer> brokenArgument = Validation.invalid(List.of("broken argument"));
        var viaZip = brokenFunction.zipWith(brokenArgument, (f, x) -> f.apply(x));
        var viaFlatMap = brokenFunction.flatMap(f -> brokenArgument.map(f));
        System.out.println("ap via zipWith:  " + viaZip);
        System.out.println("ap via flatMap:  " + viaFlatMap);
        System.out.println("consistent?      " + viaZip.equals(viaFlatMap));
    }
}
```

Output:

```text output
flatMap chain: 1 error(s)
    name is required
applicative:   5 error(s)
    name is required
    email 'ada@lovelace' is not an address
    age must be at least 18
    password needs 12+ characters
    password needs a digit
flatMap chain: valid SignUp[name=Ada, email=ada@example.org, age=33, password=correct horse 1]
applicative:   valid SignUp[name=Ada, email=ada@example.org, age=33, password=correct horse 1]
SignUp records built: 2
ap via zipWith:  Invalid[errors=[broken function, broken argument]]
ap via flatMap:  Invalid[errors=[broken function]]
consistent?      false
```

## How it works

* **Same input, two answers.** The bad form has five problems. The `flatMap` chain reports exactly one, because `email(...)` lives inside the lambda that only runs once a name exists. The applicative version calls all four field validators up front, then `combine` zips their results and keeps every error, including both password complaints.
* **`zipWith` is the whole applicative.** The four case nested record pattern over `Both` is exhaustive (javac checks it, no `default`), and the only interesting arm is the last one: two `Invalid`s become one with both lists.
* **`combine` scales `zipWith` to N fields** with a currying trick ([008](008-currying-composition.md)): zip the first two into a function still waiting for `c` and `d`, then zip that function with the third field, then the fourth. Vavr's `Validation.combine(v1, v2, v3).ap(f)` does the same job and ships one hand written overload per arity, from 2 to 8.
* **The record is built only in the all valid branch.** `SignUp::new` is called inside the `Valid, Valid` arm and nowhere else, so an invalid `SignUp` never exists. The counter proves it: two good runs, two records, and none from the bad form.
* **Parse, don't just validate.** `age` turns a `String` into an `Integer` on the way, so `SignUp` gets a real `int`. Validation and conversion are the same step.

### So why is this not a monad?

You *can* give it a `flatMap`, as the example does. The problem is that a monad's `ap` must be derivable from its `flatMap` (`vf.flatMap(f -> va.map(f))`), and that derived version can only short circuit, for the reason in [The problem](#the-problem): it never gets to look at the argument once the function is missing. The last three output lines show the two disagreeing on the same inputs. Cats calls this the `flatMapConsistentApply` law and refuses to give its `Validated` a `flatMap` at all; the sequential operation is named `andThen` so nobody mistakes it for the monadic one. Vavr is more pragmatic and offers `flatMap` anyway. Either way, know which one you are calling.

## Gotchas

* **Errors must be combinable.** Here they are a `List<String>`, concatenated. In general you need a *semigroup* for the error type (lists, sets, a `Map<Field, List<Message>>`). Pick the shape your UI needs before you write fifty validators.
* **`Invalid` with no errors is a lie.** The compact constructor rejects an empty list. Cats encodes the same rule in the type (`NonEmptyChain`).
* **Eager evaluation.** All field validators run, even after the first failure. That is the point, but it also means an expensive one (a database lookup for "email already taken") runs for a form whose name is blank. Put expensive checks in a second, `flatMap`ed phase after the cheap ones pass.
* **Generic arity boilerplate.** Java has no tuples or variadic generics, so `combine` for 5, 6 or 7 fields is another hand written overload each. This is the main reason teams reach for a library.

## When to use it (and when not to)

Use applicative validation at the edges, wherever a human or a remote system sends you several independent fields: forms, API payloads, CSV rows, configuration. It gives users every problem in one round trip and hands your domain a fully typed, already valid object, or nothing.

The OO twin of this idea is the [notification pattern (011)](../02-patterns/011-notification-validator.md): a mutable collector passed through imperative checks. It is easier for most teams to read and it is the better choice in a codebase that does not otherwise speak `map` and `flatMap`. `Validation` wins when you want the *result type* to guarantee validity (you cannot get a `SignUp` out of an `Invalid`), when validators should compose like functions, or when parsing and validating are the same step. For checks that depend on each other, plain [Either (002)](002-either.md) and its fail fast `flatMap` remain the right tool.

## Related

* [002 · Either: Typed Errors Without Exceptions](002-either.md), the fail fast sibling
* [008 · Currying, Partial Application and Function Composition](008-currying-composition.md), the trick inside `combine`
* [011 · Notification Pattern Validator](../02-patterns/011-notification-validator.md), the object oriented version of the same goal
* [038 · Higher-Kinded Types in Java (Yes, Really)](../04-generics/038-higher-kinded-types.md), to abstract over "any applicative"

## Sources

* Conor McBride and Ross Paterson, [Applicative programming with effects](https://www.staff.city.ac.uk/~ross/papers/Applicative.pdf) (2008), the paper that introduced applicative functors
* [Cats: Validated](https://typelevel.org/cats/datatypes/validated.html), including the `flatMapConsistentApply` argument and `andThen`
* [Vavr `Validation` source (0.10.5)](https://github.com/vavr-io/vavr/blob/v0.10.5/vavr/src/main/java/io/vavr/control/Validation.java), with `combine(...).ap(...)` and a pragmatic `flatMap`
* Alexis King, [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/) (2019)
