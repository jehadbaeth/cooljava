# 058 · Floating-Point Betrayals

> `0.1 + 0.2` is not `0.3`, `NaN` is unequal to itself until you box it, and zero has a sign. Twenty lines of arithmetic, at least a dozen ways to be wrong.

**Since:** Java 9 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

Every line below is ordinary Java that compiles without a warning. Before you scroll to the answer, write down what you think each line prints. Two of them are classics from Joshua Bloch and Neal Gafter's *Java Puzzlers*: line 3 is Puzzle 2, "Time for a Change", and line 17 is Puzzle 34, "Down for the Count".

```java run
import java.math.BigDecimal;
import java.util.*;

public class FloatingPoint {

    static void show(String label, Object value) {
        System.out.printf("%-38s %s%n", label, value);
    }

    public static void main(String[] args) {
        show(" 1. 0.1 + 0.2", 0.1 + 0.2);
        show(" 2. 0.1 + 0.2 == 0.3", 0.1 + 0.2 == 0.3);
        show(" 3. 2.00 - 1.10", 2.00 - 1.10);

        double nan = 0.0 / 0.0;
        show(" 4. nan == nan", nan == nan);
        show(" 5. Double.valueOf(nan).equals(nan)", Double.valueOf(nan).equals(nan));
        show(" 6. List.of(nan).contains(nan)", List.of(nan).contains(nan));

        show(" 7. -0.0 == 0.0", -0.0 == 0.0);
        show(" 8. Double.valueOf(-0.0).equals(0.0)", Double.valueOf(-0.0).equals(0.0));
        show(" 9. Math.min(-0.0, 0.0)", Math.min(-0.0, 0.0));
        show("10. 1 divided by -0.0", 1 / -0.0);

        show("11. new BigDecimal(0.1)", new BigDecimal(0.1));
        show("12. BigDecimal.valueOf(0.1)", BigDecimal.valueOf(0.1));

        BigDecimal two = new BigDecimal("2.0");
        BigDecimal twoPointZeroZero = new BigDecimal("2.00");
        show("13. 2.0 equals 2.00", two.equals(twoPointZeroZero));
        show("14. 2.0 compareTo 2.00", two.compareTo(twoPointZeroZero));
        show("15. HashSet of {2.0, 2.00}, size", new HashSet<>(List.of(two, twoPointZeroZero)).size());
        show("16. TreeSet of {2.0, 2.00}, size", new TreeSet<>(List.of(two, twoPointZeroZero)).size());

        final int START = 2_000_000_000;
        int count = 0;
        for (float f = START; f < START + 50; f++) {
            count++;
        }
        show("17. iterations of the float loop", count);

        show("18. (int) Double.NaN", (int) Double.NaN);
        show("19. (int) 1e20", (int) 1e20);
        show("20. (long) -1e20", (long) -1e20);
    }
}
```

Got your list? Good.

## The answer

```text output
 1. 0.1 + 0.2                          0.30000000000000004
 2. 0.1 + 0.2 == 0.3                   false
 3. 2.00 - 1.10                        0.8999999999999999
 4. nan == nan                         false
 5. Double.valueOf(nan).equals(nan)    true
 6. List.of(nan).contains(nan)         true
 7. -0.0 == 0.0                        true
 8. Double.valueOf(-0.0).equals(0.0)   false
 9. Math.min(-0.0, 0.0)                -0.0
10. 1 divided by -0.0                  -Infinity
11. new BigDecimal(0.1)                0.1000000000000000055511151231257827021181583404541015625
12. BigDecimal.valueOf(0.1)            0.1
13. 2.0 equals 2.00                    false
14. 2.0 compareTo 2.00                 0
15. HashSet of {2.0, 2.00}, size       2
16. TreeSet of {2.0, 2.00}, size       1
17. iterations of the float loop       0
18. (int) Double.NaN                   0
19. (int) 1e20                         2147483647
20. (long) -1e20                       -9223372036854775808
```

Lines 1 to 3 are the famous ones. The nastier traps are 5 and 8, where `equals` and `==` disagree in *opposite* directions, 9, where `Math.min` has an opinion about the sign of nothing, 13, where two equal numbers are not `equals`, and 17, where a loop silently runs zero times.

## Why

### Lines 1 to 3: decimal fractions do not exist in binary

A `double` is a 53-bit binary fraction times a power of two. `0.1` has no finite binary expansion (just as 1/3 has none in decimal), so the literal is rounded to the nearest representable value, which is slightly *above* 0.1. The same goes for `0.2`, and the two rounding errors add up to a sum that is one unit in the last place (ULP) above the double nearest to `0.3`. `Double.toString` prints the shortest decimal string that uniquely identifies the value, so you get to see the error: `0.30000000000000004`. Line 3 is the same story: `1.10` is stored a hair high, so the change from two dollars comes out a hair low.

### Lines 4 to 6: `==` says no, `equals` says yes

IEEE 754 defines NaN as unordered: every comparison involving it is `false`, including `nan == nan`. That makes `x != x` the oldest NaN test in the book. But `Double.equals` is specified differently: it compares the bit patterns from `doubleToLongBits`, which maps every NaN to one canonical pattern. That is a deliberate choice so that `equals` stays reflexive, and it is the only reason line 6 works: `List.contains` and `HashSet` call `equals`, never `==`.

### Lines 7 to 10: zero has a sign

IEEE 754 has two zeros. `-0.0 == 0.0` is `true` because the standard says they compare equal, but `Double.equals` once more compares bits, and the sign bit differs. `Math.min` is specified to treat negative zero as strictly smaller than positive zero, so it returns `-0.0`. The sign matters as soon as you divide by it: line 10 is negative infinity, while `1 / 0.0` would be positive infinity. A rounding that produces a tiny negative number which then underflows to `-0.0` can flip the sign of a later infinity.

### Lines 11 and 12: the constructor that remembers too much

`new BigDecimal(0.1)` is exact. Exactly what you gave it, that is: the double nearest to 0.1, all 55 significant digits of it. `BigDecimal.valueOf(0.1)` goes through `Double.toString(0.1)`, which yields `"0.1"`, and parses that. The Javadoc of the `double` constructor says outright that its results "can be somewhat unpredictable" and recommends the `String` constructor.

### Lines 13 to 16: BigDecimal equality includes the scale

A `BigDecimal` is an unscaled integer plus a scale: `2.0` is 20 with scale 1, `2.00` is 200 with scale 2. `equals` compares both, so they are not equal. `compareTo` compares numeric value and returns `0`. Hash-based collections use `equals` and `hashCode`, sorted ones use `compareTo`, so the same two numbers make a `HashSet` of size 2 and a `TreeSet` of size 1. `BigDecimal` is the textbook example of a class whose natural ordering is "inconsistent with equals", and its Javadoc says so.

### Line 17: a float loop counter that never starts

A `float` has 24 bits of precision. Near two billion, adjacent floats are 128 apart. In `f < START + 50` the right side is an `int`, `2000000050`, which is converted to `float` for the comparison and rounds to `2.0E9`. So is `f`. `2.0E9 < 2.0E9` is false and the loop body never runs. Change `START` to `1_999_999_900` and the loop never *ends* instead: `f` starts at the float below, `1999999872`, the bound still rounds to `2.0E9`, and `f++` adds less than half a ULP, so `f` never changes.

### Lines 18 to 20: casting NaN and giants

Narrowing a floating-point value to an integer type never throws. JLS §5.1.3 defines the result: NaN becomes `0`, and anything too large for the target type clamps to its `MAX_VALUE` or `MIN_VALUE`. So a sensor that reports NaN shows up as a perfectly plausible zero, and nobody gets an exception.

### Bonus: strictfp does nothing

Before Java 17, the JVM was allowed to use extended exponent ranges for intermediate results unless a class or method was marked `strictfp`. JEP 306 made every floating-point operation strict again, so the modifier is now a no-op, and javac tells you so:

```java
public strictfp class Strict {
    public static void main(String[] args) {
        System.out.println(0.1 + 0.2);
    }
}
```

```shell
$ javac Strict.java
```

```text
Strict.java:1: warning: [strictfp] as of release 17, all floating-point expressions are evaluated strictly and 'strictfp' is not required
public strictfp class Strict {
                ^
1 warning
```

The puzzles themselves are as old as Java 1.0. The example needs Java 9 only because of `List.of`.

## Gotchas

* **`stripTrailingZeros` is not a free fix.** It makes `2.0` and `2.00` equal, but it also turns `100` into `1E+2`. Use `toPlainString()` when you print the result.
* **`BigDecimal.ONE.divide(BigDecimal.valueOf(3))` throws** `ArithmeticException` ("Non-terminating decimal expansion"). Always pass a scale and a `RoundingMode`, or a `MathContext`.
* **`Math.round(-2.5)` is `-2`**, not `-3`, because it rounds half up (towards positive infinity). `Math.rint(2.5)` is `2.0` (half even). Know which one your accountant expects.
* **Summing in a loop drifts.** Adding `0.1` ten times in a `for` loop gives `0.9999999999999999`, while `DoubleStream.sum()` uses compensated summation and gives `1.0`. Two correct-looking implementations, two answers.
* **`Arrays.sort(double[])` uses `Double.compare`**, which orders `-0.0` before `0.0` and puts NaN last. It is a total order, unlike `<`.

## How to stay safe

* **Money is not a `double`.** Use `long` cents, or `BigDecimal` built from a `String` or with `BigDecimal.valueOf`, never `new BigDecimal(double)`.
* **Compare doubles with a tolerance** that fits the magnitude, for example `Math.abs(a - b) <= 1e-9 * Math.max(Math.abs(a), Math.abs(b))`, not with `==`.
* **Test for NaN with `Double.isNaN`**, and check `Double.isFinite` before casting a computed value to `int` or `long`.
* **Put `BigDecimal` keys in a `TreeMap` or `TreeSet`**, or normalize them (`setScale` with a fixed scale) before they go into a `HashMap`.
* **Loop with integers** and derive the floating-point value inside the loop: `double x = start + i * step`.
* **Delete `strictfp`** when you see it. It has been dead weight since Java 17.

## Related

* [059 · Integer Overflow and Arithmetic Surprises](059-integer-overflow.md), the integer side of the same coin
* [061 · Boxing and Overloading Traps](061-boxing-overloading.md), for more ways `==` and `equals` disagree
* [066 · The Element That Vanished from the HashSet](066-vanishing-hashset.md), on what broken `equals` does to collections

## Sources

* [JLS §4.2.3: Floating-Point Types, Formats, and Values](https://docs.oracle.com/javase/specs/jls/se25/html/jls-4.html#jls-4.2.3) and [JLS §5.1.3: Narrowing Primitive Conversion](https://docs.oracle.com/javase/specs/jls/se25/html/jls-5.html#jls-5.1.3)
* [`java.lang.Double` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Double.html), section "Floating-point Equality, Equivalence, and Comparison"
* [`java.math.BigDecimal` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/math/BigDecimal.html)
* [JEP 306: Restore Always-Strict Floating-Point Semantics](https://openjdk.org/jeps/306)
* Joshua Bloch and Neal Gafter, *Java Puzzlers: Traps, Pitfalls, and Corner Cases* (Addison-Wesley, 2005). The [book's site](http://www.javapuzzlers.com/) has the source code of every puzzle
