# 060 · finally Always Wins

> A `finally` block runs no matter what, and that includes overruling your `return`, eating your exception and hijacking your loop. It loses exactly one fight: against `System.exit`.

**Since:** Java 9 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

Nine small methods, each with a `try` and a `finally`. Predict every line of output before you look. Four of them come from Joshua Bloch and Neal Gafter's *Java Puzzlers*: `decision` is Puzzle 36 ("Indecision"), the manual cleanup is the bug in Puzzle 41 ("Field and Stream"), `workHard` is Puzzle 45 ("Exhausting Workout") with a fake stack limit so it finishes this century, and the last block is Puzzle 39 ("Hello, Goodbye").

```java run
import java.util.*;

public class FinallyWins {

    static void show(String label, Object value) {
        System.out.printf("%-32s %s%n", label, value);
    }

    static boolean decision() {
        try {
            return true;
        } finally {
            return false;
        }
    }

    static String report() {
        try {
            throw new IllegalStateException("disk on fire");
        } finally {
            return "all good";
        }
    }

    static int counter() {
        int count = 1;
        try {
            return count;
        } finally {
            count = 2;
        }
    }

    static List<String> guests() {
        List<String> guests = new ArrayList<>(List.of("Ada"));
        try {
            return guests;
        } finally {
            guests.add("Linus");
        }
    }

    static String breakOut() {
        while (true) {
            try {
                return "from the try block";
            } finally {
                break;
            }
        }
        return "from after the loop";
    }

    static final List<String> closed = new ArrayList<>();

    static class Resource implements AutoCloseable {
        private final String name;
        private final boolean failOnClose;

        Resource(String name, boolean failOnClose) {
            this.name = name;
            this.failOnClose = failOnClose;
        }

        @Override public void close() {
            closed.add(name);
            if (failOnClose) throw new IllegalStateException(name + " close failed");
        }
    }

    static void manualCleanup() {
        Resource in = new Resource("in", true);
        Resource out = new Resource("out", false);
        try {
            throw new RuntimeException("copy failed");
        } finally {
            in.close();
            out.close();
        }
    }

    static void automaticCleanup() {
        try (Resource in = new Resource("in", true);
             Resource out = new Resource("out", false)) {
            throw new RuntimeException("copy failed");
        }
    }

    static long calls;

    static void workHard(int depth, int stackLimit) {
        calls++;
        if (depth == stackLimit) throw new StackOverflowError("simulated");
        try {
            workHard(depth + 1, stackLimit);
        } finally {
            workHard(depth + 1, stackLimit);
        }
    }

    static String outcome(Runnable action) {
        try {
            action.run();
            return "nothing thrown";
        } catch (RuntimeException e) {
            String text = e.getClass().getSimpleName() + "(" + e.getMessage() + ")";
            for (Throwable suppressed : e.getSuppressed()) {
                text += " suppressing " + suppressed.getClass().getSimpleName() + "(" + suppressed.getMessage() + ")";
            }
            return text;
        }
    }

    public static void main(String[] args) {
        show("1. decision()", decision());
        show("2. report()", report());
        show("3. counter()", counter());
        show("4. guests()", guests());
        show("5. breakOut()", breakOut());

        show("6. manual cleanup", outcome(FinallyWins::manualCleanup));
        show("   closed", closed);
        closed.clear();
        show("7. try-with-resources", outcome(FinallyWins::automaticCleanup));
        show("   closed", closed);

        for (int stackLimit : new int[] {10, 20}) {
            calls = 0;
            try {
                workHard(0, stackLimit);
            } catch (StackOverflowError expected) {
                show("8. calls with stack limit " + stackLimit, calls);
            }
        }

        Runtime.getRuntime().addShutdownHook(new Thread(() -> System.out.println("9. shutdown hook")));
        try {
            System.out.println("9. Hello world");
            System.exit(0);
        } finally {
            System.out.println("9. Goodbye world");
        }
    }
}
```

## The answer

```text output
1. decision()                    false
2. report()                      all good
3. counter()                     1
4. guests()                      [Ada, Linus]
5. breakOut()                    from after the loop
6. manual cleanup                IllegalStateException(in close failed)
   closed                        [in]
7. try-with-resources            RuntimeException(copy failed) suppressing IllegalStateException(in close failed)
   closed                        [out, in]
8. calls with stack limit 10     2047
8. calls with stack limit 20     2097151
9. Hello world
9. shutdown hook
```

## Why

The rule behind almost every line is JLS §14.20.2: if the `finally` block completes *abruptly* (with `return`, `throw`, `break` or `continue`), the whole `try` statement completes abruptly for that reason, and whatever the `try` block was doing, returning a value or throwing an exception, is discarded without a trace.

### 1 and 2: the last `return` wins

In `decision`, the `try` block's `return true` evaluates `true` and schedules it, then the `finally` block runs and returns `false`, which replaces it. In `report` it is worse: the `IllegalStateException` is not wrapped, not suppressed, not logged. It is simply gone. A `return` in `finally` is a silent catch-all for every exception, including `Error`s like `OutOfMemoryError`.

### 3 and 4: the value is fixed, the object is not

`return count` copies the *value* `1` into the method's result before `finally` runs. Reassigning the local variable afterwards changes nothing. `return guests` copies the *reference*, and the `finally` block mutates the very list that reference points to, so the caller sees `Linus`. This is the same pass-by-value rule as for method arguments, just in a place where nobody expects it.

### 5: `break` cancels a `return`

A `break` in `finally` jumps out of the loop and discards the pending `return`. Execution continues after the loop as if the `try` block had never returned. `continue` does the same, which is how you write an infinite loop that contains a `return` on every iteration.

### 6 and 7: Field and Stream, then the fix

In the manual version, `in.close()` throws from inside `finally`. That exception replaces the original `copy failed`, so the root cause disappears, and `out.close()` never runs, so `out` leaks: the `closed` list contains only `in`. Bloch and Gafter's original copied files with two streams and had the same flaw.

Try-with-resources (Java 7) does the bookkeeping properly: it closes resources in reverse order of declaration, closes *every* one of them even when one fails, keeps the *original* exception as the primary one, and attaches the close failure with `addSuppressed`. That is exactly what line 7 shows. See [048](../05-modern-language/048-try-with-resources-tricks.md) for more.

### 8: an exhausting workout

The original `workHard` calls itself in both the `try` and the `finally` with no base case. You would expect a quick `StackOverflowError`. But when the call in `try` overflows, `finally` catches the moment and recurses again, and so does every level on the way back up. Each frame makes two calls, so the number of calls doubles with each level of depth, as the output shows: about 2 to the power of (stack limit + 1). A real JVM stack holds thousands of frames, so the original needs on the order of 2 to the power of several thousand calls. It does terminate in theory, long after the heat death of the universe, and even then it dies with a `StackOverflowError` instead of printing its promised "It's nap time."

### 9: the one thing that beats `finally`

`System.exit` never returns. It starts the JVM shutdown sequence, runs the registered shutdown hooks (which is why line 9 shows the hook) and halts. The `finally` block does not run, and neither does any code after it. The same is true when the process is killed or `Runtime.halt` is called. `finally` is a control flow construct, not a guarantee that code runs before the process dies.

### javac knew all along

Lines 1, 2 and 5 are all flagged by javac's `finally` lint, which is off by default. Save the puzzle program as `FinallyWins.java` and compile it with the lint on:

```shell
$ javac -Xlint:finally FinallyWins.java
```

```text
FinallyWins.java:14: warning: [finally] finally clause cannot complete normally
        }
        ^
FinallyWins.java:22: warning: [finally] finally clause cannot complete normally
        }
        ^
FinallyWins.java:49: warning: [finally] finally clause cannot complete normally
            }
            ^
3 warnings
```

Those are the ends of the `finally` blocks in `decision`, `report` and `breakOut`. The lint only sees `return`, `throw`, `break` and `continue`. A *method call* that throws from `finally`, as in lines 6 and 8, gets no warning at all.

## Gotchas

* **A `finally` that throws loses the original exception** even if you do not write `throw` yourself: any method call in `finally` that can fail (`close`, `unlock`, `flush`) has the same effect as line 6.
* **`finally` is not a destructor.** Daemon threads are abandoned at JVM exit without running their `finally` blocks, and a `try` that never completes (an infinite loop, a deadlock) never reaches its `finally` either.
* **`lock.unlock()` belongs in `finally`, and `lock.lock()` belongs before the `try`.** If `lock()` sits inside the `try` and throws, `finally` calls `unlock()` on a lock you never held and throws `IllegalMonitorStateException`, replacing the real error.

## How to stay safe

* Never `return`, `throw`, `break` or `continue` out of a `finally` block. Compile with `-Xlint:finally` (or `-Xlint:all -Werror`) to make that a build failure.
* Use try-with-resources for anything with a `close` method, and wrap other cleanup (restoring a setting, releasing a permit) in a small `AutoCloseable` class to get ordering and suppressed exceptions for free.
* Keep `finally` blocks tiny and unable to fail. If they must call something that can throw, catch it there and `addSuppressed` it to the primary exception yourself.
* Put work that must survive `System.exit` into a shutdown hook, and keep that hook short.

## Related

* [048 · Try-With-Resources Tricks](../05-modern-language/048-try-with-resources-tricks.md)
* [036 · Sneaky Throws: Checked Exceptions Without the Paperwork](../04-generics/036-sneaky-throws.md)
* [092 · Cheap Exceptions: The Cost of a Stack Trace](../10-jvm-performance/092-cheap-exceptions.md)

## Sources

* [JLS §14.20.2: Execution of try-finally and try-catch-finally](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.20.2) and [§14.20.3: try-with-resources](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.20.3)
* [`java.lang.Runtime` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Runtime.html), on `exit`, `halt` and shutdown hooks
* Joshua Bloch and Neal Gafter, *Java Puzzlers: Traps, Pitfalls, and Corner Cases* (Addison-Wesley, 2005). The [book's site](http://www.javapuzzlers.com/) has the source code of every puzzle
