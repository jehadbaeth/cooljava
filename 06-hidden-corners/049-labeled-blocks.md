# 049 · Labeled Blocks: break Out of Anything

> Java reserved `goto`, never gave it a meaning, and handed you labels instead: a goto that may only jump outward, and only to a statement that encloses it.

**Since:** Java 8 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

Labels have been in the language since 1.0. The badge says 8 only because that is the oldest release a current javac can target.

## The problem

You are three loops deep and you found what you were looking for. A plain `break` leaves only the innermost loop, so the usual fix is a flag:

```java
boolean found = false;
for (int row = 0; row < grid.length && !found; row++) {
    for (int col = 0; col < grid[row].length; col++) {
        if (grid[row][col] == target) {
            found = true;
            break;
        }
    }
}
```

The flag leaks into every loop condition, and the real intent ("stop everything") is spread over three places. The same smell shows up without any loop: a sequence of checks where each failure should skip the rest of the section.

## The trick

Any statement can carry a label, and `break label;` ends the labeled statement immediately. Execution continues right after it.

```java
search:
for (int row = 0; row < grid.length; row++) {
    for (int col = 0; col < grid[row].length; col++) {
        if (grid[row][col] == target) break search;
    }
}
```

The label is not limited to loops. The example below puts one on a plain `{ }` block, on an `if` and on a `try`. `continue label;` is the stricter sibling: the label must sit on a loop, and the jump goes to that loop's next iteration.

| Form | Where the label can sit | What happens |
|---|---|---|
| `break label;` | any statement | the labeled statement ends, execution resumes after it |
| `continue label;` | a loop only | the labeled loop starts its next iteration |

The JLS (14.7) is blunt about the design: "Unlike C and C++, the Java programming language has no goto statement; identifier statement labels are used with break or continue statements."

This is not a museum piece. In JDK 25, `ArrayList.remove(Object)` is a labeled block (`found: { ... break found; ... }`), and `java.util.regex.Pattern` uses `continue NEXT;` inside its Boyer-Moore setup. The first example below is the same shape as the `ArrayList` code.

## Full example

Six uses of labels, then the same grid search written with a label and with an extracted method. `tryAndBreak` takes a boolean because a bare `break work;` followed by another statement would be rejected as unreachable code.

```java run
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public class LabeledBlocks {

    // 1. A label on a plain block: an early exit without any loop of its own.
    //    ArrayList.remove(Object) in the JDK has exactly this shape.
    static boolean removeFirst(List<String> list, String target) {
        int i = 0;
        found: {
            for (; i < list.size(); i++) {
                if (list.get(i).equals(target)) break found;
            }
            return false;
        }
        list.remove(i);
        return true;
    }

    // 2. A label on an if statement: bail out of the middle of it.
    static String normalize(String input) {
        String result = "(none)";
        guard: if (input != null) {
            if (input.trim().isEmpty()) break guard;
            result = input.trim().toLowerCase();
        }
        return result;
    }

    // 3. A label on a try statement: break still runs the finally block.
    static void tryAndBreak(boolean bail) {
        work: try {
            System.out.println("  in try");
            if (bail) break work;
            System.out.println("  rest of try");
        } finally {
            System.out.println("  finally");
        }
        System.out.println("  after the labeled try");
    }

    // 4. Labeled continue: skip to the next candidate from inside the inner loop.
    static List<Integer> primesBelow(int limit) {
        List<Integer> primes = new ArrayList<>();
        candidates:
        for (int n = 2; n < limit; n++) {
            for (int divisor = 2; divisor * divisor <= n; divisor++) {
                if (n % divisor == 0) continue candidates;
            }
            primes.add(n);
        }
        return primes;
    }

    // 5. Labeled break out of a switch inside a loop. A plain break only leaves the switch.
    static void interpret(String... commands) {
        loop:
        for (String command : commands) {
            switch (command) {
                case "stop":
                    break loop;
                case "skip":
                    continue;           // no label needed: continue ignores the switch
                default:
                    System.out.println("  run " + command);
                    break;              // leaves only the switch
            }
            System.out.println("  done " + command);
        }
    }

    // 6. The same search twice: labeled break, and an extracted method with return.
    static final int[][] GRID = {{3, 8, 1}, {4, 15, 6}, {7, 2, 15}};

    static String withLabel(int target) {
        String where = "not found";
        search:
        for (int row = 0; row < GRID.length; row++) {
            for (int col = 0; col < GRID[row].length; col++) {
                if (GRID[row][col] == target) {
                    where = "row " + row + ", col " + col;
                    break search;
                }
            }
        }
        return where;
    }

    static String withMethod(int target) {
        for (int row = 0; row < GRID.length; row++) {
            for (int col = 0; col < GRID[row].length; col++) {
                if (GRID[row][col] == target) return "row " + row + ", col " + col;
            }
        }
        return "not found";
    }

    public static void main(String[] args) {
        List<String> names = new ArrayList<>(Arrays.asList("ada", "linus", "grace"));
        System.out.println("removeFirst(linus): " + removeFirst(names, "linus") + " -> " + names);
        System.out.println("removeFirst(james): " + removeFirst(names, "james") + " -> " + names);

        System.out.println("normalize(null)     = " + normalize(null));
        System.out.println("normalize(\"   \")    = " + normalize("   "));
        System.out.println("normalize(\" Hi \")   = " + normalize(" Hi "));

        System.out.println("tryAndBreak(true):");
        tryAndBreak(true);
        System.out.println("tryAndBreak(false):");
        tryAndBreak(false);

        System.out.println("primes below 30: " + primesBelow(30));

        System.out.println("interpreter:");
        interpret("load", "skip", "save", "stop", "never");

        // Labels live in their own namespace, so a variable may share the name.
        int search = 7;
        search:
        for (int i = 0; i < 3; i++) {
            if (i == 1) break search;
        }
        System.out.println("variable and label share a name: " + search);

        for (int target : new int[] {15, 2, 99}) {
            System.out.printf("find %2d: %s | %s%n", target, withLabel(target), withMethod(target));
        }
    }
}
```

Output:

```text output
removeFirst(linus): true -> [ada, grace]
removeFirst(james): false -> [ada, grace]
normalize(null)     = (none)
normalize("   ")    = (none)
normalize(" Hi ")   = hi
tryAndBreak(true):
  in try
  finally
  after the labeled try
tryAndBreak(false):
  in try
  rest of try
  finally
  after the labeled try
primes below 30: [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
interpreter:
  run load
  done load
  run save
  done save
variable and label share a name: 7
find 15: row 1, col 1 | row 1, col 1
find  2: row 2, col 1 | row 2, col 1
find 99: not found | not found
```

## goto and const: reserved, unused

`goto` and `const` are keywords that do nothing. The JLS (3.9) says why they are reserved: "This may allow a Java compiler to produce better error messages if these C++ keywords incorrectly appear in programs." Here is what javac 25 makes of that:

```java compile-fail
public class Reserved {
    static final int const = 42;

    public static void main(String[] args) {
        System.out.println("before");
        goto end;
        System.out.println("skipped");
        end: System.out.println("after");
    }
}
```

```text compile-error
Reserved.java:2: error: <identifier> expected
    static final int const = 42;
                    ^
Reserved.java:6: error: illegal start of expression
        goto end;
        ^
Reserved.java:6: error: not a statement
        goto end;
             ^
3 errors
```

The messages are the generic parse errors you would get for any stray token, and none of them says "goto is not supported". The reservation only guarantees that the word can never be an identifier.

Labels also have firm rules about where a jump may go. This program breaks four of them:

```java compile-fail
import java.util.List;

public class BadJumps {
    public static void main(String[] args) {
        outer:
        for (int i = 0; i < 3; i++) {
            List.of(1, 2).forEach(n -> {
                if (n == 2) break outer;
            });
        }

        block: {
            for (int i = 0; i < 3; i++) {
                continue block;
            }
        }

        skip: System.out.println("labeled statement");
        break skip;

        again: again: System.out.println("twice");
    }
}
```

```text compile-error
BadJumps.java:8: error: undefined label: outer
                if (n == 2) break outer;
                            ^
BadJumps.java:14: error: not a loop label: block
                continue block;
                ^
BadJumps.java:19: error: undefined label: skip
        break skip;
        ^
BadJumps.java:21: error: label again already in use
        again: again: System.out.println("twice");
               ^
4 errors
```

## How it works

* **A labeled statement is just a statement with a name.** `break label` completes that statement abruptly and the program continues with whatever follows it. There is no address to jump to, only an enclosing statement to leave, which is why every jump goes outward and nothing can jump into the middle of a block.
* **`finally` still runs.** In `tryAndBreak(true)` the break leaves the `try`, but the `finally` block executes first.
* **A plain `break` inside a `switch` leaves only the switch.** That is why the interpreter needs `break loop`, while `continue` passes straight through the switch to the next iteration without a label.
* **Labels have their own namespace.** The JLS allows a label to share a name with a variable, method or class, so `int search = 7;` next to a `search:` label is legal and still prints 7. Legal is not the same as a good idea.
* **Scope is lexical.** The second compile-fail block shows the limits: a label is invisible inside a lambda body, it is gone after its statement, `continue` needs a loop label, and a label cannot be reused while it is still in scope.

## Gotchas

* **A lambda is a boundary.** `forEach(x -> { ... break outer; ... })` cannot work, because the lambda body is a different method. Use `anyMatch`, `takeWhile` or `findFirst`, or return a value from the lambda and decide outside.
* **Unreachable code is an error.** `break work;` followed directly by another statement in the same block does not compile, which is why the demo guards the break with a boolean.
* **Style is unsettled.** The JDK source has `found:`, `outer:`, `NEXT:` and `retryAfterResize:`. Put the label on its own line in front of the statement so it stands out.
* **Labels cannot fake a state machine.** They only jump outward. If you want to jump backwards or sideways, you want a loop around a `switch`, or an enum state machine ([016](../02-patterns/016-state-machines.md)).

## When to use it (and when not to)

Reach for a label when the alternative is clearly worse: a labeled `continue` in a nested search loop, or a labeled block where the early exit means "skip the rest of this section" and extracting a method would mean passing five locals in and several results out. That is the situation inside `ArrayList.remove`: the index found by the loops is needed after them, and the JDK authors preferred a labeled block over a flag.

Everywhere else, extract a method and use `return`. The `withMethod` version in the example does the same job with no label to learn, and it can be tested and reused on its own. Streams (`anyMatch`, `findFirst`) are fine when the search is the whole point of the method, but not a replacement for a loop that mutates state. If one method needs two or three labels, it is telling you it does too much.

## Related

* [051 · Weird but Legal Java Syntax](051-weird-legal-syntax.md), where a URL in your code compiles because `https:` is a label
* [060 · finally Always Wins](../07-puzzlers/060-finally-puzzlers.md), for what else abrupt exits do to `finally`
* [041 · Pattern Matching for switch: The Complete Toolkit](../05-modern-language/041-switch-pattern-matching.md), the modern way to branch without jumping
* [016 · State Machines with Enums and Sealed Types](../02-patterns/016-state-machines.md)

## Sources

* [JLS §14.7: Labeled Statements](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.7)
* [JLS §14.15: The break Statement](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.15) and [§14.16: The continue Statement](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.16)
* [JLS §3.9: Keywords](https://docs.oracle.com/javase/specs/jls/se25/html/jls-3.html#jls-3.9)
* [`ArrayList.remove(Object)` in OpenJDK](https://github.com/openjdk/jdk/blob/master/src/java.base/share/classes/java/util/ArrayList.java), the `found:` block
