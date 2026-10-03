# 085 · Dynamic Proxies: Implementing Interfaces at Runtime

> Give the JVM an interface and one method that answers every call, and it hands back an object that implements the interface. That is how Spring Data writes your queries while you are still typing the method name.

**Since:** Java 16 · **Category:** [JVM, Reflection and Performance](../README.md#jvm-reflection-and-performance) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

You have twenty service interfaces and you want every call logged, timed, retried or counted. The classic decorator works, but it means writing one wrapper class per interface, and every wrapper forwards every method by hand:

```java
final class LoggingGreeter implements Greeter {
    private final Greeter target;
    LoggingGreeter(Greeter target) { this.target = target; }

    public String greet(String name) { log("greet(" + name + ")"); return target.greet(name); }
    // ...and the same again for every other method, in every other interface
}
```

The flip side is even more interesting. Libraries like Spring Data, Retrofit, Feign and MyBatis let you write *only* an interface (`List<Person> findByCity(String city);`) and somehow an implementation appears. There is no generated source file anywhere. So who implements it?

## The trick

`java.lang.reflect.Proxy` has been in the JDK since 1.3. You give it a class loader, a list of interfaces and an `InvocationHandler`, and it generates a class at runtime that implements all of those interfaces. Every call on that object, whatever the method, lands in one place:

```java
InvocationHandler handler = (proxy, method, args) -> {
    long start = System.nanoTime();
    try {
        return method.invoke(target, args);
    } finally {
        System.out.printf("%s took %d us%n", method.getName(), (System.nanoTime() - start) / 1_000);
    }
};
Greeter timed = (Greeter) Proxy.newProxyInstance(
        Greeter.class.getClassLoader(), new Class<?>[] {Greeter.class}, handler);
```

That handler is a timing decorator for *any* interface. The handler gets the `Method` that was called, so it can do much more than forward the call. It can read the method's name, annotations and return type and decide what to do. That is the repository trick: parse `findByNameAndAge` into "filter on `name` and `age`" and run it.

## Full example

```java run
import java.lang.reflect.*;
import java.util.*;
import java.util.regex.*;
import java.util.stream.*;

public class ProxyDemo {

    // 1. A cross-cutting concern bolted onto any interface.
    interface Greeter {
        String greet(String name);
    }

    static <T> T logging(Class<T> iface, T target, List<String> log) {
        InvocationHandler handler = (proxy, method, args) -> {
            String call = method.getName() + Arrays.toString(args);
            try {
                Object result = method.invoke(target, args);
                log.add(call + " -> " + result);
                return result;
            } catch (InvocationTargetException e) {
                log.add(call + " threw " + e.getCause());
                throw e.getCause();   // unwrap, or callers get UndeclaredThrowableException
            }
        };
        return iface.cast(Proxy.newProxyInstance(iface.getClassLoader(), new Class<?>[] {iface}, handler));
    }

    // 2. A Spring Data style repository: the method name is the query.
    record Person(String name, int age, String city) {}

    interface PersonRepository {
        List<Person> findByCity(String city);
        List<Person> findByNameAndAge(String name, int age);
        Optional<Person> findFirstByCity(String city);
        long countByCity(String city);
        boolean existsByName(String name);

        // Default methods are real code; the handler hands them back to the interface.
        default List<String> namesIn(String city) {
            return findByCity(city).stream().map(Person::name).toList();
        }
    }

    interface BrokenRepository {
        List<Person> findByColour(String colour);
    }

    private static final Pattern QUERY = Pattern.compile("(find|count|exists)(First)?By(\\w+)");

    /** A parsed derived query: an action plus the record accessors to compare with the arguments. */
    record Query(String action, boolean first, List<Method> accessors) {

        static Query parse(Method method, Class<? extends Record> entity) {
            Matcher m = QUERY.matcher(method.getName());
            if (!m.matches()) throw new IllegalArgumentException(method.getName() + ": not a derived query");
            Map<String, Method> components = Arrays.stream(entity.getRecordComponents())
                    .collect(Collectors.toMap(RecordComponent::getName, RecordComponent::getAccessor));
            List<Method> accessors = new ArrayList<>();
            for (String part : m.group(3).split("And")) {
                String property = Character.toLowerCase(part.charAt(0)) + part.substring(1);
                Method accessor = components.get(property);
                if (accessor == null) {
                    throw new IllegalArgumentException(method.getName() + ": " + entity.getSimpleName()
                            + " has no property '" + property + "'");
                }
                accessors.add(accessor);
            }
            return new Query(m.group(1), m.group(2) != null, accessors);
        }

        Object execute(List<?> rows, Object[] args) {
            Stream<?> matches = rows.stream().filter(row -> matchesAll(row, args));
            return switch (action) {
                case "count" -> matches.count();
                case "exists" -> matches.findAny().isPresent();
                default -> first ? matches.findFirst() : matches.toList();
            };
        }

        private boolean matchesAll(Object row, Object[] args) {
            try {
                for (int i = 0; i < accessors.size(); i++) {
                    if (!Objects.equals(accessors.get(i).invoke(row), args[i])) return false;
                }
                return true;
            } catch (ReflectiveOperationException e) {
                throw new IllegalStateException(e);
            }
        }
    }

    static <R> R repository(Class<R> repoType, Class<? extends Record> entity, List<?> rows) {
        // Parse every abstract method up front, so a typo fails at startup, not at the first call.
        Map<Method, Query> queries = new HashMap<>();
        for (Method method : repoType.getMethods()) {
            if (!method.isDefault()) queries.put(method, Query.parse(method, entity));
        }
        InvocationHandler handler = (proxy, method, args) -> {
            if (method.isDefault()) return InvocationHandler.invokeDefault(proxy, method, args);
            return switch (method.getName()) {
                // Object's methods are routed through the handler too; answer them explicitly.
                case "toString" -> repoType.getSimpleName() + " over " + rows.size() + " rows";
                case "hashCode" -> System.identityHashCode(proxy);
                case "equals" -> proxy == args[0];
                default -> queries.get(method).execute(rows, args);
            };
        };
        return repoType.cast(Proxy.newProxyInstance(repoType.getClassLoader(), new Class<?>[] {repoType}, handler));
    }

    static void show(String label, Object value) {
        System.out.printf("%-26s = %s%n", label, value);
    }

    public static void main(String[] args) {
        List<String> log = new ArrayList<>();
        Greeter friendly = name -> {
            if (name.isBlank()) throw new IllegalArgumentException("name is blank");
            return "Hello, " + name;
        };
        Greeter greeter = logging(Greeter.class, friendly, log);
        greeter.greet("Ada");
        try {
            greeter.greet(" ");
        } catch (IllegalArgumentException e) {
            System.out.println("caller caught: " + e.getMessage());
        }
        log.forEach(line -> System.out.println("log: " + line));

        List<Person> people = List.of(
                new Person("Ada", 36, "London"),
                new Person("Alan", 41, "Manchester"),
                new Person("Grace", 85, "New York"),
                new Person("Tim", 36, "London"));
        PersonRepository repo = repository(PersonRepository.class, Person.class, people);
        System.out.println(repo);
        show("findByCity(London)", repo.findByCity("London"));
        show("findByNameAndAge(Ada, 36)", repo.findByNameAndAge("Ada", 36));
        show("findFirstByCity(Paris)", repo.findFirstByCity("Paris"));
        show("countByCity(London)", repo.countByCity("London"));
        show("existsByName(Grace)", repo.existsByName("Grace"));
        show("namesIn(London)", repo.namesIn("London"));
        show("isProxyClass", Proxy.isProxyClass(repo.getClass()));

        try {
            repository(BrokenRepository.class, Person.class, people);
        } catch (IllegalArgumentException e) {
            System.out.println("startup check: " + e.getMessage());
        }

        // The limit: only interfaces can be proxied.
        try {
            Proxy.newProxyInstance(ProxyDemo.class.getClassLoader(), new Class<?>[] {ArrayList.class},
                    (proxy, method, a) -> null);
        } catch (IllegalArgumentException e) {
            System.out.println("class proxy: " + e.getMessage());
        }
    }
}
```

Output:

```text output
caller caught: name is blank
log: greet[Ada] -> Hello, Ada
log: greet[ ] threw java.lang.IllegalArgumentException: name is blank
PersonRepository over 4 rows
findByCity(London)         = [Person[name=Ada, age=36, city=London], Person[name=Tim, age=36, city=London]]
findByNameAndAge(Ada, 36)  = [Person[name=Ada, age=36, city=London]]
findFirstByCity(Paris)     = Optional.empty
countByCity(London)        = 2
existsByName(Grace)        = true
namesIn(London)            = [Ada, Tim]
isProxyClass               = true
startup check: findByColour: Person has no property 'colour'
class proxy: java.util.ArrayList is not an interface
```

## How it works

* **A class generated on demand.** The first `newProxyInstance` call for a given class loader and interface list spins up a new final class that `extends Proxy` and implements the interfaces. Each of its methods does the same thing: call `h.invoke(this, <that Method>, args)`. The class is cached, so later proxies for the same interfaces reuse it. Its name is unspecified (something like `$Proxy0`), so never depend on it; ask `Proxy.isProxyClass` instead.
* **The `Method` object is the whole API.** The handler sees the method's name, parameter types, return type and annotations. The logging handler only forwards. The repository handler reads the name with a regex, maps each `And` part onto a record component, and decides what to return from the prefix: `count` gives a `long`, `exists` a `boolean`, `findFirst` an `Optional`, plain `find` a `List`.
* **Parse early, fail early.** `repository(...)` parses every abstract method when the proxy is created. `findByColour` is rejected before anyone calls it, which is exactly why a Spring application refuses to start when you misspell a derived query.
* **`toString`, `equals` and `hashCode` go through the handler.** The proxy class overrides those three `Object` methods to call `invoke` as well. The repository answers them itself, which is why `System.out.println(repo)` printed a readable line instead of crashing on a lookup for a query named `toString`.
* **Default methods.** `namesIn` has a body, and the handler should run it rather than treat it as a query. `InvocationHandler.invokeDefault` (Java 16) does exactly that. Inside `namesIn`, `findByCity(city)` is a call on the proxy again, so it loops back through the handler and runs as a query. Before Java 16 this needed a `MethodHandles.privateLookupIn(...).unreflectSpecial(...)` dance that broke between JDK versions.

The pattern works on any Java version since 1.3. This example uses records, `invokeDefault` and `Stream.toList()`, hence Java 16.

## Gotchas

* **Unwrap `InvocationTargetException`.** `method.invoke` wraps whatever the target throws. Rethrow `e.getCause()`, as the logging handler does, or callers see a reflection exception instead of their `IllegalArgumentException`.
* **Checked exceptions must be declared.** If the handler throws a checked exception that the interface method does not declare, the caller gets an `UndeclaredThrowableException` wrapping it. Your `IOException` arrives in disguise.
* **`null` for a primitive return type is a `NullPointerException`.** A handler that returns `null` from `long countByCity(...)` blows up in the proxy, not in your code, and the stack trace points at a class you never wrote.
* **Calling methods on `proxy` inside the handler recurses.** `proxy.toString()` in a log line goes straight back into `invoke`. Log `method` and `args`, not the proxy.
* **Interfaces only.** The last line of output is the hard limit. To intercept a concrete class you need a subclass generated at runtime (Byte Buddy, or the [Class-File API](088-classfile-api-hidden-classes.md) if you like pain).
* **Splitting on `And` is naive.** A property called `brandName` is fine, but one called `andromedaId` turns `findByAndromedaId` into nonsense. Real frameworks tokenize against the known property names instead.
* **Every call allocates.** The arguments are boxed into an `Object[]` and the call goes through reflection. That is noise for a repository that talks to a database, and real overhead in a hot inner loop.

## When to use it (and when not to)

Use dynamic proxies for cross-cutting behavior at an interface boundary (logging, metrics, retries, transactions, access checks), for test doubles you want to build in three lines, and for "declare an interface, get an implementation" APIs like HTTP clients and repositories. It is a stable, boring JDK feature that a large part of the Java ecosystem is quietly built on.

Do not use it to avoid writing three small classes, and do not put it in a hot path where an explicit decorator would do. If you need to intercept classes rather than interfaces, or you need the generated code to be as fast as handwritten code, reach for bytecode generation instead.

## Related

* [021 · A Dependency Injection Container in 100 Lines](../03-build-it-yourself/021-di-container.md), where proxies are the natural next step for interceptors
* [086 · MethodHandles and LambdaMetafactory: Reflection at Full Speed](086-methodhandles-lambdametafactory.md), for when reflective calls get too slow
* [087 · Property Names from Method References with SerializedLambda](087-serialized-lambda.md), the other half of typesafe query builders
* [088 · Generating Bytecode with the Class-File API](088-classfile-api-hidden-classes.md), for proxying what `Proxy` cannot

## Sources

* [`java.lang.reflect.Proxy` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/reflect/Proxy.html)
* [`java.lang.reflect.InvocationHandler` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/reflect/InvocationHandler.html), including `invokeDefault`
* [Spring Data JPA: Query Methods](https://docs.spring.io/spring-data/jpa/reference/jpa/query-methods.html), the real version of the repository trick
