# 015 · Enums with Behavior: Strategy Pattern without Classes

> Five operators, five strategy classes, one factory and a registry? Or one enum, where the dispatch table *is* the type.

**Since:** Java 10 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Beginner · **Verdict:** ✅ Production

## The problem

The textbook Strategy pattern for a calculator looks like this: an `Operation` interface, a `Plus` class, a `Minus` class, a `Times` class, and then a `Map<String, Operation>` somewhere that somebody has to remember to update. The set of operations is fixed and known at compile time, yet nothing in the code says so. Nothing stops a second `Plus` instance, and a `switch` over the operations needs a `default` branch "just in case".

## The trick

When the set of strategies is **closed**, make each strategy an enum constant. Java enums are full classes: they can implement interfaces, take constructor arguments and carry behavior. There are two ways to attach the behavior, and both are in Joshua Bloch's *Effective Java*:

```java
// 1. Pass a lambda to the constructor (Item 42). Short and sweet for one-liners.
enum Operation implements DoubleBinaryOperator {
    PLUS("+", (a, b) -> a + b),
    TIMES("*", (a, b) -> a * b);
    ...
}

// 2. Give a constant its own class body overriding an abstract method (Item 34).
enum PayType {
    WEEKDAY { int overtimeMinutes(int worked) { return Math.max(0, worked - SHIFT_MINUTES); } },
    WEEKEND { int overtimeMinutes(int worked) { return worked; } };
    abstract int overtimeMinutes(int worked);
}
```

Around them sit three companions that make enums fast and pleasant: a static lookup `Map` built once from `values()`, `EnumSet` for sets of constants and `EnumMap` for per-constant data.

## Full example

```java run
import java.time.DayOfWeek;
import java.util.*;
import java.util.function.DoubleBinaryOperator;
import java.util.stream.*;
import static java.time.DayOfWeek.*;

public class EnumStrategyDemo {

    // Style 1: each constant receives its behavior as a constructor argument.
    enum Operation implements DoubleBinaryOperator {
        PLUS("+", (a, b) -> a + b),
        MINUS("-", (a, b) -> a - b),
        TIMES("*", (a, b) -> a * b),
        DIVIDE("/", (a, b) -> a / b),
        POWER("^", Math::pow);

        private final String symbol;
        private final DoubleBinaryOperator op;

        Operation(String symbol, DoubleBinaryOperator op) {
            this.symbol = symbol;
            this.op = op;
        }

        @Override public double applyAsDouble(double a, double b) { return op.applyAsDouble(a, b); }

        // Built once, after every constant exists.
        private static final Map<String, Operation> BY_SYMBOL =
                Stream.of(values()).collect(Collectors.toUnmodifiableMap(o -> o.symbol, o -> o));

        static Optional<Operation> fromSymbol(String s) { return Optional.ofNullable(BY_SYMBOL.get(s)); }
    }

    // A tiny reverse Polish calculator: the enum is the whole dispatch table.
    static double rpn(String expression, Map<Operation, Integer> usage) {
        Deque<Double> stack = new ArrayDeque<>();
        for (String token : expression.split(" ")) {
            Optional<Operation> op = Operation.fromSymbol(token);
            if (op.isPresent()) {
                double right = stack.pop(), left = stack.pop();
                stack.push(op.get().applyAsDouble(left, right));
                usage.merge(op.get(), 1, Integer::sum);
            } else {
                stack.push(Double.parseDouble(token));
            }
        }
        return stack.pop();
    }

    // Style 2: constant-specific class bodies, when the behavior needs a real method.
    enum PayType {
        WEEKDAY {
            int overtimeMinutes(int worked) { return Math.max(0, worked - SHIFT_MINUTES); }
        },
        WEEKEND {
            int overtimeMinutes(int worked) { return worked; }   // every weekend minute counts
        };

        static final int SHIFT_MINUTES = 8 * 60;

        abstract int overtimeMinutes(int worked);

        int payCents(int worked, int centsPerMinute) {
            return worked * centsPerMinute + overtimeMinutes(worked) * centsPerMinute / 2;
        }
    }

    // EnumSet is a bit vector, EnumMap an array indexed by ordinal. Both keep declaration order.
    static final Set<DayOfWeek> WEEKEND_DAYS = EnumSet.of(SATURDAY, SUNDAY);
    static final Map<DayOfWeek, PayType> PAY_TYPE = new EnumMap<>(DayOfWeek.class);
    static {
        for (DayOfWeek day : DayOfWeek.values())
            PAY_TYPE.put(day, WEEKEND_DAYS.contains(day) ? PayType.WEEKEND : PayType.WEEKDAY);
    }

    public static void main(String[] args) {
        for (Operation op : Operation.values())
            System.out.println(op + "(6, 3) = " + op.applyAsDouble(6, 3));

        var usage = new EnumMap<Operation, Integer>(Operation.class);
        System.out.println("3 4 + 2 * 2 ^ = " + rpn("3 4 + 2 * 2 ^", usage));
        System.out.println("10 4 - 3 *    = " + rpn("10 4 - 3 *", usage));
        System.out.println("usage: " + usage);
        System.out.println("'%' is " + Operation.fromSymbol("%"));

        // Payroll at 50 cents a minute: 3 hours on Saturday, 9.5 hours on Friday.
        var shifts = new EnumMap<DayOfWeek, Integer>(DayOfWeek.class);
        shifts.put(SATURDAY, 180);
        shifts.put(FRIDAY, 570);
        shifts.forEach((day, minutes) -> {
            PayType type = PAY_TYPE.get(day);
            System.out.println(day + " is " + type + ": " + minutes + " min, overtime "
                    + type.overtimeMinutes(minutes) + " min, pay " + type.payCents(minutes, 50) + " cents");
        });
        System.out.println("weekdays: " + EnumSet.complementOf(EnumSet.copyOf(WEEKEND_DAYS)));

        // A constant with a body is an anonymous subclass; a lambda constant is not.
        System.out.println(PayType.WEEKDAY.getClass() + " vs " + PayType.WEEKDAY.getDeclaringClass());
        System.out.println(Operation.PLUS.getClass() + " vs " + Operation.PLUS.getDeclaringClass());

        // values() hands out a fresh copy on every call.
        Operation[] first = Operation.values();
        Operation[] second = Operation.values();
        first[0] = null;
        System.out.println("same array? " + (first == second) + ", second[0] is still " + second[0]);
    }
}
```

Output:

```text output
PLUS(6, 3) = 9.0
MINUS(6, 3) = 3.0
TIMES(6, 3) = 18.0
DIVIDE(6, 3) = 2.0
POWER(6, 3) = 216.0
3 4 + 2 * 2 ^ = 196.0
10 4 - 3 *    = 18.0
usage: {PLUS=1, MINUS=1, TIMES=2, POWER=1}
'%' is Optional.empty
FRIDAY is WEEKDAY: 570 min, overtime 90 min, pay 30750 cents
SATURDAY is WEEKEND: 180 min, overtime 180 min, pay 13500 cents
weekdays: [MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY]
class EnumStrategyDemo$PayType$1 vs class EnumStrategyDemo$PayType
class EnumStrategyDemo$Operation vs class EnumStrategyDemo$Operation
same array? false, second[0] is still PLUS
```

And the trap everybody walks into once: registering each constant in the lookup map from its own constructor.

```java compile-fail
import java.util.*;

public class SelfRegistering {
    enum Operation {
        PLUS("+"), MINUS("-");

        private static final Map<String, Operation> BY_SYMBOL = new HashMap<>();

        Operation(String symbol) {
            BY_SYMBOL.put(symbol, this);
        }
    }

    public static void main(String[] args) {}
}
```

```text compile-error
SelfRegistering.java:10: error: illegal reference to static field from initializer
            BY_SYMBOL.put(symbol, this);
            ^
1 error
```

## How it works

* **Constants are created first.** An enum's constants are its first static fields, initialized in declaration order before any other static field. When the `PLUS` constructor runs, `BY_SYMBOL` is still `null`. javac knows this and rejects the self-registering constructor outright (JLS §8.9.2). The fix is the one in the example: build the map in a static field declared *after* the constants, from `values()`.
* **A lambda constant has no subclass.** `Operation.PLUS.getClass()` is `Operation` itself; the behavior lives in a field, and the symbol only matters for parsing. That keeps the enum small and makes each constant's behavior visible on its declaration line.
* **A constant with a body is an anonymous subclass.** The output shows `PayType$1` as the runtime class. This is why `getDeclaringClass()` exists: it always returns the enum type. `EnumSet.of` and `Enum.compareTo` rely on it, and the key type check inside `EnumMap` accepts a key whose class *or superclass* is the enum for exactly this reason. If you ever write `constant.getClass() == PayType.class`, it will be `false` for constants with bodies.
* **The `abstract` method makes the compiler your checklist.** Add a `HOLIDAY` constant without an `overtimeMinutes` body and the enum no longer compiles. With a lambda constructor, a missing lambda is a missing constructor argument: also a compile error.
* **`EnumMap` and `EnumSet` are the cheapest collections in the JDK for enum keys.** `EnumSet` stores up to 64 constants in a single `long`, so `contains` is a bit test. `EnumMap` is an array indexed by `ordinal()`. Both iterate in declaration order, whatever the insertion order: the calculator first used `PLUS`, `TIMES`, `POWER` and only then `MINUS`, yet `usage` printed `{PLUS=1, MINUS=1, TIMES=2, POWER=1}`, and the shifts came out Friday first although Saturday was put first. `DIVIDE` is simply absent, because `EnumMap` only holds the keys you put.
* **`values()` clones.** The JLS only promises an array of the constants; the compiler implements it as `$VALUES.clone()` so that nobody can corrupt the enum by writing into the array. Setting `first[0] = null` did not affect `second`, whose first element is still `PLUS`. The price is an allocation per call, so cache the result (or use the `Map`) on hot paths.

## Gotchas

* **No constant-specific types.** You cannot write `STRING<String>` and `INTEGER<Integer>` in one enum and have `get()` return the right type per constant. JEP 301 (*Enhanced Enums*) proposed generic enums and sharper typing for constants, and its status is **Closed / Withdrawn**. Use a sealed interface of records, or a class with typed `static final` instances, when each strategy needs its own type.
* **Methods declared only inside a constant body are invisible from outside**, for the same reason: the static type of `PayType.WEEKEND` is `PayType`, not the anonymous subclass.
* **`ordinal()` is not an id.** It changes when someone reorders the constants. Never persist it; store `name()` or an explicit code instead. `EnumMap` uses ordinals internally, which is fine because it never outlives the running program.
* **Enums are singletons forever.** No per-request state in an enum constant, and anything a constant references stays reachable for the lifetime of its class loader.
* **`valueOf` throws** `IllegalArgumentException` for unknown names. Wrap user input in a lookup that returns `Optional`, as `fromSymbol` does.

## When to use it (and when not to)

Use an enum strategy whenever the set of behaviors is closed and owned by you: operators, pricing tiers, file formats, retry policies, payroll rules. Prefer the lambda constructor for one-liners and the constant body for anything with several lines or several methods. Prefer a `switch` expression over the enum when the behavior belongs to *another* class and you do not want the enum to know about it.

Do not use it when third parties need to add strategies (plugins, customer-specific rules). An enum is closed by design; use a plain interface plus `ServiceLoader` or dependency injection there.

## Related

* [016 · State Machines with Enums and Sealed Types](016-state-machines.md), where each constant knows its successor
* [019 · The Visitor Pattern Is Dead, Long Live Sealed Types](019-visitor-vs-sealed.md), for closed hierarchies that need different data per case
* [041 · Pattern Matching for switch: The Complete Toolkit](../05-modern-language/041-switch-pattern-matching.md)
* [094 · Bit Twiddling Hacks](../10-jvm-performance/094-bit-twiddling.md), the bit vector inside `EnumSet`

## Sources

* Joshua Bloch, *Effective Java*, 3rd edition, Items 34 (enums with constant-specific bodies), 36 (`EnumSet`), 37 (`EnumMap`) and 42 (lambdas in enum constructors)
* [JLS §8.9: Enum Classes](https://docs.oracle.com/javase/specs/jls/se25/html/jls-8.html#jls-8.9)
* [`java.util.EnumMap` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/EnumMap.html) and [`java.util.EnumSet`](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/EnumSet.html)
* [JEP 301: Enhanced Enums](https://openjdk.org/jeps/301), Closed / Withdrawn
