# 055 · The Integer Cache and Making 2 + 2 = 5

> Somewhere inside `java.lang.Integer` lives an array of 256 objects that every boxed small number comes from. Swap two of its slots and the whole JVM agrees that 2 + 2 is 5.

**Since:** Java 9 · **Category:** [Hidden Corners and Party Tricks](../README.md#hidden-corners-and-party-tricks) · **Level:** Advanced · **Verdict:** 🧪 Party trick

## The problem

This is the classic interview gotcha:

```java
Integer a = 127, b = 127;
Integer c = 128, d = 128;
System.out.println(a == b);   // true
System.out.println(c == d);   // false
```

Autoboxing calls `Integer.valueOf`, and `valueOf` hands out *shared* objects for small values. The JLS (§5.1.7) requires that boxing any `int` between -128 and 127 always yields the same object, so `==` happens to work for 127 and stops working for 128. Use `equals` and the problem disappears; the [boxing and overloading puzzlers](../07-puzzlers/061-boxing-overloading.md) cover the everyday traps.

This doc is about the less responsible question: if all boxed 4s are one object sitting in one array, what happens when you change the array?

## The trick

The shared objects live in a private nested class, `Integer.IntegerCache`, in a static array called `cache`. Slot `i + 128` holds the `Integer` for `i`. With deep reflection you can fetch the array and put the `Integer` 5 into the slot for 4:

```java
Field cacheField = Class.forName("java.lang.Integer$IntegerCache").getDeclaredField("cache");
cacheField.setAccessible(true);
Integer[] cache = (Integer[]) cacheField.get(null);
cache[4 + 128] = cache[5 + 128];
```

From then on, every boxing of 4 anywhere in the JVM returns the object whose value is 5. Since JDK 16 (JEP 396), and with no escape hatch since JDK 17 (JEP 403), `java.base` is strongly encapsulated, so the launcher needs `--add-opens java.base/java.lang=ALL-UNNAMED`. Without it `setAccessible` throws `InaccessibleObjectException`.

## Full example

Run on JDK 25 with `--add-opens java.base/java.lang=ALL-UNNAMED`, with stderr included in the output:

```java run stderr args="--add-opens java.base/java.lang=ALL-UNNAMED"
import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

public class TwoPlusTwo {

    public static void main(String[] args) throws Exception {
        Integer small1 = 127, small2 = 127, big1 = 128, big2 = 128;
        System.out.println("127 == 127: " + (small1 == small2) + ", 128 == 128: " + (big1 == big2));

        Field cacheField = Class.forName("java.lang.Integer$IntegerCache").getDeclaredField("cache");
        System.out.println("the field: " + cacheField);
        cacheField.setAccessible(true);

        Integer[] cache = (Integer[]) cacheField.get(null);
        int offset = -cache[0];                  // cache[0] is the Integer -128
        cache[4 + offset] = cache[5 + offset];   // the slot for 4 now holds the 5 object

        System.out.println("2 + 2 = " + (2 + 2));          // plain int arithmetic, no boxing
        System.out.printf("2 + 2 = %d%n", 2 + 2);          // printf boxes its arguments

        Integer two = 2;
        Integer four = two + two;                // unbox, add, box again via valueOf(4)
        System.out.println("Integer four = " + four);
        System.out.println("four == 4: " + (four == 4) + ", four.equals(4): " + four.equals(4));

        System.out.println("List.of(1, 2, 3, 4, 5) = " + List.of(1, 2, 3, 4, 5));
        System.out.println("boxed range 1..5 = "
                + IntStream.rangeClosed(1, 5).boxed().collect(Collectors.toList()));

        Map<Integer, String> names = new TreeMap<>();
        names.put(4, "four");
        names.put(5, "five");
        System.out.println("map = " + names + ", size " + names.size() + ", get(4) = " + names.get(4));
    }
}
```

```text output
127 == 127: true, 128 == 128: false
the field: static final java.lang.Integer[] java.lang.Integer$IntegerCache.cache
2 + 2 = 4
2 + 2 = 5
Integer four = 5
four == 4: false, four.equals(4): true
List.of(1, 2, 3, 4, 5) = [1, 2, 3, 5, 5]
boxed range 1..5 = [1, 2, 3, 5, 5]
map = {5=five}, size 1, get(4) = five
```

The same program on JDK 27, same flag, stderr included again:

```java run jdk=27 stderr args="--add-opens java.base/java.lang=ALL-UNNAMED"
import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

public class TwoPlusTwo {

    public static void main(String[] args) throws Exception {
        Integer small1 = 127, small2 = 127, big1 = 128, big2 = 128;
        System.out.println("127 == 127: " + (small1 == small2) + ", 128 == 128: " + (big1 == big2));

        Field cacheField = Class.forName("java.lang.Integer$IntegerCache").getDeclaredField("cache");
        System.out.println("the field: " + cacheField);
        cacheField.setAccessible(true);

        Integer[] cache = (Integer[]) cacheField.get(null);
        int offset = -cache[0];                  // cache[0] is the Integer -128
        cache[4 + offset] = cache[5 + offset];   // the slot for 4 now holds the 5 object

        System.out.println("2 + 2 = " + (2 + 2));          // plain int arithmetic, no boxing
        System.out.printf("2 + 2 = %d%n", 2 + 2);          // printf boxes its arguments

        Integer two = 2;
        Integer four = two + two;                // unbox, add, box again via valueOf(4)
        System.out.println("Integer four = " + four);
        System.out.println("four == 4: " + (four == 4) + ", four.equals(4): " + four.equals(4));

        System.out.println("List.of(1, 2, 3, 4, 5) = " + List.of(1, 2, 3, 4, 5));
        System.out.println("boxed range 1..5 = "
                + IntStream.rangeClosed(1, 5).boxed().collect(Collectors.toList()));

        Map<Integer, String> names = new TreeMap<>();
        names.put(4, "four");
        names.put(5, "five");
        System.out.println("map = " + names + ", size " + names.size() + ", get(4) = " + names.get(4));
    }
}
```

```text output
127 == 127: true, 128 == 128: false
the field: static java.lang.Integer[] java.lang.Integer$IntegerCache.cache
2 + 2 = 4
2 + 2 = 5
Integer four = 5
four == 4: false, four.equals(4): true
List.of(1, 2, 3, 4, 5) = [1, 2, 3, 5, 5]
boxed range 1..5 = [1, 2, 3, 5, 5]
map = {5=five}, size 1, get(4) = five
```

Without the flag, `setAccessible` fails on both versions (JDK 25 shown, stack trace trimmed):

```shell
$ java TwoPlusTwo.java
```

```text
Exception in thread "main" java.lang.reflect.InaccessibleObjectException: Unable to make field static final java.lang.Integer[] java.lang.Integer$IntegerCache.cache accessible: module java.base does not "opens java.lang" to unnamed module @6c9f5c0d
	at java.base/java.lang.reflect.AccessibleObject.throwInaccessibleObjectException(AccessibleObject.java:353)
	...
	at TwoPlusTwo.main(TwoPlusTwo.java:6)
```

## How it works

* **Boxing is a method call.** `Integer four = two + two` compiles to `Integer.valueOf(two.intValue() + two.intValue())`, and `valueOf(i)` returns `IntegerCache.cache[i + 128]` for small `i`. After the swap, that slot holds the object whose `value` field is 5.
* **Only boxing is affected.** `"2 + 2 = " + (2 + 2)` concatenates an `int`, so it prints 4. `printf` takes `Object...` varargs, so its 4 is boxed and prints 5. Same expression, two answers, depending on whether a box was involved.
* **`==` and `equals` now disagree in the other direction.** `four == 4` unboxes `four` to 5 and compares ints: false. `four.equals(4)` boxes the 4 into the 5 object and compares 5 with 5: true.
* **Collections see it too.** `List.of(1, 2, 3, 4, 5)` and `IntStream.boxed()` both box through `valueOf`, so they contain two fives. The `TreeMap` is the cruelest: `put(4, "four")` stores the key 5, `put(5, "five")` then overwrites it, and `get(4)` returns `"five"`.
* **The field printout is the only difference between the two JDKs.** On JDK 25 the cache is `static final Integer[] cache`. On JDK 27 it is plain `static Integer[] cache`: the source shows it is still annotated `@Stable` (a JDK-internal annotation), and the initialization moved into a method marked `@AOTRuntimeSetup`.
* **JEP 500 does not notice.** JDK 26 and later warn when deep reflection *writes a final field* ([057](057-final-isnt-final.md)). This hack only *reads* the `cache` field and then writes an array element. Array elements are never final, so stderr stays empty on JDK 25 and on JDK 27. The only guard is the `--add-opens` from JDK 16 and 17 (JEPs 396 and 403).

The version of the trick that does write a final field is mutating `Integer.value` itself. That one is caught on JDK 27:

```java
Field value = Integer.class.getDeclaredField("value");   // private final int value
value.setAccessible(true);
value.setInt(Integer.valueOf(7), 8);                       // a real final field write
System.out.println("7 = " + Integer.valueOf(7));
```

```text
WARNING: Final field value in class java.lang.Integer has been mutated reflectively by class SevenIsEight in unnamed module @4d826d77 (file:/.../SevenIsEight.java)
WARNING: Use --enable-final-field-mutation=ALL-UNNAMED to avoid a warning
WARNING: Mutating final fields will be blocked in a future release unless final field mutation is enabled
7 = 8
```

(Real output of that snippet in a `SevenIsEight` class, run with the same `--add-opens` on JDK 27, path shortened. On JDK 25 it prints `7 = 8` with no warning.)

### Growing the cache, legitimately

The upper bound of the cache is configurable. `-XX:AutoBoxCacheMax=1000` (or `-Djava.lang.Integer.IntegerCache.high=1000`, which behaves the same on JDK 25 and 27) makes `valueOf` share objects up to 1000:

```java run args="-XX:AutoBoxCacheMax=1000"
public class BiggerCache {
    public static void main(String[] args) {
        Integer a = 1000, b = 1000, c = 1001, d = 1001;
        System.out.println("1000 == 1000: " + (a == b));
        System.out.println("1001 == 1001: " + (c == d));

        Long x = 127L, y = 127L, z = 128L, w = 128L;
        System.out.println("Long 127: " + (x == y) + ", Long 128: " + (z == w));

        System.out.println("property visible? " + System.getProperty("java.lang.Integer.IntegerCache.high"));
    }
}
```

```text output
1000 == 1000: true
1001 == 1001: false
Long 127: true, Long 128: false
property visible? null
```

Only `Integer` is configurable. `Long`, `Short` and `Byte` always cache exactly -128 to 127, which is why `Long 128` stays false. And `java.lang.Integer.IntegerCache.high` is on the JDK's short list of private system properties that `System` masks out of `System.getProperties()`, so code cannot even see that the cache was grown.

## Gotchas

* **It is global and permanent.** There is one cache per JVM. Every library, every thread and every `Map<Integer, ...>` in the process now believes 4 is 5. There is no undo short of swapping the slots back, and code that ran in between already saw the lie.
* **The JIT is allowed to ignore you.** The `cache` field is `@Stable` on both JDKs, and the `Stable` Javadoc says the components of a stable array are stable variables too: once a slot holds a non-null value, "the VM is permitted to assume that no more significant changes will occur". Compiled code that folded the old slot keeps using it. The demo works because it runs before anything is hot.
* **`==` on boxes is wrong even without the hack.** The cache bounds are a JVM option, so `a == b` for `Integer` can change behavior between two deployments of the same jar.
* **Don't grow the cache as a performance fix** without measuring. A larger cache costs memory at startup for every JVM, and escape analysis often removes short-lived boxes anyway.

## When to use it (and when not to)

The `--add-opens` hack is strictly for lightning talks and for explaining, very memorably, why `Integer` identity is meaningless. Never in code that anything else runs in, including tests: a test that swaps cache slots poisons every other test in the same JVM.

`-XX:AutoBoxCacheMax` is a real, supported HotSpot flag, but its legitimate use is narrow: a hot path that boxes many values in a known small range and where profiling shows the allocations matter. If you find yourself relying on it for `==` to work, fix the `==`.

## Related

* [057 · final Isn't Final (Yet)](057-final-isnt-final.md), the hack that JEP 500 *does* catch
* [061 · Boxing and Overloading Traps](../07-puzzlers/061-boxing-overloading.md)
* [056 · "Aa" Equals "BB" (in hashCode)](056-hashcode-collisions.md), another way to make maps misbehave
* [086 · MethodHandles and LambdaMetafactory: Reflection at Full Speed](../10-jvm-performance/086-methodhandles-lambdametafactory.md)

## Sources

* [JLS §5.1.7: Boxing Conversion](https://docs.oracle.com/javase/specs/jls/se25/html/jls-5.html#jls-5.1.7)
* [`Integer.valueOf(int)` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Integer.html#valueOf(int))
* [JEP 403: Strongly Encapsulate JDK Internals](https://openjdk.org/jeps/403)
* [JEP 500: Prepare to Make Final Mean Final](https://openjdk.org/jeps/500)
