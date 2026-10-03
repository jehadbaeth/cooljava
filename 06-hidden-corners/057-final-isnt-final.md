# 057 · final Isn't Final (Yet)

> Since Java 5, `final` on an instance field has been a strongly worded suggestion: three lines of reflection overwrite it. JDK 26 started complaining out loud, and a future release will simply say no.

**Since:** Java 16 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

Everybody reads `final` as a promise:

```java
final class Config {
    final int port;
    Config(int port) { this.port = port; }
}
```

Assigned once in the constructor, never again. You reason about correctness with it, the Java Memory Model gives final fields special safe publication guarantees, and in theory the JIT could treat the value as a constant.

In practice the promise has had a back door since JDK 5, when deep reflection learned to write final fields so that serialization libraries could rebuild objects. The back door is still open in JDK 25, and the JDK team has started to close it.

## The trick

```java
Field port = Config.class.getDeclaredField("port");
port.setAccessible(true);   // lift the access check
port.setInt(config, 9090);  // and the final check with it
```

That is the whole trick. What is more interesting is the list of places where it quietly fails or loudly refuses:

| Target | What happens |
|---|---|
| final instance field, assigned in the constructor | Works. JDK 26 and later print a warning |
| final instance field initialized with a constant (`final int retries = 3`) | "Works", but your code never sees it |
| `static final` field | `IllegalAccessException`, even after `setAccessible(true)` |
| record component field | `IllegalAccessException`, by design since records arrived |
| field of a hidden class, e.g. a lambda's captured variable | `IllegalAccessException` |
| any final field through a `VarHandle` | `UnsupportedOperationException`: VarHandles are read-only for finals |

## Full example

The same program runs on JDK 25 and JDK 27. Each numbered step pokes one row of the table.

```java run stderr
import java.lang.invoke.MethodHandles;
import java.lang.reflect.Field;
import java.util.function.IntSupplier;

public class FinalDemo {

    static final class Config {
        final int port;            // assigned in the constructor
        final int retries = 3;     // a constant variable: javac inlines every read
        static final Integer TIMEOUT = 30;
        Config(int port) { this.port = port; }
    }

    record Point(int x, int y) {}

    interface Attempt { Object run() throws Throwable; }

    static void attempt(String label, Attempt attempt) {
        try {
            System.out.println(label + " -> ok: " + attempt.run());
        } catch (Throwable t) {
            // Hidden class names end in "/0x" plus an address that changes per run: cut it off.
            String message = String.valueOf(t.getMessage()).replaceAll("/0x\\p{XDigit}+", "");
            System.out.println(label + " -> " + t.getClass().getSimpleName() + ": " + message);
        }
    }

    public static void main(String[] args) throws Exception {
        var config = new Config(8080);

        // 1. A plain final instance field.
        Field port = Config.class.getDeclaredField("port");
        port.setAccessible(true);
        port.setInt(config, 9090);
        System.out.println("port: code sees " + config.port);

        // 2. A constant variable: the write lands, but compiled code never reads the field.
        Field retries = Config.class.getDeclaredField("retries");
        retries.setAccessible(true);
        retries.setInt(config, 99);
        System.out.println("retries: code sees " + config.retries + ", reflection sees " + retries.getInt(config));

        // 3. static final: setAccessible(true) succeeds, set() still refuses.
        attempt("static final", () -> {
            Field f = Config.class.getDeclaredField("TIMEOUT");
            f.setAccessible(true);
            f.set(null, 60);
            return Config.TIMEOUT;
        });

        // 4. Records refuse, by design.
        var point = new Point(1, 2);
        attempt("record", () -> {
            Field f = Point.class.getDeclaredField("x");
            f.setAccessible(true);
            f.setInt(point, 42);
            return point;
        });

        // 5. Every lambda is an instance of a hidden class.
        int captured = 1;
        IntSupplier lambda = () -> captured;
        System.out.println("lambda class is hidden: " + lambda.getClass().isHidden());
        attempt("lambda", () -> {
            Field f = lambda.getClass().getDeclaredFields()[0];
            f.setAccessible(true);
            f.setInt(lambda, 2);
            return lambda.getAsInt();
        });

        // 6. VarHandles never had write access to finals.
        attempt("VarHandle", () -> {
            var handle = MethodHandles.lookup().findVarHandle(Config.class, "port", int.class);
            handle.set(config, 7070);
            return config.port;
        });

        // 7. The old "clear the FINAL bit" hack needs Field.modifiers. It is hidden from reflection.
        attempt("Field.modifiers", () -> Field.class.getDeclaredField("modifiers"));
    }
}
```

Output on JDK 25 (stderr included, and it is empty):

```text output
port: code sees 9090
retries: code sees 3, reflection sees 99
static final -> IllegalAccessException: Can not set static final java.lang.Integer field FinalDemo$Config.TIMEOUT to java.lang.Integer
record -> IllegalAccessException: Can not set final int field FinalDemo$Point.x to (int)42
lambda class is hidden: true
lambda -> IllegalAccessException: Can not set final int field FinalDemo$$Lambda.arg$1 to (int)2
VarHandle -> UnsupportedOperationException: set
Field.modifiers -> NoSuchFieldException: modifiers
```

On JDK 27, stdout of that program is byte for byte the same (checked by running it and diffing), plus three lines on stderr. Here is a smaller program that isolates the difference:

```java run jdk=27 stderr nondeterministic
import java.lang.reflect.Field;

public class Mutate {

    static final class Config {
        final int port;
        final String host;
        Config(int port, String host) { this.port = port; this.host = host; }
    }

    public static void main(String[] args) throws Exception {
        var config = new Config(8080, "localhost");
        Field port = Config.class.getDeclaredField("port");
        Field host = Config.class.getDeclaredField("host");
        port.setAccessible(true);
        host.setAccessible(true);

        port.setInt(config, 9090);        // first illegal final field mutation: one warning
        host.set(config, "example.org");  // second one: silent, the warning is once per module
        System.out.println("config is now " + config.host + ":" + config.port);
    }
}
```

Output on JDK 27 (one real run):

```text output
config is now example.org:9090
WARNING: Final field port in class Mutate$Config has been mutated reflectively by class Mutate in unnamed module @4d826d77 (file:Mutate.java)
WARNING: Use --enable-final-field-mutation=ALL-UNNAMED to avoid a warning
WARNING: Mutating final fields will be blocked in a future release unless final field mutation is enabled
```

Three things to read correctly here. The warning is printed at the first `setInt`, before the `println`; it shows up last only because stdout and stderr are captured separately. The hex after `unnamed module @` is an identity hash code and changes between runs, which is why this block is marked as nondeterministic. And on your machine the part in parentheses is the full path of the source file.

The new behavior is controlled by two launcher options, listed by `java --help` on JDK 27 (not `--help-extra`). Always write them with `=`, for reasons explained under Gotchas. With the same `Mutate.java` on JDK 27:

```shell
$ java --illegal-final-field-mutation=deny Mutate.java
```

```text
Exception in thread "main" java.lang.IllegalAccessException: class Mutate (in unnamed module @1a052a00) cannot set final field Mutate$Config.port (in unnamed module @1a052a00), unnamed module @1a052a00 is not allowed to mutate final fields
	at java.base/java.lang.reflect.Field.preSetFinal(Field.java:1516)
	at java.base/java.lang.reflect.Field.setFinal(Field.java:1459)
	at java.base/java.lang.reflect.Field.setInt(Field.java:1146)
	at Mutate.main(Mutate.java:18)
```

```shell
$ java --enable-final-field-mutation=ALL-UNNAMED Mutate.java
```

```text
config is now example.org:9090
```

`deny` turns the first write into an exception, `--enable-final-field-mutation` makes the warning go away, and enabling wins over `deny` for the named module (adding `--illegal-final-field-mutation=deny` to the second command changes nothing). JDK 25 does not know either option and refuses to start:

```shell
$ java --enable-final-field-mutation=ALL-UNNAMED Mutate.java    # JDK 25
```

```text
Unrecognized option: --enable-final-field-mutation=ALL-UNNAMED
Error: Could not create the Java Virtual Machine.
Error: A fatal exception has occurred. Program will exit.
```

## How it works

* **`setAccessible(true)` is the only gate on JDK 25.** For a final instance field in an ordinary class, a successful `setAccessible` also unlocks writes. That is the JDK 5 compromise for serialization frameworks, and the reason JEP 500 exists.
* **Constant variables are inlined by javac.** `final int retries = 3` is a *constant variable* (JLS §4.12.4), so `config.retries` compiles to the literal `3`. The reflective write really happens (`retries.getInt` returns 99), but no compiled read ever looks at the field. JLS §17.5.3 calls this out explicitly: such changes "may not be observed".
* **Static finals were never writable through `Field.set`.** The classic workaround cleared the `FINAL` bit in `Field.modifiers`. Since JDK 12 (JDK-8210522) the fields of `java.lang.reflect.Field` are filtered from reflection, hence `NoSuchFieldException: modifiers` on both 25 and 27. The JDK 27 Javadoc of `Field.set` now spells out every condition for writing a final field: `setAccessible` succeeded, mutation is enabled for the caller's module, the package is accessible to it, the class is neither a record nor hidden, and the field is not static.
* **Records and hidden classes are the preview of the future.** JEP 500 explains that hidden classes (JDK 15) and records (JDK 16) were deliberately made non-mutable through deep reflection. Every lambda's class is hidden, so a lambda's captured value is truly final.
* **VarHandles always respected `final`.** `findVarHandle` on a final field gives you a handle whose write access modes throw `UnsupportedOperationException`. Only the older `Field` API had the loophole.
* **JDK 26 (JEP 500) adds a second gate.** A write to a final field is now *illegal* unless the caller's module is named in `--enable-final-field-mutation` and the field's package is open to it. What happens on an illegal write is chosen by `--illegal-final-field-mutation`: `allow`, `warn` (the default in 26 and 27, one warning per module), `debug` (the same message without the `WARNING:` prefix, plus a stack trace, for every mutation) or `deny` (`IllegalAccessException`). An unknown value such as `=bogus` stops the JVM at startup. The help text adds that `--illegal-final-field-mutation` itself "will be removed in a future release", and JEP 500 says `deny` will become the default in a future release. This doc ran JDK 25 and 27; the JDK 26 behavior is taken from the JEP.
* **The warning is not printed via `System.err`.** Redirecting `System.setErr` does not capture it; it goes to the original standard error stream.

## Gotchas

* **`--add-opens` does not silence the JEP 500 warning.** The two are separate permissions: opens lets you call `setAccessible`, the new flag lets you write finals.
* **The help text shows a spelling that does not work.** `java --help` on JDK 27 documents `--enable-final-field-mutation <module name>`, with a space, just like `--add-opens`. Build 27+35 rejects that form with `Unrecognized option: --enable-final-field-mutation` and refuses to start, and `--illegal-final-field-mutation deny` fails the same way, while `--enable-native-access ALL-UNNAMED` with a space is accepted. Only the `=` form works, which is also the form the warning itself suggests.
* **One flag for two JDKs is not free.** A start script that adds `--enable-final-field-mutation` breaks on JDK 25 ("Unrecognized option"). `-XX:+IgnoreUnrecognizedVMOptions` does make JDK 25 start anyway, at the price of also hiding your real typos.
* **The warning shows up once per module.** The second mutation in `Mutate` is silent, and so are all the mutations in your favorite mocking library after the first one. To see every site, use `--illegal-final-field-mutation=debug`, or JFR: JDK 27 records `jdk.FinalFieldMutation` events with the field name and a stack trace (two of them for `Mutate.java`, even under `allow`). The event is documented as a sample, so do not expect one per write in a hot loop.
* **Compiled code may not see your write.** JLS §17.5.3 allows reads of a final field to be reordered around a reflective write, so even the cases that "work" are only well defined for an object that nobody has read or seen yet. That is exactly the deserialization case, and nothing else.
* **`System.out`, `in` and `err` are special.** They are write-protected (JLS §17.5.4) and can only be changed through `System.setOut` and friends, on every JDK.

## When to use it (and when not to)

At a party, to make a senior developer spill their coffee. In production code: never, and JDK 27 is telling you so in writing. The honest uses that exist today are all library internals:

* Serialization frameworks should move to `sun.reflect.ReflectionFactory`, which JEP 500 names as the supported path for `Serializable` classes.
* Dependency injection into final fields is better done with constructor injection, which every mainstream container supports.
* Tests that "just patch a final field" should get a constructor or a factory instead.

The practical action item is the opposite of the trick: run your test suite on JDK 26 or later with `--illegal-final-field-mutation=deny` and find out which of your dependencies still mutate finals before a future JDK makes that the default.

## Related

* [055 · The Integer Cache and Making 2 + 2 = 5](055-integer-cache-2-plus-2.md), a party trick that JEP 500 does not catch
* [043 · Records Beyond POJOs](../05-modern-language/043-records-beyond-pojos.md)
* [082 · Lazy Initialization: Double-Checked Locking, Holders and Lazy Constants](../09-concurrency/082-lazy-and-dcl.md), the supported way to get "assigned once, then constant"
* [086 · MethodHandles and LambdaMetafactory: Reflection at Full Speed](../10-jvm-performance/086-methodhandles-lambdametafactory.md)

## Sources

* [JEP 500: Prepare to Make Final Mean Final](https://openjdk.org/jeps/500)
* [JLS §17.5.3: Subsequent Modification of final Fields](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html#jls-17.5.3)
* [`Field.set` Javadoc (Java 27)](https://docs.oracle.com/en/java/javase/27/docs/api/java.base/java/lang/reflect/Field.html#set(java.lang.Object,java.lang.Object)), with the full list of conditions for writing a final field
* [JEP 371: Hidden Classes](https://openjdk.org/jeps/371) and [JEP 395: Records](https://openjdk.org/jeps/395)
