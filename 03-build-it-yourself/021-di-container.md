# 021 · A Dependency Injection Container in 100 Lines

> Spring's core trick fits on one screen: read the constructor, resolve its parameters, repeat. The hard part is the error message when it goes in a circle.

**Since:** Java 16 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

Dependency injection itself is simple: a class receives its collaborators through the constructor instead of creating them. The wiring is what grows:

```java
var config = loadConfig();
var users = new JdbcUserRepository(config);
var mailer = new ConsoleMailer(config);
var signup = new SignupService(users, mailer);
var checkout = new CheckoutService(users, new HttpPaymentGateway(config), new AuditLog());
// ... and 200 more lines that must be kept in dependency order by hand
```

A DI container automates exactly this. Frameworks make it look like magic, with annotations, classpath scanning and proxies. Underneath, the essential algorithm is a recursive function and a bit of reflection. Building it once removes the magic, and it also shows you what Spring, Guice and Dagger give you on top.

## The trick

`get(type)` does four things:

1. **Find the implementation.** A provider function wins, then an explicit `bind(interface, implementation)`, otherwise the type itself (a "just in time" binding for concrete classes, as Guice does).
2. **Pick a constructor.** The one marked `@Inject`, or the only one there is.
3. **Resolve every parameter by calling `get` again.** That recursion *is* the dependency graph walk.
4. **Remember singletons.** Classes annotated `@Singleton` are created once and cached.

Two details turn a toy into something you can reason about. A `LinkedHashSet` of the types currently under construction detects cycles and, because it keeps insertion order, prints the whole chain. And a parameter of type `Supplier<X>` is resolved *lazily*, which is the standard way (JSR-330's `Provider<T>`) to break a cycle on purpose.

## Full example

The container is everything from the two annotations to the end of the `Container` class: 78 lines, blank lines included. The application classes below it know nothing about the container.

```java run
import java.lang.annotation.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.function.*;
import java.util.stream.*;

public class DiDemo {

    @Retention(RetentionPolicy.RUNTIME) @Target(ElementType.CONSTRUCTOR) @interface Inject {}
    @Retention(RetentionPolicy.RUNTIME) @Target(ElementType.TYPE) @interface Singleton {}

    static final class ResolutionException extends RuntimeException {
        ResolutionException(String message) { super(message); }
    }

    static final class Container {
        private final Map<Class<?>, Class<?>> implementations = new HashMap<>();
        private final Map<Class<?>, Function<Container, ?>> providers = new HashMap<>();
        private final Map<Class<?>, Object> singletons = new HashMap<>();
        private final LinkedHashSet<Class<?>> underConstruction = new LinkedHashSet<>();

        <T> Container bind(Class<T> type, Class<? extends T> implementation) {
            implementations.put(type, implementation);
            return this;
        }

        <T> Container provide(Class<T> type, Function<Container, ? extends T> provider) {
            providers.put(type, provider);
            return this;
        }

        synchronized <T> T get(Class<T> type) {
            if (providers.containsKey(type)) return type.cast(providers.get(type).apply(this));
            Class<?> impl = implementations.getOrDefault(type, type);
            Object cached = singletons.get(impl);
            if (cached != null) return type.cast(cached);
            if (impl.isInterface() || Modifier.isAbstract(impl.getModifiers())) {
                throw new ResolutionException("No binding for " + impl.getSimpleName() + " (" + path(impl) + ")");
            }
            if (!underConstruction.add(impl)) {
                throw new ResolutionException("Dependency cycle: " + path(impl));
            }
            try {
                Object instance = construct(impl);
                if (impl.isAnnotationPresent(Singleton.class)) singletons.put(impl, instance);
                return type.cast(instance);
            } finally {
                underConstruction.remove(impl);
            }
        }

        private Object construct(Class<?> impl) {
            Constructor<?> constructor = pickConstructor(impl);
            Object[] args = Arrays.stream(constructor.getGenericParameterTypes()).map(this::resolve).toArray();
            try {
                return constructor.newInstance(args);
            } catch (InvocationTargetException e) {
                throw new ResolutionException("Constructor of " + impl.getSimpleName() + " failed: " + e.getCause());
            } catch (ReflectiveOperationException e) {
                throw new ResolutionException("Cannot instantiate " + impl.getSimpleName() + ": " + e);
            }
        }

        // Supplier<X> is resolved lazily: the way to break a cycle on purpose.
        private Object resolve(Type type) {
            if (type instanceof Class<?> c) return get(c);
            if (type instanceof ParameterizedType p && p.getRawType() == Supplier.class
                    && p.getActualTypeArguments()[0] instanceof Class<?> target) {
                return (Supplier<?>) () -> get(target);
            }
            throw new ResolutionException("Cannot inject " + type.getTypeName() + " (" + path(null) + ")");
        }

        private static Constructor<?> pickConstructor(Class<?> impl) {
            Constructor<?>[] all = impl.getDeclaredConstructors();
            List<Constructor<?>> marked = Arrays.stream(all).filter(c -> c.isAnnotationPresent(Inject.class)).toList();
            if (marked.size() == 1) return marked.get(0);
            if (marked.isEmpty() && all.length == 1) return all[0];
            throw new ResolutionException(impl.getSimpleName() + " needs one constructor, or exactly one @Inject");
        }

        private String path(Class<?> last) {
            return Stream.concat(underConstruction.stream(), Stream.ofNullable(last))
                    .map(Class::getSimpleName).collect(Collectors.joining(" -> "));
        }
    }

    // ---------- The application: plain records and classes ----------

    record Config(String databaseUrl, String sender) {}

    interface UserRepository { void save(String email); }
    interface Mailer { void send(String to, String text); }

    @Singleton
    record JdbcUserRepository(Config config) implements UserRepository {
        JdbcUserRepository { System.out.println("  new JdbcUserRepository"); }
        public void save(String email) { System.out.println("  INSERT " + email + " INTO " + config.databaseUrl()); }
    }

    static final class ConsoleMailer implements Mailer {
        private final String sender;
        ConsoleMailer() { this.sender = "test@localhost"; }   // for unit tests
        @Inject ConsoleMailer(Config config) {
            this.sender = config.sender();
            System.out.println("  new ConsoleMailer");
        }
        public void send(String to, String text) { System.out.println("  MAIL " + sender + " -> " + to + ": " + text); }
    }

    record SignupService(UserRepository users, Mailer mailer) {
        SignupService { System.out.println("  new SignupService"); }
        void signUp(String email) {
            users.save(email);
            mailer.send(email, "Welcome aboard!");
        }
    }

    // A cycle, a missing binding, and a cycle broken on purpose.
    record OrderService(PaymentService payments) {}
    record PaymentService(NotificationService notifications) {}
    record NotificationService(OrderService orders) {}
    interface PaymentGateway {}
    record CheckoutService(UserRepository users, PaymentGateway gateway) {}

    @Singleton record Chicken(Supplier<Egg> eggs) { Egg layEgg() { return eggs.get(); } }
    record Egg(Chicken mother) {}

    public static void main(String[] args) {
        var container = new Container()
                .provide(Config.class, c -> new Config("users.db", "hello@example.org"))
                .bind(UserRepository.class, JdbcUserRepository.class)
                .bind(Mailer.class, ConsoleMailer.class);

        System.out.println("first get(SignupService):");
        SignupService first = container.get(SignupService.class);
        first.signUp("ada@example.org");

        System.out.println("second get(SignupService):");
        SignupService second = container.get(SignupService.class);
        System.out.println("same repository (singleton)? " + (first.users() == second.users()));
        System.out.println("same mailer (prototype)?     " + (first.mailer() == second.mailer()));

        System.out.println("errors carry the whole path:");
        for (Class<?> type : List.of(OrderService.class, CheckoutService.class)) {
            try {
                container.get(type);
            } catch (ResolutionException e) {
                System.out.println("  " + e.getMessage());
            }
        }

        System.out.println("a Supplier breaks the cycle on purpose:");
        Chicken chicken = container.get(Chicken.class);
        Egg egg = chicken.layEgg();
        System.out.println("  egg.mother() == chicken? " + (egg.mother() == chicken));

        // Why the singleton cache does not use computeIfAbsent: resolution recurses into the same map.
        var cache = new HashMap<Class<?>, Object>();
        try {
            cache.computeIfAbsent(SignupService.class, k -> cache.computeIfAbsent(Mailer.class, j -> "mailer"));
        } catch (ConcurrentModificationException e) {
            System.out.println("recursive computeIfAbsent: " + e.getClass().getSimpleName());
        }
    }
}
```

Output:

```text output
first get(SignupService):
  new JdbcUserRepository
  new ConsoleMailer
  new SignupService
  INSERT ada@example.org INTO users.db
  MAIL hello@example.org -> ada@example.org: Welcome aboard!
second get(SignupService):
  new ConsoleMailer
  new SignupService
same repository (singleton)? true
same mailer (prototype)?     false
errors carry the whole path:
  Dependency cycle: OrderService -> PaymentService -> NotificationService -> OrderService
  No binding for PaymentGateway (CheckoutService -> PaymentGateway)
a Supplier breaks the cycle on purpose:
  egg.mother() == chicken? true
recursive computeIfAbsent: ConcurrentModificationException
```

## How it works

* **Recursion does the topological sort.** Nobody computes a dependency order. `get(SignupService)` needs a `UserRepository`, which needs a `Config`, which a provider returns. The constructor calls in the output appear deepest first, which is exactly the order you would have written by hand.
* **Scopes are one map.** A `@Singleton` class lands in `singletons` after its first construction; everything else is created fresh per request. The output shows the repository built once and the mailer built twice.
* **Cycle detection is set membership.** `underConstruction.add(impl)` returns `false` if the type is already being built further up the stack. Because the set is a `LinkedHashSet`, the error message can print the chain in order, which is the difference between a five second fix and a lost afternoon.
* **`getGenericParameterTypes()` keeps the type argument.** A plain `getParameterTypes()` would only say `Supplier`. The generic variant returns `Supplier<Egg>` as a `ParameterizedType`, so the container knows what to supply later. Erasure removes type arguments from *values*, not from declarations.
* **The lazy `Supplier` breaks the cycle.** `Chicken` gets a supplier instead of an `Egg`. By the time it lays one, the chicken is finished and cached as a singleton, so the egg's mother is that very chicken.
* **`@Inject` is optional.** `ConsoleMailer` has a no-argument constructor for tests and an `@Inject` constructor for the container. With a single constructor, as in all the records, no annotation is needed. The annotation needs `@Retention(RUNTIME)`; with the default retention, `isAnnotationPresent` silently returns `false`.

## Gotchas

* **No `computeIfAbsent` for recursive caches.** The tempting one-liner `singletons.computeIfAbsent(impl, this::construct)` modifies the map from inside its own mapping function. Since Java 9, `HashMap` detects that and throws, as the last output line shows. `ConcurrentHashMap` forbids it as well: depending on how the keys hash, it happens to work, throws `IllegalStateException: Recursive update`, or deadlocks two threads that recurse in opposite orders.
* **Inner classes break constructor injection.** A non-static inner class has a hidden first constructor parameter (the enclosing instance). Records, enums and interfaces nested in a class are implicitly static; ordinary nested classes need the `static` keyword.
* **Types only, no names.** Two `String` parameters are indistinguishable. Real containers add qualifiers (`@Named("smtpHost")`); parameter names are only available when compiling with `-parameters`.
* **Errors happen at runtime, on first use.** A missing binding in a rarely used service explodes in production at 3 a.m. Spring and Guice mitigate this by building eagerly at startup; Dagger moves it to compile time.
* **The global lock is crude.** `synchronized get` makes the toy thread-safe and also serializes every lookup.

## When to use it (and when not to)

Build it to understand containers, then do not ship it. The honest landscape:

| | How it wires | Errors show up | What you get on top |
|---|---|---|---|
| **This toy** | reflection, at runtime | on first `get` | nothing |
| **Guice** | reflection, at runtime, modules in plain Java | at injector creation | scopes, qualifiers, provider methods, AOP, path-style error messages like the ones above |
| **Spring** | reflection and classpath scanning, at startup | at context startup | lifecycle callbacks, proxies for transactions and scopes, configuration, a huge ecosystem |
| **Dagger** | an annotation processor writes plain Java factories | at compile time | no reflection, fast startup, works with code shrinkers |

The toy leaves out qualifiers, scopes other than singleton, field and method injection, generic bindings (`List<Plugin>`), lifecycle and shutdown hooks, proxies, and any useful thread safety. For a small application, the best container is often none: write the wiring by hand in `main` ("pure DI"). It is boring, it is checked by the compiler, and a missing dependency is a compile error. Reach for Guice or Spring when the graph is large enough that hand wiring hurts, and for Dagger when startup time or reflection is a problem.

## Related

* [006 · The Reader Monad: Dependency Injection with Plain Functions](../01-functional/006-reader-monad.md), DI with no container at all
* [085 · Dynamic Proxies: Implementing Interfaces at Runtime](../10-jvm-performance/085-dynamic-proxies.md), the other half of what Spring does at runtime
* [032 · Super Type Tokens: Capturing Generic Types at Runtime](../04-generics/032-super-type-tokens.md), how containers bind `List<Plugin>` despite erasure
* [020 · A Type-Safe Event Bus in 50 Lines](020-event-bus.md)

## Sources

* Martin Fowler, [Inversion of Control Containers and the Dependency Injection pattern](https://martinfowler.com/articles/injection.html) (2004)
* [Guice: Motivation](https://github.com/google/guice/wiki/Motivation), which walks from hand wiring to a container
* [Dagger](https://dagger.dev/dev-guide/), compile-time dependency injection
* [Jakarta Dependency Injection](https://jakarta.ee/specifications/dependency-injection/), the standard `@Inject`, `@Singleton` and `Provider<T>` (formerly JSR-330)
* [`Constructor.getGenericParameterTypes` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/reflect/Constructor.html#getGenericParameterTypes())
