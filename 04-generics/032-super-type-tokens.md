# 032 · Super Type Tokens: Capturing Generic Types at Runtime

> Erasure deletes `<String>` from every object you create, but not from the classes you declare. Declare a tiny anonymous class and `List<String>` survives until runtime.

**Since:** Java 21 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Advanced · **Verdict:** ✅ Production

## The problem

`Class<T>` objects make great type-safe keys (see [033](033-heterogeneous-container.md)), until the type you need is generic. There is no `List<String>.class`, and `List.class` cannot tell a list of names from a list of ids. A JSON library that should decode `[1, 2, 3]` into a `List<Integer>`, or a dependency injection container asked for a `Repository<User>`, needs the *full* type at runtime, and a plain `Class` has already forgotten it.

## The trick

Neal Gafter, who made `java.lang.Class` generic in JDK 5, noticed in 2006 that one place keeps generic types around: a class's declaration of its superclass. So make the token an abstract class and force callers to subclass it:

```java
abstract class TypeRef<T> {
    final Type type;
    protected TypeRef() {
        var superclass = (ParameterizedType) getClass().getGenericSuperclass();
        type = superclass.getActualTypeArguments()[0];
    }
}

TypeRef<List<String>> names = new TypeRef<List<String>>() {};   // note the {}
```

The `{}` creates an anonymous subclass whose declared superclass is literally `TypeRef<List<String>>`. That fact is written into the class file and `getGenericSuperclass()` reads it back. Forget the braces and javac stops you, which is the reason `TypeRef` is abstract:

```java compile-fail
import java.util.*;

public class NoBraces {
    abstract static class TypeRef<T> {}

    public static void main(String[] args) {
        TypeRef<List<String>> names = new TypeRef<List<String>>();
    }
}
```

```text compile-error
NoBraces.java:7: error: TypeRef is abstract; cannot be instantiated
        TypeRef<List<String>> names = new TypeRef<List<String>>();
                                      ^
1 error
```

 Gafter named it the **super type token**. Joshua Bloch called it "Gafter's Gadget", and Bob Lee built Guice's `TypeLiteral` on it. Today you meet it as Jackson's `TypeReference`, Gson's `TypeToken` and Spring's `ParameterizedTypeReference`.

## Full example

A registry keyed by full generic types, plus the limits Gafter himself pointed out a few months later:

```java run
import java.lang.reflect.*;
import java.util.*;

public class SuperTypeTokenDemo {

    /** Subclass me anonymously and my type argument survives erasure. */
    abstract static class TypeRef<T> {
        final Type type;

        protected TypeRef() {
            if (!(getClass().getGenericSuperclass() instanceof ParameterizedType superclass)) {
                throw new IllegalStateException("TypeRef created without a type argument");
            }
            type = superclass.getActualTypeArguments()[0];
        }

        /** The erased part, the only part the JVM can check: List for List<String>. */
        Class<?> rawType() {
            return switch (type) {
                case Class<?> c -> c;
                case ParameterizedType p -> (Class<?>) p.getRawType();
                default -> Object.class;
            };
        }

        @Override public boolean equals(Object o) { return o instanceof TypeRef<?> other && type.equals(other.type); }
        @Override public int hashCode() { return type.hashCode(); }
        @Override public String toString() { return type.getTypeName(); }
    }

    /** A heterogeneous map whose keys are full generic types. */
    static final class TypedRegistry {
        private final Map<TypeRef<?>, Object> values = new LinkedHashMap<>();
        private final boolean strict;

        TypedRegistry(boolean strict) { this.strict = strict; }

        <T> void put(TypeRef<T> key, T value) {
            check(key);
            values.put(key, key.rawType().cast(value));   // checks List, cannot check <String>
        }

        @SuppressWarnings("unchecked")
        <T> T get(TypeRef<T> key) {
            check(key);
            return (T) values.get(key);   // trusts that put() saw the same full type
        }

        private void check(TypeRef<?> key) {
            if (strict && mentionsTypeVariable(key.type)) {
                throw new IllegalArgumentException(key + " mentions a type variable");
            }
        }

        static boolean mentionsTypeVariable(Type t) {
            return switch (t) {
                case TypeVariable<?> v -> true;
                case ParameterizedType p -> Arrays.stream(p.getActualTypeArguments())
                        .anyMatch(TypedRegistry::mentionsTypeVariable);
                case GenericArrayType a -> mentionsTypeVariable(a.getGenericComponentType());
                case WildcardType w -> Arrays.stream(w.getUpperBounds()).anyMatch(TypedRegistry::mentionsTypeVariable)
                        || Arrays.stream(w.getLowerBounds()).anyMatch(TypedRegistry::mentionsTypeVariable);
                default -> false;
            };
        }

        void dump() { values.forEach((k, v) -> System.out.println("  " + k + " -> " + v)); }
    }

    // Gafter's "Oops": inside a generic method the token captures the type *variable* T.
    static <T> List<T> favoriteList(TypedRegistry registry) {
        TypeRef<List<T>> ref = new TypeRef<List<T>>() {};
        List<T> result = registry.get(ref);
        if (result == null) {
            result = new ArrayList<>();
            registry.put(ref, result);
        }
        return result;
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    public static void main(String[] args) {
        var names = new TypeRef<List<String>>() {};
        var ids = new TypeRef<List<Integer>>() {};
        TypeRef<Map<String, List<Integer>>> index = new TypeRef<>() {};   // diamond works too (Java 9+)

        System.out.println("stored in the class file: " + names.getClass().getGenericSuperclass());

        var registry = new TypedRegistry(true);
        registry.put(names, List.of("ada", "grace"));
        registry.put(ids, List.of(1, 2, 3));
        registry.put(index, Map.of("ada", List.of(1)));
        registry.dump();

        String first = registry.get(new TypeRef<List<String>>() {}).get(0);   // no cast
        System.out.println("first name, no cast: " + first);
        System.out.println("two List<String> tokens equal? " + names.equals(new TypeRef<List<String>>() {}));
        System.out.println("List<String> equals List<Integer>? " + names.equals(ids));

        try {
            new TypeRef() {};
        } catch (IllegalStateException e) {
            System.out.println("raw token: " + e.getMessage());
        }

        // Limit: one anonymous class per call site, so every T shares one key.
        var lenient = new TypedRegistry(false);
        List<String> strings = favoriteList(lenient);
        List<Integer> numbers = favoriteList(lenient);
        numbers.add(42);
        System.out.println("same list for String and Integer? " + (strings == (Object) numbers));
        try {
            String s = strings.get(0);
            System.out.println("never printed " + s);
        } catch (ClassCastException e) {
            System.out.println("lenient registry: " + e.getClass().getSimpleName());
        }
        try {
            favoriteList(registry);
        } catch (IllegalArgumentException e) {
            System.out.println("strict registry: " + e.getMessage());
        }
    }
}
```

Output:

```text output
stored in the class file: SuperTypeTokenDemo$TypeRef<java.util.List<java.lang.String>>
  java.util.List<java.lang.String> -> [ada, grace]
  java.util.List<java.lang.Integer> -> [1, 2, 3]
  java.util.Map<java.lang.String, java.util.List<java.lang.Integer>> -> {ada=[1]}
first name, no cast: ada
two List<String> tokens equal? true
List<String> equals List<Integer>? false
raw token: TypeRef created without a type argument
same list for String and Integer? true
lenient registry: ClassCastException
strict registry: java.util.List<T> mentions a type variable
```

## How it works

* **What erasure keeps.** Erasure removes type arguments from objects and from the bytecode of method bodies, but declarations keep their generic signatures in a `Signature` attribute in the class file, because separate compilation needs them. That is what `getGenericSuperclass()`, `getGenericReturnType()` and friends read. The first output line is the anonymous class's own declaration.
* **The `{}` is the whole trick.** Without it there is no new class and no declaration to read. The abstract modifier exists only to make the braces mandatory.
* **Equality comes for free.** The `ParameterizedType` Javadoc requires implementations to equate instances with the same generic declaration and equal type arguments. Two tokens written in different places therefore compare equal, which is what makes them usable as map keys.
* **`get` is unchecked, and honest about it.** The JVM can verify `List`, which `put` does with `rawType().cast(value)`, but it cannot verify `<String>`. The registry is type safe only because every `put` and `get` goes through a token with the same full type.
* **The diamond works with anonymous classes since Java 9** (as long as the inferred type is denotable), and javac writes the *inferred* argument into the class file, so `TypeRef<Map<String, List<Integer>>> index = new TypeRef<>() {}` captures the full map type.

The idea works on any Java version since 5. This example uses pattern matching for `switch`, so it needs Java 21.

## Gotchas

* **Type variables are captured as type variables.** `new TypeRef<List<T>>() {}` inside a generic method is compiled once, so it records `List<T>`, not `List<String>`. In the lenient registry both calls of `favoriteList` share one key and one list, and a `String` read hits an `Integer`. Gafter showed exactly this program in "A Limitation of Super Type Tokens" and proposed the fix used here: reject type variables at runtime.
* **Raw subclasses.** `new TypeRef() {}` compiles with a warning and has no type argument. Fail fast in the constructor, as above, rather than later with a cryptic `ClassCastException`.
* **The values are still erased.** A raw `TypeRef` key or an unchecked cast can store a `List<Integer>` under `List<String>`, and the registry cannot notice. Super type tokens make honest code type safe; they do not make generics reified.
* **One class per call site.** Every `new TypeRef<...>() {}` in your source is a separate class file. That is cheap, but in a library prefer `static final` constants for tokens you use often.
* **`Type` is harder to work with than `Class`.** You cannot call `type.cast(x)` or `newInstance()` on a `ParameterizedType`, and the string forms of `Type` are not specified, so never use them as keys. Do real work on `rawType()` and compare tokens with `equals`.

## When to use it (and when not to)

Use the library version whenever an API asks for it: Jackson's `mapper.readValue(json, new TypeReference<List<Order>>() {})`, Guice's `TypeLiteral`, Gson's `TypeToken`, Spring's `ParameterizedTypeReference`. Write your own when you build a registry, an event bus or a small injection container that must distinguish `Handler<Order>` from `Handler<User>`.

Do not reach for it when a `Class<T>` is enough. If no key is ever generic, Bloch's plain heterogeneous container ([033](033-heterogeneous-container.md)) is simpler and fully checked at runtime. And if the code that creates the token is itself generic in `T`, the token cannot help you: pass a token in from a caller that knows the concrete type.

## Related

* [033 · The Type-Safe Heterogeneous Container](033-heterogeneous-container.md)
* [020 · A Type-Safe Event Bus in 50 Lines](../03-build-it-yourself/020-event-bus.md)
* [021 · A Dependency Injection Container in 100 Lines](../03-build-it-yourself/021-di-container.md)
* [039 · Type Erasure Puzzlers and Generic Arrays](039-erasure-and-arrays.md)

## Sources

* Neal Gafter, [Super Type Tokens](https://gafter.blogspot.com/2006/12/super-type-tokens.html) (2006) and [A Limitation of Super Type Tokens](https://gafter.blogspot.com/2007/05/limitation-of-super-type-tokens.html) (2007)
* [`java.lang.reflect.ParameterizedType` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/reflect/ParameterizedType.html)
* Jackson [`TypeReference`](https://javadoc.io/doc/com.fasterxml.jackson.core/jackson-core/latest/com/fasterxml/jackson/core/type/TypeReference.html) and Guice [`TypeLiteral`](https://google.github.io/guice/api-docs/latest/javadoc/com/google/inject/TypeLiteral.html)
