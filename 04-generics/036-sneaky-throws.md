# 036 · Sneaky Throws: Checked Exceptions Without the Paperwork

> Checked exceptions are enforced by the compiler and by nobody else. One generic method with a lying cast throws an `IOException` out of a `Runnable`, and the JVM does not even blink.

**Since:** Java 8 · **Category:** [Generics and Type System Wizardry](../README.md#generics-and-type-system-wizardry) · **Level:** Advanced · **Verdict:** ⚠️ Situational

## The problem

`Runnable`, `Supplier`, `Function` and friends declare no checked exceptions. So the moment a lambda body touches the file system, javac stops you:

```java
List<String> lines = paths.stream()
        .map(p -> Files.readAllLines(p))   // error: unreported exception IOException
        .toList();
```

The usual escape is to catch the exception and wrap it in a `RuntimeException`. That works, but the wrapper changes the type your callers see, buries the real cause one `getCause()` deeper, and adds a try/catch to every lambda. Sometimes you just want the original `IOException` to fly out of the pipeline as itself, and you are willing to accept the consequences. (If you want the exception to stay *visible* in the types instead, that is the honest version of this idea: [037 · Checked Exceptions in Lambdas, Properly](037-generic-throws-lambdas.md).)

## The trick

```java
@SuppressWarnings("unchecked")
static <E extends Throwable> RuntimeException sneakyThrow(Throwable t) throws E {
    throw (E) t;
}
```

Two independent facts conspire here:

1. At a call site, javac **infers `E = RuntimeException`**, because `E` appears only in a `throws` clause and nothing forces it to be anything checked. As far as the compiler is concerned, `sneakyThrow` throws an unchecked exception, so no handler or `throws` clause is required.
2. Inside the method, `(E) t` is a cast to a type variable. Erasure turns `E` into `Throwable`, and `t` already is one, so **no cast is emitted at all**. The `athrow` instruction receives the original exception, whatever it is.

The return type is `RuntimeException` so that callers can write `throw sneakyThrow(e)`. That tells the flow analysis "this branch ends here", which a plain `void` method would not.

## Full example

```java run
import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.stream.Collectors;
import java.util.stream.Stream;

public class SneakyDemo {

    // javac infers E = RuntimeException at every call site, and erasure turns the cast into nothing.
    @SuppressWarnings("unchecked")
    static <E extends Throwable> RuntimeException sneakyThrow(Throwable t) throws E {
        throw (E) t;
    }

    // Roughly what Lombok's @SneakyThrows writes into your method body.
    static <T> T sneaky(Callable<T> body) {
        try {
            return body.call();
        } catch (Exception e) {
            throw sneakyThrow(e);
        }
    }

    // A generic method that "throws X" and does nothing: it fakes a throws clause for catch blocks.
    static <X extends Throwable> void declare() throws X {}

    static class Legacy {
        Legacy() throws IOException {
            throw new IOException("from a constructor");
        }
    }

    public static void main(String[] args) throws Exception {
        // 1. Runnable declares no exceptions, and we throw a checked one through it anyway.
        Runnable task = () -> { throw sneakyThrow(new IOException("thrown from a Runnable")); };
        try {
            task.run();
        } catch (Exception e) {
            System.out.println(e.getClass().getName() + ": " + e.getMessage());
            System.out.println("IOException? " + (e instanceof IOException)
                    + ", RuntimeException? " + (e instanceof RuntimeException));
        }

        // 2. A checked exception through a stream pipeline, without a wrapper type in sight.
        Path dir = Files.createTempDirectory("sneaky");
        Path good = Files.write(dir.resolve("good.txt"), Arrays.asList("hello"));
        Path missing = dir.resolve("missing.txt");
        try {
            List<List<String>> lines = Stream.of(good, missing)
                    .map(p -> sneaky(() -> Files.readAllLines(p)))
                    .collect(Collectors.toList());
            System.out.println(lines);
        } catch (Exception e) {
            System.out.println("pipeline failed with " + e.getClass().getSimpleName());
        } finally {
            Files.delete(good);
            Files.delete(dir);
        }

        // 3. Catching it by its real type needs a fake throws clause somewhere in the try body.
        try {
            SneakyDemo.<IOException>declare();
            sneakyThrow(new IOException("now catchable"));
        } catch (IOException e) {
            System.out.println("caught as IOException: " + e.getMessage());
        }

        // 4. The bytecode never admitted to throwing an IOException.
        Method m = SneakyDemo.class.getDeclaredMethod("sneakyThrow", Throwable.class);
        System.out.println("erased throws clause:  " + Arrays.toString(m.getExceptionTypes()));
        System.out.println("generic throws clause: " + Arrays.toString(m.getGenericExceptionTypes()));

        // 5. The pre-generics way: Class.newInstance propagates checked exceptions undeclared.
        try {
            @SuppressWarnings("deprecation")
            Object legacy = Legacy.class.newInstance();
        } catch (Exception e) {
            System.out.println("newInstance threw " + e.getClass().getSimpleName());
        }
    }
}
```

Output:

```text output
java.io.IOException: thrown from a Runnable
IOException? true, RuntimeException? false
pipeline failed with NoSuchFileException
caught as IOException: now catchable
erased throws clause:  [class java.lang.Throwable]
generic throws clause: [E]
newInstance threw IOException
```

The trick needs a Java 8 or later compiler (the example uses lambdas, but the inference rule is the real reason, see below). Step 2 above feeds the pipeline a missing file, and the `NoSuchFileException` comes out of the stream untouched, which is the whole point.

Now the obvious follow-up question: if the exception is really an `IOException`, can we catch it as one? Not directly. javac refuses:

```java compile-fail
import java.io.IOException;

public class CatchSneaky {
    @SuppressWarnings("unchecked")
    static <E extends Throwable> void sneakyThrow(Throwable t) throws E {
        throw (E) t;
    }

    public static void main(String[] args) {
        try {
            sneakyThrow(new IOException("boom"));
        } catch (IOException e) {
            System.out.println("caught " + e);
        }
    }
}
```

```text compile-error
CatchSneaky.java:12: error: exception IOException is never thrown in body of corresponding try statement
        } catch (IOException e) {
          ^
1 error
```

And here is the entire trick at the bytecode level. A method with a `throws E` clause compiled to two instructions:

```shell
javac Sneaky.java
javap -c -p Sneaky
```

where `Sneaky.java` holds the same method inside an interface (so there is no constructor to distract from it):

```java
interface Sneaky {
    @SuppressWarnings("unchecked")
    static <E extends Throwable> RuntimeException sneakyThrow(Throwable t) throws E {
        throw (E) t;
    }
}
```

```text
Compiled from "Sneaky.java"
interface Sneaky {
  public static <E extends java.lang.Throwable> java.lang.RuntimeException sneakyThrow(java.lang.Throwable) throws E;
    Code:
         0: aload_0
         1: athrow
}
```

Load the argument, throw it. No `checkcast`, nothing to fail.

## How it works

* **Checked exceptions are a javac rule, not a JVM rule.** The compile-time checking lives in JLS §11.2. The JVM will throw any `Throwable` from any method, and the `Exceptions` attribute in the class file (the thing `getExceptionTypes()` reads) is metadata for compilers and reflection. Output lines 1 and 2 show an `IOException` leaving a `Runnable` as itself, not as a wrapper.
* **Inference picks `RuntimeException`.** The call `sneakyThrow(new IOException(...))` mentions `E` nowhere in its arguments, so `E` has only the bound `E extends Throwable`. JLS §18.1.3 adds a special bound for variables that appear in a `throws` clause, which it describes as "purely informational: it directs resolution to optimize the instantiation of α so that, if possible, it is not a checked exception type". In §18.4 that turns into a rule: if every upper bound of the variable is a supertype of `RuntimeException`, the variable becomes `RuntimeException`. This rule is a Java 8 feature. Compiled with `javac --release 7`, the very same call infers `E = Throwable` and fails with `unreported exception Throwable`, which is why pre-Java-8 code had to spell it out as `Sneaky.<RuntimeException>sneakyThrow(e)`. That explicit form still compiles everywhere.
* **Erasure removes the safety net.** `(E) t` is an unchecked cast. The erasure of `E` is its bound `Throwable`, so the compiler emits no `checkcast` and the `javap` listing above is only `aload_0`, `athrow`. Output lines 5 and 6 show the same fact through reflection: the erased throws clause is `Throwable`, and only the generic signature remembers `E`.
* **`throw sneakyThrow(e)` instead of a bare call** keeps definite assignment and "missing return" analysis happy. After a bare `sneakyThrow(e);` javac thinks execution can continue.
* **Lombok's `@SneakyThrows` is this trick behind an annotation.** Its documentation describes the generated code as a `try` around your method body with `catch (UnsupportedEncodingException e) { throw Lombok.sneakyThrow(e); }`, and says the result "will not ignore, wrap, replace, or otherwise modify the thrown checked exception; it simply fakes out the compiler". The `sneaky(Callable)` helper above is the hand-written equivalent.
* **Catching it is the awkward part.** JLS §11.2.3 makes it an error to catch a checked exception class that the `try` body cannot throw, *unless* the class is `Exception` or one of its superclasses. So `catch (IOException e)` is rejected (the compile-fail above), while `catch (Exception e)` followed by `instanceof` is accepted. The `declare()` helper in step 3 is the other way out: calling `SneakyDemo.<IOException>declare()` in the `try` body makes javac believe an `IOException` can occur, and the `catch` becomes legal. Lombok's documentation puts it this way: "it is impossible to catch sneakily thrown checked types directly".
* **The idea is older than the generic version.** Puzzle 43 of *Java Puzzlers* (Bloch and Gafter, 2005) asks for a method that throws any given checked exception, and the comment in its companion code adds: "You must not use any deprecated methods." One answer that needs no generics is step 5: `Class.newInstance` propagates whatever the constructor throws. Its Javadoc admits it: "Use of this method effectively bypasses the compile-time exception checking that would otherwise be performed by the compiler". The method has been deprecated since Java 9 for exactly that reason.

## Gotchas

* **The signature now lies.** Nothing in a method's declaration or Javadoc tells callers an `IOException` may come out. They cannot catch it by type, IDEs cannot warn them, and if the method is later made honest (declaring `throws IOException`), the `catch (Exception e)` plus `instanceof` workarounds stay behind as noise nobody cleans up.
* **Frameworks that decide by exception type.** Spring's declarative transactions, for example, "mark a transaction for rollback only in the case of runtime, unchecked exceptions" (plus `Error`), and checked exceptions "do not result in a rollback in the default configuration". A sneakily thrown `IOException` is a checked type at runtime, so it commits. The same applies to any retry or circuit breaker policy that classifies by `instanceof RuntimeException`.
* **Stack traces and logging are normal**, which is the good news, and also why nobody notices the exception was sneaked until `catch (IOException)` refuses to compile.
* **`finally` and try-with-resources behave as usual.** The JVM sees an ordinary exception. Only static analysis is fooled.
* **The cast warning is real.** `@SuppressWarnings("unchecked")` is the one place the compiler would have caught you. Keep it on exactly one method, in one utility class, and review who calls it.
* **It does not make code better, just shorter.** Every use is a decision to skip the question "who handles this exception, and what do they need to know?"

## When to use it (and when not to)

Acceptable, in descending order of comfort:

* **Genuinely impossible exceptions.** The classic is `UnsupportedEncodingException` for `"UTF-8"`, which Lombok's documentation names as a use case. Since Java 7 `StandardCharsets.UTF_8` removes most of those.
* **Tests, scripts and throwaway tools**, where any exception ends the run and the stack trace is the whole error handling story.
* **A boundary you own**, where an interface like `Runnable` forces your hand, the exception propagates to a top-level handler that treats all `Throwable`s alike, and you would otherwise write the same wrapper forty times.

Harmful: public library APIs, code whose callers reasonably handle `IOException` or `SQLException` by type, anything running under a framework that classifies by exception type (transactions, retries, circuit breakers), and any place where the honest alternative is only three lines longer. In application code the honest alternatives are cheap: wrap in `UncheckedIOException` (see [037](037-generic-throws-lambdas.md)), return a value that carries the failure ([003 · Try](../01-functional/003-try-monad.md)), or let the lambda throw a declared type through a `throws E` interface. Reach for sneaky throws when you can name the reason it is safe in this one spot, not because the compiler was annoying.

## Related

* [037 · Checked Exceptions in Lambdas, Properly](037-generic-throws-lambdas.md), the same inference rule used honestly: the exception type stays in the signature
* [003 · Try: Turning Exceptions into Values](../01-functional/003-try-monad.md)
* [039 · Type Erasure Puzzlers and Generic Arrays](039-erasure-and-arrays.md), for more of what the missing `checkcast` means
* [092 · Cheap Exceptions: The Cost of a Stack Trace](../10-jvm-performance/092-cheap-exceptions.md)

## Sources

* JLS [§11.2 Compile-Time Checking of Exceptions](https://docs.oracle.com/javase/specs/jls/se25/html/jls-11.html#jls-11.2) and [§18.4 Resolution](https://docs.oracle.com/javase/specs/jls/se25/html/jls-18.html#jls-18.4) (the `RuntimeException` rule), with the `throws` bound defined in [§18.1.3](https://docs.oracle.com/javase/specs/jls/se25/html/jls-18.html#jls-18.1.3)
* Project Lombok, [`@SneakyThrows`](https://projectlombok.org/features/SneakyThrows)
* [`Class.newInstance` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Class.html), deprecated since Java 9
* Joshua Bloch and Neal Gafter, *Java Puzzlers* (Addison-Wesley, 2005), Puzzle 43, [companion site](http://www.javapuzzlers.com/)
* Spring Framework reference, [Rolling Back a Declarative Transaction](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/rolling-back.html)
