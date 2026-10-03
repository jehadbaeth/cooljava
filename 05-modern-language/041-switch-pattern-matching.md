# 041 · Pattern Matching for switch: The Complete Toolkit

> The humble `switch` learned to test types, take apart records, handle `null` and prove it covered every case. Here is every tool in the box, plus the one rule that bites: order matters now.

**Since:** Java 22 · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

For twenty years, `switch` could compare an `int`, a `String` or an enum against constants, and that was it. Anything involving types meant an `instanceof` ladder:

```java
String classify(Object o) {
    if (o == null) return "null";
    if (o instanceof Integer && (Integer) o < 0) return "negative int " + o;
    if (o instanceof Integer) return "int " + o;
    if (o instanceof String && ((String) o).isBlank()) return "blank string";
    // ...and nothing tells you when you forgot a case
}
```

It casts twice, it falls off the end silently, and when the hierarchy grows, nothing reminds you to come back.

## The trick

Since Java 21 a `case` label can be a **pattern**, and Java 22 added the unnamed `_`. The full toolkit fits on one card:

| Tool | Syntax | Since |
|---|---|---|
| Type pattern | `case Integer i ->` | 21 |
| Guard | `case Integer i when i < 0 ->` | 21 |
| Record pattern | `case Delivered(var who, var hour) ->` | 21 |
| Null label | `case null ->` and `case null, default ->` | 21 |
| Qualified enum constant | `case Status.SHIPPED ->` | 21 |
| Exhaustive sealed switch | no `default` needed | 21 |
| Unnamed pattern and variable | `case Delayed(_, var hours)`, `case Long _, Short _ ->` | 22 |
| Block result | `-> { ...; yield value; }` | 14 |

The rules that hold it together: labels are tried **top to bottom**, the first match wins, a label that can never match is a compile error, and a `switch` over a sealed type that covers every case needs no `default`.

## Full example

```java run
import java.util.Arrays;

public class SwitchToolkit {

    // A sealed hierarchy that mixes an enum with records.
    sealed interface Event permits Status, Delivered, Delayed {}
    enum Status implements Event { CREATED, SHIPPED }
    record Delivered(String recipient, int hour) implements Event {}
    record Delayed(String reason, int hours) implements Event {}

    // Exhaustive without default: qualified enum constants, record patterns, guards, _ and yield.
    static String describe(Event event) {
        return switch (event) {
            case Status.CREATED -> "order created";
            case Status.SHIPPED -> "on its way";
            case Delivered(var who, var hour) when hour >= 22 -> "left with " + who + " at night";
            case Delivered(var who, _) -> "delivered to " + who;
            case Delayed(_, var hours) when hours >= 48 -> {
                int days = hours / 24;
                yield "stuck for " + days + " days";
            }
            case Delayed(var reason, _) -> "delayed by " + reason;
        };
    }

    // Patterns over Object: null, guards before the general case, multi-pattern labels, arrays.
    static String classify(Object o) {
        return switch (o) {
            case null -> "null, and no NullPointerException";
            case Integer i when i < 0 -> "negative int " + i;
            case Integer i -> "int " + i;
            case Long _, Short _, Byte _ -> "some other integral box";
            case String s when s.isBlank() -> "blank string";
            case String s -> "string of length " + s.length();
            case int[] numbers -> "int[] of length " + numbers.length;
            case Event e -> "event: " + describe(e);
            default -> "something else: " + o.getClass().getSimpleName();
        };
    }

    // Constant labels still work, now with an explicit answer for null.
    static String grade(String code) {
        return switch (code) {
            case "A", "B" -> "pass";
            case "F" -> "fail";
            case null, default -> "unknown";
        };
    }

    // Without case null, a null selector throws, exactly as switch always did.
    static int legacyLength(Object o) {
        return switch (o) {
            case String s -> s.length();
            default -> -1;
        };
    }

    static int parseOrZero(String s) {
        try {
            return Integer.parseInt(s);
        } catch (NumberFormatException _) {       // unnamed variable: only the failure matters
            return 0;
        }
    }

    public static void main(String[] args) {
        var events = new Event[] {Status.CREATED, Status.SHIPPED, new Delivered("Ada", 23),
                new Delivered("Linus", 14), new Delayed("snow", 5), new Delayed("customs", 72)};
        for (Event e : events) System.out.println(describe(e));
        System.out.println();

        var things = Arrays.asList(null, -7, 42, 42L, (short) 3, "   ", "hello",
                new int[] {1, 2, 3}, new Delayed("customs", 72), 3.14);
        for (Object o : things) System.out.println(classify(o));
        System.out.println();

        System.out.println(grade("A") + " " + grade("F") + " " + grade("Z") + " " + grade(null));
        try {
            legacyLength(null);
        } catch (NullPointerException e) {
            System.out.println("legacyLength(null) threw " + e.getClass().getSimpleName());
        }
        System.out.println(parseOrZero("12") + " " + parseOrZero("twelve"));
    }
}
```

Output:

```text output
order created
on its way
left with Ada at night
delivered to Linus
delayed by snow
stuck for 3 days

null, and no NullPointerException
negative int -7
int 42
some other integral box
some other integral box
blank string
string of length 5
int[] of length 3
event: stuck for 3 days
something else: Double

pass fail unknown unknown
legacyLength(null) threw NullPointerException
12 0
```

Now break the ordering rules on purpose. Each of these labels can never be reached, and javac refuses all three:

```java compile-fail
public class Dominated {
    static String kind(Object o) {
        return switch (o) {
            case CharSequence cs -> "some text";            // every String is a CharSequence...
            case String s -> "a string";
            default -> "other";
        };
    }

    static String size(Integer n) {
        return switch (n) {
            case Integer i -> "any number";                 // ...this pattern already takes 0...
            case 0 -> "zero";
        };
    }

    static String word(String s) {
        return switch (s) {
            case String t -> "a word";                      // ...and unguarded beats guarded
            case String t when t.isEmpty() -> "nothing";
        };
    }

    public static void main(String[] args) {
        System.out.println(kind("hi") + size(0) + word(""));
    }
}
```

```text compile-error
Dominated.java:5: error: this case label is dominated by a preceding case label
            case String s -> "a string";
                 ^
Dominated.java:13: error: this case label is dominated by a preceding case label
            case 0 -> "zero";
                 ^
Dominated.java:20: error: this case label is dominated by a preceding case label
            case String t when t.isEmpty() -> "nothing";
                 ^
3 errors
```

## How it works

* **First match wins, so the compiler checks reachability.** A label is *dominated* when an earlier label matches everything it would match: a supertype pattern before a subtype pattern, a type pattern before a constant of that type, an unguarded pattern before a guarded one of the same type. The fix is always the same: specific first, general last. A guarded pattern dominates nothing, because the compiler cannot know what the guard will say.
* **Guards do not count for exhaustiveness.** `describe` needs the unguarded `case Delayed(var reason, _)` even though the guarded one comes first. Delete it and javac reports that the switch does not cover all input values.
* **`null` is opt-in.** A `switch` without `case null` still throws `NullPointerException` on a `null` selector, so old code keeps its behavior. `case null` can stand alone or be merged with `default` as `case null, default`, but not with a type pattern (`case null, String s` is rejected as an invalid label combination).
* **Qualified enum constants** are what lets an enum live inside a sealed hierarchy. With an `Event` selector, a bare `CREATED` is "cannot find symbol"; `Status.CREATED` works and counts toward exhaustiveness. Since Java 21 you may qualify constants even when the selector is the enum itself; compiled with `--release 20`, `case Color.RED` is rejected with "an enum switch case label must be the unqualified name of an enumeration constant".
* **`_` means "I don't care".** In a record pattern it skips a component (`Delayed(_, var hours)`), as a type pattern it tests without binding (`Long _`), and only labels with no bindings may be combined, which is why `case Long _, Short _, Byte _` is legal and `case Long l, Short s` is not. The same `_` works for unused catch parameters, lambda parameters and loop variables.
* **`yield`** returns a value from a block inside a switch *expression*. `return` would leave the enclosing method, so it is not allowed there.
* **Under the hood** javac compiles a pattern switch to an `invokedynamic` call to `java.lang.runtime.SwitchBootstraps.typeSwitch`, which returns the index of the first label whose type matches. When a guard fails, the generated code calls it again with a restart index, so labels are still tried strictly in order.

## Gotchas

* **`default` silences exhaustiveness.** On a sealed type, a `default` branch means a new variant compiles without complaint. List the cases instead (see [040](040-algebraic-data-types.md)).
* **Old style statements are exempt.** A `switch` *statement* that uses only constant labels, `case RED:` style, does not have to be exhaustive. The moment it uses a pattern or `case null`, it does.
* **Generic records need care.** `case Box<String>(var s)` on a `Box<?>` selector does not compile (javac: `Box<CAP#1> cannot be safely cast to Box<String>`), because erasure means the runtime could never check it. Match `Box<?>(var s)` or `Box(String s)` and let the component pattern do the type test.
* **Primitive selectors are still limited** to `int`, `char`, `short`, `byte` and their boxes in Java 25. Switching on `long`, `double` and `boolean`, and primitive type patterns, are a preview in Java 27: see [047](047-primitive-patterns.md).
* **Readability has a ceiling.** A switch with eight guarded record patterns is still eight business rules in one method. If the guards start repeating, name them as methods.

## When to use it (and when not to)

Use pattern switches whenever you branch on *what kind of thing* you have: sealed hierarchies, parse results, messages, events, `Object` coming out of a heterogeneous source. Make them expressions, leave out `default` on sealed types, and let the compiler keep the list complete.

Keep virtual methods when the behavior belongs to the type and every new type must bring its own (a plugin's `render()`), and keep plain `if` when there is one interesting case and everything else is "do nothing".

## Related

* [040 · Algebraic Data Types with Sealed Interfaces and Records](040-algebraic-data-types.md)
* [042 · Symbolic Differentiation with Record Patterns](042-record-patterns-simplifier.md), nested patterns at full strength
* [047 · Primitive Types in Patterns (Preview)](047-primitive-patterns.md)
* [019 · The Visitor Pattern Is Dead, Long Live Sealed Types](../02-patterns/019-visitor-vs-sealed.md)

## Sources

* [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441) and [JEP 440: Record Patterns](https://openjdk.org/jeps/440)
* [JEP 456: Unnamed Variables & Patterns](https://openjdk.org/jeps/456)
* [JEP 361: Switch Expressions](https://openjdk.org/jeps/361), where `yield` comes from
* [JLS §14.11.1: Switch Blocks](https://docs.oracle.com/javase/specs/jls/se25/html/jls-14.html#jls-14.11.1), including the dominance rules
* [`SwitchBootstraps` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/runtime/SwitchBootstraps.html)
