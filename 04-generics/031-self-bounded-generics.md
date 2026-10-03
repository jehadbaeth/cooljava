# 031 · Self-Bounded Generics for Inheritable Builders

> `Builder<T extends Builder<T>>` reads like a typo in a hall of mirrors, yet it is how a subclass builder keeps its fluent chain, and the JDK has shipped the same shape in `Enum` since Java 5.

**Since:** Java 8 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

You have a base class with a builder and a few subclasses that add their own fields. The obvious design puts the shared setters in the base builder and the extra ones in the subclass builders. It works until somebody calls a base method first: `header()` is declared to return `Builder`, so the chain forgets it ever held a `JsonBuilder`:

```java compile-fail
public class NaiveBuilder {
    static class Builder {
        Builder header(String name, String value) { return this; }
    }

    static class JsonBuilder extends Builder {
        JsonBuilder body(String json) { return this; }
    }

    public static void main(String[] args) {
        new JsonBuilder()
                .header("Accept", "application/json")
                .body("{}");
    }
}
```

```text compile-error
NaiveBuilder.java:13: error: cannot find symbol
                .body("{}");
                ^
  symbol:   method body(String)
  location: class Builder
1 error
```

You could override every base setter in every subclass just to narrow the return type. That is a lot of code whose only job is to say "me, but more specific".

## The trick

Give the base builder a type parameter that stands for **the concrete builder itself**, and make every fluent method return it. Joshua Bloch calls this the *simulated self-type idiom* (Effective Java, 3rd edition, Item 2):

```java
abstract static class Builder<T extends Builder<T>> {
    T header(String name, String value) { headers.put(name, value); return self(); }
    protected abstract T self();
}

static final class Builder extends Request.Builder<Builder> {   // inside JsonRequest
    Builder body(String json) { this.body = json; return this; }
    @Override protected Builder self() { return this; }
}
```

The recursive bound `T extends Builder<T>` says "T is some builder of this family". Each concrete subclass plugs itself in as `T`, so `header()` on a `JsonRequest.Builder` returns a `JsonRequest.Builder`. The `self()` method exists because `this` has the static type `Builder<T>`, not `T`, and Java has no way to say "the type of `this`". C++ programmers know the shape as the curiously recurring template pattern (CRTP).

## Full example

```java run
import java.util.*;

public class SelfBoundedDemo {

    abstract static class Request {
        final String endpoint;
        final SortedMap<String, String> headers;
        final int timeoutSeconds;

        /** T is "the concrete builder". Every fluent method returns T, never Builder. */
        abstract static class Builder<T extends Builder<T>> {
            private final String endpoint;
            private final SortedMap<String, String> headers = new TreeMap<>();
            private int timeoutSeconds = 30;

            Builder(String endpoint) { this.endpoint = endpoint; }

            T header(String name, String value) { headers.put(name, value); return self(); }
            T timeout(int seconds) { timeoutSeconds = seconds; return self(); }

            abstract Request build();

            /** The simulated self type: each concrete builder answers "return this". */
            protected abstract T self();
        }

        Request(Builder<?> b) {
            endpoint = b.endpoint;
            headers = Collections.unmodifiableSortedMap(new TreeMap<>(b.headers));
            timeoutSeconds = b.timeoutSeconds;
        }
    }

    static final class JsonRequest extends Request {
        final String body;

        static final class Builder extends Request.Builder<Builder> {
            private String body = "{}";

            Builder(String endpoint) { super(endpoint); }
            Builder body(String json) { body = json; return this; }

            @Override JsonRequest build() { return new JsonRequest(this); }   // covariant return
            @Override protected Builder self() { return this; }
        }

        private JsonRequest(Builder b) { super(b); body = b.body; }

        @Override public String toString() {
            return "JSON " + endpoint + " " + headers + " timeout=" + timeoutSeconds + "s body=" + body;
        }
    }

    static final class FormRequest extends Request {
        final SortedMap<String, String> fields;

        static final class Builder extends Request.Builder<Builder> {
            private final SortedMap<String, String> fields = new TreeMap<>();

            Builder(String endpoint) { super(endpoint); }
            Builder field(String name, String value) { fields.put(name, value); return this; }

            @Override FormRequest build() { return new FormRequest(this); }
            @Override protected Builder self() { return this; }
        }

        private FormRequest(Builder b) { super(b); fields = new TreeMap<>(b.fields); }

        @Override public String toString() {
            return "FORM " + endpoint + " " + headers + " timeout=" + timeoutSeconds + "s fields=" + fields;
        }
    }

    // Enum<E extends Enum<E>> is the same idea: getDeclaringClass() returns Class<E>, so no casts.
    static <E extends Enum<E>> E next(E value) {
        E[] all = value.getDeclaringClass().getEnumConstants();
        return all[(value.ordinal() + 1) % all.length];
    }

    enum Light { RED, GREEN, YELLOW }

    // The tempting shortcut: an unchecked cast instead of an abstract self().
    abstract static class LazyBuilder<T extends LazyBuilder<T>> {
        String name;

        @SuppressWarnings("unchecked")
        T name(String n) { name = n; return (T) this; }
    }
    static final class Honest extends LazyBuilder<Honest> {}
    static final class Liar extends LazyBuilder<Honest> {}   // compiles: the bound cannot say "me"

    public static void main(String[] args) {
        JsonRequest json = new JsonRequest.Builder("satellites.track")
                .header("Accept-Language", "en")         // still a JsonRequest.Builder here
                .timeout(5)
                .body("{\"track\": true}")              // so the subclass method is reachable
                .build();                                 // and build() returns JsonRequest
        System.out.println(json);

        FormRequest form = new FormRequest.Builder("auth.login")
                .field("user", "ada")
                .header("X-Trace", "abc123")
                .field("remember", "yes")
                .build();
        System.out.println(form);

        System.out.println("next(YELLOW) = " + next(Light.YELLOW));
        System.out.println("next(RED)    = " + next(Light.RED));

        Honest honest = new Honest().name("fine");
        System.out.println("Honest builder: " + honest.name);
        try {
            Honest stolen = new Liar().name("oops");
            System.out.println("never printed " + stolen);
        } catch (ClassCastException e) {
            System.out.println("Liar builder: " + e.getClass().getSimpleName() + " at the call site");
        }
    }
}
```

Output:

```text output
JSON satellites.track {Accept-Language=en} timeout=5s body={"track": true}
FORM auth.login {X-Trace=abc123} timeout=30s fields={remember=yes, user=ada}
next(YELLOW) = RED
next(RED)    = GREEN
Honest builder: fine
Liar builder: ClassCastException at the call site
```

With the abstract `self()` from the main example, the liar is caught by the compiler instead, because `return this` no longer type checks:

```java compile-fail
public class LiarBuilder {
    abstract static class Builder<T extends Builder<T>> {
        protected abstract T self();
    }

    static final class Honest extends Builder<Honest> {
        @Override protected Honest self() { return this; }
    }

    static final class Liar extends Builder<Honest> {
        @Override protected Honest self() { return this; }
    }

    public static void main(String[] args) {}
}
```

```text compile-error
LiarBuilder.java:11: error: incompatible types: Liar cannot be converted to Honest
        @Override protected Honest self() { return this; }
                                                   ^
1 error
```

## How it works

* **The recursive bound is a promise, not a proof.** `T extends Builder<T>` only guarantees that `T` is *a* builder in the family. `Liar extends LazyBuilder<Honest>` satisfies it, because `Honest` really is a `LazyBuilder<Honest>`. Java has no "this type" keyword, which is why the idiom is called *simulated*.
* **Where the cast blows up.** In `LazyBuilder`, `(T) this` erases to a cast to the bound, `LazyBuilder`, so javac emits no cast instruction at all (`javap -c` shows a bare `areturn`). The real check is the `checkcast Honest` that javac inserts at the *caller*, so the `ClassCastException` appears in `main`, one step away from the actual bug. That is the general shape of heap pollution (see [039](039-erasure-and-arrays.md)).
* **Abstract `self()` moves the check to compile time.** Each concrete builder must write `return this`, and that line only compiles when `T` is really the builder's own type. A perverse subclass could still `return new Honest()`, but nobody does that by accident.
* **Covariant `build()`.** The base declares `abstract Request build()`, and each subclass narrows it to `JsonRequest build()`. That has been legal since Java 5 and needs no generics at all.
* **`Enum<E extends Enum<E>>`** is the JDK's own CRTP. Every `enum Light` compiles to `final class Light extends Enum<Light>`. The bound is why `compareTo(E)` accepts only constants of the *same* enum, why `EnumSet<E extends Enum<E>>` exists, and why `getDeclaringClass()` can return `Class<E>`, which lets `next()` above stay cast free.
* **`BaseStream<T, S extends BaseStream<T, S>>`** uses the same trick so that `parallel()`, `sequential()`, `unordered()` and `onClose()` return `Stream<T>` on a `Stream` and `IntStream` on an `IntStream`.
* **`Comparable<T>` is self-typed by convention only.** Nothing stops `class Money implements Comparable<String>`. Generic algorithms therefore ask for `<T extends Comparable<? super T>>`, which [035](035-pecs-wildcard-capture.md) takes apart.

The idiom is as old as generics (Java 5). The example sticks to plain classes, so it compiles on Java 8, the oldest release today's javac can still target.

## Gotchas

* **Every non-leaf level must stay generic.** If `JsonRequest` should itself be extensible, you need an abstract `JsonRequest.Builder<T extends JsonRequest.Builder<T>> extends Request.Builder<T>` plus a concrete leaf builder. Making an intermediate builder concrete freezes `T`, and subclasses below it lose their chain again.
* **Raw types switch it all off.** A raw `Request.Builder` variable makes `header()` return the erasure of `T`, which is plain `Request.Builder`, and the chain loses every subclass method. The warning is easy to miss.
* **Readers will squint.** `class Foo<T extends Foo<T>>` costs a comment, every time. Put the comment on the base builder, not on each subclass.
* **Lombok can write it for you.** `@SuperBuilder` generates an abstract builder plus a concrete `...BuilderImpl` per class with exactly this kind of recursive generics and an internal `self()` method. Use it if you already use Lombok, and read the delomboked code once so the error messages make sense.

## When to use it (and when not to)

Use it when a class hierarchy is genuinely part of your API and subclasses need fluent construction: request builders, test fixtures, assertion libraries (AssertJ's `AbstractAssert<SELF extends AbstractAssert<SELF, ACTUAL>, ACTUAL>` is a well-known example in the wild). It is also the right tool for "any enum" utilities, where `<E extends Enum<E>>` is simply how you spell the bound.

Skip it when the hierarchy is not essential. A sealed interface of records with one plain builder or a static factory per record is flatter and easier to read, and composition beats a three-level builder hierarchy almost every time. If all you need is copies with one field changed, look at [withers](../02-patterns/014-record-withers.md) instead.

## Related

* [030 · Phantom Types: Let the Compiler Track State](030-phantom-types.md)
* [013 · Step Builder: Compile-Time Required Fields](../02-patterns/013-step-builder.md)
* [035 · PECS and Wildcard Capture](035-pecs-wildcard-capture.md), for `Comparable<? super T>`
* [039 · Type Erasure Puzzlers and Generic Arrays](039-erasure-and-arrays.md), for why the unchecked cast fails where it does

## Sources

* Joshua Bloch, Effective Java, 3rd edition, Item 2 ([table of contents](https://www.pearson.de/media/muster/toc/toc_9780134686073.pdf))
* Angelika Langer, [Java Generics FAQ: Type Parameters](http://www.angelikalanger.com/GenericsFAQ/FAQSections/TypeParameters.html), including "How do I decrypt `Enum<E extends Enum<E>>`?"
* [`java.lang.Enum` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Enum.html) and [`BaseStream`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/stream/BaseStream.html)
* [Project Lombok: @SuperBuilder](https://projectlombok.org/features/SuperBuilder)
* [Curiously recurring template pattern](https://en.wikipedia.org/wiki/Curiously_recurring_template_pattern), Wikipedia
