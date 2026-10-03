# 033 · The Type-Safe Heterogeneous Container

> One map, values of many types, not a single cast at the call site. The trick is to stop parameterizing the container and parameterize the key instead.

**Since:** Java 10 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

Every codebase eventually grows a bag of loosely related settings or request attributes:

```java
Map<String, Object> context = new HashMap<>();
context.put("timeout", Duration.ofSeconds(5));
context.put("retries", 3);

int retries = (Integer) context.get("retries");       // a cast at every read
Duration timeout = (Duration) context.get("retries");  // compiles, explodes at runtime
```

A normal generic `Map<K, V>` has one value type for the whole map. Here every entry has its own, so the compiler gives up and you are back to casting `Object`s like it is 2003.

## The trick

Joshua Bloch's answer (Effective Java, 3rd edition, Item 33, and his JavaOne talk of 2006) is to put the type parameter on the **key**. With a `Class<T>` as the key, the method signature ties the key's type to the value's type:

```java
<T> void put(Class<T> type, T instance) { map.put(type, type.cast(instance)); }
<T> T get(Class<T> type)                { return type.cast(map.get(type)); }
```

The map itself is a humble `Map<Class<?>, Object>`, but every way in and out goes through a `Class<T>`, so the relationship "the value stored under `Integer.class` is an `Integer`" is enforced on both sides. `Class.cast` is a *checked* cast, so even raw-type abuse is caught at the door.

Bloch's version allows one value per type. The natural upgrade, used by Netty's `AttributeKey<T>` and the JDK's own `SocketOption<T>`, is a dedicated **typed key** object: many keys can share a type, and keys can have generic types such as `List<String>`.

## Full example

```java run
import java.time.Duration;
import java.util.*;

public class HeterogeneousDemo {

    /** Bloch's Favorites: the key *is* the type, so one entry per type. */
    static final class Favorites {
        private final Map<Class<?>, Object> favorites = new HashMap<>();

        <T> void put(Class<T> type, T instance) {
            favorites.put(Objects.requireNonNull(type), type.cast(instance));   // guards against raw types
        }

        <T> T get(Class<T> type) { return type.cast(favorites.get(type)); }
    }

    /** A typed key. No equals/hashCode on purpose: two keys are equal only if they are the same object. */
    static final class Key<T> {
        private final String name;
        private final T defaultValue;

        private Key(String name, T defaultValue) { this.name = name; this.defaultValue = defaultValue; }

        static <T> Key<T> of(String name, T defaultValue) { return new Key<>(name, defaultValue); }

        @Override public String toString() { return name; }
    }

    /** The container. It never sees a T, only Key<T> and T together. */
    static final class Context {
        private final Map<Key<?>, Object> values = new LinkedHashMap<>();

        <T> Context with(Key<T> key, T value) { values.put(key, value); return this; }

        @SuppressWarnings("unchecked")   // safe: with() is the only way in, and it ties T to Key<T>
        <T> T get(Key<T> key) { return values.containsKey(key) ? (T) values.get(key) : key.defaultValue; }

        @Override public String toString() { return values.toString(); }
    }

    static final Key<Duration> CONNECT_TIMEOUT = Key.of("connectTimeout", Duration.ofSeconds(5));
    static final Key<Duration> READ_TIMEOUT = Key.of("readTimeout", Duration.ofSeconds(30));
    static final Key<List<String>> TAGS = Key.of("tags", List.of());
    static final Key<Integer> RETRIES = Key.of("retries", 3);

    @SuppressWarnings({"rawtypes", "unchecked"})
    public static void main(String[] args) {
        var favorites = new Favorites();
        favorites.put(String.class, "Java");
        favorites.put(Integer.class, 0xcafebabe);
        favorites.put(Class.class, Favorites.class);

        String text = favorites.get(String.class);         // no casts anywhere
        int number = favorites.get(Integer.class);
        Class<?> type = favorites.get(Class.class);
        System.out.printf("%s %x %s%n", text, number, type.getSimpleName());

        try {
            Class raw = Integer.class;                      // raw types can lie to javac...
            favorites.put(raw, "not a number");
        } catch (ClassCastException e) {
            System.out.println("raw put: " + e.getMessage());   // ...but not to Class.cast
        }
        try {
            favorites.put(int.class, 42);                   // int.class is a Class<Integer>, but...
        } catch (ClassCastException e) {
            System.out.println("primitive key: " + e.getMessage());
        }

        var ctx = new Context()
                .with(CONNECT_TIMEOUT, Duration.ofMillis(250))
                .with(TAGS, List.of("eu", "beta"));
        Duration connect = ctx.get(CONNECT_TIMEOUT);       // two keys, same type, separate entries
        Duration read = ctx.get(READ_TIMEOUT);             // falls back to the key's default
        List<String> tags = ctx.get(TAGS);                 // a generic value type, impossible with Class keys
        int retries = ctx.get(RETRIES);
        System.out.println("connect=" + connect + " read=" + read + " tags=" + tags + " retries=" + retries);

        // Identity keys: a second key that happens to share a name is a different key.
        Key<Integer> otherRetries = Key.of("retries", 0);
        ctx.with(otherRetries, 10);
        System.out.println("RETRIES=" + ctx.get(RETRIES) + " otherRetries=" + ctx.get(otherRetries) + " ctx=" + ctx);

        // The price of generic values: a raw key smuggles in a String, and the read fails later.
        Key smuggler = RETRIES;
        ctx.with(smuggler, "three");
        try {
            int broken = ctx.get(RETRIES);
            System.out.println("never printed " + broken);
        } catch (ClassCastException e) {
            System.out.println("raw key: " + e.getClass().getSimpleName() + " at the read, not the write");
        }
    }
}
```

Output:

```text output
Java cafebabe Favorites
raw put: Cannot cast java.lang.String to java.lang.Integer
primitive key: Cannot cast java.lang.Integer to int
connect=PT0.25S read=PT30S tags=[eu, beta] retries=3
RETRIES=3 otherRetries=10 ctx={connectTimeout=PT0.25S, tags=[eu, beta], retries=10}
raw key: ClassCastException at the read, not the write
```

And the thing everybody tries first, a class literal for a generic type, is not even valid syntax:

```java compile-fail
import java.util.*;

public class GenericKey {
    static <T> void put(Class<T> type, T value) {}

    public static void main(String[] args) {
        put(List<String>.class, List.of("a", "b"));
    }
}
```

```text compile-error
GenericKey.java:7: error: <identifier> expected
        put(List<String>.class, List.of("a", "b"));
                         ^
GenericKey.java:7: error: <identifier> expected
        put(List<String>.class, List.of("a", "b"));
                              ^
2 errors
```

## How it works

* **The key carries the type.** `put(Class<T>, T)` and `get(Class<T>)` share one type variable, so javac checks at every call site that the value matches the key. The map's own declared type, `Map<Class<?>, Object>`, is irrelevant because nobody outside can touch it.
* **`Class.cast` is the dynamic twin of a cast.** It throws `ClassCastException` if the object is not an instance, and it is how `get` returns `T` without an unchecked warning. Calling it in `put` too is what catches the raw `Class` attack at the moment of the bad write, the same idea behind `Collections.checkedList`.
* **Primitive class literals are a trap.** `int.class` has type `Class<Integer>`, so `put(int.class, 42)` compiles. But `int.class.isInstance(x)` is false for every object, so `cast` fails, as the output shows.
* **Typed keys trade checking for flexibility.** A `Key<T>` without a `Class<T>` cannot check anything at runtime, so `get` needs an unchecked cast. That cast is safe exactly as long as nobody uses raw types, which the last line of output demonstrates by breaking the rule. If all your value types are reifiable, give `Key<T>` a `Class<T>` field and use `cast` again.
* **Identity equality is a feature.** Because `Key` does not override `equals`, `RETRIES` and `otherRetries` never collide, even with the same name. The printed context holds a single `retries=10` entry, and it belongs to `otherRetries`: `RETRIES` was never set and still answers with its default of 3. Netty goes the other way: `AttributeKey.valueOf(name)` returns the singleton key for a name, and `newInstance(name)` throws if the name is taken. Convenient, but `valueOf` is generic in `T`, so two call sites can ask for `"retries"` as an `AttributeKey<Integer>` and an `AttributeKey<String>` and get the same key. Keep keys as `static final` constants and the question never comes up.

The pattern itself is Java 5 vintage. The example uses `var` and `List.of`, so it compiles from Java 10.

## Gotchas

* **No generic class literals.** As the compile error shows, `List<String>.class` is not an expression at all, and `Class<List<String>> c = List.class` fails with `incompatible types: Class<List> cannot be converted to Class<List<String>>`. Use typed keys, or [super type tokens](032-super-type-tokens.md) when the key must *be* a full generic type.
* **One value per `Class`.** Favorites cannot hold two `Duration`s. As soon as two settings share a type, switch to typed keys.
* **`get` returns `null` for a missing `Class` key.** Unboxing `int number = favorites.get(Integer.class)` would throw `NullPointerException` on an empty container. Typed keys with defaults avoid that.
* **Subtypes are not found.** `put(ArrayList.class, list)` is invisible to `get(List.class)`. If you need "anything assignable to", iterate and check `isAssignableFrom`, and accept the linear scan.

## When to use it (and when not to)

Use it for extensible attribute bags where different modules add their own entries without knowing about each other: request or channel attributes, plugin registries, test fixtures, per-session contexts. The JDK uses the same idea in several places: `AnnotatedElement.getAnnotation(Class<A>)` is a heterogeneous container keyed by annotation type, `Socket.setOption(SocketOption<T>, T)` uses typed keys such as `StandardSocketOptions.SO_KEEPALIVE`, and every `ThreadLocal<T>` is a typed identity key into a per-thread map.

Do not use it as a substitute for a record. If you know all the fields at compile time, `record Settings(Duration connectTimeout, Duration readTimeout, int retries)` is shorter, faster, and the compiler catches missing fields. Heterogeneous containers are for the cases where the set of keys is open.

## Related

* [032 · Super Type Tokens: Capturing Generic Types at Runtime](032-super-type-tokens.md)
* [021 · A Dependency Injection Container in 100 Lines](../03-build-it-yourself/021-di-container.md), a heterogeneous container with constructors attached
* [079 · Scoped Values: ThreadLocal's Better Sibling](../09-concurrency/079-scoped-values.md), typed keys for per-thread context
* [030 · Phantom Types: Let the Compiler Track State](030-phantom-types.md)

## Sources

* Joshua Bloch, Effective Java, 3rd edition, Item 33 ([table of contents](https://www.pearson.de/media/muster/toc/toc_9780134686073.pdf))
* Neal Gafter, [Super Type Tokens](https://gafter.blogspot.com/2006/12/super-type-tokens.html), which quotes the Favorites example from Bloch's 2006 JavaOne talk
* [`Class.cast` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Class.html#cast(java.lang.Object)) and [`SocketOption`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/net/SocketOption.html)
* Netty [`AttributeKey`](https://netty.io/4.1/api/io/netty/util/AttributeKey.html)
