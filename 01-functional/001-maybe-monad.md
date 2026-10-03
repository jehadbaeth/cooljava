# 001 · The Maybe Monad from Scratch

> Twenty lines of sealed interface buy you a value that might not be there, a chain that never NPEs, and three laws you can actually test.

**Since:** Java 21 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Null checks nest. Every lookup that can fail adds a level:

```java
String city = null;
User user = users.get(id);
if (user != null) {
    Address address = user.address();
    if (address != null) {
        city = address.city();
    }
}
```

`Optional` flattens this, but it is worth building the real thing once. You learn what a monad is (spoiler: a type with `flatMap` that obeys three rules), and you learn why `Optional` is *almost* one but not quite.

## The trick

A **Maybe** is a sum type with two cases: `Just(value)` or `Nothing`. Sealed interfaces and records make that a one-liner each, and pattern matching makes the operations short:

```java
sealed interface Maybe<T> {
    record Just<T>(T value) implements Maybe<T> {
        public Just { Objects.requireNonNull(value, "Just(null) is not a thing"); }
    }
    record Nothing<T>() implements Maybe<T> {}

    default <R> Maybe<R> flatMap(Function<? super T, Maybe<R>> f) {
        return switch (this) {
            case Just<T>(T value) -> f.apply(value);
            case Nothing<T>()     -> new Nothing<>();
        };
    }
}
```

That `flatMap` is the whole monad. `map` is derived from it, and so is everything else.

A type is a **monad** when it has a constructor (`just`, often called *unit* or *return*) and a `flatMap` (*bind*) that satisfy:

| Law | In code | Meaning |
|---|---|---|
| Left identity | `just(a).flatMap(f)` equals `f.apply(a)` | Wrapping then binding does nothing extra |
| Right identity | `m.flatMap(Maybe::just)` equals `m` | Binding to the constructor is a no-op |
| Associativity | `m.flatMap(f).flatMap(g)` equals `m.flatMap(x -> f.apply(x).flatMap(g))` | You can regroup a chain freely |

Because records get structural `equals` for free, those laws become plain boolean checks.

## Full example

```java run
import java.util.*;
import java.util.function.*;

public class MaybeDemo {

    sealed interface Maybe<T> {
        record Just<T>(T value) implements Maybe<T> {
            public Just { Objects.requireNonNull(value, "Just(null) is not a thing"); }
        }
        record Nothing<T>() implements Maybe<T> {}

        static <T> Maybe<T> just(T value) { return new Just<>(value); }
        static <T> Maybe<T> nothing() { return new Nothing<>(); }
        static <T> Maybe<T> ofNullable(T value) { return value == null ? nothing() : just(value); }

        default <R> Maybe<R> flatMap(Function<? super T, Maybe<R>> f) {
            return switch (this) {
                case Just<T>(T value) -> f.apply(value);
                case Nothing<T>() -> nothing();
            };
        }

        // map is just flatMap followed by the constructor.
        default <R> Maybe<R> map(Function<? super T, ? extends R> f) {
            return flatMap(value -> just(f.apply(value)));
        }

        default Maybe<T> filter(Predicate<? super T> p) {
            return flatMap(value -> p.test(value) ? just(value) : nothing());
        }

        default <R> R fold(Supplier<? extends R> ifNothing, Function<? super T, ? extends R> ifJust) {
            return switch (this) {
                case Just<T>(T value) -> ifJust.apply(value);
                case Nothing<T>() -> ifNothing.get();
            };
        }

        default T orElse(T fallback) { return fold(() -> fallback, v -> v); }
    }

    record Address(String city) {}
    record User(String name, Address address) {}

    static final Map<Integer, User> USERS = Map.of(
            1, new User("Ada", new Address("London")),
            2, new User("Linus", null));

    static Maybe<User> findUser(int id) { return Maybe.ofNullable(USERS.get(id)); }

    static String cityOf(int id) {
        return findUser(id)
                .flatMap(u -> Maybe.ofNullable(u.address()))
                .map(Address::city)
                .map(String::toUpperCase)
                .orElse("<unknown>");
    }

    public static void main(String[] args) {
        System.out.println("1 -> " + cityOf(1));
        System.out.println("2 -> " + cityOf(2));   // user without address
        System.out.println("3 -> " + cityOf(3));   // no such user

        // The three monad laws, checked with record equality.
        Function<Integer, Maybe<Integer>> half = n -> n % 2 == 0 ? Maybe.just(n / 2) : Maybe.nothing();
        Function<Integer, Maybe<String>> show = n -> Maybe.just("#" + n);
        for (Maybe<Integer> m : List.of(Maybe.just(8), Maybe.just(3), Maybe.<Integer>nothing())) {
            boolean left = m.fold(() -> true, a -> Maybe.just(a).flatMap(half).equals(half.apply(a)));
            boolean right = m.flatMap(Maybe::just).equals(m);
            boolean assoc = m.flatMap(half).flatMap(show)
                    .equals(m.flatMap(x -> half.apply(x).flatMap(show)));
            System.out.printf("%-20s left=%b right=%b assoc=%b%n", m, left, right, assoc);
        }

        // Why Optional is not quite a lawful functor: map() silently turns null into empty.
        Function<String, String> toNull = s -> null;
        Function<String, String> describe = s -> s == null ? "it was null" : s;
        Optional<String> twoSteps = Optional.of("x").map(toNull).map(describe);
        Optional<String> oneStep = Optional.of("x").map(toNull.andThen(describe));
        System.out.println("Optional map(f).map(g)      = " + twoSteps);
        System.out.println("Optional map(f.andThen(g))  = " + oneStep);
        System.out.println("composition law holds?        " + twoSteps.equals(oneStep));
    }
}
```

Output:

```text output
1 -> LONDON
2 -> <unknown>
3 -> <unknown>
Just[value=8]        left=true right=true assoc=true
Just[value=3]        left=true right=true assoc=true
Nothing[]            left=true right=true assoc=true
Optional map(f).map(g)      = Optional.empty
Optional map(f.andThen(g))  = Optional[it was null]
composition law holds?        false
```

## How it works

* **`sealed` plus records** gives an algebraic data type: a `Maybe` is *exactly* a `Just` or a `Nothing`, and the compiler knows it, so the `switch` needs no `default` branch.
* **Record patterns** (`case Just<T>(T value)`) deconstruct and bind in one step. This is Java 21 syntax. On Java 17 you would write `if (this instanceof Just<T> j) return f.apply(j.value());`.
* **`Just` refuses `null`** in its compact constructor. That is what makes the laws hold: there is no way to smuggle an absent value into a present one.
* **`map` is defined via `flatMap`.** If a function passed to `map` returns `null`, `Maybe` fails loudly (`just(null)` throws) instead of quietly changing meaning. If you want "null means absent", say so explicitly with `flatMap(v -> Maybe.ofNullable(...))`.

### So is `Optional` a monad?

Mostly, in practice. Formally, no. `Optional.map` treats a `null` result as "empty", which breaks the functor composition law, as the last three lines of output show: the same two functions give different answers depending on whether you compose them before or after mapping. The same `null` handling breaks left identity if you pick `ofNullable` as the constructor. This was a deliberate design choice. `Optional` was introduced as a *return type for "no result"*, not as a general purpose monad, and Brian Goetz has said as much publicly (see Sources). Know the edge, then use it happily.

## Gotchas

* **`Nothing` equality.** `new Nothing<String>().equals(new Nothing<Integer>())` is `true` because erasure leaves nothing to compare. That is fine semantically but surprises people who use it as a map key.
* **Allocation.** Every `nothing()` allocates. A shared singleton needs an unchecked cast (`@SuppressWarnings("unchecked")`), which is safe here because `Nothing` holds no `T`.
* **Do not put `Maybe` in fields or parameters** just because you can. Same advice as for `Optional`: it shines as a return type and in pipelines.
* **Interop.** Add `toOptional()` and `fromOptional()` so your custom type does not become an island in a codebase full of `Optional`.

## When to use it (and when not to)

Build it to *understand* monads, or when you want a stricter, law abiding variant with a few extras (`fold`, exhaustive pattern matching). In production code, `java.util.Optional` is the boring, interoperable answer, and boring is a feature. If you need a full functional toolkit (Option, Either, Try, persistent collections), use [Vavr](https://vavr.io/) instead of growing your own.

## Related

* [002 · Either: Typed Errors Without Exceptions](002-either.md), the same idea but the "nothing" case explains *why*
* [003 · Try: Turning Exceptions into Values](003-try-monad.md)
* [038 · Higher-Kinded Types in Java](../04-generics/038-higher-kinded-types.md), to write code that works for *any* monad
* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md)

## Sources

* [JEP 409: Sealed Classes](https://openjdk.org/jeps/409) and [JEP 440: Record Patterns](https://openjdk.org/jeps/440)
* Brian Goetz on the intent behind `Optional`, [Stack Overflow answer](https://stackoverflow.com/a/26328555) (2014)
* [`java.util.Optional` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/Optional.html)
* Philip Wadler, [Monads for functional programming](https://homepages.inf.ed.ac.uk/wadler/papers/marktoberdorf/baastad.pdf) (1995)
* [Vavr](https://vavr.io/), a mature functional library for Java
