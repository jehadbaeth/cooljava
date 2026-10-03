# 059 · Integer Overflow and Arithmetic Surprises

> Java integers never throw on overflow. They wrap around in silence, and the absolute value of a number can be negative.

**Since:** Java 18 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

Seventeen expressions, no tricks with Unicode or reflection, just arithmetic. Guess each result before you scroll. Several are from Joshua Bloch and Neal Gafter's *Java Puzzlers*: line 2 is "Looper Meets the Wolfman" (Puzzle 33), line 4 is "Long Division" (Puzzle 3), line 5 is "It's Elementary" (Puzzle 4), line 12 is "Oddity" (Puzzle 1) and line 8 is the core of "The Last Laugh" (Puzzle 11). Division is spelled out in the labels for the output's sake; the code uses the real operator.

```java run
public class Overflow {

    static void show(String label, Object value) {
        System.out.printf("%-38s %s%n", label, value);
    }

    static boolean isOdd(int i) {
        return i % 2 == 1;
    }

    public static void main(String[] args) {
        show(" 1. Math.abs(Integer.MIN_VALUE)", Math.abs(Integer.MIN_VALUE));
        show(" 2. MIN_VALUE == -MIN_VALUE", Integer.MIN_VALUE == -Integer.MIN_VALUE);
        show(" 3. MIN_VALUE divided by -1", Integer.MIN_VALUE / -1);

        final long MICROS_PER_DAY = 24 * 60 * 60 * 1000 * 1000;
        final long MILLIS_PER_DAY = 24 * 60 * 60 * 1000;
        show(" 4. MICROS_PER_DAY divided by MILLIS", MICROS_PER_DAY / MILLIS_PER_DAY);
        show(" 5. 12345 + 5432l", 12345 + 5432l);

        short s = Short.MAX_VALUE;
        s += 1;
        show(" 6. short MAX_VALUE, then s += 1", s);
        byte b = 10;
        b *= 30;
        show(" 7. byte 10, then b *= 30", b);

        show(" 8. 'a' + 'b'", 'a' + 'b');
        show(" 9. \"\" + 'a' + 'b'", "" + 'a' + 'b');
        char c = 'a';
        c += 1;
        show("10. char 'a', then c += 1", c);

        show("11. -7 % 3", -7 % 3);
        show("12. isOdd(-3)", isOdd(-3));
        show("13. Math.floorMod(-7, 3)", Math.floorMod(-7, 3));

        int low = 1_500_000_000;
        int high = 2_000_000_000;
        show("14. (low + high) divided by 2", (low + high) / 2);
        show("15. (low + high) >>> 1", (low + high) >>> 1);

        double half = 1 / 2;
        show("16. double half = 1 divided by 2", half);
        show("17. 7 divided by 2 * 2.0", 7 / 2 * 2.0);
    }
}
```

## The answer

```text output
 1. Math.abs(Integer.MIN_VALUE)        -2147483648
 2. MIN_VALUE == -MIN_VALUE            true
 3. MIN_VALUE divided by -1            -2147483648
 4. MICROS_PER_DAY divided by MILLIS   5
 5. 12345 + 5432l                      17777
 6. short MAX_VALUE, then s += 1       -32768
 7. byte 10, then b *= 30              44
 8. 'a' + 'b'                          195
 9. "" + 'a' + 'b'                     ab
10. char 'a', then c += 1              b
11. -7 % 3                             -1
12. isOdd(-3)                          false
13. Math.floorMod(-7, 3)               2
14. (low + high) divided by 2          -397483648
15. (low + high) >>> 1                 1750000000
16. double half = 1 divided by 2       0.0
17. 7 divided by 2 * 2.0               6.0
```

## Why

### Lines 1 to 3: the number that is its own negative

`int` is 32-bit two's complement, so its range is lopsided: `-2147483648` to `2147483647`. The negation of `MIN_VALUE` would be `2147483648`, which does not fit, so it wraps right back to `MIN_VALUE`. That makes `MIN_VALUE` the only nonzero `int` equal to its own negation (line 2), and `Math.abs` simply returns it unchanged (line 1, and its Javadoc admits it). Line 3 is the same overflow through division. Many CPUs trap on that particular division; the JLS (§15.17.2) instead defines the result as `MIN_VALUE`, so Java quietly gives you a negative quotient of two negative numbers. The classic production bug is `Math.abs(key.hashCode()) % buckets`, which goes negative for exactly one hash code in four billion.

### Line 4: the long that was an int all along

`24 * 60 * 60 * 1000 * 1000` is evaluated entirely in `int` arithmetic, because every operand is an `int` literal. The product, 86,400,000,000, overflows long before it is widened to `long` for the assignment: it wraps to 500,654,080, and that divided by 86,400,000 is 5. The target type of an assignment never influences how the right-hand side is computed. Make the first factor a `long` (`24L * 60 ...`) and the whole chain is computed in 64 bits.

### Line 5: an `l` that looks like a `1`

`5432l` is a `long` literal with a lowercase L, not `54321`. 12345 + 5432 is 17777. Always write `L`. Checkstyle has a rule for it, and so does every code reviewer who has seen this puzzle once.

### Lines 6 and 7: compound assignment hides a cast

JLS §15.26.2 defines `s += 1` as `s = (short) (s + 1)`. The cast is invisible and narrowing, so `Short.MAX_VALUE + 1` wraps to `Short.MIN_VALUE`, and `10 * 30`, which is 300, loses its high bits and becomes `300 - 256`, which is 44. The long form, without the hidden cast, does not even compile. That pair (`x += i` legal, `x = x + i` rejected) is the whole of Bloch and Gafter's "Tweedledum" (Puzzle 9):

```java compile-fail
public class Narrowing {
    public static void main(String[] args) {
        short s = 1;
        s = s + 1;
    }
}
```

```text compile-error
Narrowing.java:4: error: incompatible types: possible lossy conversion from int to short
        s = s + 1;
              ^
1 error
```

### Lines 8 to 10: char is a number

Binary `+` concatenates only if one operand is a `String`. Two `char`s are promoted to `int` and added: `'a'` is 97 and `'b'` is 98. Line 9 works because `+` is left-associative: `"" + 'a'` is a `String` first. Line 10 is a compound assignment again, so the hidden `(char)` cast brings the `int` 98 back to `'b'`.

### Lines 11 to 13: `%` is remainder, not modulo

Java's `%` takes the sign of the dividend, so `-7 % 3` is `-1`, and `isOdd` with `i % 2 == 1` is wrong for every negative odd number. Test `i % 2 != 0` instead. `Math.floorMod` returns a result with the sign of the divisor, which is what you want for clock arithmetic, ring buffers and bucket indexes.

### Lines 14 and 15: the bug in nearly every binary search

`low + high` overflows when both are above a billion, and the "midpoint" goes negative. This exact line sat in the binary search that Jon Bentley proved correct in *Programming Pearls*, and in the `java.util.Arrays.binarySearch` that Joshua Bloch wrote for the JDK, where it lay in wait for about nine years until arrays got big enough. Bloch wrote it up in 2006 as "Nearly All Binary Searches and Mergesorts are Broken". The fixes are `low + (high - low) / 2` or `(low + high) >>> 1`: the unsigned shift reinterprets the overflowed sum as an unsigned 32-bit number, which it correctly is, and halves it.

### Lines 16 and 17: integer division happens before anyone asks for a double

`1 / 2` is `0`, computed in `int`, and only then widened to `0.0`. In line 17, `7 / 2` is `3` before the `2.0` ever joins in. Same rule as line 4: the destination type does not travel back into the expression.

## The safe versions

The `Math.*Exact` family (Java 8, with `absExact` added in 15 and `divideExact` in 18) throws instead of wrapping:

```java run
import java.util.function.IntSupplier;

public class ExactArithmetic {

    static void attempt(String label, IntSupplier computation) {
        try {
            System.out.printf("%-38s %d%n", label, computation.getAsInt());
        } catch (ArithmeticException e) {
            System.out.printf("%-38s %s: %s%n", label, e.getClass().getSimpleName(), e.getMessage());
        }
    }

    public static void main(String[] args) {
        attempt("Math.absExact(MIN_VALUE)", () -> Math.absExact(Integer.MIN_VALUE));
        attempt("Math.divideExact(MIN_VALUE, -1)", () -> Math.divideExact(Integer.MIN_VALUE, -1));
        attempt("Math.addExact(MAX_VALUE, 1)", () -> Math.addExact(Integer.MAX_VALUE, 1));
        attempt("Math.multiplyExact(86_400_000, 1000)", () -> Math.multiplyExact(86_400_000, 1000));
        attempt("Math.toIntExact(3_000_000_000L)", () -> Math.toIntExact(3_000_000_000L));
        attempt("Math.floorMod(-7, 3)", () -> Math.floorMod(-7, 3));

        long microsPerDay = 24L * 60 * 60 * 1000 * 1000;
        System.out.printf("%-38s %d%n", "24L * 60 * 60 * 1000 * 1000", microsPerDay);
    }
}
```

```text output
Math.absExact(MIN_VALUE)               ArithmeticException: Overflow to represent absolute value of Integer.MIN_VALUE
Math.divideExact(MIN_VALUE, -1)        ArithmeticException: integer overflow
Math.addExact(MAX_VALUE, 1)            ArithmeticException: integer overflow
Math.multiplyExact(86_400_000, 1000)   ArithmeticException: integer overflow
Math.toIntExact(3_000_000_000L)        ArithmeticException: integer overflow
Math.floorMod(-7, 3)                   2
24L * 60 * 60 * 1000 * 1000            86400000000
```

## Gotchas

* **`Math.abs` on `long` has the same hole** at `Long.MIN_VALUE`. `Math.absExact(long)` exists too.
* **Overflow also hides in `compareTo`.** `return a - b;` as a comparator is wrong when the values have opposite signs and large magnitudes. Use `Integer.compare(a, b)`.
* **`(byte) 200` is `-56`.** Bytes are signed. Use `Byte.toUnsignedInt` when reading binary data.
* **Shifts are masked.** `1 << 32` is `1`, not `0`, because only the low five bits of the shift distance count for an `int` (six for a `long`).
* **`Integer.parseInt("2147483648")` throws** `NumberFormatException`, but `Integer.parseInt("-2147483648")` is fine. The asymmetry is the same lopsided range.

## How to stay safe

* Use `Math.addExact`, `multiplyExact`, `toIntExact` and friends wherever a value comes from outside (sizes, counts, money in cents, durations). Silent wraparound is never the behavior you wanted.
* Put an `L` on the *first* literal of any constant expression that can exceed two billion, and use uppercase `L` always.
* Use `Math.floorMod` for indexes and `x % 2 != 0` for oddness.
* Compute midpoints as `low + (high - low) / 2` or `(low + high) >>> 1`.
* Write `1.0 / 2` or cast one operand when you mean floating-point division.
* Turn on static analysis. Error Prone flags `Math.abs` results that can be negative, `int` math assigned to a `long`, and lowercase `l` suffixes; SpotBugs catches the first two as well.

## Related

* [058 · Floating-Point Betrayals](058-floating-point.md), for when the numbers have a fractional part
* [061 · Boxing and Overloading Traps](061-boxing-overloading.md), for more type promotion surprises
* [094 · Bit Twiddling Hacks](../10-jvm-performance/094-bit-twiddling.md), where wraparound is a feature

## Sources

* [JLS §15.17.2: Division Operator /](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.17.2) and [JLS §15.26.2: Compound Assignment Operators](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.26.2)
* [`java.lang.Math` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Math.html)
* Joshua Bloch, [Extra, Extra: Read All About It: Nearly All Binary Searches and Mergesorts are Broken](https://research.google/blog/extra-extra-read-all-about-it-nearly-all-binary-searches-and-mergesorts-are-broken/) (Google Research blog, 2006)
* Joshua Bloch and Neal Gafter, *Java Puzzlers: Traps, Pitfalls, and Corner Cases* (Addison-Wesley, 2005). The [book's site](http://www.javapuzzlers.com/) has the source code of every puzzle
