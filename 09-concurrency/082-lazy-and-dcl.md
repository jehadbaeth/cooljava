# 082 · Lazy Initialization: Double-Checked Locking, Holders and Lazy Constants

> The most famous broken idiom in Java is six lines long and looks perfectly reasonable. Here is why it broke, the three ways to do it right, and the JDK 27 API that makes all of them obsolete.

**Since:** Java 19 (LazyConstant: Java 27 preview, JEP 531) · **Category:** [Concurrency](../README.md#concurrency) · **Level:** Advanced · **Verdict:** ✅ Production

## The problem

Some objects are expensive (a parsed configuration, a connection pool, a compiled template) and might never be needed. You want them created on first use, exactly once, even when eight threads ask at the same moment. The naive version is a race: two threads both see `null` and both build one. Making the getter `synchronized` is correct, but in the 1990s an uncontended lock was expensive, so people tried to skip it once the object existed:

```java
class Broken {
    private static Helper helper;                  // not volatile

    static Helper get() {
        if (helper == null) {                      // unsynchronized check
            synchronized (Broken.class) {
                if (helper == null) {
                    helper = new Helper();         // allocate, construct, publish
                }
            }
        }
        return helper;
    }
}
```

That is **double-checked locking** (DCL), and before Java 5 there was no way to make it correct. A who's who of the field (Bacon, Bloch, Click, Lea, Manson, Pugh and others) signed "The 'Double-Checked Locking is Broken' Declaration" to say so.

The reason: `helper = new Helper()` is three steps (allocate memory, run the constructor, store the reference), and nothing forces a thread that skips the lock to see them in that order. The JIT or the CPU may make the reference visible *before* the constructor's field writes. A second thread then passes the first `if`, finds a non-null `helper`, and uses an object whose fields still hold their default values. Even the two plain reads of `helper` (the check and the `return`) are a data race, and the memory model does not promise that the second one is at least as fresh as the first.

You will almost never see this fail on a laptop, which is exactly why it survived so long. Tools such as jcstress exist to catch it.

## The trick

There are four correct ways, and one of them is now in the JDK:

| Idiom | Works for | Cost after initialization | Failure in the initializer |
|---|---|---|---|
| `volatile` DCL with a local variable | instance and static fields | one volatile read | retried on the next call |
| Initialization-on-demand holder | static fields only | none (plain static read) | class is poisoned forever |
| `enum` singleton | singletons only | none | class is poisoned forever |
| `LazyConstant.of(supplier)` | anything | none, constant folded when held in a `static final` field | constant is poisoned forever |

The fixed DCL needs only one keyword. Since the Java 5 memory model (JSR 133), a write to a `volatile` field *happens before* every later read of it, which also publishes everything the constructor wrote before that store:

```java
private static volatile Config instance;

static Config get() {
    Config local = instance;                  // one volatile read on the fast path
    if (local == null) {
        synchronized (Config.class) {
            local = instance;
            if (local == null) {
                instance = local = new Config();
            }
        }
    }
    return local;
}
```

The local variable is Joshua Bloch's refinement in *Effective Java* (Item 83): once initialized, the method reads the volatile field once instead of twice. Here it is a speed tweak; in racy idioms without `volatile` (such as the hash caching in `String.hashCode`) reading the field exactly once is what makes them correct at all.

The holder idiom is even simpler, because it lets the JVM do the locking: put the field in a private nested class (`Holder.INSTANCE`). A class is initialized at its first active use, and JLS §12.4.2 requires that initialization to happen under a lock, exactly once.

## Full example

The first program runs on JDK 25. It races eight threads through a starting gate against the volatile DCL and a reusable `Lazy<T>`, shows when the holder class is initialized, attacks a classic singleton and an enum with reflection and serialization, and then makes every initializer fail once to compare what happens next.

```java run
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;

public class LazyDemo {

    // 1. Double-checked locking, done right.
    static final class Config {
        static final AtomicInteger LOADS = new AtomicInteger();
        private static volatile Config instance;

        private Config() { LOADS.incrementAndGet(); }

        static Config get() {
            Config local = instance;
            if (local == null) {
                synchronized (Config.class) {
                    local = instance;
                    if (local == null) {
                        instance = local = new Config();
                    }
                }
            }
            return local;
        }
    }

    // 2. A reusable memoizing Supplier: the same DCL, wrapped once and for all.
    static final class Lazy<T> implements Supplier<T> {
        private Supplier<? extends T> supplier;    // guarded by the lock, dropped after use
        private volatile T value;

        private Lazy(Supplier<? extends T> supplier) { this.supplier = Objects.requireNonNull(supplier); }
        static <T> Lazy<T> of(Supplier<? extends T> supplier) { return new Lazy<>(supplier); }

        @Override public T get() {
            T local = value;
            if (local == null) {
                synchronized (this) {
                    local = value;
                    if (local == null) {
                        local = Objects.requireNonNull(supplier.get(), "supplier returned null");
                        value = local;
                        supplier = null;   // let the lambda and whatever it captured be collected
                    }
                }
            }
            return local;
        }
    }

    // 3. Initialization-on-demand holder.
    static final class Registry {
        static { System.out.println("  Registry initialized"); }
        private Registry() { System.out.println("  Registry instance created"); }
        static void ping() { System.out.println("  Registry.ping()"); }

        private static final class Holder {
            static final Registry INSTANCE = new Registry();
        }
        static Registry instance() { return Holder.INSTANCE; }
    }

    // 4. Singletons under attack.
    static final class ClassicSingleton implements Serializable {
        static final ClassicSingleton INSTANCE = new ClassicSingleton();
        private ClassicSingleton() {}
    }
    enum EnumSingleton { INSTANCE }

    // 5. An initializer that fails the first time and works the second time.
    static int attempts;
    static String connect() {
        if (++attempts == 1) throw new IllegalStateException("network down");
        return "connected";
    }
    static final class Connection {
        private static final class Holder { static final String VALUE = connect(); }
        static String get() { return Holder.VALUE; }
    }

    static <T> int distinctResults(Supplier<T> task) throws Exception {
        var gate = new CountDownLatch(1);
        try (ExecutorService pool = Executors.newFixedThreadPool(8)) {
            List<Future<T>> futures = new ArrayList<>();
            for (int i = 0; i < 8; i++) futures.add(pool.submit(() -> { gate.await(); return task.get(); }));
            gate.countDown();   // all eight threads race for the first get()
            Set<T> seen = Collections.newSetFromMap(new IdentityHashMap<>());
            for (Future<T> f : futures) seen.add(f.get());
            return seen.size();
        }
    }

    @SuppressWarnings("unchecked")
    static <T> T roundTrip(T object) throws Exception {
        var bytes = new ByteArrayOutputStream();
        try (var out = new ObjectOutputStream(bytes)) { out.writeObject(object); }
        try (var in = new ObjectInputStream(new ByteArrayInputStream(bytes.toByteArray()))) {
            return (T) in.readObject();
        }
    }

    static String attempt(Supplier<String> s) {
        try { return s.get(); } catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    public static void main(String[] args) throws Exception {
        System.out.println("volatile DCL: " + distinctResults(Config::get) + " instance, "
                + Config.LOADS.get() + " constructor call");
        var loads = new AtomicInteger();
        Lazy<StringBuilder> lazy = Lazy.of(() -> { loads.incrementAndGet(); return new StringBuilder("pool"); });
        System.out.println("Lazy<T>:      " + distinctResults(lazy) + " instance, " + loads.get() + " supplier call");

        System.out.println("holder idiom:");
        Registry.ping();
        System.out.println("  first instance() call");
        System.out.println("  same instance twice: " + (Registry.instance() == Registry.instance()));

        var constructor = ClassicSingleton.class.getDeclaredConstructor();
        constructor.setAccessible(true);
        System.out.println("classic singleton, reflection makes a second one: "
                + (constructor.newInstance() != ClassicSingleton.INSTANCE));
        System.out.println("classic singleton, deserialized copy is new:     "
                + (roundTrip(ClassicSingleton.INSTANCE) != ClassicSingleton.INSTANCE));
        try {
            var enumConstructor = EnumSingleton.class.getDeclaredConstructor(String.class, int.class);
            enumConstructor.setAccessible(true);
            enumConstructor.newInstance("EVIL_TWIN", 1);
        } catch (IllegalArgumentException e) {
            System.out.println("enum singleton, reflection: " + e.getMessage());
        }
        System.out.println("enum singleton, deserialized copy is the same:   "
                + (roundTrip(EnumSingleton.INSTANCE) == EnumSingleton.INSTANCE));

        System.out.println("failing initializer, holder: "
                + attempt(Connection::get) + ", then " + attempt(Connection::get));
        attempts = 0;
        Lazy<String> connection = Lazy.of(LazyDemo::connect);
        System.out.println("failing initializer, Lazy:   "
                + attempt(connection) + ", then " + attempt(connection));
    }
}
```

Output:

```text output
volatile DCL: 1 instance, 1 constructor call
Lazy<T>:      1 instance, 1 supplier call
holder idiom:
  Registry initialized
  Registry.ping()
  first instance() call
  Registry instance created
  same instance twice: true
classic singleton, reflection makes a second one: true
classic singleton, deserialized copy is new:     true
enum singleton, reflection: Cannot reflectively create enum objects
enum singleton, deserialized copy is the same:   true
failing initializer, holder: ExceptionInInitializerError, then NoClassDefFoundError
failing initializer, Lazy:   IllegalStateException, then connected
```

The same experiments with `java.lang.LazyConstant`, which needs JDK 27 and `--enable-preview`:

```java preview
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

public class LazyConstantDemo {

    record Config(String url) {}

    static final AtomicInteger LOADS = new AtomicInteger();
    static final AtomicInteger SQUARES_COMPUTED = new AtomicInteger();

    // Held in a static final field, the content can be constant folded by the JIT.
    static final LazyConstant<Config> CONFIG = LazyConstant.of(() -> {
        LOADS.incrementAndGet();
        return new Config("jdbc:h2:mem:demo");
    });

    // A list of 1,000 independent lazy constants: each element is computed on first access.
    static final List<Integer> SQUARES = List.ofLazy(1_000, i -> {
        SQUARES_COMPUTED.incrementAndGet();
        return i * i;
    });

    public static void main(String[] args) throws Exception {
        var gate = new CountDownLatch(1);
        Set<Config> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        try (ExecutorService pool = Executors.newFixedThreadPool(8)) {
            List<Future<Config>> futures = new ArrayList<>();
            for (int i = 0; i < 8; i++) futures.add(pool.submit(() -> { gate.await(); return CONFIG.get(); }));
            gate.countDown();
            for (Future<Config> f : futures) seen.add(f.get());
        }
        System.out.println("LazyConstant: " + seen.size() + " instance, " + LOADS.get() + " computation");

        System.out.println("SQUARES.get(12) = " + SQUARES.get(12) + " and again " + SQUARES.get(12)
                + ", elements computed: " + SQUARES_COMPUTED.get() + " of " + SQUARES.size());

        var attempts = new AtomicInteger();
        LazyConstant<String> connection = LazyConstant.of(() -> {
            if (attempts.incrementAndGet() == 1) throw new IllegalStateException("network down");
            return "connected";
        });
        for (int call = 1; call <= 2; call++) {
            try {
                System.out.println("get #" + call + ": " + connection.get());
            } catch (NoSuchElementException e) {
                System.out.println("get #" + call + ": NoSuchElementException, cause " + e.getCause());
            }
        }
        System.out.println("computing function calls: " + attempts.get());

        LazyConstant<String> nothing = LazyConstant.of(() -> null);
        try {
            nothing.get();
        } catch (NoSuchElementException e) {
            System.out.println("null content: rejected with cause " + e.getCause().getClass().getSimpleName());
        }
    }
}
```

Output:

```text output
LazyConstant: 1 instance, 1 computation
SQUARES.get(12) = 144 and again 144, elements computed: 1 of 1000
get #1: NoSuchElementException, cause java.lang.IllegalStateException: network down
get #2: NoSuchElementException, cause null
computing function calls: 1
null content: rejected with cause NullPointerException
```

## How it works

* **`volatile` is the whole fix.** A volatile write is a release: everything the writing thread did before it, including the constructor's field writes, becomes visible to any thread whose volatile read sees the new reference. The broken version had a lock on the writer's side only, and a lock only helps a reader that takes the same lock.
* **`Lazy<T>` drops its supplier** after the first success. A memoizer that keeps the lambda keeps everything the lambda captured. It also rejects `null`, because `null` is its "not yet" marker; a nullable value would be recomputed on every call.
* **The holder idiom has no visible synchronization** because class initialization already has it. `Registry.ping()` initializes `Registry` but not `Holder`: nested classes are initialized independently, on first use. After that, `Holder.INSTANCE` is a plain read of a `static final` field, which the JIT treats as a constant.
* **Enums are reflection proof by decree.** `Constructor.newInstance` refuses enum classes outright, and the serialization spec writes enum constants by name and resolves them back to the existing constant. A classic singleton needs a `readResolve` method returning `INSTANCE` to survive deserialization, and nothing stops `setAccessible`. Bloch's verdict (Item 3): a single-element enum is often the best way to implement a singleton.
* **`LazyConstant` is the JDK doing all of the above for you.** `get()` runs the computing function at most once, blocks racing threads until it is done, and stores the result in a field marked with the JDK-internal `@Stable` annotation. That annotation tells the JIT the value never changes after its first write, so a `static final LazyConstant` folds like a real constant, which a `volatile` field never can. `List.ofLazy`, `Map.ofLazy` and (new in 27) `Set.ofLazy` give you the same thing per element: above, one call computed one square out of a thousand.

### Three idioms, three failure modes

The last lines of each output are the part nobody reads until production does it for them. When the initializer throws, the **holder** class goes into an erroneous state: the first call gets `ExceptionInInitializerError`, every later call gets `NoClassDefFoundError: Could not initialize class ...`, and only a JVM restart cures it. The hand-rolled **`Lazy<T>`** never stored anything, so the next call simply tries again and succeeds. **`LazyConstant`** gives up for good, like the holder: the first `get()` throws `NoSuchElementException` with the original exception as its cause, later calls throw it without a cause and without calling the function again (the counter stays at 1), and a `null` result counts as a failure too.

None of these behaviors is wrong, but they are very different. If your initializer talks to the network, "poisoned forever" is probably not what you want, and only the hand-written version retries.

## Gotchas

* **Do not forget `volatile`.** DCL without it compiles, passes every test you will write, and fails on the one machine in production that reorders stores. Arm CPUs (including Apple Silicon) reorder more aggressively than x86.
* **`synchronized (this)` in `Lazy<T>`** means callers who also lock on the `Lazy` object can interfere. Lock on a private `Object` if the instance escapes into code you do not control.
* **Recursive initialization deadlocks or fails.** A holder whose initializer touches itself sees a half-initialized class (see [065](../07-puzzlers/065-initialization-order.md)); a `LazyConstant` whose function calls its own `get()` throws `NoSuchElementException` with an `IllegalStateException` cause; `Lazy<T>` above would re-enter its own lock and recurse until the stack overflows.
* **Do not print a lazy list.** `toString()` on `List.ofLazy(...)` forces every element. Printing a `LazyConstant` is harmless but its text contains an identity hash, so do not assert on it.
* **Instance fields fold less well.** Constant folding through a `LazyConstant` works reliably only when it sits in a `static final` field, because reflection can still modify ordinary instance `final` fields (see [057](../06-hidden-corners/057-final-isnt-final.md)).
* **The API moved.** It started as `StableValue` in JDK 25 (JEP 502), became `LazyConstant` in JDK 26 (JEP 526), and lost `isInitialized` and `orElse` in JDK 27 (JEP 531). Code written against an older preview does not compile on the next one.

## When to use it (and when not to)

First ask whether you need laziness at all. A plain `static final` field is already lazy, because the class it lives in is initialized only when first used. Most "lazy singletons" are better as eager fields, or as objects created once and passed in through a constructor.

When you do need it: the **holder** for static values, the **enum** for real singletons that must survive serialization, and **`volatile` DCL** or a small `Lazy<T>` for instance fields and for initializers that may fail and should be retried. Once `LazyConstant` is final, it replaces the first three with something shorter and faster; until then it is a preview API you can try but should not ship.

The idioms themselves work since Java 5; this example closes its executor with try-with-resources, hence Java 19.

## Related

* [084 · The Loop That Never Ends: volatile and the Memory Model](084-visibility-puzzler.md), the happens-before rules this page relies on
* [081 · A Lock-Free Stack with Compare-and-Set](081-treiber-stack.md), safe publication with atomics instead of locks
* [009 · Memoization Done Right](../01-functional/009-memoization.md), the many-keys version of `Lazy<T>`
* [065 · Initialization Order Puzzlers](../07-puzzlers/065-initialization-order.md), what class initialization does when it goes wrong

## Sources

* David Bacon, Joshua Bloch, Jeff Bogda, Cliff Click et al., [The "Double-Checked Locking is Broken" Declaration](https://www.cs.umd.edu/~pugh/java/memoryModel/DoubleCheckedLocking.html)
* Jeremy Manson and Brian Goetz, [JSR 133 (Java Memory Model) FAQ](https://www.cs.umd.edu/~pugh/java/memoryModel/jsr-133-faq.html) (2004)
* [JLS §12.4.2: Detailed Initialization Procedure](https://docs.oracle.com/javase/specs/jls/se25/html/jls-12.html#jls-12.4.2)
* [JEP 531: Lazy Constants (Third Preview)](https://openjdk.org/jeps/531)
* Joshua Bloch, *Effective Java*, 3rd edition (2018), Item 3 (enum singletons) and Item 83 (lazy initialization)
