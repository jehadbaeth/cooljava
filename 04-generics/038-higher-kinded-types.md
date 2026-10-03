# 038 · Higher-Kinded Types in Java (Yes, Really)

> Java can abstract over `String` in `List<String>`, but never over `List` itself. A 2014 OCaml idea, one marker interface and a few empty enums get you a `Functor`, a `Monad` and a `Monoid` that work for any container you like.

**Since:** Java 9 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

`Optional` and `Stream` both have a `map` and a `flatMap`, and the laws they obey are the same ones ([001 · The Maybe Monad](../01-functional/001-maybe-monad.md) spells them out). Yet you cannot write a method once that works for all of them, because the thing they have in common is a *type constructor*: something that turns a type `A` into a type `F<A>`. Type parameters in Java stand for types, not for constructors. The natural attempt does not compile:

```java compile-fail
public class NoHkt {
    // The natural attempt: let F stand for a type constructor such as List or Optional.
    interface Container<F> {
        <A> F<A> wrap(A value);
    }

    public static void main(String[] args) {}
}
```

```text compile-error
NoHkt.java:4: error: unexpected type
        <A> F<A> wrap(A value);
            ^
  required: class
  found:    type parameter F
  where F is a type-variable:
    F extends Object declared in interface Container
1 error
```

Languages with *higher-kinded types* (Haskell, Scala) accept `F<A>` here. Java does not. But there is a well known way around it.

## The trick

Jeremy Yallop and Leo White showed in "Lightweight higher-kinded polymorphism" (FLOPS 2014) how to get higher-kinded programming in OCaml without its functor machinery. The paper uses "an abstract type `app` to represent type application, and opaque brands to denote abstractable type constructors", plus injection and projection functions to move between a real type and its encoded form. The idea is a defunctionalization: instead of passing the type constructor around, pass a *name* for it.

In Java the same three pieces look like this:

* `interface Kind<F, A> {}` is `app`. Read it as "`F` applied to `A`".
* `F` is the **witness** (the paper says brand): an ordinary, never instantiated type that names a type constructor. By convention it is called `Mu`, and it is nested in the wrapper class, as in `ListKind.Mu`. That is a Java convention, not the paper's name.
* `of` and `narrow` are injection and projection: they wrap a real `List<A>` into a `Kind<ListKind.Mu, A>` and back.

With that, `Functor` takes the witness instead of the constructor, and `F<B>` becomes `Kind<F, B>`: `<A, B> Kind<F, B> map(Kind<F, A> fa, Function<? super A, ? extends B> f)`. Everything is a plain generic type again, so javac accepts it, and code written against `Functor<F>` is written once and handed the instance for lists, optionals or your own types.

## Full example

```java run
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.function.BinaryOperator;
import java.util.function.Function;

public class HktDemo {

    // Kind<F, A> reads "F applied to A". F is a witness (brand), never instantiated.
    interface Kind<F, A> {}

    interface Functor<F> {
        <A, B> Kind<F, B> map(Kind<F, A> fa, Function<? super A, ? extends B> f);
    }

    interface Monad<F> extends Functor<F> {
        <A> Kind<F, A> pure(A value);
        <A, B> Kind<F, B> flatMap(Kind<F, A> fa, Function<? super A, ? extends Kind<F, B>> f);
    }

    interface Foldable<F> {
        <A, M> M foldMap(Kind<F, A> fa, Monoid<M> monoid, Function<? super A, ? extends M> f);
    }

    interface Monoid<T> {
        T empty();
        T combine(T left, T right);

        static <T> Monoid<T> of(T empty, BinaryOperator<T> op) {
            return new Monoid<>() {
                public T empty() { return empty; }
                public T combine(T left, T right) { return op.apply(left, right); }
            };
        }
    }

    static final Monoid<Integer> SUM = Monoid.of(0, Integer::sum);
    static final Monoid<String> CONCAT = Monoid.of("", String::concat);

    // ---- Witness for java.util.List: wrap it, and brand the wrapper. ----
    static final class ListKind<A> implements Kind<ListKind.Mu, A> {
        enum Mu {}   // uninhabited, like the marker types in the phantom types document
        private final List<A> list;
        private ListKind(List<A> list) { this.list = list; }
        static <A> Kind<Mu, A> of(List<A> list) { return new ListKind<>(list); }
        static <A> List<A> narrow(Kind<Mu, A> kind) { return ((ListKind<A>) kind).list; }
    }

    static final class OptionalKind<A> implements Kind<OptionalKind.Mu, A> {
        enum Mu {}
        private final Optional<A> optional;
        private OptionalKind(Optional<A> optional) { this.optional = optional; }
        static <A> Kind<Mu, A> of(Optional<A> optional) { return new OptionalKind<>(optional); }
        static <A> Optional<A> narrow(Kind<Mu, A> kind) { return ((OptionalKind<A>) kind).optional; }
    }

    // ---- Instances ----
    static final class ListInstance implements Monad<ListKind.Mu>, Foldable<ListKind.Mu> {
        public <A, B> Kind<ListKind.Mu, B> map(Kind<ListKind.Mu, A> fa, Function<? super A, ? extends B> f) {
            List<B> out = new ArrayList<>();
            for (A a : ListKind.narrow(fa)) out.add(f.apply(a));
            return ListKind.of(out);
        }
        public <A> Kind<ListKind.Mu, A> pure(A value) { return ListKind.of(List.of(value)); }
        public <A, B> Kind<ListKind.Mu, B> flatMap(Kind<ListKind.Mu, A> fa,
                Function<? super A, ? extends Kind<ListKind.Mu, B>> f) {
            List<B> out = new ArrayList<>();
            for (A a : ListKind.narrow(fa)) out.addAll(ListKind.narrow(f.apply(a)));
            return ListKind.of(out);
        }
        public <A, M> M foldMap(Kind<ListKind.Mu, A> fa, Monoid<M> monoid, Function<? super A, ? extends M> f) {
            M result = monoid.empty();
            for (A a : ListKind.narrow(fa)) result = monoid.combine(result, f.apply(a));
            return result;
        }
    }

    static final class OptionalInstance implements Monad<OptionalKind.Mu>, Foldable<OptionalKind.Mu> {
        public <A, B> Kind<OptionalKind.Mu, B> map(Kind<OptionalKind.Mu, A> fa, Function<? super A, ? extends B> f) {
            return OptionalKind.of(OptionalKind.narrow(fa).map(f));
        }
        public <A> Kind<OptionalKind.Mu, A> pure(A value) { return OptionalKind.of(Optional.of(value)); }
        public <A, B> Kind<OptionalKind.Mu, B> flatMap(Kind<OptionalKind.Mu, A> fa,
                Function<? super A, ? extends Kind<OptionalKind.Mu, B>> f) {
            Optional<A> optional = OptionalKind.narrow(fa);
            return optional.isPresent() ? f.apply(optional.get()) : OptionalKind.of(Optional.empty());
        }
        public <A, M> M foldMap(Kind<OptionalKind.Mu, A> fa, Monoid<M> monoid, Function<? super A, ? extends M> f) {
            Optional<A> optional = OptionalKind.narrow(fa);
            return optional.isPresent() ? f.apply(optional.get()) : monoid.empty();
        }
    }

    // ---- Generic code, written once for every F that has the right instances. ----
    static <F> Kind<F, String> shout(Functor<F> functor, Kind<F, String> words) {
        return functor.map(words, w -> w.toUpperCase() + "!");
    }

    static <F> String stats(Functor<F> functor, Foldable<F> foldable, Kind<F, String> words) {
        int letters = foldable.foldMap(functor.map(words, String::length), SUM, n -> n);
        String initials = foldable.foldMap(words, CONCAT, w -> w.substring(0, 1));
        return letters + " letters, initials " + initials;
    }

    // With lists this means "every combination", with optionals "only if both are present".
    static <F> Kind<F, String> pairUp(Monad<F> monad, Kind<F, String> names, Kind<F, Integer> numbers) {
        return monad.flatMap(names, name -> monad.map(numbers, n -> name + n));
    }

    public static void main(String[] args) {
        ListInstance lists = new ListInstance();
        OptionalInstance optionals = new OptionalInstance();

        Kind<ListKind.Mu, String> crew = ListKind.of(List.of("Ada", "Grace", "Katherine"));
        Kind<OptionalKind.Mu, String> pilot = OptionalKind.of(Optional.of("Yuri"));

        System.out.println(ListKind.narrow(shout(lists, crew)));
        System.out.println(OptionalKind.narrow(shout(optionals, pilot)));

        System.out.println(stats(lists, lists, crew));
        System.out.println(stats(optionals, optionals, pilot));

        Kind<ListKind.Mu, Integer> ones = ListKind.of(List.of(1, 2));
        Kind<OptionalKind.Mu, Integer> seven = OptionalKind.of(Optional.of(7));
        Kind<OptionalKind.Mu, Integer> none = OptionalKind.of(Optional.empty());
        System.out.println(ListKind.narrow(pairUp(lists, ListKind.of(List.of("a", "b")), ones)));
        System.out.println(OptionalKind.narrow(pairUp(optionals, pilot, seven)));
        System.out.println(OptionalKind.narrow(pairUp(optionals, pilot, none)));

        // narrow is a trusted downcast: a forged Kind with the right brand fails there.
        Kind<ListKind.Mu, String> forged = new Kind<>() {};
        try {
            ListKind.narrow(forged);
        } catch (ClassCastException e) {
            System.out.println("forged kind: ClassCastException");
        }
    }
}
```

Output:

```text output
[ADA!, GRACE!, KATHERINE!]
Optional[YURI!]
17 letters, initials AGK
4 letters, initials Y
[a1, a2, b1, b2]
Optional[Yuri7]
Optional.empty
forged kind: ClassCastException
```

Two things javac does for you here. A witness cannot be mixed up with another one, so handing an optional to the list functor is a compile error, with an error message that names both witnesses:

```java compile-fail
import java.util.function.Function;

public class WrongWitness {
    interface Kind<F, A> {}
    enum ListMu {}
    enum OptionalMu {}

    interface Functor<F> {
        <A, B> Kind<F, B> map(Kind<F, A> fa, Function<? super A, ? extends B> f);
    }

    static Functor<ListMu> listFunctor() { return null; }
    static Kind<OptionalMu, String> name() { return null; }

    public static void main(String[] args) {
        listFunctor().map(name(), String::length);
    }
}
```

```text compile-error
WrongWitness.java:16: error: method map in interface Functor<F> cannot be applied to given types;
        listFunctor().map(name(), String::length);
                     ^
  required: Kind<ListMu,A>,Function<? super A,? extends B>
  found:    Kind<OptionalMu,String>,String::length
  reason: cannot infer type-variable(s) A,B
    (argument mismatch; Kind<OptionalMu,String> cannot be converted to Kind<ListMu,A>)
  where A,B,F are type-variables:
    A extends Object declared in method <A,B>map(Kind<F,A>,Function<? super A,? extends B>)
    B extends Object declared in method <A,B>map(Kind<F,A>,Function<? super A,? extends B>)
    F extends Object declared in interface Functor
1 error
```

## How it works

* **A witness is a name, not a type constructor.** `Kind<ListKind.Mu, String>` means "`List` of `String`", but javac only ever sees two ordinary type arguments. That is why every rule of normal generics (inference, bounds, wildcards) keeps working, and also why the encoding costs you a wrapper object.
* **The brand is uninhabited.** `enum Mu {}` has no constants, so nobody can create a value of it. The paper introduces brands as "an uninhabited opaque type". It is the same device as the marker types in [030 · Phantom Types](030-phantom-types.md): a type that exists only inside angle brackets, so the witness is a phantom parameter of `Kind`.
* **Instances are passed explicitly.** Java has no implicit resolution, so `shout(lists, crew)` takes the `Functor` object as a parameter. `ListInstance` implements `Monad` and `Foldable` for the list witness in one class.
* **`Monad<F> extends Functor<F>`** is where the idea pays off, and it keeps the promise of [001](../01-functional/001-maybe-monad.md): code that works for *any* monad. `pairUp` uses only `flatMap` and `map`. With the list instance it means "every combination" (`[a1, a2, b1, b2]`), with the optional instance "only if both are present" (`Optional[Yuri7]`, or `Optional.empty`). The code is identical, the meaning comes from the instance.
* **`Monoid` plus `foldMap` is a generic fold.** A monoid is an `empty` value and an associative `combine`. `foldMap` maps every element into the monoid and combines the results, so `stats` computes a sum (`SUM`) and a string (`CONCAT`) from lists and from optionals with the same function.

## Gotchas

* **The ergonomics are poor, and that is the honest summary.** Every value crossing into generic code is wrapped, every result is narrowed, and every call passes an instance explicitly. Signatures grow a `Kind<F, ...>` and a `Functor<F>` parameter. Wrapping a `List` in a `ListKind` is also one extra object per call boundary. Compare all that with calling `Optional.map` directly.
* **`narrow` is a trusted downcast.** Nothing stops someone from writing `new Kind<ListKind.Mu, String>() {}`. The last line of the output shows that forged value blowing up with a `ClassCastException` inside `narrow`. Making `Kind` sealed would stop forgeries, but it would also stop anyone outside the package from adding instances. Real encodings accept the risk, or hide the constructors and trust convention. (A type you own can also implement `Kind<Its.Mu, A>` itself and skip the wrapper, but the same forgery applies.)
* **There is no kind checking.** `Kind<String, Integer>` compiles, because `F` is just a type. The paper points out the same weakness: the type checker will not stop ill-kinded expressions. And types with several parameters need partial application: `Either<E, _>` needs a witness that fixes `E`, for example a generic `EitherKind.Mu<E>`, which is another page of boilerplate.
* **Existing libraries are experiments or big commitments.** [highj](https://github.com/highj/highj) describes itself as "just an experiment" that "relies heavily on Java 8 features" and is "not yet intended for production". [Higher-Kinded-J](https://github.com/higher-kinded-j/higher-kinded-j) describes itself as "a simulation of higher-kinded types by defunctionalisation" and is built on JDK 25. [derive4j/hkt](https://github.com/derive4j/hkt) is an annotation processor that provides the encoding and builds on the same paper. All three exist, none is the JDK, and adopting one means adopting its wrappers everywhere.

## When to use it (and when not to)

Use it to learn what a type class really is, to prototype a functional library, or when you are genuinely writing abstractions over *effects* (free monads, tagless final interpreters, `traverse` and `sequence` for arbitrary containers) where the alternative is copying the same algorithm once per container. That is the use case where the machinery pays for itself.

In application code it is a party trick. Business logic that names `Optional` or `List` directly is shorter, faster and readable by the next person. When two types share behavior, a plain interface or a sealed hierarchy ([040](../05-modern-language/040-algebraic-data-types.md)) does the job without a witness. The encoding itself needs only generics, so the technique is not tied to a recent Java version.

## Related

* [001 · The Maybe Monad from Scratch](../01-functional/001-maybe-monad.md), the monad laws that `pairUp` relies on
* [030 · Phantom Types: Let the Compiler Track State](030-phantom-types.md), where the uninhabited marker type comes from
* [035 · PECS and Wildcard Capture](035-pecs-wildcard-capture.md), for the `? super A` and `? extends B` in `map`
* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md), the plain alternative when types share behavior

## Sources

* Jeremy Yallop and Leo White, [Lightweight higher-kinded polymorphism](https://link.springer.com/chapter/10.1007/978-3-319-07151-0_8), in *Functional and Logic Programming (FLOPS 2014)*, Springer, 2014 ([author PDF](https://www.cl.cam.ac.uk/~jdy22/papers/lightweight-higher-kinded-polymorphism.pdf))
* [highj](https://github.com/highj/highj), higher kinded types for Java
* [Higher-Kinded-J](https://github.com/higher-kinded-j/higher-kinded-j)
* [derive4j/hkt](https://github.com/derive4j/hkt), higher-kinded type machinery for Java
