# 061 · Boxing and Overloading Traps

> The `?:` operator can throw a `NullPointerException` without a single dereference in sight, and `println` treats a `char[]` better than string concatenation does. Autoboxing made Java friendlier and its corner cases weirder.

**Since:** Java 9 · **Category:** [Puzzlers and Gotchas](../README.md#puzzlers-and-gotchas) · **Level:** Intermediate · **Verdict:** ✅ Production

## The puzzle

Fourteen lines. Each one either prints a value or reports an exception. Guess them all. Lines 2 and 3 are Joshua Bloch and Neal Gafter's "Dos Equis" (*Java Puzzlers*, Puzzle 8), line 8 is "The Case of the Confusing Constructor" (Puzzle 46) with a method instead of a constructor, and line 10 is "ABC" (Puzzle 12).

```java run
import java.util.*;

public class BoxingTraps {

    static void show(String label, Object value) {
        System.out.printf("%-36s %s%n", label, value);
    }

    static String pick(long x)    { return "pick(long)"; }
    static String pick(Integer x) { return "pick(Integer)"; }
    static String pick(int... x)  { return "pick(int...)"; }

    static String box(Object x)   { return "box(Object)"; }
    static String box(int... x)   { return "box(int...)"; }

    static String describe(Object o) { return "describe(Object)"; }
    static String describe(String s) { return "describe(String)"; }

    static String confusing(Object o)   { return "confusing(Object)"; }
    static String confusing(double[] d) { return "confusing(double[])"; }

    public static void main(String[] args) {
        Map<String, Integer> stock = new HashMap<>();
        boolean known = true;
        try {
            Integer apples = known ? stock.get("apples") : 0;
            show(" 1. known ? stock.get(\"apples\") : 0", apples);
        } catch (NullPointerException e) {
            show(" 1. known ? stock.get(\"apples\") : 0", e.getMessage());
        }

        char x = 'X';
        int i = 0;
        show(" 2. true ? x : 0", true ? x : 0);
        show(" 3. false ? i : x", false ? i : x);
        Object number = true ? Integer.valueOf(1) : Double.valueOf(2.0);
        show(" 4. true ? Integer(1) : Double(2.0)", number);

        show(" 5. pick(42)", pick(42));
        show(" 6. box(42)", box(42));
        show(" 7. describe(null)", describe(null));
        show(" 8. confusing(null)", confusing(null));

        char[] abc = {'a', 'b', 'c'};
        System.out.printf("%-36s ", " 9. System.out.println(abc)");
        System.out.println(abc);
        show("10. (\"\" + abc).startsWith(\"[C@\")", ("" + abc).startsWith("[C@"));

        Long small = 127L, smallToo = 127L;
        Long big = 128L, bigToo = 128L;
        show("11. Long 127 == Long 127", small == smallToo);
        show("12. Long 128 == Long 128", big == bigToo);
        show("13. Long.valueOf(0).equals(0)", Long.valueOf(0).equals(0));

        Map<Long, String> names = Map.of(1L, "one");
        show("14. names.get(1)", names.get(1));
    }
}
```

## The answer

```text output
 1. known ? stock.get("apples") : 0  Cannot invoke "java.lang.Integer.intValue()" because the return value of "java.util.Map.get(Object)" is null
 2. true ? x : 0                     X
 3. false ? i : x                    88
 4. true ? Integer(1) : Double(2.0)  1.0
 5. pick(42)                         pick(long)
 6. box(42)                          box(Object)
 7. describe(null)                   describe(String)
 8. confusing(null)                  confusing(double[])
 9. System.out.println(abc)          abc
10. ("" + abc).startsWith("[C@")     true
11. Long 127 == Long 127             true
12. Long 128 == Long 128             false
13. Long.valueOf(0).equals(0)        false
14. names.get(1)                     null
```

## Why

### Line 1: the conditional that unboxes

The type of `cond ? a : b` is decided by the *operand* types, not by the variable you assign it to. JLS §15.25 has a table for it, and the row for `Integer` and `int` says the result is `int`. So the compiler unboxes `stock.get("apples")` with a hidden `intValue()` call, the map returns `null`, and you get an NPE on a line with no visible dereference. The helpful NPE message (JEP 358) gives the game away by naming the method nobody wrote. The fix is to make both operands the same reference type: `known ? stock.get("apples") : Integer.valueOf(0)`, or better, `stock.getOrDefault("apples", 0)`.

### Lines 2 to 4: the conditional that promotes

Both operands are numeric, so the expression gets the binary numeric promotion treatment. Line 2: `0` is a constant that fits in a `char`, and JLS §15.25 lets a `char` operand absorb such a constant, so the type stays `char` and you see `X`. Line 3: `i` is a variable, not a constant, so the type is `int` and `'X'` prints as its code, `88`. Line 4: an `Integer` and a `Double` are unboxed and promoted to `double`, so you get `1.0` even though the "chosen" branch held an `Integer` and the target is `Object`. Mixing boxed numeric types in a conditional quietly converts the winner.

### Lines 5 to 8: overload resolution in three phases

JLS §15.12.2 looks for applicable methods in three phases and stops at the first phase that finds any:

1. **Strict invocation: identity and widening only, no boxing, no varargs.** Widening `int` to `long` is allowed, so `pick(long)` wins line 5, even though `pick(Integer)` looks like a more natural match.
2. **Loose invocation: boxing and unboxing are added, still no varargs.** `box(42)` has nothing in phase 1, but `42` boxes to `Integer`, which is an `Object`, so `box(Object)` wins line 6.
3. **Variable arity invocation: varargs at last.** Only if both earlier phases found nothing.

This ordering is backwards compatibility in action: code written before Java 5 had no boxing or varargs, and it had to keep calling the same methods afterwards.

Within a phase the *most specific* method wins. `null` fits both `Object` and `String`, but `String` is a subtype of `Object`, so `describe(String)` is more specific (line 7). An array type is also a subtype of `Object`, which is why `confusing(null)` picks `double[]` (line 8). Add a second, unrelated candidate and there is no most specific method any more:

```java compile-fail
public class Ambiguous {
    static String describe(String s)  { return "String"; }
    static String describe(Integer i) { return "Integer"; }

    public static void main(String[] args) {
        System.out.println(describe(null));
    }
}
```

```text compile-error
Ambiguous.java:6: error: reference to describe is ambiguous
        System.out.println(describe(null));
                           ^
  both method describe(String) in Ambiguous and method describe(Integer) in Ambiguous match
1 error
```

### Lines 9 and 10: char arrays are special, until they are not

`PrintStream` has a `println(char[])` overload that prints the characters, so line 9 shows `abc`. String concatenation has no such special case. It calls `String.valueOf(Object)`, which falls back to `Object.toString`: the type descriptor `[C`, an `@`, and the identity hash code in hex. (The program prints only the prefix, because the hash differs from run to run.) `System.out.println((Object) abc)` gets you the same garbage. Use `String.valueOf(abc)` or `new String(abc)` to turn it into text.

### Lines 11 to 14: boxed numbers are objects

`Long.valueOf` caches the values from -128 to 127, and autoboxing calls `valueOf`. So `==` compares references and happens to work for small numbers only, which is the most dangerous kind of working. [055](../06-hidden-corners/055-integer-cache-2-plus-2.md) covers the cache in detail. Lines 13 and 14 are the subtler trap: `equals` on wrapper types requires the *same* wrapper type. The literal `0` boxes to an `Integer`, and an `Integer` is never equal to a `Long`, so the lookup in a `Map<Long, String>` with an `int` key silently returns `null`. `Map.get` takes an `Object`, so the compiler cannot complain.

## Gotchas

* **Accidental boxing in loops is slow.** Effective Java's example is `Long sum = 0L; for (long i = 0; i < Integer.MAX_VALUE; i++) sum += i;`, which allocates a new `Long` on almost every iteration. One capital letter, an order of magnitude in run time.
* **`list.remove(1)` on a `List<Integer>`** calls `remove(int index)`, not `remove(Object)`, by the same phase 1 rule. See [062](062-collections-traps.md).
* **Unboxing in comparisons:** `Integer a = 1000, b = 1000; a <= b && b <= a && a != b` is `true`, because `<=` unboxes and `!=` compares references. That is Puzzle 32, "Curse of Looper".
* **A `null` `Boolean` in an `if`** throws an NPE too. Prefer `Boolean.TRUE.equals(flag)` when the value may be absent.

## How to stay safe

* Keep both branches of a conditional the same type. If one side is a reference that might be `null`, the other side must be a reference too.
* Compare boxed numbers with `equals`, or unbox explicitly, never with `==`.
* Match the key type exactly when looking things up: `names.get(1L)`, not `names.get(1)`. IDE inspections and Error Prone (`CollectionIncompatibleType`) catch the mismatch.
* Avoid overloading a method with parameters that are related by boxing or that both accept `null` (`Object`/`String`, `int`/`Integer`, `int`/`long`). Give the methods different names instead, as Effective Java recommends.
* Use primitives (`long`, `int`) for accumulators and counters.

## Related

* [055 · The Integer Cache and Making 2 + 2 = 5](../06-hidden-corners/055-integer-cache-2-plus-2.md)
* [062 · Collection Traps](062-collections-traps.md)
* [059 · Integer Overflow and Arithmetic Surprises](059-integer-overflow.md)
* [047 · Primitive Types in Patterns (Preview)](../05-modern-language/047-primitive-patterns.md)

## Sources

* [JLS §15.25: Conditional Operator ? :](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.25)
* [JLS §15.12.2: Compile-Time Step 2: Determine Method Signature](https://docs.oracle.com/javase/specs/jls/se25/html/jls-15.html#jls-15.12.2)
* [JEP 358: Helpful NullPointerExceptions](https://openjdk.org/jeps/358)
* Joshua Bloch and Neal Gafter, *Java Puzzlers: Traps, Pitfalls, and Corner Cases* (Addison-Wesley, 2005). The [book's site](http://www.javapuzzlers.com/) has the source code of every puzzle
