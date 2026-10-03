# 087 · Property Names from Method References with SerializedLambda

> `Person::getCity` knows it means "city". Ask it nicely (through a private method javac generated for serialization) and it will tell you, which gives you query builders that survive a rename refactoring.

**Since:** Java 16 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

Query builders, validators, sort specifications and change trackers all need property names, and the usual way to supply them is a string:

```java
query.eq("city", "London").gt("birthYear", 1980);
```

Rename `city` to `town` in your IDE and every string silently stays behind. The bug arrives at runtime, as a SQL error in the best case and as a filter that matches nothing in the worst. What you want is to write `Person::getCity` and get `"city"` back. But a method reference compiles to an opaque lambda object, and `Function` has no `getName()`.

## The trick

Make the functional interface **serializable**:

```java
interface Property<T, R> extends Function<T, R>, Serializable {}
```

To serialize a lambda, the runtime has to remember what it points at. So for every serializable lambda the generated class gets a private `writeReplace()` method that returns a `java.lang.invoke.SerializedLambda`, a plain object describing the lambda: the implementing class, the implementing method's name and signature, the captured arguments. Call `writeReplace` reflectively and read `getImplMethodName()`:

```java
Method writeReplace = ref.getClass().getDeclaredMethod("writeReplace");
writeReplace.setAccessible(true);
String method = ((SerializedLambda) writeReplace.invoke(ref)).getImplMethodName();   // "getCity"
```

Strip `get` or `is`, lower-case the first letter, and `Person::getCity` becomes `"city"`. MyBatis-Plus builds its `LambdaQueryWrapper` on exactly this trick.

## Full example

```java run
import java.io.Serializable;
import java.lang.invoke.MethodHandleInfo;
import java.lang.invoke.SerializedLambda;
import java.lang.reflect.Method;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;

public class PropertyNames {

    /** Serializable on purpose: that makes javac keep a description of the method reference. */
    @FunctionalInterface
    interface Property<T, R> extends Function<T, R>, Serializable {}

    static final class Person {
        private final String name;
        private final int birthYear;
        private final String city;
        private final boolean active;

        Person(String name, int birthYear, String city, boolean active) {
            this.name = name; this.birthYear = birthYear; this.city = city; this.active = active;
        }
        public String getName() { return name; }
        public int getBirthYear() { return birthYear; }
        public String getCity() { return city; }
        public boolean isActive() { return active; }
    }

    record Planet(String name, int moons) {}

    static final Map<Class<?>, String> CACHE = new ConcurrentHashMap<>();
    static final AtomicInteger EXTRACTIONS = new AtomicInteger();

    static SerializedLambda serialized(Serializable lambda) {
        try {
            // javac makes every serializable lambda class carry a private writeReplace().
            Method writeReplace = lambda.getClass().getDeclaredMethod("writeReplace");
            writeReplace.setAccessible(true);
            return (SerializedLambda) writeReplace.invoke(lambda);
        } catch (ReflectiveOperationException e) {
            throw new IllegalArgumentException("not a serializable lambda: " + lambda, e);
        }
    }

    static String stripPrefix(String method, String prefix) {
        boolean bean = method.startsWith(prefix) && method.length() > prefix.length()
                && Character.isUpperCase(method.charAt(prefix.length()));
        return bean ? method.substring(prefix.length()) : null;
    }

    static <T> String propertyName(Property<T, ?> ref) {
        // Each method reference expression gets its own lambda class, so the class is a fine cache key.
        return CACHE.computeIfAbsent(ref.getClass(), c -> {
            EXTRACTIONS.incrementAndGet();
            String method = serialized(ref).getImplMethodName();
            if (method.startsWith("lambda$")) {
                throw new IllegalArgumentException("not a method reference: " + method);
            }
            String bare = Objects.requireNonNullElse(stripPrefix(method, "get"),
                    Objects.requireNonNullElse(stripPrefix(method, "is"), method));   // records: no prefix
            return Character.toLowerCase(bare.charAt(0)) + bare.substring(1);
        });
    }

    static <T> String column(Property<T, ?> ref) {
        return propertyName(ref).replaceAll("([a-z])([A-Z])", "$1_$2").toLowerCase();
    }

    /** A tiny typesafe query builder in the style of MyBatis-Plus's LambdaQueryWrapper. */
    static final class Query<T> {
        private final String table;
        private final List<String> conditions = new ArrayList<>();
        private final List<Object> params = new ArrayList<>();

        Query(String table) { this.table = table; }

        Query<T> eq(Property<T, ?> property, Object value) { return condition(property, "=", value); }
        Query<T> gt(Property<T, ?> property, Object value) { return condition(property, ">", value); }

        private Query<T> condition(Property<T, ?> property, String op, Object value) {
            conditions.add(column(property) + " " + op + " ?");
            params.add(value);
            return this;
        }

        String sql() { return "SELECT * FROM " + table + " WHERE " + String.join(" AND ", conditions); }
        List<Object> params() { return params; }
    }

    public static void main(String[] args) {
        System.out.println(propertyName(Person::getName) + ", " + propertyName(Person::getBirthYear)
                + ", " + propertyName(Person::isActive) + ", " + propertyName(Planet::moons));

        SerializedLambda info = serialized((Property<Person, String>) Person::getCity);
        System.out.println("impl class:  " + info.getImplClass());
        System.out.println("impl method: " + info.getImplMethodName());
        System.out.println("impl kind:   " + MethodHandleInfo.referenceKindToString(info.getImplMethodKind()));

        var query = new Query<Person>("person")
                .eq(Person::getCity, "London")
                .gt(Person::getBirthYear, 1980)
                .eq(Person::isActive, true);
        System.out.println(query.sql());
        System.out.println("params: " + query.params());

        // The cache: the same method reference expression always has the same class.
        EXTRACTIONS.set(0);
        CACHE.clear();
        for (int i = 0; i < 1_000; i++) propertyName(Planet::name);
        System.out.println("1000 lookups, " + EXTRACTIONS.get() + " reflective extraction(s)");

        // Limits: a lambda has no useful name, and a plain Function has no writeReplace at all.
        try {
            propertyName((Person p) -> p.getName());
        } catch (IllegalArgumentException e) {
            System.out.println(e.getMessage());
        }
        Function<Person, String> plain = Person::getName;
        boolean hasWriteReplace = Arrays.stream(plain.getClass().getDeclaredMethods())
                .anyMatch(m -> m.getName().equals("writeReplace"));
        System.out.println("plain Function has writeReplace? " + hasWriteReplace);
    }
}
```

Output:

```text output
name, birthYear, active, moons
impl class:  PropertyNames$Person
impl method: getCity
impl kind:   invokeVirtual
SELECT * FROM person WHERE city = ? AND birth_year > ? AND active = ?
params: [London, 1980, true]
1000 lookups, 1 reflective extraction(s)
not a method reference: lambda$main$30574422$1
plain Function has writeReplace? false
```

## How it works

* **Serializable lambdas carry their recipe.** When the target type of a lambda or method reference is serializable, javac bootstraps it with `LambdaMetafactory.altMetafactory` and the `FLAG_SERIALIZABLE` flag. The generated class then gets a `writeReplace()` that returns a `SerializedLambda`, and the capturing class gets a `$deserializeLambda$` method to rebuild it on the other side. We never serialize anything. We only borrow the description.
* **`getImplMethodName()` is the whole trick.** For `Person::getCity` it is `getCity`, the method the lambda calls. `getImplClass()` is the class that declares it, in JVM internal form (`PropertyNames$Person`), and the implementation kind is `invokeVirtual`. Record accessors have no `get` prefix, so `Planet::moons` comes out as `moons` directly. The prefix check also requires an upper-case letter afterwards, so a property called `issue` does not turn into `sue`.
* **The query builder** is now a few string operations: property name, then camelCase to snake_case for the column. `Person::getBirthYear` becomes `birth_year`, and if someone renames `getCity`, the IDE renames the method reference with it.
* **Caching by class.** Every method reference *expression* in the source gets its own `invokedynamic` call site and its own lambda class, and evaluating it again yields an instance of that same class. So a class-keyed cache does the reflective work once per call site: a thousand lookups, one extraction.
* **Lambdas are not method references.** `(Person p) -> p.getName()` compiles to a synthetic method in `PropertyNames`, so the "implementation method" is that synthetic method. Its name, `lambda$main$30574422$1` in the output, is a javac detail (for serializable lambdas javac mixes a hash into the name to make it less sensitive to unrelated edits). Either way it is not a property, and the code rejects it.
* **No `Serializable`, no `writeReplace`.** A plain `Function` from the same method reference has no such method. Requiring `Property` in your API signatures turns that runtime failure into a compile-time one.

`SerializedLambda` exists since Java 8, so the trick works there too. This example uses a record, hence Java 16.

## Gotchas

* **It leans on an implementation detail.** The `SerializedLambda` Javadoc says that a `writeReplace` returning `SerializedLambda` is *one means* for compilers to make lambdas serializable, not a guarantee. javac and the JDK have done it this way since Java 8, and other JVM languages may not. A route that avoids `setAccessible` is to write the lambda to an `ObjectOutputStream` subclass (over `OutputStream.nullOutputStream()`) that calls `enableReplaceObject(true)` and grabs the `SerializedLambda` in `replaceObject`. It is slower, and it relies on the same mechanism.
* **Modules.** `setAccessible` works here because the lambda class lives in the same (unnamed) module as the caller. A library in a named module reading lambdas from *your* named module needs your package to be `opens` to it.
* **Method references only, and only simple ones.** `Person::getAddress` works. A path like `p -> p.getAddress().getCity()` does not, because it is a lambda. Libraries that support nested paths either chain references or fall back to proxies that record calls.
* **Serializable lambdas are a (small) attack surface.** Each one adds a `$deserializeLambda$` entry point to the capturing class. Never deserialize untrusted data, lambdas or not.
* **Cache, and cache carefully.** Calling `writeReplace` on every query is wasteful. A static `Map<Class<?>, String>` is fine in a normal application, but in a container that reloads class loaders it pins every lambda class (and its loader) forever. Use weak keys there, or a `ClassValue` around the reflective `writeReplace` lookup.

## When to use it (and when not to)

Use it in libraries and internal frameworks where string property names are a real source of bugs: query builders, criteria APIs, sort parameters, audit diffs, validation messages (see [011](../02-patterns/011-notification-validator.md)). The implementation is twenty lines and the payoff is refactoring safety across a whole codebase. Many teams run MyBatis-Plus in production on exactly this mechanism.

Do not use it if you control code generation. An annotation processor or JPA's static metamodel (`Person_.city`) gives you the same safety with no reflection at all. And do not use it for anything that must keep working on every JVM language and every future javac.

## Related

* [011 · Notification Pattern Validator](../02-patterns/011-notification-validator.md), whose `rule("email", SignUp::email, ...)` could derive `"email"` with this trick
* [086 · MethodHandles and LambdaMetafactory: Reflection at Full Speed](086-methodhandles-lambdametafactory.md), the factory that builds these lambda classes
* [085 · Dynamic Proxies: Implementing Interfaces at Runtime](085-dynamic-proxies.md), the other way frameworks turn method calls into queries
* [032 · Super Type Tokens: Capturing Generic Types at Runtime](../04-generics/032-super-type-tokens.md), another way to recover at runtime what the source code already said

## Sources

* [`java.lang.invoke.SerializedLambda` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/SerializedLambda.html)
* [`LambdaMetafactory.altMetafactory` and `FLAG_SERIALIZABLE` (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/invoke/LambdaMetafactory.html)
* [MyBatis-Plus: Conditional Constructor](https://baomidou.com/en/guides/wrapper/), the `LambdaQueryWrapper` this example imitates
* [JLS §15.27.4: Run-Time Evaluation of Lambda Expressions](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.27.4)
