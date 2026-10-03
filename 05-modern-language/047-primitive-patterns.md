# 047 · Primitive Types in Patterns (Preview)

> `if (i instanceof byte b)` is a range check that cannot be written wrong, and `switch` finally takes a `long`. It is in its fifth preview in Java 27, so treat the syntax as a loan, not a gift.

**Since:** Java 27 (preview, JEP 532) · **Category:** [Modern Language Features](../README.md#modern-language-features) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Java has always converted between primitives quietly, and quietly is the problem:

```java
int i = 1000;
byte b = (byte) i;              // compiles, silently becomes -24
float f = 16_777_217;           // compiles, silently becomes 1.6777216E7
```

The safe version is a hand-written range check that every project reimplements:

```java
if (i >= Byte.MIN_VALUE && i <= Byte.MAX_VALUE) {
    byte ok = (byte) i;
}
```

Pattern matching never helped, because primitives were second class citizens in it:

* `switch` accepts `byte`, `short`, `char` and `int`, but not `long`, `float`, `double` or `boolean`.
* `instanceof` only tests reference types.
* A record pattern must name the component type exactly. For `record JsonNumber(double value)`, you can write `JsonNumber(double d)` and then cast by hand, but not `JsonNumber(int i)`.

## The trick

JEP 532 asks one question everywhere: **would this conversion lose information?** If not, the pattern matches and you get the converted value. If so, it simply does not match and you handle the value in another branch. Four things follow from that:

| What | Example |
|---|---|
| `switch` on every primitive type | `switch (someLong) { case 10_000_000_000L -> ...; case long n -> ... }` |
| `instanceof` as an exactness test | `if (i instanceof byte b) { ... }` |
| Narrowing inside record patterns | `case JsonNumber(int i) -> ...` matches only when the `double` is a whole number that fits an `int` |
| Primitive patterns over boxes | `case int i` on an `Object` matches an `Integer` |

It is a preview language feature, so it needs `--enable-preview`, and it is tied to one JDK release. Everything below was compiled and run on JDK 27 (build 27+35), except the one block that says otherwise.

## Full example

```java preview
import java.util.*;

public class PrimitivePatterns {

    // 1. switch on long, double and boolean.
    static String size(long bytes) {
        return switch (bytes) {
            case 0L -> "empty";
            case 10_000_000_000L -> "ten billion bytes exactly";
            case long n when n < 0 -> "negative: " + n;
            case long n when n < 1_000_000 -> n + " bytes";
            case long n -> n + " bytes, a lot";
        };
    }

    static String sign(double d) {
        return switch (d) {
            case 0.0 -> "positive zero";
            case -0.0 -> "negative zero";
            case Double.NaN -> "not a number";
            case double x when x < 0 -> "negative";
            case double _ -> "positive";
        };
    }

    static String verdict(boolean ok) {
        return switch (ok) {
            case true -> "pass";
            case false -> "fail";
        };
    }

    // 2. instanceof as an exactness test replaces hand-written range checks.
    static String pack(int value) {
        if (value instanceof byte b) return "1 byte : " + b;
        if (value instanceof short s) return "2 bytes: " + s;
        return "4 bytes: " + value;
    }

    static String fits(int value) {
        var types = new ArrayList<String>();
        if (value instanceof byte) types.add("byte");
        if (value instanceof short) types.add("short");
        if (value instanceof char) types.add("char");
        if (value instanceof float) types.add("float");
        return value + " fits in " + (types.isEmpty() ? "none of them" : String.join(", ", types));
    }

    // 3. For floating point, "exact" means nothing is lost, not even a sign.
    static String exactness(double d) {
        return "%-6s int=%-5b long=%-5b float=%b"
                .formatted(d, d instanceof int, d instanceof long, d instanceof float);
    }

    // 4. Record patterns can narrow a component, and only match when nothing is lost.
    record JsonNumber(double value) {}

    static String describe(JsonNumber n) {
        return switch (n) {
            case JsonNumber(int i) -> "int " + i;
            case JsonNumber(long l) -> "long " + l;
            case JsonNumber(double d) -> "double " + d;
        };
    }

    // 5. Patterns see through boxes, but only the exact box.
    static String boxed(Object o) {
        return switch (o) {
            case int i -> "int " + i;
            case long l -> "long " + l;
            case double d -> "double " + d;
            default -> "something else: " + o.getClass().getSimpleName();
        };
    }

    public static void main(String[] args) {
        int big = 16_777_217;
        System.out.println("the old way: (byte) 1000 = " + (byte) 1000 + ", (float) 16777217 = " + (float) big);

        System.out.println("switch:");
        for (long n : new long[] {0, 10_000_000_000L, -5, 999, 4_000_000_000L}) {
            System.out.println("  " + size(n));
        }
        for (double d : new double[] {0.0, -0.0, Double.NaN, -2.5, 2.5}) {
            System.out.println("  " + d + " is " + sign(d));
        }
        System.out.println("  " + verdict(true) + " " + verdict(false));

        System.out.println("instanceof:");
        for (int v : new int[] {42, 1000, -1, 70_000, 5_000_000}) {
            System.out.println("  " + pack(v));
        }
        for (int v : new int[] {42, 1000, -1, 70_000, 16_777_217}) {
            System.out.println("  " + fits(v));
        }
        for (double d : new double[] {3.0, 0.5, 0.1, -0.0, Double.NaN, 1e10}) {
            System.out.println("  " + exactness(d));
        }

        System.out.println("record patterns:");
        for (double d : new double[] {30, 30.5, 1e10}) {
            System.out.println("  " + describe(new JsonNumber(d)));
        }

        System.out.println("boxes:");
        for (Object o : new Object[] {42, 42L, 2.5, (byte) 7, 1.5f}) {
            System.out.println("  " + boxed(o));
        }
    }
}
```

Output:

```text output
the old way: (byte) 1000 = -24, (float) 16777217 = 1.6777216E7
switch:
  empty
  ten billion bytes exactly
  negative: -5
  999 bytes
  4000000000 bytes, a lot
  0.0 is positive zero
  -0.0 is negative zero
  NaN is not a number
  -2.5 is negative
  2.5 is positive
  pass fail
instanceof:
  1 byte : 42
  2 bytes: 1000
  1 byte : -1
  4 bytes: 70000
  4 bytes: 5000000
  42 fits in byte, short, char, float
  1000 fits in short, char, float
  -1 fits in byte, short, float
  70000 fits in float
  16777217 fits in none of them
  3.0    int=true  long=true  float=true
  0.5    int=false long=false float=true
  0.1    int=false long=false float=false
  -0.0   int=false long=false float=true
  NaN    int=false long=false float=true
  1.0E10 int=false long=true  float=true
record patterns:
  int 30
  double 30.5
  long 10000000000
boxes:
  int 42
  long 42
  double 2.5
  something else: Byte
  something else: Float
```

Compile and run it by hand, with JDK 27 on the `PATH`, without and with the preview flag:

```shell
$ javac PrimitivePatterns.java
$ javac --enable-preview --release 27 PrimitivePatterns.java
$ java PrimitivePatterns
$ java --enable-preview PrimitivePatterns | head -2
```

```text
PrimitivePatterns.java:7: error: primitive patterns are a preview feature and are disabled by default.
        return switch (bytes) {
                      ^
  (use --enable-preview to enable primitive patterns)
1 error
Note: PrimitivePatterns.java uses preview features of Java SE 27.
Note: Recompile with -Xlint:preview for details.
Error: LinkageError occurred while loading main class PrimitivePatterns
	java.lang.UnsupportedClassVersionError: Preview features are not enabled for PrimitivePatterns (class file version 71.65535). Try running with '--enable-preview'
the old way: (byte) 1000 = -24, (float) 16777217 = 1.6777216E7
switch:
```

The same feature has rules, and javac enforces them. Three typical mistakes in one file:

```java compile-fail jdk=27 args="--enable-preview --release 27"
public class PatternMistakes {
    static String a(long v) {
        return switch (v) { case 1 -> "one"; default -> "other"; };
    }

    static String b(boolean v) {
        return switch (v) { case true -> "t"; case false -> "f"; default -> "?"; };
    }

    static String c(int j) {
        return switch (j) { case float f -> "float"; case 16_777_216 -> "constant"; default -> "rest"; };
    }

    public static void main(String[] args) {}
}
```

```text compile-error
PatternMistakes.java:3: error: constant label of type int is not compatible with switch selector type long
        return switch (v) { case 1 -> "one"; default -> "other"; };
                                 ^
PatternMistakes.java:7: error: switch has both boolean values and a default label
        return switch (v) { case true -> "t"; case false -> "f"; default -> "?"; };
                                                                 ^
PatternMistakes.java:11: error: this case label is dominated by a preceding case label
        return switch (j) { case float f -> "float"; case 16_777_216 -> "constant"; default -> "rest"; };
                                                          ^
Note: PatternMistakes.java uses preview features of Java SE 27.
Note: Recompile with -Xlint:preview for details.
3 errors
```

The third error has a history. A Java 25 preview compiler accepts the same dominated label and even runs it, because JDK 26 (JEP 530) tightened the dominance checks:

```java preview jdk=25
public class DominatedOnJava25 {
    public static void main(String[] args) {
        int j = 16_777_216;
        System.out.println(switch (j) {
            case float f -> "float pattern " + f;
            case 16_777_216 -> "constant";
            default -> "rest";
        });
    }
}
```

```text output
float pattern 1.6777216E7
```

## How it works

* **Exact conversion.** A conversion is exact if no information is lost at run time. Some are exact for every value (`byte` to `int`, `int` to `double`, boxing), the JEP calls those *unconditionally exact*. Others depend on the value: `long` to `int` is checked with numerical equality, and `int` to `float` with representation equivalence. That is why `16_777_217` (2 to the power 24, plus 1) fails the `float` test, as the `fits` line shows: `float` has only 24 bits of mantissa. The JEP notes that the same value still passes the `double` test.
* **`instanceof T` and `instanceof T t`.** `instanceof` now means "is it safe to cast to this type" for primitives as well. `i instanceof byte` is the check, `i instanceof byte b` is check plus cast plus binding, in one expression.
* **Three rules changed for type patterns.** *Applicability* (is the pattern legal at all?) now allows any primitive pattern that a cast would allow, so `case double d` is legal on an `int` selector. *Unconditionality* (does it always match?) uses unconditional exactness. *Matching* means the value can be cast exactly, so a `JsonNumber(int i)` pattern rejects `30.5` and `1e10` and the next case picks them up.
* **Switch constants must have the selector's type.** On a `long`, `float` or `double` selector, constants must be `long`, `float` or `double` literals. `case 1` on a `long` is rejected by design: a `0` where you meant `0f` would hide a lossy conversion. javac says `constant label of type int is not compatible with switch selector type long`.
* **Booleans are exhaustive with `true` and `false`.** A `default` next to both is an error, and so is leaving one out. A switch *statement* on a `long`, `float`, `double` or `boolean` must be exhaustive as well, unlike one on `int`: `switch (v) { case 1L -> ... }` fails with `the switch statement does not cover all possible input values`.
* **Dominance now covers primitives.** On a `long` selector, `case long q` dominates a later `case int i`, and a pattern that is unconditional on the selector type dominates every later label. It also covers constants: `16_777_216` converts to `float` without loss, so a constant label after `case float f` on an `int` selector can never match and is an error on JDK 27. The same applies to unrelated interfaces: on an `A` selector, `case A _` followed by `case B _` is an error on JDK 27, which the JEP flags as a source incompatibility for old switches that were merely misleading.
* **Boxes.** `case int i` on an `Object` matches an `Integer` only. A boxed `Byte`, `Long` or `Float` is a different class, so `boxed((byte) 7)` and `boxed(1.5f)` fall through to `default`. A `Byte` selector is different: `switch (aByte) { case int p -> ... }` is exhaustive, because `byte` to `int` is unconditionally exact.

## Gotchas

* **Preview means preview.** Class files compiled with `--enable-preview` carry minor version 65535 and refuse to load on a JVM without the flag, as the third command in the shell block shows. They also only run on the exact feature release they were compiled for. Do not ship libraries that use it.
* **The rules moved between previews.** JEP 455 (JDK 23) introduced the feature, JEP 488 (24) and JEP 507 (25) repeated it, JEP 530 (26) changed the unconditional exactness definition and tightened dominance checks, and JEP 532 (27) previews it again without change. Code that compiled on a 25 preview can fail on 27.
* **Floating point has sharp corners.** On JDK 27, `-0.0 instanceof int` is `false` (`int` has no negative zero), `Double.NaN instanceof float` is `true`, and `0.1 instanceof float` is `false` because `0.1f` is a different number. `case 0.0` and `case -0.0` are separate labels, and `case Double.NaN` works. The JEP does not discuss zero and NaN, so check these edge cases on your JDK before relying on them.
* **No constant patterns yet.** `case Box(42)` is not valid. The JEP lists constant patterns as future work, enabled by this one.

## When to use it (and when not to)

Today: experiments, teaching, conference demos, and checking how your own parsers and decoders would read with it. The best use cases are decoders and protocol code (`pack`, bounded narrowing) and JSON-like data, where a `double` component may or may not be a whole number.

Not yet: production code, libraries, anything compiled on one JDK and run on another. When it is final, it will replace many hand-written range checks, and `switch` on `long` and `boolean` will finally be boring. Until then, `Math.toIntExact` and explicit range checks are the portable answer. For the sealed-record side of pattern matching, which is final and safe to use today, see [040 · Algebraic Data Types](040-algebraic-data-types.md).

## Related

* [040 · Algebraic Data Types with Sealed Interfaces and Records](040-algebraic-data-types.md)
* [041 · Pattern Matching for switch: The Complete Toolkit](041-switch-pattern-matching.md)
* [042 · Symbolic Differentiation with Record Patterns](042-record-patterns-simplifier.md)
* [058 · Floating-Point Betrayals](../07-puzzlers/058-floating-point.md), for why `0.1` is not a `float`

## Sources

* [JEP 532: Primitive Types in Patterns, instanceof, and switch (Fifth Preview)](https://openjdk.org/jeps/532)
* [JEP 530: Primitive Types in Patterns, instanceof, and switch (Fourth Preview)](https://openjdk.org/jeps/530)
* [JEP 455: Primitive Types in Patterns, instanceof, and switch (Preview)](https://openjdk.org/jeps/455)
* [JEP 12: Preview Features](https://openjdk.org/jeps/12)
