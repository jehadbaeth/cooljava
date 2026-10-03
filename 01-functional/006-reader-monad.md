# 006 · The Reader Monad: Dependency Injection with Plain Functions

> "Inversion of control is really just a pretentious way of saying 'Taking an argument.'" (Rúnar Bjarnason). The Reader monad takes that literally, then delays the argument until the very last moment.

**Since:** Java 16 · **Category:** [Functional Programming](../README.md#functional-programming) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

A small service needs a user repository, a clock, a mailer and some configuration. In a world of static functions you end up threading all of them through every call, including through functions that do not use them but call something that does:

```java
static String welcomeText(Config config, UserRepository users, Clock clock, int userId) { ... }
static String sendWelcome(Config config, UserRepository users, Clock clock, Mailer mailer, int userId) {
    String text = welcomeText(config, users, clock, userId);   // forwarding, forwarding, forwarding
    ...
}
```

Object oriented Java solves this with constructor injection: put the dependencies in fields once, and every method can reach them. Functional programmers solve it differently: do not take the dependencies now, *return a function that will take them later*.

## The trick

A **Reader** is a computation that needs an environment `E` to produce an `A`. It is nothing more than a `Function<E, A>` wearing a record:

```java
record Reader<E, A>(Function<E, A> run) {
    <B> Reader<E, B> flatMap(Function<? super A, Reader<E, B>> f) {
        return new Reader<>(env -> f.apply(run.apply(env)).run().apply(env));
    }
}
```

Look at what `flatMap` does with `env`: it hands the *same* environment to the first step and to whatever step comes next. That is the whole trick. You compose services as if no environment existed, and the composed result is still a single `Reader` that asks for it once. Plus three helpers:

* `ask()` returns the environment itself, `asks(f)` returns a piece of it (`asks(Env::clock)`).
* `local(change)` runs a sub computation against a modified environment, which is how you override one dependency for one part of the program.
* `run.apply(env)` is the composition root. It happens once, at the edge, and that is where you decide between production and test wiring.

## Full example

```java run
import java.time.*;
import java.util.*;
import java.util.function.*;

public class ReaderDemo {

    // A Reader<E, A> is a computation that needs an E to produce an A. It is just a function.
    record Reader<E, A>(Function<E, A> run) {
        static <E, A> Reader<E, A> pure(A value) { return new Reader<>(env -> value); }
        static <E> Reader<E, E> ask() { return new Reader<>(env -> env); }
        static <E, A> Reader<E, A> asks(Function<E, A> f) { return new Reader<>(f); }

        <B> Reader<E, B> map(Function<? super A, ? extends B> f) {
            return new Reader<>(env -> f.apply(run.apply(env)));
        }

        // The same env goes to both steps. That is the entire trick.
        <B> Reader<E, B> flatMap(Function<? super A, Reader<E, B>> f) {
            return new Reader<>(env -> f.apply(run.apply(env)).run().apply(env));
        }

        // Run this part of the program against a modified environment.
        Reader<E, A> local(UnaryOperator<E> change) {
            return new Reader<>(env -> run.apply(change.apply(env)));
        }
    }

    record User(int id, String name, String email) {}
    interface UserRepository { Optional<User> find(int id); }
    interface Mailer { void send(String to, String body); }
    record Config(String product, String support, ZoneId zone) {}

    // Everything the services might need, in one value.
    record Env(Config config, UserRepository users, Clock clock, Mailer mailer) {
        Env withConfig(Config newConfig) { return new Env(newConfig, users, clock, mailer); }
    }

    // Services are static functions that say "give me an Env and I will give you a result".
    static Reader<Env, String> salutation() {
        return Reader.asks(env -> {
            int hour = LocalTime.now(env.clock().withZone(env.config().zone())).getHour();
            return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
        });
    }

    static Reader<Env, String> displayName(int userId) {
        return Reader.asks(env -> env.users().find(userId).map(User::name).orElse("stranger"));
    }

    // Composes two services. No Env parameter anywhere, and none to forward.
    static Reader<Env, String> welcomeText(int userId) {
        return salutation().flatMap(hello ->
               displayName(userId).flatMap(name ->
               Reader.asks(env -> "%s, %s! Welcome to %s. Questions? %s"
                       .formatted(hello, name, env.config().product(), env.config().support()))));
    }

    static Reader<Env, String> sendWelcome(int userId) {
        return welcomeText(userId).flatMap(text -> Reader.asks(env -> env.users().find(userId)
                .map(user -> {
                    env.mailer().send(user.email(), text);
                    return "sent to " + user.email();
                })
                .orElse("no user " + userId)));
    }

    public static void main(String[] args) {
        Reader<Env, String> program = sendWelcome(1);   // a description; nothing has run yet

        // Two wirings of the same program. Both are in-memory so the output is deterministic.
        List<String> testOutbox = new ArrayList<>();
        Env test = new Env(
                new Config("Acme (test)", "qa@example.test", ZoneOffset.UTC),
                id -> id == 1 ? Optional.of(new User(1, "Tess", "tess@example.test")) : Optional.empty(),
                Clock.fixed(Instant.parse("2026-10-03T08:00:00Z"), ZoneOffset.UTC),
                (to, body) -> testOutbox.add(to + " <- " + body));

        List<String> prodOutbox = new ArrayList<>();
        Map<Integer, User> prodUsers = Map.of(1, new User(1, "Ada", "ada@acme.example"));
        Env prod = new Env(
                new Config("Acme", "support@acme.example", ZoneId.of("Asia/Tokyo")),
                id -> Optional.ofNullable(prodUsers.get(id)),
                Clock.fixed(Instant.parse("2026-10-03T08:00:00Z"), ZoneOffset.UTC),
                (to, body) -> prodOutbox.add(to + " <- " + body));

        System.out.println("test: " + program.run().apply(test));
        System.out.println("prod: " + program.run().apply(prod));
        System.out.println("prod: " + sendWelcome(2).run().apply(prod));
        testOutbox.forEach(mail -> System.out.println("  test outbox  " + mail));
        prodOutbox.forEach(mail -> System.out.println("  prod outbox  " + mail));

        // local: override one dependency for one sub computation, leave the rest alone.
        Reader<Env, String> beta = welcomeText(1)
                .local(env -> env.withConfig(new Config("Acme Beta", "beta@acme.example", env.config().zone())));
        System.out.println("beta: " + beta.run().apply(prod));

        // ask and map: a Reader is a function, and map is andThen.
        Reader<Env, String> product = Reader.<Env>ask().map(env -> env.config().product());
        Function<Env, String> plain = product.run();
        System.out.println("products: " + plain.apply(test) + " and " + plain.apply(prod));
    }
}
```

Output:

```text output
test: sent to tess@example.test
prod: sent to ada@acme.example
prod: no user 2
  test outbox  tess@example.test <- Good morning, Tess! Welcome to Acme (test). Questions? qa@example.test
  prod outbox  ada@acme.example <- Good afternoon, Ada! Welcome to Acme. Questions? support@acme.example
beta: Good afternoon, Ada! Welcome to Acme Beta. Questions? beta@acme.example
products: Acme (test) and Acme
```

## How it works

* **`sendWelcome(1)` runs nothing.** It builds a `Reader`, a function waiting for an `Env`. The program only executes when `run().apply(env)` is called, and you can call it as often as you like with different environments. Same code, test wiring and prod wiring, two different results.
* **The clock is a dependency like any other.** Both environments share the same fixed instant (08:00 UTC). In test the zone is UTC, so it is morning. In prod the zone is Tokyo, where it is 17:00, so the same `salutation()` says good afternoon. No mocking framework involved: `Clock.fixed` is the fake.
* **`flatMap` passes the env along**, so `welcomeText` composes `salutation` and `displayName` without ever mentioning `Env` as a parameter. Compare the forwarding chain in [The problem](#the-problem).
* **`local` scopes an override.** The beta greeting runs against prod (Tokyo time, Ada) with a different `Config`, and only for that sub computation. It is the functional relative of rebinding a [ScopedValue](../09-concurrency/079-scoped-values.md), except the override is visible in the code instead of in the call stack.
* **`ask` and `map`.** `ask()` is the identity function on the environment, and `map` is `Function.andThen`. Unwrap the record with `run()` and you have an ordinary `Function<Env, String>`, ready for any API that takes one.

### Compared with constructor injection

The object oriented version of the same service is this:

```java
final class WelcomeService {
    private final Config config; private final UserRepository users; private final Clock clock; private final Mailer mailer;
    WelcomeService(Config config, UserRepository users, Clock clock, Mailer mailer) { ... }
    String sendWelcome(int userId) { ... }   // reads the fields
}
```

Both answer the same question, "where do dependencies come from?", at different times. Constructor injection binds them when the object is *built*; Reader binds them when the computation is *run*. Constructor injection reads naturally to every Java developer, works with every framework, and stack traces stay readable. Reader gives you dependencies that are visible in the return type, programs that are values you can store and run against several environments, and `local` overrides for free.

## Gotchas

* **One big `Env`.** Every service sees every dependency, which is a service locator in a nicer coat. In Haskell you would constrain the environment per function; in Java the practical answer is small interfaces (`HasClock`, `HasUsers`) that `Env` implements, and services typed against only what they need.
* **The staircase.** Three composed services already need three nested lambdas, and Java has no do-notation to flatten them.
* **Side effects run at `run` time,** not at build time. `sendWelcome` sends mail when the Reader is applied, every time it is applied. Treat a `Reader` that performs effects like a `Runnable`, not like a value you can evaluate twice for free.
* **Stack traces are lambda soup.** A failure deep inside `welcomeText` shows up as a series of `lambda$welcomeText$3` frames, which is less friendly than `WelcomeService.welcomeText`.

## When to use it (and when not to)

In Java, use constructor injection. It is the boring, idiomatic answer, and [021 · A Dependency Injection Container in 100 Lines](../03-build-it-yourself/021-di-container.md) shows how little machinery it really needs. Reader is a party trick here: it is worth knowing because it reveals that dependency injection is "just" passing an argument late, and because the idea shows up in disguise elsewhere (a `Function<Config, Server>` built at startup is a Reader).

Where it genuinely helps: a mostly static, functional code base (a rules engine, a pricing calculator) where you want to run the same composed logic against several configurations, for example a what if simulation that evaluates one pricing program against ten candidate configs. That is one `Reader`, ten `run` calls.

## Related

* [005 · The State Monad: Pure Functions That Carry State](005-state-monad.md), Reader's sibling that can also *write* the environment
* [008 · Currying, Partial Application and Function Composition](008-currying-composition.md), where "take the dependency first" starts
* [021 · A Dependency Injection Container in 100 Lines](../03-build-it-yourself/021-di-container.md), the object oriented way
* [079 · Scoped Values: ThreadLocal's Better Sibling](../09-concurrency/079-scoped-values.md), dynamically scoped context in the JDK

## Sources

* Rúnar Bjarnason, [Dead-Simple Dependency Injection](https://www.youtube.com/watch?v=ZasXwtTRkio) (Northeast Scala Symposium 2012); the "pretentious way of saying taking an argument" line is quoted in the [Functional Talks summary](http://functionaltalks.org/2013/06/17/runar-oli-bjarnason-dead-simple-dependency-injection/)
* Mark Seemann, [The Reader monad](https://blog.ploeh.dk/2022/11/14/the-reader-monad/) (2022) and [From dependency injection to dependency rejection](https://blog.ploeh.dk/2017/01/27/from-dependency-injection-to-dependency-rejection/) (2017), for a skeptical functional view
* [`Control.Monad.Reader`](https://hackage.haskell.org/package/mtl/docs/Control-Monad-Reader.html), Haskell mtl documentation of `ask`, `asks` and `local`
* [`java.time.Clock` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/time/Clock.html), the JDK's own injectable dependency
